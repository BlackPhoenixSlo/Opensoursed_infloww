"use strict";

// Main-window resilience: auto-reload after a renderer crash or hang, but only
// a few times in a short window — a page that crashes on every load must end
// on the error page, not in a reload loop. Pure; the clock is injected.

const MAX_RELOADS = 3;
const WINDOW_MS = 5 * 60 * 1000;

function createReloadLimiter({ max = MAX_RELOADS, windowMs = WINDOW_MS, now = Date.now } = {}) {
  let stamps = [];
  return {
    // true → go ahead and reload (and count it); false → cap reached.
    tryReload() {
      const t = now();
      stamps = stamps.filter((s) => t - s < windowMs);
      if (stamps.length >= max) return false;
      stamps.push(t);
      return true;
    },
  };
}

// The route to restore on retry/reload: path + query of a same-origin URL, with
// the share token (`?t=`) stripped so it is never kept or re-sent. Anything off
// the app origin (error pages, about:blank, other sites) → null.
function routeToRemember(url, appOrigin) {
  if (!appOrigin) return null;
  let u;
  try {
    u = new URL(url);
  } catch {
    return null;
  }
  if (u.origin !== appOrigin) return null;
  u.searchParams.delete("t");
  return `${u.pathname}${u.search}`;
}

module.exports = { MAX_RELOADS, WINDOW_MS, createReloadLimiter, routeToRemember };
