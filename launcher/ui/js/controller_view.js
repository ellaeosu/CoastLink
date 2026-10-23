// Presentation only. Input is sampled by SDL; this module never navigates or clicks the app.
// The live preview draws the controller that is actually connected: pads.py tells the model (the SDL type refined by the
// USB vendor/product ids) and each model has its own outline, layout, labels and button colours. Original line art.
import { esc } from './ui.js';

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

// ---------------------------------------------------------------- drawing primitives (viewBox 480 x 318)
const ctl = (src, x, y, body, label = '', cls = '', rot = 0) =>
  `<g class="pad-control ${cls}" data-source="${src}" transform="translate(${x} ${y})${rot ? ` rotate(${rot})` : ''}">${body}${label ? `<text y="1"${rot ? ` transform="rotate(${-rot})"` : ''}>${esc(label)}</text>` : ''}</g>`;
const circle = (r) => `<circle r="${r}"/>`;
const rect = (w, h, rx) => `<rect x="${-w / 2}" y="${-h / 2}" width="${w}" height="${h}" rx="${rx}"/>`;
const ellipse = (rx, ry) => `<ellipse rx="${rx}" ry="${ry}"/>`;
const octagon = (r) => `<polygon class="stick-well" points="${Array.from({ length: 8 }, (_, i) => { const a = Math.PI / 8 + i * Math.PI / 4; return `${(Math.cos(a) * r).toFixed(1)},${(Math.sin(a) * r).toFixed(1)}`; }).join(' ')}"/>`;

function stick(side, x, y, { well = 30, knob = 18, gate = 'round', cls = '' } = {}) {
  return `<g transform="translate(${x} ${y})">${gate === 'oct' ? octagon(well) : `<circle class="stick-well" r="${well}"/>`}
    <circle class="stick-deadzone" data-deadzone="${side}" r="3"/><path class="stick-cross" d="M${-well + 6} 0h${2 * well - 12}M0 ${-well + 6}v${2 * well - 12}"/>
    <g data-stick="${side}" data-well="${well}" data-source="${side}stick" class="pad-control ${cls}"><circle class="stick-knob" r="${knob}"/><circle class="stick-cap" r="${knob - 6}"/></g></g>`;
}
function dpadCross(x, y, s = 1) {                     // one plus-shaped pad, four pressable arms
  const a = 11 * s, l = 30 * s;
  const arm = (src, d, rot) => `<g class="pad-control pad-dpad" data-source="${src}" transform="translate(${x} ${y}) rotate(${rot})"><path d="M${-a} ${-a}V${-l + 4}Q${-a} ${-l} ${-a + 4} ${-l}H${a - 4}Q${a} ${-l} ${a} ${-l + 4}V${-a}Z"/><path class="pad-arrow" d="M0 ${-l + 8}l-4 6h8z"/></g>`;
  return `<rect class="pad-inset" x="${x - a}" y="${y - a}" width="${2 * a}" height="${2 * a}"/>${arm('dpup', 0, 0)}${arm('dpright', 0, 90)}${arm('dpdown', 0, 180)}${arm('dpleft', 0, 270)}`;
}
function dpadButtons(x, y, gap, shape) {             // four separate buttons (PlayStation arrows, Joy-Con round)
  const btn = (src, dx, dy, rot) => shape === 'round'
    ? ctl(src, x + dx, y + dy, circle(11) + `<path class="pad-arrow" d="M0 -5l-4 6h8z" transform="rotate(${rot})"/>`, '', 'pad-dpad')
    : ctl(src, x + dx, y + dy, `<path d="M-10 -12H10V4L0 14L-10 4Z" transform="rotate(${rot})"/><path class="pad-arrow" d="M0 -6l-4 6h8z" transform="rotate(${rot})"/>`, '', 'pad-dpad');
  return btn('dpup', 0, -gap, 0) + btn('dpright', gap, 0, 90) + btn('dpdown', 0, gap, 180) + btn('dpleft', -gap, 0, 270);
}
function diamond(x, y, gap, r, labels, cls) {         // labels: [south, east, west, north]
  return ctl('south', x, y + gap, circle(r), labels[0], cls[0]) + ctl('east', x + gap, y, circle(r), labels[1], cls[1]) +
    ctl('west', x - gap, y, circle(r), labels[2], cls[2]) + ctl('north', x, y - gap, circle(r), labels[3], cls[3]);
}
const shoulder = (src, label, x, y, w, h, rot, cls = 'pad-shoulder') => ctl(src, x, y, rect(w, h, Math.min(10, h / 2)), label, cls, rot);
const pill = (src, label, x, y, w = 30, h = 14) => ctl(src, x, y, rect(w, h, h / 2), label, 'pad-menu');
const guide = (x, y, r, label = '') => ctl('guide', x, y, circle(r) + `<circle class="pad-ring" r="${r - 4}"/>`, label, 'pad-guide');

// ---------------------------------------------------------------- outlines
const SHELL = {
  xbox: 'M150 92C190 80 290 80 330 92C375 96 405 104 420 122C440 150 455 205 462 245C468 282 440 300 414 288C392 278 372 252 352 232C330 214 300 208 240 208C180 208 150 214 128 232C108 252 88 278 66 288C40 300 12 282 18 245C25 205 40 150 60 122C75 104 105 96 150 92Z',
  x360: 'M146 96C186 84 294 84 334 96C378 100 408 112 424 134C444 166 458 214 462 248C466 284 438 300 410 288C388 278 368 250 348 232C326 216 298 212 240 212C182 212 154 216 132 232C112 250 92 278 70 288C42 300 14 284 18 248C22 214 36 166 56 134C72 112 102 100 146 96Z',
  ps: 'M120 100C170 92 310 92 360 100C395 104 412 116 424 138C440 170 456 220 462 250C468 285 440 302 414 290C392 280 372 250 350 236C320 222 290 236 240 236C190 236 160 222 130 236C108 250 88 280 66 290C40 302 12 285 18 250C24 220 40 170 56 138C68 116 85 104 120 100Z',
  ps5: 'M112 98C160 88 320 88 368 98C404 104 420 118 432 142C448 176 462 226 466 258C470 292 440 306 412 292C390 280 372 252 352 240C322 226 290 240 240 240C190 240 158 226 128 240C108 252 90 280 68 292C40 306 10 292 14 258C18 226 32 176 48 142C60 118 76 104 112 98Z',
  ps3: 'M126 104C172 96 308 96 354 104C392 110 410 124 420 146C434 176 450 224 456 252C462 286 436 302 410 290C390 280 372 252 350 238C322 224 292 232 240 232C188 232 158 224 130 238C108 252 90 280 70 290C44 302 18 286 24 252C30 224 46 176 60 146C70 124 88 110 126 104Z',
  pro: 'M140 96C190 88 290 88 340 96C380 100 404 110 418 130C438 160 452 210 458 248C464 284 438 300 412 290C390 280 372 254 352 236C330 220 300 214 240 214C180 214 150 220 128 236C108 254 90 280 68 290C42 300 16 284 22 248C28 210 42 160 62 130C76 110 100 100 140 96Z',
  gc: 'M130 98C170 84 310 84 350 98C392 112 412 132 424 160C440 196 452 236 446 262C438 292 404 296 384 276C368 260 356 244 338 236C310 226 280 230 240 230C200 230 170 226 142 236C124 244 112 260 96 276C76 296 42 292 34 262C28 236 40 196 56 160C68 132 88 112 130 98Z',
  jcl: 'M232 70V294H178C140 294 122 272 122 238V126C122 92 140 70 178 70Z',
  jcr: 'M248 70H302C340 70 358 92 358 126V238C358 272 340 294 302 294H248Z',
};

const XBOX_FACE = [['A', 'B', 'X', 'Y'], ['face-green', 'face-red', 'face-blue', 'face-yellow']];
const PS_FACE = [['×', '○', '□', '△'], ['face-psblue', 'face-psred', 'face-pspink', 'face-psteal']];
const NIN_FACE = [['B', 'A', 'Y', 'X'], ['', '', '', '']];

function xboxLike(m) {
  const is360 = m === 'xbox360', series = m === 'xboxseries';
  return `<path class="pad-shell" d="${is360 ? SHELL.x360 : SHELL.xbox}"/>
    ${shoulder('lefttrigger', 'LT', 132, 50, 54, 30, -10)}${shoulder('righttrigger', 'RT', 348, 50, 54, 30, 10)}
    ${shoulder('leftshoulder', 'LB', 130, 84, 84, 16, -8)}${shoulder('rightshoulder', 'RB', 350, 84, 84, 16, 8)}
    ${stick('left', 146, 140)}${dpadCross(194, 200, 0.95)}${stick('right', 290, 200)}${diamond(338, 140, 23, 13, ...XBOX_FACE)}
    ${guide(240, is360 ? 124 : 112, is360 ? 17 : 14)}${pill('back', is360 ? 'Back' : 'View', 206, 144, is360 ? 34 : 26, 14)}${pill('start', is360 ? 'Start' : 'Menu', 274, 144, is360 ? 34 : 26, 14)}
    ${series ? pill('misc1', 'Share', 240, 162, 26, 12) : ''}`;
}
function psLike(m) {
  const pad = m !== 'ps3', ps5 = m === 'ps5';
  const labels = ps5 ? ['Create', 'Options'] : m === 'ps4' ? ['Share', 'Options'] : ['Select', 'Start'];
  return `<path class="pad-shell" d="${ps5 ? SHELL.ps5 : m === 'ps3' ? SHELL.ps3 : SHELL.ps}"/>
    ${shoulder('lefttrigger', 'L2', 122, 52, 56, 30, -6)}${shoulder('righttrigger', 'R2', 358, 52, 56, 30, 6)}
    ${shoulder('leftshoulder', 'L1', 120, 86, 70, 16, -4)}${shoulder('rightshoulder', 'R1', 360, 86, 70, 16, 4)}
    ${pad ? ctl('touchpad', 240, 128, rect(ps5 ? 124 : 108, ps5 ? 66 : 58, 12), '', 'pad-touchpad') + (m === 'ps4' ? '<path class="pad-lightbar" d="M196 98H284"/>' : '') : ''}
    ${pad ? pill('back', '', ps5 ? 166 : 172, 110, 10, 22) + pill('start', '', ps5 ? 314 : 308, 110, 10, 22)
          : pill('back', labels[0], 208, 144, 38, 13) + pill('start', labels[1], 272, 144, 38, 13)}
    ${dpadButtons(112, 146, 22, 'arrow')}${diamond(368, 146, 23, 13, ...PS_FACE)}
    ${stick('left', 184, 204, { well: 28, knob: 17 })}${stick('right', 296, 204, { well: 28, knob: 17 })}
    ${guide(240, pad ? 186 : 174, 10)}${ps5 ? pill('misc1', '', 240, 208, 22, 8) : ''}`;
}
function switchPro() {
  return `<path class="pad-shell" d="${SHELL.pro}"/>
    ${shoulder('lefttrigger', 'ZL', 132, 52, 56, 26, -10)}${shoulder('righttrigger', 'ZR', 348, 52, 56, 26, 10)}
    ${shoulder('leftshoulder', 'L', 132, 84, 84, 16, -8)}${shoulder('rightshoulder', 'R', 348, 84, 84, 16, 8)}
    ${stick('left', 148, 142)}${dpadCross(196, 202, 0.9)}${stick('right', 288, 202)}${diamond(336, 142, 23, 13, ...NIN_FACE)}
    ${pill('back', '−', 206, 112, 18, 10)}${pill('start', '+', 274, 112, 18, 10)}
    ${ctl('misc1', 216, 144, rect(14, 14, 3), '', 'pad-menu')}${guide(264, 144, 10)}`;
}
function joycons(m) {
  const left = m !== 'joyconr', right = m !== 'joyconl';
  return `${left ? `<path class="pad-shell" d="${SHELL.jcl}"/>${shoulder('lefttrigger', 'ZL', 170, 38, 60, 22, -6)}${shoulder('leftshoulder', 'L', 172, 60, 76, 14, -3)}
      ${stick('left', 176, 128, { well: 26, knob: 16 })}${dpadButtons(176, 202, 21, 'round')}${pill('back', '−', 214, 88, 16, 8)}${ctl('misc1', 196, 260, rect(14, 14, 3), '', 'pad-menu')}` : ''}
    ${right ? `<path class="pad-shell" d="${SHELL.jcr}"/>${shoulder('righttrigger', 'ZR', 310, 38, 60, 22, 6)}${shoulder('rightshoulder', 'R', 308, 60, 76, 14, 3)}
      ${diamond(304, 128, 21, 11, ...NIN_FACE)}${stick('right', 304, 202, { well: 26, knob: 16 })}${pill('start', '+', 266, 88, 16, 8)}${guide(284, 260, 9)}` : ''}`;
}
function gamecube() {
  return `<path class="pad-shell gc-shell" d="${SHELL.gc}"/>
    ${shoulder('lefttrigger', 'L', 136, 64, 92, 24, -10, 'pad-shoulder gc-trigger')}${shoulder('righttrigger', 'R', 344, 64, 92, 24, 10, 'pad-shoulder gc-trigger')}
    ${shoulder('rightshoulder', 'Z', 352, 92, 54, 12, 8, 'pad-shoulder gc-z')}
    ${stick('left', 146, 146, { well: 30, knob: 17, gate: 'oct' })}${dpadCross(178, 214, 0.62)}${stick('right', 294, 214, { well: 24, knob: 12, gate: 'oct', cls: 'gc-cstick' })}
    ${ctl('south', 350, 150, circle(22), 'A', 'gc-a')}${ctl('west', 314, 182, circle(12), 'B', 'gc-b')}
    ${ctl('east', 388, 136, ellipse(10, 19), 'X', 'gc-xy', -18)}${ctl('north', 342, 110, ellipse(19, 10), 'Y', 'gc-xy', -8)}
    ${ctl('start', 240, 150, circle(8), '', 'pad-menu')}`;
}

/** the live preview: device = a pads.devices row (or a kind string); keyboard / raw: the other two previews */
export function controllerDiagram(device, keyboard = false, raw = false) {
  if (keyboard) return `<div class="keyboard-preview" aria-label="Live keyboard preview">${['L', 'ZL', 'MINUS', 'PLUS', 'R', 'ZR', 'UP', 'X', 'Y', 'LEFT', 'DOWN', 'RIGHT', 'A', 'B'].map((c) => `<span data-key-control="${c}" class="preview-key">${esc({ MINUS: '−', PLUS: '+', UP: '↑', DOWN: '↓', LEFT: '←', RIGHT: '→' }[c] || c)}</span>`).join('')}</div>`;
  if (raw) return `<div class="raw-preview"><span class="small faint">Raw joystick · Windows button numbers</span><div class="raw-buttons">${Array.from({ length: 12 }, (_, i) => `<span class="preview-key" data-source="button${i}">${i}</span>`).join('')}</div><div class="raw-hat">${['up', 'left', 'down', 'right'].map((dir, i) => `<span class="preview-key" data-source="hat0${dir}">${['↑', '←', '↓', '→'][i]}</span>`).join('')}</div><span class="small faint">Stick axes appear in the readouts.</span></div>`;
  const m = modelOf(device);
  const body = m.startsWith('ps') ? psLike(m) : m === 'switchpro' ? switchPro() : m.startsWith('joycon') ? joycons(m) : m === 'gamecube' ? gamecube() : xboxLike(m);
  return `<svg class="pad-svg model-${m}" viewBox="0 0 480 318" role="img" aria-label="${esc(MODEL_NAMES[m])} live input diagram">${body}</svg>`;
}

export function paintController(root, state, deadzone = 0.1, threshold = 0.33) {
  const sources = pressedSources(state, threshold);
  root.querySelectorAll('[data-source]').forEach((node) => node.classList.toggle('lit', sources.includes(node.dataset.source)));
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
