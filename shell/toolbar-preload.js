const { contextBridge, ipcRenderer } = require('electron');

// Exposed to the toolbar page (toolbar.html). Kept minimal — only the
// IPC channels the toolbar needs. Named gatorToolbar to avoid colliding
// with the Gator renderer's window.gatorShell API.
contextBridge.exposeInMainWorld('gatorToolbar', {
  on: (channel, cb) => {
    const wrapped = (_e, ...args) => cb(...args);
    ipcRenderer.on(channel, wrapped);
    return () => ipcRenderer.removeListener(channel, wrapped);
  },
  send: (channel, ...args) => ipcRenderer.send(channel, ...args),
  invoke: (channel, ...args) => ipcRenderer.invoke(channel, ...args),
  // Window controls are NOT wired here. A contextBridge-exposed object is
  // frozen, so the old approach of overriding these per-child from main.js
  // via executeJavaScript silently no-op'd (the child toolbar's close button
  // closed the MAIN window). Instead the toolbar sends generic
  // 'toolbar:minimize'|'toolbar:maximize-toggle'|'toolbar:close' events; main.js
  // routes them to the correct window via e.sender.id (same pattern already
  // used for toolbar:back/forward/reload). 'platform' stays — toolbar.html
  // uses it to hide controls on macOS.
  platform: process.platform,
});
