"use client";


import { isAlertSoundId, type AlertSoundId } from "./alertSounds";
import { persistJSON, readJSON } from "./persist";
import type { FanId } from "@/lib/fanId";
import type { Platform } from "@/lib/platform";

export type NotifTypeKey =
  | "message"
  | "purchases"
  | "tip"
  | "subscribed"
  | "commented"
  | "mentioned"
  | "favorited";

export const NOTIF_TYPES: { key: NotifTypeKey; label: string; icon: string }[] = [
  { key: "message",    label: "Messages",     icon: "💬" },
  { key: "purchases",  label: "Purchases",    icon: "💰" },
  { key: "tip",        label: "Tips",         icon: "💸" },
  { key: "subscribed", label: "Subscribers",  icon: "⭐" },
  { key: "mentioned",  label: "Mentions",     icon: "@" },
  { key: "commented",  label: "Comments",     icon: "💭" },
  { key: "favorited",  label: "Likes",        icon: "♡" },
];

export interface NotifSettings {
  enabled: boolean;
  toast: Record<NotifTypeKey, boolean>;
  bubble: Record<NotifTypeKey, boolean>;
  osPing: boolean;
  platforms: Record<Platform, boolean>;
  sounds: Record<AlertKind, SoundPref>;
}

export type AlertKind = "sale" | "reminder";

export interface SoundPref {
  on: boolean;
  sound: AlertSoundId;
}

export const ALERT_KINDS: { key: AlertKind; label: string }[] = [
  { key: "sale", label: "New PPV sale or tip" },
  { key: "reminder", label: "Timed reminder" },
];

export const DEFAULT_NOTIF_SETTINGS: NotifSettings = {
  enabled: true,
  toast: {
    message: true,
    purchases: true,
    tip: true,
    subscribed: true,
    mentioned: false,
    commented: false,
    favorited: false,
  },
  bubble: {
    message: true,
    purchases: true,
    tip: true,
    subscribed: true,
    mentioned: false,
    commented: false,
    favorited: false,
  },
  osPing: true,
  platforms: { onlyfans: true, fansly: true },
  sounds: {
    sale: { on: false, sound: "s1" },
    reminder: { on: true, sound: "s1" },
  },
};

function readSoundPref(raw: unknown, def: SoundPref): SoundPref {
  const p = (raw && typeof raw === "object" ? raw : {}) as Partial<SoundPref>;
  return {
    on: typeof p.on === "boolean" ? p.on : def.on,
    sound: isAlertSoundId(p.sound) ? p.sound : def.sound,
  };
}

const STORAGE_KEY = "chatterly:notif-settings:v1";

const DEFAULTS_ROUND = 2;
const DEFAULT_ON = Object.fromEntries(Object.entries(DEFAULT_NOTIF_SETTINGS.toast).filter(([, on]) => on));

export function readNotifSettings(): NotifSettings {
  const parsed = readJSON<Omit<Partial<NotifSettings>, "sounds"> & {
    defaultsRound?: number;
    sounds?: Partial<NotifSettings["sounds"]> & { message?: unknown };
  }>(STORAGE_KEY);
  if (!parsed) return DEFAULT_NOTIF_SETTINGS;
  const stale = (parsed.defaultsRound ?? 1) < DEFAULTS_ROUND;
  const forced = stale ? DEFAULT_ON : {};
  return {
    enabled: stale ? true : (parsed.enabled ?? DEFAULT_NOTIF_SETTINGS.enabled),
    toast: { ...DEFAULT_NOTIF_SETTINGS.toast, ...(parsed.toast ?? {}), ...forced },
    bubble: { ...DEFAULT_NOTIF_SETTINGS.bubble, ...(parsed.bubble ?? {}) },
    osPing: parsed.osPing ?? DEFAULT_NOTIF_SETTINGS.osPing,
    platforms: { ...DEFAULT_NOTIF_SETTINGS.platforms, ...(parsed.platforms ?? {}) },
    sounds: {
      sale: readSoundPref(parsed.sounds?.sale ?? parsed.sounds?.message, DEFAULT_NOTIF_SETTINGS.sounds.sale),
      reminder: readSoundPref(parsed.sounds?.reminder, DEFAULT_NOTIF_SETTINGS.sounds.reminder),
    },
  };
}

export function writeNotifSettings(s: NotifSettings): void {
  persistJSON(STORAGE_KEY, { ...s, defaultsRound: DEFAULTS_ROUND });
  try {
    // Deferred so subscribers do not setState while the caller is still in React's render/commit.
    queueMicrotask(() => {
      try { window.dispatchEvent(new CustomEvent("chatterly:notif-settings")); } catch { }
    });
  } catch { }
}


const FILTER_KEY = "chatterly:notif-filter:v1";

export function readNotifFilterId(): string | null {
  if (typeof window === "undefined") return null;
  try { return window.localStorage.getItem(FILTER_KEY); } catch { return null; }
}

export function writeNotifFilterId(id: string): void {
  try { window.localStorage.setItem(FILTER_KEY, id); } catch { }
}

export function mapOfTypeToKey(rawType: string | undefined | null): NotifTypeKey | null {
  if (!rawType) return null;
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


export interface CachedNotification {
  id: string;
  accountId: string;
  type: string;
  typeKey: NotifTypeKey | null;
  user: {
    id?: FanId;
    name?: string;
    username?: string;
    avatar?: string;
  };
  text: string;
  replacePairs?: Record<string, string>;
  createdAt: string;
  respondedBy?: string;
}

const HISTORY_KEY = "chatterly:notif-history:v1";
const HISTORY_MAX_PER_ACCOUNT = 100;
const HISTORY_TTL_MS = 7 * 24 * 60 * 60 * 1000;

type HistoryMap = Record<string, CachedNotification[]>;

function prune(items: CachedNotification[]): CachedNotification[] {
  const cutoff = Date.now() - HISTORY_TTL_MS;
  return items
    .filter((n) => {
      const t = Date.parse(n.createdAt);
      return Number.isFinite(t) && t >= cutoff;
    })
    .sort((a, b) => Date.parse(b.createdAt) - Date.parse(a.createdAt))
    .slice(0, HISTORY_MAX_PER_ACCOUNT);
}

export function readNotifHistory(): HistoryMap {
  const parsed = readJSON<HistoryMap>(HISTORY_KEY);
  if (!parsed || typeof parsed !== "object") return {};
  const out: HistoryMap = {};
  for (const [aid, list] of Object.entries(parsed)) {
    if (Array.isArray(list)) out[aid] = prune(list);
  }
  return out;
}

function writeNotifHistory(h: HistoryMap): void {
  persistJSON(HISTORY_KEY, h);
  try {
    queueMicrotask(() => {
      try { window.dispatchEvent(new CustomEvent("chatterly:notif-history")); } catch { }
    });
  } catch { }
}

export function appendNotifHistory(n: CachedNotification): void {
  if (typeof window === "undefined") return;
  const h = readNotifHistory();
  const list = h[n.accountId] ?? [];
  if (list.some((x) => x.id === n.id)) return;
  h[n.accountId] = prune([n, ...list]);
  writeNotifHistory(h);
}

export function patchNotifHistoryUser(
  accountId: string,
  notifId: string,
  patch: Partial<CachedNotification["user"]>,
): void {
  if (typeof window === "undefined") return;
  const h = readNotifHistory();
  const list = h[accountId];
  if (!list) return;
  let dirty = false;
  for (let i = 0; i < list.length; i++) {
    if (list[i].id !== notifId) continue;
    list[i] = { ...list[i], user: { ...list[i].user, ...patch } };
    dirty = true;
    break;
  }
  if (dirty) {
    h[accountId] = list;
    writeNotifHistory(h);
  }
}

export function markNotifHistoryResponded(accountId: string, fanId: FanId, by: string): void {
  if (typeof window === "undefined") return;
  const h = readNotifHistory();
  const list = h[accountId];
  if (!list) return;
  let dirty = false;
  h[accountId] = list.map((n) => {
    if (n.typeKey !== "message" || n.respondedBy !== undefined || String(n.user.id) !== String(fanId)) return n;
    dirty = true;
    return { ...n, respondedBy: by };
  });
  if (dirty) writeNotifHistory(h);
}


export const NOTIF_ARRIVED_EVENT = "chatterly:notif-arrived";
export const NOTIF_CLEARED_EVENT = "chatterly:notif-cleared";

let lastArrivalAt = Date.now();
export function lastNotifArrival(): number {
  return lastArrivalAt;
}

export function dispatchNotifArrived(): void {
  lastArrivalAt = Date.now();
  if (typeof window === "undefined") return;
  try { window.dispatchEvent(new CustomEvent(NOTIF_ARRIVED_EVENT)); } catch { }
}

export function dispatchNotifCleared(): void {
  if (typeof window === "undefined") return;
  try { window.dispatchEvent(new CustomEvent(NOTIF_CLEARED_EVENT)); } catch { }
}
