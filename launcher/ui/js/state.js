// What every screen shares while the app runs.
export const app = {
  info: null, hello: null, status: null,
  gameRunning: false, gameMode: null, gameLines: [], startup: '', roomCode: '', versionMismatch: false,
  update: null,           // the newest signed release found {manifest, newer}
};
