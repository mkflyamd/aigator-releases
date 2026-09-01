const { contextBridge, ipcRenderer } = require('electron');
contextBridge.exposeInMainWorld('hudControls', {
  minimize:           () => ipcRenderer.invoke('hud:minimize'),
  maximize:           () => ipcRenderer.invoke('hud:maximize'),
  close:              () => ipcRenderer.invoke('hud:close'),
  resizeTo:           (w, h) => ipcRenderer.invoke('hud:resize', w, h),
  setCaptureExcluded: (excluded) => ipcRenderer.invoke('hud:set-capture-excluded', excluded),
  onMinimized:        (cb) => ipcRenderer.on('hud:minimized', cb),
  onRestored:         (cb) => ipcRenderer.on('hud:restored', cb),
});
