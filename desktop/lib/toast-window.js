"use strict";

// Our own desktop toasts: a small frameless, always-on-top window in the top
// right of the primary screen that stacks the notices (renderer/toast.html).
//
// Why: on macOS, Electron 42+ delivers OS notifications only for a code-signed
// app (lib/signing.js), and our builds are unsigned (README → Signing). A
// window of our own shows either way, the way Infloww's does (transparent,
// alwaysOnTop, non-focusable, showInactive), so typing elsewhere is never
// interrupted.
//
// `ToastNotification` speaks the part of Electron's `Notification` that
// lib/notify.js uses (isSupported, new({title, body}), on("click"|"close"),
// show()), so main.js hands it to registerNotifyIpc in place of the native
// class and the validation, dedupe and click routing stay in one place.
// Electron objects are injected; test/toast-window.test.js drives it.

const WIDTH = 360;
const CARD_H = 74; //  renderer/toast.css: a 66px card + an 8px gap
const MARGIN = 12;
const MAX_CARDS = 4;
const TTL_MS = 12000;

function createToasts({ BrowserWindow, screen, ipcMain, preload, html, setTimer = setTimeout }) {
  let win = null;
  let ready = false;
  let cards = []; // ToastNotification, oldest first
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

  // Take a card off the stack and tell its owner why ("click" or "close").
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
          /* a handler's problem, not the stack's */
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
