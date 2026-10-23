// Audio: master volume and mute-in-background apply while the game runs (the runtime re-reads graphics.ini every quarter
// second); the output device applies at the next start. Music, effects and voices are the game's own Options > Sound.
import { call } from '../bridge.js';
import { esc, icons, toast, errorText } from '../ui.js';
import { register } from '../nav.js';
import { soundSettings, setSoundSettings, play } from '../sound.js';

let saveQueue = Promise.resolve();

register({
  id: 'audio', title: 'Audio', icon: 'audio',
  leave() { this.flushLive?.(); this.flushLive = null; this.viewToken = null; },
  async render(root) {
    const token = this.viewToken = {};
    const current = () => this.viewToken === token && root.isConnected;
    const [s, devices] = await Promise.all([call('settings.get'), call('audio.devices').catch(() => null)]);
    if (!current()) return;
    const g = s.graphics;
    const vol = g.volume === 'auto' ? 100 : +g.volume;
    const selectedDevice = g.audio_device || 'default';
    const ui = soundSettings();
    const names = [...new Set((devices || []).map((d) => d.name).filter((name) => typeof name === 'string' && name))];
    if (selectedDevice !== 'default' && !names.includes(selectedDevice)) names.push(selectedDevice);
    root.innerHTML = `<header class="page-head"><div><h1 style="font-size:34px">Audio</h1><p>Volume changes apply right away, even mid-match.</p></div>
      <div class="row"><span class="small muted" id="audio-state" role="status">Saved settings</span><button class="btn primary" id="save">${icons.save} Save</button></div></header>
    <div style="display:grid;grid-template-columns:minmax(0,1.2fr) minmax(0,1fr);gap:14px">
      <section class="card" aria-label="Volume" style="gap:22px"><h2>Volume</h2>
        <div class="slider"><div class="top"><label for="vol" style="font-size:16px;font-weight:600">Master</label><span class="mono" id="vol-v">${vol}</span></div><input id="vol" type="range" min="0" max="100" value="${vol}"></div>
        <p class="small muted" style="margin:0">Music, sound effects and voices have their own sliders in the game: Options → Sound. Those are kept with your save data.</p>
        <button class="btn" id="test" style="border-color:#fff;align-self:flex-start">${icons.audio} Test Windows output</button>
      </section>
      <section class="card" aria-label="Output" style="gap:18px"><h2>Output</h2>
        <div class="col" style="gap:6px"><label for="out" style="font-weight:600">Device</label><select id="out" class="input"><option value="default">Windows default output</option>
          ${names.map((n) => `<option value="${esc(n)}" ${n === selectedDevice ? 'selected' : ''}>${esc(n)}</option>`).join('')}</select>
          <span class="small faint">The game device applies next launch. The test sound uses Windows output.${devices ? '' : ' Device list unavailable; your saved choice is kept.'}</span></div>
        <label class="check" style="min-height:48px">Mute when the game is in the background<input type="checkbox" id="mute" ${g.mute_background === 'on' ? 'checked' : ''}></label>
        <div class="divider"></div>
        <label class="check" style="min-height:48px">Menu sounds<input type="checkbox" id="ui-snd" ${ui.on ? 'checked' : ''}></label>
        <div class="slider"><div class="top"><label for="ui-snd-vol">Menu sound volume</label><span class="mono" id="ui-snd-vol-v">${Math.round(ui.volume * 100)}</span></div><input id="ui-snd-vol" type="range" min="0" max="100" value="${Math.round(ui.volume * 100)}"></div>
        <span class="small faint">The app's own clicks and blips. Applies right away; the game's sound is not affected.</span>
      </section></div>`;
    root.querySelector('#ui-snd').addEventListener('change', (e) => { setSoundSettings({ on: e.target.checked }); if (e.target.checked) play('toggleOn'); });
    root.querySelector('#ui-snd-vol').addEventListener('input', (e) => { root.querySelector('#ui-snd-vol-v').textContent = e.target.value; setSoundSettings({ volume: +e.target.value / 100 }); });
    const v = root.querySelector('#vol');
    const state = root.querySelector('#audio-state'), output = root.querySelector('#out');
    let timer = null, revision = 0, savedDevice = selectedDevice;
    const livePatch = () => ({ volume: v.value, mute_background: root.querySelector('#mute').checked ? 'on' : 'off' });
    const write = (patch) => {
      const version = revision;
      if (current()) state.textContent = 'Saving…';
      const request = saveQueue.catch(() => {}).then(() => call('settings.save', { settings: { graphics: patch } }));
      saveQueue = request;
      request.then(() => {
        if (Object.hasOwn(patch, 'audio_device')) savedDevice = patch.audio_device;
        if (current() && version === revision) state.textContent = output.value === savedDevice ? 'Saved' : 'Output change not saved';
      }).catch((e) => { if (current()) { state.textContent = 'Not saved'; toast(errorText(e), 'bad'); } });
      return request;
    };
    const flush = () => { if (timer !== null) { clearTimeout(timer); timer = null; return write(livePatch()); } return null; };
    this.flushLive = flush;
    v.oninput = () => {
      revision++; root.querySelector('#vol-v').textContent = v.value; state.textContent = 'Unsaved changes';
      clearTimeout(timer); timer = setTimeout(flush, 250);
    };
    root.querySelector('#mute').onchange = () => { revision++; write(livePatch()).catch(() => {}); };
    output.onchange = () => { revision++; state.textContent = 'Output change not saved'; };
    root.querySelector('#save').onclick = async () => {
      clearTimeout(timer); timer = null;
      const button = root.querySelector('#save'); button.disabled = true;
      try { await write({ ...livePatch(), audio_device: output.value }); if (current()) toast('Saved.', 'ok'); }
      catch { /* write shows the error and preserves the unsaved state */ }
      finally { if (current()) button.disabled = false; }
    };
    root.querySelector('#test').onclick = async () => {
      const button = root.querySelector('#test'); button.disabled = true;
      let ctx;
      try {
        const Context = window.AudioContext || window.webkitAudioContext;
        if (!Context) throw new Error('Sound preview is unavailable in this window. You can test sound in the game.');
        ctx = new Context(); await ctx.resume();
        const o = ctx.createOscillator(), gain = ctx.createGain();
        o.frequency.value = 660; gain.gain.value = 0.15 * (+v.value / 100);
        o.connect(gain).connect(ctx.destination);
        o.onended = () => { ctx.close().catch(() => {}); if (current()) button.disabled = false; };
        o.start(); o.stop(ctx.currentTime + 0.35);
      } catch (e) {
        if (ctx) ctx.close().catch(() => {});
        if (current()) { button.disabled = false; toast(errorText(e), 'bad'); }
      }
    };
  },
});
