// Service worker — capture bookkeeping + the multi-account switcher.
//
// Both platforms want the same thing: keep several logins side by side, swap
// between them, and never hit /logout (server-side sessions stay alive for
// reuse). They differ in exactly ONE respect — where the browser keeps the
// session material:
//
//   OnlyFans  cookies            → chrome.cookies
//   Fansly    page localStorage  → chrome.scripting, MAIN world
//
// So the flows below are written once against a PLATFORMS descriptor that
// abstracts that single difference. Adding a third platform is a new entry,
// not a new copy of the machinery.

// ── OnlyFans session medium (cookies) ─────────────────────────────

const OF_COOKIE_DOMAIN = "onlyfans.com";
const OF_BASE_URL = "https://onlyfans.com/";

function cookieUrl(c) {
  const proto = c.secure ? "https" : "http";
  const host = c.domain.startsWith(".") ? c.domain.slice(1) : c.domain;
  return `${proto}://${host}${c.path}`;
}

async function getOfCookies() {
  return await chrome.cookies.getAll({ domain: OF_COOKIE_DOMAIN });
}

// The two cookies that ARE the OnlyFans session. Everything else in the jar —
// `fp`, `__cf_bm`, `lang` — is still there when you are signed OUT, which is
// why "the jar is non-empty" was never the right test for "there is a login
// here". OF's logout does not rewrite `lastCapture` either, so the popup keeps
// showing "✓ Captured" and Save stays enabled on a signed-out tab; saving then
// filed the crumbs OVER a good stored session and painted it green. That is the
// data loss this extension exists to prevent.
//
// The popup states the same two names for its copy button (`REQUIRED_COOKIES`).
const OF_REQUIRED_COOKIES = ["auth_id", "sess"];

function hasOfSession(cookies) {
  const names = new Set((cookies || []).map((c) => c.name));
  return OF_REQUIRED_COOKIES.every((n) => names.has(n));
}

async function clearOfCookies() {
  const cookies = await getOfCookies();
  await Promise.all(
    cookies.map((c) =>
      chrome.cookies
        .remove({ url: cookieUrl(c), name: c.name, storeId: c.storeId })
        .catch(() => null)
    )
  );
  // Every rejection above is swallowed — one `remove` that fails is not worth
  // failing a switch over. But swallowing ALL of them meant a wipe that removed
  // NOTHING still answered "cleared", and the popup said "sign in to the next
  // one" to a browser still signed in as the account it just filed. Judge by
  // what is actually left, and only by the cookies that carry the session: the
  // crumbs may survive, the login may not.
  if (hasOfSession(await getOfCookies())) {
    throw new Error("the OnlyFans session cookies could not be cleared");
  }
}

async function restoreOfCookies(cookies) {
  for (const c of cookies || []) {
    try {
      const set = {
        url: cookieUrl(c),
        name: c.name,
        value: c.value,
        path: c.path,
        secure: c.secure,
        httpOnly: c.httpOnly,
        sameSite: c.sameSite || "unspecified",
        storeId: c.storeId,
      };
      // hostOnly cookies must not carry a `domain` field on set()
      if (!c.hostOnly && c.domain) set.domain = c.domain;
      if (!c.session && c.expirationDate) set.expirationDate = c.expirationDate;
      await chrome.cookies.set(set);
    } catch (e) {
      console.warn("[Chatterly] cookie restore failed", c.name, e);
    }
  }
}

// ── Fansly session medium (page localStorage) ─────────────────────
//
// Fansly carries no auth cookies at all. The whole session is a JSON blob in
// the page's localStorage, which only the page itself can reach — hence
// chrome.scripting into the MAIN world.

const FANSLY_BASE_URL = "https://fansly.com/";
const FANSLY_SESSION_KEY = "session_active_session";
const FANSLY_DEVICE_KEY = "device_device_id";

// JSON.parse turns 18-19 digit snowflake ids into float64 and ROUNDS them
// (700174924320792578 -> 700174924320792600). Pre-quote any 16+ digit integer
// VALUE so those ids survive as exact strings. Same trick as the interceptors.
function parseJsonBigIntSafe(raw) {
  const safe = String(raw).replace(/:(\s*)(-?\d{16,})(\s*[,}\]])/g, ':$1"$2"$3');
  return JSON.parse(safe);
}

// Runs IN the fansly.com page (MAIN world) — no closure capture, args only.
function _fanslyStorageOp(op, sessionKey, deviceKey, blobJson, deviceRaw) {
  try {
    if (op === "read") {
      return { ok: true, blob: localStorage.getItem(sessionKey), device: localStorage.getItem(deviceKey) };
    }
    if (op === "clear") {
      // Keep the device id: Fansly ties rate limits to it, and reusing the
      // browser's own device across logins is what the real client does.
      localStorage.removeItem(sessionKey);
      return { ok: true };
    }
    if (op === "write") {
      localStorage.setItem(sessionKey, blobJson);
      if (deviceRaw != null) localStorage.setItem(deviceKey, deviceRaw);
      return { ok: true };
    }
    return { ok: false, error: "unknown op " + op };
  } catch (e) {
    return { ok: false, error: String((e && e.message) || e) };
  }
}

async function fanslyStorage(op, material = {}) {
  const tab = await ensureTab(PLATFORMS.fansly);
  const [res] = await chrome.scripting.executeScript({
    target: { tabId: tab.id },
    world: "MAIN",
    func: _fanslyStorageOp,
    args: [op, FANSLY_SESSION_KEY, FANSLY_DEVICE_KEY, material.blobJson ?? null, material.deviceRaw ?? null],
  });
  const out = res && res.result;
  if (!out || !out.ok) throw new Error((out && out.error) || "fansly storage op failed");
  return out;
}

// The session material we hand back to the browser is the RAW localStorage
// strings, kept verbatim so snowflake ids never round-trip through a number.
async function readFanslySession(accountId) {
  let raw;
  try {
    raw = await fanslyStorage("read");
  } catch (_) {
    return null;   // no live tab — caller falls back to what it already stored
  }
  // Only trust the live blob if it is actually THIS account. Mid-switch the tab
  // can already hold the next login, and filing that here would cross sessions.
  if (!raw.blob) return null;
  try {
    const parsed = parseJsonBigIntSafe(raw.blob);
    const owner = parsed && (parsed.accountId || parsed.account_id);
    if (String(owner) !== String(accountId)) return null;
  } catch (_) {
    return null;
  }
  return { blobJson: raw.blob, deviceRaw: raw.device };
}

// ── Platform descriptors ──────────────────────────────────────────
//
// The single place the two platforms differ. Everything below is generic.

const PLATFORMS = {
  onlyfans: {
    store: "accounts",
    captureKey: "lastCapture",
    baseUrl: OF_BASE_URL,
    tabMatch: "https://onlyfans.com/*",
    // Who does this capture belong to?
    idOf: (cap) => cap && cap.headers && cap.headers["user-id"],
    // Session material: read what the browser currently holds, or put it back.
    readSession: async () => {
      const cookies = await getOfCookies();
      // Not `cookies.length` — see OF_REQUIRED_COOKIES. A signed-out jar is
      // non-empty and must read as "no session here", so that the refusal in
      // saveAndClear fires instead of filing crumbs over a good saved row.
      return hasOfSession(cookies) ? { cookies } : null;
    },
    clearSession: clearOfCookies,
    writeSession: (material) => restoreOfCookies(material.cookies),
  },
  fansly: {
    store: "fanslyAccounts",
    captureKey: "lastFanslyCapture",
    baseUrl: FANSLY_BASE_URL,
    tabMatch: "https://fansly.com/*",
    idOf: (cap) => cap && cap.accountId,
    readSession: readFanslySession,
    clearSession: () => fanslyStorage("clear"),
    writeSession: (material) => fanslyStorage("write", material),
    // If no live tab could be read, a session can still be reconstructed from
    // the capture — it carries every field Fansly's client reads back.
    sessionFromCapture: (cap) => ({
      blobJson: JSON.stringify({
        token: cap.token,
        id: cap.id,
        accountId: String(cap.accountId),
        deviceId: cap.device_id,
      }),
      deviceRaw: cap.device_id || null,
    }),
  },
};

// ── Shared helpers ────────────────────────────────────────────────

// A human label for a saved login: "@handle", falling back to the display
// name, then to nothing (the popup then shows the raw id). Canonical — the
// popup imports this rule rather than restating it.
function labelFrom(capture) {
  if (!capture) return null;
  if (capture.username) return "@" + String(capture.username).replace(/^@+/, "");
  if (capture.displayName) return String(capture.displayName);
  return null;
}

async function platformTabs(p) {
  return await chrome.tabs.query({ url: p.tabMatch });
}

async function ensureTab(p) {
  const tabs = await platformTabs(p);
  if (tabs.length) return tabs[0];
  const tab = await chrome.tabs.create({ url: p.baseUrl, active: false });
  // Wait for the origin to exist before anyone tries to touch its storage.
  await new Promise((resolve) => {
    const done = (id, info) => {
      if (id === tab.id && info.status === "complete") {
        chrome.tabs.onUpdated.removeListener(done);
        resolve();
      }
    };
    chrome.tabs.onUpdated.addListener(done);
    setTimeout(() => { chrome.tabs.onUpdated.removeListener(done); resolve(); }, 8000);
  });
  return tab;
}

async function focusOrOpenTab(p) {
  const tabs = await platformTabs(p);
  if (!tabs.length) return await chrome.tabs.create({ url: p.baseUrl });
  await chrome.tabs.update(tabs[0].id, { active: true });
  await chrome.windows.update(tabs[0].windowId, { focused: true });
  return tabs[0];
}

async function reloadTabs(p) {
  const tabs = await platformTabs(p);
  if (!tabs.length) return await chrome.tabs.create({ url: p.baseUrl });
  await Promise.all(tabs.map((t) => chrome.tabs.reload(t.id).catch(() => null)));
  return await focusOrOpenTab(p);
}

// ── Which account is live, per platform ───────────────────────────
//
// Deliberately NOT derived from the capture key. The capture key is purely
// observational — the content script writes it whenever the page acts — so
// letting it also mean "the account the user selected" is what forced the old
// suppression flag: a switch had to write it, which then woke the reactive
// listener mid-reload. `activeAccounts` is written only by the explicit flows,
// so the two concerns never collide and the listener needs no guard.

async function getActiveId(p) {
  const state = await chrome.storage.local.get(["activeAccounts", p.captureKey, p.store]);
  const pinned = (state.activeAccounts || {})[p.store];
  if (pinned) return String(pinned);
  // Nothing pinned yet (fresh install, or a login captured before this ran):
  // fall back to whoever the page last observed — but only if we still hold
  // that account. Otherwise forgetting the live login would resurrect it here
  // and badge a row that no longer exists.
  const id = p.idOf(state[p.captureKey]);
  if (!id) return null;
  const accounts = state[p.store] || {};
  return accounts[String(id)] ? String(id) : null;
}

async function setActiveId(p, accountId) {
  const { activeAccounts = {} } = await chrome.storage.local.get(["activeAccounts"]);
  if (accountId) activeAccounts[p.store] = String(accountId);
  else delete activeAccounts[p.store];
  await chrome.storage.local.set({ activeAccounts });
}

// ── Generic account operations ────────────────────────────────────

// File the live session under its account id. Stores the capture (what the
// relay needs) alongside the session material (what the browser needs to be
// logged in again).
async function snapshotAccount(p) {
  const state = await chrome.storage.local.get([p.captureKey, p.store]);
  const capture = state[p.captureKey];
  const accounts = state[p.store] || {};
  const accountId = p.idOf(capture);
  if (!accountId) return null;
  const id = String(accountId);
  // An older build filed a row under the literal string "undefined" when the
  // capture had no usable id. Never create one again, and never resurrect it.
  if (id === "undefined" || id === "null") return null;

  // The tombstone check belongs HERE, not only in the reactive listener. Every
  // other caller (saveAndClear, and switchAccount snapshotting whoever was
  // live) also writes rows, and the listener's own check is separated from its
  // write by an await — so a capture already in flight when the user hit
  // Remove sailed past the check and refiled the row a moment after the
  // delete. Guarding the write itself is the only place no path can dodge.
  if ((await getTombstones(p))[id]) return null;

  const prev = accounts[id] || {};
  // No `prev.session` fallback. It used to stand in when the live read came
  // back empty, which on OnlyFans now means "signed out" — and re-filing the
  // stored session under a fresh `savedAt` would report a save to the user
  // while the live browser had nothing to save, then wipe it. Fansly, which
  // genuinely can fail to read a live tab, reconstructs from the capture.
  const material =
    (await p.readSession(id)) ||
    (p.sessionFromCapture ? p.sessionFromCapture(capture) : null);
  if (!material) return null;   // nothing worth saving

  accounts[id] = {
    accountId: id,
    label: labelFrom(capture) || prev.label || null,
    capture: capture || prev.capture || null,
    session: material,
    savedAt: new Date().toISOString(),
  };
  await chrome.storage.local.set({ [p.store]: accounts });
  return id;
}

// Save the current login, then wipe the session so the site shows a fresh
// login screen. The site is never told to log out, so the saved session
// stays valid for switching back.
async function saveAndClear(p) {
  const savedAs = await snapshotAccount(p);
  // snapshotAccount answers `null` — it does not throw — on every path where
  // there was nothing to file: no id on the capture, a junk "undefined" id, a
  // tombstone, or no session material anywhere. Clearing anyway wipes the live
  // cookies and saves nothing, and the popup used to paint that green. There is
  // no way back from it, so refuse before touching the session.
  if (!savedAs) {
    return {
      ok: false,
      savedAs: null,
      error:
        "nothing to save — you are not signed in to this site, or the " +
        "extension has not seen this login yet. Sign in, let the page load " +
        "once, then try again.",
    };
  }
  // THE ROW IS COMMITTED FROM HERE ON, and every await below can throw. The
  // envelope is RETURNED, not thrown with the id pinned to the Error: a partial
  // is a third outcome (saved, not fully cleared), and a domain with three
  // states does not fit through a channel with two. The wipe used to be the
  // only await inside the guard, so a throw in any of the other four reported a
  // clean failure over a save that stands, and the stale list stayed on screen.
  try {
    await p.clearSession();
    await chrome.storage.local.remove([p.captureKey]);
    await setActiveId(p, null);
    // The session is gone, so nothing can republish a forgotten id from a stale
    // tab any more. Whoever signs in next — including someone previously
    // forgotten — should be captured normally.
    const { forgotten = {} } = await chrome.storage.local.get(["forgotten"]);
    if (forgotten[p.store]) {
      delete forgotten[p.store];
      await chrome.storage.local.set({ forgotten });
    }
    await reloadTabs(p);
  } catch (e) {
    return {
      ok: false,
      savedAs,
      error:
        "saved " + savedAs + ", but couldn't finish clearing this browser: " +
        String(e?.message || e),
    };
  }
  return { ok: true, savedAs };
}

// Put a saved session back and reload, snapshotting whoever was live first.
async function switchAccount(p, targetId) {
  const accounts = (await chrome.storage.local.get([p.store]))[p.store] || {};
  const target = accounts[targetId];
  if (!target) throw new Error("account not found: " + targetId);
  if (!target.session) throw new Error("no stored session for " + targetId);

  const activeId = await getActiveId(p);
  if (activeId && activeId !== targetId) await snapshotAccount(p);

  // Clear then write, but only commit the bookkeeping once the write lands:
  // if writeSession throws, the stored accounts are untouched, so the user can
  // just hit Use again rather than being left with no session and a pin that
  // claims otherwise.
  await p.clearSession();
  await p.writeSession(target.session);
  // Reinstate the capture so the popup's copy button is immediately correct.
  if (target.capture) await chrome.storage.local.set({ [p.captureKey]: target.capture });
  else await chrome.storage.local.remove([p.captureKey]);
  await setActiveId(p, targetId);
  await clearTombstone(p, targetId);
  await reloadTabs(p);
  return targetId;
}

async function forgetAccount(p, accountId) {
  // Tombstone FIRST. A capture write racing this call would otherwise be
  // snapshotted between the delete and the tombstone, putting the row back
  // immediately — which is exactly what "I press X and it's still there"
  // looked like.
  await tombstone(p, accountId);

  const accounts = (await chrome.storage.local.get([p.store]))[p.store] || {};
  delete accounts[accountId];
  // Rows an older build filed under a missing id can't be deleted by their own
  // button (the button carries the same bad id), so sweep them here.
  for (const k of Object.keys(accounts)) {
    if (k === "undefined" || k === "null" || !accounts[k]) delete accounts[k];
  }
  await chrome.storage.local.set({ [p.store]: accounts });
  if ((await getActiveId(p)) === accountId) await setActiveId(p, null);

  // Forgetting the LIVE login is not enough on its own. The site tab is still
  // signed in, so its next /api2/v2/ call republishes the capture, and the
  // reactive snapshot below sees no stored row for that id, calls it a first
  // sighting, and files it straight back — the row reappears seconds after the
  // "Forgot" toast. The tombstone above is what makes the skip stick until the
  // user genuinely returns to that account (a switch, or a fresh sign-in).
}

// ── Forget tombstones ─────────────────────────────────────────────
//
// A forgotten id stays suppressed only while its session is still live in the
// tab. Any deliberate return to the account clears it, so forgetting is never
// stickier than the one thing the user asked for.

async function getTombstones(p) {
  const { forgotten = {} } = await chrome.storage.local.get(["forgotten"]);
  return forgotten[p.store] || {};
}

async function tombstone(p, accountId) {
  const { forgotten = {} } = await chrome.storage.local.get(["forgotten"]);
  const forPlatform = forgotten[p.store] || {};
  forPlatform[String(accountId)] = new Date().toISOString();
  forgotten[p.store] = forPlatform;
  await chrome.storage.local.set({ forgotten });
}

async function clearTombstone(p, accountId) {
  const { forgotten = {} } = await chrome.storage.local.get(["forgotten"]);
  const forPlatform = forgotten[p.store];
  if (!forPlatform || !(String(accountId) in forPlatform)) return;
  delete forPlatform[String(accountId)];
  forgotten[p.store] = forPlatform;
  await chrome.storage.local.set({ forgotten });
}

async function listAccounts(p) {
  const accounts = (await chrome.storage.local.get([p.store]))[p.store] || {};
  return { accounts, activeId: await getActiveId(p) };
}

// ── Message router ────────────────────────────────────────────────
//
// Every account action is {action, platform, accountId?}. The per-platform
// message names are gone along with the per-platform handlers.

const ACTIONS = {
  list:    (p) => listAccounts(p),
  // The only action that answers with its own envelope — three outcomes, so it
  // sets `ok` itself and the router's default does not apply. Do not re-wrap it.
  save:    (p) => saveAndClear(p),
  switch:  (p, id) => switchAccount(p, id).then((switchedTo) => ({ switchedTo })),
  forget:  (p, id) => forgetAccount(p, id).then(() => ({})),
};

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (!msg) return;

  // Capture pings from the bridges — logging only; the bridges write storage.
  if (msg.type === "capture" || msg.type === "fanslyCapture") {
    console.log("[Chatterly] capture received", {
      platform: msg.type === "capture" ? "onlyfans" : "fansly",
      id: msg.payload?.headers?.["user-id"] ?? msg.payload?.accountId,
      at: msg.payload?.capturedAt,
    });
    return;
  }

  if (msg.type === "getCookies") {
    getOfCookies()
      .then((cookies) => sendResponse({ cookies }))
      .catch((err) => sendResponse({ cookies: [], error: String(err?.message || err) }));
    return true;
  }

  if (msg.type === "resetCapture") {
    const p = PLATFORMS[msg.platform] || PLATFORMS.onlyfans;
    // A rejection here used to leave the held channel with no responder at all,
    // which the popup reads as a dead worker after four retries — while its own
    // handler toasted "Cleared" unconditionally. Answer either way.
    chrome.storage.local
      .remove([p.captureKey])
      .then(() => sendResponse({ ok: true }))
      .catch((e) => sendResponse({ ok: false, error: String(e?.message || e) }));
    return true;
  }

  if (msg.type === "account") {
    (async () => {
      try {
        const p = PLATFORMS[msg.platform];
        if (!p) throw new Error("unknown platform: " + msg.platform);
        const run = ACTIONS[msg.action];
        if (!run) throw new Error("unknown action: " + msg.action);
        const accountId = msg.accountId ? String(msg.accountId) : null;
        if ((msg.action === "switch" || msg.action === "forget") && !accountId) {
          throw new Error("missing accountId");
        }
        // `ok: true` is the default an action opts OUT of: the spread lands
        // after it, so an action that returns its own `ok` (saveAndClear, whose
        // domain has three outcomes) wins. Everything else returns a payload
        // and is a success by arriving.
        sendResponse({ ok: true, ...(await run(p, accountId)) });
      } catch (e) {
        sendResponse({ ok: false, error: String(e?.message || e) });
      }
    })();
    return true;
  }

  // An unrecognised type used to fall off the end of this listener returning
  // `undefined`, which the popup cannot tell apart from a worker that never
  // woke: four retries, ~725 ms, and "extension background is down" for what is
  // a routing bug on our side. Name it.
  sendResponse({ ok: false, error: "unknown message type: " + String(msg.type) });
  return true;
});

// ── Reactive bookkeeping ──────────────────────────────────────────
//
// Keep the saved-logins list populated without manual snapshots. This reacts
// ONLY to what the page observed; the explicit flows above pin `activeAccounts`
// themselves, so nothing here can fire mid-switch and cross two sessions.

for (const p of Object.values(PLATFORMS)) {
  chrome.storage.onChanged.addListener((changes, area) => {
    if (area !== "local" || !changes[p.captureKey]) return;
    const next = changes[p.captureKey].newValue;
    const accountId = p.idOf(next);
    if (!accountId) return;
    const id = String(accountId);
    chrome.storage.local.get([p.store]).then(async ({ [p.store]: accounts = {} }) => {
      // Forgotten while still signed in: the tab keeps publishing, but the user
      // already said they don't want this login kept. Skip until they return.
      if ((await getTombstones(p))[id]) return;
      const prev = accounts[id];
      // First sighting, or >30s since the last save — avoids re-snapshotting on
      // every sign() tick within an active session. The one exception is a row
      // still showing a bare id: the handle arrives on a later publish than the
      // headers, so a row saved before /users/me was seen must take the label
      // as soon as one exists rather than waiting out the window.
      const gainsLabel = prev && !prev.label && !!labelFrom(next);
      const stale = !prev || Date.now() - new Date(prev.savedAt).getTime() > 30_000;
      if (!stale && !gainsLabel) return;
      await snapshotAccount(p);
      // A login the user reached by signing in (not via Use) becomes active.
      if (!(await getActiveId(p))) await setActiveId(p, id);
    }).catch((e) => {
      // Nothing awaits this chain. Without a catch, a rejecting getTombstones
      // or snapshotAccount is a silent unhandled rejection in a service worker
      // and the reactive snapshot simply stops filing logins, with no signal
      // anywhere. At least leave a trace in the worker console.
      console.warn("[Chatterly] reactive snapshot failed", p.store, e);
    });
  });
}

// One-time cleanup of junk rows an older build left behind — a login filed
// under a missing id (key "undefined"/"null"), which the popup renders as a
// dead row whose own X can't remove it reliably. Runs on install and on every
// service-worker start so it heals without the user having to do anything.
async function sweepJunkRows() {
  const patch = {};
  for (const p of Object.values(PLATFORMS)) {
    const accounts = (await chrome.storage.local.get([p.store]))[p.store];
    if (!accounts) continue;
    let dirty = false;
    for (const k of Object.keys(accounts)) {
      if (k === "undefined" || k === "null" || !accounts[k] || !accounts[k].accountId
          || accounts[k].accountId === "undefined" || accounts[k].accountId === "null") {
        delete accounts[k];
        dirty = true;
      }
    }
    if (dirty) patch[p.store] = accounts;
  }
  if (Object.keys(patch).length) await chrome.storage.local.set(patch);
}

chrome.runtime.onInstalled.addListener(() => {
  console.log("[Chatterly] login capture extension installed");
  sweepJunkRows();
});
chrome.runtime.onStartup.addListener(sweepJunkRows);
// Also run right now, so reloading the unpacked extension (which does not always
// fire onInstalled) still clears a stale row on this very load.
sweepJunkRows();
