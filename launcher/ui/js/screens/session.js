import { call, rust } from '../bridge.js';
import { esc, status, toast, confirmAction, errorText } from '../ui.js';
import { register } from '../nav.js';
import { app } from '../state.js';
import { sessionRows } from './play.js';

const tile = (label, value, sub, id, level) => `<div class="card tight"><span class="small muted">${label}</span><span class="mono" style="font:700 28px var(--mono)" id="${id}">${value}</span><span class="small ${level === 'warn' ? '' : 'faint'}" style="${level === 'warn' ? 'color:var(--amber)' : ''}" id="${id}-sub">${sub}</span></div>`;

register({
  id: 'session', title: 'Session & Verify', icon: 'session',
  leave() { clearInterval(this.timer); this.offDrop?.(); this.offDrop = null; this.viewToken = null; },
  async render(root) {
    const token = this.viewToken = {};
    const current = () => this.viewToken === token && root.isConnected;
    const verify = { mine: null, theirs: null };
    root.innerHTML = `<header class="page-head"><div><h1 style="font-size:34px">Session & Verify</h1><p id="sub">No session running</p></div>
      <div class="row"><button class="btn" id="copy">Copy logs</button><button class="btn" id="leave" style="border-color:var(--amber);color:var(--amber)">Leave session</button></div></header>
      <div id="startup"></div>
      <section aria-label="Players" style="display:grid;grid-template-columns:minmax(0,1fr) 120px minmax(0,1fr);gap:14px">
        <div class="card red tight"><span class="label" style="color:#000" id="p1-l">Player 1</span><span style="font:700 26px var(--head)" id="p1">–</span></div>
        <div class="card tight outline" style="align-items:center;justify-content:center"><span style="font:700 32px var(--head)" id="score">–</span><span class="small muted">matches</span></div>
        <div class="card tight" style="border:2px solid #fff"><span class="label" id="p2-l">Player 2</span><span style="font:700 26px var(--head)" id="p2">–</span></div></section>
      <section aria-label="Connection stats" style="display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:14px">
        ${tile('Ping', '–', '', 's-ping')}${tile('Input delay', '–', 'auto', 's-delay')}${tile('Rollbacks', '–', 'this session', 's-rb')}${tile('Waits for the other PC', '–', '', 's-wait')}</section>
      <div class="fill" style="display:grid;grid-template-columns:minmax(0,1.3fr) minmax(0,1fr);gap:14px">
        <section class="card" aria-label="Verify"><h2>Verify sync with a friend</h2>
          <div class="grid2" style="gap:10px"><button class="drop has" id="mine" style="border-color:var(--blue)"><span><span class="label" style="color:var(--blue)">Your log</span><br><span id="mine-n">Looking…</span></span></button>
            <button class="drop" id="theirs"><span><span class="label">Friend's log</span><br>Drop the file here or click to choose</span></button></div>
          <button class="btn primary" id="compare" disabled>Compare logs</button>
          <div class="tile" id="result"><span class="label">Last result</span><span class="small faint">Extract your friend's Copy logs ZIP, then choose their coastlink_state_….hash.txt. You can also select the matching evidence log.</span></div>
        </section>
        <section class="card" aria-label="Checks"><h2>Live checks</h2><div class="col" id="checks"></div>
          <div class="row"><button class="btn" id="logs">Open logs folder</button></div>
          <h2 style="margin-top:6px">Recent</h2><div class="col" id="recent"></div></section></div>`;

    let refreshing = false;
    const refresh = async () => {
      if (!current() || refreshing) return;
      refreshing = true;
      let l;
      try { l = await call('session.live'); }
      catch (e) { if (current()) root.querySelector('#sub').textContent = `Session status unavailable: ${errorText(e)}`; return; }
      finally { refreshing = false; }
      if (!current()) return;
      const running = l.running;
      app.gameRunning = running;
      root.querySelector('#leave').disabled = !running;
      root.querySelector('#sub').textContent = running ? `${app.gameMode || 'online'} · ${l.route ? (l.route === 'direct' ? 'direct UDP' : 'lobby relay') : 'connecting'}${l.matches ? ` · match ${l.matches}` : ''}` : (l.active ? `Last session · ${l.log}` : 'No session yet');
      const me = l.local_player ?? (app.gameMode === 'join' || app.gameMode === 'lobby-join' ? 1 : 0);
      root.querySelector('#p1-l').textContent = `Player 1 · ${me === 0 ? 'you' : l.opponent || 'them'}`;
      root.querySelector('#p2-l').textContent = `Player 2 · ${me === 1 ? 'you' : l.opponent || 'them'}`;
      root.querySelector('#p1').textContent = me === 0 ? 'You' : (l.opponent || 'Opponent');
      root.querySelector('#p2').textContent = me === 1 ? 'You' : (l.opponent || 'Opponent');
      root.querySelector('#score').textContent = l.matches ?? '–';
      root.querySelector('#s-ping').textContent = l.ping_ms != null ? `${l.ping_ms} ms` : '–';
      root.querySelector('#s-delay').textContent = l.input_delay != null ? `${l.input_delay} fr` : '–';
      root.querySelector('#s-rb').textContent = l.rollbacks ?? '–';
      root.querySelector('#s-wait').textContent = l.stalls ?? '–';
      root.querySelector('#s-wait-sub').textContent = l.stall_ms ? `${(l.stall_ms / 1000).toFixed(1)} s total` : '';
      root.querySelector('#startup').innerHTML = running && app.startup ? `<div class="card tight">${status('info', app.startup)}</div>` : '';
      root.querySelector('#checks').innerHTML = [
        `<div class="check-row ${app.versionMismatch ? 'bad' : 'info'}">${app.versionMismatch ? status('bad', 'Versions differ') : status('info', 'This build')}<span class="what"></span><span class="detail">${app.versionMismatch ? 'someone with your code runs another version' : esc(app.info?.version || app.hello?.version || '')}</span></div>`,
        `<div class="check-row ${l.desyncs ? 'warn' : 'info'}">${status(l.desyncs ? 'warn' : 'info', 'Sync')}<span class="what"></span><span class="detail">${l.desyncs ? `${l.desyncs} checksum(s) differ` : l.frame ? 'no difference reported' : 'waiting for match data'}</span></div>`,
        `<div class="check-row ${l.route ? 'ok' : 'info'}">${status(l.route ? 'ok' : 'info', 'Route')}<span class="what"></span><span class="detail">${l.route === 'direct' ? 'direct · relay backup' : l.route === 'relay' ? 'through the lobby relay' : 'not connected'}</span></div>`,
      ].join('');
    };
    refresh();
    this.timer = setInterval(refresh, 2000);
    call('sessions', { limit: 5 }).then((rows) => { if (current()) root.querySelector('#recent').innerHTML = sessionRows(rows); })
      .catch((e) => { if (current()) root.querySelector('#recent').textContent = `Recent sessions unavailable: ${errorText(e)}`; });

    // ---- verify
    let comparing = false;
    const ready = () => {
      if (!current()) return;
      root.querySelector('#compare').disabled = comparing || !(verify.mine && verify.theirs);
      root.querySelector('#mine').disabled = comparing; root.querySelector('#theirs').disabled = comparing;
    };
    call('verify.latest').then((r) => {
      if (!current() || verify.mine) return;
      verify.mine = r.state; verify.mineRuntime = r.evidence || r.runtime;
      root.querySelector('#mine-n').textContent = r.state ? r.state.split(/[\\/]/).pop() : 'Choose your state log'; ready();
    }).catch((e) => { if (current()) root.querySelector('#mine-n').textContent = `Choose your log (${errorText(e)})`; });
    const setLogs = (selection, mine = false) => {
      if (comparing) { toast('Wait for this comparison to finish before choosing different logs.', 'info'); return; }
      const paths = (Array.isArray(selection) ? selection : [selection]).filter((path) => typeof path === 'string' && path);
      const path = paths.find((name) => /\.hash\.txt$/i.test(name));
      if (!path) { toast('Choose a coastlink_state_….hash.txt file. Evidence logs can be selected with it.', 'warn'); return; }
      const stamp = /coastlink_state_(.+)\.hash\.txt$/i.exec(path)?.[1];
      const runtime = paths.find((name) => name !== path && (stamp ? name.endsWith(`coastlink_evidence_${stamp}.log`) : /coastlink_evidence_.+\.log$/i.test(name)))
        || paths.find((name) => name !== path && (stamp ? name.endsWith(`coastlink_runtime_${stamp}.txt`) : /coastlink_runtime_.+\.txt$/i.test(name)));
      if (mine) { verify.mine = path; verify.mineRuntime = runtime || null; root.querySelector('#mine-n').textContent = path.split(/[\\/]/).pop(); }
      else {
        verify.theirs = path; verify.theirsRuntime = runtime || null;
        const b = root.querySelector('#theirs'); b.classList.add('has'); b.innerHTML = `<span><span class="label">Friend's log</span><br>${esc(path.split(/[\\/]/).pop())}${runtime ? '<br><span class="small muted">Evidence selected</span>' : ''}</span>`;
      }
      ready();
    };
    const choose = async (mine) => {
      try { const paths = await window.__TAURI__.dialog.open({ multiple: true, filters: [{ name: 'CoastLink state and evidence', extensions: ['txt', 'log'] }] }); if (paths && current()) setLogs(paths, mine); }
      catch (e) { if (current()) toast(errorText(e), 'bad'); }
    };
    root.querySelector('#mine').onclick = () => choose(true);
    root.querySelector('#theirs').onclick = () => choose(false);
    window.__TAURI__.event.listen('tauri://drag-drop', (e) => { if (current()) setLogs(e.payload?.paths || []); })
      .then((off) => { if (current()) this.offDrop = off; else off(); })
      .catch((e) => { if (current()) toast(`File drop unavailable. Use Choose: ${errorText(e)}`, 'warn'); });
    root.querySelector('#compare').onclick = async () => {
      const box = root.querySelector('#result');
      comparing = true; ready();
      box.innerHTML = status('info', 'Comparing…');
      try {
        const r = await call('verify', { mine: verify.mine, theirs: verify.theirs, mine_runtime: verify.mineRuntime, theirs_runtime: verify.theirsRuntime }, { timeout: 120000 });
        if (!current()) return;
        const ok = r.report?.ok === true, complete = r.report?.complete_match_verified === true, mismatch = r.report?.verdict === 'mismatch';
        const label = complete ? 'Complete recorded match verified' : ok ? 'Recorded hashes match' : mismatch ? 'Recorded hashes differ' : 'Not enough evidence to verify';
        box.innerHTML = `<span class="label">Result</span>${status(ok ? 'ok' : mismatch ? 'bad' : 'warn', label)}<pre class="small" style="white-space:pre-wrap;margin:0;max-height:160px;overflow:auto">${esc(r.text)}</pre>
          <span class="small faint">Covers the recorded hashes only, not every part of the game state.</span>`;
      } catch (e) { if (current()) box.innerHTML = status('bad', errorText(e)); }
      finally { comparing = false; ready(); }
    };

    root.querySelector('#copy').onclick = async () => { try { const r = await call('logs.bundle'); if (current()) { toast(`Logs saved to ${r.path}`, 'ok', 8000); await rust('open_path', { path: r.path.replace(/[\\/][^\\/]+$/, '') }); } } catch (e) { if (current()) toast(errorText(e), 'bad'); } };
    root.querySelector('#logs').onclick = async () => { try { const r = await call('logs.folder'); if (current()) await rust('open_path', { path: r.path }); } catch (e) { if (current()) toast(errorText(e), 'bad'); } };
    root.querySelector('#leave').onclick = async () => {
      if (!app.gameRunning) { toast('No game is running.', 'info'); return; }
      if (await confirmAction('Leave the session?', 'This closes the game on this PC. Your friend sees that you left.', 'Close the game')) {
        const button = root.querySelector('#leave'); button.disabled = true;
        try { await call('game.stop'); if (current()) { app.gameRunning = false; toast('Game closed.', 'ok'); await refresh(); } }
        catch (e) { if (current()) { button.disabled = false; toast(errorText(e), 'bad'); } }
      }
    };
  },
});
