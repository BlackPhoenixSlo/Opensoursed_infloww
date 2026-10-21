"use strict";

// Which relay events become a notification when the page can't show them
// (crashed, reloading, never loaded): the main-process stream (lib/sse.js)
// turns them into `fasttShell.notify`-shaped payloads for lib/notify.js.
//
// Mirrors the page's NotificationToaster (app/components/NotificationToaster.tsx)
// for the three lanes that ping: an inbound DM (`api2_chat_message`), a PPV
// unlock (`purchase_notified`) and OF's own `toasts` feed (tips, new subs …).
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

// OF text is HTML with {PLACEHOLDER}s; lib/notify.js caps the result.
function stripHtml(raw, replacements) {
  let s = typeof raw === "string" ? raw : "";
  if (replacements && typeof replacements === "object") {
    for (const [k, v] of Object.entries(replacements)) s = s.split(k).join(String(v));
  }
  return s.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim();
}

// The page's chat href; tips and buys add the one-shot `?refresh=media`.
function chatHref(accountId, fanId, typeKey) {
  const href = `/messages-pro/${encodeURIComponent(accountId)}/${fanId}`;
  return typeKey === "tip" || typeKey === "purchases" ? `${href}?refresh=media` : href;
}

/**
 * One relay event → zero or more notices `{ id, typeKey, title, body, href }`
 * (`href` null when there is no fan to open).
 */
function noticesFor(type, env) {
  const accountId = env && env.__account_id ? String(env.__account_id) : null;
  if (!accountId) return [];

  if (type === "api2_chat_message") {
    const msg = env.api2_chat_message;
    const from = msg && msg.fromUser;
    if (!msg || msg.id == null || !from || !isFanId(from.id)) return [];
    if (String(from.id) === accountId) return []; // our own send never pings
    const body = stripHtml(msg.text) || ((msg.mediaCount || 0) > 0 ? "Sent you media" : "Sent you a message");
    return [{
      id: `${accountId}:m${msg.id}`,
      typeKey: "message",
      title: from.name || from.username || "Inflowwww",
      body,
      href: chatHref(accountId, String(from.id), "message"),
    }];
  }

  if (type === "purchase_notified") {
    const p = env.purchase_notified;
    if (!p || !p.notif_id || !isFanId(p.fan_id)) return [];
    const cents = Number(p.amount_cents);
    return [{
      id: `${accountId}:${p.notif_id}`,
      typeKey: "purchases",
      title: p.name || "Inflowwww",
      body: Number.isFinite(cents) && cents > 0 ? `Unlocked your PPV — $${(cents / 100).toFixed(2)}` : "Unlocked your PPV",
      href: chatHref(accountId, String(p.fan_id), "purchases"),
    }];
  }

  if (type === "toasts" && Array.isArray(env.toasts)) {
    const out = [];
    for (const t of env.toasts) {
      if (!t || typeof t !== "object" || t.id == null) continue;
      const typeKey = typeKeyOf(t.type);
      if (!typeKey) continue;
      const data = t.data && typeof t.data === "object" ? t.data : {};
      const related = data.relatedUser && typeof data.relatedUser === "object" ? data.relatedUser : {};
      const repl = data.replacements && typeof data.replacements === "object" ? data.replacements : t.replacePairs;
      const fromUser = t.fromUser && typeof t.fromUser === "object" ? t.fromUser : {};
      const fanRaw = related.id ?? (repl && repl["{RELATED_USER_ID}"]) ?? fromUser.id;
      out.push({
        id: `${accountId}:${t.id}`,
        typeKey,
        title: related.name || (repl && repl["{RELATED_USER_NAME}"]) || fromUser.name || "Inflowwww",
        body: stripHtml(t.text || t.description || t.title, repl) || t.type,
        href: isFanId(fanRaw) ? chatHref(accountId, String(fanRaw), typeKey) : null,
      });
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

module.exports = { DEFAULT_SETTINGS, SETTINGS_KEY, parseSettings, shouldPing, noticesFor, SeenKeys };
