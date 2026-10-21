"use strict";

// App links: `inflowwww://chat/<accountId>/<fanId>` opens one chat in the
// desktop app. The link names NO host — it always resolves against the server
// the shell is configured for — so the only thing a link can ever do is pick a
// same-origin path, and the only path it can pick is the app's own Messages Pro
// deep link `/messages-pro/<accountId>/<fanId>` (app/lib/nav.ts fanDeepLinkHref).
//
// Parsing is a strict match on the RAW string, never `new URL()`: URL parsing
// resolves `..` segments and would turn `chat/x/../../settings` into something
// else before we could look at it. Ids are opaque (numeric on OnlyFans, string
// snowflakes on Fansly), so we only constrain their alphabet: no `.`, `/`, `%`,
// `?` or `#` can get through, which rules out traversal, encoded slashes,
// extra segments, queries and fragments in one rule.

const SCHEME = "inflowwww";
const ID = "[A-Za-z0-9_-]{1,64}";
const LINK_RE = new RegExp(`^${SCHEME}://chat/(${ID})/(${ID})/?$`, "i");
const ROUTE_RE = new RegExp(`^/messages-pro/(${ID})/(${ID})/?$`);

// `inflowwww://chat/<aid>/<fan>` → "/messages-pro/<aid>/<fan>", anything else → null.
function parseDeepLink(raw) {
  if (typeof raw !== "string") return null;
  const m = raw.trim().match(LINK_RE);
  return m ? `/messages-pro/${m[1]}/${m[2]}` : null;
}

// Windows/Linux deliver the link as a command-line argument (startup argv and
// the `second-instance` argv). Return the first argument that parses.
function deepLinkFromArgv(argv) {
  if (!Array.isArray(argv)) return null;
  for (const arg of argv) {
    const route = parseDeepLink(arg);
    if (route) return route;
  }
  return null;
}

// Reverse: the main window's current URL → its app link, or null when the
// window is not on a chat of the configured server.
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
