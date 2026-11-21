"use strict";

// Go live (ticket 127, D28): OnlyFans's own /my/streaming page in a desktop
// window, one NON-persistent partition per Creator (`of-live-<creatorId>`), so
// the session never touches disk. Every open reseeds it from the Relay's session
// read: the auth cookies (never Cloudflare's own) plus localStorage.bcTokenSha =
// x_bc, both before the first load. A cookie copy without bcTokenSha killed the
// session in the D26 spike ("Wrong user" 301).
//
// Nothing here is ever written back to the Relay, and nothing is logged: the
// cookies and x_bc live only in this partition's memory and the OF page itself.
// The window gets no preload and no Node, so the secrets cross no bridge.
// Camera and mic are allowed for onlyfans.com only; OF logout is blocked (both
// the request and a navigation), because logging out here would end the
// Creator's session everywhere.
//
// No Relay session for the Creator (the Relay's explicit `{"session": null}`,
// never any other answer): the window opens unseeded on OF's login page (the
// site root) for a human to sign in. Never a scripted login: no
// script runs in the page, nothing is filled or submitted (D28 addendum: a
// scripted login stalls on OF's anti-bot check).
//
// Electron and the Relay read are injected ({ BrowserWindow, session,
// fetchSession }) so node tests can fake them, as lib/toast-window.js does;
// main.js keeps only the IPC registration and its sender-origin check.
//
// ASSUMPTION: the ticket says "parameterise the existing capture window"; that
// factory is bound to the capture flow's global state and interceptor preload,
// so the shared part (Chrome UA + client hints) moved to lib/of-ua.js and both
// windows use it. Overturned by: a reviewer wanting one factory with flags.
// ASSUMPTION: "secrets never reach the renderer" means the app's renderer and
// preload.js; the OF page's own renderer must hold bcTokenSha (D26). Overturned
// by: a way to seed OF's localStorage without a renderer.

const ofUa = require("./of-ua");

const OF_ORIGIN = "https://onlyfans.com";
const LIVE_PATH = "/my/streaming";
const LOGIN_PATH = "/";
const STORAGES = ["cookies", "localstorage", "indexdb", "serviceworkers", "cachestorage"];
const AUTH_COOKIE = "sess";

function livePartition(creatorId) {
  const id = creatorId == null ? "" : String(creatorId);
  if (!/^\d+$/.test(id)) throw new Error("go live: a Creator id is digits only");
  return `of-live-${id}`;
}

function parse(url) {
  try {
    return new URL(String(url || ""));
  } catch {
    return null;
  }
}

// https://onlyfans.com or a subdomain, default port only.
function isOfOrigin(url) {
  const u = parse(url);
  if (!u || u.protocol !== "https:" || u.port !== "") return false;
  return u.hostname === "onlyfans.com" || u.hostname.endsWith(".onlyfans.com");
}

// Camera + mic ("media") on onlyfans.com only; every other permission and
// every other origin is denied.
function allowPermission(permission, origin) {
  return permission === "media" && isOfOrigin(origin);
}

// OF's logout endpoints (/api2/v2/users/logout, /users/helper-logout, from the
// captured bundle) and any */logout page.
function isLogoutUrl(url) {
  if (!isOfOrigin(url)) return false;
  return /(^|\/)(helper-)?logout\/?$/.test(parse(url).pathname);
}

function isCloudflareCookie(name) {
  return /^(__cf|_cf|cf_)/i.test(String(name || ""));
}

// One Relay cookie → Electron cookies.set details, or null when it must not be
// seeded (Cloudflare's, another site's, expired, nameless).
function cookieDetails(c) {
  if (!c || !c.name || isCloudflareCookie(c.name)) return null;
  const host = "onlyfans.com";
  const raw = String(c.domain || "");
  const bare = raw.replace(/^\./, "").toLowerCase();
  if (bare && bare !== host && !host.endsWith("." + bare)) return null;
  const exp = c.expires == null ? null : Number(c.expires);
  if (exp != null && (!Number.isFinite(exp) || exp * 1000 <= Date.now())) return null;
  const d = {
    url: OF_ORIGIN + "/",
    name: String(c.name),
    value: String(c.value == null ? "" : c.value),
    path: c.path || "/",
    secure: !!c.secure,
    httpOnly: !!c.httpOnly,
  };
  // A leading dot is a domain cookie; no dot (or none) stays host-only.
  if (raw.startsWith(".")) d.domain = raw;
  if (exp != null) d.expirationDate = exp;
  return d;
}

function goLiveRefusal(status) {
  if (status === 401) return "Sign in to Inflowwww again, then retry Go live.";
  if (status === 403) return "You're not allowed to go live for this Creator.";
  if (status === 404) return "Go live in the app is not turned on for this server.";
  if (status === 429) return "Too many tries. Wait a minute, then retry Go live.";
  if (status === 409 || status === 503) return "This Creator has no working OnlyFans session. Reconnect it, then retry.";
  return "Couldn't open Go live. Try again.";
}

async function openOfLiveWindow(deps, opts) {
  const { BrowserWindow, session } = deps;
  const partition = livePartition(opts.creatorId);
  const major = opts.chromeMajor || "";
  if (!/^\d+$/.test(major)) throw new Error("go live: no Chrome version for the user agent");
  const unseeded = opts.unseeded === true;
  const xBc = unseeded ? "" : String(opts.xBc || "");
  const cookies = unseeded ? [] : (opts.cookies || []).map(cookieDetails).filter(Boolean);
  if (!unseeded && !xBc) throw new Error("go live: no session token");
  if (!unseeded && !cookies.some((c) => c.name === AUTH_COOKIE)) throw new Error("go live: no session cookie");

  const ses = session.fromPartition(partition);
  await ses.clearStorageData({ storages: STORAGES });
  const ua = ofUa.uaProfile(opts.platform, major);
  ofUa.applyClientHints(ses, ua, major);
  ses.setPermissionRequestHandler((wc, permission, cb, details) => {
    const from = (details && details.requestingUrl) || (wc && wc.getURL && wc.getURL()) || "";
    cb(allowPermission(permission, from));
  });
  ses.setPermissionCheckHandler((_wc, permission, origin) => allowPermission(permission, origin));
  ses.webRequest.onBeforeRequest((details, cb) => cb({ cancel: isLogoutUrl(details.url) }));
  for (const c of cookies) await ses.cookies.set(c);

  const win = new BrowserWindow({
    width: 1240,
    height: 860,
    backgroundColor: "#ffffff",
    title: unseeded ? "Go live: sign in to OnlyFans" : "Go live",
    autoHideMenuBar: true,
    show: false,
    webPreferences: {
      partition,
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      backgroundThrottling: false,
    },
  });
  const wc = win.webContents;
  wc.setUserAgent(ua.userAgent);
  const blockLogout = (event, url) => {
    if (isLogoutUrl(url || (event && event.url))) event.preventDefault();
  };
  wc.on("will-navigate", blockLogout);
  wc.on("will-redirect", blockLogout);
  win.on("closed", () => {
    ses.clearStorageData({ storages: STORAGES }).catch(() => {});
  });

  if (!unseeded) {
    // Write bcTokenSha into the origin's localStorage from a document that is
    // that origin but never touches the network (measured: it persists into the
    // next real load of the same non-persistent partition).
    await wc.loadURL("data:text/html,", { baseURLForDataURL: OF_ORIGIN + "/" });
    await wc.executeJavaScript(`localStorage.setItem("bcTokenSha", ${JSON.stringify(xBc)}); void 0`);
  }

  wc.loadURL(OF_ORIGIN + (unseeded ? LOGIN_PATH : LIVE_PATH)).catch(() => {});
  win.show();
  return win;
}

// The Relay's session read → what to open. Only an OK answer whose body says
// `{"session": null}` is the sign-in mode; an OK seed must carry a cookie list
// and x_bc; every other answer (any 503 included: deploy downtime, a proxy, a
// broken session file) is refused with its status.
function goLiveSeed(status, body) {
  if (status < 200 || status > 299) return { refuse: status || 0 };
  const s = body && typeof body === "object" && "session" in body ? body.session : undefined;
  if (s === null) return { signIn: true };
  if (s && Array.isArray(s.cookies) && typeof s.x_bc === "string") return { cookies: s.cookies, xBc: s.x_bc };
  return { refuse: 0 };
}

// The Go live open flow, one per app. deps: { BrowserWindow, session,
// fetchSession(creatorId) → Response-like {status, json()}, platform,
// chromeMajor, focusWindow(win), warn(msg) }. Returns
// openGoLive(creatorId) → {ok, signIn?, error?}: one window per Creator (a second
// open focuses it), a double click opens one, the seed is dropped after use and
// never logged.
function createGoLive(deps) {
  const windows = new Map(); // creatorId -> BrowserWindow
  const opening = new Set(); // creatorIds being opened
  const warn = deps.warn || (() => {});
  return async function openGoLive(rawId) {
    const creatorId = typeof rawId === "string" ? rawId.trim() : "";
    try {
      livePartition(creatorId);
    } catch {
      return { ok: false, error: "Select a model to go live." };
    }
    const open = windows.get(creatorId);
    if (open && !open.isDestroyed()) {
      deps.focusWindow(open);
      return { ok: true };
    }
    if (opening.has(creatorId)) return { ok: true };
    opening.add(creatorId);
    try {
      let seed;
      try {
        const resp = await deps.fetchSession(creatorId);
        const ok = resp.status >= 200 && resp.status <= 299;
        seed = goLiveSeed(resp.status, ok ? await resp.json().catch(() => null) : null);
      } catch {
        return { ok: false, error: goLiveRefusal(0) };
      }
      if ("refuse" in seed) return { ok: false, error: goLiveRefusal(seed.refuse) };
      const base = { creatorId, platform: deps.platform, chromeMajor: deps.chromeMajor };
      const win = await openOfLiveWindow(
        deps,
        seed.signIn ? { ...base, unseeded: true } : { ...base, cookies: seed.cookies, xBc: seed.xBc },
      );
      const signIn = !!seed.signIn;
      seed = null;
      windows.set(creatorId, win);
      win.on("closed", () => {
        if (windows.get(creatorId) === win) windows.delete(creatorId);
      });
      return signIn ? { ok: true, signIn: true } : { ok: true };
    } catch (err) {
      // The message only: never the seed.
      warn("[go-live] open failed: " + (err && err.message));
      return { ok: false, error: goLiveRefusal(0) };
    } finally {
      opening.delete(creatorId);
    }
  };
}

module.exports = {
  OF_ORIGIN,
  LIVE_PATH,
  LOGIN_PATH,
  livePartition,
  isOfOrigin,
  allowPermission,
  isLogoutUrl,
  isCloudflareCookie,
  cookieDetails,
  goLiveRefusal,
  goLiveSeed,
  openOfLiveWindow,
  createGoLive,
};
