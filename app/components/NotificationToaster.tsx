"use client";

/**
 * NotificationToaster — listens to OF's SSE `toasts` event, renders a
 * transient toast top-right, and bumps the bell badge by 1 per arrival.
 *
 * Badge ownership lives in NotificationBell (tab-local counter). This
 * component only fires `chatterly:notif-arrived` events; the bell
 * subscribes and increments. No polling, no count diffing, no
 * cross-tab baseline — every tab starts at 0 and counts forward.
 *
 * We still mirror each arrival into localStorage via appendNotifHistory
 * so the bell dropdown can display likes / mentions that OF's own
 * /notifications endpoint drops.
 *
 * Two non-OF sources share the stack. The clock-in reminder
 * (docs/spec/phase-02-shifts-time-tracking.md, Clock-in reminder): for a
 * Chatter session it polls `GET /admin/shifts/me` every minute and shows
 * "Your shift on <Creator> has started." once per (shift_id,
 * occurrence_start), keyed in localStorage, with a "Clock in" action that
 * clocks in at once through `useClock` (or opens `ClockDialog` for a chatter
 * in two Agencies, who names a Creator). And the app's one-line notices
 * (`lib/notices`), such as the clock's "Clock in successful" and a chatter's
 * access changes (`useAccessChangeNotices`). In-app only: no
 * email, push or OS notification.
 */

import { useEffect, useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import type { QueryClient } from "@tanstack/react-query";

import ClockDialog from "@/components/shifts/ClockDialog";
import { useOptionalChatter } from "@/contexts/ChatterContext";
import { useScope } from "@/contexts/ScopeContext";
import { useOptionalUser } from "@/contexts/UserContext";
import { useActiveAccounts } from "@/hooks/useAccounts";
import { useAccessChangeNotices } from "@/hooks/useAccessChangeNotices";
import { accountPlatform } from "@/lib/platform";
import { useDeferredMount } from "@/hooks/useDeferredMount";
import { useNotificationSettings } from "@/hooks/useNotificationSettings";
import { chatTabName, openChatTab } from "@/lib/chatPopout";
import { eventBus, type EventEnvelope } from "@/lib/events";
import { resolveChatTarget, toUtcIso, type ChatTarget } from "@/hooks/useInboxRealtime";
import { relay } from "@/lib/relay";
import { proxyImage } from "@/lib/mediaUrl";
import { isValidFanId, type FanId } from "@/lib/fanId";
import { onNotice } from "@/lib/notices";
import { hasShellNotify, osNotify } from "@/lib/osNotify";
import { playAlertOnce } from "@/lib/alertSounds";
import { useClock, useMyShifts } from "@/lib/shifts";
import type { NotificationUser } from "@/lib/moneyRailStorage";
import { mergeOFUserName, ofUserNameKey } from "@/hooks/useOFUser";
import { fmtPrice } from "@/lib/format";
import {
  appendNotifHistory,
  dispatchNotifArrived,
  dispatchNotifCleared,
  mapOfTypeToKey,
  markNotifHistoryResponded,
  patchNotifHistoryUser,
  type NotifSettings,
  type NotifTypeKey,
} from "@/lib/notifSettings";

// One entry per accountId. Lives outside the component so HMR /
// StrictMode double-mounts don't lose seen-id state. Each set is
// bounded to the last MAX_SEEN_IDS arrivals so it can't grow
// unbounded for the life of the tab — older ids can't recur as
// dupes anyway (OF only re-pushes recent locale variants).
const MAX_SEEN_IDS = 500;
const seenIdsByAccount = new Map<string, Set<string>>();

// Atomically claim an arrival id for an account: false = already seen (the
// caller drops the event), true = now marked seen. THE dedup step every lane
// (toasts / DM / purchase) runs before delivering anything. The insertion-
// ordered Set evicts its oldest ids past MAX_SEEN_IDS.
function claimUnseen(aid: string, id: string): boolean {
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

interface NotificationItem {
  id?: number | string;
  type?: string;
  text?: string;
  description?: string;
  createdAt?: string;
  user?: NotificationUser;
  fromUser?: NotificationUser;
  replacePairs?: Record<string, string>;
}

interface Toast {
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

const TOAST_TTL_MS = 8_000;
const MAX_TOASTS_VISIBLE = 6;

const toastListeners = new Set<(toasts: Toast[]) => void>();
let currentToasts: Toast[] = [];

function publish() {
  for (const fn of toastListeners) fn(currentToasts);
}

function pushToast(t: Toast) {
  const dedupKey = `${t.accountId}:${t.id}`;
  if (currentToasts.some((x) => `${x.accountId}:${x.id}` === dedupKey)) return;
  currentToasts = [...currentToasts, t].slice(-MAX_TOASTS_VISIBLE);
  publish();
  const ttl = Math.max(0, t.expiresAt - Date.now());
  window.setTimeout(() => dismissToast(t.accountId, t.id), ttl);
}

function dismissToast(accountId: string | null, id: string) {
  const before = currentToasts.length;
  currentToasts = currentToasts.filter((t) => !(t.accountId === accountId && t.id === id));
  if (currentToasts.length !== before) publish();
}

function patchToastHref(accountId: string, id: string, href: string): void {
  const idx = currentToasts.findIndex((x) => x.accountId === accountId && x.id === id);
  if (idx < 0) return;
  if (currentToasts[idx].href === href) return;
  currentToasts = currentToasts.map((t, i) => (i === idx ? { ...t, href } : t));
  publish();
}

/** A notification's Fan into his name key, keeping a team nickname the chat
 *  list's enrichment stitched there (a notification never carries one). */
function seedName(
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

async function resolveUsernameId(
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

function useToastStack(): Toast[] {
  const [toasts, setToasts] = useState<Toast[]>(currentToasts);
  useEffect(() => {
    const fn = (next: Toast[]) => setToasts(next);
    toastListeners.add(fn);
    return () => { toastListeners.delete(fn); };
  }, []);
  return toasts;
}

/**
 * OF's toast payload's `user` field is the recipient (the model whose
 * post was liked), not the actor (the fan). The actor's avatar lives
 * inside the HTML `text` blob as the first <img src="…"> tag.
 */
function extractAvatarFromHtml(raw: string | undefined | null): string | null {
  if (!raw || typeof raw !== "string") return null;
  const m = raw.match(/<img[^>]*\bsrc=["']([^"']+)["']/i);
  return m ? m[1] : null;
}

function extractUsernameFromHtml(raw: string | undefined | null): string | null {
  if (!raw || typeof raw !== "string") return null;
  const m = raw.match(/href=["']https?:\/\/(?:www\.)?onlyfans\.com\/([A-Za-z0-9._-]+)["']/i);
  return m ? m[1] : null;
}

function renderText(raw: string, replacePairs?: Record<string, string>): string {
  let s = raw;
  if (replacePairs) {
    for (const [k, v] of Object.entries(replacePairs)) s = s.split(k).join(v);
  }
  return s.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim();
}

function hrefFor(n: NotificationItem, accountId: string): string | null {
  const u = n.user || n.fromUser || {};
  if (u.id) return `/messages-pro/${encodeURIComponent(accountId)}/${u.id}`;
  if (u.username) {
    return `/messages-pro/${encodeURIComponent(accountId)}/u/${encodeURIComponent(u.username)}`;
  }
  return null;
}

/** Tip / purchase toasts deep-link with a one-shot `?refresh=media` flag.
 *  The fan just moved money, so the popout's rehydrated persisted caches
 *  (PPV ledger, last-purchases, gallery, profile) are stale by seconds —
 *  the popout chat page reads the flag on mount and refetches the thread
 *  plus the FanDrawer's manual-↻ set. Other types link plain: no reason
 *  to burn the refetches on a like or a comment. */
function withRefreshFlag(href: string, typeKey: NotifTypeKey | null): string {
  if (typeKey !== "tip" && typeKey !== "purchases") return href;
  return `${href}${href.includes("?") ? "&" : "?"}refresh=media`;
}

/** One arrival, as every SSE lane hands it to `deliverNotification`. */
interface Arrival {
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

/** Rows the seeded money list keeps — the rail never shows more (MAX_ROWS). */
const MONEY_LIST_CAP = 50;

/** The ["notif-list", aid, type] key a money arrival lands in, or null for a
 *  non-money one. The same key the Money rail and the bell read. */
function moneyListKey(aid: string, typeKey: NotifTypeKey | null) {
  return typeKey === "tip" || typeKey === "purchases" ? ["notif-list", aid, typeKey] as const : null;
}

/**
 * A money arrival goes straight into the rail's cached OF list — no OF
 * round-trip. The SSE payload IS the row OF's feed will list (same id; the
 * rail and bell dedupe on it), so re-reading /notifications on every arrival
 * only paid 2 OF calls per model per event for nothing. Once the real feed
 * is next read (mount, tab return, the slow safety poll, `resync`) its row
 * replaces this one.
 *
 * Seeded into the cache rather than left to the history mirror alone: the
 * mirror holds 100 rows per Creator across ALL types, so on a busy Creator
 * DMs push a sale out of it within the hour. A list that was never fetched
 * is left alone — its first fetch brings the row, the mirror shows it meanwhile.
 */
function seedMoneyList(qc: QueryClient, n: Arrival): void {
  const key = moneyListKey(n.accountId, n.typeKey);
  const prev = key && qc.getQueryData<NotificationItem[]>(key);
  if (!key || !prev || prev.some((r) => String(r.id) === n.id)) return;
  const row: NotificationItem = {
    id: n.id,
    type: n.rawType,
    text: n.historyText ?? n.text,
    createdAt: new Date(n.createdMs).toISOString(),
    user: n.user,
    replacePairs: n.replacePairs,
  };
  qc.setQueryData(key, [row, ...prev].slice(0, MONEY_LIST_CAP));
}

/** The seeded row's late-resolved fan id (OF's toasts can name a fan only by
 *  @username) — the cached row outranks the history row it would patch. */
function patchMoneyListUser(
  qc: QueryClient, aid: string, typeKey: NotifTypeKey | null, id: string, patch: Partial<NotificationUser>,
): void {
  const key = moneyListKey(aid, typeKey);
  const prev = key && qc.getQueryData<NotificationItem[]>(key);
  const i = prev ? prev.findIndex((r) => String(r.id) === id) : -1;
  if (!key || !prev || i < 0) return;
  const next = prev.slice();
  next[i] = { ...next[i], user: { ...next[i].user, ...patch } };
  qc.setQueryData(key, next);
}

/** One arrival, delivered. Every SSE lane below — OF's `toasts` feed, inbound
 *  DMs, PPV unlocks — differs only in how it parses its envelope; from here on
 *  the policy is identical, so it lives here once instead of three times.
 *
 *  The contract that must not drift: history is mirrored ALWAYS, pings are
 *  GATED. A muted arrival (master off, or its type toggled off) still reaches
 *  the bell dropdown and the money rail — muting popups must not make those go
 *  deaf — but produces no badge bump, no popup and no OS notification.
 */
function deliverNotification(settings: NotifSettings, n: Arrival): void {
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

  if (!settings.enabled || (n.typeKey && !settings.toast[n.typeKey])) return;

  dispatchNotifArrived();
  pushToast({
    id: n.id,
    accountId: n.accountId,
    typeKey: n.typeKey,
    rawType: n.rawType,
    user: n.user,
    text: n.text,
    createdAt: n.createdMs,
    bubble: n.typeKey ? !!settings.bubble[n.typeKey] : false,
    href: n.href,
    expiresAt: Date.now() + TOAST_TTL_MS,
  });

  // OS ping only while this window is unfocused (a focused window shows the
  // toast). The desktop app shows it natively and dedupes popouts by id; a
  // browser needs the web permission already granted (lib/osNotify).
  const focused = typeof document !== "undefined" ? document.hasFocus() : true;
  if (settings.osPing && !focused) {
    void osNotify({
      id: `${n.accountId}:${n.id}`,
      title: n.user.name || n.user.username || "Inflowwww",
      body: n.text || n.rawType || "New activity",
      href: n.href,
    });
  }
}

function NotificationDeltaPoller() {
  const { accountId } = useScope();
  const active = useActiveAccounts();
  const { settings } = useNotificationSettings();
  const ready = useDeferredMount(1_500);
  const qc = useQueryClient();

  const targetIds = useMemo<string[]>(
    () => (accountId ? [accountId] : active.map((a) => a.id)),
    [accountId, active],
  );
  // An account on a platform switched off pings nothing (as the master
  // switch off), its history still mirrored. One not in `active` has no
  // platform known: OnlyFans, as accountPlatform reads a missing one.
  const settingsFor = useMemo(() => {
    const platformOf = new Map(active.map((a) => [a.id, accountPlatform(a)]));
    const off = { ...settings, enabled: false };
    return (aid: string) => (settings.platforms[platformOf.get(aid) ?? "onlyfans"] ? settings : off);
  }, [active, settings]);

  // SSE: direct "toasts" event — OF pushes the full notification payload
  // here within ~1s of the underlying action. This is our only source of
  // truth now; no polling, no count-diff backstop.
  //
  // The listener runs even with the master "Enabled" toggle OFF: the history
  // mirror feeds the bell dropdown AND the Buys & tips rail, and muting
  // popups must not make those go deaf. `enabled` gates the pings below
  // (toast + badge + OS), not the pipeline.
  useEffect(() => {
    if (!ready) return;
    const off = eventBus.on("toasts", (env: EventEnvelope) => {
      const aid = env.__account_id;
      if (!aid || !targetIds.includes(aid)) return;
      const arr = (env as { toasts?: unknown }).toasts;
      if (!Array.isArray(arr)) return;

      for (const raw of arr) {
        if (!raw || typeof raw !== "object") continue;
        const t = raw as Record<string, unknown>;
        const idVal = t.id;
        if (idVal == null) continue;
        const id = String(idVal);

        // Dedup on the notification ID. OF's locale variants share the
        // same id so we only count each arrival once.
        if (!claimUnseen(aid, id)) continue;

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

        if (user.id != null) {
          seedName(qc, aid, user.id, user);
        }
        const text = renderText(rawText, repl ?? (t.replacePairs as Record<string, string> | undefined));
        const createdMs = typeof t.createdAt === "string"
          ? Date.parse(t.createdAt) || Date.now()
          : Date.now();

        const baseHref = hrefFor({ user } as NotificationItem, aid);
        // History always, pings gated — the money rail and the feed dropdown
        // must still list a muted arrival (incl. likes).
        const arrival: Arrival = {
          id,
          accountId: aid,
          typeKey,
          rawType: typeof t.type === "string" ? t.type : "",
          user,
          text,
          historyText: rawText,
          replacePairs: repl ?? (t.replacePairs as Record<string, string> | undefined),
          createdMs,
          href: baseHref ? withRefreshFlag(baseHref, typeKey) : null,
        };
        deliverNotification(settingsFor(aid), arrival);
        // No notif-list refetch, muted or not: a tip/purchase is seeded into
        // the rail's list from this payload; anything else reaches the bell
        // through the history mirror it already merges.
        seedMoneyList(qc, arrival);

        // Resolve username → id in the background whether or not it pinged;
        // the history entry gets patched either way. Only OF's own toasts
        // arrive without a user id, which is why this lane alone needs it.
        if (!user.id && user.username) {
          const uname = user.username;
          resolveUsernameId(aid, uname, qc).then((resolvedId) => {
            if (resolvedId == null) return;
            const canonical = withRefreshFlag(
              `/messages-pro/${encodeURIComponent(aid)}/${resolvedId}`,
              typeKey,
            );
            patchToastHref(aid, id, canonical);
            patchNotifHistoryUser(aid, id, { id: resolvedId });
            patchMoneyListUser(qc, aid, typeKey, id, { id: resolvedId });
          }).catch(() => { /* ignore */ });
        }
      }
    });
    return off;
  }, [qc, settingsFor, ready, targetIds]);

  // SSE: inbound chat messages — OF's native `toasts` feed does NOT carry
  // DMs (those arrive on `api2_chat_message`, consumed by useInboxRealtime
  // for the chat cache), so without this a new webhook message never
  // produced a toast/bubble. Mirror inbound messages into the same toast
  // pipeline: shown when the per-type "message" Toast toggle is on, and
  // rendered as an accent-ring "bubble" when `settings.bubble.message` is
  // on. Outbound (our own sends / AI replies / mass / funnel) never ping.
  useEffect(() => {
    // Same as the `toasts` handler: the mirror keeps running with the master
    // toggle off; only the pings below are gated.
    if (!ready) return;
    const off = eventBus.on("api2_chat_message", (env: EventEnvelope) => {
      const target: ChatTarget | null = resolveChatTarget(
        env as unknown as Parameters<typeof resolveChatTarget>[0],
      );
      if (!target) return;
      const { accountId: aid, fanId, isOutbound, msg, fromId } = target;
      if (isOutbound) return;                 // only a fan's inbound DM pings
      if (!targetIds.includes(aid)) return;   // in-scope accounts only

      // Namespace the id with "m" so a message can't collide with an OF
      // notification id in the shared per-account seen set / toast dedup.
      const id = "m" + String(msg.id);
      if (!claimUnseen(aid, id)) return;

      const fromUser = (msg.fromUser ?? {}) as NotificationUser;
      const user: NotificationUser = {
        id: fromId,
        name: fromUser.name || fromUser.username,
        username: fromUser.username,
        avatar: fromUser.avatar,
      };
      if (user.id != null) {
        seedName(qc, aid, user.id, user);
      }

      const rawText = (typeof msg.text === "string" ? msg.text : "").trim();
      const text =
        renderText(rawText) ||
        ((msg.mediaCount ?? 0) > 0 ? "Sent you media" : "Sent you a message");
      const createdMs = msg.createdAt
        ? Date.parse(toUtcIso(msg.createdAt)) || Date.now()
        : Date.now();

      // History is mirrored REGARDLESS of the toggles (see deliverNotification),
      // so the bell dropdown still lists DMs with toasts off — OF's
      // /notifications feed lists them inconsistently, so this is their only
      // reliable route into the dropdown.
      // No notif-list refetch: the rail lists only money, and the bell merges
      // the history mirror — re-reading OF's feed per DM was 2 OF calls per
      // model per message, the bulk of the rail's OF traffic.
      const s = settingsFor(aid);
      deliverNotification(s, {
        id,
        accountId: aid,
        typeKey: "message",
        rawType: "message",
        user,
        text,
        historyText: rawText || text,
        createdMs,
        href: `/messages-pro/${encodeURIComponent(aid)}/${fanId}`,
      });
      // The new-message sound has its own switch (not the toast's); the master
      // toggle (and the account's platform switch) mutes it like every other
      // ping. One window plays it.
      if (s.enabled && s.sounds.message.on) {
        playAlertOnce(`${aid}:${id}`, s.sounds.message.sound);
      }
    });
    return off;
  }, [qc, settingsFor, ready, targetIds]);

  // SSE: a person answered a fan (the relay's `chat_responded`): that fan's
  // message rows in the bell say "<by> has responded" instead of offering Reply.
  useEffect(() => eventBus.on("chat_responded", (env: EventEnvelope) => {
    const r = env.chat_responded as { fan_id?: FanId; by?: string } | undefined;
    if (env.__account_id && isValidFanId(r?.fan_id)) {
      markNotifHistoryResponded(env.__account_id, r.fan_id, r.by ?? "");
    }
  }), []);

  // SSE: a PPV unlock. The ONLY money event with no push path of its own —
  // OF sends no purchase frame and no purchase toast (verified against the
  // full raw-event window), so the `toasts` handler above never fires for a
  // buy and, before this, a sale produced no toast, no badge, no bell entry,
  // and no rail row until someone reloaded the page.
  //
  // The relay announces it off OF's purchases-notification feed — the fresh
  // source (~30s). Deliberately NOT the transactions ledger: that is the money
  // record, but it lands late and by its own measurement sometimes hours late,
  // which is useless for "he just bought".
  //
  // `notif_id` is OF's REAL notification id, which is what makes this safe:
  // the rail and bell list that same feed, and both dedupe on the id, so this
  // live ping and the eventual feed row collapse into ONE row instead of
  // showing the sale twice.
  useEffect(() => {
    if (!ready) return;
    const off = eventBus.on("purchase_notified", (env: EventEnvelope) => {
      const aid = env.__account_id;
      if (!aid || !targetIds.includes(aid)) return;
      const p = env.purchase_notified as {
        notif_id?: string; fan_id?: FanId; amount_cents?: number;
        created_at?: string | null; name?: string | null;
      } | undefined;
      const fanId = p?.fan_id;
      if (!p?.notif_id || !isValidFanId(fanId)) return;

      // OF's own id, unprefixed — it MUST equal the id the feed will carry
      // for this purchase, or the dedupe this whole design rests on fails.
      const id = String(p.notif_id);
      if (!claimUnseen(aid, id)) return;

      // The notification names the payer; fall back to the ["of-user"] cache
      // the message handler above populates.
      const cached = qc.getQueryData<NotificationUser | null>(ofUserNameKey(aid, fanId));
      const user: NotificationUser = {
        id: fanId,
        name: p.name || cached?.name,
        username: cached?.username,
        avatar: cached?.avatar,
      };

      const cents = Number(p.amount_cents);
      const text = Number.isFinite(cents) && cents > 0
        ? `Unlocked your PPV — ${fmtPrice(cents)}`
        : "Unlocked your PPV";
      // OF stamps these with an explicit offset ("…+00:00"); toUtcIso passes
      // a zoned timestamp through untouched.
      const createdMs = p.created_at
        ? Date.parse(toUtcIso(p.created_at)) || Date.now()
        : Date.now();

      const arrival: Arrival = {
        id,
        accountId: aid,
        typeKey: "purchases",
        rawType: "purchases",
        user,
        text,
        createdMs,
        // Same one-shot refresh flag the money toasts and rail rows carry —
        // the fan just moved money, so the popout's caches are stale.
        href: withRefreshFlag(`/messages-pro/${encodeURIComponent(aid)}/${fanId}`, "purchases"),
      };
      deliverNotification(settingsFor(aid), arrival);
      // The relay read this off OF's purchases feed — the list already has it,
      // so seed the row instead of re-reading it.
      seedMoneyList(qc, arrival);
    });
    return off;
  }, [qc, settingsFor, ready, targetIds]);

  // Request OS permission lazily once the user has flipped osPing on. The
  // desktop app notifies natively and needs no web permission.
  useEffect(() => {
    if (!settings.osPing) return;
    if (typeof Notification === "undefined" || hasShellNotify()) return;
    if (Notification.permission === "default") {
      try { Notification.requestPermission().catch(() => {}); } catch { /* ignore */ }
    }
  }, [settings.osPing]);

  return null;
}

function ToastCard({ t }: { t: Toast }) {
  const avatar = proxyImage(t.user?.avatar ?? null, t.accountId);
  const ring = t.bubble
    ? "ring-2 ring-accent shadow-[0_0_24px_-4px_var(--color-accent)]"
    : "ring-1 ring-border";
  const sticker = t.bubble ? "text-base" : "text-xs";
  const body = (
    <div
      className={
        "pointer-events-auto w-auto sm:w-[320px] bg-panel rounded-lg overflow-hidden flex items-start gap-2.5 p-2.5 " +
        ring
      }
    >
      <div className="w-9 h-9 rounded-full bg-bg-elev-1 overflow-hidden shrink-0 grid place-items-center relative">
        {avatar ? (
          <img src={avatar} alt="" loading="lazy" decoding="async" className="w-full h-full object-cover" />
        ) : (
          <span className="text-[11px] text-fg-dim">
            {(t.user?.name || t.user?.username || "?").slice(0, 1).toUpperCase()}
          </span>
        )}
        <span className={`absolute -bottom-1 -right-1 ${sticker}`} aria-hidden>
          {stickerFor(t.typeKey)}
        </span>
      </div>
      <div className="min-w-0 flex-1">
        <div className="text-[12px] text-fg leading-snug">
          {t.user?.name && <span className="font-medium">{t.user.name} </span>}
          <span className="text-fg-dim">{t.text}</span>
        </div>
        <div className="text-[10px] text-fg-dim mt-0.5 flex items-center justify-between gap-2">
          <span>{labelFor(t.typeKey, t.rawType)}</span>
          {t.href && (
            <span className="text-fg-dim/80 hover:text-fg underline underline-offset-2">
              Open chat ↗
            </span>
          )}
        </div>
      </div>
      {t.action && (
        <button
          type="button"
          onClick={() => { t.action?.run(); dismissToast(t.accountId, t.id); }}
          className="text-[11px] px-2 h-10 sm:h-6 rounded border border-border hover:bg-bg-elev-1 shrink-0"
        >
          {t.action.label}
        </button>
      )}
      <button
        type="button"
        onClick={(e) => { e.preventDefault(); e.stopPropagation(); dismissToast(t.accountId, t.id); }}
        className="text-fg-dim hover:text-fg text-[11px] w-10 h-10 sm:w-5 sm:h-5 grid place-items-center rounded hover:bg-bg-elev-1"
        aria-label="Dismiss"
      >
        ✕
      </button>
    </div>
  );
  if (t.href) {
    const href = t.href;
    return (
      <a
        href={href}
        target={chatTabName(href)}
        className="block animate-toast-in"
        onClick={(e) => {
          openChatTab(e, href);
          dispatchNotifCleared();
          dismissToast(t.accountId, t.id);
        }}
      >
        {body}
      </a>
    );
  }
  return <div className="animate-toast-in">{body}</div>;
}

function stickerFor(k: NotifTypeKey | null): string {
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

function labelFor(k: NotifTypeKey | null, raw: string): string {
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

function ToastStack() {
  const toasts = useToastStack();
  if (toasts.length === 0) return null;
  return (
    <div className="fixed top-[var(--chrome-top)] left-2 right-2 sm:left-auto sm:right-3 z-[60] flex flex-col gap-2 pointer-events-none [&>*:nth-child(n+3)]:hidden sm:[&>*:nth-child(n+3)]:block">
      {toasts.slice().reverse().map((t) => (
        <ToastCard key={`${t.accountId ?? "app"}:${t.id}`} t={t} />
      ))}
    </div>
  );
}

const REMINDED_KEY = "chatterly:shift-reminders:v1";
const MAX_REMINDED = 200;

/** Atomically claim a reminder key: false = already shown in this browser
 *  (persisted, so a reload does not repeat it), true = now marked shown.
 *  Keeps the newest MAX_REMINDED keys. Keys carry the chatter id, so two
 *  chatters sharing a browser are each reminded. */
function claimReminder(key: string): boolean {
  let seen: string[] = [];
  try {
    const raw = JSON.parse(window.localStorage.getItem(REMINDED_KEY) ?? "[]");
    if (Array.isArray(raw)) seen = raw.filter((k): k is string => typeof k === "string");
  } catch { /* unreadable: start over */ }
  if (seen.includes(key)) return false;
  try {
    window.localStorage.setItem(REMINDED_KEY, JSON.stringify([...seen, key].slice(-MAX_REMINDED)));
  } catch { /* storage full or blocked: the toast still shows once in this tab */ }
  return true;
}

/**
 * The clock-in reminder: a Chatter session's `GET /admin/shifts/me` poll
 * (the Relay decides when `reminder` is set), one toast per occurrence.
 *
 * ASSUMPTION: the reminder toast ignores the notification Settings toggles
 * (they are per OF notification type) and does not bump the bell badge or
 * enter its history; the agency's `clock_in_reminder` is its only switch. It
 * keeps the stack's usual 8-second lifetime. Rung 3 for the lifetime, rung 5
 * for the rest. Overturned if the reminder must honour the master toggle or
 * stay until dismissed.
 */
function ClockInReminder() {
  const user = useOptionalUser()?.user ?? null;
  const chatter = useOptionalChatter()?.chatter ?? null;
  const me = useMyShifts(!user && !!chatter);
  const clock = useClock(!user && !!chatter);
  // Stable, and reads the clock as it is when the toast's button runs.
  const act = clock.act;
  const reminder = me.data?.reminder ?? null;
  const accounts = me.data?.accounts;
  const chatterId = chatter?.chatter_id;

  useEffect(() => {
    if (!reminder || !chatterId) return;
    const key = `${chatterId}:${reminder.shift_id}:${reminder.occurrence_start}`;
    if (!claimReminder(key)) return;
    const creator = accounts?.find((a) => a.account_id === reminder.account_id)?.display_name
      ?? reminder.account_id;
    pushToast({
      id: `shift-reminder:${key}`,
      accountId: reminder.account_id,
      typeKey: null,
      rawType: "Shift reminder",
      user: null,
      text: `Your shift on ${creator} has started.`,
      createdAt: Date.now(),
      bubble: false,
      href: null,
      expiresAt: Date.now() + TOAST_TTL_MS,
      action: { label: "Clock in", run: () => void act("in") },
    });
  }, [reminder, accounts, chatterId, act]);

  return clock.picking ? <ClockDialog onClose={clock.closePicker} /> : null;
}

/** `lib/notices`' one-line notices as cards in the stack, with the usual lifetime. */
function NoticeBridge() {
  useEffect(() => onNotice((n) => pushToast({
    id: n.id,
    accountId: null,
    typeKey: null,
    rawType: n.label,
    user: null,
    text: n.text,
    createdAt: Date.now(),
    bubble: false,
    href: null,
    expiresAt: Date.now() + TOAST_TTL_MS,
  })), []);
  return null;
}

export function NotificationToaster() {
  // A chatter's "permissions updated" / "unassigned from" notices.
  useAccessChangeNotices();
  return (
    <>
      <NotificationDeltaPoller />
      <ClockInReminder />
      <NoticeBridge />
      <ToastStack />
    </>
  );
}
