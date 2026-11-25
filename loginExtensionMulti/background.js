// Never hit /logout: server-side sessions stay alive for reuse.
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

// auth_id + sess are the session; fp/__cf_bm/lang survive a sign-out, so a non-empty jar is not a login.
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
  // Individual remove() failures are swallowed, so judge by what is left, and only by the session cookies.
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


const FANSLY_BASE_URL = "https://fansly.com/";
const FANSLY_SESSION_KEY = "session_active_session";
const FANSLY_DEVICE_KEY = "device_device_id";

function parseJsonBigIntSafe(raw) {
  // JSON.parse rounds 18-19 digit snowflake ids; pre-quote 16+ digit values so they stay exact strings.
  const safe = String(raw).replace(/:(\s*)(-?\d{16,})(\s*[,}\]])/g, ':$1"$2"$3');
  return JSON.parse(safe);
}

function _fanslyStorageOp(op, sessionKey, deviceKey, blobJson, deviceRaw) {
  try {
    if (op === "read") {
      return { ok: true, blob: localStorage.getItem(sessionKey), device: localStorage.getItem(deviceKey) };
    }
    if (op === "clear") {
      localStorage.removeItem(sessionKey);
      return { ok: true };
    }
    if (op === "write") {
      localStorage.setItem(sessionKey, blobJson);
      // Keep the browser's device id: Fansly ties rate limits to it.
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

async function readFanslySession(accountId) {
  let raw;
  try {
    raw = await fanslyStorage("read");
  } catch (_) {
    return null;
  }
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


const PLATFORMS = {
  onlyfans: {
    store: "accounts",
    captureKey: "lastCapture",
    baseUrl: OF_BASE_URL,
    tabMatch: "https://onlyfans.com/*",
    idOf: (cap) => cap && cap.headers && cap.headers["user-id"],
    readSession: async () => {
      const cookies = await getOfCookies();
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


async function getActiveId(p) {
  const state = await chrome.storage.local.get(["activeAccounts", p.captureKey, p.store]);
  const pinned = (state.activeAccounts || {})[p.store];
  if (pinned) return String(pinned);
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


async function snapshotAccount(p) {
  const state = await chrome.storage.local.get([p.captureKey, p.store]);
  const capture = state[p.captureKey];
  const accounts = state[p.store] || {};
  const accountId = p.idOf(capture);
  if (!accountId) return null;
  const id = String(accountId);
  // An older build filed rows under the literal "undefined"; never create or resurrect one.
  if (id === "undefined" || id === "null") return null;

  // Guard the write itself: a capture in flight during Remove would otherwise refile the row after the delete.
  if ((await getTombstones(p))[id]) return null;

  const prev = accounts[id] || {};
  // No prev.session fallback: on OnlyFans an empty live read means signed out; refiling the stored session would fake a save, then wipe it.
  const material =
    (await p.readSession(id)) ||
    (p.sessionFromCapture ? p.sessionFromCapture(capture) : null);
  if (!material) return null;

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

async function saveAndClear(p) {
  const savedAs = await snapshotAccount(p);
  // Refuse before touching the session: a null snapshot saves nothing and the wipe cannot be undone.
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
  try {
    // The row is committed from here: a throw returns a partial envelope (saved, not fully cleared), not a clean failure.
    await p.clearSession();
    await chrome.storage.local.remove([p.captureKey]);
    await setActiveId(p, null);
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

async function switchAccount(p, targetId) {
  const accounts = (await chrome.storage.local.get([p.store]))[p.store] || {};
  const target = accounts[targetId];
  if (!target) throw new Error("account not found: " + targetId);
  if (!target.session) throw new Error("no stored session for " + targetId);

  const activeId = await getActiveId(p);
  if (activeId && activeId !== targetId) await snapshotAccount(p);

  // Commit bookkeeping only after writeSession lands, so a failed write leaves stored accounts untouched.
  await p.clearSession();
  await p.writeSession(target.session);
  if (target.capture) await chrome.storage.local.set({ [p.captureKey]: target.capture });
  else await chrome.storage.local.remove([p.captureKey]);
  await setActiveId(p, targetId);
  await clearTombstone(p, targetId);
  await reloadTabs(p);
  return targetId;
}

async function forgetAccount(p, accountId) {
  // Tombstone first, and it must outlive the live tab: the tab keeps publishing and would refile the row seconds later.
  await tombstone(p, accountId);

  const accounts = (await chrome.storage.local.get([p.store]))[p.store] || {};
  delete accounts[accountId];
  for (const k of Object.keys(accounts)) {
    if (k === "undefined" || k === "null" || !accounts[k]) delete accounts[k];
  }
  await chrome.storage.local.set({ [p.store]: accounts });
  if ((await getActiveId(p)) === accountId) await setActiveId(p, null);

}


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


const ACTIONS = {
  list:    (p) => listAccounts(p),
  save:    (p) => saveAndClear(p),
  switch:  (p, id) => switchAccount(p, id).then((switchedTo) => ({ switchedTo })),
  forget:  (p, id) => forgetAccount(p, id).then(() => ({})),
};

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (!msg) return;

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
        // Spread after ok:true so an action returning its own ok (saveAndClear, three outcomes) wins.
        sendResponse({ ok: true, ...(await run(p, accountId)) });
      } catch (e) {
        sendResponse({ ok: false, error: String(e?.message || e) });
      }
    })();
    return true;
  }

  sendResponse({ ok: false, error: "unknown message type: " + String(msg.type) });
  return true;
});


for (const p of Object.values(PLATFORMS)) {
  chrome.storage.onChanged.addListener((changes, area) => {
    if (area !== "local" || !changes[p.captureKey]) return;
    const next = changes[p.captureKey].newValue;
    const accountId = p.idOf(next);
    if (!accountId) return;
    const id = String(accountId);
    chrome.storage.local.get([p.store]).then(async ({ [p.store]: accounts = {} }) => {
      // Forgotten while still signed in: the tab keeps publishing; skip until the user returns.
      if ((await getTombstones(p))[id]) return;
      const prev = accounts[id];
      const gainsLabel = prev && !prev.label && !!labelFrom(next);
      // Re-snapshot at most every 30 s per row, except a bare-id row that just gained its handle.
      const stale = !prev || Date.now() - new Date(prev.savedAt).getTime() > 30_000;
      if (!stale && !gainsLabel) return;
      await snapshotAccount(p);
      if (!(await getActiveId(p))) await setActiveId(p, id);
    }).catch((e) => {
      console.warn("[Chatterly] reactive snapshot failed", p.store, e);
    });
  });
}

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
sweepJunkRows();
