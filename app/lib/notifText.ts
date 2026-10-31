/**
 * Notification text helpers shared by the bell (`NotificationBell`), the
 * toaster (`NotificationToaster`) and the Buys & tips rail (`MoneyRail`):
 * OF's feed request and reply shape, the money types and their list key, the
 * rendered row text, the row's age, and the toast card's sticker + label.
 * Pure: no React, no relay.
 */

import type { NotificationItem } from "@/lib/moneyRailStorage";
import type { NotifTypeKey } from "@/lib/notifSettings";

/** Rows per feed read (`notifPath`'s limit); a shorter page ends a Creator's feed. */
export const NOTIF_PAGE_SIZE = 20;

/** The feed's request for a tab: one page of rows from `offset` (the bell reads 0). */
export function notifPath(type: string | null, offset = 0): string {
  const q = new URLSearchParams({ limit: String(NOTIF_PAGE_SIZE), offset: String(offset) });
  if (type) q.set("type", type);
  return `/api/of/v2/users/notifications?${q.toString()}`;
}

/** OF's feed reply (a bare array or `{ list }`) as its rows; anything else is none. */
export function parseList(raw: unknown): NotificationItem[] {
  if (Array.isArray(raw)) return raw as NotificationItem[];
  if (raw && typeof raw === "object" && Array.isArray((raw as { list?: unknown }).list)) {
    return (raw as { list: NotificationItem[] }).list;
  }
  return [];
}

/** The money types: what the Buys & tips rail lists, what the toaster seeds
 *  into the rail's cached lists, and what deep-links with `?refresh=media`. */
export const MONEY_TYPES = ["purchases", "tip"] as const;
export type MoneyTypeKey = (typeof MONEY_TYPES)[number];

/** Tip / purchase toasts deep-link with a one-shot `?refresh=media` flag.
 *  The fan just moved money, so the popout's rehydrated persisted caches
 *  (PPV ledger, last-purchases, gallery, profile) are stale by seconds —
 *  the popout chat page reads the flag on mount and refetches the thread
 *  plus the FanDrawer's manual-↻ set. Other types link plain: no reason
 *  to burn the refetches on a like or a comment. */
export function isMoney(typeKey: NotifTypeKey | null | undefined): typeKey is MoneyTypeKey {
  return typeKey === "tip" || typeKey === "purchases";
}

/** Money rows kept: the rail shows at most this many, and a seeded money list
 *  is trimmed to it. */
export const MONEY_ROWS_CAP = 50;

/** The ["notif-list", aid, type] key a money arrival lands in, or null for a
 *  non-money one. The same key the Money rail and the bell read. */
export function moneyListKey(aid: string, typeKey: NotifTypeKey | null) {
  return isMoney(typeKey) ? ["notif-list", aid, typeKey] as const : null;
}

/** OF's notification HTML as one line of text: `replacePairs` substituted,
 *  tags replaced by `tagSep`, whitespace collapsed. The bell drops tags (""),
 *  the toaster and the rail space them (" "). */
export function renderText(raw: string, replacePairs?: Record<string, string>, tagSep = " "): string {
  let s = raw;
  if (replacePairs) {
    for (const [k, v] of Object.entries(replacePairs)) s = s.split(k).join(v);
  }
  return s.replace(/<[^>]+>/g, tagSep).replace(/\s+/g, " ").trim();
}

/** A row's age: "Ns ago" … "29d ago", then the date ("" when undated or unparseable). */
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
