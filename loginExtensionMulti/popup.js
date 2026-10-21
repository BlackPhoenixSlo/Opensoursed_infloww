// Popup UI logic.
//
// Two panels — OnlyFans and Fansly — over one shared saved-logins widget.
// The account list, its click handling and the label rules are written once
// and driven by a per-panel descriptor; only the capture-specific bits (the
// OF curl, the Fansly session JSON) are platform code.

const OF_URL = "https://onlyfans.com/";
const LOGIN_URL = "https://onlyfans.com/";  // OF shows the login modal on root if signed-out
const REQUIRED_COOKIES = ["auth_id", "sess"];  // OF's session cookies

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
  // Force reflow so re-adding .show triggers the transition fresh.
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

// The one rule for turning a capture into a human label. Mirrors labelFrom()
// in background.js, which is what actually gets stored on the account record.
function labelFrom(capture) {
  if (!capture) return null;
  if (capture.username) return "@" + String(capture.username).replace(/^@+/, "");
  if (capture.displayName) return String(capture.displayName);
  return null;
}

// Everything except the Status box goes through the service worker. When that
// worker is down — a registration that failed, a start that threw, an extension
// reloaded out from under an open popup — sendMessage answers with `undefined`
// and the real reason sits in chrome.runtime.lastError. The old `r || {}` threw
// that away, and one dead worker then told three separate lies: an empty
// saved-logins list ("no accounts saved yet"), a save that failed with a bare
// "?", and a "Missing cookies — sign in first" on an account that was signed in
// the whole time. Carry the failure so the popup can say the one true thing.
const NO_WORKER =
  "extension background is down — reload it at chrome://extensions";

// THE ONE TRUST TEST. Every caller asks this, not "is the worker dead" — the
// question is "did I get an answer I can show the user as fact". Three shapes
// fail it and only one of them is a dead worker:
//
//   1. `dead`      — sendMessage never reached a handler.
//   2. `ok === false` — a handler ran and threw; the router's catch returns a
//      TRUTHY envelope, which sails past any `if (resp.dead)` guard and then
//      destructures to `accounts === undefined` → "No accounts saved yet".
//      That is the exact state that makes someone sign in again and overwrite
//      a good session.
//   3. `error` set — a handler answered with a plausible payload AND a reason
//      it is empty. `getCookies` does precisely this (`{cookies: [], error}`),
//      which is how "Missing cookies — sign in first" was shown to an account
//      that was signed in the whole time.
//
// ⚠️ ONE CALLER IS EXEMPT, DELIBERATELY: the save site (`wireSaveAndNext`).
// This predicate is BINARY — trusted or not — and `save` answers over a domain
// that has THREE states: clean success, clean failure, and a PARTIAL success
// where the account row was committed and the clean-up threw
// (`{ok: false, savedAs, error}` from background.js's saveAndClear). `untrusted`
// would collapse that third state into the second and the stale list on screen
// would stand, so the save site reads `resp.ok` and then `resp.savedAs` itself.
// Any NEW partial-success envelope has the same problem; do not route it here.
function untrusted(resp) {
  return !resp || resp.dead === true || resp.ok === false || !!resp.error;
}

// The reason to put in front of the user. Never hardcode NO_WORKER at a call
// site: a channel error with a real cause of its own was being reported as
// "background is down" regardless of what it actually said.
function reasonOf(resp) {
  return (resp && resp.error) || NO_WORKER;
}

// sendMessage can also throw SYNCHRONOUSLY — "Extension context invalidated",
// the case the comment above names, when the extension is reloaded out from
// under an open popup. Inside a `new Promise` executor that rejects the
// promise, so the guard below never runs and whatever placeholder is in the
// HTML stands for the life of the popup. Answer with the dead envelope
// instead, so there is exactly one failure shape to handle.
const SEND_TIMEOUT_MS = 20_000;

function sendOnce(msg) {
  return new Promise((res) => {
    // A handler that accepts the channel and then hangs would leave this
    // awaiting forever with the clicked button disabled and no feedback. The
    // ceiling is deliberately generous, not the 5 s that first suggests
    // itself: a Fansly switch goes through fanslyStorage → ensureTab TWICE
    // (clear then write) and ensureTab alone waits up to 8 s for a new tab to
    // load. A shorter timeout would report failure on a switch that is about
    // to succeed — a fresh lie in place of the old one.
    //
    // ⚠️ 20 s is PER `sendOnce`, NOT what the user waits. A timeout resolves
    // `{dead: true}`, which is exactly the shape `sendWithRetries` retries, so
    // the real ceilings are:
    //   ~60 s  a retryable message (3 × 20 s + 120 ms + 240 ms of backoff)
    //   ~80 s  save / switch — `send` wakes the worker with a retryable `list`
    //          (up to ~60 s) and only then sends the real message once
    // Still bounded, and every path ends in a toast rather than a stuck button;
    // but do not read "20 s" here as the answer to "how long can this hang".
    const timer = setTimeout(
      () => res({ ok: false, dead: true, error: "the extension background did not answer in time" }),
      SEND_TIMEOUT_MS
    );
    const answer = (r) => { clearTimeout(timer); res(r); };
    try {
      chrome.runtime.sendMessage(msg, (r) => {
        // Reading lastError is also what stops Chrome logging it as unchecked.
        const err = chrome.runtime.lastError;
        if (r) return answer(r);
        answer({ ok: false, dead: true, error: (err && err.message) || NO_WORKER });
      });
    } catch (e) {
      answer({ ok: false, dead: true, error: String((e && e.message) || e) || NO_WORKER });
    }
  });
}

// An MV3 service worker sleeps after ~30s idle. The very sendMessage that finds
// it asleep is also what wakes it, but the first call can come back empty while
// it is still spinning up — which is the whole "works only right after a reload"
// symptom: a fresh load has a live worker, a day-old one does not. So a dead
// reply gets a couple of retries with a short backoff; by then the worker is up
// and answering. Only a worker that never comes back reports the failure.
function delay(ms) { return new Promise((r) => setTimeout(r, ms)); }

// One try plus two retries — 120 ms then 240 ms of backoff, 360 ms total. The
// previous shape ran the loop three times AND made a fourth call after it, so
// a dead worker cost 720 ms of pure sleep and one redundant send whose answer
// the loop had already produced.
const ATTEMPTS = 3;

// Retrying is only safe for a message that lands on the same state however
// many times it runs. `save` and `switch` are not: each wipes the live session
// and reloads the site's tabs, so a retry runs the destructive half a SECOND
// time and answers about that second run — which is how a save that did work
// came back as `{savedAs: null}` and toasted "Cleared". `list` and `getCookies`
// change nothing; `forget` and `resetCapture` settle at one state.
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
  // Non-idempotent. The retries existed to wake a sleeping worker, so do that
  // with a harmless read first and then send the real message exactly once.
  const woke = await sendWithRetries({
    type: "account", action: "list", platform: msg.platform,
  });
  if (woke.dead) return woke;
  return await sendOnce(msg);
}

// ── Saved-logins list (shared by both panels) ─────────────────────

// A panel is: which platform it drives, which <div> holds its rows, and what
// the site is called in user-facing text.
async function renderAccountList(panel) {
  const resp = await send({
    type: "account", action: "list", platform: panel.platform,
  });
  // An untrustworthy reply must not render as "nothing saved yet" — the saved
  // logins are still on disk, we just cannot vouch for this answer, and telling
  // the user they are gone is what makes them sign in again and overwrite a
  // good session. Show the reason the reply actually carried.
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
    // The label rides on the buttons as data-label so toasts and confirms can
    // read it back without scraping rendered text out of the DOM.
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

// Two-click delete. The button turns into an explicit "Remove?" for a few
// seconds; clicking anything else, or letting it time out, stands down.
function disarmDelete(btn) {
  delete btn.dataset.armed;
  btn.textContent = "\u00d7";
  btn.classList.remove("armed");
  clearTimeout(btn.__armTimer);
}

function armDelete(panel, btn) {
  // Only one row can be armed at a time.
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
    // Any click that is not the armed button itself stands it down.
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
      // No confirm() here. A modal dialog CLOSES an extension popup, which
      // kills this handler mid-await — the forget message never goes out and
      // the row is still there next time the popup opens. Confirmation is a
      // second click on the same button instead: it arms, and only the armed
      // click deletes.
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

// "Save current & log in to another" — identical for both platforms.
function wireSaveAndNext(panel, button) {
  button.addEventListener("click", async () => {
    button.disabled = true;
    const resp = await send({ type: "account", action: "save", platform: panel.platform });
    if (resp.ok) {
      // No `savedAs ? … : "Cleared"` ternary any more. `saveAndClear` REFUSES
      // when there is nothing to file, so `ok:true` with a falsy `savedAs` is
      // unreachable — and the else-leg was the exact wrong toast: it painted a
      // save that saved nothing as a successful "Cleared", green, with the live
      // cookies gone and no way back.
      showToast(`Saved ${resp.savedAs} — sign in to the next one`);
      renderAccountList(panel);
    } else if (resp.dead) {
      // The worker never answered. Unlike every other failure this one does NOT
      // mean the work did not happen: `send` puts a non-idempotent message on
      // the wire exactly once, and a save that outlived the timeout may have
      // committed the row and wiped the session. Saying "couldn't save" over
      // that is the same lie in the other direction, so say what is true.
      showToast(
        "No answer from the extension — reopen the popup to see whether it saved",
        "err"
      );
      renderAccountList(panel);
    } else {
      showToast("Couldn't save: " + reasonOf(resp), "err");
      // A save can fail AFTER the row was committed (the wipe threw). The
      // worker says so by carrying `savedAs` on a not-ok envelope; the list on
      // screen is then already stale.
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

// ── OnlyFans panel ────────────────────────────────────────────────

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
  // POSIX-safe single-quote: end quote, escape ', re-open.
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
  // Runtime-only fields the wire doesn't carry but the relay needs for
  // a brand-new x-of-rev. The relay's curl parser recognises these as
  // overrides and never forwards them upstream.
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
    // `getCookies` answers `{cookies: [], error}` when chrome.cookies throws —
    // truthy, `dead` falsy — so the old guard let it through and the empty list
    // below produced "Missing cookies: auth_id, sess — sign in first" on an
    // account that was signed in. An empty list is only news if we trust it.
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
    // "Cleared" used to be toasted unconditionally, including when the worker
    // never answered and the capture is still sitting there.
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

// ── Fansly panel ──────────────────────────────────────────────────
//
// Fansly needs no signing: the whole session is a small JSON blob the content
// scripts lift out of localStorage, so this panel copies that verbatim.

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

function fanslySessionJson(cap) {
  // Exactly the shape service/fansly_backend.py reads at fansly_session.json.
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
