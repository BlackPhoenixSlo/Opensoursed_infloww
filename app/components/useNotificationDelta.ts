"use client";


import { useEffect, useMemo } from "react";
import { useQueryClient } from "@tanstack/react-query";
import type { QueryClient } from "@tanstack/react-query";

import { useScope } from "@/contexts/ScopeContext";
import { useActiveAccounts } from "@/hooks/useAccounts";
import { accountPlatform, isPlatform } from "@/lib/platform";
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
  type NotifSettings,
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

function playSaleSound(s: NotifSettings, n: Arrival): void {
  if (!isMoney(n.typeKey) || Math.abs(Date.now() - n.createdMs) > 5 * 60_000) return;
  if (s.enabled && s.sounds.sale.on && claimUnseen(`${n.accountId}#sound`, n.id)) {
    playAlertOnce(`${n.accountId}:${n.id}`, s.sounds.sale.sound);
  }
}

// Seed the SSE row into the rail's cached list (same id as OF's feed row); the history mirror alone loses a sale to DM churn.
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
  const activeIds = useMemo(() => new Set(active.map((a) => a.id)), [active]);
  const settingsFor = useMemo(() => {
    const platformOf = new Map(active.map((a) => [a.id, accountPlatform(a)]));
    const off = { ...settings, enabled: false };
    return (aid: string) => {
      const p = platformOf.get(aid) ?? "onlyfans";
      return isPlatform(p) && settings.platforms[p] ? settings : off;
    };
  }, [active, settings]);

  useEffect(() => {
    if (!ready) return;
    // Listener runs with the master toggle off: the history mirror feeds the bell and the rail; only pings are gated.
    const off = eventBus.on("toasts", (env: EventEnvelope) => {
      const aid = env.__account_id;
      const inScope = !!aid && targetIds.includes(aid);
      if (!aid || (!inScope && !activeIds.has(aid))) return;
      const arr = (env as { toasts?: unknown }).toasts;
      if (!Array.isArray(arr)) return;

      for (const raw of arr) {
        const arrival = toastArrival(aid, raw);
        if (!arrival) continue;
        const { id, typeKey, user } = arrival;
        if (!inScope && !isMoney(typeKey)) continue;
        if (user.id != null) seedName(qc, aid, user.id, user);

        // No notif-list refetch: arrivals are mirrored locally; re-reading OF would cost 2 calls per model per event.
        mirrorNotification(arrival);
        if (inScope && claimUnseen(aid, id)) pingNotification(settingsFor(aid), arrival);
        if (inScope) playSaleSound(settingsFor(aid), arrival);
        seedMoneyList(qc, arrival);

        if (inScope && !user.id && user.username) {
          const uname = user.username;
          resolveUsernameId(aid, uname, qc).then((resolvedId) => {
            if (resolvedId == null) return;
            patchToastHref(aid, id, notificationHref(aid, { ...user, id: resolvedId }, { refresh: isMoney(typeKey) })!);
            patchNotifHistoryUser(aid, id, { id: resolvedId });
            patchMoneyListUser(qc, aid, typeKey, id, { id: resolvedId });
          }).catch(() => { });
        }
      }
    });
    return off;
  }, [qc, settingsFor, ready, targetIds, activeIds]);

  useEffect(() => {
    if (!ready) return;
    // OF `toasts` does not carry DMs; mirror them here. Only a fan's inbound DM pings.
    const off = eventBus.on("api2_chat_message", (env: EventEnvelope) => {
      const target = resolveChatTarget(
        env as unknown as Parameters<typeof resolveChatTarget>[0],
      );
      if (!target) return;
      const { accountId: aid, isOutbound } = target;
      if (isOutbound) return;
      if (!targetIds.includes(aid)) return;

      const arrival = dmArrival(target);
      const { id, user } = arrival;
      if (user.id != null) seedName(qc, aid, user.id, user);

      const s = settingsFor(aid);
      mirrorNotification(arrival);
      if (claimUnseen(aid, id)) pingNotification(s, arrival);
    });
    return off;
  }, [qc, settingsFor, ready, targetIds]);

  useEffect(() => eventBus.on("chat_responded", (env: EventEnvelope) => {
    const r = env.chat_responded as { fan_id?: FanId; by?: string } | undefined;
    if (env.__account_id && isValidFanId(r?.fan_id)) {
      markNotifHistoryResponded(env.__account_id, r.fan_id, r.by ?? "");
    }
  }), []);

  useEffect(() => {
    if (!ready) return;
    // The only money event with no push path of its own (OF sends no purchase frame); fed off the purchases feed, not the late transactions ledger.
    const off = eventBus.on("purchase_notified", (env: EventEnvelope) => {
      const aid = env.__account_id;
      const inScope = !!aid && targetIds.includes(aid);
      if (!aid || (!inScope && !activeIds.has(aid))) return;
      const p = env.purchase_notified as Partial<PurchaseNotified> | undefined;
      const fanId = p?.fan_id;
      if (!p?.notif_id || !isValidFanId(fanId)) return;

      // notif_id is OF's real id: the rail and bell dedupe on it, so this ping and the feed row collapse into one.
      const cached = qc.getQueryData<NotificationUser | null>(ofUserNameKey(aid, fanId));
      const arrival = purchaseArrival(aid, { ...p, notif_id: p.notif_id, fan_id: fanId }, cached);
      mirrorNotification(arrival);
      if (inScope && claimUnseen(aid, arrival.id)) pingNotification(settingsFor(aid), arrival);
      if (inScope) playSaleSound(settingsFor(aid), arrival);
      seedMoneyList(qc, arrival);
    });
    return off;
  }, [qc, settingsFor, ready, targetIds, activeIds]);

  useEffect(() => {
    if (!ready) return;
    return listenPushNotices((raw) =>
      deliverPushNotice(raw, (aid) => (targetIds.includes(aid) ? settingsFor(aid) : null)));
  }, [settingsFor, ready, targetIds]);

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
