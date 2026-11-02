// What the app's own pages (setup.html, unavailable.html) may ask of the app: the texts, the
// installer's steps, the server's state. The server's pages (the face, /admin, /themes) get it
// too but use none of it.

const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('anyassistant', {
  texts: () => ipcRenderer.invoke('texts'),
  serverState: () => ipcRenderer.invoke('server-state'),
  startServer: () => ipcRenderer.invoke('server-start'),
  retry: () => ipcRenderer.invoke('retry'),
  setup: {
    installDefaults: () => ipcRenderer.invoke('setup:install-defaults'),
    askQuestions: () => ipcRenderer.invoke('setup:ask-questions'),
    install: (answers, startAtLogin) => ipcRenderer.invoke('setup:install', answers, startAtLogin),
    startDevice: () => ipcRenderer.invoke('setup:device-start'),
    skipDevice: () => ipcRenderer.invoke('setup:device-skip'),
    phase: (next) => ipcRenderer.invoke('setup:phase', next),
    servers: () => ipcRenderer.invoke('setup:servers'),
    probe: (host, port) => ipcRenderer.invoke('setup:probe', host, port),
    pair: (host, port, code, pairing) => ipcRenderer.invoke('setup:pair', host, port, code, pairing),
    close: () => ipcRenderer.invoke('setup:close'),
    pairWindow: () => ipcRenderer.invoke('setup:pair-window'),
    on: (event, handler) => ipcRenderer.on('setup:' + event, (e, data) => handler(data)),
  },
});
