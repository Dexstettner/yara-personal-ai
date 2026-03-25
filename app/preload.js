const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('electronAPI', {
  // Receber eventos do main process
  onHotkeyListen: (cb) => ipcRenderer.on('hotkey-listen', cb),
  onBackendDisconnected: (cb) => ipcRenderer.on('backend-disconnected', cb),

  // Enviar eventos ao main process
  savePosition: (x, y) => ipcRenderer.send('save-position', { x, y }),
  minimizeToTray: () => ipcRenderer.send('minimize-to-tray'),
  getConfig: () => ipcRenderer.invoke('get-config'),
  getPosition: () => ipcRenderer.invoke('get-position'),
  moveWindow: (x, y) => ipcRenderer.send('move-window', { x, y }),
});
