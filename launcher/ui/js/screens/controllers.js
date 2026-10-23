// Controllers: which device each player uses, its bindings (controllers.ini; the running game reloads it within a second),
// a live test, rumble, saved profiles, and what the GameCube adapter needs.
import { call, on } from '../bridge.js';
import { esc, icons, status, toast, modal, errorText } from '../ui.js';
import { register, suspend } from '../nav.js';
import { controllerDiagram, paintController, pressedSources, bindingPressed, modelName } from '../controller_view.js';

const LEFT = [['L', 'Shield'], ['ZL', 'Grab'], ['MINUS', 'Minus'], ['UP', 'Taunt up'], ['DOWN', 'Taunt down'], ['LEFT', 'Taunt left'], ['RIGHT', 'Taunt right'], ['STICK_L', 'Stick press']];
const RIGHT = [['A', 'Attack'], ['B', 'Special'], ['X', 'Jump'], ['Y', 'Jump'], ['R', 'Shield'], ['ZR', 'Grab'], ['PLUS', 'Pause'], ['STICK_R', 'Stick press']];
const GLYPH = { MINUS: '−', PLUS: '+', UP: 'D↑', DOWN: 'D↓', LEFT: 'D←', RIGHT: 'D→', STICK_L: 'LS', STICK_R: 'RS', LSTICK_LEFT: 'L←', LSTICK_UP: 'L↑', LSTICK_RIGHT: 'L→', LSTICK_DOWN: 'L↓', RSTICK_LEFT: 'R←', RSTICK_UP: 'R↑', RSTICK_RIGHT: 'R→', RSTICK_DOWN: 'R↓' };
const KEY_LEFT = [['LSTICK_LEFT', 'Move left'], ['LSTICK_UP', 'Move up'], ['LSTICK_RIGHT', 'Move right'], ['LSTICK_DOWN', 'Move down']];
const KEY_RIGHT = [['RSTICK_LEFT', 'C-stick left'], ['RSTICK_UP', 'C-stick up'], ['RSTICK_RIGHT', 'C-stick right'], ['RSTICK_DOWN', 'C-stick down']];
const FIXED = { L: 'leftshoulder', R: 'rightshoulder', ZL: 'lefttrigger', ZR: 'righttrigger', PLUS: 'start', MINUS: 'back', STICK_L: 'leftstick', STICK_R: 'rightstick', UP: 'dpup', DOWN: 'dpdown', LEFT: 'dpleft', RIGHT: 'dpright' };
const NAMES = {
  xbox: { south: 'A', east: 'B', west: 'X', north: 'Y', leftshoulder: 'LB', rightshoulder: 'RB', lefttrigger: 'LT', righttrigger: 'RT', back: 'View', start: 'Menu', guide: 'Xbox', leftstick: 'LS press', rightstick: 'RS press' },
  ps: { south: 'Cross', east: 'Circle', west: 'Square', north: 'Triangle', leftshoulder: 'L1', rightshoulder: 'R1', lefttrigger: 'L2', righttrigger: 'R2', back: 'Share', start: 'Options', guide: 'PS', leftstick: 'L3', rightstick: 'R3' },
  nin: { south: 'B', east: 'A', west: 'Y', north: 'X', leftshoulder: 'L', rightshoulder: 'R', lefttrigger: 'ZL', righttrigger: 'ZR', back: '−', start: '+', guide: 'Home', leftstick: 'LS press', rightstick: 'RS press' },
  gc: { south: 'A', east: 'X', west: 'B', north: 'Y', rightshoulder: 'Z', lefttrigger: 'L', righttrigger: 'R', start: 'Start' },
};
const COMMON = { dpup: 'D-pad up', dpdown: 'D-pad down', dpleft: 'D-pad left', dpright: 'D-pad right', none: 'Not bound' };
const family = (kind = '') => /PlayStation/.test(kind) ? 'ps' : /GameCube/.test(kind) ? 'gc' : /Switch|Joy-Con/.test(kind) ? 'nin' : 'xbox';
function sourceName(src, kind) {
  return String(src).split(',').map((s) => s.trim()).map((s) => NAMES[family(kind)][s] || COMMON[s] ||
    s.replace(/^button(\d+)$/, 'Button $1').replace(/^axis(\d+)([+-]?)$/, 'Axis $1$2').replace(/^hat(\d+)(\w+)$/, 'Hat $2').replace(/^left(x|y)([+-])$/, 'Left stick $1$2').replace(/^right(x|y)([+-])$/, 'Right stick $1$2')).join(' / ');
}
function defaultSource(control, layout, kind, raw = false) {
  if (raw) return { A: 'button1', B: 'button0', X: 'button3', Y: 'button2', L: 'button4', R: 'button5', ZL: 'button6', ZR: 'button7', PLUS: 'button9', MINUS: 'button8', STICK_L: 'button10', STICK_R: 'button11', UP: 'hat0up', DOWN: 'hat0down', LEFT: 'hat0left', RIGHT: 'hat0right' }[control];
  if (FIXED[control]) return FIXED[control];
  const labels = layout === 'labels' || (layout !== 'positional' && /GameCube/.test(kind));
  return (labels ? { A: 'south', B: 'east', X: 'west', Y: 'north' } : { A: 'east', B: 'south', X: 'north', Y: 'west' })[control];
}
function keyName(e) {
  const k = e.key;
  if (e.code?.startsWith('Numpad') && /^\d$/.test(k)) return 'NUM' + k;
  if (/^[a-z0-9]$/i.test(k)) return k.toUpperCase();
  if (/^F([1-9]|1[0-2])$/.test(k)) return k;
  return { ArrowLeft: 'LEFT', ArrowUp: 'UP', ArrowRight: 'RIGHT', ArrowDown: 'DOWN', Enter: 'ENTER', Backspace: 'BACKSPACE', ' ': 'SPACE', Tab: 'TAB', Shift: 'SHIFT', Control: 'CTRL', Alt: 'ALT' }[k] || null;
}

register({
  id: 'controllers', title: 'Controllers', icon: 'pad',
  leave() { this.cleanup?.(); },
  async render(root) {
    let active = true;
    this.cleanup = () => { active = false; };
    const s = { player: 1, devices: [], cfg: null, settings: null, adapters: [], profiles: [], pending: { players: {}, devices: {} }, keyboard: {}, kbPlayer: null, live: null, listen: null };
    const load = async () => {
      [s.devices, s.cfg, s.settings, s.adapters, s.profiles] = await Promise.all([call('pads.devices'), call('pads.config'), call('settings.get'),
        call('pads.adapters').catch(() => []), call('pads.profiles', { action: 'list' }).then((r) => r.profiles).catch(() => [])]);
      if (!s.kbChanged) s.kbPlayer = s.settings.controller.keyboard_player;
    };
    await load();
    if (!active) return;
    const assigned = (p) => s.pending.players[p] ?? s.cfg.players[p] ?? 'auto';
    const kbIs = (p) => String(s.kbPlayer) === String(p) || (s.kbPlayer === 'auto' && p === [1,2,3,4,5,6,7,8].find((n) => assigned(n) === 'auto' && !s.devices.some((d) => d.player === n)));
    const deviceOf = (p) => { const a = assigned(p); if (a === 'none') return null; return a && a !== 'auto' ? s.devices.find((d) => d.guid === a && d.player === p) || s.devices.find((d) => d.guid === a) || { guid: a, name: 'Not connected', kind: '' } : s.devices.find((d) => d.player === p) || null; };
    const kbHere = (p) => String(s.kbPlayer) === String(p) || (!deviceOf(p) && kbIs(p));
    const devVal = (guid, key) => {
      const d = s.devices.find((v) => v.guid === guid), pending = s.pending.devices[guid];
      const type = d?.type_key || ({ ps: 'playstation', nin: 'switch', gc: 'gamecube', xbox: 'xbox' }[family(d?.kind)]);
      const device = pending && Object.hasOwn(pending, key) ? pending[key] : s.cfg.devices[guid]?.[key];
      return device ?? s.cfg.types?.[type]?.[key] ?? s.cfg.general[key];
    };
    const setDev = (guid, key, value) => { (s.pending.devices[guid] ||= {})[key] = value; updateDirty(); };
    const dirty = () => Object.keys(s.pending.players).length || Object.keys(s.pending.devices).length || Object.keys(s.keyboard).length || s.kbChanged;

    root.classList.add('controllers-screen');
    root.innerHTML = `<header class="page-head"><div><span class="label">Make it feel like yours</span><h1>Controllers</h1><p>Choose your controller. Press a button and watch it light up.</p></div>
      <div class="row"><button class="btn" id="reset">Reset to default</button><button class="btn primary" id="save">${icons.save} Save</button></div></header>
      <div class="tabs" role="tablist" aria-label="Player" id="tabs"></div>
      <div id="adapters"></div>
      <section class="card tight controller-device-row" aria-label="Device and profile" id="devrow"></section>
      <div class="controller-workspace" id="body"></div>`;
    function updateDirty() { const b = root.querySelector('#save'); if (b) { b.disabled = !dirty(); b.innerHTML = `${icons.save} ${dirty() ? 'Save changes' : 'Saved'}`; } }

    const renderTabs = () => {
      root.querySelector('#tabs').innerHTML = [1, 2, 3, 4, 5, 6, 7, 8].map((p) => {
        const d = deviceOf(p), has = d || kbIs(p);
        return `<button class="tab ${has ? 'has' : ''}" role="tab" aria-selected="${s.player === p}" data-p="${p}">${has ? `<span class="dot" style="background:${p === 1 ? 'var(--red)' : 'var(--blue)'}"></span>` : ''}Player ${p}</button>`;
      }).join('');
      root.querySelectorAll('[data-p]').forEach((b) => b.onclick = () => { cancelListening(); s.player = +b.dataset.p; s.lastPad = null; renderAll(); });
    };
    const renderAdapters = () => {
      root.querySelector('#adapters').innerHTML = s.adapters.map((a) => `<div class="card tight" style="flex-direction:row;align-items:center">${status(a.usable ? 'ok' : 'warn', a.mode === 'pc' ? 'GameCube adapter (PC mode)' : 'GameCube adapter (Wii U / Switch mode)')}<span class="small muted grow">${esc(a.advice)}</span></div>`).join('');
    };
    const renderDevRow = () => {
      const p = s.player, a = assigned(p), d = deviceOf(p);
      const kb = String(s.kbPlayer) === String(p);
      const opts = [`<option value="auto" ${a === 'auto' && !kb ? 'selected' : ''}>Automatic (next controller that connects)</option>`,
        ...s.devices.map((x) => `<option value="${esc(x.guid)}" ${(a === x.guid || (a === 'auto' && !kb && d?.guid === x.guid && false)) ? 'selected' : ''}>${esc(x.name)} · ${esc(x.kind)}${x.player && x.player !== p ? ` (now player ${x.player})` : ''}</option>`),
        `<option value="keyboard" ${kb ? 'selected' : ''}>Keyboard</option>`, `<option value="none" ${a === 'none' && !kb ? 'selected' : ''}>Nobody</option>`];
      const layout = d ? devVal(d.guid, 'layout') || 'auto' : 'auto';
      root.querySelector('#devrow').innerHTML = `<div class="col" style="gap:6px"><label class="label" for="dev">Input device</label>
          <div class="row" style="gap:8px"><select id="dev" class="input grow">${opts.join('')}</select><button class="btn icon" id="refresh" aria-label="Refresh devices">${icons.refresh}</button></div>
          <span class="small faint">${d && a === 'auto' ? `Automatic: ${esc(d.name)}` : s.devices.length ? '' : 'No controller found. Plug one in and press Refresh.'}</span></div>
        <div class="col" style="gap:6px"><label class="label" for="layout">Face buttons</label><select id="layout" class="input" ${d ? '' : 'disabled'}>
          <option value="auto">Automatic</option><option value="positional">By position (like a Switch)</option><option value="labels">By the printed letters</option></select></div>
        <div class="col" style="gap:6px"><label class="label" for="prof">Profile</label><div class="row" style="gap:8px">
          <select id="prof" class="input grow" ${d ? '' : 'disabled'}><option value="">Choose a saved profile…</option>${s.profiles.map((n) => `<option>${esc(n)}</option>`).join('')}</select>
          <button class="btn icon" id="prof-save" aria-label="Save profile" ${d ? '' : 'disabled'}>${icons.save}</button><button class="btn icon" id="prof-del" aria-label="Delete profile" ${d ? '' : 'disabled'}>${icons.trash}</button></div></div>`;
      root.querySelector('#layout').value = layout;
      root.querySelector('#dev').onchange = (e) => {
        cancelListening(); s.lastPad = null;
        const v = e.target.value;
        if (v === 'keyboard') { s.kbPlayer = String(p); s.kbChanged = true; s.pending.players[p] = 'none'; }
        else {
          if (v === 'none' && kbHere(p)) { s.kbPlayer = 'none'; s.kbChanged = true; }
          else if (String(s.kbPlayer) === String(p)) { s.kbPlayer = 'auto'; s.kbChanged = true; }
          s.pending.players[p] = v;
        }
        renderAll();
      };
      root.querySelector('#refresh').onclick = async () => { try { await load(); if (active) { renderAll(); toast(`${s.devices.length} controller(s) found.`, 'ok'); } } catch (e) { toast(errorText(e), 'bad'); } };
      root.querySelector('#layout').onchange = (e) => { setDev(d.guid, 'layout', e.target.value === 'auto' ? null : e.target.value); renderBody(); };
      root.querySelector('#prof').onchange = async (e) => {
        if (!e.target.value) return;
        const profileName = e.target.value;
        try { await saveAll(true); await call('pads.profiles', { action: 'load', name: profileName, guid: d.guid }); await load(); renderAll(); toast(`Profile ${profileName} loaded.`, 'ok'); }
        catch (err) { toast(errorText(err), 'bad'); }
      };
      root.querySelector('#prof-save').onclick = async () => {
        let typed = '';
        const capture = (e) => { if (e.target.id === 'pname') typed = e.target.value.trim(); };
        document.addEventListener('input', capture, true);
        const ok = await modal({ title: 'Save profile', body: "Saves this controller's bindings and stick settings under a name.", html: '<input class="input" id="pname" maxlength="40" placeholder="Profile name">', actions: [{ label: 'Cancel', value: false }, { label: 'Save', value: true, kind: 'primary' }] });
        document.removeEventListener('input', capture, true);
        if (!ok || !typed) return;
        try { await saveAll(true); s.profiles = (await call('pads.profiles', { action: 'save', name: typed, guid: d.guid })).profiles; renderDevRow(); toast('Profile saved.', 'ok'); }
        catch (err) { toast(errorText(err), 'bad'); }
      };
      root.querySelector('#prof-del').onclick = async () => {
        const n = root.querySelector('#prof').value;
        if (!n) { toast('Choose the profile to delete first.', 'warn'); return; }
        try { s.profiles = (await call('pads.profiles', { action: 'delete', name: n })).profiles; if (active) renderDevRow(); } catch (e) { toast(errorText(e), 'bad'); }
      };
    };

    const bindRow = (control, action, d) => {
      const kb = !d;
      let label;
      if (kb) label = s.keyboard[control] ?? s.settings.keyboard_bindings[control] ?? 'none';
      else { const v = devVal(d.guid, 'map.' + control.toLowerCase()); label = v ? sourceName(v, d.kind) : sourceName(defaultSource(control, devVal(d.guid, 'layout') || 'auto', d.kind, d.gamepad === false), d.kind); }
      const listening = s.listen === control;
      return `<div class="bind-row ${listening ? 'listening' : ''}"><span class="glyph ${'ABXY'.includes(control) && control.length === 1 ? 'round' : ''}">${esc(GLYPH[control] || control)}</span>
        <span class="action">${listening ? 'Press a button… (Esc cancels)' : esc(action)}</span><button class="bind" data-bind="${control}" aria-label="${esc(listening ? 'Cancel binding ' + control : 'Change ' + action + ' (' + control + '), currently ' + label)}" title="${esc(action)}">${listening ? 'Cancel' : esc(label)}</button></div>`;
    };
    const slider = (id, label, value, min, max, step, fmt) => `<div class="slider"><div class="top"><label for="${id}">${label}</label><span class="mono" id="${id}-v">${fmt(value)}</span></div>
      <input id="${id}" type="range" min="${min}" max="${max}" step="${step}" value="${value}"></div>`;

    const renderBody = () => {
      const d = kbHere(s.player) ? null : deviceOf(s.player);
      const body = root.querySelector('#body');
      if (!d && !kbHere(s.player)) {
        body.innerHTML = `<section class="card" style="grid-column:1/-1"><h2>No device on player ${s.player}</h2><p class="muted" style="margin:0">Pick a controller above, or leave it on Automatic: the next controller that connects takes this slot.</p></section>`;
        return;
      }
      const g = s.cfg.general;
      const dz = +(d ? devVal(d.guid, 'deadzone') ?? g.deadzone ?? 0.1 : 0.1), oz = +(d ? devVal(d.guid, 'outer_zone') ?? g.outer_zone ?? 0.98 : 0.98);
      const rs = +(d ? devVal(d.guid, 'rumble_strength') ?? g.rumble_strength ?? 1 : 1), rum = (d ? devVal(d.guid, 'rumble') ?? g.rumble ?? 'on' : 'off') !== 'off';
      body.innerHTML = `<section class="card controller-bindings" aria-label="Left side"><div class="row"><h2>Movement</h2><span class="small faint grow">& triggers</span></div>
          ${d ? `<div class="row"><span class="grow small">Left stick</span><span class="axis-readout" data-axis-readout="left">X 0.00 · Y 0.00</span></div>
          ${slider('dz', 'Deadzone', dz, 0, 0.95, 0.01, (v) => (+v).toFixed(2))}${slider('oz', 'Range (full tilt at)', oz, 0.05, 1, 0.01, (v) => Math.round(v * 100) + '%')}${slider('trigger', 'Trigger threshold', +(devVal(d.guid, 'trigger_threshold') ?? 0.33), 0, 1, 0.01, (v) => Math.round(v * 100) + '%')}<div class="divider"></div>` : ''}
          ${[...LEFT, ...(!d ? KEY_LEFT : [])].map(([c, a]) => bindRow(c, a, d)).join('')}</section>
        <section class="card controller-live" aria-label="Live test"><div class="row" style="justify-content:space-between"><span class="label">Live preview</span><span id="conn" class="small">${d ? status(s.devices.some((x) => x.guid === d.guid) ? 'ok' : 'warn', s.devices.some((x) => x.guid === d.guid) ? 'Connected' : 'Not connected') : status('ok', 'Keyboard')}</span></div>
          <div class="controller-identity"><h2>${d ? esc(modelName(d)) : 'Keyboard'}</h2><span class="small muted">${d ? esc(d.name) : 'Your bindings, at a glance'}</span></div>
          <div class="controller-stage">${controllerDiagram(d, !d, d?.gamepad === false)}</div>
          <div id="pressed" class="controller-pressed"><span class="small faint">Press a button to test</span></div>
          <div class="controller-preview-note">Preview only · Controller input never operates the launcher.</div>
          ${d ? `<div class="divider"></div><label class="check">Rumble<input type="checkbox" id="rum" ${rum ? 'checked' : ''}></label>
          ${slider('rs', 'Rumble strength', rs, 0, 2, 0.05, (v) => Math.round(v * 100) + '%')}<button class="btn" id="rtest">Test rumble</button>` : ''}</section>
        <section class="card controller-bindings" aria-label="Right side"><div class="row" style="justify-content:space-between"><h2>Actions</h2><span class="small faint">Game → yours</span></div>
          ${d ? '<span class="axis-readout" data-axis-readout="right">X 0.00 · Y 0.00</span>' : ''}
          ${[...RIGHT, ...(!d ? KEY_RIGHT : [])].map(([c, a]) => bindRow(c, a, d)).join('')}</section>`;
      const hook = (id, key, fmt) => { const el = body.querySelector('#' + id); if (!el) return; el.oninput = () => { body.querySelector(`#${id}-v`).textContent = fmt(el.value); setDev(d.guid, key, el.value); if (s.lastPad?.guid === d.guid) showPad(s.lastPad, d); }; };
      if (d) {
        hook('dz', 'deadzone', (v) => (+v).toFixed(2)); hook('oz', 'outer_zone', (v) => Math.round(v * 100) + '%'); hook('rs', 'rumble_strength', (v) => Math.round(v * 100) + '%'); hook('trigger', 'trigger_threshold', (v) => Math.round(v * 100) + '%');
        body.querySelector('#rum').onchange = (e) => setDev(d.guid, 'rumble', e.target.checked ? 'on' : 'off');
        body.querySelector('#rtest').onclick = () => call('pads.rumble', { guid: d.guid, strength: +body.querySelector('#rs').value, ms: 450 }).then((r) => r.ok || toast('This controller did not accept rumble.', 'warn')).catch((e) => toast(errorText(e), 'bad'));
      }
      body.querySelectorAll('[data-bind]').forEach((b) => b.onclick = () => (s.listen === b.dataset.bind ? stopListen() : startListen(b.dataset.bind, d)));
      watch(d); if (d && s.lastPad?.guid === d.guid) showPad(s.lastPad, d);
    };

    // ---- live input and binding by pressing
    let baseline = null;
    const offPad = on('pad', (m) => {
      const d = kbHere(s.player) ? null : deviceOf(s.player);
      if (!d || m.guid !== d.guid) return;
      s.lastPad = m;
      const now = showPad(m, d);
      if (s.listen && baseline) {
        const fresh = now.find((b) => !baseline.includes(b));
        if (fresh) { setDev(d.guid, 'map.' + s.listen.toLowerCase(), fresh); stopListen(); }
        else baseline = baseline.filter((b) => now.includes(b));
      } else baseline = now;
    });
    function showPad(m, d) {
      const conn = root.querySelector('#conn'); if (conn) conn.innerHTML = status(m.connected === false ? 'warn' : 'ok', m.connected === false ? 'Disconnected' : 'Connected');
      const now = paintController(root, m.connected === false ? {} : m, devVal(d.guid, 'deadzone') ?? 0.1, devVal(d.guid, 'trigger_threshold') ?? 0.33);
      root.querySelectorAll('[data-bind]').forEach((b) => {
        const control = b.dataset.bind;
        const binding = devVal(d.guid, 'map.' + control.toLowerCase()) ?? defaultSource(control, devVal(d.guid, 'layout') || 'auto', d.kind, d.gamepad === false);
        b.closest('.bind-row').classList.toggle('input-active', bindingPressed(binding, now));
      });
      const pr = root.querySelector('#pressed'); if (pr) pr.innerHTML = now.length ? now.map((b) => `<span class="pressed">${esc(sourceName(b, d.kind))}</span>`).join('') : '<span class="small faint">Press a button to test</span>';
      return now;
    }
    const keys = new Set();
    function paintKeys() {
      const values = [...keys];
      root.querySelectorAll('[data-key-control], [data-bind]').forEach((el) => {
        const c = el.dataset.keyControl || el.dataset.bind;
        const active = String(s.keyboard[c] ?? s.settings.keyboard_bindings[c] ?? 'none').split(',').some((k) => values.includes(k.trim()));
        if (el.dataset.keyControl) el.classList.toggle('lit', active);
        else el.closest('.bind-row').classList.toggle('input-active', active);
      });
    }
    const keydown = (e) => {
      const pr = root.querySelector('#pressed');
      if (kbHere(s.player) && !e.target.closest('input,select,textarea') && !s.listen) { keys.add(keyName(e) || e.key); paintKeys(); if (pr) pr.innerHTML = [...keys].map((k) => `<span class="pressed">${esc(k)}</span>`).join(''); }
      if (!s.listen) return;
      e.preventDefault(); e.stopPropagation();
      if (e.key === 'Escape') { stopListen(); return; }
      if (kbHere(s.player)) { const k = keyName(e); if (k) { s.keyboard[s.listen] = k; stopListen(); updateDirty(); } }
    };
    document.addEventListener('keydown', keydown, true);
    const keyup = (e) => { keys.delete(keyName(e) || e.key); if (kbHere(s.player)) paintKeys(); };
    const blur = () => { keys.clear(); if (kbHere(s.player)) paintKeys(); };
    document.addEventListener('keyup', keyup); window.addEventListener('blur', blur);
    function cancelListening() { if (s.listen) suspend(false); s.listen = null; }
    function startListen(control, d) { cancelListening(); s.listen = control; baseline = d ? s.lastPad?.guid === d.guid ? pressedSources(s.lastPad, devVal(d.guid, 'trigger_threshold') ?? 0.33) : null : []; suspend(true); renderBody(); }
    function stopListen() { cancelListening(); renderBody(); }
    function watch(d) { const g = d && s.devices.some((x) => x.guid === d.guid) ? d.guid : null; if (g !== s.live) { s.live = g; call('pads.watch', { guid: g }).catch(() => {}); } }

    // ---- save / reset
    async function saveAll(silent) {
      if (s.saving) throw new Error('Wait for the current save to finish.');
      s.saving = true; cancelListening();
      const disabled = [...root.querySelectorAll('button,input,select')].map((el) => [el, el.disabled]);
      disabled.forEach(([el]) => { el.disabled = true; });
      try {
      const out = { players: { ...s.pending.players }, devices: s.pending.devices };
      if (Object.keys(out.players).length || Object.keys(out.devices).length) s.cfg = await call('pads.config', { save: out });
      if (Object.keys(s.keyboard).length || s.kbChanged) {
        const patch = {};
        if (Object.keys(s.keyboard).length) patch.keyboard_bindings = { ...s.keyboard };
        if (s.kbChanged) patch.controller = { keyboard_player: String(s.kbPlayer) };
        s.settings = await call('settings.save', { settings: patch });
      }
      s.pending = { players: {}, devices: {} }; s.keyboard = {}; s.kbChanged = false;
      if (!silent) toast('Saved. A running game uses it within a second.', 'ok');
      } finally {
        s.saving = false; disabled.forEach(([el, was]) => { el.disabled = was; }); updateDirty();
      }
    }
    root.querySelector('#save').onclick = async () => { try { await saveAll(false); await load(); if (active) renderAll(); } catch (e) { toast(errorText(e), 'bad'); } };
    root.querySelector('#reset').onclick = async () => {
      const d = kbHere(s.player) ? null : deviceOf(s.player);
      if (!d && !kbHere(s.player)) return;
      const ok = await modal({ title: 'Reset to default?', body: d ? `Every binding and stick setting of ${d.name} goes back to the default.` : 'The keyboard keys go back to the default.', actions: [{ label: 'Cancel', value: false }, { label: 'Reset', value: true, kind: 'primary' }] });
      if (!ok) return;
      try {
        if (d) { const keys = { ...(s.cfg.devices[d.guid] || {}) }; await call('pads.config', { save: { devices: { [d.guid]: Object.fromEntries(Object.keys(keys).filter((k) => k !== 'name').map((k) => [k, null])) } } }); }
        else await call('settings.save', { settings: { keyboard_bindings: { A: 'Z', B: 'X', X: 'C', Y: 'V', L: 'Q', R: 'E', ZL: 'A', ZR: 'S', PLUS: 'ENTER', MINUS: 'BACKSPACE', STICK_L: 'none', STICK_R: 'none', LEFT: 'J', UP: 'I', RIGHT: 'L', DOWN: 'K', LSTICK_LEFT: 'LEFT', LSTICK_UP: 'UP', LSTICK_RIGHT: 'RIGHT', LSTICK_DOWN: 'DOWN', RSTICK_LEFT: 'none', RSTICK_UP: 'none', RSTICK_RIGHT: 'none', RSTICK_DOWN: 'none' } } });
        if (d) delete s.pending.devices[d.guid]; else s.keyboard = {}; cancelListening(); await load(); renderAll(); toast('Back to the defaults.', 'ok');
      } catch (e) { toast(errorText(e), 'bad'); }
    };
    this.cleanup = () => { active = false; offPad(); document.removeEventListener('keydown', keydown, true); document.removeEventListener('keyup', keyup); window.removeEventListener('blur', blur); cancelListening(); call('pads.watch', { guid: null }).catch(() => {}); if (dirty()) toast('Controller changes were not saved.', 'warn'); };
    const renderAll = () => { renderTabs(); renderAdapters(); renderDevRow(); renderBody(); updateDirty(); };
    renderAll();
  },
});
