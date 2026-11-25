"use strict";


const MESSAGES_PRO_WINDOW = "messages-pro";
const MESSAGES_PRO_SIZE = Object.freeze({ width: 1470, height: 915 });
// Chromium itself reuses a window opened by the name `messages-pro` (measured on Electron 43), so the handler never sees second opens.
const TAB_DISPOSITIONS = new Set(["foreground-tab", "background-tab"]);

function isMessagesProRoute(url) {
  let pathname;
  try {
    pathname = new URL(url, "http://route.invalid").pathname;
  } catch {
    return false;
  }
  return pathname === "/messages-pro" || pathname.startsWith("/messages-pro/");
}

function sameOriginOpen({ url, disposition, features }, messagesProOpen) {
  if (messagesProOpen && TAB_DISPOSITIONS.has(disposition) && isMessagesProRoute(url)) return { messagesPro: true };
  return /\b(width|height)=/.test(features || "") ? {} : { ...MESSAGES_PRO_SIZE };
}

// Handed to the mounted page in place: no reload, and a second click cannot cancel the first.
const IN_PLACE_KEY = "__inflowwOpenNotification";

function openInMessagesProWindow(win, route, appOrigin, focus) {
  if (!win || win.isDestroyed() || !appOrigin) return false;
  let target;
  try {
    target = new URL(route, appOrigin);
  } catch {
    return false;
  }
  if (target.origin !== appOrigin || !isMessagesProRoute(target.pathname)) return false;
  const load = () => (win.isDestroyed() ? undefined : win.loadURL(target.href).catch(() => {}));
  let showing = "";
  try {
    showing = new URL(win.webContents.getURL()).origin;
  } catch {
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
