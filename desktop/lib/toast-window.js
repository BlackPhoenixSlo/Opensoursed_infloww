"use strict";


const WIDTH = 360;
// renderer/toast.css: a 66px card + an 8px gap
const CARD_H = 74;
const MARGIN = 12;
const MAX_CARDS = 4;
const TTL_MS = 12000;

// On macOS, Electron 42+ delivers OS notifications only for a code-signed app and our builds are unsigned, so toasts are a window of our own (non-focusable, showInactive: typing elsewhere is never interrupted).
function createToasts({ BrowserWindow, screen, ipcMain, preload, html, setTimer = setTimeout }) {
  let win = null;
  let ready = false;
  let cards = [];
  let seq = 0;

  function bounds() {
    const wa = screen.getPrimaryDisplay().workArea;
    const height = Math.max(1, cards.length) * CARD_H + MARGIN;
    return { x: wa.x + wa.width - WIDTH - MARGIN, y: wa.y + MARGIN, width: WIDTH, height };
  }

  function ensureWindow() {
    if (win && !win.isDestroyed()) return;
    ready = false;
    win = new BrowserWindow({
      ...bounds(),
      frame: false,
      transparent: true,
      resizable: false,
      movable: false,
      minimizable: false,
      maximizable: false,
      fullscreenable: false,
      focusable: false,
      skipTaskbar: true,
      alwaysOnTop: true,
      hasShadow: false,
      show: false,
      webPreferences: { preload, contextIsolation: true, nodeIntegration: false, sandbox: true, devTools: false },
    });
    win.setAlwaysOnTop(true, "floating");
    win.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true });
    win.on("closed", () => {
      win = null;
      ready = false;
    });
    win.webContents.once("did-finish-load", () => {
      ready = true;
      render();
    });
    win.loadFile(html);
  }

  function render() {
    if (!win || win.isDestroyed() || !ready) return;
    if (!cards.length) {
      win.hide();
      return;
    }
    win.setBounds(bounds());
    win.webContents.send("toast:cards", cards.map(({ id, title, body }) => ({ id, title, body })));
    if (!win.isVisible()) win.showInactive();
  }

  function remove(id, why) {
    const card = cards.find((c) => c.id === id);
    if (!card) return;
    cards = cards.filter((c) => c !== card);
    render();
    card.emit(why);
  }

  const fromToastWindow = (event) => !!(win && !win.isDestroyed() && event.sender === win.webContents);
  ipcMain.on("toast:open", (event, id) => {
    if (fromToastWindow(event)) remove(String(id), "click");
  });
  ipcMain.on("toast:dismiss", (event, id) => {
    if (fromToastWindow(event)) remove(String(id), "close");
  });

  class ToastNotification {
    static isSupported() {
      return true;
    }

    constructor({ title, body } = {}) {
      this.id = String(++seq);
      this.title = typeof title === "string" ? title : "";
      this.body = typeof body === "string" ? body : "";
      this.handlers = {};
    }

    on(event, fn) {
      (this.handlers[event] ||= []).push(fn);
      return this;
    }

    emit(event) {
      for (const fn of this.handlers[event] || []) {
        try {
          fn();
        } catch {
        }
      }
    }

    show() {
      cards.push(this);
      while (cards.length > MAX_CARDS) remove(cards[0].id, "close");
      ensureWindow();
      render();
      setTimer(() => remove(this.id, "close"), TTL_MS);
    }
  }

  return { ToastNotification };
}

module.exports = { createToasts, MAX_CARDS, TTL_MS };
