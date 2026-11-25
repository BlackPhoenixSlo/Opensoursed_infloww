"use strict";


// Every method maps to an ipcMain handler in of-capture.js that verifies a file:// sender, so the remote OnlyFans window cannot drive these.
const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("fasttCapture", Object.freeze({
  getState: () => ipcRenderer.invoke("capture:get-state"),
  finish: () => ipcRenderer.invoke("capture:finish"),
  reopen: () => ipcRenderer.invoke("capture:reopen"),
  cancel: () => ipcRenderer.invoke("capture:cancel"),
  onState: (cb) => {
    const handler = (_e, state) => cb(state);
    ipcRenderer.on("capture:state", handler);
    return () => ipcRenderer.removeListener("capture:state", handler);
  },
}));
