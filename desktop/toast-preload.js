"use strict";


// lib/toast-window.js accepts these messages only from the toast window itself.
const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("fasttToast", Object.freeze({
  onCards: (fn) => ipcRenderer.on("toast:cards", (_e, payload) => fn(payload)),
  open: (id) => ipcRenderer.send("toast:open", String(id)),
  dismiss: (id) => ipcRenderer.send("toast:dismiss", String(id)),
}));
