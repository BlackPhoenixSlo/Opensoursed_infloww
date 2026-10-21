"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const { createToasts, MAX_CARDS, TTL_MS } = require("../lib/toast-window");
const { createNotifier } = require("../lib/notify");

function fakes() {
  const sent = [];
  const listeners = {};
  const timers = [];
  let win = null;
  class FakeWindow {
    constructor() {
      win = this;
      this.visible = false;
      this.destroyed = false;
      this.webContents = {
        once: (_ev, fn) => setImmediate(fn), // did-finish-load
        send: (_ch, cards) => sent.push(cards.map((c) => c.title)),
      };
    }
    setAlwaysOnTop() {}
    setVisibleOnAllWorkspaces() {}
    on() {}
    loadFile() {}
    isDestroyed() {
      return this.destroyed;
    }
    setBounds(b) {
      this.bounds = b;
    }
    isVisible() {
      return this.visible;
    }
    showInactive() {
      this.visible = true;
    }
    hide() {
      this.visible = false;
    }
  }
  const toasts = createToasts({
    BrowserWindow: FakeWindow,
    screen: { getPrimaryDisplay: () => ({ workArea: { x: 0, y: 0, width: 1000, height: 800 } }) },
    ipcMain: { on: (ch, fn) => (listeners[ch] = fn) },
    preload: "p.js",
    html: "t.html",
    setTimer: (fn, ms) => timers.push({ fn, ms }),
  });
  const fromToast = () => ({ sender: win.webContents });
  return { toasts, sent, listeners, timers, fromToast, win: () => win };
}

const tick = () => new Promise((r) => setImmediate(r));

test("cards stack in one non-focusing window; a click opens, a dismiss or the TTL closes", async () => {
  const { toasts, sent, listeners, timers, fromToast, win } = fakes();
  const events = [];
  const a = new toasts.ToastNotification({ title: "A", body: "a" });
  a.on("click", () => events.push("a click"));
  a.on("close", () => events.push("a close"));
  const b = new toasts.ToastNotification({ title: "B", body: "b" });
  b.on("close", () => events.push("b close"));
  const c = new toasts.ToastNotification({ title: "C", body: "c" });
  c.on("close", () => events.push("c close"));
  a.show();
  b.show();
  c.show();
  await tick();
  assert.deepEqual(sent.at(-1), ["A", "B", "C"]);
  assert.equal(win().visible, true);

  listeners["toast:open"]({ sender: {} }, a.id); // not the toast window: ignored
  assert.deepEqual(events, []);
  listeners["toast:open"](fromToast(), a.id);
  listeners["toast:dismiss"](fromToast(), b.id);
  assert.deepEqual(events, ["a click", "b close"]);
  assert.deepEqual(sent.at(-1), ["C"]);

  assert.equal(timers[2].ms, TTL_MS);
  timers[2].fn(); // C expires
  assert.deepEqual(events, ["a click", "b close", "c close"]);
  assert.equal(win().visible, false);
  timers[0].fn(); // A already gone: nothing more
  assert.equal(events.length, 3);
});

test("past MAX_CARDS the oldest card closes", async () => {
  const { toasts, sent } = fakes();
  const closed = [];
  for (let i = 0; i <= MAX_CARDS; i++) {
    const n = new toasts.ToastNotification({ title: `T${i}` });
    n.on("close", () => closed.push(i));
    n.show();
  }
  await tick();
  assert.deepEqual(closed, [0]);
  assert.equal(sent.at(-1).length, MAX_CARDS);
});

test("lib/notify.js drives it as its Notification class: a click routes the href", async () => {
  const { toasts, listeners, fromToast } = fakes();
  const opened = [];
  const notifier = createNotifier({ Notification: toasts.ToastNotification, onClick: (p) => opened.push(p) });
  assert.equal(notifier.show({ id: "1:m5", title: "Fan", body: "hi", href: "/messages-pro/1/5" }, "https://app.example"), true);
  await tick();
  listeners["toast:open"](fromToast(), "1");
  assert.deepEqual(opened, ["/messages-pro/1/5"]);
});
