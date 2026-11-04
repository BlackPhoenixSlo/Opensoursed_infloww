"use strict";

// Which relay events become a notification when the page can't show them
// (crashed, reloading, never loaded): the main-process stream (lib/sse.js)
// turns them into `fasttShell.notify`-shaped payloads for lib/notify.js.
//
// Mirrors the page's NotificationToaster (app/components/NotificationToaster.tsx)
// for the three lanes that ping: an inbound DM (`api2_chat_message`), a PPV
// unlock (`purchase_notified`) and OF's own `toasts` feed (new subs, likes …);
// a tip rides on the DM lane (isTip).
// Same ids (`<account>:<claimUnseen id>`, so lib/notify.js dedupes a ping the
// page also sends), same hrefs, same gate: the user's in-app settings
// (`chatterly:notif-settings:v1`, read from the page while it runs — see
// main.js), so a type muted in the app stays muted here. Not mirrored: the
// per-platform switch (the stream doesn't say which platform an account is on)
// and the page's ping for an OF toast type it can't name (skipped here).
//
// Electron-free; test/relay-notices.test.js covers it.

// app/lib/notifSettings.ts DEFAULT_NOTIF_SETTINGS, the fields used here.
const DEFAULT_SETTINGS = Object.freeze({
  enabled: true,
  osPing: true,
  toast: Object.freeze({
    message: false,
    purchases: true,
    tip: true,
    subscribed: false,
    mentioned: false,
    commented: false,
    favorited: false,
  }),
});

const SETTINGS_KEY = "chatterly:notif-settings:v1";

/** The stored JSON string (or null) over the defaults, as readNotifSettings(). */
function parseSettings(raw) {
  let parsed = null;
  try {
    parsed = typeof raw === "string" ? JSON.parse(raw) : null;
  } catch {
    parsed = null;
  }
  if (!parsed || typeof parsed !== "object") return DEFAULT_SETTINGS;
  return {
    enabled: typeof parsed.enabled === "boolean" ? parsed.enabled : DEFAULT_SETTINGS.enabled,
    osPing: typeof parsed.osPing === "boolean" ? parsed.osPing : DEFAULT_SETTINGS.osPing,
    toast: { ...DEFAULT_SETTINGS.toast, ...(parsed.toast && typeof parsed.toast === "object" ? parsed.toast : {}) },
  };
}

function shouldPing(settings, typeKey) {
  return !!(settings.enabled && settings.osPing && typeKey && settings.toast[typeKey]);
}

// app/lib/notifSettings.ts mapOfTypeToKey.
function typeKeyOf(rawType) {
  if (!rawType || typeof rawType !== "string") return null;
  const t = rawType.toLowerCase();
  if (t === "message" || t === "messages" || t === "chatmessage") return "message";
  if (t === "tip" || t === "tips") return "tip";
  if (t === "purchase" || t === "purchases" || t === "paided_message") return "purchases";
  if (t === "subscribed" || t === "subscriber" || t === "subscription") return "subscribed";
  if (t === "commented" || t === "comment") return "commented";
  if (t === "mentioned" || t === "mention") return "mentioned";
  if (t === "favorited" || t === "favorite" || t === "like" || t === "liked") return "favorited";
  return null;
}

// app/lib/fanId.ts isValidFanId: a positive integer, as a number or a string.
function isFanId(v) {
  if (typeof v !== "number" && typeof v !== "string") return false;
  if (typeof v === "number" && !Number.isSafeInteger(v)) return false;
  const s = String(v);
  return /^\d+$/.test(s) && !/^0+$/.test(s);
}

// app/lib/brand.ts BRAND_NAME's default; main.js passes the page's.
const DEFAULT_BRAND = "Inflowwww";

// app/lib/notifText.ts renderText: OF text is HTML with {PLACEHOLDER}s; lib/notify.js caps the result.
function renderText(raw, replacements) {
  let s = typeof raw === "string" ? raw : "";
  if (replacements && typeof replacements === "object") {
    for (const [k, v] of Object.entries(replacements)) s = s.split(k).join(String(v));
  }
  return s.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim();
}

// app/lib/format.ts fmtPrice: cents → "$7", "$7.50", "$1,234.56".
function fmtPrice(cents) {
  const c = Math.sign(cents) * Math.round(Math.abs(cents));
  const digits = c % 100 === 0 ? 0 : 2;
  const s = (Math.abs(c) / 100).toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });
  return `${c < 0 ? "-" : ""}$${s}`;
}

// app/lib/notificationLink.ts notificationHref: the Fan's Deep link (by
// username when no id), `?refresh=media` for money, `fanTab` = the tab's name.
function notificationHref(accountId, user, refresh) {
  const acc = encodeURIComponent(accountId);
  let path;
  if (user.id) path = `/messages-pro/${acc}/${user.id}`;
  else if (user.username) path = `/messages-pro/${acc}/u/${encodeURIComponent(user.username)}`;
  else return null;
  const q = new URLSearchParams(refresh ? { refresh: "media" } : {});
  q.set("fanTab", user.name || user.username || `fan ${user.id}`);
  return `${path}?${q}`;
}

const isMoney = (typeKey) => typeKey === "tip" || typeKey === "purchases";

// app/components/toastStore.ts extractUsernameFromHtml.
function usernameFromHtml(raw) {
  const m = typeof raw === "string" && raw.match(/href=["']https?:\/\/(?:www\.)?onlyfans\.com\/([A-Za-z0-9._-]+)["']/i);
  return m ? m[1] : undefined;
}

function notice(accountId, id, typeKey, user, body, href, brand) {
  return { id: `${accountId}:${id}`, typeKey, title: user.name || user.username || brand, body, href };
}

/**
 * One relay event → zero or more notices `{ id, typeKey, title, body, href }`
 * (`href` null when there is no fan to open), exactly as the page's
 * toastStore builds them (`noticeOf` over `dmArrival` / `purchaseArrival` /
 * `toastArrival`); service/tests/fixtures/notice_cases.json pins both.
 * `brand`: the title when the event names no one.
 */
function noticesFor(type, env, brand = DEFAULT_BRAND) {
  const accountId = env && env.__account_id ? String(env.__account_id) : null;
  if (!accountId) return [];

  if (type === "api2_chat_message") {
    const msg = env.api2_chat_message;
    const from = msg && msg.fromUser;
    if (!msg || msg.id == null || !from || !isFanId(from.id)) return [];
    if (String(from.id) === accountId) return []; // our own send never pings
    const user = { id: from.id, name: from.name || from.username, username: from.username };
    // A tip is a DM with isTip, its dollars in tipAmount (else price).
    if (msg.isTip) {
      const cents = Math.round((Number(msg.tipAmount) || Number(msg.price) || 0) * 100);
      const body = cents > 0 ? `Tipped you ${fmtPrice(cents)}` : "Sent you a tip";
      return [notice(accountId, `m${msg.id}`, "tip", user, body, notificationHref(accountId, user, true), brand)];
    }
    const body = renderText(typeof msg.text === "string" ? msg.text.trim() : "") ||
      ((msg.mediaCount || 0) > 0 ? "Sent you media" : "Sent you a message");
    return [notice(accountId, `m${msg.id}`, "message", user, body, notificationHref(accountId, user, false), brand)];
  }

  if (type === "purchase_notified") {
    const p = env.purchase_notified;
    if (!p || !p.notif_id || !isFanId(p.fan_id)) return [];
    const cents = Number(p.amount_cents);
    const user = { id: p.fan_id, name: p.name || undefined };
    const body = Number.isFinite(cents) && cents > 0 ? `Unlocked your PPV — ${fmtPrice(cents)}` : "Unlocked your PPV";
    return [notice(accountId, String(p.notif_id), "purchases", user, body, notificationHref(accountId, user, true), brand)];
  }

  if (type === "toasts" && Array.isArray(env.toasts)) {
    const out = [];
    for (const t of env.toasts) {
      if (!t || typeof t !== "object" || t.id == null) continue;
      const typeKey = typeKeyOf(t.type);
      if (!typeKey) continue; // a type the settings can't name: the page alone pings it
      const rawText = (typeof t.text === "string" && t.text) || (typeof t.description === "string" && t.description) ||
        (typeof t.title === "string" && t.title) || "";
      const data = t.data && typeof t.data === "object" ? t.data : {};
      const related = data.relatedUser && typeof data.relatedUser === "object" ? data.relatedUser : {};
      const repl = data.replacements && typeof data.replacements === "object" ? data.replacements : undefined;
      const fromUser = t.fromUser && typeof t.fromUser === "object" ? t.fromUser : {};
      const recipient = t.user && typeof t.user === "object" ? t.user : {};
      const relatedRaw = related.id ?? (repl && repl["{RELATED_USER_ID}"] ? Number(repl["{RELATED_USER_ID}"]) : undefined);
      const relatedId = typeof relatedRaw === "number" && Number.isFinite(relatedRaw) ? relatedRaw : undefined;
      const str = (v) => (typeof v === "string" && v ? v : undefined);
      const user = {
        id: relatedId ?? fromUser.id,
        name: str(related.name) || str(repl && repl["{RELATED_USER_NAME}"]) || fromUser.name || recipient.name,
        username: str(related.username) || str(repl && repl["{RELATED_USER_LOGIN}"]) || fromUser.username ||
          usernameFromHtml(rawText) || recipient.username,
      };
      const body = renderText(rawText, repl || t.replacePairs) || t.type;
      out.push(notice(accountId, String(t.id), typeKey, user, body, notificationHref(accountId, user, isMoney(typeKey)), brand));
    }
    return out;
  }

  return [];
}

// Bounded "seen" set: the relay's replay after a reconnect reaches back further
// than lib/notify.js's one-minute dedupe. Oldest ids fall off first.
class SeenKeys {
  constructor(max = 1000) {
    this.max = max;
    this.keys = new Set();
  }

  claim(key) {
    if (this.keys.has(key)) return false;
    this.keys.add(key);
    while (this.keys.size > this.max) this.keys.delete(this.keys.values().next().value);
    return true;
  }
}

module.exports = { DEFAULT_BRAND, DEFAULT_SETTINGS, SETTINGS_KEY, parseSettings, shouldPing, noticesFor, SeenKeys };
