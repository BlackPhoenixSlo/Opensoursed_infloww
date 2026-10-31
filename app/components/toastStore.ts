/**
 * The toaster's toast stack and arrival handling (`NotificationToaster`,
 * `useNotificationDelta`): the per-account seen-id sets every SSE lane claims
 * an arrival in, the toast stack, the username → fan-id lookups, the pure
 * parsers that turn each lane's payload into one `Arrival` (`toastArrival`,
 * `dmArrival`, `purchaseArrival`), the pure gate `deliverDecision`, and
 * `deliverNotification`, which mirrors history and pushes the pings. The
 * state is module-level so every mounted listener and a StrictMode
 * double-mount share one copy.
 */

import { useEffect, useState } from "react";
import type { QueryClient } from "@tanstack/react-query";

import { relay } from "@/lib/relay";
import { isValidFanId, type FanId } from "@/lib/fanId";
import type { NotificationUser } from "@/lib/moneyRailStorage";
import { mergeOFUserName } from "@/hooks/useOFUser";
import { toUtcIso, type ChatTarget } from "@/hooks/useInboxRealtime";
import { notificationHref } from "@/lib/notificationLink";
import { osNotify } from "@/lib/osNotify";
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

// One entry per accountId. Each set is bounded to the last MAX_SEEN_IDS
// arrivals so it can't grow unbounded for the life of the tab — older ids
// can't recur as dupes anyway (OF only re-pushes recent locale variants).
export const MAX_SEEN_IDS = 500;
const seenIdsByAccount = new Map<string, Set<string>>();

// Atomically claim an arrival id for an account: false = already seen (the
// caller drops the event), true = now marked seen. THE dedup step every lane
// (toasts / DM / purchase) runs before delivering anything. The insertion-
// ordered Set evicts its oldest ids past MAX_SEEN_IDS.
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
  /** The Creator the card is about; null for the app's own cards (`lib/notices`). */
  accountId: string | null;
  typeKey: NotifTypeKey | null;
  rawType: string;
  /** Who the card is from; null for a card from no OF user (the clock's). */
  user: NotificationUser | null;
  text: string;
  createdAt: number;
  bubble: boolean;
  href: string | null;
  expiresAt: number;
  /** A button on the card (the clock-in reminder's "Clock in"); dismisses the toast too. */
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

/** A notification's Fan into his name key, keeping a team nickname the chat
 *  list's enrichment stitched there (a notification never carries one). */
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

// Username → user-id cache. SSE-pushed likes carry only the @username;
// we resolve eagerly so the toast's click target is canonical and the
// chat popout's header renders instantly.
const resolvedIdByUsername = new Map<string, FanId>();
const inflightLookups = new Map<string, Promise<FanId | null>>();

export async function resolveUsernameId(
  accountId: string,
  username: string,
  qc: QueryClient,
): Promise<FanId | null> {
  const key = `${accountId}:${username}`;
  const cached = resolvedIdByUsername.get(key);
  if (cached) return cached;
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
      // Keep the id as sent — `Number(...)` + `as number` truncated a Fansly
      // snowflake and then seeded ["of-user", accountId, id] with it, so the
      // cache entry was keyed off an id nothing else in the app looks up.
      const id = u?.id;
      if (!isValidFanId(id)) return null;
      resolvedIdByUsername.set(key, id);
      seedName(qc, accountId, id, u);
      return id;
    } catch {
      return null;
    } finally {
      inflightLookups.delete(key);
    }
  })();
  inflightLookups.set(key, p);
  return p;
}

/** One arrival, as every SSE lane hands it to `deliverNotification`. */
export interface Arrival {
  id: string;
  accountId: string;
  typeKey: NotifTypeKey | null;
  /** OF's own type string, kept verbatim for the history row. */
  rawType: string;
  user: NotificationUser;
  /** Rendered, for the toast. */
  text: string;
  /** Stored, for the history row — OF's lanes keep the raw HTML so the
   *  dropdown can re-render it. Defaults to `text`. */
  historyText?: string;
  replacePairs?: Record<string, string>;
  createdMs: number;
  href: string | null;
}

/** The pings an arrival earns: the toast card to push (with the badge bump
 *  and, unfocused, the OS ping that go with it), or null for a muted one —
 *  master off, or its type's toast toggled off. A muted arrival still has its
 *  history mirrored; that is `deliverNotification`'s, not this gate's. */
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

/** One arrival, delivered. Every SSE lane — OF's `toasts` feed, inbound DMs,
 *  PPV unlocks — differs only in how it parses its envelope; from here on the
 *  policy is identical, so it lives here once instead of three times.
 *
 *  The contract that must not drift: history is mirrored ALWAYS, pings are
 *  GATED. A muted arrival (master off, or its type toggled off) still reaches
 *  the bell dropdown and the money rail — muting popups must not make those go
 *  deaf — but produces no badge bump, no popup and no OS notification.
 */
export function deliverNotification(settings: NotifSettings, n: Arrival): void {
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

  const toast = deliverDecision(settings, n);
  if (!toast) return;

  dispatchNotifArrived();
  pushToast(toast);

  // OS ping only while this window is unfocused (a focused window shows the
  // toast). The desktop app shows it natively and dedupes popouts by id; a
  // browser needs the web permission already granted (lib/osNotify).
  const focused = typeof document !== "undefined" ? document.hasFocus() : true;
  if (settings.osPing && !focused) {
    void osNotify({
      id: `${n.accountId}:${n.id}`,
      title: n.user.name || n.user.username || BRAND_NAME,
      body: n.text || n.rawType || "New activity",
      href: n.href,
    });
  }
}

/**
 * OF's toast payload's `user` field is the recipient (the model whose
 * post was liked), not the actor (the fan). The actor's avatar lives
 * inside the HTML `text` blob as the first <img src="…"> tag.
 */
export function extractAvatarFromHtml(raw: string | undefined | null): string | null {
  if (!raw || typeof raw !== "string") return null;
  const m = raw.match(/<img[^>]*\bsrc=["']([^"']+)["']/i);
  return m ? m[1] : null;
}

export function extractUsernameFromHtml(raw: string | undefined | null): string | null {
  if (!raw || typeof raw !== "string") return null;
  const m = raw.match(/href=["']https?:\/\/(?:www\.)?onlyfans\.com\/([A-Za-z0-9._-]+)["']/i);
  return m ? m[1] : null;
}

/** One entry of OF's `toasts` SSE array as an `Arrival`, or null for one with
 *  no id (nothing to dedupe on). The actor (fan) is, field by field:
 *  `data.relatedUser`, then OF's `data.replacements` ({RELATED_USER_*}), then
 *  `fromUser`, then the HTML text (username, avatar), then — name and
 *  username only — the recipient `user`. Only `relatedUser` / the
 *  replacements give an id; with neither, `fromUser`'s. */
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

/** A fan's inbound DM (`api2_chat_message`, resolved) as an `Arrival`. The id
 *  is namespaced "m" so a message can't collide with an OF notification id in
 *  the shared per-account seen set / toast dedup. */
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
  const text =
    renderText(rawText) ||
    ((msg.mediaCount ?? 0) > 0 ? "Sent you media" : "Sent you a message");
  return {
    id: "m" + String(msg.id),
    accountId: aid,
    typeKey: "message",
    rawType: "message",
    user,
    text,
    historyText: rawText || text,
    createdMs: msg.createdAt ? Date.parse(toUtcIso(msg.createdAt)) || now : now,
    href: notificationHref(aid, { ...user, id: fanId }),
  };
}

/** The relay's `purchase_notified` payload, once its id and fan are known good. */
export interface PurchaseNotified {
  notif_id: string;
  fan_id: FanId;
  amount_cents?: number;
  created_at?: string | null;
  name?: string | null;
}

/** A PPV unlock as an `Arrival`. The id is OF's own, unprefixed — it MUST
 *  equal the id the feed will carry for this purchase, or the rail's and the
 *  bell's dedupe fails. The payload names the payer; `cached` (his ["of-user"]
 *  entry) fills in the rest. */
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
    // OF stamps these with an explicit offset ("…+00:00"); toUtcIso passes
    // a zoned timestamp through untouched.
    createdMs: p.created_at ? Date.parse(toUtcIso(p.created_at)) || now : now,
    // Same one-shot refresh flag the money toasts and rail rows carry — the
    // fan just moved money, so the popout's caches are stale.
    href: notificationHref(aid, user, { refresh: true }),
  };
}
