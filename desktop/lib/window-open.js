"use strict";

// Where a same-origin window.open / target=_blank of the hosted page goes
// (main.js setWindowOpenHandler), and where a notification's click opens.
//
// The Messages Pro window is the one the page names `messages-pro`
// (app/lib/nav.ts `openPopout`). Chromium itself reuses it for a second open by
// that name (measured on Electron 43, 2026-10-26; slop inbox-unread's desktop
// checks keep the window count), so the handler never sees those. What it
// does see:
// - a Messages Pro link opened as a tab (a named open with no features, a
//   target=_blank link, a cmd-click). The app has no tabs, so it goes into the
//   Messages Pro window when one is open; a notification's link adds the Fan's
//   tab there (`?fanTab`, app/lib/notificationLink.ts);
// - anything else: a new window, at the Messages Pro window's size unless the
//   page asked for one (Electron's default is 800x600).

const MESSAGES_PRO_WINDOW = "messages-pro";
const MESSAGES_PRO_SIZE = Object.freeze({ width: 1470, height: 915 });
const TAB_DISPOSITIONS = new Set(["foreground-tab", "background-tab"]);

/** True for `/messages-pro` and every route under it ("/x?y" or a full URL). */
function isMessagesProRoute(url) {
  let pathname;
  try {
    pathname = new URL(url, "http://route.invalid").pathname;
  } catch {
    return false;
  }
  return pathname === "/messages-pro" || pathname.startsWith("/messages-pro/");
}

/**
 * A same-origin open (Electron's handler details): `{ messagesPro: true }` to
 * load it in the open Messages Pro window instead (`messagesProOpen`), else
 * the new window's `{ width, height }`, or `{}` when the page gave its own.
 */
function sameOriginOpen({ url, disposition, features }, messagesProOpen) {
  if (messagesProOpen && TAB_DISPOSITIONS.has(disposition) && isMessagesProRoute(url)) return { messagesPro: true };
  return /\b(width|height)=/.test(features || "") ? {} : { ...MESSAGES_PRO_SIZE };
}

// The page global a mounted Messages Pro takes a notification's link through,
// in place (app/lib/notificationLink.ts IN_PLACE_KEY).
const IN_PLACE_KEY = "__inflowwOpenNotification";

/**
 * Open `route` (a path, or a URL on the app's origin) in the Messages Pro
 * window `win`, focused (`focus(win)`): handed to its page in place when the
 * page takes it (a notification's link while Messages Pro is up: no reload,
 * and a second click cannot cancel the first), else loaded there. False, and
 * nothing done: no window, or not a Messages Pro route on `appOrigin`.
 */
function openInMessagesProWindow(win, route, appOrigin, focus) {
  if (!win || win.isDestroyed() || !appOrigin) return false;
  let target;
  try {
    target = new URL(route, appOrigin);
  } catch {
    return false;
  }
  if (target.origin !== appOrigin || !isMessagesProRoute(target.pathname)) return false;
  // Closed meanwhile: nothing. A load aborted by a newer one: that one wins.
  const load = () => (win.isDestroyed() ? undefined : win.loadURL(target.href).catch(() => {}));
  let showing = "";
  try {
    showing = new URL(win.webContents.getURL()).origin;
  } catch {
    /* not loaded yet */
  }
  if (showing !== appOrigin) load();
  else {
    const path = JSON.stringify(target.pathname + target.search);
    win.webContents
      .executeJavaScript(`typeof window.${IN_PLACE_KEY} === "function" && window.${IN_PLACE_KEY}(${path}) === true`)
      .then((taken) => taken || load(), load)
      .catch(() => {});
  }
  focus(win);
  return true;
}

module.exports = { MESSAGES_PRO_WINDOW, isMessagesProRoute, sameOriginOpen, openInMessagesProWindow };
