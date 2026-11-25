"use strict";


const { BrowserWindow, session, ipcMain } = require("electron");
const ofUa = require("../lib/of-ua");
const { chromeMajor } = ofUa;

const OF_URL = "https://onlyfans.com/";
// Omit `persist:` to keep the Electron capture partition in memory.
const CAPTURE_PARTITION = "of-capture";
const APP_TOKEN = "33d57ade8c02dbc5a333db99ff9ae26a";
const REQUIRED_HDRS = ["user-id", "x-bc", "x-of-rev", "sign", "time"];
const POLL_MS = 1500;
const SAVE_TIMEOUT_MS = 30000;
const SIGNIN_CHECK_TIMEOUT_MS = 5000;

// UA must match the engine rendering the page: a pinned literal rots into the tell it prevents; process.versions.chrome cannot drift
const CHROME_MAJOR = chromeMajor(process.versions);

// a malformed UA ("Chrome/.0.0.0") is a unique fingerprint: fail loudly instead of signing requests with it
if (!/^\d+$/.test(CHROME_MAJOR)) {
  throw new Error(
    "of-capture: cannot derive Chrome major from process.versions.chrome=" +
      JSON.stringify(process.versions.chrome)
  );
}
const UA = ofUa.uaProfile(process.platform, CHROME_MAJOR);

let flow = null;

function freshState() {
  return {
    headers: {},
    rules: {},
    cookies: { auth_id: false, sess: false },
    authId: null,
    status: "waiting",
    error: null,
    savedAs: null,
    appSignedIn: null,
    detection: `Chrome ${CHROME_MAJOR} UA + client-hints (no CDP — Cloudflare-safe)`,
    diag: { url: "", httpStatus: null, lastRelayError: "" },
  };
}

function hasHeaders(s) {
  if (!REQUIRED_HDRS.every((k) => s.headers[k])) return false;
  const uid = String(s.headers["user-id"]);
  if (!/^[1-9]\d*$/.test(uid)) return false;
  return !(s.authId && /^\d+$/.test(s.authId) && s.authId !== uid);
}
function hasRules(s) {
  return !!s.rules.static_param;
}
function hasCookies(s) {
  return s.cookies.auth_id && s.cookies.sess;
}
function isReady(s) {
  return hasHeaders(s) && hasRules(s) && hasCookies(s);
}

function stateSummary(s) {
  return {
    status: s.status,
    error: s.error,
    savedAs: s.savedAs,
    appSignedIn: s.appSignedIn,
    appBase: flow ? flow.getConfig().base : null,
    detection: s.detection,
    userId: s.headers["user-id"] || null,
    ofRev: s.headers["x-of-rev"] || null,
    haveHeaders: hasHeaders(s),
    haveRules: hasRules(s),
    haveCookies: hasCookies(s),
    ready: isReady(s),
    diag: s.diag,
  };
}

function pushState() {
  if (flow && flow.statusWindow && !flow.statusWindow.isDestroyed()) {
    flow.statusWindow.webContents.send("capture:state", stateSummary(flow.state));
  }
}

function shellQuote(s) {
  return "'" + String(s).replace(/'/g, "'\\''") + "'";
}

function buildCurl(s, cookieList) {
  const h = s.headers;
  const r = s.rules;
  const url = h.__url || "https://onlyfans.com/api2/v2/users/me";
  const cookieHeader = cookieList
    .filter((c) => c.value && c.name)
    .map((c) => `${c.name}=${c.value}`)
    .join("; ");
  const lines = [
    `curl ${shellQuote(url)} \\`,
    `  -H ${shellQuote("accept: application/json, text/plain, */*")} \\`,
    `  -H ${shellQuote("user-agent: " + (h["user-agent"] || UA.userAgent))} \\`,
    `  -H ${shellQuote("user-id: " + h["user-id"])} \\`,
    `  -H ${shellQuote("x-bc: " + h["x-bc"])} \\`,
    `  -H ${shellQuote("x-of-rev: " + h["x-of-rev"])} \\`,
    `  -H ${shellQuote("sign: " + h["sign"])} \\`,
    `  -H ${shellQuote("time: " + h["time"])} \\`,
    `  -H ${shellQuote("referer: https://onlyfans.com/")} \\`,
    `  -H ${shellQuote("app-token: " + APP_TOKEN)}`,
  ];
  if (r.static_param) {
    lines[lines.length - 1] += " \\";
    lines.push(`  -H ${shellQuote("x-relay-static-param: " + r.static_param)}`);
  }
  if (r.start) {
    lines[lines.length - 1] += " \\";
    lines.push(`  -H ${shellQuote("x-relay-sign-start: " + r.start)}`);
  }
  if (r.end) {
    lines[lines.length - 1] += " \\";
    lines.push(`  -H ${shellQuote("x-relay-sign-end: " + r.end)}`);
  }
  if (cookieHeader) {
    lines[lines.length - 1] += " \\";
    lines.push(`  -b ${shellQuote(cookieHeader)}`);
  }
  return lines.join("\n");
}

function mergeCapture(s, cap) {
  if (!cap) return;
  if (cap.headers) {
    for (const k of Object.keys(cap.headers)) {
      if (cap.headers[k]) s.headers[k] = cap.headers[k];
    }
  }
  if (cap.url) s.headers.__url = cap.url;
  if (cap.rules) {
    if (cap.rules.static_param) s.rules.static_param = cap.rules.static_param;
    if (cap.rules.start) s.rules.start = cap.rules.start;
    if (cap.rules.end) s.rules.end = cap.rules.end;
  }
}

async function pollOnce() {
  if (!flow || !flow.ofWindow || flow.ofWindow.isDestroyed()) return;
  const s = flow.state;
  if (s.status === "sending" || s.status === "done") return;
  try {
    const cookies = await session.fromPartition(CAPTURE_PARTITION).cookies.get({ url: OF_URL });
    flow.cookieList = cookies;
    const names = new Set(cookies.map((c) => c.name));
    s.cookies.auth_id = names.has("auth_id");
    s.cookies.sess = names.has("sess");
    const auth = cookies.find((c) => c.name === "auth_id");
    s.authId = auth ? String(auth.value) : null;
  } catch {
  }
  if (s.appSignedIn !== true) await checkAppSignIn();
  if (s.status === "waiting" && isReady(s)) s.status = "ready";
  pushState();
  maybeAutoSave();
}

async function checkAppSignIn() {
  if (!flow || flow.checkingSignIn) return;
  const { base } = flow.getConfig();
  if (!base) return;
  flow.checkingSignIn = true;
  try {
    const r = await session.fromPartition(registerCaptureIpc._paths.appPartition).fetch(`${base}/auth/me`, {
      cache: "no-store",
      signal: AbortSignal.timeout(SIGNIN_CHECK_TIMEOUT_MS),
    });
    const me = r.ok ? await r.json().catch(() => null) : null;
    if (flow) flow.state.appSignedIn = !!(me && me.user_id);
  } catch {
    if (flow) flow.state.appSignedIn = "unreachable";
  } finally {
    if (flow) flow.checkingSignIn = false;
  }
}

function maybeAutoSave() {
  if (!flow || flow.autoSaveTried) return;
  const s = flow.state;
  if (s.status !== "ready" || s.appSignedIn !== true) return;
  flow.autoSaveTried = true;
  submitToRelay().catch(() => {});
}

function saveErrorMessage(status, text) {
  let detail = "";
  try {
    const d = JSON.parse(text).detail;
    detail = typeof d === "string" ? d : (d && d.message) || "";
  } catch {
  }
  if (status === 403) return "Inflowwww refused to save this account to you. It may belong to another agency.";
  if (status === 400 || status === 422) {
    return `OnlyFans' session wasn't accepted${detail ? ` (${detail})` : ""}. Open your Messages again, then Retry save.`;
  }
  if (status >= 500) return "The Inflowwww server had a problem saving. Wait a moment, then Retry save.";
  return `Saving failed (HTTP ${status}). Retry save, or see Technical details.`;
}

async function submitToRelay() {
  const s = flow.state;
  if (!isReady(s)) {
    s.status = "error";
    s.error = "Not ready yet — sign in and open your Messages so OnlyFans signs a request.";
    pushState();
    return;
  }
  const { base, token } = flow.getConfig();
  if (!base) {
    s.status = "error";
    s.error = "No server configured. Set it in Settings first.";
    pushState();
    return;
  }
  try {
    const bu = new URL(base);
    const isLocal = bu.hostname === "localhost" || bu.hostname === "127.0.0.1";
    if (bu.protocol !== "https:" && !isLocal) {
      s.status = "error";
      s.error = "Refusing to send the OnlyFans session over an insecure (http) connection — use an https server URL.";
      pushState();
      return;
    }
  } catch {
  }

  s.status = "sending";
  s.error = null;
  s.diag.lastRelayError = "";
  pushState();

  const curl = buildCurl(s, flow.cookieList || []);
  const url = `${base}/admin/session/bootstrap${token ? `?t=${encodeURIComponent(token)}` : ""}`;
  try {
    // Node's fetch sends no cookies ("Relay 401: sign in required"): the app partition's fetch carries the session
    const resp = await session.fromPartition(registerCaptureIpc._paths.appPartition).fetch(url, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ mode: "paste-curl", curl, make_active: true, nickname: null }),
      signal: AbortSignal.timeout(SAVE_TIMEOUT_MS),
    });
    const text = await resp.text();
    if (!resp.ok) {
      s.diag.lastRelayError = `HTTP ${resp.status}: ${text.slice(0, 300)}`;
      if (resp.status === 401) {
        s.status = "ready";
        s.appSignedIn = false;
        if (flow) flow.autoSaveTried = false;
      } else {
        s.status = "error";
        s.error = saveErrorMessage(resp.status, text);
      }
      pushState();
      return;
    }
    let parsed = null;
    try {
      parsed = JSON.parse(text);
    } catch {
    }
    s.status = "done";
    s.savedAs = (parsed && (parsed.user_id || parsed.account_id || parsed.userId)) || s.headers["user-id"] || "saved";
    pushState();
    if (flow && typeof flow.onSaved === "function") {
      try {
        flow.onSaved();
      } catch (_) {
      }
    }
    closeOfWindow();
    if (flow) {
      clearInterval(flow.pollTimer);
      flow.pollTimer = null;
      const sw = flow.statusWindow;
      setTimeout(() => {
        if (sw && !sw.isDestroyed()) sw.close();
      }, 1400);
    }
  } catch (err) {
    s.status = "error";
    s.diag.lastRelayError = String((err && err.message) || err);
    s.error =
      err && err.name === "TimeoutError"
        ? "Inflowwww took too long to answer. Your OnlyFans sign-in is kept; Retry save."
        : `Couldn't reach Inflowwww at ${base}. Check it is running, then Retry save.`;
    pushState();
  }
}

function closeOfWindow() {
  if (flow && flow.ofWindow && !flow.ofWindow.isDestroyed()) {
    flow.ofWindow.destroy();
    flow.ofWindow = null;
  }
}

function teardown() {
  if (!flow) return;
  clearInterval(flow.pollTimer);
  closeOfWindow();
  session
    .fromPartition(CAPTURE_PARTITION)
    .clearStorageData({ storages: ["cookies", "localstorage", "indexdb", "serviceworkers", "cachestorage"] })
    .catch(() => {});
  if (flow.statusWindow && !flow.statusWindow.isDestroyed()) flow.statusWindow.destroy();
  flow = null;
}

async function createOfWindow() {
  const win = new BrowserWindow({
    width: 1120,
    height: 820,
    backgroundColor: "#ffffff",
    title: "Sign in to OnlyFans",
    autoHideMenuBar: true,
    show: false,
    webPreferences: {
      partition: CAPTURE_PARTITION,
      preload: flow.interceptorPreload,
      // preload runs in the page main world to patch XHR/fetch; no CDP (Cloudflare hard-blocks it); the page still gets no Node
      contextIsolation: false,
      nodeIntegration: false,
      sandbox: false,
      devTools: true,
      backgroundThrottling: false,
    },
  });
  ofUa.applyClientHints(session.fromPartition(CAPTURE_PARTITION), UA, CHROME_MAJOR);
  win.webContents.setUserAgent(UA.userAgent);
  flow.ofWindow = win;

  const wc = win.webContents;
  win.on("closed", () => {
    if (flow) flow.ofWindow = null;
  });
  win.once("ready-to-show", () => win.show());
  wc.on("did-navigate", (_e, navUrl, httpResponseCode) => {
    if (flow) {
      flow.state.diag.url = navUrl;
      flow.state.diag.httpStatus = httpResponseCode;
      pushState();
    }
  });
  wc.on("console-message", (d) => {
    if (d && (d.level === "warning" || d.level === "error") && d.message) {
      console.log(`[capture] OF page ${d.level}:`, String(d.message).slice(0, 200));
    }
  });
  wc.on("did-finish-load", () => console.log("[capture] OF loaded:", wc.getURL()));
  wc.on("did-fail-load", (_e, code, desc, url, isMain) => {
    if (!isMain || code === -3) return;
    console.warn("[capture] OF did-fail-load", code, desc, url);
    if (flow) {
      flow.state.status = "error";
      flow.state.error = `OnlyFans didn't load (${desc || code}). Click Reopen Login to retry.`;
      pushState();
    }
    if (!win.isDestroyed() && !win.isVisible()) win.show();
  });
  wc.on("render-process-gone", (_e, d) => console.warn("[capture] OF render gone:", d && d.reason));

  win.loadURL(OF_URL).catch((e) => {
    if (!e || e.errno !== -3) console.warn("[capture] OF loadURL:", e && e.message);
  });
  setTimeout(() => {
    if (win && !win.isDestroyed() && !win.isVisible()) win.show();
  }, 6000);
}

function createStatusWindow(preloadPath, htmlPath) {
  const win = new BrowserWindow({
    width: 460,
    height: 620,
    resizable: false,
    backgroundColor: "#0b0b0f",
    title: "Add OnlyFans Account",
    alwaysOnTop: true,
    webPreferences: {
      preload: preloadPath,
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      devTools: false,
    },
  });
  win.setMenuBarVisibility(false);
  flow.statusWindow = win;
  win.on("closed", () => teardown());
  win.loadFile(htmlPath).then(() => pushState());
}

function isTrustedLocalSender(event) {
  const url = event.senderFrame ? event.senderFrame.url : "";
  return typeof url === "string" && url.startsWith("file://");
}

function registerCaptureIpc(paths) {
  registerCaptureIpc._paths = paths;

  ipcMain.on("of-capture:data", (event, payload) => {
    if (!flow || !flow.ofWindow || flow.ofWindow.isDestroyed()) return;
    if (event.sender.id !== flow.ofWindow.webContents.id) return;
    mergeCapture(flow.state, payload);
    const s = flow.state;
    if (s.status === "waiting" && isReady(s)) s.status = "ready";
    pushState();
    maybeAutoSave();
  });

  ipcMain.handle("capture:get-state", (event) => {
    if (!isTrustedLocalSender(event)) return null;
    return flow ? stateSummary(flow.state) : null;
  });
  ipcMain.handle("capture:finish", async (event) => {
    if (!isTrustedLocalSender(event) || !flow) return;
    if (flow.state.status === "sending" || flow.state.status === "done") return;
    flow.state.status = isReady(flow.state) ? "ready" : "waiting";
    await submitToRelay();
  });
  ipcMain.handle("capture:reopen", (event) => {
    if (!isTrustedLocalSender(event) || !flow) return;
    if (!flow.ofWindow || flow.ofWindow.isDestroyed()) {
      createOfWindow().catch((e) => {
        flow.state.status = "error";
        flow.state.error = `Couldn't open OnlyFans: ${e && e.message}`;
        pushState();
      });
    } else {
      flow.ofWindow.show();
      flow.ofWindow.focus();
    }
  });
  ipcMain.handle("capture:cancel", (event) => {
    if (!isTrustedLocalSender(event)) return;
    teardown();
  });
}

async function openOfCaptureFlow(getConfig, onSaved) {
  if (flow) {
    if (flow.statusWindow && !flow.statusWindow.isDestroyed()) {
      flow.statusWindow.show();
      flow.statusWindow.focus();
    }
    return;
  }
  const paths = registerCaptureIpc._paths || {};
  flow = {
    getConfig,
    onSaved,
    state: freshState(),
    ofWindow: null,
    statusWindow: null,
    cookieList: [],
    pollTimer: null,
    checkingSignIn: false,
    autoSaveTried: false,
    interceptorPreload: paths.interceptorPreload,
  };

  createStatusWindow(paths.statusPreload, paths.statusHtml);
  checkAppSignIn().then(pushState, () => {});
  try {
    await createOfWindow();
  } catch (e) {
    flow.state.status = "error";
    flow.state.error = `Couldn't open OnlyFans: ${e && e.message}`;
    pushState();
    return;
  }
  flow.pollTimer = setInterval(() => {
    pollOnce().catch(() => {});
  }, POLL_MS);
}

module.exports = { registerCaptureIpc, openOfCaptureFlow };
