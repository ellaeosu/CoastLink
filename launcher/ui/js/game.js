// Starting the game (Play and Online share it).
import { call } from './bridge.js';
import { toast, modal, errorText } from './ui.js';
import { app } from './state.js';
import { go } from './nav.js';

export async function launch(mode, args = {}) {
  if (app.gameRunning) { toast('The game is already running.', 'warn'); return false; }
  app.gameLines = []; app.roomCode = ''; app.versionMismatch = false;
  try {
    await call('launch', { mode, ...args });
  } catch (e) {
    const text = errorText(e);
    if (/Shaders are not prepared/.test(text)) {
      const r = await modal({ title: 'Shaders first', body: text, actions: [{ label: 'Cancel', value: false }, { label: 'Launch offline now', value: true, kind: 'primary' }] });
      if (r) return launch('offline');
      return false;
    }
    toast(text, 'bad', 10000);
    return false;
  }
  app.gameRunning = true; app.gameMode = mode;
  toast(mode === 'offline' ? 'Starting the game…' : 'Starting the game and connecting…', 'ok');
  if (mode !== 'offline') go('session');
  return true;
}
