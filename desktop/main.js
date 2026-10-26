"use strict";

// ───────────────────────────────────────────────────────────────────────────
// Inflowwww desktop shell — main process.
//
// A thin, deliberately-boring Electron window onto the Inflowwww Next app
// (server URL: env OPENINFLOWW_URL > stored Settings). Every launch opens the
// Settings window first unless the user ticked "Don't show this again" or the
// env override is set; a failed load always reopens it. It imports NOTHING
// from app/ or service/ and ships no product code — it only knows a URL and a
// relay share token. Deleting this folder leaves the web app untouched.
//
// Design comes from the fusion review (the old plan/DESKTOP_APP_PLAN.md, tag legacy-ui-final → "FUSION
// HARDENING") and was hardened by a second adversarial multi-agent review:
//   • Remote-load only (same origin as the app ⇒ cookies/SSE/rewrites work
//     with zero relay changes). NEVER bundle the UI (that's a relay redesign).
//   • Deny-by-default navigation on will-navigate / will-redirect /
//     will-frame-navigate; external links → OS browser; same-origin popouts
//     (group view) allowed as child windows on the shared partition.
//   • Least privilege: nodeIntegration off, contextIsolation on, sandbox on, no
//     Node/IPC bridge exposed to the remote page (only a static version object).
//     The local Settings page gets its own trusted preload.
//   • The trust origin is read LIVE from config inside each handler, so changing
//     the server in Settings can't leave a window trusting the old origin.
//   • Seed the relay share token into the partition (cookie + localStorage via
//     the frontend's own ?t= mechanism) ONCE, only on a 2xx load, keeping the
//     token out of URLs/logs/history everywhere else.
//   • A real in-app "Log Out / Clear Session" destroys the on-disk credential —
//     the fusion revocation concern.
//
// What this shell deliberately does NOT do: capture OnlyFans sessions. Per the
// fusion review that stays in the Chrome extension (moving it into Electron is a
// detection regression against the creator's account). The app consumes the
// session the relay already holds; it never creates one.
// ───────────────────────────────────────────────────────────────────────────

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
const { DEFAULT_SETTINGS, SETTINGS_KEY, parseSettings, shouldPing, noticesFor, SeenKeys } = require("./lib/relay-notices");
const { ClockPause } = require("./lib/clock-pause");
const { registerCaptureIpc, openOfCaptureFlow } = require("./capture/of-capture");

const IS_DEV = process.argv.includes("--dev");
// Internal identifiers keep the old "fastt" name on purpose: renaming the
// partition would drop every user's session.
const PARTITION = "persist:fastt";
// Dev-only: `--screenshot-to <path>` captures the first window (Settings or the
// main window) ~3s after it loads, writes a PNG and quits.
const SCREENSHOT_TO = (() => {
  const i = process.argv.indexOf("--screenshot-to");
  return i !== -1 && process.argv[i + 1] ? path.resolve(process.argv[i + 1]) : null;
})();
const SHELL_VERSION = app.getVersion();
const EXTERNAL_SCHEMES = new Set(["http:", "https:", "mailto:", "tel:", "sms:"]);

app.setName("Inflowwww");
// userData keeps the pre-rename "OpenInfloww" folder name on purpose, like the
// partition above: setName alone would move it and log every user out.
app.setPath("userData", path.join(app.getPath("appData"), "OpenInfloww"));

// ── Pre-ready: local log, crash dumps, advanced options ─────────────────────
// console.* also goes to <userData>/logs/main.log with the share token redacted
// (lib/logfile.js). Crash dumps stay local (<userData>/Crashpad); nothing uploads.
const SECRET_CODEC = safeStorageCodec(safeStorage);
const LOG = createLogFile({
  dir: path.join(app.getPath("userData"), "logs"),
  getSecrets: () => [tokenCache && tokenCache.token], // in-memory only, never the keychain
});
mirrorConsole(console, LOG);
crashReporter.start({ uploadToServer: false });
// The one config store, read before ready because hardware acceleration must be
// decided then.
const store = new Store(app.getPath("userData"));
const ADVANCED = readAdvanced(store);
applyBeforeReady(app, ADVANCED);
app.whenReady().then(() => applyAfterReady(app, ADVANCED));

// ── Single-instance + app links ─────────────────────────────────────────────
// A second launch focuses whatever window we have. An `inflowwww://chat/…` link
// (lib/deeplink.js) opens that chat: macOS delivers it via `open-url` (at launch
// too, before ready), Windows/Linux as an argument — startup process.argv, or
// the `second-instance` argv when the app is already running.
const { SCHEME, parseDeepLink, deepLinkFromArgv, chatLinkForUrl } = require("./lib/deeplink");
const { createReloadLimiter, routeToRemember } = require("./lib/recovery");

let pendingRoute = null; // an app link waiting for the next loadApp()
let loadStarted = false; // the startup loadApp() has run (it consumes a queued link)

if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  pendingRoute = deepLinkFromArgv(process.argv);
  if (process.defaultApp) {
    // `electron .` run: the OS must launch the Electron binary with our app path.
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

// Show the main window (it may be hidden: macOS hide-on-close), else load the
// app, or Settings when there is no server yet.
function showMain() {
  if (mainWindow && !mainWindow.isDestroyed()) return focusWindow(mainWindow);
  isConfigured() ? loadApp() : openSettingsWindow();
}

// Open an app-link route in the main window. It is queued in pendingRoute and
// loaded by the next loadApp(): the startup one (app not ready / still booting),
// the one after Settings is saved (not configured yet), or the one called here.
function openRoute(route) {
  if (!route) return;
  pendingRoute = route;
  if (!app.isReady()) return; // isConfigured() reads the keychain, which needs ready
  if (!isConfigured()) return openSettingsWindow();
  if (!loadStarted) return; // startup gap: the startup loadApp() takes it
  if (mainWindow && !mainWindow.isDestroyed()) focusWindow(mainWindow);
  loadApp();
}

// The Messages Pro window while it is open (lib/window-open.js). A route of its
// own (a notification's link, a Messages Pro link opened as a tab) opens there,
// focused, leaving the main window where it is. False: none open, or not one.
let messagesProWindow = null;
function openInMessagesPro(route) {
  return openInMessagesProWindow(messagesProWindow, route, originOf(currentConfig().base), focusWindow);
}

let mainWindow = null;
let settingsWindow = null;
let settingsShowsProblem = false; // Settings is up because a load failed
let boundsSaveTimer = null;
let isQuitting = false; // set by before-quit; see the main window's close handler
let screenshotArmed = false;

function liveWindow() {
  // Prefer a currently-VISIBLE window (Settings when it is up) over a
  // backgrounded main window, so a second launch focuses what the user is
  // actually looking at.
  const wins = [settingsWindow, mainWindow].filter((w) => w && !w.isDestroyed());
  return wins.find((w) => w.isVisible()) || wins[0] || null;
}

// ── URL / token helpers ─────────────────────────────────────────────────────

function normalizeBase(rawUrl) {
  // Returns the http(s) ORIGIN only (no path) or null. We only ever load the app
  // root and append the route ourselves, so keeping a user-supplied path would
  // double it and give a sub-path-scoped cookie.
  try {
    const u = new URL(String(rawUrl).trim());
    if (u.protocol !== "http:" && u.protocol !== "https:") return null;
    return serverOrigin(u.origin); // a saved/typed landing URL → the app (lib/origin.js)
  } catch {
    return null;
  }
}

function regDomain(host) {
  // Approx registrable domain (last two labels). Correct for our 2-label domains
  // (your-host.example.com, onlyfans.com); a multi-part TLD like co.uk would over-narrow, but
  // we only use it to keep a window navigating within the SITE it's already on.
  if (!host) return "";
  const parts = String(host).split(".");
  return parts.slice(-2).join(".");
}

// OPENINFLOWW_URL overrides the stored server URL for this run only; it is
// never written to the config store.
const ENV_URL = normalizeBase(process.env.OPENINFLOWW_URL || "");
if (process.env.OPENINFLOWW_URL && !ENV_URL) {
  console.warn("[openinflowwww] ignoring OPENINFLOWW_URL (not a valid http(s) URL):", process.env.OPENINFLOWW_URL);
}

// The URL as shown to the user: no ?t= token, no query, no hash.
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

// The share token is OS-encrypted on disk (lib/secret.js) and decrypted once,
// on first use after ready; config:save and clearSession replace this cache.
// unreadable = stored but undecryptable → treated as missing.
let tokenCache = null; // { token, unreadable }

function shareTokenState() {
  if (!tokenCache) {
    const secret = getSecret(store, "shareToken", SECRET_CODEC);
    tokenCache = { token: secret || "", unreadable: secret === null };
  }
  return tokenCache;
}

function currentConfig() {
  // No built-in default server: a guessed URL (it used to be localhost:3001)
  // silently points the app at whatever happens to run there. Unset → Settings.
  const base = ENV_URL || normalizeBase(store.get("serverUrl", "")) || null;
  return { base, token: shareTokenState().token };
}

function isConfigured() {
  // "configured" is tracked explicitly so a deliberately tokenless (share-gate
  // disabled) install still auto-loads the app instead of re-prompting forever.
  // An undecryptable token sends the user back to Settings to paste it again;
  // config:save then drops the bad blob, so this can't loop.
  if (ENV_URL) return true;
  if (shareTokenState().unreadable) return false;
  const { base, token } = currentConfig();
  return !!store.get("configured", false) || !!(base && token);
}

// Proactively (re)write the relay share-token cookie into the partition so even
// the top-level HTML request carries it and it never lapses mid-use.
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

// Decide the URL to load. On the first load for a given (server, token) we append
// ?t= so the frontend's resolveShareToken() persists it to localStorage (needed
// for SSE, which sends no cookies; resolveShareToken() reads it on any route).
// `route` is an app path (an app link or the route to restore), default the
// Dashboard (/). Not /inbox: that redirects to Messages Pro, which is a window
// of its own (the page sees to that, app/components/shell/AppShell.tsx).
async function computeLoadUrl(route) {
  const { base, token } = currentConfig();
  if (!base) return null;
  const target = `${base}${route || "/"}`;
  if (!token) return target; // gate-off / not yet tokened → let the UI's own login show.

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

// ── Security: applied to EVERY web contents (main + popouts + local pages) ───

function guardNavigation(event, url) {
  // Deny-by-default. Allowed in-window: (1) the Inflowwww app origin, and (2) staying
  // within the SITE the window is already on. The main window is always on
  // your-host.example.com, so (2) does not widen its policy — it exists so the OnlyFans
  // capture window can navigate onlyfans.com (login redirects) in-window instead
  // of being ejected. Foreign http(s) + mailto/tel/sms → OS browser; every other
  // scheme (file:, custom) is blocked outright.
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
    /* no current url */
  }
  if (curHost && u.hostname && regDomain(u.hostname) === regDomain(curHost)) return;
  event.preventDefault();
  if (EXTERNAL_SCHEMES.has(u.protocol)) shell.openExternal(url);
}

function hardenContents(contents) {
  // Gate TOP-LEVEL navigation only: will-navigate + its server-side 30x redirects.
  // Intentionally NOT will-frame-navigate — it fires for every sub-frame, and
  // ejecting cross-origin IFRAMES (recaptcha, payment, embeds — present on the OF
  // login page) to the OS browser would break them and spam external opens.
  // Sub-frames load in-frame like a normal browser; the browser sandboxes them.
  contents.on("will-navigate", guardNavigation);
  contents.on("will-redirect", guardNavigation);

  // window.open / target=_blank: same-origin → in-app child window on the shared
  // partition (keeps group-view popouts + BroadcastChannel working), or the open
  // Messages Pro window for a Messages Pro link opened as a tab
  // (lib/window-open.js); anything else → OS browser, never a new in-app window.
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

  // Right-click menu: spellcheck suggestions + cut/copy/paste. A typing-heavy
  // chat tool needs these; without a handler the OS/Chromium menu never shows.
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
  const allow = new Set(["notifications"]); // the UI already fires web Notifications.

  ses.setPermissionRequestHandler((wc, permission, cb) => {
    if (!allow.has(permission)) return cb(false);
    cb(isAppOrigin(wc.getURL(), originOf(currentConfig().base)));
  });
  ses.setPermissionCheckHandler((wc, permission, requestingOrigin) => {
    if (!allow.has(permission)) return false;
    // Chromium may hand over "https://host/" or "" (lib/origin.js parses; "" → the page's URL).
    return isAppOrigin(requestingOrigin || (wc ? wc.getURL() : ""), originOf(currentConfig().base));
  });
}

// ── Window bounds ─────────────────────────────────────────────────────────────

function sanitizeBounds(saved) {
  const def = { width: 1440, height: 900 };
  if (!saved || typeof saved !== "object") return def;
  const width = Number.isFinite(saved.width) ? saved.width : def.width;
  const height = Number.isFinite(saved.height) ? saved.height : def.height;
  if (!Number.isFinite(saved.x) || !Number.isFinite(saved.y)) return { width, height };
  // Drop x/y (let Electron center) if the saved rect no longer overlaps any
  // display — otherwise a monitor that's been unplugged strands the window
  // off-screen and invisible.
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

// ── Windows ─────────────────────────────────────────────────────────────────

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

// Show on first paint, or after `ms` regardless: a load that never paints (a
// stuck navigation, a hung server) must not leave an invisible window that the
// Dock says is running. Only the first show is forced; a later hide is respected.
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
      backgroundThrottling: false, // keep SSE/reconnect alive while minimized/occluded
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
    // macOS: closing hides the window so the page keeps running (SSE,
    // notifications, sounds); the Dock icon (activate) shows it again.
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
  // Looking at the app: the stream's unseen DMs are seen.
  mainWindow.on("focus", () => {
    if (!streamUnseen) return;
    streamUnseen = 0;
    refreshBadge();
  });

  const wc = mainWindow.webContents;

  // Keep "Copy App Link to This Chat" enabled only while on a chat.
  wc.on("did-navigate-in-page", (_e, _url, isMainFrame) => {
    if (isMainFrame) syncChatLinkItem();
  });

  // Unread badge from the page title (best-effort; see lib/badge.js), or the
  // stream's own count while the page is down.
  wc.on("page-title-updated", (_e, title) => {
    titleUnread = parseUnread(title);
    refreshBadge();
  });

  // Mark the (server, token) pair seeded ONLY on a genuine 2xx main-frame load —
  // never on an HTTP error/gate page, which would suppress the ?t= reseed.
  wc.on("did-navigate", (_e, navUrl, httpResponseCode) => {
    syncChatLinkItem();
    const { base } = currentConfig();
    if (base && navUrl.startsWith(base) && httpResponseCode >= 200 && httpResponseCode < 300) {
      markSeeded();
      relayStream.kick(); // signed in now? retry a stream the relay refused
    }
  });

  // Connection failure → Settings, so a wrong URL can be fixed right there.
  wc.on("did-fail-load", (_e, errorCode, errorDesc, validatedURL, isMainFrame) => {
    if (!isMainFrame) return;
    if (errorCode === -3) return; // ERR_ABORTED — superseded/redirected load.
    showLoadProblem(errorDesc, validatedURL);
  });

  // Renderer crash / hang → reload on its own, at most 3 times in 5 minutes
  // (lib/recovery.js); past that, Settings with the failure noted instead of a reload loop.
  // A window torn down on purpose (logout's destroy()) is never brought back;
  // the check runs a tick later so it also holds if the event fires mid-destroy.
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

// The main window's app link when it is on a chat, else null (lib/deeplink.js).
function currentChatLink() {
  if (!mainWindow || mainWindow.isDestroyed()) return null;
  return chatLinkForUrl(mainWindow.webContents.getURL(), originOf(currentConfig().base));
}

function syncChatLinkItem() {
  const menu = Menu.getApplicationMenu();
  const item = menu && menu.getMenuItemById("copy-app-chat-link");
  if (item) item.enabled = !!currentChatLink();
}

// The main window's current route on the configured server (its last committed
// URL, which a crashed or failed page still reports), else null — so a server
// change or a fresh window (reopen, after logout) starts at the Dashboard.
function currentRoute() {
  if (!mainWindow || mainWindow.isDestroyed()) return null;
  return routeToRemember(mainWindow.webContents.getURL(), originOf(currentConfig().base));
}

// Load a queued app link, else restore the current route, else the Dashboard.
async function loadApp() {
  loadStarted = true;
  const route = pendingRoute || currentRoute();
  const target = await computeLoadUrl(route);
  if (!target) {
    openSettingsWindow();
    return;
  }
  if (pendingRoute === route) pendingRoute = null; // a link that arrived meanwhile stays queued
  if (!mainWindow || mainWindow.isDestroyed()) createMainWindow();
  const wc = mainWindow.webContents;
  // loadURL resolves for an HTTP error page too, so note the main-frame status.
  let status = 0;
  const onNavigate = (_e, _url, code) => (status = code);
  // guardNavigation blocks a redirect off the app origin (http → https, apex →
  // www); that fails the load with no did-fail-load, so note it here.
  let blockedRedirect = "";
  const onRedirect = (e) => {
    if (e.isMainFrame && e.defaultPrevented) blockedRedirect = e.url;
  };
  wc.on("did-navigate", onNavigate);
  wc.on("will-redirect", onRedirect);
  try {
    await mainWindow.loadURL(target);
  } catch (err) {
    // did-fail-load already opens Settings; swallow the aborted/network
    // rejection so it doesn't surface as an unhandled promise rejection.
    if (IS_DEV) console.warn("[loadApp] loadURL rejected:", err && err.message);
    if (blockedRedirect) showLoadProblem(`The server redirected to ${displayUrl(blockedRedirect)}.`, target);
    return;
  } finally {
    wc.removeListener("did-navigate", onNavigate);
    wc.removeListener("will-redirect", onRedirect);
  }
  // 4xx/5xx (a wrong server's 404, the share gate's 401) → Settings.
  if (status >= 400) showLoadProblem(`The server answered HTTP ${status}.`, target);
  else watchForBlankPage(wc, target);
}

// True when the page shows no text, no running animation (a spinner) and no
// visible image/control: a blank or black page.
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

// A 2xx load can still render nothing (a broken bundle, a server that answers an
// empty page). Give the app ~10s to hydrate; blank the whole time → Settings.
async function watchForBlankPage(wc, url) {
  for (let i = 0; i < 10; i++) {
    await new Promise((r) => setTimeout(r, 1000));
    if (wc.isDestroyed()) return;
    const blank = await wc.executeJavaScript(BLANK_PAGE_CHECK).catch(() => false);
    if (!blank) return;
  }
  showLoadProblem("The page loaded blank.", url);
}

// Any failed load reopens Settings, ignoring "Don't show this again", with what
// failed shown on top; its Save & Open is the retry.
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
  // Only parent/modal to the main window when it is actually VISIBLE. A macOS
  // document-modal sheet on a hidden/absent parent may never present, stranding
  // the user with no way forward from the error/logout state.
  const anchor = mainWindow && !mainWindow.isDestroyed() && mainWindow.isVisible() ? mainWindow : undefined;
  // Fit short screens; the page scrolls if a long failure note still overflows.
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
    if (settingsWindow !== win) return; // detached by Save & Open
    settingsWindow = null;
    // Dismissed without saving after a failed load: close the blank main window
    // too rather than leave it empty. On macOS the Dock icon then retries the
    // load; elsewhere the app quits.
    if (settingsShowsProblem && mainWindow && !mainWindow.isDestroyed()) mainWindow.close();
  });
  win.loadFile(file, { search });
}

// After a native OnlyFans capture saves an account, refresh the hosted UI so the
// new account shows up in the Accounts list without a manual Cmd+R. A plain
// reload isn't enough — the UI hydrates a PERSISTED React-Query cache
// (localStorage `chatterly-rq-cache`) and shows the stale account list. Clearing
// that cache key first forces a fresh fetch on reload.
function reloadMainAfterCapture() {
  if (!mainWindow || mainWindow.isDestroyed()) return;
  mainWindow.webContents
    .executeJavaScript("try{localStorage.removeItem('chatterly-rq-cache');}catch(e){}; location.reload();")
    .catch(() => {
      try {
        mainWindow.webContents.reload();
      } catch {
        /* ignore */
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
  // Tear the authenticated window down entirely (a fresh one is created on the
  // next load). destroy() is synchronous, so openSettingsWindow() below sees
  // no live main window and opens a normal, non-modal settings window.
  if (mainWindow && !mainWindow.isDestroyed()) mainWindow.destroy();
  openSettingsWindow();
}

// ── IPC (only from our LOCAL trusted page: config.html) ──────────────────────

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
  // A bare host ("inflowwww.com", "localhost:3011") gets http://, as in a browser.
  const raw = String((incoming && incoming.serverUrl) || "").trim();
  const base = normalizeBase(/^[a-z][a-z\d+.-]*:\/\//i.test(raw) ? raw : `http://${raw}`);
  if (!base) return { ok: false, error: "Enter a valid http(s) server URL." };

  // normalizeBase keeps the origin only, so a pasted #hash/path/query is dropped.
  const patch = {
    serverUrl: base,
    configured: true,
    skipStartupSettings: !!(incoming && incoming.skipStartupSettings),
    ...advancedPatch(incoming),
  };
  const token = incoming && typeof incoming.shareToken === "string" ? incoming.shareToken.trim() : "";
  if (token) patch.seededFor = ""; // force a fresh ?t= seed for the new token
  store.setMany(patch);
  if (token) {
    setSecret(store, "shareToken", token, SECRET_CODEC);
    tokenCache = { token, unreadable: false };
  } else if (shareTokenState().unreadable) {
    deleteSecret(store, "shareToken"); // saved blank over an undecryptable token: drop it
    tokenCache = { token: "", unreadable: false };
  }

  // Detach before closing: a fast failure of the load below must open a fresh
  // Settings window, not reuse this closing one.
  const closing = settingsWindow;
  settingsWindow = null;
  settingsShowsProblem = false;
  if (closing && !closing.isDestroyed()) closing.close();
  await loadApp();
  showMain(); // loadApp() reuses a main window macOS hide-on-close may have hidden
  startBackground(); // the server or token may have changed
  return { ok: true };
});

// Settings → Advanced → Restart: keep the switches as shown, then relaunch so
// they take effect.
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

// Triggered by the native "Connect OnlyFans" button that preload.js injects into
// the hosted page. Only the app's OWN remote origin may fire it, and all it does
// is open a login window — no data crosses.
ipcMain.handle("shell:add-of-account", (event) => {
  if (!isAppOrigin(event.senderFrame ? event.senderFrame.url : "", originOf(currentConfig().base))) return;
  openOfCaptureFlow(() => currentConfig(), reloadMainAfterCapture);
});

// Notifications for the hosted page (`fasttShell.notify`, row 3.3) and the
// relay stream below; see lib/notify.js. macOS shows them in our own toast
// window (lib/toast-window.js): Electron 42+ there delivers OS notifications
// only for a signed app, and builds are unsigned. Elsewhere, native ones.
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
  // A notification's link opens in the Messages Pro window when one is open;
  // else the main window loads it and hands it to a new one (AppShell).
  onClick: (appPath) => (appPath ? openInMessagesPro(appPath) || openRoute(appPath) : showMain()),
});

// ── Relay requests from the main process ────────────────────────────────────
// Authenticated as the page's own fetches are: the partition's cookies (as
// capture/of-capture.js) plus `?t=` (app/lib/relay.ts).
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

// ── Notifications + badge while the page can't (lib/sse.js) ─────────────────
// The page notifies and badges from its own event stream. While it is crashed,
// reloading or not loaded, this main-process stream does it instead; while the
// page runs, it only keeps the page's notification settings at hand.

const seenNotices = new SeenKeys(); // the relay's replay must not ping twice
let notifSettings = DEFAULT_SETTINGS; // the page's, as last read
let titleUnread = 0; // from the page title (lib/badge.js)
let streamUnseen = 0; // inbound DMs that arrived while the page was down

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
        `(() => { try { return localStorage.getItem(${JSON.stringify(SETTINGS_KEY)}); } catch (e) { return null; } })()`,
      ),
      new Promise((_, reject) => setTimeout(() => reject(new Error("timeout")), 1000)),
    ]);
    notifSettings = parseSettings(raw);
  } catch {
    /* keep the last known */
  }
}

async function onRelayEvent(type, payload) {
  const notices = noticesFor(type, payload).filter((n) => seenNotices.claim(n.id));
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

// ── Sleep / lock pauses the time-tracking clock (lib/clock-pause.js) ─────────

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
    // Woken to a lock screen: unlock-screen clocks back in.
    if (powerMonitor.getSystemIdleState(1) === "locked") return;
    clock.resume("wake").catch(() => {});
  });
  powerMonitor.on("unlock-screen", () => clock.resume("unlock").catch(() => {}));
}

// Start (or restart, after a server/token change) what talks to the relay from
// the main process. A no-op until configured.
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

// ── Menu ─────────────────────────────────────────────────────────────────────

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

// HTTP cache only: cookies and storage stay, so the user stays logged in.
async function clearCacheAndRelaunch() {
  await session
    .fromPartition(PARTITION)
    .clearCache()
    .catch((err) => console.error("[help] clearCache failed:", err && err.message));
  app.relaunch();
  app.exit(0);
}

// Menu-bar (macOS) / notification-area icon: the way back to a hidden window.
let tray = null; // kept referenced, or GC removes the icon
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

// ── Lifecycle ─────────────────────────────────────────────────────────────────

app.whenReady().then(async () => {
  // Log the bundle's signing state once at boot (why: lib/signing.js).
  describeSigning({ isPackaged: app.isPackaged })
    .then((d) => console.log("[infloww-rea-shell]", summarize(d)))
    .catch(() => {});
  // Windows shows toasts only for an app with an AppUserModelID (= build.appId).
  if (process.platform === "win32") app.setAppUserModelId("org.openinflowwww.desktop");

  app.setAboutPanelOptions({
    applicationName: "Inflowwww",
    applicationVersion: SHELL_VERSION,
    copyright: "© Inflowwww contributors",
  });

  // Harden every web contents that ever gets created — main, popouts, and the
  // local Settings page.
  app.on("web-contents-created", (_e, contents) => hardenContents(contents));

  lockDownSession();
  // A service worker left registered by the previous run (the app's /sw-images.js,
  // scoped to the whole origin) makes the first navigation of the next launch hang
  // forever in Electron, so the main window never reaches ready-to-show and no
  // window appears. Unregister it before loading; the app re-registers it, and the
  // cached images (Cache Storage) are kept.
  await session
    .fromPartition(PARTITION)
    .clearStorageData({ storages: ["serviceworkers"] })
    .catch((err) => console.warn("[startup] clearing service workers failed:", err && err.message));
  registerCaptureIpc({
    statusPreload: path.join(__dirname, "capture", "status-preload.js"),
    statusHtml: path.join(__dirname, "renderer", "capture.html"),
    interceptorPreload: path.join(__dirname, "capture", "of-interceptor-preload.js"),
    appPartition: PARTITION, // Finish & Save posts with the app's session cookie
  });
  buildMenu();
  createTray();
  watchPower();

  // Settings first on every launch, unless the user opted out (and has a
  // config to load) or the env override names the server.
  if (ENV_URL || (isConfigured() && store.get("skipStartupSettings", false))) {
    await loadApp();
  } else {
    openSettingsWindow();
  }
  startBackground();

  app.on("activate", showMain);
});

// Cmd+Q / menu Quit fires this before any window closes, so the macOS
// hide-on-close lets the main window really close.
app.on("before-quit", () => {
  isQuitting = true;
  relayStream.stop();
  clock.dispose();
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});
