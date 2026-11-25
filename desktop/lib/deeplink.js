"use strict";


const SCHEME = "inflowwww";
const ID = "[A-Za-z0-9_-]{1,64}";
const LINK_RE = new RegExp(`^${SCHEME}://chat/(${ID})/(${ID})/?$`, "i");
const ROUTE_RE = new RegExp(`^/messages-pro/(${ID})/(${ID})/?$`);

// Strict match on the RAW string, never new URL(): URL parsing resolves `..` and would rewrite chat/x/../../settings. The id alphabet excludes . / % ? # (no traversal, encoded slashes, queries). The link names no host.
function parseDeepLink(raw) {
  if (typeof raw !== "string") return null;
  const m = raw.trim().match(LINK_RE);
  return m ? `/messages-pro/${m[1]}/${m[2]}` : null;
}

function deepLinkFromArgv(argv) {
  if (!Array.isArray(argv)) return null;
  for (const arg of argv) {
    const route = parseDeepLink(arg);
    if (route) return route;
  }
  return null;
}

function chatLinkForUrl(url, appOrigin) {
  if (!appOrigin) return null;
  let u;
  try {
    u = new URL(url);
  } catch {
    return null;
  }
  if (u.origin !== appOrigin) return null;
  const m = u.pathname.match(ROUTE_RE);
  return m ? `${SCHEME}://chat/${m[1]}/${m[2]}` : null;
}

module.exports = { SCHEME, parseDeepLink, deepLinkFromArgv, chatLinkForUrl };
