import { call } from '../bridge.js';
import { esc, status, toast, errorText } from '../ui.js';
import { register } from '../nav.js';
import { launch } from '../game.js';
import { app } from '../state.js';

const MODES = [
  { id: 'lobby', title: 'Shared lobby', pill: 'Recommended', text: 'Same private code on both PCs. Goes direct when it can, relay if not.' },
  { id: 'host', title: 'Host a room', text: 'Get a room code and send it to your friend.' },
  { id: 'join', title: 'Join a room', text: "Paste the code from the host's screen." },
];
const DEFAULT_SERVER = 'opensmash-lobby.duckdns.org:39500';
const saved = () => { try { return JSON.parse(localStorage.getItem('online') || '{}'); } catch { return {}; } };
const remember = (v) => { try { localStorage.setItem('online', JSON.stringify(v)); } catch { /* private storage off */ } };

function mismatchText(r, mine) {
  const theirs = r.other_versions?.length ? r.other_versions.join(' or ') : 'another version';
  return `Someone with this lobby code is on ${theirs}, you're on ${mine}. Both of you need the same version (Updates & build).`;
}

register({
  id: 'online', title: 'Online', icon: 'online',
  leave() { this.viewToken = null; },
  async render(root) {
    const token = this.viewToken = {};
    const current = () => this.viewToken === token && root.isConnected;
    const st = { mode: 'lobby', role: 'host', code: '', room: '', server: DEFAULT_SERVER, name: '', ...saved() };
    if (!MODES.some((mode) => mode.id === st.mode)) st.mode = 'lobby';
    if (!['host', 'join'].includes(st.role)) st.role = 'host';
    for (const key of ['code', 'room', 'server', 'name']) if (typeof st[key] !== 'string') st[key] = '';
    const [settings, live] = await Promise.all([call('settings.get'), call('session.live').catch(() => ({}))]);
    if (!current()) return;
    const version = app.hello?.version?.replace(/-.*/, '') || app.info?.version || '';
    const game = app.hello?.status?.game_version || '13.0.4';
    root.innerHTML = `<header class="page-head"><div><h1 style="font-size:34px">Online</h1><p>Both players need the same CoastLink version (${esc(version)}), the same update (${esc(game)}) and the same DLC.</p></div></header>
    <div role="radiogroup" aria-label="Connection mode" class="grid3" id="modes"></div>
    <div class="fill" style="display:grid;grid-template-columns:minmax(0,1.3fr) minmax(0,1fr);gap:14px">
      <section class="card" aria-label="Connect" id="connect" style="gap:18px"></section>
      <section class="card" aria-label="Connection"><h2>Last connection</h2>
        <div class="grid2" style="gap:10px"><div class="tile"><span class="small muted">Ping</span><span class="big" id="t-ping">${live.ping_ms != null ? live.ping_ms + ' ms' : '–'}</span></div>
          <div class="tile"><span class="small muted">Route</span><span class="big" style="font-size:22px" id="t-route">${live.route === 'direct' ? 'Direct' : live.route === 'relay' ? 'Relay' : '–'}</span></div></div>
        <div class="col" style="gap:6px"><label for="delay" style="font-weight:600">Online input delay</label>
          <select id="delay" class="input"><option value="auto">Auto${live.input_delay != null ? ` (${live.input_delay} frames last time)` : ' (from the ping)'}</option><option value="lower">1 frame lower</option><option value="higher">1 frame higher</option></select>
          <span class="small faint">Lower feels snappier but rolls back more. Each PC picks its own.</span></div>
        <div class="tile" style="flex-direction:row;align-items:center;gap:10px" id="version-row">${status('info', `This PC: CoastLink ${version} · game ${game}`)}</div>
      </section></div>`;
    const delay = root.querySelector('#delay');
    let savedDelay = settings.launch?.input_delay || 'auto';
    delay.value = savedDelay;
    delay.onchange = async () => {
      const value = delay.value; delay.disabled = true;
      try {
        await call('settings.save', { settings: { launch: { input_delay: value } } });
        savedDelay = value; if (current()) toast('Input delay saved. It applies to the next game launch.', 'ok');
      } catch (e) { if (current()) { delay.value = savedDelay; toast(errorText(e), 'bad'); } }
      finally { if (current()) delay.disabled = false; }
    };
    const save = () => remember({ mode: st.mode, role: st.role, code: st.code, room: st.room, server: st.server, name: st.name });

    const renderModes = () => {
      root.querySelector('#modes').innerHTML = MODES.map((m) => `<button type="button" role="radio" class="choice" aria-checked="${st.mode === m.id}" data-mode="${m.id}">
        <span class="title">${esc(m.title)}${m.pill ? `<span class="pill">${esc(m.pill)}</span>` : ''}</span><span class="small muted">${esc(m.text)}</span></button>`).join('');
      root.querySelectorAll('[data-mode]').forEach((b) => b.onclick = () => { st.mode = b.dataset.mode; save(); renderModes(); renderConnect(); });
    };
    const renderConnect = () => {
      const box = root.querySelector('#connect');
      const advanced = `<details class="col"><summary class="small" style="cursor:pointer;min-height:30px">More options</summary>
        <div class="grid2" style="margin-top:8px"><div class="col" style="gap:6px"><label class="label" for="name">Your name</label><input id="name" class="input" maxlength="32" value="${esc(st.name)}" placeholder="Shown to the other player"></div>
        ${st.mode === 'lobby' ? `<div class="col" style="gap:6px"><label class="label" for="server">Lobby server</label><input id="server" class="input mono" value="${esc(st.server)}"></div>` : ''}</div></details>`;
      if (st.mode === 'lobby') {
        box.innerHTML = `<div class="col"><label class="label" for="code">Lobby code</label><input id="code" class="input code" value="${esc(st.code)}" placeholder="pick-a-code" maxlength="64" autocomplete="off"></div>
          <div class="col"><span class="label" id="role-l">Your role</span><div class="seg" role="radiogroup" aria-labelledby="role-l" style="grid-template-columns:1fr 1fr">
            <button role="radio" aria-checked="${st.role === 'host'}" data-role="host">Host (player 1)</button><button role="radio" aria-checked="${st.role === 'join'}" data-role="join">Join (player 2)</button></div>
            <span class="small faint">One of you hosts, the other joins. Don't both pick Host.</span></div>${advanced}`;
      } else if (st.mode === 'host') {
        box.innerHTML = `<div class="col"><span class="label">Room code</span><div class="input code row" id="room" style="align-items:center">${esc(app.roomCode || 'Shown here once the game is up')}</div>
          <span class="small faint">Launch, then send this code to your friend. It also shows in the game window.</span></div>
          <div class="row"><button class="btn" id="copy" ${app.roomCode ? '' : 'disabled'}>Copy code</button></div>${advanced}`;
      } else {
        box.innerHTML = `<div class="col"><label class="label" for="room-in">Host's room code</label><input id="room-in" class="input code" value="${esc(st.room || '')}" placeholder="XXXXX-XXXXX" maxlength="11" autocomplete="off"></div>${advanced}`;
      }
      box.insertAdjacentHTML('beforeend', `<div class="row"><button class="btn primary big grow" id="go">Connect & launch</button>
        ${st.mode === 'lobby' ? '<button class="btn big" id="test">Test connection</button>' : ''}</div><div id="test-out" class="col small"></div>`);
      box.querySelectorAll('[data-role]').forEach((b) => b.onclick = () => { st.role = b.dataset.role; save(); renderConnect(); });
      const bind = (sel, key) => { const el = box.querySelector(sel); if (el) el.oninput = () => { st[key] = el.value.trim(); save(); }; };
      bind('#code', 'code'); bind('#name', 'name'); bind('#server', 'server'); bind('#room-in', 'room');
      box.querySelector('#copy')?.addEventListener('click', async () => {
        try { await navigator.clipboard.writeText(app.roomCode); if (current()) toast('Room code copied.', 'ok'); }
        catch (e) { if (current()) toast(errorText(e), 'bad'); }
      });
      box.querySelector('#go').onclick = async () => {
        const args = { name: st.name };
        let mode = st.mode;
        if (mode === 'lobby') {
          if (!/^[A-Za-z0-9_-]{4,64}$/.test(st.code)) { toast('Pick a lobby code of 4–64 letters, numbers, - or _ and use the same one on both PCs.', 'warn'); return; }
          mode = st.role === 'host' ? 'lobby-host' : 'lobby-join'; args.code = st.code; args.server = st.server || DEFAULT_SERVER;
        } else if (mode === 'join') {
          if (!/^[0-9A-Za-z]{5}-?[0-9A-Za-z]{5}$/.test(st.room || '')) { toast("Enter the host's 10-character room code (XXXXX-XXXXX).", 'warn'); return; }
          args.code = st.room;
        }
        await launch(mode, args);
      };
      box.querySelector('#test')?.addEventListener('click', async () => {
        if (!/^[A-Za-z0-9_-]{4,64}$/.test(st.code)) { toast('Enter your private lobby code first, using 4–64 letters, numbers, - or _.', 'warn'); return; }
        const key = `${st.server || DEFAULT_SERVER}|${st.code}`;
        const out = box.querySelector('#test-out');
        const button = box.querySelector('#test'); button.disabled = true;
        out.innerHTML = status('info', 'Testing…');
        try {
          const r = await call('net.test', { server: st.server || DEFAULT_SERVER, code: st.code }, { timeout: 40000 });
          if (!current() || !out.isConnected || key !== `${st.server || DEFAULT_SERVER}|${st.code}`) return;
          if (!r.reachable || r.error) { out.innerHTML = status('bad', r.error || 'The lobby did not answer.'); return; }
          const rows = [status('ok', `Lobby reachable · ${r.lobby_ms} ms to the lobby`)];
          rows.push(r.waiting_same_version ? status('ok', `${r.waiting_same_version} player(s) on your version with this code right now`) : status('info', 'Nobody with this code is online yet'));
          if (r.waiting_other_version) {
            rows.push(status('bad', mismatchText(r, version)));
            root.querySelector('#version-row').innerHTML = status('bad', 'Versions differ');
          }
          out.innerHTML = rows.map((x) => `<div>${x}</div>`).join('');
        } catch (e) { if (current() && out.isConnected) out.innerHTML = status('bad', errorText(e)); }
        finally { if (current() && button.isConnected) button.disabled = false; }
      });
    };
    renderModes(); renderConnect();
    if (app.versionMismatch) root.querySelector('#version-row').innerHTML = status('bad', 'Someone with your code is on a different CoastLink version. Both of you need the same version.');
  },
});
