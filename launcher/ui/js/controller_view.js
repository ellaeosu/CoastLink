// Presentation only. Input is sampled by SDL; this module never navigates or clicks the app.
// The live preview draws the controller that is actually connected: pads.py tells the model (the SDL type refined by the
// USB vendor/product ids) and each model has its own outline, layout, labels and button colours. Original line art.
import { esc } from './ui.js';
import { padArt } from './pad_art.js';

export const family = (kind = '') => /PlayStation/i.test(kind) ? 'ps' : /GameCube/i.test(kind) ? 'gc' : /Switch|Joy-Con/i.test(kind) ? 'nin' : 'xbox';

export function axisValue(axes, name, raw) {
  return Math.max(-1, Math.min(1, (axes?.[name] ?? axes?.['axis' + raw] ?? 0) / 32767));
}

export function pressedSources(state = {}, threshold = 0.33) {
  const out = new Set(state.buttons || []);
  for (const [key, value] of Object.entries(state.axes || {})) {
    if (/trigger/.test(key)) { if (value > threshold * 32767) out.add(key); }
    else if (Math.abs(value) > 20000) out.add(key + (value > 0 ? '+' : '-'));
  }
  return [...out];
}

export function bindingPressed(binding, sources) {
  return String(binding || '').split(',').some((part) => sources.includes(part.trim().toLowerCase()));
}

// ---------------------------------------------------------------- which picture
export const MODEL_NAMES = {
  xbox360: 'Xbox 360 controller', xboxone: 'Xbox One controller', xboxseries: 'Xbox Series controller',
  ps3: 'DualShock 3', ps4: 'DualShock 4', ps5: 'DualSense', switchpro: 'Switch Pro Controller',
  joyconpair: 'Joy-Con pair', joyconl: 'Joy-Con (L)', joyconr: 'Joy-Con (R)', gamecube: 'GameCube controller', generic: 'Controller',
};
const KIND_MODEL = { 'Xbox 360': 'xbox360', 'Xbox One': 'xboxone', 'PlayStation 3': 'ps3', 'PlayStation 4': 'ps4', 'PlayStation 5': 'ps5',
  'Switch Pro': 'switchpro', 'Joy-Con (L)': 'joyconl', 'Joy-Con (R)': 'joyconr', 'Joy-Con pair': 'joyconpair', GameCube: 'gamecube' };
/** device row from pads.devices (or just its kind text) -> model key */
export function modelOf(device) {
  if (!device) return 'generic';
  if (typeof device === 'string') return KIND_MODEL[device] || 'generic';
  return MODEL_NAMES[device.model] ? device.model : KIND_MODEL[device.kind] || 'generic';
}
export const modelName = (device) => (device && typeof device === 'object' && device.gamepad === false) ? 'Joystick' : MODEL_NAMES[modelOf(device)];

/** the live preview: device = a pads.devices row (or a kind string); keyboard / raw: the other two previews */
export function controllerDiagram(device, keyboard = false, raw = false) {
  if (keyboard) return `<div class="keyboard-preview" aria-label="Live keyboard preview">${['L', 'ZL', 'MINUS', 'PLUS', 'R', 'ZR', 'UP', 'X', 'Y', 'LEFT', 'DOWN', 'RIGHT', 'A', 'B'].map((c) => `<span data-key-control="${c}" class="preview-key">${esc({ MINUS: '−', PLUS: '+', UP: '↑', DOWN: '↓', LEFT: '←', RIGHT: '→' }[c] || c)}</span>`).join('')}</div>`;
  if (raw) return `<div class="raw-preview"><span class="small faint">Raw joystick · Windows button numbers</span><div class="raw-buttons">${Array.from({ length: 12 }, (_, i) => `<span class="preview-key" data-source="button${i}">${i}</span>`).join('')}</div><div class="raw-hat">${['up', 'left', 'down', 'right'].map((dir, i) => `<span class="preview-key" data-source="hat0${dir}">${['↑', '←', '↓', '→'][i]}</span>`).join('')}</div><span class="small faint">Stick axes appear in the readouts.</span></div>`;
  const m = modelOf(device), art = padArt(m, typeof device === 'object' && device?.vendor === 0x057E);
  return `<svg class="pad-svg model-${m}" viewBox="${art.viewBox}" role="img" aria-label="${esc(MODEL_NAMES[m])} live input diagram">${art.svg}</svg>`;
}

export function paintController(root, state, deadzone = 0.1, threshold = 0.33) {
  const sources = pressedSources(state, threshold);
  root.querySelectorAll('[data-source]').forEach((node) => node.classList.toggle('lit',
    sources.includes(node.dataset.source) || (node.dataset.alt || '').split(' ').some((alt) => alt && sources.includes(alt))));
  for (const [side, names, raw] of [['left', ['leftx', 'lefty'], 0], ['right', ['rightx', 'righty'], 2]]) {
    const x = axisValue(state?.axes, names[0], raw), y = axisValue(state?.axes, names[1], raw + 1);
    const knob = root.querySelector(`[data-stick="${side}"]`), well = +(knob?.dataset.well || 30);
    knob?.setAttribute('transform', `translate(${(x * well * 0.45).toFixed(2)} ${(y * well * 0.45).toFixed(2)})`);
    root.querySelector(`[data-deadzone="${side}"]`)?.setAttribute('r', String(Math.max(0, Math.min(0.95, +deadzone || 0)) * (well - 3)));
    const text = root.querySelector(`[data-axis-readout="${side}"]`);
    if (text) text.textContent = `X ${x.toFixed(2)} · Y ${(-y).toFixed(2)}`;
  }
  return sources;
}
