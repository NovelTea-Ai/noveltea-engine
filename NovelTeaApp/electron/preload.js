const { contextBridge, ipcRenderer } = require('electron')

// The desktop client's small bridge: window buttons, opening a link in your browser, and choosing which server to talk to.
// It deliberately has nothing that touches the server or its files.
contextBridge.exposeInMainWorld('electron', {
  minimize: () => ipcRenderer.send('window-minimize'),
  maximize: () => ipcRenderer.send('window-maximize'),
  close: () => ipcRenderer.send('window-close'),
  openExternal: (url) => ipcRenderer.send('open-external', url),
  getServerUrl: () => ipcRenderer.invoke('server:get-url'),
  connectServer: (url) => ipcRenderer.invoke('server:connect', url),
  changeServer: () => ipcRenderer.send('server:change'),
})
