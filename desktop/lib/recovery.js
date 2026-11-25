"use strict";


const MAX_RELOADS = 3;
const WINDOW_MS = 5 * 60 * 1000;

function createReloadLimiter({ max = MAX_RELOADS, windowMs = WINDOW_MS, now = Date.now } = {}) {
  let stamps = [];
  return {
    tryReload() {
      const t = now();
      stamps = stamps.filter((s) => t - s < windowMs);
      if (stamps.length >= max) return false;
      stamps.push(t);
      return true;
    },
  };
}

function routeToRemember(url, appOrigin) {
  if (!appOrigin) return null;
  let u;
  try {
    u = new URL(url);
  } catch {
    return null;
  }
  if (u.origin !== appOrigin) return null;
  // Strip the share token so it is never kept or re-sent.
  u.searchParams.delete("t");
  return `${u.pathname}${u.search}`;
}

module.exports = { MAX_RELOADS, WINDOW_MS, createReloadLimiter, routeToRemember };
