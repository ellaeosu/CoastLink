// Menu sounds: short tones made with Web Audio when they play (no sound files). One listener set for the whole app, so
// every screen gets them: moving focus, buttons, switching screens, toggles, sliders, dialogs, results. Audio > Menu sounds
// turns them off or sets their volume (kept in this PC's app storage).
const KEY = 'coastlink.sounds';
let ctx = null, master = null, last = 0, lastRank = 0;

export function soundSettings() {
  try { const v = JSON.parse(localStorage.getItem(KEY) || '{}'); return { on: v.on !== false, volume: Number.isFinite(v.volume) ? v.volume : 0.6 }; }
  catch { return { on: true, volume: 0.6 }; }
}
export function setSoundSettings(change) {
  const next = { ...soundSettings(), ...change };
  try { localStorage.setItem(KEY, JSON.stringify(next)); } catch { /* storage off: this session only */ }
  if (master) master.gain.value = next.volume;
  return next;
}

function audio() {
  if (!ctx) {
    const C = window.AudioContext || window.webkitAudioContext;
    if (!C) return null;
    ctx = new C();
    master = ctx.createGain();
    master.gain.value = soundSettings().volume;
    master.connect(ctx.destination);
  }
  if (ctx.state === 'suspended') ctx.resume().catch(() => {});
  return ctx;
}

// one note: [start s, from Hz, to Hz, length s, gain, wave]
function notes(list) {
  const a = audio();
  if (!a) return;
  const t0 = a.currentTime + 0.005;
  for (const [at, f0, f1, len, peak, wave = 'sine'] of list) {
    const o = a.createOscillator(), g = a.createGain(), t = t0 + at;
    o.type = wave;
    o.frequency.setValueAtTime(f0, t);
    if (f1 !== f0) o.frequency.exponentialRampToValueAtTime(f1, t + len);
    g.gain.setValueAtTime(0.0001, t);
    g.gain.exponentialRampToValueAtTime(peak, t + 0.006);
    g.gain.exponentialRampToValueAtTime(0.0001, t + len);
    o.connect(g).connect(master);
    o.start(t); o.stop(t + len + 0.02);
  }
}

const SOUNDS = {          // name: [rank (a higher one wins within 70 ms), notes]
  move:    [1, [[0, 1400, 1400, 0.03, 0.05]]],
  slider:  [1, []],
  select:  [2, [[0, 880, 1175, 0.06, 0.08, 'triangle']]],
  toggleOn:  [2, [[0, 988, 988, 0.04, 0.07, 'triangle'], [0.045, 1319, 1319, 0.05, 0.06, 'triangle']]],
  toggleOff: [2, [[0, 988, 988, 0.04, 0.07, 'triangle'], [0.045, 740, 740, 0.05, 0.06, 'triangle']]],
  page:    [3, [[0, 523, 880, 0.08, 0.07], [0.03, 1047, 1047, 0.06, 0.03]]],
  back:    [3, [[0, 740, 494, 0.08, 0.07, 'triangle']]],
  confirm: [3, [[0, 784, 784, 0.05, 0.08, 'triangle'], [0.055, 1175, 1175, 0.08, 0.08, 'triangle']]],
  open:    [3, [[0, 587, 880, 0.1, 0.06]]],
  success: [4, [[0, 1047, 1047, 0.06, 0.06], [0.06, 1319, 1319, 0.06, 0.06], [0.12, 1568, 1568, 0.12, 0.06]]],
  warn:    [4, [[0, 659, 659, 0.07, 0.07, 'triangle'], [0.08, 523, 523, 0.1, 0.07, 'triangle']]],
  error:   [5, [[0, 330, 330, 0.09, 0.08, 'triangle'], [0.1, 247, 247, 0.14, 0.08, 'triangle']]],
};

export function play(name, pitch = 0) {
  const s = soundSettings();
  if (!s.on || s.volume <= 0 || document.hidden) return;
  const [rank, list] = SOUNDS[name] || [0, []];
  const now = performance.now();
  if (now - last < 70 && rank <= lastRank) return;
  last = now; lastRank = rank;
  if (name === 'slider') notes([[0, 420 + pitch * 700, 420 + pitch * 700, 0.018, 0.035]]);
  else notes(list);
}

export function installSounds() {
  let keyMove = 0, slideAt = 0;
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') play('back');
    else if (/^Arrow/.test(e.key)) keyMove = performance.now();
  }, true);
  document.addEventListener('focusin', (e) => { if (performance.now() - keyMove < 150 && !e.target.matches?.('input[type=range], select')) play('move'); });
  document.addEventListener('click', (e) => {
    const el = e.target.closest?.('button, [role=radio], [role=tab], summary, a[href]');
    if (!el || el.disabled || el.getAttribute('aria-disabled') === 'true') return;
    if (el.matches('.nav-item, [data-go]')) play('page');
    else if (el.matches('[role=radio], [role=tab]')) play('toggleOn');
    else if (el.closest('.modal') && !el.classList.contains('primary')) play('back');
    else play(el.classList.contains('primary') ? 'confirm' : 'select');
  }, true);
  document.addEventListener('change', (e) => {
    const el = e.target;
    if (el.type === 'checkbox') play(el.checked ? 'toggleOn' : 'toggleOff');
    else if (el.tagName === 'SELECT') play('select');
  }, true);
  document.addEventListener('input', (e) => {
    const el = e.target;
    if (el.type !== 'range' || performance.now() - slideAt < 45) return;
    slideAt = performance.now();
    play('slider', (el.value - el.min) / ((el.max - el.min) || 1));
  }, true);
  new MutationObserver((records) => {
    for (const r of records) for (const node of r.addedNodes) {
      if (!(node instanceof HTMLElement)) continue;
      if (node.classList.contains('modal-back')) play('open');
      else if (node.classList.contains('toast')) {
        const st = node.querySelector('.status');
        play(st?.classList.contains('bad') ? 'error' : st?.classList.contains('warn') ? 'warn' : 'success');
      }
    }
  }).observe(document.body, { childList: true, subtree: true });
}
