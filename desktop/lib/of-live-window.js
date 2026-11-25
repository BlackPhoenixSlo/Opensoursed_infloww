"use strict";


const ofUa = require("./of-ua");

// Non-persistent partition per Creator, reseeded on every open: auth cookies (never Cloudflare's) plus localStorage.bcTokenSha = x_bc before the first load; a cookie copy without bcTokenSha killed the session ("Wrong user" 301). Nothing is written back or logged; no preload/Node in the window.
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

function isOfOrigin(url) {
  const u = parse(url);
  if (!u || u.protocol !== "https:" || u.port !== "") return false;
  return u.hostname === "onlyfans.com" || u.hostname.endsWith(".onlyfans.com");
}

function allowPermission(permission, origin) {
  return permission === "media" && isOfOrigin(origin);
}

// OF logout is blocked: logging out here would end the Creator's session everywhere.
function isLogoutUrl(url) {
  if (!isOfOrigin(url)) return false;
  return /(^|\/)(helper-)?logout\/?$/.test(parse(url).pathname);
}

function isCloudflareCookie(name) {
  return /^(__cf|_cf|cf_)/i.test(String(name || ""));
}

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
    // seed bcTokenSha from a document of the OF origin that never touches the network (measured: it persists into the next real load of this partition)
    await wc.loadURL("data:text/html,", { baseURLForDataURL: OF_ORIGIN + "/" });
    await wc.executeJavaScript(`localStorage.setItem("bcTokenSha", ${JSON.stringify(xBc)}); void 0`);
  }

  wc.loadURL(OF_ORIGIN + (unseeded ? LOGIN_PATH : LIVE_PATH)).catch(() => {});
  win.show();
  return win;
}

// Only an OK answer with `{"session": null}` is sign-in mode (never a scripted login: it stalls on OF's anti-bot check); every other answer, any 503 included, is refused with its status.
function goLiveSeed(status, body) {
  if (status < 200 || status > 299) return { refuse: status || 0 };
  const s = body && typeof body === "object" && "session" in body ? body.session : undefined;
  if (s === null) return { signIn: true };
  if (s && Array.isArray(s.cookies) && typeof s.x_bc === "string") return { cookies: s.cookies, xBc: s.x_bc };
  return { refuse: 0 };
}

function createGoLive(deps) {
  const windows = new Map();
  const opening = new Set();
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
