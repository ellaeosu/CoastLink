import { call } from '../bridge.js';
import { esc, icons, toast, confirmAction, pct, errorText } from '../ui.js';
import { register } from '../nav.js';

const seg = (key, value, options) => `<div class="seg" role="radiogroup" aria-label="${esc(key)}" style="grid-template-columns:repeat(${options.length},1fr)">${options.map(([v, l]) =>
  `<button role="radio" aria-checked="${String(value) === v}" data-seg="${key}" data-v="${v}">${esc(l)}</button>`).join('')}</div>`;
const select = (id, value, options) => {
  const values = options.some(([v]) => String(v) === String(value)) ? options : [[String(value), `Current: ${value}`], ...options];
  return `<select class="input" id="${id}">${values.map(([v, l]) => `<option value="${esc(v)}" ${String(value) === String(v) ? 'selected' : ''}>${esc(l)}</option>`).join('')}</select>`;
};
const check = (id, label, on) => `<label class="check">${esc(label)}<input type="checkbox" id="${id}" ${on ? 'checked' : ''}></label>`;

register({
  id: 'display', title: 'Display & speed', icon: 'display',
  leave() { clearInterval(this.timer); this.viewToken = null; },
  async render(root) {
    const token = this.viewToken = {};
    const current = () => this.viewToken === token && root.isConnected;
    const [s, shaders] = await Promise.all([call('settings.get'), call('shaders.status').catch(() => null)]);
    if (!current()) return;
    const g = { ...s.graphics }, launch = { ...s.launch };
    const size = `${g.width}x${g.height}`;
    const sizes = [['1280x720', '1280 × 720'], ['1600x900', '1600 × 900'], ['1920x1080', '1920 × 1080'], ['2560x1440', '2560 × 1440'], ['3840x2160', '3840 × 2160']];
    if (!sizes.some(([v]) => v === size)) sizes.unshift([size, size.replace('x', ' × ')]);
    root.innerHTML = `<header class="page-head"><div><h1 style="font-size:34px">Display & speed</h1><p>Changes apply the next time the game starts.</p></div>
      <div class="row"><span class="small muted" id="save-state" role="status">Saved settings</span><button class="btn primary" id="save">${icons.save} Save</button></div></header>
    <div class="fill" style="display:grid;grid-template-columns:minmax(0,1.15fr) minmax(0,1fr);gap:14px">
      <div class="col" style="gap:14px">
        <section class="card" aria-label="Graphics"><h2>Graphics</h2>
          <div class="col"><span style="font-weight:600">Renderer</span>${seg('renderer', g.renderer, [['vulkan', 'Vulkan'], ['opengl', 'OpenGL (fallback)']])}</div>
          <div class="col"><span style="font-weight:600">Game window</span>${seg('window', g.window, [['windowed', 'Window'], ['borderless', 'Fullscreen'], ['fullscreen', 'Fullscreen, on top']])}
            <span class="small faint">Fullscreen fills the screen without changing its resolution. F11 in the game switches, and the game remembers it.</span></div>
          <div class="grid2" style="gap:12px">
            <div class="col" style="gap:6px"><label for="size" style="font-weight:600">Window size</label>${select('size', size, sizes)}</div>
            <div class="col" style="gap:6px"><label for="scale" style="font-weight:600">Internal resolution</label>${select('scale', String(+g.resolution_scale), [['0.25', '480 × 270'], ['0.5', '960 × 540 (weak GPU)'], ['0.75', '1440 × 810'], ['1', '1920 × 1080 (console)'], ['1.25', '2400 × 1350'], ['1.5', '2880 × 1620'], ['2', '3840 × 2160 (strong GPU)']])}</div>
            <div class="col" style="gap:6px"><label for="vsync" style="font-weight:600">VSync</label>${select('vsync', g.vsync, [['auto', 'Auto (recommended)'], ['display', 'Match the display'], ['clock', '60 Hz clock'], ['off', 'Off (tearing, lowest latency)'], ['mailbox', 'Mailbox'], ['on', 'On']])}</div>
            <div class="col" style="gap:6px"><label for="latency" style="font-weight:600">Input latency</label>${select('latency', g.latency, [['normal', 'Normal'], ['low', 'Low'], ['lowest', 'Lowest (small judder)']])}</div>
          </div>
          ${check('low', 'Weak or integrated GPU profile', g.profile === 'low')}<span class="small faint" id="graphics-note"></span>
        </section>
        <section class="card" aria-label="Game speed"><h2>Game speed</h2>${seg('speed', launch.speed, [['normal', 'Normal (60)'], ['unlimited', 'Unlimited']])}
          <span class="small faint">Unlimited fast-forwards the whole game offline. Online always runs at normal speed.</span>
          ${check('movies', 'Skip movies (intros and cutscenes)', launch.skip_movies)}</section>
      </div>
      <div class="col" style="gap:14px">
        <section class="card" aria-label="Overlay"><h2>Overlay</h2>
          <div class="tile" style="min-height:140px;position:relative;justify-content:center;align-items:center"><span class="faint small">Overlay preview</span>
            <div style="position:absolute;top:10px;right:10px;padding:8px 10px;border-radius:8px;background:#000;border:1px solid var(--control);font:12px/1.5 var(--mono)"><div>60 fps · 16.6 ms</div><div>ping 94 · delay 3</div><div style="color:#FF7A85">rollback 1 fr</div></div></div>
          ${check('stats', 'Stats overlay (F2 in the game)', g.stats_overlay === 'on')}${check('ftime', 'Frame time in the window title', g.frame_time_overlay === 'on')}${check('menu', 'In-game settings menu (F1)', g.menu === 'on')}</section>
        <section class="card" aria-label="Shader cache"><div class="row" style="justify-content:space-between"><h2>Shader cache</h2><span class="mono small" id="shader-count"></span></div>
          <div class="bar blue"><i id="shader-bar" style="width:0%"></i></div>
          <div class="row"><span class="small faint grow" id="shader-detail"></span>
          <button class="btn" id="clear">Clear</button></div></section>
      </div></div>`;
    root.querySelectorAll('[data-seg]').forEach((b) => b.onclick = () => {
      const key = b.dataset.seg;
      if (key === 'speed') launch.speed = b.dataset.v; else g[key] = b.dataset.v;
      root.querySelectorAll(`[data-seg="${key}"]`).forEach((x) => x.setAttribute('aria-checked', String(x === b)));
      if (key === 'renderer') showGraphicsLimits();
    });
    const saveState = root.querySelector('#save-state');
    let revision = 0;
    const dirty = () => { revision++; saveState.textContent = 'Unsaved changes'; };
    root.addEventListener('input', dirty);
    root.addEventListener('change', dirty);
    root.querySelectorAll('[data-seg]').forEach((b) => b.addEventListener('click', dirty));
    const showGraphicsLimits = () => {
      const gl = g.renderer === 'opengl', low = root.querySelector('#low').checked;
      root.querySelector('#scale').disabled = gl || low;
      root.querySelector('#vsync').disabled = gl || low;
      root.querySelector('#latency').disabled = gl;
      root.querySelector('#graphics-note').textContent = gl ? 'OpenGL uses its own pacing. Scaling, VSync and input-latency settings here apply to Vulkan.' : low ? 'Low profile uses 50% render scale and clock pacing; your custom choices are kept.' : '';
    };
    root.querySelector('#low').onchange = showGraphicsLimits;
    showGraphicsLimits();
    const drawShaders = (value) => {
      root.querySelector('#shader-count').textContent = value ? (value.done ? 'Prepared' : value.total ? `${value.read} / ${value.total}` : 'Not prepared') : 'Status unavailable';
      root.querySelector('#shader-bar').style.width = `${value ? pct(value.read, value.total) : 0}%`;
      root.querySelector('#shader-detail').textContent = !value ? 'Shader status could not be read. It will retry automatically.' : value.done ? 'Prepared. Clearing requires a new offline preparation pass.' : 'Launch offline and finish preparation before going online.';
    };
    drawShaders(shaders);
    let readingShaders = false;
    const refreshShaders = async () => {
      if (readingShaders || !current()) return;
      readingShaders = true;
      try { const value = await call('shaders.status'); if (current()) drawShaders(value); }
      catch { if (current()) drawShaders(null); }
      finally { readingShaders = false; }
    };
    this.timer = setInterval(refreshShaders, 3000);
    root.querySelector('#save').onclick = async () => {
      const button = root.querySelector('#save');
      const version = revision;
      const [w, h] = root.querySelector('#size').value.split('x');
      const patch = { renderer: g.renderer, window: g.window, width: w, height: h, resolution_scale: root.querySelector('#scale').value, vsync: root.querySelector('#vsync').value, latency: root.querySelector('#latency').value,
        profile: root.querySelector('#low').checked ? 'low' : 'custom', stats_overlay: root.querySelector('#stats').checked ? 'on' : 'off',
        frame_time_overlay: root.querySelector('#ftime').checked ? 'on' : 'off', menu: root.querySelector('#menu').checked ? 'on' : 'off' };
      button.disabled = true; saveState.textContent = 'Saving…';
      try {
        await call('settings.save', { settings: { graphics: patch, launch: { speed: launch.speed, skip_movies: root.querySelector('#movies').checked } } });
        if (current()) { saveState.textContent = version === revision ? 'Saved' : 'Unsaved changes'; toast('Saved. It applies the next time the game starts.', 'ok'); }
      } catch (e) { if (current()) { saveState.textContent = 'Not saved'; toast(errorText(e), 'bad'); } }
      finally { if (current()) button.disabled = false; }
    };
    root.querySelector('#clear').onclick = async () => {
      if (!await confirmAction('Clear the shader cache?', 'The next start prepares every shader again, which takes a few minutes. Online play waits until it is done.', 'Clear')) return;
      const button = root.querySelector('#clear'); button.disabled = true;
      try { const r = await call('shaders.clear'); if (current()) { toast(`Cleared (${r.removed} item(s)).`, 'ok'); await refreshShaders(); } }
      catch (e) { if (current()) toast(errorText(e), 'bad'); }
      finally { if (current()) button.disabled = false; }
    };
  },
});
