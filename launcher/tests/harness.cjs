// Isolated, headless UI harness: every Tauri/backend command is mocked. No game or native window is launched.
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');
const uiRoot = path.resolve(__dirname, '../ui');

async function createHarness({ viewport = { width: 1500, height: 1000 } } = {}) {
  const browser = await chromium.launch({ headless: true, channel: 'msedge' });
  const page = await browser.newPage({ viewport });
  const errors = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await page.addInitScript(() => {
    window.screenRegistry = new Map(); window.mockCalls = []; window.mockRust = []; window.mockLaunches = [];
    window.mockErrors = {}; window.mockResponses = {}; window.mockNavigation = []; window.mockDialog = null;
    window.mockListeners = new Map(); window.mockDropListeners = new Set(); window.mockSuspend = 0;
    window.mockSettings = {
      graphics: { renderer: 'vulkan', window: 'windowed', width: '1280', height: '720', resolution_scale: '1',
        vsync: 'auto', latency: 'normal', profile: 'custom', stats_overlay: 'off', frame_time_overlay: 'off', menu: 'on',
        volume: 'auto', audio_device: 'default', mute_background: 'off' },
      launch: { speed: 'normal', skip_movies: false, input_delay: 'auto' },
    };
    window.mockResponses = {
      'shaders.status': { done: true, read: 521, total: 521 },
      'session.live': { active: false, running: false }, sessions: [],
      status: { checklist: [], status: { ready: true, game_version: '13.0.4' } },
      'audio.devices': [{ name: 'Speakers #2 [USB] = Device' }],
      'verify.latest': { state: 'C:/logs/coastlink_state_20261023_120000.hash.txt', evidence: 'C:/logs/coastlink_evidence_20261023_120000.log', runtime: 'C:/logs/coastlink_runtime_20261023_120000.txt' },
      verify: { report: { ok: false, verdict: 'insufficient_evidence', complete_match_verified: false }, text: 'Not enough evidence.' },
      'logs.folder': { path: 'C:/logs' }, 'logs.bundle': { path: 'C:/logs/CoastLink-logs.zip' },
      'game.stop': { stopped: true },
      'net.test': { reachable: true, lobby_ms: 32, waiting_same_version: 1, waiting_other_version: 0 },
    };
    window.mockCall = async (cmd, args = {}) => {
      window.mockCalls.push({ cmd, args: structuredClone(args) });
      if (window.mockErrors[cmd]) throw new Error(window.mockErrors[cmd]);
      if (window.mockWait?.[cmd]) await new Promise((resolve) => { window.mockResolve ||= {}; window.mockResolve[cmd] = resolve; });
      if (cmd === 'settings.get') return structuredClone(window.mockSettings);
      if (cmd === 'settings.save') {
        for (const [section, patch] of Object.entries(args.settings)) window.mockSettings[section] = { ...window.mockSettings[section], ...patch };
        return structuredClone(window.mockSettings);
      }
      if (cmd === 'shaders.clear') { window.mockResponses['shaders.status'] = { done: false, read: 0, total: 0 }; return { removed: 3 }; }
      if (Object.hasOwn(window.mockResponses, cmd)) return structuredClone(window.mockResponses[cmd]);
      throw new Error(`No mock configured for ${cmd}`);
    };
    window.__TAURI__ = {
      dialog: { open: async () => window.mockDialog },
      event: { listen: async (_name, fn) => { window.mockDropListeners.add(fn); return () => window.mockDropListeners.delete(fn); } },
    };
  });
  await page.route('https://coastlink.test/**', async (route) => {
    const name = decodeURIComponent(new URL(route.request().url()).pathname);
    if (name === '/') return route.fulfill({ contentType: 'text/html', body: '<!doctype html><html><head><link rel="stylesheet" href="/app.css"></head><body><main id="view"><div class="screen" id="test-root"></div></main><div id="toast"></div></body></html>' });
    if (name === '/js/bridge.js') return route.fulfill({ contentType: 'text/javascript', body: `export const call=(cmd,args)=>window.mockCall(cmd,args); export const rust=async(cmd,args)=>{window.mockRust.push({cmd,args});return true;}; export function on(name,fn){if(!window.mockListeners.has(name))window.mockListeners.set(name,new Set());window.mockListeners.get(name).add(fn);return()=>window.mockListeners.get(name).delete(fn);} export const dialog=window.__TAURI__.dialog;` });
    if (name === '/js/nav.js') return route.fulfill({ contentType: 'text/javascript', body: `export function register(screen){window.screenRegistry.set(screen.id,screen);} export function go(id){window.mockNavigation.push(id);} export function suspend(on){window.mockSuspend+=on?1:-1;} export const currentId=()=>window.testCurrent?.id;` });
    if (name === '/js/state.js') return route.fulfill({ contentType: 'text/javascript', body: `export const app=window.mockApp ||= {hello:{version:'0.6.0',status:{game_version:'13.0.4'}},info:{version:'0.6.0'},gameLines:[],gameRunning:false,roomCode:'',versionMismatch:false};` });
    if (name === '/js/game.js') return route.fulfill({ contentType: 'text/javascript', body: `export async function launch(mode,args={}){window.mockLaunches.push({mode,args});return true;}` });
    const target = path.join(uiRoot, name.slice(1));
    if (!target.startsWith(uiRoot + path.sep) || !fs.existsSync(target)) return route.fulfill({ status: 404, body: 'Not found' });
    const type = target.endsWith('.js') ? 'text/javascript' : target.endsWith('.css') ? 'text/css' : target.endsWith('.woff2') ? 'font/woff2' : 'application/octet-stream';
    return route.fulfill({ contentType: type, body: fs.readFileSync(target) });
  });
  await page.goto('https://coastlink.test/');
  const open = async (id) => page.evaluate(async (name) => {
    if (window.testCurrent?.leave) window.testCurrent.leave();
    document.querySelector('#view').innerHTML = '<div class="screen" id="test-root"></div>';
    await import(`/js/screens/${name}.js`);
    window.testCurrent = window.screenRegistry.get(name);
    if (!window.testCurrent) throw new Error(`Screen ${name} did not register`);
    await window.testCurrent.render(document.querySelector('#test-root'));
  }, id);
  const close = async () => { await page.evaluate(() => window.testCurrent?.leave?.()); await browser.close(); };
  return { browser, page, open, close, errors };
}

module.exports = { createHarness };
