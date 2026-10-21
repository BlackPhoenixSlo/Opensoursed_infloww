"use strict";

// Preload for the toast window (renderer/toast.html, a local page we ship).
// Two one-way messages out (open a card's chat, dismiss a card) and the card
// list in; lib/toast-window.js accepts them only from the toast window itself.

const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("fasttToast", Object.freeze({
  onCards: (fn) => ipcRenderer.on("toast:cards", (_e, payload) => fn(payload)),
  open: (id) => ipcRenderer.send("toast:open", String(id)),
  dismiss: (id) => ipcRenderer.send("toast:dismiss", String(id)),
}));
