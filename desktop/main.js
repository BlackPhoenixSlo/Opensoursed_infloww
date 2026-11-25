"use strict";


const { app, BrowserWindow, Menu, Tray, shell, ipcMain, session, screen, nativeImage, clipboard } = require("electron");
const { safeStorage, crashReporter, Notification, powerMonitor, powerSaveBlocker } = require("electron");
const path = require("path");
const crypto = require("crypto");
const { pathToFileURL } = require("url");
const { Store } = require("./lib/store");
const { parseUnread, applyBadge } = require("./lib/badge");
const { describeSigning, summarize } = require("./lib/signing");
const { originOf, isAppOrigin, serverOrigin } = require("./lib/origin");
const { registerNotifyIpc } = require("./lib/notify");
const { MESSAGES_PRO_WINDOW, openInMessagesProWindow, sameOriginOpen } = require("./lib/window-open");
const { safeStorageCodec, getSecret, setSecret, deleteSecret } = require("./lib/secret");
const { readAdvanced, advancedPatch, applyBeforeReady, applyAfterReady } = require("./lib/advanced");
const { createLogFile, mirrorConsole } = require("./lib/logfile");
const { createToasts } = require("./lib/toast-window");
const { SseClient } = require("./lib/sse");
const { DEFAULT_BRAND, DEFAULT_SETTINGS, SETTINGS_KEY, parseSettings, shouldPing, noticesFor, SeenKeys } = require("./lib/relay-notices");
const { ClockPause } = require("./lib/clock-pause");
const { registerCaptureIpc, openOfCaptureFlow } = require("./capture/of-capture");
const { createGoLive, goLiveRefusal } = require("./lib/of-live-window");
const { chromeMajor } = require("./lib/of-ua");

const IS_DEV = process.argv.includes("--dev");
// keeps the old "fastt" name on purpose: renaming the partition drops every user's session
const PARTITION = "persist:fastt";
const SCREENSHOT_TO = (() => {
  const i = process.argv.indexOf("--screenshot-to");
  return i !== -1 && process.argv[i + 1] ? path.resolve(process.argv[i + 1]) : null;
})();
const SHELL_VERSION = app.getVersion();
const EXTERNAL_SCHEMES = new Set(["http:", "https:", "mailto:", "tel:", "sms:"]);

app.setName("Inflowwww");
// keeps the pre-rename "OpenInfloww" folder on purpose: setName alone would move it and log every user out
app.setPath("userData", path.join(app.getPath("appData"), "OpenInfloww"));

const SECRET_CODEC = safeStorageCodec(safeStorage);
const LOG = createLogFile({
  dir: path.join(app.getPath("userData"), "logs"),
  getSecrets: () => [tokenCache && tokenCache.token],
});
mirrorConsole(console, LOG);
crashReporter.start({ uploadToServer: false });
const store = new Store(app.getPath("userData"));
const ADVANCED = readAdvanced(store);
applyBeforeReady(app, ADVANCED);
app.whenReady().then(() => applyAfterReady(app, ADVANCED));

const { SCHEME, parseDeepLink, deepLinkFromArgv, chatLinkForUrl } = require("./lib/deeplink");
const { createReloadLimiter, routeToRemember } = require("./lib/recovery");

let pendingRoute = null;
let loadStarted = false;

if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  pendingRoute = deepLinkFromArgv(process.argv);
  if (process.defaultApp) {
    if (process.argv.length >= 2) app.setAsDefaultProtocolClient(SCHEME, process.execPath, [path.resolve(process.argv[1])]);
  } else {
    app.setAsDefaultProtocolClient(SCHEME);
  }
  app.on("open-url", (event, url) => {
    event.preventDefault();
    openRoute(parseDeepLink(url));
  });
  app.on("second-instance", (_e, argv) => {
    const w = liveWindow();
    if (w) focusWindow(w);
    const route = deepLinkFromArgv(argv);
    if (route) openRoute(route);
    else if (!w && app.isReady()) isConfigured() ? loadApp() : openSettingsWindow();
  });
}

function focusWindow(w) {
  if (w.isMinimized()) w.restore();
  w.show();
  w.focus();
}

function showMain() {
  if (mainWindow && !mainWindow.isDestroyed()) return focusWindow(mainWindow);
  isConfigured() ? loadApp() : openSettingsWindow();
}

function openRoute(route) {
  if (!route) return;
  pendingRoute = route;
  if (!app.isReady()) return;
  if (!isConfigured()) return openSettingsWindow();
  if (!loadStarted) return;
  if (mainWindow && !mainWindow.isDestroyed()) focusWindow(mainWindow);
  loadApp();
}

let messagesProWindow = null;
function openInMessagesPro(route) {
  return openInMessagesProWindow(messagesProWindow, route, originOf(currentConfig().base), focusWindow);
}

let mainWindow = null;
let settingsWindow = null;
let settingsShowsProblem = false;
let boundsSaveTimer = null;
let isQuitting = false;
let screenshotArmed = false;

function liveWindow() {
  const wins = [settingsWindow, mainWindow].filter((w) => w && !w.isDestroyed());
  return wins.find((w) => w.isVisible()) || wins[0] || null;
}


function normalizeBase(rawUrl) {
  try {
    const u = new URL(String(rawUrl).trim());
    if (u.protocol !== "http:" && u.protocol !== "https:") return null;
    return serverOrigin(u.origin);
  } catch {
    return null;
  }
}

function regDomain(host) {
  if (!host) return "";
  const parts = String(host).split(".");
  return parts.slice(-2).join(".");
}

const ENV_URL = normalizeBase(process.env.OPENINFLOWW_URL || "");
if (process.env.OPENINFLOWW_URL && !ENV_URL) {
  console.warn("[openinflowwww] ignoring OPENINFLOWW_URL (not a valid http(s) URL):", process.env.OPENINFLOWW_URL);
}

function displayUrl(rawUrl) {
  try {
    const u = new URL(rawUrl);
    return `${u.origin}${u.pathname}`;
  } catch {
    return "";
  }
}

function seedMarker(base, token) {
  return crypto.createHash("sha256").update(`${base} ${token}`).digest("hex").slice(0, 24);
}

let tokenCache = null;

function shareTokenState() {
  if (!tokenCache) {
    const secret = getSecret(store, "shareToken", SECRET_CODEC);
    tokenCache = { token: secret || "", unreadable: secret === null };
  }
  return tokenCache;
}

function currentConfig() {
  const base = ENV_URL || normalizeBase(store.get("serverUrl", "")) || null;
  return { base, token: shareTokenState().token };
}

function isConfigured() {
  if (ENV_URL) return true;
  if (shareTokenState().unreadable) return false;
  const { base, token } = currentConfig();
  return !!store.get("configured", false) || !!(base && token);
}

async function refreshShareCookie(base, token) {
  if (!token) return;
  const ses = session.fromPartition(PARTITION);
  try {
    await ses.cookies.set({
      url: base,
      name: "share_token",
      value: token,
      path: "/",
      httpOnly: true,
      secure: base.startsWith("https:"),
      sameSite: "lax",
      expirationDate: Math.floor(Date.now() / 1000) + 7 * 24 * 3600,
    });
  } catch (err) {
    console.error("[seed] cookie set failed:", err && err.message);
  }
}

async function computeLoadUrl(route) {
  const { base, token } = currentConfig();
  if (!base) return null;
  const target = `${base}${route || "/"}`;
  if (!token) return target;

  // the ?t= is needed for SSE, which sends no cookies
  await refreshShareCookie(base, token);

  const marker = seedMarker(base, token);
  if (store.get("seededFor") !== marker) {
    const u = new URL(target);
    u.searchParams.set("t", token);
    return u.toString();
  }
  return target;
}

function markSeeded() {
  const { base, token } = currentConfig();
  if (base && token) store.set("seededFor", seedMarker(base, token));
}


function guardNavigation(event, url) {
  const appOrigin = originOf(currentConfig().base);
  let u;
  try {
    u = new URL(url);
  } catch {
    event.preventDefault();
    return;
  }
  if (appOrigin && u.origin === appOrigin) return;
  let curHost = null;
  try {
    curHost = new URL(event.sender.getURL()).hostname;
  } catch {
  }
  if (curHost && u.hostname && regDomain(u.hostname) === regDomain(curHost)) return;
  event.preventDefault();
  if (EXTERNAL_SCHEMES.has(u.protocol)) shell.openExternal(url);
}

function hardenContents(contents) {
  // top-level only, not will-frame-navigate: ejecting cross-origin iframes (recaptcha, payment on the OF login page) to the OS browser would break them
  contents.on("will-navigate", guardNavigation);
  contents.on("will-redirect", guardNavigation);

  // same-origin -> in-app child window on the shared partition (keeps group-view popouts + BroadcastChannel working); else OS browser, never a new in-app window
  contents.setWindowOpenHandler((details) => {
    const { url } = details;
    const appOrigin = originOf(currentConfig().base);
    let u;
    try {
      u = new URL(url);
    } catch {
      return { action: "deny" };
    }
    if (appOrigin && u.origin === appOrigin) {
      const { messagesPro, ...size } = sameOriginOpen(details, !!messagesProWindow && !messagesProWindow.isDestroyed());
      if (messagesPro && openInMessagesPro(url)) return { action: "deny" };
      return {
        action: "allow",
        overrideBrowserWindowOptions: {
          ...size,
          backgroundColor: "#0b0b0f",
          webPreferences: {
            preload: path.join(__dirname, "preload.js"),
            contextIsolation: true,
            nodeIntegration: false,
            sandbox: true,
            backgroundThrottling: false,
            devTools: IS_DEV,
            partition: PARTITION,
          },
        },
      };
    }
    if (EXTERNAL_SCHEMES.has(u.protocol)) shell.openExternal(url);
    return { action: "deny" };
  });
  contents.on("did-create-window", (win, { frameName }) => {
    if (frameName !== MESSAGES_PRO_WINDOW) return;
    messagesProWindow = win;
    win.on("closed", () => {
      if (messagesProWindow === win) messagesProWindow = null;
    });
  });

  contents.on("will-attach-webview", (event) => event.preventDefault());

  contents.on("context-menu", (_e, params) => {
    const template = [];
    for (const s of params.dictionarySuggestions) {
      template.push({ label: s, click: () => contents.replaceMisspelling(s) });
    }
    if (params.dictionarySuggestions.length) template.push({ type: "separator" });
    if (params.misspelledWord) {
      template.push(
        {
          label: "Add to Dictionary",
          click: () => contents.session.addWordToSpellCheckerDictionary(params.misspelledWord),
        },
        { type: "separator" },
      );
    }
    const ef = params.editFlags;
    template.push(
      { role: "cut", enabled: ef.canCut },
      { role: "copy", enabled: ef.canCopy },
      { role: "paste", enabled: ef.canPaste },
      { role: "selectAll" },
    );
    Menu.buildFromTemplate(template).popup();
  });
}

function lockDownSession() {
  const ses = session.fromPartition(PARTITION);
  const allow = new Set(["notifications"]);

  ses.setPermissionRequestHandler((wc, permission, cb) => {
    if (!allow.has(permission)) return cb(false);
    cb(isAppOrigin(wc.getURL(), originOf(currentConfig().base)));
  });
  ses.setPermissionCheckHandler((wc, permission, requestingOrigin) => {
    if (!allow.has(permission)) return false;
    return isAppOrigin(requestingOrigin || (wc ? wc.getURL() : ""), originOf(currentConfig().base));
  });
}


function sanitizeBounds(saved) {
  const def = { width: 1440, height: 900 };
  if (!saved || typeof saved !== "object") return def;
  const width = Number.isFinite(saved.width) ? saved.width : def.width;
  const height = Number.isFinite(saved.height) ? saved.height : def.height;
  if (!Number.isFinite(saved.x) || !Number.isFinite(saved.y)) return { width, height };
  // no overlap with any display (unplugged monitor): drop x/y so Electron centers it
  const overlaps = screen.getAllDisplays().some((d) => {
    const w = d.workArea;
    return saved.x < w.x + w.width && saved.x + width > w.x && saved.y < w.y + w.height && saved.y + height > w.y;
  });
  return overlaps ? { x: saved.x, y: saved.y, width, height } : { width, height };
}

function persistBounds() {
  if (!mainWindow || mainWindow.isDestroyed()) return;
  if (mainWindow.isFullScreen() || mainWindow.isMinimized()) return;
  store.set("bounds", mainWindow.getBounds());
}

function scheduleBoundsSave() {
  clearTimeout(boundsSaveTimer);
  boundsSaveTimer = setTimeout(persistBounds, 400);
}


function armScreenshot(win) {
  if (!SCREENSHOT_TO || screenshotArmed) return;
  screenshotArmed = true;
  win.webContents.once("did-finish-load", () => {
    setTimeout(async () => {
      try {
        const img = await win.webContents.capturePage();
        require("fs").writeFileSync(SCREENSHOT_TO, img.toPNG());
        console.log("[openinflowwww] screenshot written:", SCREENSHOT_TO);
      } catch (err) {
        console.error("[openinflowwww] screenshot failed:", err && err.message);
      }
      app.quit();
    }, 3000);
  });
}

// forced show after ms: a load that never paints must not leave an invisible window the Dock says is running
function showWhenReady(win, ms = 8000) {
  let shown = false;
  win.once("show", () => (shown = true));
  win.once("ready-to-show", () => win.show());
  setTimeout(() => {
    if (!shown && !win.isDestroyed() && !win.isVisible()) win.show();
  }, ms);
}

function createMainWindow() {
  const bounds = sanitizeBounds(store.get("bounds", null));
  mainWindow = new BrowserWindow({
    ...bounds,
    minWidth: 900,
    minHeight: 600,
    backgroundColor: "#0b0b0f",
    show: false,
    titleBarStyle: process.platform === "darwin" ? "hiddenInset" : "default",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      webviewTag: false,
      spellcheck: true,
      backgroundThrottling: false,
      devTools: IS_DEV,
      partition: PARTITION,
      additionalArguments: [`--infloww-rea-shell-version=${SHELL_VERSION}`],
    },
  });

  showWhenReady(mainWindow);
  armScreenshot(mainWindow);
  mainWindow.on("resize", scheduleBoundsSave);
  mainWindow.on("move", scheduleBoundsSave);
  mainWindow.on("close", (e) => {
    persistBounds();
    // macOS: closing hides the window so SSE, notifications and sounds keep running
    if (process.platform !== "darwin" || isQuitting) return;
    e.preventDefault();
    if (mainWindow.isFullScreen()) {
      mainWindow.once("leave-full-screen", () => mainWindow.hide());
      mainWindow.setFullScreen(false);
    } else {
      mainWindow.hide();
    }
  });
  mainWindow.on("closed", () => {
    mainWindow = null;
    syncChatLinkItem();
  });
  mainWindow.on("focus", () => {
    if (!streamUnseen) return;
    streamUnseen = 0;
    refreshBadge();
  });

  const wc = mainWindow.webContents;

  wc.on("did-navigate-in-page", (_e, _url, isMainFrame) => {
    if (isMainFrame) syncChatLinkItem();
  });

  wc.on("page-title-updated", (_e, title) => {
    titleUnread = parseUnread(title);
    refreshBadge();
  });

  wc.on("did-navigate", (_e, navUrl, httpResponseCode) => {
    syncChatLinkItem();
    const { base } = currentConfig();
    // seed ?t= only on a genuine 2xx main-frame load, never on an HTTP error/gate page
    if (base && navUrl.startsWith(base) && httpResponseCode >= 200 && httpResponseCode < 300) {
      markSeeded();
      relayStream.kick();
    }
  });

  wc.on("did-fail-load", (_e, errorCode, errorDesc, validatedURL, isMainFrame) => {
    if (!isMainFrame) return;
    if (errorCode === -3) return;
    showLoadProblem(errorDesc, validatedURL);
  });

  const win = mainWindow;
  const reloads = createReloadLimiter();
  const recover = () => {
    if (win.isDestroyed() || wc.isDestroyed()) return;
    if (reloads.tryReload()) loadApp();
    else showLoadProblem("The app stopped responding.", "");
  };
  wc.on("render-process-gone", (_e, details) => {
    if (details && details.reason !== "clean-exit") setImmediate(recover);
  });
  wc.on("unresponsive", recover);

  return mainWindow;
}

function currentChatLink() {
  if (!mainWindow || mainWindow.isDestroyed()) return null;
  return chatLinkForUrl(mainWindow.webContents.getURL(), originOf(currentConfig().base));
}

function syncChatLinkItem() {
  const menu = Menu.getApplicationMenu();
  const item = menu && menu.getMenuItemById("copy-app-chat-link");
  if (item) item.enabled = !!currentChatLink();
}

function currentRoute() {
  if (!mainWindow || mainWindow.isDestroyed()) return null;
  return routeToRemember(mainWindow.webContents.getURL(), originOf(currentConfig().base));
}

async function loadApp() {
  loadStarted = true;
  const route = pendingRoute || currentRoute();
  const target = await computeLoadUrl(route);
  if (!target) {
    openSettingsWindow();
    return;
  }
  if (pendingRoute === route) pendingRoute = null;
  if (!mainWindow || mainWindow.isDestroyed()) createMainWindow();
  const wc = mainWindow.webContents;
  let status = 0;
  const onNavigate = (_e, _url, code) => (status = code);
  let blockedRedirect = "";
  const onRedirect = (e) => {
    if (e.isMainFrame && e.defaultPrevented) blockedRedirect = e.url;
  };
  wc.on("did-navigate", onNavigate);
  wc.on("will-redirect", onRedirect);
  try {
    await mainWindow.loadURL(target);
  } catch (err) {
    if (IS_DEV) console.warn("[loadApp] loadURL rejected:", err && err.message);
    if (blockedRedirect) showLoadProblem(`The server redirected to ${displayUrl(blockedRedirect)}.`, target);
    return;
  } finally {
    wc.removeListener("did-navigate", onNavigate);
    wc.removeListener("will-redirect", onRedirect);
  }
  if (status >= 400) showLoadProblem(`The server answered HTTP ${status}.`, target);
  else watchForBlankPage(wc, target);
}

const BLANK_PAGE_CHECK = `(() => {
  const b = document.body;
  if (!b) return true;
  if (b.innerText.trim()) return false;
  if (document.getAnimations().some((a) => a.playState === "running")) return false;
  return ![...b.querySelectorAll("img, svg, canvas, video, iframe, input, button, textarea")].some((el) => {
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  });
})()`;

async function watchForBlankPage(wc, url) {
  for (let i = 0; i < 10; i++) {
    await new Promise((r) => setTimeout(r, 1000));
    if (wc.isDestroyed()) return;
    const blank = await wc.executeJavaScript(BLANK_PAGE_CHECK).catch(() => false);
    if (!blank) return;
  }
  showLoadProblem("The page loaded blank.", url);
}

function showLoadProblem(desc, url) {
  console.warn("[load] failed:", desc, displayUrl(url));
  openSettingsWindow({ desc: desc || "", url: displayUrl(url) });
}

function openSettingsWindow(problem) {
  const file = path.join(__dirname, "renderer", "config.html");
  const search = problem ? new URLSearchParams(problem).toString() : "";
  if (settingsWindow && !settingsWindow.isDestroyed()) {
    if (problem) {
      settingsShowsProblem = true;
      settingsWindow.loadFile(file, { search });
    }
    settingsWindow.show();
    settingsWindow.focus();
    return;
  }
  settingsShowsProblem = !!problem;
  // parent/modal only to a VISIBLE main window: a macOS sheet on a hidden parent may never present
  const anchor = mainWindow && !mainWindow.isDestroyed() && mainWindow.isVisible() ? mainWindow : undefined;
  const display = anchor ? screen.getDisplayMatching(anchor.getBounds()) : screen.getPrimaryDisplay();
  const win = new BrowserWindow({
    width: 520,
    height: Math.min(760, display.workArea.height),
    resizable: false,
    minimizable: false,
    maximizable: false,
    backgroundColor: "#0b0b0f",
    title: "Inflowwww — Settings",
    parent: anchor,
    modal: !!anchor,
    show: false,
    webPreferences: {
      preload: path.join(__dirname, "config-preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      devTools: IS_DEV,
    },
  });
  settingsWindow = win;
  win.setMenuBarVisibility(false);
  showWhenReady(win);
  armScreenshot(win);
  win.on("closed", () => {
    if (settingsWindow !== win) return;
    settingsWindow = null;
    if (settingsShowsProblem && mainWindow && !mainWindow.isDestroyed()) mainWindow.close();
  });
  win.loadFile(file, { search });
}

// the UI hydrates a PERSISTED React-Query cache (localStorage chatterly-rq-cache); a plain reload shows the stale account list
function reloadMainAfterCapture() {
  if (!mainWindow || mainWindow.isDestroyed()) return;
  mainWindow.webContents
    .executeJavaScript("try{localStorage.removeItem('chatterly-rq-cache');}catch(e){}; location.reload();")
    .catch(() => {
      try {
        mainWindow.webContents.reload();
      } catch {
      }
    });
}

async function clearSession() {
  const ses = session.fromPartition(PARTITION);
  try {
    await ses.clearStorageData({
      storages: ["cookies", "localstorage", "indexdb", "serviceworkers", "cachestorage"],
    });
  } catch (err) {
    console.error("[logout] clearStorageData failed:", err && err.message);
  }
  deleteSecret(store, "shareToken");
  tokenCache = { token: "", unreadable: false };
  store.set("seededFor", "");
  store.set("configured", false);
  stopBackground();
  if (mainWindow && !mainWindow.isDestroyed()) mainWindow.destroy();
  openSettingsWindow();
}


function isTrustedLocalSender(event) {
  const url = event.senderFrame ? event.senderFrame.url : "";
  return typeof url === "string" && url.startsWith("file://");
}

ipcMain.handle("config:get", (event) => {
  if (!isTrustedLocalSender(event)) return null;
  const { base, token } = currentConfig();
  return {
    serverUrl: base || "",
    hasToken: !!token,
    tokenUnreadable: shareTokenState().unreadable,
    skipStartupSettings: !!store.get("skipStartupSettings", false),
    isMac: process.platform === "darwin",
    shellVersion: SHELL_VERSION,
    ...readAdvanced(store),
  };
});

ipcMain.handle("config:save", async (event, incoming) => {
  if (!isTrustedLocalSender(event)) return { ok: false, error: "untrusted sender" };
  const raw = String((incoming && incoming.serverUrl) || "").trim();
  const base = normalizeBase(/^[a-z][a-z\d+.-]*:\/\//i.test(raw) ? raw : `http://${raw}`);
  if (!base) return { ok: false, error: "Enter a valid http(s) server URL." };

  const patch = {
    serverUrl: base,
    configured: true,
    skipStartupSettings: !!(incoming && incoming.skipStartupSettings),
    ...advancedPatch(incoming),
  };
  const token = incoming && typeof incoming.shareToken === "string" ? incoming.shareToken.trim() : "";
  if (token) patch.seededFor = "";
  store.setMany(patch);
  if (token) {
    setSecret(store, "shareToken", token, SECRET_CODEC);
    tokenCache = { token, unreadable: false };
  } else if (shareTokenState().unreadable) {
    deleteSecret(store, "shareToken");
    tokenCache = { token: "", unreadable: false };
  }

  const closing = settingsWindow;
  settingsWindow = null;
  settingsShowsProblem = false;
  if (closing && !closing.isDestroyed()) closing.close();
  await loadApp();
  showMain();
  startBackground();
  return { ok: true };
});

ipcMain.handle("app:restart", (event, incoming) => {
  if (!isTrustedLocalSender(event)) return;
  const patch = advancedPatch(incoming);
  if (Object.keys(patch).length) store.setMany(patch);
  app.relaunch();
  app.exit(0);
});

ipcMain.handle("app:quit", (event) => {
  if (!isTrustedLocalSender(event)) return;
  app.quit();
});

ipcMain.handle("shell:add-of-account", (event) => {
  if (!isAppOrigin(event.senderFrame ? event.senderFrame.url : "", originOf(currentConfig().base))) return;
  openOfCaptureFlow(() => currentConfig(), reloadMainAfterCapture);
});

const openGoLive = createGoLive({
  BrowserWindow,
  session,
  platform: process.platform,
  chromeMajor: chromeMajor(process.versions),
  focusWindow,
  warn: (msg) => console.warn(msg),
  fetchSession: (creatorId) =>
    relayFetch("/api/of/live-window/session", {
      method: "POST",
      headers: { Accept: "application/json", "X-Account-Id": creatorId },
      cache: "no-store",
      signal: AbortSignal.timeout(10000),
    }),
});

ipcMain.handle("shell:open-go-live", (event, rawId) => {
  if (!isAppOrigin(event.senderFrame ? event.senderFrame.url : "", originOf(currentConfig().base))) {
    return { ok: false, error: goLiveRefusal(403) };
  }
  return openGoLive(rawId);
});

// macOS: our own toast window; Electron 42+ delivers OS notifications there only for a signed app, and builds are unsigned
const TOASTS =
  process.platform === "darwin"
    ? createToasts({
        BrowserWindow,
        screen,
        ipcMain,
        preload: path.join(__dirname, "toast-preload.js"),
        html: path.join(__dirname, "renderer", "toast.html"),
      })
    : null;
const notifier = registerNotifyIpc({
  ipcMain,
  Notification: TOASTS ? TOASTS.ToastNotification : Notification,
  getAppOrigin: () => originOf(currentConfig().base),
  onClick: (appPath) => (appPath ? openInMessagesPro(appPath) || openRoute(appPath) : showMain()),
});

function relayFetch(pathname, init = {}) {
  const { base, token } = currentConfig();
  if (!base) return Promise.reject(new Error("no server configured"));
  const u = new URL(pathname, base);
  if (token) u.searchParams.set("t", token);
  return session.fromPartition(PARTITION).fetch(u.toString(), init);
}

async function relayJson(pathname, init = {}) {
  const resp = await relayFetch(pathname, {
    ...init,
    headers: { Accept: "application/json", ...(init.body ? { "Content-Type": "application/json" } : {}) },
    cache: "no-store",
    signal: AbortSignal.timeout(8000),
  });
  return resp.ok ? resp.json().catch(() => ({})) : null;
}


const seenNotices = new SeenKeys();
let notifSettings = DEFAULT_SETTINGS;
let notifBrand = DEFAULT_BRAND;
let titleUnread = 0;
let streamUnseen = 0;

function refreshBadge() {
  applyBadge({ app, win: mainWindow, nativeImage, count: Math.max(titleUnread, streamUnseen) });
}

function pageIsLive() {
  if (!mainWindow || mainWindow.isDestroyed()) return false;
  const wc = mainWindow.webContents;
  return !wc.isCrashed() && !wc.isLoading() && isAppOrigin(wc.getURL(), originOf(currentConfig().base));
}

async function readNotifSettings() {
  try {
    const raw = await Promise.race([
      mainWindow.webContents.executeJavaScript(
        `(() => { const brand = document.querySelector('meta[name="application-name"]')?.content || null;
          try { return [localStorage.getItem(${JSON.stringify(SETTINGS_KEY)}), brand]; } catch (e) { return [null, brand]; } })()`,
      ),
      new Promise((_, reject) => setTimeout(() => reject(new Error("timeout")), 1000)),
    ]);
    notifSettings = parseSettings(raw[0]);
    if (typeof raw[1] === "string" && raw[1]) notifBrand = raw[1];
  } catch {
  }
}

async function onRelayEvent(type, payload) {
  const notices = noticesFor(type, payload, notifBrand).filter((n) => seenNotices.claim(n.id));
  if (!notices.length) return;
  if (pageIsLive()) return readNotifSettings();
  const dms = notices.filter((n) => n.typeKey === "message").length;
  if (dms) {
    streamUnseen += dms;
    refreshBadge();
  }
  const appOrigin = originOf(currentConfig().base);
  for (const n of notices) if (shouldPing(notifSettings, n.typeKey)) notifier.show(n, appOrigin);
}

const relayStream = new SseClient({
  fetchStream: (lastEventId, signal) =>
    relayFetch("/events?scope=all", {
      headers: { Accept: "text/event-stream", ...(lastEventId ? { "Last-Event-ID": lastEventId } : {}) },
      cache: "no-store",
      signal,
    }),
  onEvent: (type, payload) => {
    onRelayEvent(type, payload).catch((err) => console.warn("[notify] stream event failed:", err && err.message));
  },
  log: (msg) => console.log(msg),
});


const CLOCK_POLL_MS = 60000;
let clockTimer = null;

const clock = new ClockPause({
  api: {
    status: () => relayJson("/admin/shifts/clock-status"),
    clockOut: async (id) =>
      !!(await relayJson("/admin/shifts/clock-out", { method: "POST", body: JSON.stringify({ clock_event_id: id }) })),
    clockIn: async (accountId) =>
      !!(await relayJson("/admin/shifts/clock-in", {
        method: "POST",
        body: JSON.stringify(accountId ? { account_id: accountId } : {}),
      })),
  },
  blocker: {
    start: () => powerSaveBlocker.start("prevent-app-suspension"),
    stop: (id) => powerSaveBlocker.stop(id),
  },
  log: (msg) => console.log(msg),
});

function watchPower() {
  const pause = (reason) => () => clock.pause(reason).catch(() => {});
  powerMonitor.on("suspend", pause("sleep"));
  powerMonitor.on("lock-screen", pause("lock"));
  powerMonitor.on("resume", () => {
    relayStream.kick();
    if (powerMonitor.getSystemIdleState(1) === "locked") return;
    clock.resume("wake").catch(() => {});
  });
  powerMonitor.on("unlock-screen", () => clock.resume("unlock").catch(() => {}));
}

function startBackground() {
  if (!isConfigured() || !currentConfig().base) return;
  relayStream.restart();
  clearInterval(clockTimer);
  clock.refresh().catch(() => {});
  clockTimer = setInterval(() => clock.refresh().catch(() => {}), CLOCK_POLL_MS);
}

function stopBackground() {
  relayStream.stop();
  clearInterval(clockTimer);
  clockTimer = null;
  clock.dispose();
  streamUnseen = 0;
  refreshBadge();
}


function buildMenu() {
  const isMac = process.platform === "darwin";
  const reseed = {
    label: "Re-seed Login / Fix Access",
    click: async () => {
      store.set("seededFor", "");
      await loadApp();
    },
  };
  const settings = { label: "Settings…", accelerator: "CmdOrCtrl+,", click: () => openSettingsWindow() };
  const logout = { label: "Log Out / Clear Session", click: () => clearSession() };
  const addOfAccount = {
    label: "Add OnlyFans Account…",
    click: () => openOfCaptureFlow(() => currentConfig(), reloadMainAfterCapture),
  };

  const template = [
    ...(isMac
      ? [
          {
            label: app.name,
            submenu: [
              { role: "about" },
              { type: "separator" },
              settings,
              { type: "separator" },
              { role: "services" },
              { type: "separator" },
              { role: "hide" },
              { role: "hideOthers" },
              { role: "unhide" },
              { type: "separator" },
              { role: "quit" },
            ],
          },
        ]
      : []),
    {
      label: "File",
      submenu: isMac ? [{ role: "close" }] : [settings, { type: "separator" }, { role: "quit" }],
    },
    {
      label: "Account",
      submenu: [addOfAccount, reseed, { type: "separator" }, logout],
    },
    {
      label: "Edit",
      submenu: [
        { role: "undo" },
        { role: "redo" },
        { type: "separator" },
        { role: "cut" },
        { role: "copy" },
        { role: "paste" },
        { role: "selectAll" },
        { type: "separator" },
        {
          id: "copy-app-chat-link",
          label: "Copy App Link to This Chat",
          enabled: !!currentChatLink(),
          click: () => {
            const link = currentChatLink();
            if (link) clipboard.writeText(link);
          },
        },
      ],
    },
    {
      label: "View",
      submenu: [
        {
          label: "Reload",
          accelerator: "CmdOrCtrl+R",
          click: () => mainWindow && !mainWindow.isDestroyed() && mainWindow.webContents.reload(),
        },
        { label: "Reconnect", click: () => loadApp() },
        { type: "separator" },
        { role: "resetZoom" },
        { role: "zoomIn" },
        { role: "zoomOut" },
        { type: "separator" },
        { role: "togglefullscreen" },
        ...(IS_DEV ? [{ type: "separator" }, { role: "toggleDevTools" }] : []),
      ],
    },
    {
      label: "Window",
      submenu: [{ role: "minimize" }, { role: "zoom" }, ...(isMac ? [{ role: "front" }] : [{ role: "close" }])],
    },
    {
      role: "help",
      submenu: [
        {
          label: "Open Inflowwww in Browser",
          click: () => {
            const { base } = currentConfig();
            if (base) shell.openExternal(base);
          },
        },
        { type: "separator" },
        { label: "Show Logs Folder", click: () => shell.openPath(LOG.dir) },
        { label: "Clear Cache and Relaunch", click: clearCacheAndRelaunch },
      ],
    },
  ];

  Menu.setApplicationMenu(Menu.buildFromTemplate(template));
}

async function clearCacheAndRelaunch() {
  await session
    .fromPartition(PARTITION)
    .clearCache()
    .catch((err) => console.error("[help] clearCache failed:", err && err.message));
  app.relaunch();
  app.exit(0);
}

let tray = null;
function createTray() {
  try {
    tray = new Tray(nativeImage.createFromPath(path.join(__dirname, "assets", "tray.png")));
  } catch (err) {
    console.warn("[tray] unavailable:", err && err.message);
    return;
  }
  tray.setToolTip("Inflowwww");
  tray.setContextMenu(
    Menu.buildFromTemplate([
      { label: "Open Inflowwww", click: showMain },
      { label: "Clear Cache and Relaunch", click: clearCacheAndRelaunch },
      { type: "separator" },
      { role: "quit" },
    ]),
  );
  if (process.platform !== "darwin") tray.on("click", showMain);
}


app.whenReady().then(async () => {
  describeSigning({ isPackaged: app.isPackaged })
    .then((d) => console.log("[infloww-rea-shell]", summarize(d)))
    .catch(() => {});
  // Windows shows toasts only for an app with an AppUserModelID (= build.appId)
  if (process.platform === "win32") app.setAppUserModelId("org.openinflowwww.desktop");

  app.setAboutPanelOptions({
    applicationName: "Inflowwww",
    applicationVersion: SHELL_VERSION,
    copyright: "© Inflowwww contributors",
  });

  app.on("web-contents-created", (_e, contents) => hardenContents(contents));

  // a service worker left registered by the previous run (/sw-images.js, origin-wide) makes the next launch's first navigation hang forever, so no window appears; cached images are kept
  lockDownSession();
  await session
    .fromPartition(PARTITION)
    .clearStorageData({ storages: ["serviceworkers"] })
    .catch((err) => console.warn("[startup] clearing service workers failed:", err && err.message));
  registerCaptureIpc({
    statusPreload: path.join(__dirname, "capture", "status-preload.js"),
    statusHtml: path.join(__dirname, "renderer", "capture.html"),
    interceptorPreload: path.join(__dirname, "capture", "of-interceptor-preload.js"),
    appPartition: PARTITION,
  });
  buildMenu();
  createTray();
  watchPower();

  if (ENV_URL || (isConfigured() && store.get("skipStartupSettings", false))) {
    await loadApp();
  } else {
    openSettingsWindow();
  }
  startBackground();

  app.on("activate", showMain);
});

app.on("before-quit", () => {
  isQuitting = true;
  relayStream.stop();
  clock.dispose();
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});
