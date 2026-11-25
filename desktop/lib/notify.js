"use strict";


const { isAppOrigin } = require("./origin");

const MAX_TITLE = 120;
const MAX_BODY = 300;
const MAX_ID = 200;
// popouts share the preload and run their own toaster
const DEDUPE_MS = 60_000;
const RATE_WINDOW_MS = 10_000;
const RATE_MAX = 8;
// macOS may never emit `close` for an auto-dismissed banner: a cap, not a leak; the oldest is dropped (its click may then do nothing)
const MAX_LIVE = 20;

function plainText(value, max) {
  if (typeof value !== "string") return "";
  const s = value.replace(/[\u0000-\u001f\u007f]+/g, " ").replace(/\s+/g, " ").trim();
  return s.length > max ? `${s.slice(0, max - 1)}…` : s;
}

function sameOriginPath(href, appOrigin) {
  if (typeof href !== "string" || !href || !appOrigin) return null;
  let u;
  try {
    u = new URL(href, appOrigin);
  } catch {
    return null;
  }
  if (u.origin !== appOrigin) return null;
  return `${u.pathname}${u.search}${u.hash}`;
}

function parsePayload(payload, appOrigin) {
  if (!payload || typeof payload !== "object") return null;
  const title = plainText(payload.title, MAX_TITLE);
  if (!title) return null;
  const id = typeof payload.id === "string" ? payload.id.slice(0, MAX_ID) : "";
  return {
    id,
    title,
    body: plainText(payload.body, MAX_BODY),
    path: sameOriginPath(payload.href, appOrigin),
  };
}

function createNotifier({ Notification, onClick, now = Date.now }) {
  const seen = new Map();
  let recent = [];
  const live = new Set();

  function show(payload, appOrigin) {
    const p = parsePayload(payload, appOrigin);
    if (!p) return false;
    if (!Notification || (typeof Notification.isSupported === "function" && !Notification.isSupported())) {
      return false;
    }
    const t = now();
    for (const [k, at] of seen) if (t - at >= DEDUPE_MS) seen.delete(k);
    if (p.id && seen.has(p.id)) return false;
    recent = recent.filter((at) => t - at < RATE_WINDOW_MS);
    if (recent.length >= RATE_MAX) return false;

    let n;
    try {
      // silent: the page plays its own alert sound
      n = new Notification({ title: p.title, body: p.body, silent: true });
    } catch {
      return false;
    }
    if (p.id) seen.set(p.id, t);
    recent.push(t);
    live.add(n);
    if (live.size > MAX_LIVE) live.delete(live.values().next().value);
    const forget = () => live.delete(n);
    n.on("click", () => {
      forget();
      try {
        onClick(p.path);
      } catch {
      }
    });
    n.on("close", forget);
    n.on("failed", forget);
    try {
      n.show();
    } catch {
      forget();
      return false;
    }
    return true;
  }

  return { show };
}

function registerNotifyIpc({ ipcMain, Notification, getAppOrigin, onClick, now }) {
  const notifier = createNotifier({ Notification, onClick, now });
  ipcMain.handle("shell:notify", (event, payload) => {
    const appOrigin = getAppOrigin();
    const sender = event && event.senderFrame ? event.senderFrame.url : "";
    if (!isAppOrigin(sender, appOrigin)) return false;
    return notifier.show(payload, appOrigin);
  });
  return notifier;
}

module.exports = {
  plainText,
  sameOriginPath,
  parsePayload,
  createNotifier,
  registerNotifyIpc,
  DEDUPE_MS,
  RATE_MAX,
  RATE_WINDOW_MS,
  MAX_TITLE,
  MAX_BODY,
};
