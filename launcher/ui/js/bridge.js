// The window's link to the Rust shell (invoke) and to the Python backend (JSON lines through the shell).
const T = window.__TAURI__;
const pending = new Map();
const listeners = new Map();
let nextId = 1;

export const rust = (cmd, args = {}) => T.core.invoke(cmd, args);

/** One backend command; resolves with its result, rejects with its readable error. timeout 0 = none. */
export function call(cmd, args = {}, { timeout = 60000 } = {}) {
  const id = nextId++;
  return new Promise((resolve, reject) => {
    pending.set(id, { resolve, reject });
    T.core.invoke('sidecar_send', { line: JSON.stringify({ id, cmd, args }) }).catch((e) => {
      pending.delete(id);
      reject(new Error(String(e)));
    });
    if (timeout) setTimeout(() => {
      if (pending.has(id)) { pending.delete(id); reject(new Error(`No answer from the CoastLink backend (${cmd}).`)); }
    }, timeout);
  });
}

export function on(name, fn) {
  if (!listeners.has(name)) listeners.set(name, new Set());
  listeners.get(name).add(fn);
  return () => listeners.get(name).delete(fn);
}

function emit(name, data) {
  for (const fn of listeners.get(name) || []) {
    try { fn(data); } catch (e) { console.error(e); }
  }
}

T.event.listen('sidecar', (e) => {
  let m;
  try { m = JSON.parse(e.payload); } catch { return; }
  if (m.id !== undefined && pending.has(m.id)) {
    const p = pending.get(m.id);
    pending.delete(m.id);
    if (m.ok) p.resolve(m.result);
    else p.reject(Object.assign(new Error(m.error || 'Something went wrong.'), { kind: m.kind }));
  } else if (m.event) emit(m.event, m);
});
T.event.listen('sidecar-exit', () => emit('backend-exit', {}));
T.event.listen('sidecar-stderr', (e) => console.warn('[backend]', e.payload));
T.event.listen('bootstrap', (e) => emit('bootstrap', e.payload));

export const dialog = {
  open: (options) => T.dialog.open(options),
};
