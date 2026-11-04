"use client";

/**
 * useNotificationDelta — the toaster's SSE lanes (`NotificationToaster`): OF's
 * `toasts` feed, inbound DMs (`api2_chat_message`), PPV unlocks
 * (`purchase_notified`) and `chat_responded`. The three arrival lanes are
 * each parse (toastStore's pure `*Arrival`) → on EVERY frame the history row
 * (`mirrorNotification`) and the lane's own side effects (name / rail seeding,
 * the username lookup, the sound) → claim (`claimUnseen`) → pings
 * (`pingNotification`). The claim gates the pings only: a Web Push the service
 * worker offered this focused page (`push-notice`, toastStore.deliverPushNotice,
 * same scope as the lanes, pings only) may have claimed the arrival first, and
 * its frame (idle mode's replay) must still write the full history row, seed
 * the rail and play the sound; those dedupe themselves (by id, by the sound's
 * own claim). Also the lazy Web Push sync (lib/webPush). The OS permission
 * is asked only from a tap (NotificationBell): iOS ignores an ask without one.
 */

import { useEffect, useMemo } from "react";
import { useQueryClient } from "@tanstack/react-query";
import type { QueryClient } from "@tanstack/react-query";

import { useScope } from "@/contexts/ScopeContext";
import { useActiveAccounts } from "@/hooks/useAccounts";
import { accountPlatform } from "@/lib/platform";
import { useDeferredMount } from "@/hooks/useDeferredMount";
import { useNotificationSettings } from "@/hooks/useNotificationSettings";
import { eventBus, type EventEnvelope } from "@/lib/events";
import { resolveChatTarget } from "@/hooks/useInboxRealtime";
import { isValidFanId, type FanId } from "@/lib/fanId";
import { notificationHref } from "@/lib/notificationLink";
import { listenPushNotices, primePush, pushSupported, syncPush } from "@/lib/webPush";
import { playAlertOnce } from "@/lib/alertSounds";
import type { NotificationItem, NotificationUser } from "@/lib/moneyRailStorage";
import { ofUserNameKey } from "@/hooks/useOFUser";
import { MONEY_ROWS_CAP, isMoney, moneyListKey } from "@/lib/notifText";
import {
  markNotifHistoryResponded,
  patchNotifHistoryUser,
  type NotifTypeKey,
} from "@/lib/notifSettings";
import {
  claimUnseen,
  deliverPushNotice,
  dmArrival,
  mirrorNotification,
  patchToastHref,
  pingNotification,
  purchaseArrival,
  resolveUsernameId,
  seedName,
  toastArrival,
  type Arrival,
  type PurchaseNotified,
} from "./toastStore";

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
  qc.setQueryData(key, [row, ...prev].slice(0, MONEY_ROWS_CAP));
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

export function useNotificationDelta(): void {
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
        // Parse, then dedupe on the notification ID: OF's locale variants
        // share the same id so we only count each arrival once.
        const arrival = toastArrival(aid, raw);
        if (!arrival) continue;
        const { id, typeKey, user } = arrival;
        if (user.id != null) seedName(qc, aid, user.id, user);

        // History always, pings gated — the money rail and the feed dropdown
        // must still list a muted arrival (incl. likes).
        mirrorNotification(arrival);
        if (claimUnseen(aid, id)) pingNotification(settingsFor(aid), arrival);
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
            patchToastHref(aid, id, notificationHref(aid, { ...user, id: resolvedId }, { refresh: isMoney(typeKey) })!);
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
      const target = resolveChatTarget(
        env as unknown as Parameters<typeof resolveChatTarget>[0],
      );
      if (!target) return;
      const { accountId: aid, isOutbound } = target;
      if (isOutbound) return;                 // only a fan's inbound DM pings
      if (!targetIds.includes(aid)) return;   // in-scope accounts only

      const arrival = dmArrival(target);
      const { id, user } = arrival;
      if (user.id != null) seedName(qc, aid, user.id, user);

      // History is mirrored REGARDLESS of the toggles (toastStore.mirrorNotification),
      // so the bell dropdown still lists DMs with toasts off — OF's
      // /notifications feed lists them inconsistently, so this is their only
      // reliable route into the dropdown.
      // No notif-list refetch: the rail lists only money, and the bell merges
      // the history mirror — re-reading OF's feed per DM was 2 OF calls per
      // model per message, the bulk of the rail's OF traffic.
      const s = settingsFor(aid);
      mirrorNotification(arrival);
      if (claimUnseen(aid, id)) pingNotification(s, arrival);
      // The new-message sound has its own switch (not the toast's); the master
      // toggle (and the account's platform switch) mutes it like every other
      // ping. One window plays it, once per message: its own claim, apart
      // from the toast's (a push-notice may have claimed that one first).
      if (s.enabled && s.sounds.message.on && claimUnseen(`${aid}#sound`, id)) {
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
      const p = env.purchase_notified as Partial<PurchaseNotified> | undefined;
      const fanId = p?.fan_id;
      if (!p?.notif_id || !isValidFanId(fanId)) return;

      // The notification names the payer; fall back to the ["of-user"] cache
      // the message handler above populates.
      const cached = qc.getQueryData<NotificationUser | null>(ofUserNameKey(aid, fanId));
      const arrival = purchaseArrival(aid, { ...p, notif_id: p.notif_id, fan_id: fanId }, cached);
      // OF's own id, unprefixed — the dedupe this whole design rests on.
      mirrorNotification(arrival);
      if (claimUnseen(aid, arrival.id)) pingNotification(settingsFor(aid), arrival);
      // The relay read this off OF's purchases feed — the list already has it,
      // so seed the row instead of re-reading it.
      seedMoneyList(qc, arrival);
    });
    return off;
  }, [qc, settingsFor, ready, targetIds]);

  // Web Push the service worker offers this focused page (instead of an OS
  // notification): toasted here for an in-scope Creator, through the lanes'
  // claim, and acked; out of scope (or before this mounts: a popout still
  // booting) the worker shows it itself. No rail seeding or sound here: the
  // lane's own frame still does both when it arrives.
  useEffect(() => {
    if (!ready) return;
    return listenPushNotices((raw) =>
      deliverPushNotice(raw, (aid) => (targetIds.includes(aid) ? settingsFor(aid) : null)));
  }, [settingsFor, ready, targetIds]);

  // Web Push, lazily: the key and SW cached for a tap's subscribe; the relay's
  // row kept matching the settings (the PUT is an idempotent upsert that also
  // recreates a pruned row, the DELETE drops it when nothing is wanted); and
  // re-PUT on tab return and SSE reconnect, so a revoked session (401/404)
  // stops counting as live and the page pings again. A failed subscribe
  // shows the bell's hint (NotificationBell).
  useEffect(() => { void primePush(); }, []);
  useEffect(() => {
    if (!pushSupported()) return;
    void syncPush(settings);
    const again = () => { if (document.visibilityState === "visible") void syncPush(settings, { force: true }); };
    let was: boolean | null = null;
    const offStream = eventBus.onStateChange((up) => {
      if (up && was === false) again();
      was = up;
    });
    document.addEventListener("visibilitychange", again);
    return () => {
      offStream();
      document.removeEventListener("visibilitychange", again);
    };
  }, [settings]);
}
