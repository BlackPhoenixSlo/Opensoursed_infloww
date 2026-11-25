"use strict";

const path = require("path");


const LEADING_PAREN = /^\((\d+)\)/;
const TRAILING_PAREN = /\((\d+)\)\s*$/;
const BULLET = /[•·]\s*(\d+)\s*$/;

function parseUnread(title) {
  if (typeof title !== "string" || !title) return 0;
  const m = title.match(LEADING_PAREN) || title.match(TRAILING_PAREN) || title.match(BULLET);
  if (!m) return 0;
  const n = parseInt(m[1], 10);
  return Number.isFinite(n) && n > 0 ? n : 0;
}

const OVERLAY_DIR = path.join(__dirname, "..", "assets", "overlay");
const overlayCache = new Map();

function overlayFor(nativeImage, count) {
  if (!nativeImage || !(count > 0)) return null;
  const key = count > 9 ? "9plus" : String(count);
  if (overlayCache.has(key)) return overlayCache.get(key);
  let img = null;
  try {
    // a missing file yields an empty image, not a throw; setOverlayIcon with it would blank the taskbar icon
    const candidate = nativeImage.createFromPath(path.join(OVERLAY_DIR, `unread-${key}.png`));
    if (candidate && !candidate.isEmpty()) img = candidate;
  } catch {
  }
  overlayCache.set(key, img);
  return img;
}

function applyBadge({ app, win, nativeImage, count, overlayIcon }) {
  try {
    if (app && typeof app.setBadgeCount === "function") {
      app.setBadgeCount(count);
    }
  } catch {
  }

  if (process.platform === "win32" && win && !win.isDestroyed()) {
    try {
      const icon = overlayIcon || overlayFor(nativeImage, count);
      if (count > 0 && icon) {
        win.setOverlayIcon(icon, `${count} unread`);
      } else {
        win.setOverlayIcon(null, "");
      }
    } catch {
    }
  }
}

module.exports = { parseUnread, applyBadge, overlayFor };
