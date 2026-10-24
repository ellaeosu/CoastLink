// Controller illustrations for the live preview, in the flat style of Ryujinx's input screen: one drawing per model
// (original art, no logos) with the real controller's proportions, button layout and colours, shoulders and triggers
// behind the body, two-tone bodies where the real pad has them (DualSense core, Pro Controller grips). Every pressable
// part carries data-source (SDL gamepad names) so the preview lights it; the stick caps move. Spacing rule: every
// button keeps at least 8 units from its neighbours and from the outline.
import { esc } from './ui.js';

let clipIds = 0;
const part = (src, body, { x = 0, y = 0, rot = 0, label = '', cls = '', alt = '' } = {}) =>
  `<g class="art-part ${cls}" data-source="${src}"${alt ? ` data-alt="${alt}"` : ''} transform="translate(${x} ${y})${rot ? ` rotate(${rot})` : ''}">${body}${
    label ? `<text class="art-label"${rot ? ` transform="rotate(${-rot})"` : ''}>${esc(label)}</text>` : ''}</g>`;
const oct = (r) => Array.from({ length: 8 }, (_, i) => { const a = Math.PI / 8 + i * Math.PI / 4; return `${(Math.cos(a) * r).toFixed(1)},${(Math.sin(a) * r).toFixed(1)}`; }).join(' ');

/** the body outline, an optional second tone clipped to it, then the outline on top */
function body(d, tone = '') {
  const id = `padclip${++clipIds}`;
  return `<defs><clipPath id="${id}"><path d="${d}"/></clipPath></defs><path class="art-body" d="${d}"/>${
    tone ? `<g clip-path="url(#${id})">${tone}</g>` : ''}<path class="art-outline" d="${d}"/>`;
}
function stick(side, x, y, { base = 40, cap = 29, gate = false, label = '', cls = '' } = {}) {
  const well = gate ? `<polygon class="art-well" points="${oct(base)}"/><polygon class="art-well-ring" points="${oct(base - 6)}"/>`
    : `<circle class="art-well" r="${base}"/><circle class="art-well-ring" r="${base - 6}"/>`;
  return `<g transform="translate(${x} ${y})">${well}<circle class="stick-deadzone" data-deadzone="${side}" r="3"/>
    <g class="art-part art-stick ${cls}" data-stick="${side}" data-well="${base - 6}" data-source="${side}stick"><circle class="art-shadow" cy="3" r="${cap}"/><circle class="art-stick-cap" r="${cap}"/><circle class="art-stick-top" r="${cap - 8}"/>${
      label ? `<text class="art-label art-stick-label">${esc(label)}</text>` : ''}</g></g>`;
}
const face = (src, x, y, r, label, cls = '') => part(src, `<circle class="art-shadow" cy="2.5" r="${r}"/><circle class="art-btn-face" r="${r}"/>`, { x, y, label, cls: `art-btn ${cls}` });
const SYM = { tri: '<path class="art-sym art-tri" d="M0 -7.5L7 5H-7Z"/>', cir: '<circle class="art-sym art-cir" r="6.5"/>',
  crs: '<path class="art-sym art-crs" d="M-6 -6L6 6M6 -6L-6 6"/>', sq: '<rect class="art-sym art-sq" x="-6" y="-6" width="12" height="12" rx="1"/>' };
const psFace = (src, x, y, sym, mono) => part(src, `<circle class="art-shadow" cy="2.5" r="17"/><circle class="art-btn-face" r="17"/>${SYM[sym]}`,
  { x, y, cls: `art-btn${mono ? ' art-mono' : ''}` });
/** a plus-shaped D-pad (four pressable arms), optionally in a round recess */
function dpadCross(x, y, { arm = 30, w = 22, base = 0 } = {}) {
  const h = w / 2, a = arm, r = 5;
  const cross = `M${-h} ${-a + r}Q${-h} ${-a} ${-h + r} ${-a}H${h - r}Q${h} ${-a} ${h} ${-a + r}V${-h}H${a - r}Q${a} ${-h} ${a} ${-h + r}V${h - r}Q${a} ${h} ${a - r} ${h}H${h}V${a - r}Q${h} ${a} ${h - r} ${a}H${-h + r}Q${-h} ${a} ${-h} ${a - r}V${h}H${-a + r}Q${-a} ${h} ${-a} ${h - r}V${-h + r}Q${-a} ${-h} ${-a + r} ${-h}H${-h}Z`;
  const hot = `M${-h} ${-h}V${-a + r}Q${-h} ${-a} ${-h + r} ${-a}H${h - r}Q${h} ${-a} ${h} ${-a + r}V${-h}Z`;
  const arm1 = (src, rot) => `<g class="art-part art-dpad-arm" data-source="${src}" transform="translate(${x} ${y}) rotate(${rot})"><path class="art-hot" d="${hot}"/><path class="art-arrow" d="M0 ${-a + 7}l-4.5 6h9z"/></g>`;
  return `${base ? `<circle class="art-dpad-base" cx="${x}" cy="${y}" r="${base}"/>` : ''}<path class="art-shadow" transform="translate(${x} ${y + 2.5})" d="${cross}"/><path class="art-dpad" transform="translate(${x} ${y})" d="${cross}"/>${
    arm1('dpup', 0)}${arm1('dpright', 90)}${arm1('dpdown', 180)}${arm1('dpleft', 270)}`;
}
function dpadArrows(x, y, d = 30) {                     // PlayStation: four separate buttons, tips to the middle
  const one = (src, rot) => `<g class="art-part art-btn" data-source="${src}" transform="translate(${x} ${y}) rotate(${rot}) translate(0 ${-d})"><path class="art-btn-face" d="M-11 -12H11V3L0 13L-11 3Z"/><path class="art-arrow" d="M0 -7l-4.5 6h9z"/></g>`;
  return one('dpup', 0) + one('dpright', 90) + one('dpdown', 180) + one('dpleft', 270);
}
function dpadRound(x, y, d = 30, r = 13) {              // Joy-Con: four round buttons
  const one = (src, dx, dy, rot) => part(src, `<circle class="art-shadow" cy="2" r="${r}"/><circle class="art-btn-face" r="${r}"/><path class="art-arrow" d="M0 -5l-4.5 6h9z" transform="rotate(${rot})"/>`, { x: x + dx, y: y + dy, cls: 'art-btn' });
  return one('dpup', 0, -d, 0) + one('dpright', d, 0, 90) + one('dpdown', 0, d, 180) + one('dpleft', -d, 0, 270);
}
const trigger = (src, label, x, y, w, h, rot) => part(src, `<rect class="art-trigger" x="${-w / 2}" y="${-h / 2}" width="${w}" height="${h}" rx="${Math.min(16, h / 2)}"/>`,
  { x, y, rot, label, cls: 'art-shoulder' });
const bumper = (src, label, d, lx, ly) => `<g class="art-part art-shoulder" data-source="${src}"><path class="art-bumper" d="${d}"/><text class="art-label art-mini" x="${lx}" y="${ly}">${esc(label)}</text></g>`;
const small = (src, x, y, shape, icon = '', rot = 0) => part(src, shape + icon, { x, y, rot, cls: 'art-small-btn' });
const circ = (r) => `<circle class="art-small" r="${r}"/>`;
const rrect = (w, h, r) => `<rect class="art-small" x="${-w / 2}" y="${-h / 2}" width="${w}" height="${h}" rx="${r}"/>`;
const icon = (d) => `<path class="art-icon" d="${d}"/>`;
const HOUSE = icon('M-5 1L0 -4L5 1M-3.5 -0.5V4H3.5V-0.5'), MINUS = icon('M-4 0H4'), PLUS = icon('M-4 0H4M0 -4V4');
// shoulders shared by the Xbox and Pro Controller drawings: bumpers wrap the top corners, triggers sit behind them
const LB = 'M80 150C86 100 138 66 258 60C272 60 274 90 262 92C160 94 116 108 102 154Z', RB = 'M560 150C554 100 502 66 382 60C368 60 366 90 378 92C480 94 524 108 538 154Z';
const shoulders = (names) => `${trigger('lefttrigger', names[0], 164, 38, 96, 44, -8)}${trigger('righttrigger', names[1], 476, 38, 96, 44, 8)}
  ${bumper('leftshoulder', names[2], LB, 184, 77)}${bumper('rightshoulder', names[3], RB, 456, 77)}`;

// ---------------------------------------------------------------- Xbox (One, Series, 360) and the generic pad
const XBOX = 'M320 84C250 84 172 86 128 100C94 111 76 136 68 172C58 218 50 290 54 342C58 390 84 420 114 418C144 416 162 396 182 370C204 352 246 352 320 352C394 352 436 352 458 370C478 396 496 416 526 418C556 420 582 390 586 342C590 290 582 218 572 172C564 136 546 111 512 100C468 86 390 84 320 84Z';
const X360 = 'M320 90C252 88 182 90 138 104C102 116 82 144 74 180C64 228 56 300 62 346C68 394 94 422 126 418C152 414 168 396 188 372C210 356 250 356 320 356C390 356 430 356 452 372C472 396 488 414 514 418C546 422 572 394 578 346C584 300 576 228 566 180C558 144 538 116 502 104C458 90 388 88 320 90Z';
function xbox(m) {
  const x360 = m === 'xbox360', series = m === 'xboxseries';
  const cy = 178, ly = 292;
  return `${shoulders(['LT', 'RT', 'LB', 'RB'])}
    ${body(x360 ? X360 : XBOX)}
    ${stick('left', x360 ? 196 : 198, x360 ? 180 : cy)}${dpadCross(x360 ? 252 : 250, x360 ? 294 : ly, { arm: 30, w: 22, base: 38 })}${stick('right', x360 ? 388 : 390, x360 ? 294 : ly)}
    ${face('south', 442, cy + 35, 17, 'A', x360 ? 'art-f360a' : 'art-xa')}${face('east', 477, cy, 17, 'B', x360 ? 'art-f360b' : 'art-xb')}
    ${face('west', 407, cy, 17, 'X', x360 ? 'art-f360x' : 'art-xx')}${face('north', 442, cy - 35, 17, 'Y', x360 ? 'art-f360y' : 'art-xy')}
    ${x360 ? part('guide', '<circle class="art-small art-guide" r="24"/><circle class="art-ring art-ring-360" r="17"/>', { x: 320, y: 132, cls: 'art-small-btn' })
      + small('back', 268, 140, circ(9), icon('M2 -3.5L-3 0L2 3.5Z')) + small('start', 372, 140, circ(9), icon('M-2 -3.5L3 0L-2 3.5Z'))
      : part('guide', '<circle class="art-small art-guide" r="20"/><circle class="art-ring" r="12"/>', { x: 320, y: 122, cls: 'art-small-btn' })
      + small('back', 276, 166, circ(10), icon('M-4.5 -1.5h5v4.5h-5zM-1.5 -4.5h5v4.5')) + small('start', 364, 166, circ(10), icon('M-4.5 -3h9M-4.5 0h9M-4.5 3h9'))}
    ${series ? small('misc1', 320, 204, rrect(22, 12, 6), icon('M0 3V-3M-2.8 -0.5L0 -3.3L2.8 -0.5')) : ''}`;
}

// ---------------------------------------------------------------- PlayStation (DualSense, DualShock 4, DualShock 3)
const PS5 = 'M320 78C250 78 170 80 120 92C90 100 72 120 64 150C52 200 40 290 44 350C48 400 75 425 108 420C140 415 158 392 172 364C192 340 232 326 320 326C408 326 448 340 468 364C482 392 500 415 532 420C565 425 592 400 596 350C600 290 588 200 576 150C568 120 550 100 520 92C470 80 390 78 320 78Z';
const PS5_CORE = 'M214 160C240 190 400 190 426 160C468 214 462 306 540 440H100C178 306 172 214 214 160Z';      // the black core under the touchpad
const PS4 = 'M320 82C252 82 172 84 124 96C94 104 76 124 68 154C56 202 46 286 50 342C54 390 80 414 112 410C142 406 160 384 174 358C194 336 234 322 320 322C406 322 446 336 466 358C480 384 498 406 528 410C560 414 586 390 590 342C594 286 584 202 572 154C564 124 546 104 516 96C468 84 388 82 320 82Z';
const PS3 = 'M320 96C256 96 182 98 136 108C104 116 86 136 78 164C66 210 56 290 60 342C64 388 88 412 118 408C146 404 162 384 176 360C196 338 236 326 320 326C404 326 444 338 464 360C478 384 494 404 522 408C552 412 576 388 580 342C584 290 574 210 562 164C554 136 536 116 504 108C458 98 384 96 320 96Z';
const L1 = 'M78 146C86 98 136 66 244 60C258 60 260 90 248 92C158 94 116 106 100 150Z', R1 = 'M562 146C554 98 504 66 396 60C382 60 380 90 392 92C482 94 524 106 540 150Z';
function playstation(m) {
  const ps5 = m === 'ps5', ps4 = m === 'ps4', ps3 = m === 'ps3';
  const top = ps5 ? 0 : ps4 ? 4 : 14;
  const dx = ps5 ? 148 : ps4 ? 152 : 154, fx = ps5 ? 492 : ps4 ? 488 : 486, cy = ps3 ? 178 : 176;
  const sy = ps5 ? 268 : ps4 ? 264 : 266, sx = ps5 ? 246 : ps4 ? 248 : 250;
  const touch = ps5 ? 'M-92 -46H92Q100 -46 100 -38V18Q100 40 78 44C40 50 -40 50 -78 44Q-100 40 -100 18V-38Q-100 -46 -92 -46Z'
    : 'M-80 -36H80Q84 -36 84 -32V20Q84 36 66 38C30 42 -30 42 -66 38Q-84 36 -84 20V-32Q-84 -36 -80 -36Z';
  return `${trigger('lefttrigger', 'L2', 152, 34 + top, 92, 42, -6)}${trigger('righttrigger', 'R2', 488, 34 + top, 92, 42, 6)}
    ${bumper('leftshoulder', 'L1', L1, 174, 75 + top)}${bumper('rightshoulder', 'R1', R1, 466, 75 + top)}
    ${body(ps5 ? PS5 : ps4 ? PS4 : PS3, ps5 ? `<path class="art-plate" d="${PS5_CORE}"/>` : '')}
    ${ps3 ? '' : part('touchpad', `<path class="art-touch" d="${touch}"/>`, { x: 320, y: ps5 ? 130 : 132 })}
    ${ps5 ? '<path class="art-lightbar" d="M211 96Q208 140 220 182"/><path class="art-lightbar" d="M429 96Q432 140 420 182"/>' : ps4 ? '<path class="art-lightbar" d="M250 90H390"/>' : ''}
    ${ps3 ? small('back', 282, 154, rrect(26, 10, 3)) + small('start', 358, 154, rrect(26, 10, 3), icon('M-3 -3.5L4 0L-3 3.5Z'))
      : small('back', ps5 ? 198 : 214, ps5 ? 112 : 106, rrect(10, ps5 ? 24 : 20, 5), '', ps5 ? -12 : -8) + small('start', ps5 ? 442 : 426, ps5 ? 112 : 106, rrect(10, ps5 ? 24 : 20, 5), '', ps5 ? 12 : 8)}
    ${dpadArrows(dx, cy)}
    ${psFace('north', fx, cy - 33, 'tri', ps5)}${psFace('east', fx + 33, cy, 'cir', ps5)}${psFace('south', fx, cy + 33, 'crs', ps5)}${psFace('west', fx - 33, cy, 'sq', ps5)}
    ${stick('left', sx, sy, { base: 38, cap: 28 })}${stick('right', 640 - sx, sy, { base: 38, cap: 28 })}
    ${part('guide', circ(ps3 ? 13 : 12), { x: 320, y: ps3 ? 198 : ps5 ? 264 : 260, cls: 'art-small-btn' })}
    ${ps5 ? small('misc1', 320, 298, rrect(24, 8, 4)) : ''}`;
}

// ---------------------------------------------------------------- Nintendo Switch Pro Controller and Joy-Con
const PRO = 'M320 90C252 90 176 90 132 102C98 111 80 134 72 168C62 216 54 290 58 340C62 390 88 418 118 416C148 414 164 394 184 368C206 350 248 350 320 350C392 350 434 350 456 368C476 394 492 414 522 416C552 418 578 390 582 340C586 290 578 216 568 168C560 134 542 111 508 102C464 90 388 90 320 90Z';
const PRO_FACE = 'M146 98C250 84 390 84 494 98C524 176 506 254 484 330C474 372 460 404 432 440H208C180 404 166 372 156 330C134 254 116 176 146 98Z';
function switchPro() {
  return `${shoulders(['ZL', 'ZR', 'L', 'R'])}
    ${body(PRO, `<path class="art-grip" d="M0 0H640V440H0Z"/><path class="art-face" d="${PRO_FACE}"/>`)}
    ${stick('left', 198, 180)}${dpadCross(250, 290, { arm: 30, w: 22, base: 36 })}${stick('right', 390, 290)}
    ${face('north', 442, 145, 17, 'X')}${face('east', 477, 180, 17, 'A')}${face('south', 442, 215, 17, 'B')}${face('west', 407, 180, 17, 'Y')}
    ${small('back', 276, 132, circ(8.5), MINUS)}${small('start', 364, 132, circ(8.5), PLUS)}
    ${small('misc1', 290, 176, rrect(17, 17, 4), '<circle class="art-icon" r="4"/>')}${small('guide', 350, 176, circ(11), HOUSE)}`;
}
const JCL = 'M312 56V404H262C222 404 196 380 196 340V120C196 80 222 56 262 56Z', JCR = 'M328 56H378C418 56 444 80 444 120V340C444 380 418 404 378 404H328Z';
function joycons(m) {
  const left = `${trigger('lefttrigger', 'ZL', 252, 16, 84, 26, -4)}${bumper('leftshoulder', 'L', 'M198 104C201 62 228 36 262 33H310V62H262C236 64 218 80 214 108Z', 286, 46)}
    <path class="art-body art-jc-l" d="${JCL}"/><rect class="art-rail" x="304" y="56" width="8" height="348"/><path class="art-outline" d="${JCL}"/>
    ${small('back', 290, 84, rrect(16, 6, 3))}${stick('left', 254, 142, { base: 34, cap: 25 })}${dpadRound(254, 252)}
    ${small('misc1', 268, 334, rrect(16, 16, 4), '<circle class="art-icon" r="3.5"/>')}`;
  const right = `${trigger('righttrigger', 'ZR', 388, 16, 84, 26, 4)}${bumper('rightshoulder', 'R', 'M442 104C439 62 412 36 378 33H330V62H378C404 64 422 80 426 108Z', 354, 46)}
    <path class="art-body art-jc-r" d="${JCR}"/><rect class="art-rail" x="328" y="56" width="8" height="348"/><path class="art-outline" d="${JCR}"/>
    ${small('start', 350, 84, circ(8), PLUS)}${face('north', 386, 112, 13, 'X')}${face('east', 416, 142, 13, 'A')}${face('south', 386, 172, 13, 'B')}${face('west', 356, 142, 13, 'Y')}
    ${stick('right', 386, 252, { base: 34, cap: 25 })}${small('guide', 372, 334, circ(11), HOUSE)}`;
  if (m === 'joyconl') return `<g transform="translate(66 0)">${left}</g>`;
  if (m === 'joyconr') return `<g transform="translate(-66 0)">${right}</g>`;
  return left + right;
}

// ---------------------------------------------------------------- GameCube (480 x 318: the layout of the overlay picture)
const GC_PARTS = ['M63.2 113.8C63.2 61.8 125.6 40 240 36.8C354.4 40 416.8 61.8 416.8 113.8L416.8 152.8L63.2 152.8Z',
  'M60.6 145L63.2 269.8Q65.8 303.6 94.4 302Q120.4 301 123 269.8L135 190Z', 'M419.4 145L416.8 269.8Q414.2 303.6 385.6 302Q359.6 301 357 269.8L345 190Z'];
const GC_LOBES = [[138.6, 129.4, 78], [341.4, 116.4, 78], [177.6, 212.6, 52], [302.4, 212.6, 52]];
function gamecube(winusb) {
  // PC mode (SDL's layout): Z = right shoulder. Wii U mode (nnpad_gca.c): Z = misc2, the full L / R clicks = the shoulders.
  const shapes = (cls) => GC_PARTS.map((d) => `<path class="${cls}" d="${d}"/>`).join('') + GC_LOBES.map(([x, y, r]) => `<circle class="${cls}" cx="${x}" cy="${y}" r="${r}"/>`).join('');
  const tab = (src, label, x, alt) => part(src, '<path class="art-trigger" d="M-24 18V-6Q-24 -16 -13 -16H13Q24 -16 24 -6V18Z"/>', { x, y: 40, label, cls: 'art-shoulder', alt });
  return `${tab('lefttrigger', 'L', 82, winusb ? 'leftshoulder' : '')}${tab('righttrigger', 'R', 398, winusb ? 'rightshoulder' : '')}
    ${shapes('art-outline-u')}${shapes('art-body')}
    ${part(winusb ? 'misc2' : 'rightshoulder', '<path class="art-bumper" d="M-30 -6Q2 -17 30 9L25 16Q0 -4 -27 1Z"/>', { x: 352, y: 56, label: 'Z', cls: 'art-shoulder art-gc-z' })}
    <circle class="art-contour" cx="138.6" cy="129.4" r="54"/><circle class="art-contour" cx="302.4" cy="212.6" r="32"/><circle class="art-contour" cx="177.6" cy="212.6" r="34"/>
    ${stick('left', 138.6, 129.4, { base: 34, cap: 21, gate: true })}${dpadCross(177.6, 212.6, { arm: 23, w: 15 })}
    ${stick('right', 302.4, 212.6, { base: 23, cap: 15, gate: true, label: 'C', cls: 'art-gc-c' })}
    ${face('south', 352.4, 127.8, 23, 'A', 'art-gc-a')}${face('west', 310.2, 151.2, 13.5, 'B', 'art-gc-b')}
    ${part('east', '<ellipse class="art-shadow" cy="2" rx="10.8" ry="21"/><ellipse class="art-btn-face" rx="10.8" ry="21"/>', { x: 393.5, y: 113, rot: -15, label: 'X', cls: 'art-btn art-gc-xy' })}
    ${part('north', '<ellipse class="art-shadow" cy="2" rx="22.9" ry="10.4"/><ellipse class="art-btn-face" rx="22.9" ry="10.4"/>', { x: 341.4, y: 84.5, rot: -8, label: 'Y', cls: 'art-btn art-gc-xy' })}
    ${small('start', 240, 129.4, circ(8.5))}`;
}

/** { viewBox, svg } for a model key from controller_view.js; winusb: a GameCube adapter port in Wii U mode */
export function padArt(model, winusb = false) {
  if (model === 'gamecube') return { viewBox: '0 0 480 318', svg: gamecube(winusb) };
  if (model.startsWith('ps')) return { viewBox: '0 0 640 440', svg: playstation(model) };
  if (model === 'switchpro') return { viewBox: '0 0 640 440', svg: switchPro() };
  if (model.startsWith('joycon')) return { viewBox: model === 'joyconpair' ? '130 0 380 412' : '190 0 260 412', svg: joycons(model) };
  return { viewBox: '0 0 640 440', svg: xbox(model) };
}
