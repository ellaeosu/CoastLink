// Presentation only. Input is sampled by SDL; this module never navigates or clicks the app.
import { esc } from './ui.js';

export const family = (kind = '') => /PlayStation/i.test(kind) ? 'ps' : /GameCube/i.test(kind) ? 'gc' : /Switch|Joy-Con/i.test(kind) ? 'nin' : 'xbox';
const LABELS = {
  xbox: ['A', 'B', 'X', 'Y', 'LB', 'RB', 'LT', 'RT', 'View', 'Menu'],
  ps: ['×', '○', '□', '△', 'L1', 'R1', 'L2', 'R2', 'Share', 'Options'],
  nin: ['B', 'A', 'Y', 'X', 'L', 'R', 'ZL', 'ZR', '−', '+'],
  gc: ['A', 'X', 'B', 'Y', 'L', 'Z', 'L', 'R', '−', 'Start'],
};

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

export function controllerDiagram(kind, keyboard = false, raw = false) {
  if (keyboard) return `<div class="keyboard-preview" aria-label="Live keyboard preview">${['L', 'ZL', 'MINUS', 'PLUS', 'R', 'ZR', 'UP', 'X', 'Y', 'LEFT', 'DOWN', 'RIGHT', 'A', 'B'].map((c) => `<span data-key-control="${c}" class="preview-key">${esc({ MINUS: '−', PLUS: '+', UP: '↑', DOWN: '↓', LEFT: '←', RIGHT: '→' }[c] || c)}</span>`).join('')}</div>`;
  if (raw) return `<div class="raw-preview"><span class="small faint">Raw joystick · Windows button numbers</span><div class="raw-buttons">${Array.from({length: 12}, (_, i) => `<span class="preview-key" data-source="button${i}">${i}</span>`).join('')}</div><div class="raw-hat">${['up','left','down','right'].map((dir, i) => `<span class="preview-key" data-source="hat0${dir}">${['↑','←','↓','→'][i]}</span>`).join('')}</div><span class="small faint">Stick axes appear in the readouts.</span></div>`;
  const f = family(kind), l = LABELS[f];
  const button = (source, label, x, y, r = 16) => `<g class="pad-control" data-source="${source}" transform="translate(${x} ${y})"><circle r="${r}"/><text y="1">${esc(label)}</text></g>`;
  const shoulder = (src, label, x, y) => `<g class="pad-control pad-shoulder" data-source="${src}" transform="translate(${x} ${y})"><rect x="-34" y="-14" width="68" height="28" rx="9"/><text y="1">${esc(label)}</text></g>`;
  const stick = (side, x, y) => `<g transform="translate(${x} ${y})"><circle class="stick-well" r="31"/><circle class="stick-deadzone" data-deadzone="${side}" r="3"/><path class="stick-cross" d="M-25 0h50M0-25v50"/><g data-stick="${side}" data-source="${side}stick" class="pad-control"><circle class="stick-knob" r="18"/></g></g>`;
  const dpad = (x, y) => `<g transform="translate(${x} ${y})">${[['dpup',0,-17,'↑'],['dpdown',0,17,'↓'],['dpleft',-17,0,'←'],['dpright',17,0,'→']].map(([src,dx,dy,t]) => `<g class="pad-control pad-dpad" data-source="${src}" transform="translate(${dx} ${dy})"><rect x="-10" y="-10" width="20" height="20" rx="4"/><text y="1">${t}</text></g>`).join('')}</g>`;
  const shell = f === 'nin' ? 'M90 91Q67 91 60 119L36 250Q34 279 64 281Q91 281 119 237L159 211H321L361 237Q389 281 416 281Q446 279 444 250L420 119Q413 91 390 91Z' : f === 'gc' ? 'M111 91Q72 89 58 133L37 257Q42 290 71 270L151 211H329L409 270Q438 290 443 257L422 133Q408 89 369 91Z' : 'M105 91Q66 94 55 135L32 246Q27 280 54 286Q80 290 119 236L161 212H319L361 236Q400 290 426 286Q453 280 448 246L425 135Q414 94 375 91Z';
  const lx = f === 'ps' ? 173 : 124, ly = f === 'ps' ? 217 : 150;
  const rx = f === 'gc' ? 291 : 304, ry = 217;
  const face = f === 'gc' ? button('south',l[0],358,158,24) + button('west',l[2],319,178,13) + button('north',l[3],339,120,13) + button('east',l[1],391,132,13) : button('south',l[0],365,186) + button('east',l[1],397,153) + button('west',l[2],333,153) + button('north',l[3],365,120);
  return `<svg class="pad-svg family-${f}" viewBox="0 0 480 318" role="img" aria-label="${esc(kind || 'Controller')} live input diagram"><path class="pad-shell" d="${shell}"/><path class="pad-seam" d="M161 212Q240 185 319 212"/>
    ${shoulder('lefttrigger',l[6],124,36)}${shoulder('righttrigger',l[7],356,36)}${shoulder('leftshoulder',l[4],124,70)}${shoulder('rightshoulder',l[5],356,70)}
    ${stick('left',lx,ly)}${stick('right',rx,ry)}${dpad(f === 'ps' ? 115 : 178, f === 'ps' ? 151 : 222)}${face}
    <g class="pad-control pad-menu" data-source="back" transform="translate(211 133)"><rect x="-24" y="-14" width="48" height="28" rx="9"/><text y="1">${esc(l[8])}</text></g>
    <g class="pad-control pad-menu" data-source="start" transform="translate(269 133)"><rect x="-24" y="-14" width="48" height="28" rx="9"/><text y="1">${esc(l[9])}</text></g>
    <text class="pad-wordmark" x="240" y="177">COASTLINK</text></svg>`;
}

export function paintController(root, state, deadzone = 0.1, threshold = 0.33) {
  const sources = pressedSources(state, threshold);
  root.querySelectorAll('[data-source]').forEach((node) => node.classList.toggle('lit', sources.includes(node.dataset.source)));
  for (const [side, names, raw] of [['left', ['leftx', 'lefty'], 0], ['right', ['rightx', 'righty'], 2]]) {
    const x = axisValue(state?.axes, names[0], raw), y = axisValue(state?.axes, names[1], raw + 1);
    root.querySelector(`[data-stick="${side}"]`)?.setAttribute('transform', `translate(${(x * 13).toFixed(2)} ${(y * 13).toFixed(2)})`);
    root.querySelector(`[data-deadzone="${side}"]`)?.setAttribute('r', String(Math.max(0, Math.min(0.95, +deadzone || 0)) * 27));
    const text = root.querySelector(`[data-axis-readout="${side}"]`);
    if (text) text.textContent = `X ${x.toFixed(2)} · Y ${(-y).toFixed(2)}`;
  }
  return sources;
}
