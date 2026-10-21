"use strict";

// Preload for our LOCAL trusted Settings page (renderer/config.html), loaded
// from file://. Unlike preload.js (the remote page), this is a page WE ship, so
// it is safe to bridge a small, explicit IPC surface for the settings form
// (which doubles as the load-failure screen).
//
// Every method here maps to an ipcMain.handle in main.js that additionally
// verifies the sender is a file:// frame — so this surface can never be driven
// by the remote your-host.example.com page even if a preload were misconfigured.

const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("fasttNative", Object.freeze({
  // Settings form
  getConfig: () => ipcRenderer.invoke("config:get"),
  saveConfig: (cfg) => ipcRenderer.invoke("config:save", cfg),
  restart: (advanced) => ipcRenderer.invoke("app:restart", advanced),
  quit: () => ipcRenderer.invoke("app:quit"),
}));
