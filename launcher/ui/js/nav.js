// Screens, sidebar, and keyboard navigation. Controllers are input-preview only:
// testing a pad must never launch a game, change a setting, or leave this screen.
import { esc, icons } from './ui.js';

const screens = [];
let current = null;
let history = [];
let suspended = 0;

export function register(screen) { screens.push(screen); }
export const currentId = () => current?.id;

export function renderNav() {
  document.getElementById('nav-items').innerHTML = screens.filter((s) => !s.hidden).map((s) =>
    `<button class="nav-item" data-go="${esc(s.id)}" aria-current="${current?.id === s.id ? 'page' : 'false'}">${icons[s.icon] || ''}${esc(s.title)}</button>`).join('');
}

export async function go(id, { push = true, params } = {}) {
  const next = screens.find((s) => s.id === id);
  if (!next) return;
  if (current && current.leave) { try { current.leave(); } catch (e) { console.error(e); } }
  if (push && current && current.id !== id) history.push(current.id);
  current = next;
  renderNav();
  const view = document.getElementById('view');
  view.innerHTML = '<div class="screen"></div>';
  const root = view.firstElementChild;
  try {
    await next.render(root, params || {});
  } catch (e) {
    root.innerHTML = `<div class="card"><h2>This screen could not load</h2><p class="muted">${esc(e.message || e)}</p></div>`;
  }
  view.scrollTop = 0;
  const first = root.querySelector('[autofocus]') || null;
  (first || view).focus({ preventScroll: true });
}

export function back() {
  const modal = document.querySelector('.modal-back');
  if (modal) { modal.closeModal?.(null); return; }
  const prev = history.pop();
  if (prev) go(prev, { push: false });
  else if (current?.id !== 'play') go('play', { push: false });
}

/** Controllers screen: while a binding listens for a press, pad buttons must not navigate. */
export const suspend = (on) => { suspended += on ? 1 : -1; if (suspended < 0) suspended = 0; };

// ---------------------------------------------------------------- spatial focus movement
const FOCUSABLE = 'button:not(:disabled), a[href], input:not(:disabled), select:not(:disabled), [tabindex="0"]';
function visible(el) {
  const r = el.getBoundingClientRect();
  return r.width > 0 && r.height > 0 && getComputedStyle(el).visibility !== 'hidden';
}
function scope() { return document.querySelector('.modal-back .modal') || document.querySelector('#setup') || document.body; }

export function move(dir) {
  const items = [...scope().querySelectorAll(FOCUSABLE)].filter(visible);
  const active = document.activeElement && items.includes(document.activeElement) ? document.activeElement : null;
  if (!active) { items[0]?.focus(); return; }
  const a = active.getBoundingClientRect();
  const ax = a.left + a.width / 2, ay = a.top + a.height / 2;
  let best = null, bestScore = Infinity;
  for (const el of items) {
    if (el === active) continue;
    const r = el.getBoundingClientRect();
    const x = r.left + r.width / 2, y = r.top + r.height / 2;
    const dx = x - ax, dy = y - ay;
    const along = { left: -dx, right: dx, up: -dy, down: dy }[dir];
    if (along <= 4) continue;
    const across = dir === 'left' || dir === 'right' ? Math.abs(dy) : Math.abs(dx);
    const score = along + across * 2.2;
    if (score < bestScore) { bestScore = score; best = el; }
  }
  if (best) { best.focus(); best.scrollIntoView({ block: 'nearest', inline: 'nearest' }); }
}

export function installNavigation() {
  document.addEventListener('click', (e) => {
    const goto = e.target.closest('[data-go]');
    if (goto) { e.preventDefault(); go(goto.dataset.go); }
  });
  document.addEventListener('keydown', (e) => {
    if (suspended) return;
    const el = document.activeElement;
    const typing = el && (el.tagName === 'INPUT' && !['range', 'checkbox', 'radio'].includes(el.type));
    if (e.key === 'Escape' && !typing) { back(); e.preventDefault(); return; }
    if (typing || e.altKey || e.ctrlKey) return;
    const dir = { ArrowLeft: 'left', ArrowRight: 'right', ArrowUp: 'up', ArrowDown: 'down' }[e.key];
    if (!dir) return;
    if ((dir === 'left' || dir === 'right') && el && (el.type === 'range' || el.tagName === 'SELECT')) return;   // (native)
    move(dir); e.preventDefault();
  });
}
