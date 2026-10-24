// Controllers: which device each player uses, its bindings (controllers.ini; the running game reloads it within a second),
// a live test, rumble, saved profiles, and what the GameCube adapter needs.
import { call, on } from '../bridge.js';
import { esc, icons, status, toast, modal, errorText } from '../ui.js';
import { register, suspend } from '../nav.js';
import { controllerDiagram, paintController, pressedSources, bindingPressed, modelName } from '../controller_view.js';

// Ryujinx-style groups: [control, Smash action (tooltip)]
const SHOULDER_L = [['ZL', 'Shield'], ['MINUS', 'Minus'], ['L', 'Grab']];
const SHOULDER_R = [['ZR', 'Shield'], ['PLUS', 'Pause'], ['R', 'Grab']];
const FACE = [['A', 'Attack'], ['B', 'Special'], ['X', 'Jump'], ['Y', 'Jump']];
const DPAD = [['UP', 'Taunt up'], ['DOWN', 'Taunt down'], ['LEFT', 'Taunt left'], ['RIGHT', 'Taunt right']];
const GLYPH = { MINUS: '−', PLUS: '+', UP: 'Up', DOWN: 'Down', LEFT: 'Left', RIGHT: 'Right', STICK_L: 'Button', STICK_R: 'Button',
  LSTICK_LEFT: 'Left', LSTICK_UP: 'Up', LSTICK_RIGHT: 'Right', LSTICK_DOWN: 'Down', RSTICK_LEFT: 'Left', RSTICK_UP: 'Up', RSTICK_RIGHT: 'Right', RSTICK_DOWN: 'Down' };
const KEY_LEFT = [['LSTICK_UP', 'Move up'], ['LSTICK_DOWN', 'Move down'], ['LSTICK_LEFT', 'Move left'], ['LSTICK_RIGHT', 'Move right']];
const KEY_RIGHT = [['RSTICK_UP', 'C-stick up'], ['RSTICK_DOWN', 'C-stick down'], ['RSTICK_LEFT', 'C-stick left'], ['RSTICK_RIGHT', 'C-stick right']];
// the keyboard drives a Pro Controller: which part of the picture each key lights
const KB_SRC = { A: 'east', B: 'south', X: 'north', Y: 'west', L: 'leftshoulder', R: 'rightshoulder', PLUS: 'start', MINUS: 'back',
  STICK_L: 'leftstick', STICK_R: 'rightstick', UP: 'dpup', DOWN: 'dpdown', LEFT: 'dpleft', RIGHT: 'dpright' };
const FIXED = { L: 'leftshoulder', R: 'rightshoulder', ZL: 'lefttrigger', ZR: 'righttrigger', PLUS: 'start', MINUS: 'back', STICK_L: 'leftstick', STICK_R: 'rightstick', UP: 'dpup', DOWN: 'dpdown', LEFT: 'dpleft', RIGHT: 'dpright' };
const NAMES = {
  xbox: { south: 'A', east: 'B', west: 'X', north: 'Y', leftshoulder: 'LB', rightshoulder: 'RB', lefttrigger: 'LT', righttrigger: 'RT', back: 'View', start: 'Menu', guide: 'Xbox', leftstick: 'LS press', rightstick: 'RS press' },
  ps: { south: 'Cross', east: 'Circle', west: 'Square', north: 'Triangle', leftshoulder: 'L1', rightshoulder: 'R1', lefttrigger: 'L2', righttrigger: 'R2', back: 'Share', start: 'Options', guide: 'PS', leftstick: 'L3', rightstick: 'R3' },
  nin: { south: 'B', east: 'A', west: 'Y', north: 'X', leftshoulder: 'L', rightshoulder: 'R', lefttrigger: 'ZL', righttrigger: 'ZR', back: '−', start: '+', guide: 'Home', leftstick: 'LS press', rightstick: 'RS press' },
  // GameCube adapter in PC mode (SDL's layout for it: A b1 = south, B = east, X = west, Y = north, Z = right shoulder)
  gc: { south: 'A', east: 'B', west: 'X', north: 'Y', rightshoulder: 'Z', lefttrigger: 'L', righttrigger: 'R', start: 'Start', back: 'None' },
  // GameCube adapter in Wii U mode (nnpad_gca.c: Z = misc2, the full L / R clicks = shoulders, the analog L / R = triggers)
  gcw: { south: 'A', east: 'B', west: 'X', north: 'Y', misc2: 'Z', leftshoulder: 'L click', rightshoulder: 'R click', lefttrigger: 'L', righttrigger: 'R', start: 'Start' },
};
const COMMON = { dpup: 'D-pad up', dpdown: 'D-pad down', dpleft: 'D-pad left', dpright: 'D-pad right', none: 'Not bound' };
const family = (kind = '') => /PlayStation/.test(kind) ? 'ps' : /GameCube/.test(kind) ? 'gc' : /Switch|Joy-Con/.test(kind) ? 'nin' : 'xbox';
/** the naming family of a device row (or of a kind text) */
const famOf = (d) => !d ? 'xbox' : typeof d === 'string' ? family(d) : d.model === 'gamecube' ? (d.vendor === 0x057E ? 'gcw' : 'gc') : family(d.kind);
function sourceName(src, dev) {
  const names = NAMES[famOf(dev)];
  return String(src).split(',').map((s) => s.trim()).map((s) => names[s] || COMMON[s] ||
    s.replace(/^button(\d+)$/, 'Button $1').replace(/^axis(\d+)([+-]?)$/, 'Axis $1$2').replace(/^hat(\d+)(\w+)$/, 'Hat $2').replace(/^left(x|y)([+-])$/, 'Left stick $1$2').replace(/^right(x|y)([+-])$/, 'Right stick $1$2')).join(' / ');
}
// the game's built-in layout for a GameCube adapter port in Wii U mode (nnpad_sdl.c def_map, d->gca): Z acts as ZR
const GCW_DEFAULT = { A: 'south', B: 'east', X: 'west', Y: 'north', L: 'leftshoulder', R: 'rightshoulder', ZL: 'none', ZR: 'misc2', PLUS: 'start',
  MINUS: 'none', STICK_L: 'none', STICK_R: 'none', UP: 'dpup', DOWN: 'dpdown', LEFT: 'dpleft', RIGHT: 'dpright' };
function defaultSource(control, layout, dev, raw = false) {
  if (raw) return { A: 'button1', B: 'button0', X: 'button3', Y: 'button2', L: 'button4', R: 'button5', ZL: 'button6', ZR: 'button7', PLUS: 'button9', MINUS: 'button8', STICK_L: 'button10', STICK_R: 'button11', UP: 'hat0up', DOWN: 'hat0down', LEFT: 'hat0left', RIGHT: 'hat0right' }[control];
  const fam = famOf(dev);
  if (fam === 'gcw' && control in GCW_DEFAULT) return GCW_DEFAULT[control];
  if (FIXED[control]) return FIXED[control];
  const labels = layout === 'labels' || (layout !== 'positional' && fam === 'gc');
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
      // a GameCube adapter in Wii U mode is read only by the game: CoastLink opens it while this screen is up, so its ports
      // show here as the same controllers the game makes (same identity: bindings carry over), and lets go when you leave
      s.adapters = await call('pads.adapters').catch(() => []);
      s.gca = s.adapters.some((a) => a.mode === 'wiiu' && a.usable) && !s.gcaTesting
        ? await call('pads.gca_live', { on: true }, { timeout: 15000 }).catch((e) => ({ on: false, error: errorText(e) })) : null;
      [s.devices, s.cfg, s.settings, s.profiles, s.report] = await Promise.all([call('pads.devices'), call('pads.config'), call('settings.get'),
        call('pads.profiles', { action: 'list' }).then((r) => r.profiles).catch(() => []),
        call('pads.game_report').catch(() => ({ lines: [] }))]);
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
      const type = d?.model === 'gamecube' ? 'gamecube' : d?.type_key || ({ ps: 'playstation', nin: 'switch', gc: 'gamecube', xbox: 'xbox' }[family(d?.kind)]);
      const device = pending && Object.hasOwn(pending, key) ? pending[key] : s.cfg.devices[guid]?.[key];
      return device ?? s.cfg.types?.[type]?.[key] ?? s.cfg.general[key];
    };
    const setDev = (guid, key, value) => { (s.pending.devices[guid] ||= {})[key] = value; updateDirty(); };
    const dirty = () => Object.keys(s.pending.players).length || Object.keys(s.pending.devices).length || Object.keys(s.keyboard).length || s.kbChanged;

    root.classList.add('controllers-screen');
    root.innerHTML = `<header class="page-head"><div><h1>Controllers</h1><p>Click a binding, then press the button you want for it. Press anything to see it light up.</p></div>
      <div class="row"><button class="btn" id="reset">Reset to default</button><button class="btn primary" id="save">${icons.save} Save</button></div></header>
      <div id="adapters"></div>
      <section class="rj-panel rj-top" aria-label="Player, device and profile" id="devrow"></section>
      <div class="rj-grid" id="body"></div>`;
    function updateDirty() { const b = root.querySelector('#save'); if (b) { b.disabled = !dirty(); b.innerHTML = `${icons.save} ${dirty() ? 'Save changes' : 'Saved'}`; } }

    const renderTabs = () => {};      // (the player is chosen in the top panel, as in Ryujinx)
    // GameCube adapters: what Windows sees, a live test of the Wii U mode (WinUSB, which only the game reads), and the
    // controller lines of the last game start
    const gcLines = () => (s.report?.lines || []).filter((l) => /nn::gca|GameCube|0x0079|Mayflash/i.test(l));
    const renderAdapters = () => {
      const box = root.querySelector('#adapters');
      const lines = gcLines();
      if (!s.adapters.length && !lines.length) { box.innerHTML = ''; return; }
      box.innerHTML = `<div class="rj-panel gca-panel">${s.adapters.map((a) => `<div class="row wrap" style="gap:10px">
          ${status(a.usable ? 'ok' : 'warn', a.mode === 'pc' ? 'GameCube adapter · PC mode' : 'GameCube adapter · Wii U mode')}
          <span class="small muted grow">${esc(a.advice)}</span>
          ${a.mode === 'wiiu' && a.usable ? '<button class="btn" id="gca-test">Test adapter</button>' : ''}</div>`).join('')}
        <div class="gca-ports" id="gca-ports" hidden>${[1, 2, 3, 4].map((p) => `<div class="gca-port" data-port="${p}"><span class="rj-key">Port ${p}</span><span class="gca-state small faint">waiting…</span></div>`).join('')}</div>
        <span class="small" id="gca-result">${s.gca?.error ? status('warn', s.gca.error)
          : s.gca?.on ? status('ok', s.gca.ports?.length ? `Port${s.gca.ports.length > 1 ? 's' : ''} ${s.gca.ports.join(', ')} ready: pick ${s.gca.ports.length > 1 ? 'one' : 'it'} under Input Device to see it and change its buttons.`
            : 'No controller is plugged into the adapter.') : ''}</span>
        ${lines.length ? `<details><summary class="small" style="cursor:pointer;min-height:28px">What the game saw last time it started</summary>
          <pre class="gca-log">${esc(lines.join('\n'))}</pre></details>` : ''}</div>`;
      const btn = box.querySelector('#gca-test');
      if (btn) btn.onclick = async () => {
        if (s.gcaTesting) { call('pads.gca_stop').catch(() => {}); return; }
        s.gcaTesting = true; btn.textContent = 'Stop test';
        box.querySelector('#gca-ports').hidden = false;
        box.querySelector('#gca-result').innerHTML = status('info', 'Reading the adapter for 15 seconds: press buttons on each controller…');
        let r;
        try { r = await call('pads.gca_test', { seconds: 15 }, { timeout: 30000 }); }
        catch (e) { r = { ok: false, error: errorText(e) }; }
        s.gcaTesting = false;
        if (!active) return;
        await load();                                   // the ports come back as controllers once the test let go of the adapter
        if (!active) return;
        renderAll();
        const out = root.querySelector('#gca-result');
        if (out) out.innerHTML = status(r.ok ? 'ok' : 'bad', r.ok ? r.summary : r.error);
      };
    };
    const offGca = on('gca', (m) => {
      for (const p of m.ports || []) {
        const el = root.querySelector(`.gca-port[data-port="${p.port}"]`);
        if (!el) continue;
        el.classList.toggle('on', p.connected);
        el.querySelector('.gca-state').innerHTML = p.connected
          ? (p.pressed.length ? p.pressed.map((b) => `<span class="pressed">${esc(b)}</span>`).join('') : status('ok', 'Connected'))
          : '<span class="faint">Empty</span>';
      }
    });
    const renderDevRow = () => {
      const p = s.player, a = assigned(p), d = deviceOf(p);
      const kb = String(s.kbPlayer) === String(p);
      const opts = [`<option value="auto" ${a === 'auto' && !kb ? 'selected' : ''}>Automatic (next controller that connects)</option>`,
        ...s.devices.map((x) => `<option value="${esc(x.guid)}" ${(a === x.guid || (a === 'auto' && !kb && d?.guid === x.guid && false)) ? 'selected' : ''}>${esc(x.name)} · ${esc(x.kind)}${x.player && x.player !== p ? ` (now player ${x.player})` : ''}</option>`),
        `<option value="keyboard" ${kb ? 'selected' : ''}>Keyboard</option>`, `<option value="none" ${a === 'none' && !kb ? 'selected' : ''}>Nobody</option>`];
      const layout = d ? devVal(d.guid, 'layout') || 'auto' : 'auto';
      const players = [1, 2, 3, 4, 5, 6, 7, 8].map((n) => { const who = deviceOf(n) ? deviceOf(n).name : kbIs(n) ? 'Keyboard' : '';
        return `<option value="${n}" ${n === p ? 'selected' : ''}>Player ${n}${who ? ` · ${esc(who)}` : ''}</option>`; }).join('');
      root.querySelector('#devrow').innerHTML = `
        <label class="rj-label" for="player">Player</label><select id="player" class="input">${players}</select>
        <label class="rj-label" for="prof">Profile</label><div class="row" style="gap:8px">
          <select id="prof" class="input grow" ${d ? '' : 'disabled'}><option value="">Default</option>${s.profiles.map((n) => `<option>${esc(n)}</option>`).join('')}</select>
          <button class="btn icon" id="prof-save" aria-label="Save profile" title="Save these bindings as a profile" ${d ? '' : 'disabled'}>${icons.save}</button><button class="btn icon" id="prof-del" aria-label="Delete profile" title="Delete the chosen profile" ${d ? '' : 'disabled'}>${icons.trash}</button></div>
        <label class="rj-label" for="dev">Input Device</label><div class="row" style="gap:8px"><select id="dev" class="input grow">${opts.join('')}</select><button class="btn icon" id="refresh" aria-label="Refresh devices" title="Look for controllers again">${icons.refresh}</button></div>
        <label class="rj-label" for="layout">Controller Type</label><select id="layout" class="input" ${d ? '' : 'disabled'}>
          <option value="auto">Automatic</option><option value="positional">Pro Controller (by position)</option><option value="labels">By the printed letters</option></select>
        <span class="small faint rj-hint">${d && a === 'auto' ? `Automatic: ${esc(d.name)}` : s.devices.length ? '' : 'No controller found. Plug one in and press Refresh.'}</span>`;
      root.querySelector('#layout').value = layout;
      root.querySelector('#player').onchange = (e) => { cancelListening(); s.player = +e.target.value; s.lastPad = null; renderAll(); };
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
      else { const v = devVal(d.guid, 'map.' + control.toLowerCase()); label = v ? sourceName(v, d) : sourceName(defaultSource(control, devVal(d.guid, 'layout') || 'auto', d, d.gamepad === false), d); }
      const listening = s.listen === control;
      return `<div class="rj-row ${listening ? 'listening' : ''}" title="${esc(action)}"><span class="rj-key">${esc(GLYPH[control] || control)}</span>
        <button class="bind" data-bind="${control}" aria-label="${esc(listening ? 'Cancel binding ' + control : 'Change ' + action + ' (' + control + '), currently ' + label)}">${listening ? (kb ? 'Press a key… (Esc)' : 'Press a button… (Esc)') : esc(label)}</button></div>`;
    };
    const box = (title, inner, cls = '') => `<div class="rj-box ${cls}">${title ? `<div class="rj-title">${title}</div>` : ''}${inner}</div>`;
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
      const rows = (list) => list.map(([c, a]) => bindRow(c, a, d)).join('');
      const connected = d ? s.devices.some((x) => x.guid === d.guid) : true;
      const picture = d ? controllerDiagram(d, false, d.gamepad === false) : controllerDiagram({ model: 'switchpro', gamepad: true });
      body.innerHTML = `<section class="rj-col" aria-label="Left side">
          ${box('', `<div class="rj-pair">${rows(SHOULDER_L)}</div>`, 'rj-shoulders')}
          ${box('Left Stick', `${rows([['STICK_L', 'Stick press']])}${d
            ? `<div class="rj-row"><span class="rj-key">Stick</span><span class="axis-readout" data-axis-readout="left">X 0.00 · Y 0.00</span></div>
               ${slider('dz', 'Deadzone', dz, 0, 0.95, 0.01, (v) => (+v).toFixed(2))}${slider('oz', 'Range (full tilt at)', oz, 0.05, 1, 0.01, (v) => Math.round(v * 100) + '%')}`
            : rows(KEY_LEFT)}`)}
          ${box('D-Pad', rows(DPAD))}</section>
        <section class="rj-col rj-center" aria-label="Live preview">
          ${d && d.gamepad !== false ? box('', slider('trigger', 'Trigger Threshold', +(devVal(d.guid, 'trigger_threshold') ?? 0.33), 0, 1, 0.01, (v) => (+v).toFixed(2)), 'rj-threshold') : ''}
          <div class="controller-identity"><h2>${d ? esc(modelName(d)) : 'Keyboard'}</h2><span class="small muted">${d ? esc(d.name) : 'The game sees a Pro Controller'}</span>
            <span id="conn" class="small">${status(connected ? 'ok' : 'warn', d ? (connected ? 'Connected' : 'Not connected') : 'Keys light it up')}</span></div>
          <div class="controller-stage rj-stage">${picture}</div>
          <div id="pressed" class="controller-pressed"><span class="small faint">${d ? 'Press a button to test' : 'Press a key to test'}</span></div>
          ${d ? box('Rumble', `<label class="check">Rumble<input type="checkbox" id="rum" ${rum ? 'checked' : ''}></label>
            ${slider('rs', 'Strength', rs, 0, 2, 0.05, (v) => Math.round(v * 100) + '%')}<button class="btn" id="rtest">Test rumble</button>`) : ''}
          <div class="controller-preview-note">Preview only · controller input never operates the launcher.</div></section>
        <section class="rj-col" aria-label="Right side">
          ${box('', `<div class="rj-pair">${rows(SHOULDER_R)}</div>`, 'rj-shoulders')}
          ${box('Buttons', rows(FACE))}
          ${box('Right Stick', `${rows([['STICK_R', 'Stick press']])}${d
            ? '<div class="rj-row"><span class="rj-key">Stick</span><span class="axis-readout" data-axis-readout="right">X 0.00 · Y 0.00</span></div>'
            : rows(KEY_RIGHT)}`)}</section>`;
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
        const binding = devVal(d.guid, 'map.' + control.toLowerCase()) ?? defaultSource(control, devVal(d.guid, 'layout') || 'auto', d, d.gamepad === false);
        b.closest('.rj-row').classList.toggle('input-active', bindingPressed(binding, now));
      });
      const pr = root.querySelector('#pressed'); if (pr) pr.innerHTML = now.length ? now.map((b) => `<span class="pressed">${esc(sourceName(b, d))}</span>`).join('') : '<span class="small faint">Press a button to test</span>';
      return now;
    }
    const keys = new Set();
    function paintKeys() {
      const values = [...keys], held = new Set();
      root.querySelectorAll('[data-bind]').forEach((el) => {
        const c = el.dataset.bind;
        const active = String(s.keyboard[c] ?? s.settings.keyboard_bindings[c] ?? 'none').split(',').some((k) => values.includes(k.trim()));
        el.closest('.rj-row').classList.toggle('input-active', active);
        if (active) held.add(c);
      });
      // the Pro Controller picture: buttons, triggers and both sticks from the held keys
      const axis = (neg, pos) => ((held.has(pos) ? 1 : 0) - (held.has(neg) ? 1 : 0)) * 32767;
      paintController(root, { buttons: [...held].map((c) => KB_SRC[c]).filter(Boolean),
        axes: { leftx: axis('LSTICK_LEFT', 'LSTICK_RIGHT'), lefty: axis('LSTICK_UP', 'LSTICK_DOWN'), rightx: axis('RSTICK_LEFT', 'RSTICK_RIGHT'),
                righty: axis('RSTICK_UP', 'RSTICK_DOWN'), lefttrigger: held.has('ZL') ? 32767 : 0, righttrigger: held.has('ZR') ? 32767 : 0 } });
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
    this.cleanup = () => { active = false; offPad(); offGca(); if (s.gcaTesting) call('pads.gca_stop').catch(() => {}); document.removeEventListener('keydown', keydown, true); document.removeEventListener('keyup', keyup); window.removeEventListener('blur', blur); cancelListening(); call('pads.watch', { guid: null }).catch(() => {}); call('pads.gca_live', { on: false }).catch(() => {}); if (dirty()) toast('Controller changes were not saved.', 'warn'); };
    const renderAll = () => { renderTabs(); renderAdapters(); renderDevRow(); renderBody(); updateDirty(); };
    renderAll();
  },
});
