"use strict";

// Native notifications for the hosted page (roadmap W3 row 3.3).
//
// The page calls `window.fasttShell.notify({id, title, body, href})` (preload.js)
// and the main process shows an Electron `Notification` — not the web
// `Notification`, whose permission state never reached "granted" in packaged
// builds. This module holds the IPC wiring and the parts worth testing without
// Electron: sender check, plain-text capping, dedupe/rate limit by id, and the
// "same-origin path only" rule for the click target. Electron objects are
// injected.

const { isAppOrigin } = require("./origin");

const MAX_TITLE = 120;
const MAX_BODY = 300;
const MAX_ID = 200;
const DEDUPE_MS = 60_000; //      popouts share the preload and run their own toaster
const RATE_WINDOW_MS = 10_000;
const RATE_MAX = 8; //            per RATE_WINDOW_MS, across all ids
// Notifications we keep referenced so their click handler survives GC. macOS
// may never emit `close` for an auto-dismissed banner, so this is a cap, not a
// leak: past it the OLDEST is dropped (a click on that one may then do nothing).
const MAX_LIVE = 20;

/** Plain text: control characters dropped, whitespace collapsed, capped at `max`. */
function plainText(value, max) {
  if (typeof value !== "string") return "";
  const s = value.replace(/[\u0000-\u001f\u007f]+/g, " ").replace(/\s+/g, " ").trim();
  return s.length > max ? `${s.slice(0, max - 1)}…` : s;
}

/** A path on `appOrigin` ("/x?y#z") for `href`, or null for anything else
 *  (other origins, protocol-relative "//host", javascript:, garbage). */
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

/**
 * Validate a page payload. Returns `{ id, title, body, path }` or null.
 * `title` is required; `id` keys the dedupe; `path` is null when `href` is
 * missing or not a same-origin path.
 */
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

/**
 * createNotifier({ Notification, onClick, now }) → { show(payload, appOrigin) }
 *
 * `Notification` is Electron's main-process class; `onClick(path|null)` focuses
 * the app and opens `path`. `show` returns true when a notification was shown.
 */
function createNotifier({ Notification, onClick, now = Date.now }) {
  const seen = new Map(); //   id → shown at
  let recent = []; //          shown-at times inside RATE_WINDOW_MS
  const live = new Set(); //   keep references so click handlers survive GC

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
      // silent: the page plays its own alert sound (row 3.13).
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
        /* window gone */
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

/**
 * Register the `shell:notify` IPC: only the configured app origin may call it
 * (lib/origin.js; none configured → denied). `onClick(path|null)` shows the
 * app and opens `path`. Returns the notifier.
 */
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
