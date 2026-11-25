"use strict";


const { contextBridge, ipcRenderer } = require("electron");

// Local trusted page only; each method's ipcMain.handle also checks the sender is a file:// frame, so the remote page can never drive it
contextBridge.exposeInMainWorld("fasttNative", Object.freeze({
  getConfig: () => ipcRenderer.invoke("config:get"),
  saveConfig: (cfg) => ipcRenderer.invoke("config:save", cfg),
  restart: (advanced) => ipcRenderer.invoke("app:restart", advanced),
  quit: () => ipcRenderer.invoke("app:quit"),
}));
