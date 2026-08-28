const { contextBridge, ipcRenderer } = require('electron');
contextBridge.exposeInMainWorld('hudControls', {
  minimize:    () => ipcRenderer.invoke('hud:minimize'),
  close:       () => ipcRenderer.invoke('hud:close'),
  resizeTo:    (w, h) => ipcRenderer.invoke('hud:resize', w, h),
});
