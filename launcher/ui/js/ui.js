// Shared helpers: escaping, icons, status (icon + word, never colour alone), toasts, dialogs, formatting.
export const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

const svg = (body, { size = 20, width = 2, fill = 'none', extra = '' } = {}) =>
  `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="${fill}" stroke="currentColor" stroke-width="${width}" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" ${extra}>${body}</svg>`;

export const icons = {
  play: svg('<path d="M7 4l13 8-13 8z"/>', { width: 2.2 }),
  online: svg('<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18"/>'),
  pad: svg('<path d="M6 7h12a4 4 0 0 1 4 4v2a5 5 0 0 1-9 3h-2a5 5 0 0 1-9-3v-2a4 4 0 0 1 4-4z"/><path d="M7 10v4M5 12h4"/><circle cx="16" cy="11" r="0.8"/><circle cx="18" cy="13" r="0.8"/>'),
  display: svg('<rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8M12 16v4"/>'),
  audio: svg('<path d="M4 9h4l5-4v14l-5-4H4z"/><path d="M17 9a4 4 0 0 1 0 6M19.5 6.5a8 8 0 0 1 0 11"/>'),
  session: svg('<path d="M3 20h18M6 16v-5M11 16V6M16 16v-7M21 16v-3"/>'),
  updates: svg('<path d="M12 4v11M7 10l5 5 5-5M4 20h16"/>'),
  arrow: svg('<path d="M5 12h14M13 6l6 6-6 6"/>', { size: 18, width: 2.5 }),
  refresh: svg('<path d="M20 12a8 8 0 1 1-2.3-5.7"/><path d="M20 4v5h-5"/>', { size: 18, width: 2.2 }),
  save: svg('<path d="M5 4h11l3 3v13H5z"/><path d="M8 4v5h7V4M8 20v-6h8v6"/>', { size: 18, width: 2.2 }),
  trash: svg('<path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13"/>', { size: 18, width: 2.2 }),
  folder: svg('<path d="M3 6h6l2 2h10v11H3z"/>', { size: 18 }),
  copy: svg('<rect x="8" y="8" width="12" height="12" rx="2"/><path d="M4 16V4h12"/>', { size: 18 }),
  ok: svg('<path d="M5 12l5 5 9-10"/>', { size: 18, width: 3 }),
  warn: svg('<path d="M12 4l9 16H3z"/><path d="M12 10v4M12 17v.5"/>', { size: 18, width: 2.5 }),
  bad: svg('<circle cx="12" cy="12" r="9"/><path d="M9 9l6 6M15 9l-6 6"/>', { size: 18, width: 2.5 }),
  info: svg('<circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8v.5"/>', { size: 18, width: 2.5 }),
};

/** A status: icon + word (+ colour). level: ok | warn | bad | info */
export function status(level, text) {
  const icon = { ok: icons.ok, warn: icons.warn, bad: icons.bad, info: icons.info }[level] || icons.info;
  return `<span class="status ${level === 'info' ? 'ok' : esc(level)}">${icon}<span>${esc(text)}</span></span>`;
}

export function toast(message, level = 'info', ms = 4200) {
  const box = document.getElementById('toast');
  const el = document.createElement('div');
  el.className = 'toast';
  el.setAttribute('role', level === 'bad' ? 'alert' : 'status');
  el.innerHTML = `${status(level, level === 'bad' ? 'Error' : level === 'warn' ? 'Note' : level === 'ok' ? 'Done' : 'Info')}<span style="flex:1">${esc(message)}</span>`;
  box.appendChild(el);
  setTimeout(() => el.remove(), ms);
}

/** A dialog: actions = [{label, value, kind}] -> resolves with the chosen value (null when closed with Esc / B). */
export function modal({ title, body = '', html = '', actions = [{ label: 'OK', value: true, kind: 'primary' }] }) {
  return new Promise((resolve) => {
    const back = document.createElement('div');
    back.className = 'modal-back';
    back.innerHTML = `<div class="modal" role="dialog" aria-modal="true" aria-label="${esc(title)}">
      <h2>${esc(title)}</h2>${body ? `<p class="muted" style="margin:0">${esc(body)}</p>` : ''}${html}
      <div class="row" style="justify-content:flex-end">${actions.map((a, i) => `<button class="btn ${esc(a.kind || '')}" data-i="${i}">${esc(a.label)}</button>`).join('')}</div></div>`;
    const prev = document.activeElement;
    const close = (value) => { back.remove(); document.removeEventListener('keydown', key, true); prev?.focus?.(); resolve(value); };
    const key = (e) => { if (e.key === 'Escape') { e.stopPropagation(); close(null); } };
    back.addEventListener('click', (e) => {
      const b = e.target.closest('button[data-i]');
      if (b) close(actions[+b.dataset.i].value);
      else if (e.target === back) close(null);
    });
    document.addEventListener('keydown', key, true);
    back.closeModal = close;
    document.body.appendChild(back);
    (back.querySelector('button.primary') || back.querySelector('button'))?.focus();
  });
}

export const confirmAction = (title, body, label = 'Continue') =>
  modal({ title, body, actions: [{ label: 'Cancel', value: false }, { label, value: true, kind: 'primary' }] });

/** "today 2:18 pm" from a 20261022_141819 stamp */
export function when(stamp) {
  const m = /^(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})/.exec(stamp || '');
  if (!m) return '';
  const d = new Date(+m[1], +m[2] - 1, +m[3], +m[4], +m[5]);
  const today = new Date(); const y = new Date(); y.setDate(today.getDate() - 1);
  const time = d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' }).toLowerCase();
  if (d.toDateString() === today.toDateString()) return `today ${time}`;
  if (d.toDateString() === y.toDateString()) return `yesterday ${time}`;
  return d.toLocaleDateString([], { month: 'short', day: 'numeric' }) + ' ' + time;
}

export const pct = (a, b) => (b ? Math.max(0, Math.min(100, Math.round((a / b) * 100))) : 0);
export const errorText = (e) => (e && e.message) || String(e);
