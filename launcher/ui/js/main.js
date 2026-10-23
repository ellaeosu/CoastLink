// Boot: the private Python (first run), the backend, the first-run setup wizard, the sidebar status, update check on launch.
import { rust, call, on } from './bridge.js';
import { esc, $, icons, status, toast, modal, pct, errorText } from './ui.js';
import * as nav from './nav.js';
import { app } from './state.js';
import './screens/play.js';
import './screens/online.js';
import './screens/controllers.js';
import './screens/display.js';
import './screens/audio.js';
import './screens/session.js';
import './screens/updates.js';

// ---------------------------------------------------------------- sidebar status
export async function refreshStatus() {
  try {
    const s = await call('status', {}, { timeout: 20000 });
    app.status = s;
    const line = $('#side-status-line'), detail = $('#side-status-detail');
    const game = s.status.game_version ? `Game ${s.status.game_version}` : 'Game not built';
    if (s.game_running) { line.outerHTML = `<span id="side-status-line">${status('ok', 'Game running')}</span>`; }
    else if (s.build_running) { line.outerHTML = `<span id="side-status-line">${status('warn', 'Building')}</span>`; }
    else if (s.status.ready) { line.outerHTML = `<span id="side-status-line">${status('ok', 'Ready to play')}</span>`; }
    else { line.outerHTML = `<span id="side-status-line">${status('bad', 'Setup needed')}</span>`; }
    detail.textContent = `${game} · ${s.status.ready ? 'rollback build OK' : 'build incomplete'}`;
  } catch (e) { /* the backend restarts itself; the next poll tries again */ }
}

// ---------------------------------------------------------------- game process events (any screen)
on('game', (m) => {
  app.gameLines.push(m.line);
  if (app.gameLines.length > 400) app.gameLines.shift();
  const room = /ROOM CODE\s+([A-Za-z0-9]{5}-[A-Za-z0-9]{5})/.exec(m.line);
  if (room) { app.roomCode = room[1]; toast(`Hosting. Give your friend room code ${room[1]}.`, 'ok', 9000); }
  if (/VERSION MISMATCH/.test(m.line)) app.versionMismatch = true;
  if (m.startup) app.startup = m.startup;
});
on('game_end', (m) => {
  app.gameRunning = false; app.startup = '';
  if (m.code && m.code !== 0) {
    const last = app.gameLines.filter((l) => /error|fatal|stopped|unavailable|Coastlink/i.test(l)).slice(-3).join('\n');
    toast(`The game closed with an error (exit ${m.code}). ${last ? last.slice(0, 220) : 'See Session & Verify > Open logs.'}`, 'bad', 12000);
  }
  refreshStatus();
});
on('backend-exit', async () => {
  toast('The CoastLink backend stopped; starting it again.', 'warn');
  try { await rust('sidecar_restart'); } catch (e) { toast(errorText(e), 'bad'); }
});

// ---------------------------------------------------------------- first-run setup
const setupHtml = (step, body) => `<div class="wizard" role="dialog" aria-label="Set up CoastLink">
  <div class="row"><div class="brand-mark" aria-hidden="true"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#000" stroke-width="2.5" stroke-linecap="round"><path d="M3 15c3-4 6-4 9 0s6 4 9 0"/><path d="M3 9c3-4 6-4 9 0s6 4 9 0"/></svg></div>
  <h1>Set up CoastLink</h1></div>
  <div class="steps" aria-hidden="true">${[0, 1, 2].map((i) => `<span class="${i < step ? 'done' : i === step ? 'now' : ''}"></span>`).join('')}</div>
  ${body}</div>`;

function showSetup(html) {
  let box = $('#setup');
  if (!box) { box = document.createElement('div'); box.id = 'setup'; document.body.appendChild(box); }
  box.innerHTML = html;
  (box.querySelector('[autofocus]') || box.querySelector('button'))?.focus();
  return box;
}
const closeSetup = () => $('#setup')?.remove();

async function setupPython() {
  return new Promise((resolve) => {
    const box = showSetup(setupHtml(0, `<div class="card"><h2>Getting CoastLink's own Python</h2>
      <p class="muted" style="margin:0">CoastLink runs its tools with a private copy of Python from python.org (about 11 MB, checked against a fixed SHA-256). Nothing else on this PC changes.</p>
      <div class="bar"><i id="py-bar" style="width:0%"></i></div><span class="small faint" id="py-text">Starting…</span>
      <div class="row"><button class="btn primary" id="py-retry" hidden>Try again</button></div></div>`));
    const off = on('bootstrap', (p) => {
      $('#py-bar').style.width = pct(p.done, p.total) + '%';
      $('#py-text').textContent = `${p.stage}: ${(p.done / 1048576).toFixed(1)} MB${p.total ? ' of ' + (p.total / 1048576).toFixed(1) + ' MB' : ''}`;
    });
    const go = async () => {
      $('#py-retry').hidden = true;
      try { await rust('bootstrap_python'); off(); resolve(); }
      catch (e) { $('#py-text').textContent = 'Could not get Python: ' + errorText(e) + '. Check the internet connection.'; $('#py-retry').hidden = false; }
    };
    box.querySelector('#py-retry').onclick = go;
    go();
  });
}

function fileRow(id, label, value, hint) {
  return `<div class="file-row"><span>${esc(label)}</span><span class="path" id="${id}-path" title="${esc(value || '')}">${esc(value || hint)}</span>
    <button class="btn" data-pick="${id}">Choose…</button></div>`;
}

async function setupWizard(hello) {
  let found = {};
  try { found = await call('build.discover', {}, { timeout: 30000 }); } catch (e) { found = { notes: [errorText(e)] }; }
  const pick = { base: found.base, update: found.update, keys: found.keys, dlc_folder: found.dlc_folder || '' };
  const render = () => {
    showSetup(setupHtml(1, `<div class="card"><h2>Your game files</h2>
      <p class="muted" style="margin:0">CoastLink builds a PC version of Smash Ultimate from your own copy. It found these on this PC (from Ryujinx). Nothing is uploaded or downloaded, and no key values are read by CoastLink.</p>
      ${fileRow('base', 'Base game', pick.base, 'Not found — choose the .nsp / .xci')}
      ${fileRow('update', 'Update 13.0.4', pick.update, 'Not found — choose the 13.0.4 update .nsp')}
      ${fileRow('keys', 'prod.keys', pick.keys, 'Not found — choose prod.keys')}
      ${fileRow('dlc_folder', 'DLC folder', pick.dlc_folder, found.dlc_files?.length ? `${found.dlc_files.length} DLC file(s) from Ryujinx` : 'Optional')}
      ${(found.notes || []).map((n) => `<div class="small">${status('warn', n)}</div>`).join('')}
      <div class="row" style="justify-content:space-between"><span class="small faint">The first build takes a few hours and about 35 GB. You can pause it and resume later.</span>
      <button class="btn primary big" id="start-build" ${pick.base && pick.update && pick.keys ? '' : 'disabled'} autofocus>Start the build</button></div></div>`));
    document.querySelectorAll('[data-pick]').forEach((b) => b.onclick = async () => {
      const id = b.dataset.pick;
      const res = await window.__TAURI__.dialog.open(id === 'dlc_folder' ? { directory: true } :
        { filters: id === 'keys' ? [{ name: 'Keys', extensions: ['keys'] }] : [{ name: 'Switch packages', extensions: ['nsp', 'xci', 'nsz', 'xcz'] }] });
      if (res) { pick[id] = res; render(); }
    });
    $('#start-build').onclick = () => runBuild(pick);
  };
  render();
}

export async function runBuild(pick = {}) {
  try { await call('build.start', { ...pick, jobs: 4 }); }
  catch (e) { if (!/already running/.test(errorText(e))) { toast(errorText(e), 'bad', 9000); return; } }
  buildScreen();
}

function eta(started, done, total) {
  if (!done || done >= total) return '';
  const left = ((Date.now() - started) / done) * (total - done) / 60000;
  return left > 90 ? `about ${Math.round(left / 60)} h left` : `about ${Math.max(1, Math.round(left))} min left`;
}

function buildScreen() {
  const log = [];
  const started = Date.now();
  let first = null, stopped = false, timer;
  showSetup(setupHtml(2, `<div class="card"><div class="row" style="justify-content:space-between"><h2 id="b-stage">Building</h2><span class="small faint" id="b-eta"></span></div>
    <div class="col"><div class="row small" style="justify-content:space-between"><span>Main game</span><span class="mono" id="b-main"></span></div><div class="bar"><i id="b-main-bar"></i></div></div>
    <div class="col"><div class="row small" style="justify-content:space-between"><span>Fighter modules</span><span class="mono" id="b-mod"></span></div><div class="bar"><i id="b-mod-bar"></i></div></div>
    <div class="log" id="b-log" aria-label="Build output"></div>
    <div class="row" style="justify-content:space-between"><span class="small faint">You can close CoastLink; the build keeps its progress and resumes next time.</span>
    <button class="btn" id="b-pause" autofocus>Pause</button></div></div>`));
  const tick = async () => {
    try {
      const p = await call('build.progress');
      if (first === null) first = p.main + p.modules_done;
      $('#b-stage').textContent = `${p.stage} (step ${p.step} of ${p.steps})`;
      $('#b-main').textContent = `${p.main} / ${p.main_total}`; $('#b-main-bar').style.width = pct(p.main, p.main_total) + '%';
      $('#b-mod').textContent = `${p.modules_done} / ${p.modules_total || '?'}`; $('#b-mod-bar').style.width = pct(p.modules_done, p.modules_total) + '%';
      const total = p.main_total + (p.modules_total || 100);
      $('#b-eta').textContent = eta(started, p.main + p.modules_done - first, total - first);
      if (p.finished && !p.running) finishBuild(true);
    } catch { /* keep polling */ }
  };
  timer = setInterval(tick, 3000); tick();
  const offLine = on('build', (m) => { log.push(m.line); if (log.length > 200) log.shift(); const el = $('#b-log'); if (el) { el.textContent = log.join('\n'); el.scrollTop = el.scrollHeight; } });
  const offEnd = on('build_end', (m) => { if (!stopped) finishBuild(m.code === 0, log); });
  $('#b-pause').onclick = async () => {
    if (!stopped) { stopped = true; await call('build.stop'); $('#b-pause').textContent = 'Resume'; $('#b-stage').textContent = 'Paused'; }
    else { stopped = false; $('#b-pause').textContent = 'Pause'; await call('build.start', { jobs: 4 }).catch((e) => toast(errorText(e), 'bad')); }
  };
  function finishBuild(ok, lines = log) {
    clearInterval(timer); offLine(); offEnd();
    if (ok) {
      showSetup(setupHtml(3, `<div class="card"><h2>${icons.ok} Build finished</h2><p class="muted" style="margin:0">Start with an offline run: the first start prepares the shaders for your graphics card (a few minutes, once). After that, online matches start without stutter.</p>
        <div class="row"><button class="btn primary big" id="b-done" autofocus>Open CoastLink</button></div></div>`));
      $('#b-done').onclick = () => { closeSetup(); refreshStatus(); nav.go('play'); };
    } else {
      const reason = lines.filter((l) => /error|failed|stopped|missing|not found|disk/i.test(l)).slice(-4).join('\n') || lines.slice(-4).join('\n');
      showSetup(setupHtml(2, `<div class="card"><h2>${status('bad', 'The build stopped')}</h2>
        <p class="muted" style="margin:0">Your progress is kept. Fix the problem below, then resume.</p><pre class="log" style="height:auto;max-height:200px">${esc(reason || 'No details.')}</pre>
        <div class="row"><button class="btn primary" id="b-resume" autofocus>Resume the build</button><button class="btn" id="b-later">Later</button></div></div>`));
      $('#b-resume').onclick = () => runBuild();
      $('#b-later').onclick = () => { closeSetup(); nav.go('updates'); };
    }
  }
}

// ---------------------------------------------------------------- boot
async function waitForBackend() {
  for (let i = 0; i < 40; i++) {
    try { return await call('hello', {}, { timeout: 8000 }); } catch { await new Promise((r) => setTimeout(r, 500)); }
  }
  throw new Error('The CoastLink backend did not start.');
}

async function boot() {
  nav.installNavigation();
  const info = await rust('app_info');
  app.info = info;
  $('#brand-version').textContent = `${info.version} rollback`;
  if (!info.python) await setupPython();
  let hello;
  try { hello = await waitForBackend(); }
  catch (e) { await modal({ title: 'CoastLink could not start', body: errorText(e) + ' Reinstall CoastLink, or send the folder\'s logs to whoever helps you.' }); return; }
  app.hello = hello;
  nav.go('play');
  refreshStatus();
  setInterval(refreshStatus, 8000);
  if (hello.status.build_in_progress) buildScreen();
  else if (!hello.status.ready) setupWizard(hello);
  call('update.config').then((cfg) => { if (cfg.check_on_launch && cfg.feed) import('./screens/updates.js').then((u) => u.checkForUpdates({ quiet: true })); }).catch(() => {});
  call('first_run_done').catch(() => {});
}

boot().catch((e) => { document.getElementById('view').innerHTML = `<div class="card"><h2>CoastLink could not start</h2><p class="muted">${esc(errorText(e))}</p></div>`; });
