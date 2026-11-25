import { useEffect, useState } from "react";
import type { QueryClient } from "@tanstack/react-query";

import { relay } from "@/lib/relay";
import { isValidFanId, type FanId } from "@/lib/fanId";
import type { NotificationUser } from "@/lib/moneyRailStorage";
import { mergeOFUserName } from "@/hooks/useOFUser";
import { toUtcIso, type ChatTarget } from "@/hooks/useInboxRealtime";
import { fanTabOf, notificationHref } from "@/lib/notificationLink";
import { osNotify, type OsNotifyPayload } from "@/lib/osNotify";
import { isPushLive, type PushPayload } from "@/lib/webPush";
import { fmtPrice } from "@/lib/format";
import { isMoney, renderText } from "@/lib/notifText";
import { BRAND_NAME } from "@/lib/brand";
import {
  appendNotifHistory,
  dispatchNotifArrived,
  mapOfTypeToKey,
  type NotifSettings,
  type NotifTypeKey,
} from "@/lib/notifSettings";

export const MAX_SEEN_IDS = 500;
// Bounded to MAX_SEEN_IDS per account; OF only re-pushes recent locale variants, so older ids can't recur.
const seenIdsByAccount = new Map<string, Set<string>>();

export function claimUnseen(aid: string, id: string): boolean {
  const seen = seenIdsByAccount.get(aid) ?? new Set<string>();
  if (seen.has(id)) return false;
  seen.add(id);
  while (seen.size > MAX_SEEN_IDS) {
    const oldest = seen.values().next().value;
    if (oldest === undefined) break;
    seen.delete(oldest);
  }
  seenIdsByAccount.set(aid, seen);
  return true;
}

export interface Toast {
  id: string;
  accountId: string | null;
  typeKey: NotifTypeKey | null;
  rawType: string;
  user: NotificationUser | null;
  text: string;
  createdAt: number;
  bubble: boolean;
  href: string | null;
  expiresAt: number;
  action?: { label: string; run: () => void };
}

export const TOAST_TTL_MS = 8_000;
export const MAX_TOASTS_VISIBLE = 6;

const toastListeners = new Set<(toasts: Toast[]) => void>();
let currentToasts: Toast[] = [];

function publish() {
  for (const fn of toastListeners) fn(currentToasts);
}

export function pushToast(t: Toast) {
  const dedupKey = `${t.accountId}:${t.id}`;
  if (currentToasts.some((x) => `${x.accountId}:${x.id}` === dedupKey)) return;
  currentToasts = [...currentToasts, t].slice(-MAX_TOASTS_VISIBLE);
  publish();
  const ttl = Math.max(0, t.expiresAt - Date.now());
  window.setTimeout(() => dismissToast(t.accountId, t.id), ttl);
}

export function dismissToast(accountId: string | null, id: string) {
  const before = currentToasts.length;
  currentToasts = currentToasts.filter((t) => !(t.accountId === accountId && t.id === id));
  if (currentToasts.length !== before) publish();
}

export function patchToastHref(accountId: string, id: string, href: string): void {
  const idx = currentToasts.findIndex((x) => x.accountId === accountId && x.id === id);
  if (idx < 0) return;
  if (currentToasts[idx].href === href) return;
  currentToasts = currentToasts.map((t, i) => (i === idx ? { ...t, href } : t));
  publish();
}

export function useToastStack(): Toast[] {
  const [toasts, setToasts] = useState<Toast[]>(currentToasts);
  useEffect(() => {
    const fn = (next: Toast[]) => setToasts(next);
    toastListeners.add(fn);
    return () => { toastListeners.delete(fn); };
  }, []);
  return toasts;
}

export function seedName(
  qc: QueryClient, accountId: string, id: FanId, u: { name?: string; username?: string; avatar?: string | null },
): void {
  mergeOFUserName(qc, accountId, id, (prev) => ({
    id,
    name: u.name,
    username: u.username,
    avatar: u.avatar ?? null,
    customNickname: prev?.customNickname ?? null,
  }));
}

const resolvedIdByUsername = new Map<string, FanId>();
export const MISS_TTL_MS = 60_000;
const missedAt = new Map<string, number>();
const inflightLookups = new Map<string, Promise<FanId | null>>();

export async function resolveUsernameId(
  accountId: string,
  username: string,
  qc: QueryClient,
): Promise<FanId | null> {
  const key = `${accountId}:${username}`;
  const cached = resolvedIdByUsername.get(key);
  if (cached) return cached;
  if (Date.now() - (missedAt.get(key) ?? -Infinity) < MISS_TTL_MS) return null;
  const inflight = inflightLookups.get(key);
  if (inflight) return inflight;

  const p = (async () => {
    try {
      const u = await relay.get<{
        id?: number | string;
        name?: string;
        username?: string;
        avatar?: string | null;
      }>(
        `/api/of/v2/users/${encodeURIComponent(username)}`,
        { accountId },
      );
      // Keep the id as sent: Number() truncated a Fansly snowflake and keyed the cache off an id nothing else looks up.
      const id = u?.id;
      if (!isValidFanId(id)) {
        missedAt.set(key, Date.now());
        return null;
      }
      resolvedIdByUsername.set(key, id);
      seedName(qc, accountId, id, u);
      return id;
    } catch {
      missedAt.set(key, Date.now());
      return null;
    } finally {
      inflightLookups.delete(key);
    }
  })();
  inflightLookups.set(key, p);
  return p;
}

export interface Arrival {
  id: string;
  accountId: string;
  typeKey: NotifTypeKey | null;
  rawType: string;
  user: NotificationUser;
  text: string;
  historyText?: string;
  replacePairs?: Record<string, string>;
  createdMs: number;
  href: string | null;
}

export function deliverDecision(settings: NotifSettings, n: Arrival, now = Date.now()): Toast | null {
  if (!settings.enabled || (n.typeKey && !settings.toast[n.typeKey])) return null;
  return {
    id: n.id,
    accountId: n.accountId,
    typeKey: n.typeKey,
    rawType: n.rawType,
    user: n.user,
    text: n.text,
    createdAt: n.createdMs,
    bubble: n.typeKey ? !!settings.bubble[n.typeKey] : false,
    href: n.href,
    expiresAt: now + TOAST_TTL_MS,
  };
}

// History is mirrored ALWAYS, even for muted arrivals; muting popups must not blind the bell and money rail. A push-notice never mirrors (thin copy would dedupe away the full row).
export function mirrorNotification(n: Arrival): void {
  appendNotifHistory({
    id: n.id,
    accountId: n.accountId,
    type: n.rawType,
    typeKey: n.typeKey,
    user: {
      id: n.user.id,
      name: n.user.name,
      username: n.user.username,
      avatar: n.user.avatar,
    },
    text: n.historyText ?? n.text,
    replacePairs: n.replacePairs,
    createdAt: new Date(n.createdMs).toISOString(),
  });
}

export function pingNotification(settings: NotifSettings, n: Arrival): void {
  const toast = deliverDecision(settings, n);
  if (!toast) return;

  dispatchNotifArrived();
  pushToast(toast);

  // OS ping only while unfocused; with a live Web Push subscription the relay/service worker pings, so the page never does.
  const focused = typeof document !== "undefined" ? document.hasFocus() : true;
  if (settings.osPing && !focused && !isPushLive()) void osNotify(noticeOf(n));
}

export function noticeOf(n: Arrival): OsNotifyPayload {
  return {
    id: `${n.accountId}:${n.id}`,
    title: n.user.name || n.user.username || BRAND_NAME,
    body: n.text || n.rawType || "New activity",
    href: n.href,
  };
}

export function extractAvatarFromHtml(raw: string | undefined | null): string | null {
  if (!raw || typeof raw !== "string") return null;
  const m = raw.match(/<img[^>]*\bsrc=["']([^"']+)["']/i);
  return m ? m[1] : null;
}

// OF's toast `user` is the recipient (the model), not the actor; the actor's avatar is the first <img> in the HTML `text`.
export function extractUsernameFromHtml(raw: string | undefined | null): string | null {
  if (!raw || typeof raw !== "string") return null;
  const m = raw.match(/href=["']https?:\/\/(?:www\.)?onlyfans\.com\/([A-Za-z0-9._-]+)["']/i);
  return m ? m[1] : null;
}

export function toastArrival(aid: string, raw: unknown, now = Date.now()): Arrival | null {
  if (!raw || typeof raw !== "object") return null;
  const t = raw as Record<string, unknown>;
  if (t.id == null) return null;
  const id = String(t.id);

  const typeKey = mapOfTypeToKey(typeof t.type === "string" ? t.type : null);

  const rawText = (typeof t.text === "string" ? t.text : "")
    || (typeof t.description === "string" ? t.description : "")
    || (typeof t.title === "string" ? t.title : "");
  const data = (t.data && typeof t.data === "object")
    ? (t.data as { relatedUser?: Record<string, unknown>; replacements?: Record<string, string> })
    : undefined;
  const relatedUser = data?.relatedUser;
  const repl = data?.replacements;
  const fromReplId = repl?.["{RELATED_USER_ID}"];
  const fromReplName = repl?.["{RELATED_USER_NAME}"];
  const fromReplLogin = repl?.["{RELATED_USER_LOGIN}"];
  const fromReplAvatar = repl?.["{RELATED_USER_AVATAR}"];

  const fromUser = (t.fromUser as NotificationUser | undefined);
  const recipientUser = (t.user as NotificationUser | undefined);
  const htmlAvatar = extractAvatarFromHtml(rawText);
  const htmlUsername = extractUsernameFromHtml(rawText);

  const relatedAvatarObj = relatedUser?.avatarThumbs as
    | { c50?: string; c144?: string }
    | undefined;
  const relatedAvatar =
    relatedAvatarObj?.c144 ||
    relatedAvatarObj?.c50 ||
    (typeof relatedUser?.avatar === "string" ? relatedUser.avatar : undefined);

  const relatedIdRaw = relatedUser?.id ?? (fromReplId ? Number(fromReplId) : undefined);
  const relatedId =
    typeof relatedIdRaw === "number" && Number.isFinite(relatedIdRaw)
      ? relatedIdRaw
      : undefined;

  const user: NotificationUser = {
    id: relatedId ?? fromUser?.id,
    name:
      (typeof relatedUser?.name === "string" ? relatedUser.name : undefined) ||
      fromReplName ||
      fromUser?.name ||
      recipientUser?.name,
    username:
      (typeof relatedUser?.username === "string" ? relatedUser.username : undefined) ||
      fromReplLogin ||
      fromUser?.username ||
      htmlUsername ||
      recipientUser?.username,
    avatar:
      relatedAvatar ||
      fromReplAvatar ||
      fromUser?.avatar ||
      htmlAvatar ||
      undefined,
  };

  const replacePairs = repl ?? (t.replacePairs as Record<string, string> | undefined);
  return {
    id,
    accountId: aid,
    typeKey,
    rawType: typeof t.type === "string" ? t.type : "",
    user,
    text: renderText(rawText, replacePairs),
    historyText: rawText,
    replacePairs,
    createdMs: typeof t.createdAt === "string" ? Date.parse(t.createdAt) || now : now,
    href: notificationHref(aid, user, { refresh: isMoney(typeKey) }),
  };
}

export function dmArrival(target: ChatTarget, now = Date.now()): Arrival {
  const { accountId: aid, fanId, msg, fromId } = target;
  const fromUser = (msg.fromUser ?? {}) as NotificationUser;
  const user: NotificationUser = {
    id: fromId,
    name: fromUser.name || fromUser.username,
    username: fromUser.username,
    avatar: fromUser.avatar,
  };
  const rawText = (typeof msg.text === "string" ? msg.text : "").trim();
  const tip = !!msg.isTip;
  const cents = tip ? Math.round((Number(msg.tipAmount) || Number(msg.price) || 0) * 100) : 0;
  const text = tip
    ? (cents > 0 ? `Tipped you ${fmtPrice(cents)}` : "Sent you a tip")
    : renderText(rawText) || ((msg.mediaCount ?? 0) > 0 ? "Sent you media" : "Sent you a message");
  return {
    id: "m" + String(msg.id),
    accountId: aid,
    typeKey: tip ? "tip" : "message",
    rawType: tip ? "tip" : "message",
    user,
    text,
    historyText: tip ? text : rawText || text,
    createdMs: msg.createdAt ? Date.parse(toUtcIso(msg.createdAt)) || now : now,
    href: notificationHref(aid, { ...user, id: fanId }, { refresh: tip }),
  };
}

export interface PurchaseNotified {
  notif_id: string;
  fan_id: FanId;
  amount_cents?: number;
  created_at?: string | null;
  name?: string | null;
}

// The id is OF's own, unprefixed: it MUST equal the feed's id for this purchase or rail/bell dedupe fails.
export function purchaseArrival(
  aid: string, p: PurchaseNotified, cached: NotificationUser | null | undefined, now = Date.now(),
): Arrival {
  const user: NotificationUser = {
    id: p.fan_id,
    name: p.name || cached?.name,
    username: cached?.username,
    avatar: cached?.avatar,
  };
  const cents = Number(p.amount_cents);
  return {
    id: String(p.notif_id),
    accountId: aid,
    typeKey: "purchases",
    rawType: "purchases",
    user,
    text: Number.isFinite(cents) && cents > 0
      ? `Unlocked your PPV — ${fmtPrice(cents)}`
      : "Unlocked your PPV",
    createdMs: p.created_at ? Date.parse(toUtcIso(p.created_at)) || now : now,
    href: notificationHref(aid, user, { refresh: true }),
  };
}

export function pushArrival(raw: unknown, now = Date.now()): Arrival | null {
  if (!raw || typeof raw !== "object") return null;
  const p = raw as PushPayload;
  const aid = p.account_id == null ? "" : String(p.account_id);
  const tag = typeof p.tag === "string" ? p.tag : "";
  if (!aid || !tag.startsWith(`${aid}:`) || tag.length <= aid.length + 1) return null;
  const href = typeof p.href === "string" && p.href.startsWith("/") && !p.href.startsWith("//") ? p.href : null;
  const rawType = typeof p.type === "string" ? p.type : "";
  const title = typeof p.title === "string" && p.title !== BRAND_NAME ? p.title : undefined;
  return {
    id: tag.slice(aid.length + 1),
    accountId: aid,
    typeKey: mapOfTypeToKey(rawType),
    rawType,
    user: { id: (href && fanTabOf(href)?.fanId) || undefined, name: title },
    text: typeof p.body === "string" ? p.body : "",
    createdMs: now,
    href,
  };
}

export function deliverPushNotice(
  raw: unknown, settingsFor: (aid: string) => NotifSettings | null,
): boolean {
  const a = pushArrival(raw);
  const settings = a && settingsFor(a.accountId);
  if (!a || !settings) return false;
  if (claimUnseen(a.accountId, a.id)) pingNotification(settings, a);
  return true;
}
