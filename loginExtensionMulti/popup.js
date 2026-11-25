const OF_URL = "https://onlyfans.com/";
const LOGIN_URL = "https://onlyfans.com/";
const REQUIRED_COOKIES = ["auth_id", "sess"];

const $ = (id) => document.getElementById(id);
const loginBtn = $("login-btn");
const copyBtn = $("copy-btn");
const resetBtn = $("reset-btn");
const addAccountBtn = $("add-account-btn");
const accountsList = $("accounts-list");
const statusLine = $("status-line");
const metaBox = $("meta");
const toast = $("toast");

let currentCapture = null;

function showToast(msg, kind = "ok") {
  toast.textContent = msg;
  toast.classList.remove("show");
  toast.style.color = kind === "err" ? "var(--err)" : "var(--ok)";
  toast.style.background = kind === "err"
    ? "rgba(248,81,73,0.12)"
    : "rgba(46,160,67,0.12)";
  toast.style.borderColor = kind === "err"
    ? "rgba(248,81,73,0.4)"
    : "rgba(46,160,67,0.4)";
  void toast.offsetWidth;
  toast.classList.add("show");
  clearTimeout(showToast._t);
  showToast._t = setTimeout(() => toast.classList.remove("show"), 2500);
}

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function fmtWhen(iso) {
  if (!iso) return "";
  const t = new Date(iso).getTime();
  if (!t) return "";
  const s = Math.floor((Date.now() - t) / 1000);
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

function labelFrom(capture) {
  if (!capture) return null;
  if (capture.username) return "@" + String(capture.username).replace(/^@+/, "");
  if (capture.displayName) return String(capture.displayName);
  return null;
}

const NO_WORKER =
  "extension background is down — reload it at chrome://extensions";

// Binary trust test; the save site is exempt: it reads resp.ok then resp.savedAs (partial success: row committed, clean-up threw)
function untrusted(resp) {
  return !resp || resp.dead === true || resp.ok === false || !!resp.error;
}

function reasonOf(resp) {
  return (resp && resp.error) || NO_WORKER;
}

// 20 s per sendOnce, generous on purpose: a Fansly switch runs ensureTab twice (up to 8 s each); a timeout is retried, so ~60-80 s total
const SEND_TIMEOUT_MS = 20_000;

function sendOnce(msg) {
  return new Promise((res) => {
    const timer = setTimeout(
      () => res({ ok: false, dead: true, error: "the extension background did not answer in time" }),
      SEND_TIMEOUT_MS
    );
    const answer = (r) => { clearTimeout(timer); res(r); };
    try {
      chrome.runtime.sendMessage(msg, (r) => {
        const err = chrome.runtime.lastError;
        if (r) return answer(r);
        answer({ ok: false, dead: true, error: (err && err.message) || NO_WORKER });
      });
    } catch (e) {
      answer({ ok: false, dead: true, error: String((e && e.message) || e) || NO_WORKER });
    }
  });
}

// An MV3 service worker sleeps after ~30 s idle; the sendMessage that finds it asleep wakes it but can come back empty, so retry
function delay(ms) { return new Promise((r) => setTimeout(r, ms)); }

const ATTEMPTS = 3;

// save and switch wipe the live session and reload tabs: a retry would run the destructive half twice
function isRetryable(msg) {
  if (msg.type !== "account") return true;
  return msg.action === "list" || msg.action === "forget";
}

async function sendWithRetries(msg) {
  let last = null;
  for (let attempt = 0; attempt < ATTEMPTS; attempt++) {
    last = await sendOnce(msg);
    if (!last.dead) return last;
    if (attempt < ATTEMPTS - 1) await delay(120 * (attempt + 1));
  }
  return last;
}

async function send(msg) {
  if (isRetryable(msg)) return await sendWithRetries(msg);
  // Non-idempotent: wake the worker with a harmless read, then send the real message exactly once
  const woke = await sendWithRetries({
    type: "account", action: "list", platform: msg.platform,
  });
  if (woke.dead) return woke;
  return await sendOnce(msg);
}


async function renderAccountList(panel) {
  const resp = await send({
    type: "account", action: "list", platform: panel.platform,
  });
  if (untrusted(resp)) {
    panel.list.innerHTML =
      `<div class="empty err">Can't read saved logins — ${escapeHtml(reasonOf(resp))}</div>`;
    return;
  }
  const { accounts, activeId } = resp;
  const entries = Object.values(accounts || {}).sort((a, b) =>
    (b.savedAt || "").localeCompare(a.savedAt || "")
  );
  if (!entries.length) {
    panel.list.innerHTML =
      `<div class="empty">No ${escapeHtml(panel.siteName)} accounts saved yet — sign in to capture one.</div>`;
    return;
  }
  panel.list.innerHTML = "";
  for (const acct of entries) {
    const id = String(acct.accountId);
    const label = acct.label || labelFrom(acct.capture);
    const isActive = id === String(activeId);
    const row = document.createElement("div");
    row.className = "acct-row" + (isActive ? " active" : "");
    const btn = (act, cls, text, title) =>
      `<button data-act="${act}"${cls ? ` class="${cls}"` : ""}` +
      ` data-id="${escapeHtml(id)}" data-label="${escapeHtml(label || id)}"` +
      `${title ? ` title="${title}"` : ""}>${text}</button>`;
    row.innerHTML =
      (label
        ? `<div class="id"><span class="handle">${escapeHtml(label)}</span>` +
          `<span class="sub-id">${escapeHtml(id)}</span></div>`
        : `<div class="id">${escapeHtml(id)}</div>`) +
      `<div class="when">${escapeHtml(fmtWhen(acct.savedAt))}</div>` +
      (isActive ? `<span class="badge">active</span>` : btn("switch", "", "Use")) +
      btn("delete", "danger", "×", "Forget this login");
    panel.list.appendChild(row);
  }
}

function disarmDelete(btn) {
  delete btn.dataset.armed;
  btn.textContent = "\u00d7";
  btn.classList.remove("armed");
  clearTimeout(btn.__armTimer);
}

function armDelete(panel, btn) {
  for (const other of panel.list.querySelectorAll('button[data-armed="1"]')) {
    if (other !== btn) disarmDelete(other);
  }
  btn.dataset.armed = "1";
  btn.textContent = "Remove?";
  btn.classList.add("armed");
  btn.__armTimer = setTimeout(() => disarmDelete(btn), 4000);
}

function wireAccountList(panel) {
  panel.list.addEventListener("click", async (e) => {
    const btn = e.target.closest("button[data-act]");
    for (const armed of panel.list.querySelectorAll('button[data-armed="1"]')) {
      if (armed !== btn) disarmDelete(armed);
    }
    if (!btn) return;
    const accountId = btn.dataset.id;
    const name = btn.dataset.label || accountId;
    if (!accountId) return;

    if (btn.dataset.act === "switch") {
      btn.disabled = true;
      const resp = await send({
        type: "account", action: "switch", platform: panel.platform, accountId,
      });
      if (resp.ok) showToast(`Switched to ${name} — ${panel.siteName} reloading`);
      else {
        showToast("Switch failed: " + reasonOf(resp), "err");
        btn.disabled = false;
      }
      return;
    }

    if (btn.dataset.act === "delete") {
      // No confirm(): a modal closes an extension popup and kills this handler mid-await
      if (btn.dataset.armed !== "1") {
        armDelete(panel, btn);
        return;
      }
      btn.disabled = true;
      const resp = await send({
        type: "account", action: "forget", platform: panel.platform, accountId,
      });
      if (resp.ok) {
        showToast(`Forgot ${name}`);
        renderAccountList(panel);
      } else {
        showToast("Delete failed: " + reasonOf(resp), "err");
        btn.disabled = false;
        disarmDelete(btn);
      }
    }
  });
}

function wireSaveAndNext(panel, button) {
  button.addEventListener("click", async () => {
    button.disabled = true;
    const resp = await send({ type: "account", action: "save", platform: panel.platform });
    if (resp.ok) {
      showToast(`Saved ${resp.savedAs} — sign in to the next one`);
      renderAccountList(panel);
    // No answer does not mean nothing happened: the save may have committed and wiped the session
    } else if (resp.dead) {
      showToast(
        "No answer from the extension — reopen the popup to see whether it saved",
        "err"
      );
      renderAccountList(panel);
    } else {
      showToast("Couldn't save: " + reasonOf(resp), "err");
      if (resp.savedAs) renderAccountList(panel);
    }
    setTimeout(() => (button.disabled = false), 600);
  });
}

async function focusOrOpen(url, match) {
  const tabs = await chrome.tabs.query({ url: match });
  if (tabs.length > 0) {
    await chrome.tabs.update(tabs[0].id, { active: true });
    await chrome.windows.update(tabs[0].windowId, { focused: true });
    return tabs[0];
  }
  return await chrome.tabs.create({ url });
}

async function copyToClipboard(text, okMsg) {
  try {
    await navigator.clipboard.writeText(text);
    showToast(okMsg);
  } catch (_) {
    const ta = document.createElement("textarea");
    ta.value = text;
    document.body.appendChild(ta);
    ta.select();
    document.execCommand("copy");
    document.body.removeChild(ta);
    showToast(okMsg + " (fallback)");
  }
}

const OF_PANEL = { platform: "onlyfans", siteName: "OnlyFans", list: accountsList };
const FANSLY_PANEL = {
  platform: "fansly", siteName: "Fansly", list: $("fansly-accounts-list"),
};


function renderStatus() {
  if (!currentCapture) {
    statusLine.innerHTML = '<span class="warn">Waiting for sign-in…</span>';
    metaBox.textContent = "";
    copyBtn.disabled = true;
    addAccountBtn.disabled = true;
    return;
  }
  const h = currentCapture.headers || {};
  const r = currentCapture.rules || {};
  const haveStatic = !!r.static_param;
  statusLine.innerHTML = haveStatic
    ? '<span class="ok">✓ Captured (with signing rules)</span>'
    : '<span class="warn">✓ Headers captured — waiting for sign() to fire…</span>';
  const who = labelFrom(currentCapture);
  metaBox.innerHTML =
    (who ? `<div>account: ${escapeHtml(who)}</div>` : "") +
    `<div>user-id: ${escapeHtml(h["user-id"] || "?")}</div>` +
    `<div>x-of-rev: ${escapeHtml(h["x-of-rev"] || "?")}</div>` +
    `<div>static_param: ${haveStatic ? escapeHtml(r.static_param.slice(0, 24) + "…") : "<span class=\"warn\">not yet — open a chat in OF to trigger sign()</span>"}</div>` +
    `<div>captured: ${escapeHtml(currentCapture.capturedAt || "?")}</div>`;
  copyBtn.disabled = false;
  addAccountBtn.disabled = false;
}

function shellQuote(s) {
  return "'" + String(s).replace(/'/g, "'\\''") + "'";
}

function buildCurl(capture, cookies) {
  const h = capture.headers;
  const r = capture.rules || {};
  const url = capture.url || "https://onlyfans.com/api2/v2/users/me";
  const cookieHeader = cookies
    .filter((c) => c.value && c.name)
    .map((c) => `${c.name}=${c.value}`)
    .join("; ");

  const lines = [
    `curl ${shellQuote(url)} \\`,
    `  -H ${shellQuote("accept: application/json, text/plain, */*")} \\`,
    `  -H ${shellQuote("user-agent: " + (h["user-agent"] || navigator.userAgent))} \\`,
    `  -H ${shellQuote("user-id: " + h["user-id"])} \\`,
    `  -H ${shellQuote("x-bc: " + h["x-bc"])} \\`,
    `  -H ${shellQuote("x-of-rev: " + h["x-of-rev"])} \\`,
    `  -H ${shellQuote("sign: " + h["sign"])} \\`,
    `  -H ${shellQuote("time: " + h["time"])} \\`,
    `  -H ${shellQuote("referer: https://onlyfans.com/")} \\`,
    `  -H ${shellQuote("app-token: 33d57ade8c02dbc5a333db99ff9ae26a")}`,
  ];
  const extra = [
    ["x-relay-static-param", r.static_param],
    ["x-relay-sign-start", r.start],
    ["x-relay-sign-end", r.end],
  ];
  for (const [name, value] of extra) {
    if (!value) continue;
    lines[lines.length - 1] += " \\";
    lines.push(`  -H ${shellQuote(name + ": " + value)}`);
  }
  if (cookieHeader) {
    lines[lines.length - 1] += " \\";
    lines.push(`  -b ${shellQuote(cookieHeader)}`);
  }
  return lines.join("\n");
}

async function init() {
  const { lastCapture } = await chrome.storage.local.get(["lastCapture"]);
  currentCapture = lastCapture || null;
  renderStatus();
  renderAccountList(OF_PANEL);
  wireAccountList(OF_PANEL);
  wireSaveAndNext(OF_PANEL, addAccountBtn);

  chrome.storage.onChanged.addListener((changes, area) => {
    if (area !== "local") return;
    if (changes.lastCapture) {
      currentCapture = changes.lastCapture.newValue || null;
      renderStatus();
      if (currentCapture) showToast("New capture stored");
    }
    if (changes.accounts || changes.activeAccounts) renderAccountList(OF_PANEL);
  });

  loginBtn.addEventListener("click", async () => {
    loginBtn.disabled = true;
    try {
      await focusOrOpen(LOGIN_URL, "https://onlyfans.com/*");
      showToast("OnlyFans opened — sign in, then return here");
    } catch (e) {
      showToast("Couldn't open OnlyFans: " + e.message, "err");
    } finally {
      setTimeout(() => (loginBtn.disabled = false), 600);
    }
  });

  copyBtn.addEventListener("click", async () => {
    if (!currentCapture) return;
    const resp = await send({ type: "getCookies" });
    if (untrusted(resp)) {
      showToast("Couldn't read cookies: " + reasonOf(resp), "err");
      return;
    }
    const cookies = resp.cookies || [];
    const names = new Set(cookies.map((c) => c.name));
    const missing = REQUIRED_COOKIES.filter((n) => !names.has(n));
    if (missing.length > 0) {
      showToast("Missing cookies: " + missing.join(", ") + " — sign in first", "err");
      return;
    }
    await copyToClipboard(
      buildCurl(currentCapture, cookies),
      "Curl copied — paste into the relay's Setup tab"
    );
  });

  resetBtn.addEventListener("click", async () => {
    const resp = await send({ type: "resetCapture", platform: "onlyfans" });
    if (untrusted(resp)) {
      showToast("Couldn't clear the capture: " + reasonOf(resp), "err");
      return;
    }
    currentCapture = null;
    renderStatus();
    showToast("Cleared — sign in again to re-capture");
  });
}


let fanslyCapture = null;

function renderFansly() {
  const line = $("fansly-status-line");
  const meta = $("fansly-meta");
  const copy = $("fansly-copy-btn");
  const add = $("fansly-add-account-btn");
  if (!fanslyCapture || !fanslyCapture.token) {
    line.innerHTML = '<span class="warn">Waiting for Fansly sign-in…</span>';
    meta.textContent = "";
    copy.disabled = true;
    add.disabled = true;
    return;
  }
  line.innerHTML = '<span class="ok">✓ Fansly session captured</span>';
  const who = labelFrom(fanslyCapture);
  meta.innerHTML =
    (who ? `<div>account: ${escapeHtml(who)}</div>` : "") +
    `<div>account-id: ${escapeHtml(fanslyCapture.accountId || "?")}</div>` +
    `<div>session-id: ${escapeHtml(fanslyCapture.id || "?")}</div>` +
    `<div>device-id: ${escapeHtml(fanslyCapture.device_id || "?")}</div>` +
    `<div>captured: ${escapeHtml(fmtWhen(fanslyCapture.capturedAt) || "?")}</div>`;
  copy.disabled = false;
  add.disabled = false;
}

// Shape service/fansly_backend.py reads at fansly_session.json
function fanslySessionJson(cap) {
  return JSON.stringify({
    platform: "fansly",
    token: cap.token,
    id: cap.id,
    accountId: cap.accountId,
    device_id: cap.device_id,
    user_agent: cap.user_agent,
    accept_language: cap.accept_language || "en-US,en;q=0.9",
  }, null, 2);
}

async function initFansly() {
  const { lastFanslyCapture } = await chrome.storage.local.get(["lastFanslyCapture"]);
  fanslyCapture = lastFanslyCapture || null;
  renderFansly();
  renderAccountList(FANSLY_PANEL);
  wireAccountList(FANSLY_PANEL);
  wireSaveAndNext(FANSLY_PANEL, $("fansly-add-account-btn"));

  chrome.storage.onChanged.addListener((changes, area) => {
    if (area !== "local") return;
    if (changes.lastFanslyCapture) {
      fanslyCapture = changes.lastFanslyCapture.newValue || null;
      renderFansly();
      if (fanslyCapture) showToast("Fansly session captured");
    }
    if (changes.fanslyAccounts || changes.activeAccounts) renderAccountList(FANSLY_PANEL);
  });

  $("fansly-login-btn").addEventListener("click", async () => {
    try {
      await focusOrOpen("https://fansly.com/", "https://fansly.com/*");
      showToast("Fansly opened — sign in, then return");
    } catch (e) {
      showToast("Couldn't open Fansly: " + e.message, "err");
    }
  });

  $("fansly-copy-btn").addEventListener("click", async () => {
    if (!fanslyCapture) return;
    await copyToClipboard(
      fanslySessionJson(fanslyCapture),
      "Fansly session copied — paste into Setup (Fansly)"
    );
  });

  $("fansly-reset-btn").addEventListener("click", async () => {
    const resp = await send({ type: "resetCapture", platform: "fansly" });
    if (untrusted(resp)) {
      showToast("Couldn't clear the capture: " + reasonOf(resp), "err");
      return;
    }
    fanslyCapture = null;
    renderFansly();
    showToast("Fansly capture cleared");
  });
}

init();
initFansly();
