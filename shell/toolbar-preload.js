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
  // Window controls (for custom title bar buttons)
  platform: process.platform,
  minimize: () => ipcRenderer.invoke('win:minimize'),
  maximizeToggle: () => ipcRenderer.invoke('win:maximize-toggle'),
  close: () => ipcRenderer.invoke('win:close'),
  isMaximized: () => ipcRenderer.invoke('win:is-maximized'),
});
