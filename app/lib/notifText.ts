import type { NotificationItem } from "@/lib/moneyRailStorage";
import type { NotifTypeKey } from "@/lib/notifSettings";

export const NOTIF_PAGE_SIZE = 20;

export function notifPath(type: string | null, offset = 0): string {
  const q = new URLSearchParams({ limit: String(NOTIF_PAGE_SIZE), offset: String(offset) });
  if (type) q.set("type", type);
  return `/api/of/v2/users/notifications?${q.toString()}`;
}

export function parseList(raw: unknown): NotificationItem[] {
  if (Array.isArray(raw)) return raw as NotificationItem[];
  if (raw && typeof raw === "object" && Array.isArray((raw as { list?: unknown }).list)) {
    return (raw as { list: NotificationItem[] }).list;
  }
  return [];
}

export const MONEY_TYPES = ["purchases", "tip"] as const;
export type MoneyTypeKey = (typeof MONEY_TYPES)[number];

export function isMoney(typeKey: NotifTypeKey | null | undefined): typeKey is MoneyTypeKey {
  return typeKey === "tip" || typeKey === "purchases";
}

export const MONEY_ROWS_CAP = 50;

export function moneyListKey(aid: string, typeKey: NotifTypeKey | null) {
  return isMoney(typeKey) ? ["notif-list", aid, typeKey] as const : null;
}

export function renderText(raw: string, replacePairs?: Record<string, string>, tagSep = " "): string {
  let s = raw;
  if (replacePairs) {
    for (const [k, v] of Object.entries(replacePairs)) s = s.split(k).join(v);
  }
  return s.replace(/<[^>]+>/g, tagSep).replace(/\s+/g, " ").trim();
}

export function fmtTime(iso?: string): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const ms = Date.now() - d.getTime();
  const sec = Math.floor(ms / 1000);
  if (sec < 60) return `${sec}s ago`;
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min}m ago`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr}h ago`;
  const day = Math.floor(hr / 24);
  if (day < 30) return `${day}d ago`;
  return d.toLocaleDateString([], { month: "short", day: "numeric" });
}

export function stickerFor(k: NotifTypeKey | null): string {
  switch (k) {
    case "message":    return "💬";
    case "purchases":  return "💰";
    case "tip":        return "💸";
    case "subscribed": return "⭐";
    case "mentioned":  return "@";
    case "commented":  return "💭";
    case "favorited":  return "♡";
    default:           return "🔔";
  }
}

export function labelFor(k: NotifTypeKey | null, raw: string): string {
  switch (k) {
    case "message":    return "New message";
    case "purchases":  return "Purchase";
    case "tip":        return "Tip received";
    case "subscribed": return "New subscriber";
    case "mentioned":  return "Mentioned you";
    case "commented":  return "Commented";
    case "favorited":  return "Liked";
    default:           return raw || "Notification";
  }
}
