// Updates & build: the signed release feed (ed25519 checked in the Rust shell with the built-in key, then the package's
// SHA-256 from the signed manifest), offline update files, roll back, and the game build's state.
import { call, on, rust } from '../bridge.js';
import { esc, icons, status, toast, modal, confirmAction, pct, errorText } from '../ui.js';
import { register, currentId, go } from '../nav.js';
import { app } from '../state.js';
import { runBuild } from '../main.js';

const newer = (a, b) => { const p = (v) => String(v).split(/[.-]/).slice(0, 3).map((x) => parseInt(x, 10) || 0); const x = p(a), y = p(b); for (let i = 0; i < 3; i++) if (x[i] !== y[i]) return x[i] > y[i]; return false; };
const installed = () => String(app.hello?.version || app.info?.version || '0').replace(/-.*/, '');

export async function checkForUpdates({ quiet = false } = {}) {
  let r;
  try { r = await call('update.check', {}, { timeout: 30000 }); }
  catch (e) { if (!quiet) toast('Could not check for updates: ' + errorText(e), 'warn', 8000); return null; }
  const valid = await rust('verify_manifest', { text: r.text, signature: r.signature }).catch(() => false);
  if (!valid) { if (!quiet) toast('The update feed\'s signature is not valid. Nothing was downloaded.', 'bad', 9000); return null; }
  const m = r.manifest;
  if (m.product !== 'CoastLink' || !m.package?.url || !/^[0-9a-f]{64}$/i.test(m.package.sha256 || '')) { if (!quiet) toast('The update feed is incomplete.', 'bad'); return null; }
  app.update = { manifest: m, newer: newer(m.version, installed()) };
  if (app.update.newer) toast(`CoastLink ${m.version} is available (Updates & build).`, 'ok', 9000);
  else if (!quiet) toast(`You're up to date (${installed()}).`, 'ok');
  if (currentId() === 'updates') go('updates', { push: false });
  return app.update;
}

async function afterApply(r) {
  if (!r.changed) { toast('That version is already installed.', 'info'); return; }
  toast(`Installed ${r.version}. A backup of the replaced files was kept (${r.backup}).`, 'ok', 9000);
  if (r.restart_app) {
    if (await modal({ title: 'Restart CoastLink', body: 'The update includes a new CoastLink app. It restarts now to finish.', actions: [{ label: 'Restart now', value: true, kind: 'primary' }] }) !== false) {
      await rust('self_update', { newExe: app.info.repo + '\\CoastLink.exe.new' });
    }
  } else if (r.restart_backend) await rust('sidecar_restart');
  setTimeout(() => location.reload(), 600);
}

register({
  id: 'updates', title: 'Updates & build', icon: 'updates',
  leave() { this.off?.(); },
  async render(root) {
    const [cfg, progress, backups] = await Promise.all([call('update.config'), call('build.progress'), call('update.backups').catch(() => [])]);
    const u = app.update;
    const ver = installed();
    root.innerHTML = `<header class="page-head"><div><h1 style="font-size:34px">Updates & build</h1><p>Everyone in a match needs the same CoastLink version.</p></div></header>
    <div class="fill" style="display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:14px">
      <div class="col" style="gap:14px">
        <section class="card" aria-label="Version"><div class="row" style="justify-content:space-between">
          <div class="col" style="gap:2px"><span class="label">Installed</span><span style="font:700 30px var(--head)">${esc(ver)}</span></div>
          ${u?.newer ? `<span class="pill">${esc(u.manifest.version)} available</span>` : u ? status('ok', 'Up to date') : ''}</div>
          <div class="row">${u?.newer ? `<button class="btn primary grow" id="install">Download and install ${esc(u.manifest.version)}</button>` : '<button class="btn primary grow" id="check">Check for updates</button>'}
            <button class="btn grow" id="file">Install update file…</button></div>
          <div id="dl" class="col" hidden><div class="bar"><i id="dl-bar"></i></div><span class="small faint" id="dl-text"></span></div>
          <details><summary class="small" style="cursor:pointer;min-height:30px">Update settings</summary><div class="col" style="margin-top:8px">
            <label class="label" for="feed-repo">Release repository (owner/name on GitHub)</label><input class="input mono" id="feed-repo" value="${esc(cfg.repo || '')}" placeholder="owner/coastlink">
            <label class="check">Check for updates when CoastLink starts<input type="checkbox" id="feed-auto" ${cfg.check_on_launch ? 'checked' : ''}></label>
            <button class="btn" id="feed-save">Save update settings</button></div></details>
        </section>
        <section class="card fill" aria-label="What's new"><h2>${u ? `What's new in ${esc(u.manifest.version)}` : `What's new in ${esc(ver)}`}</h2>
          <ul class="col" style="margin:0;padding-left:20px;gap:8px">${(u?.manifest.notes || ['A native CoastLink app: no console or PowerShell windows.', 'GameCube adapters in PC mode (Mayflash) give each controller its own player.', 'Online refuses to pair different CoastLink versions and says so.', 'Audio output device, mute in background, and volume that changes mid-match.']).map((n) => `<li>${esc(n)}</li>`).join('')}</ul>
          ${backups.length ? `<div class="row"><select class="input grow" id="backup">${backups.map((b) => `<option value="${esc(b.backup)}">${b.from ? `Back to ${esc(b.from)}` : esc(b.backup)}${b.to ? ` (before ${esc(b.to)})` : ''}</option>`).join('')}</select><button class="btn" id="rollback">Roll back</button></div>` : ''}
        </section>
      </div>
      <div class="col" style="gap:14px">
        <section class="card" aria-label="Build status"><div class="row" style="justify-content:space-between"><h2>Game build</h2><span class="small muted">${esc(app.hello?.status?.game_version || '')} · rollback</span></div>
          <div class="col" style="gap:6px"><div class="row small" style="justify-content:space-between"><span>Main game</span><span class="mono">${progress.main} / ${progress.main_total}</span></div><div class="bar blue"><i style="width:${pct(progress.main, progress.main_total)}%"></i></div></div>
          <div class="col" style="gap:6px"><div class="row small" style="justify-content:space-between"><span>Fighter modules</span><span class="mono">${progress.modules_done} / ${progress.modules_total}</span></div><div class="bar blue"><i style="width:${pct(progress.modules_done, progress.modules_total)}%"></i></div></div>
          <div class="col" style="gap:6px"><div class="row small" style="justify-content:space-between"><span>Linking & checks</span><span>${progress.finished ? 'done' : esc(progress.stage)}</span></div><div class="bar blue"><i style="width:${progress.finished ? 100 : 0}%"></i></div></div>
          <div class="row small" style="justify-content:space-between"><span class="muted">Disk used</span><span id="disk">…</span></div></section>
        <section class="card fill" aria-label="Maintenance"><h2>Maintenance</h2>
          <button class="btn" style="justify-content:space-between" id="resume">Resume or repair build ${icons.arrow}</button>
          <button class="btn" style="justify-content:space-between" id="clean">Clean old normal-build files ${icons.trash}</button>
          <button class="btn" style="justify-content:space-between" id="open">Open install folder ${icons.folder}</button>
          <div class="divider"></div>
          <div class="row" style="justify-content:space-between"><span style="font-weight:600">Game save</span><span class="small faint">Everyone can use the same save (a JKSV backup)</span></div>
          <div class="row"><button class="btn grow" id="save-import">Import save file…</button><button class="btn" id="save-folder">Import a folder…</button></div>
          <div class="row" id="save-restore-row" hidden><select class="input grow" id="save-backup"></select><button class="btn" id="save-restore">Put back</button></div></section>
      </div></div>`;
    call('build.size', {}, { timeout: 120000 }).then((r) => { const d = root.querySelector('#disk'); if (d) d.textContent = `${r.gb} GB`; }).catch(() => {});
    this.off = on('download', (m) => { const box = root.querySelector('#dl'); if (!box) return; box.hidden = false; root.querySelector('#dl-bar').style.width = pct(m.done, m.total) + '%'; root.querySelector('#dl-text').textContent = `${(m.done / 1048576).toFixed(1)} of ${(m.total / 1048576).toFixed(1)} MB`; });
    root.querySelector('#check')?.addEventListener('click', () => checkForUpdates());
    root.querySelector('#install')?.addEventListener('click', async () => {
      if (app.gameRunning) { toast('Close the game before updating.', 'warn'); return; }
      const p = u.manifest.package;
      try {
        const file = await call('update.download', { url: p.url, sha256: p.sha256, size: p.size, name: p.name }, { timeout: 0 });
        root.querySelector('#dl-text').textContent = 'Verified. Installing…';
        await afterApply(await call('update.apply', { path: file.path, sha256: p.sha256 }, { timeout: 120000 }));
      } catch (e) { toast(errorText(e), 'bad', 10000); }
    });
    root.querySelector('#file').onclick = async () => {
      const path = await window.__TAURI__.dialog.open({ filters: [{ name: 'CoastLink update', extensions: ['zip'] }] });
      if (!path) return;
      try {
        const proof = await rust('verify_update_file', { path });
        await afterApply(await call('update.apply', { path: proof.path, sha256: proof.sha256 }, { timeout: 120000 }));
      } catch (e) { toast(errorText(e), 'bad', 10000); }
    };
    root.querySelector('#rollback')?.addEventListener('click', async () => {
      const name = root.querySelector('#backup').value;
      if (!await confirmAction('Roll back?', `The files the update ${name} replaced are put back.`, 'Roll back')) return;
      try { const r = await call('update.rollback', { backup: name }); await afterApply({ ...r, changed: r.files || 1, version: r.restored || 'the previous version', backup: name }); } catch (e) { toast(errorText(e), 'bad'); }
    });
    root.querySelector('#feed-save').onclick = async () => {
      try { await call('update.config', { settings: { repo: root.querySelector('#feed-repo').value, check_on_launch: root.querySelector('#feed-auto').checked } }); toast('Update settings saved.', 'ok'); }
      catch (e) { toast(errorText(e), 'bad'); }
    };
    root.querySelector('#resume').onclick = () => runBuild();
    root.querySelector('#clean').onclick = async () => {
      try {
        const dry = await call('cleanup', { dry_run: true }, { timeout: 120000 });
        const list = dry.would_remove || [];
        if (!list.length) { toast('Nothing to clean.', 'ok'); return; }
        if (!await confirmAction('Clean old files?', `${list.length} item(s) from the old normal build can go. The rollback build, your game data and saves stay.`, 'Clean')) return;
        await call('cleanup', {}, { timeout: 600000 }); toast('Cleaned.', 'ok');
      } catch (e) { toast(errorText(e), 'bad'); }
    };
    root.querySelector('#open').onclick = () => rust('open_path', { path: app.info.repo });
    // ---- game save: import a JKSV backup the player has (zip, folder or system_data.bin); the old save is kept and can be put back
    const loadSaveBackups = () => call('save.backups').then((rows) => {
      const row = root.querySelector('#save-restore-row');
      if (!row) return;
      row.hidden = !rows.length;
      root.querySelector('#save-backup').innerHTML = rows.map((b) => `<option value="${esc(b.name)}">Save from ${esc(b.name.replace(/^save-(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2}).*$/, '$1-$2-$3 $4:$5'))} (${b.mb} MB)</option>`).join('');
    }).catch(() => {});
    const importSave = async (path) => {
      if (!path) return;
      if (app.gameRunning) { toast('Close the game first: it writes its save while it runs.', 'warn'); return; }
      if (!await confirmAction('Replace your save?', 'Your current save is kept as a backup and can be put back here. Spirit Board (BCAT) data is not used by this version of the game.', 'Import')) return;
      try { const r = await call('save.import', { path }, { timeout: 120000 }); toast(`Save imported (${r.files} file(s)). It's used the next time the game starts.`, 'ok', 8000); loadSaveBackups(); }
      catch (e) { toast(errorText(e), 'bad', 10000); }
    };
    root.querySelector('#save-import').onclick = async () => importSave(await window.__TAURI__.dialog.open({ filters: [{ name: 'Save backup', extensions: ['zip', 'bin'] }] }));
    root.querySelector('#save-folder').onclick = async () => importSave(await window.__TAURI__.dialog.open({ directory: true }));
    root.querySelector('#save-restore').onclick = async () => {
      const name = root.querySelector('#save-backup').value;
      if (!name || !await confirmAction('Put this save back?', 'The save you have now is kept as a backup too.', 'Put back')) return;
      try { await call('save.restore', { name }, { timeout: 120000 }); toast('Save put back.', 'ok'); loadSaveBackups(); } catch (e) { toast(errorText(e), 'bad'); }
    };
    loadSaveBackups();
  },
});
