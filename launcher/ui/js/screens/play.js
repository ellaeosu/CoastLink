import { call } from '../bridge.js';
import { esc, icons, status, when, toast } from '../ui.js';
import { register } from '../nav.js';
import { launch } from '../game.js';

const COLS = 'grid-template-columns:minmax(0,1.4fr) minmax(0,1fr) minmax(0,1fr) minmax(0,1fr)';

export function sessionRows(rows) {
  if (!rows.length) return '<div class="empty">No online sessions yet. Your matches show up here.</div>';
  return rows.map((r) => `<div class="list-row" style="${COLS}"><span style="font-weight:600">${esc(r.opponent)} · ${esc(when(r.stamp))}</span>
    <span>${esc(r.matches)}</span><span class="mono">${esc(r.avg_ping_ms ?? '–')} ms</span>
    <span>${r.sync === 'match' ? status('ok', 'Match') : r.sync === 'check' ? status('warn', 'Check') : status('info', 'Not compared')}</span></div>`).join('');
}

register({
  id: 'play', title: 'Play', icon: 'play',
  leave() { this.viewToken = null; },
  async render(root) {
    const token = this.viewToken = {};
    const current = () => this.viewToken === token && root.isConnected;
    root.innerHTML = `<header class="page-head"><div><h1 style="font-size:34px">Hey, ready for a set?</h1><p>Test offline first, then jump online with your crew.</p></div></header>
    <section class="grid2" aria-label="Start">
      <div class="card red" style="min-height:190px;padding:28px">
        <span class="label" style="color:#000">Online · rollback</span>
        <span style="font:700 30px/1.15 var(--head)">Play with friends</span>
        <span style="font-weight:500">Host, join a room code, or use the shared lobby.</span>
        <button class="btn dark" style="margin-top:auto;align-self:flex-start;min-height:50px" data-go="online" autofocus>Go online ${icons.arrow}</button>
      </div>
      <div class="card outline" style="min-height:190px;padding:28px">
        <span class="label">Offline</span>
        <span style="font:700 30px/1.15 var(--head)">Practice / test run</span>
        <span class="muted">Check controllers and performance before a session.</span>
        <button class="btn" style="margin-top:auto;align-self:flex-start;min-height:50px;border-color:#fff" id="offline">Launch offline</button>
      </div>
    </section>
    <div class="fill" style="display:grid;grid-template-columns:minmax(0,1.5fr) minmax(0,1fr);gap:16px">
      <section class="card" aria-label="Recent sessions">
        <div class="row" style="justify-content:space-between"><h2>Recent sessions</h2><button class="btn" style="min-height:44px" data-go="session">See all</button></div>
        <div class="list-head" style="${COLS}"><span>OPPONENT</span><span>MATCHES</span><span>AVG PING</span><span>SYNC</span></div>
        <div class="col" id="recent"><div class="empty">Loading…</div></div>
      </section>
      <section class="card" aria-label="Before you play"><h2>Before you play</h2><div class="col" id="checks"><div class="small muted">Checking this PC…</div></div>
        <label class="check" style="margin-top:auto">Start the game fullscreen<input type="checkbox" id="fullscreen" disabled></label>
        <button class="btn" data-go="controllers">Set up controllers</button></section>
    </div>`;
    root.querySelector('#offline').onclick = () => launch('offline');
    const full = root.querySelector('#fullscreen');
    call('settings.get').then((s) => { if (!current()) return; full.checked = s.graphics.window !== 'windowed'; full.disabled = false; }).catch(() => {});
    full.onchange = async () => {
      full.disabled = true;
      try {
        await call('settings.save', { settings: { graphics: { window: full.checked ? 'borderless' : 'windowed' } } });
        toast(full.checked ? 'The game starts fullscreen from now on.' : 'The game starts in a window from now on.', 'ok');
      } catch (e) { full.checked = !full.checked; toast(e.message || String(e), 'bad'); }
      finally { if (current()) full.disabled = false; }
    };
    call('sessions', { limit: 3 }).then((rows) => { if (current()) root.querySelector('#recent').innerHTML = sessionRows(rows); })
      .catch((e) => { if (current()) root.querySelector('#recent').textContent = `Recent sessions unavailable: ${e.message || e}`; });
    call('status', {}, { timeout: 20000 }).then((s) => {
      if (!current()) return;
      root.querySelector('#checks').innerHTML = s.checklist.map((c) => `<div class="check-row ${c.level}">${status(c.level, '')}<span class="what">${esc(c.label)}</span><span class="detail">${esc(c.detail)}</span></div>`).join('');
    }).catch((e) => { if (current()) root.querySelector('#checks').innerHTML = status('warn', `Checks unavailable: ${e.message || e}`); });
  },
});
