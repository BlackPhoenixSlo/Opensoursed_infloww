"use client";

/**
 * useAccountStateEvents — turn the relay's account-state SSE events into
 * react-query invalidations, so the queries they cover can drop their fast
 * polls to a slow safety poll (see `ssePoll`). Mounted once, in ScopeProvider.
 *
 * The relay already scopes these to the signed-in principal's Creators and
 * Agency; nothing here filters.
 *
 * `transaction_recorded` (a sale landed in the ledger, sent after its commit by
 * the OF ingest, the WS pump and the Fansly lane) refetches the open reports
 * and dashboard, so they are live without a poll: at once, then at most once
 * more per SALES_MIN_MS. Not the infinite Sales records list, which would
 * re-walk every loaded page; its Refresh button covers it.
 */

import { useEffect } from "react";
import { useQueryClient, type QueryKey } from "@tanstack/react-query";
import { eventBus, type EventEnvelope } from "@/lib/events";
import { APPLIED_SETTINGS_KEY } from "@/lib/appliedSettings";

type Body = Record<string, unknown>;

const byAccount = (key: string, aid: string | undefined): QueryKey => (aid ? [key, aid] : [key]);

const KEYS: Record<string, (aid: string | undefined, body: Body) => QueryKey[]> = {
  session_dead: () => [["accounts"], ["app-errors", "recent"]],
  agency_notifications: () => [["agency-notifications"]],  // the owner's centre (AgencyNotifications.tsx)
  account_active: () => [["accounts"], ["chatter"]],
  proxy_switched: () => [["proxies"], ["accounts"]],
  permissions_changed: () => [APPLIED_SETTINGS_KEY],
  assignment_changed: () => [["accounts"], ["chatter"], ["employees"]],
  scheduled_send_changed: (aid) => [byAccount("scheduled-sends", aid)],
  rule_run_finished: (aid, b) => [
    byAccount("automation-rules", aid),
    ["stats", "automation-runs"],
    ...(b.kind === "scheduled_send" ? [byAccount("scheduled-sends", aid)] : []),
    ...(b.status === "error" ? [["app-errors", "recent"]] : []),
  ],
};

/** A busy Agency finishes runs back to back: their invalidations are
 *  gathered and sent at most once per this window. */
export const COALESCE_MS = 2_000;
const COALESCED = new Set(["rule_run_finished", "scheduled_send_changed"]);
/** `resync` refetches every query; a flapping link must not repeat that. */
export const RESYNC_MIN_MS = 30_000;
/** A sale refetches the heavy reports; a busy Agency sells back to back. */
export const SALES_MIN_MS = 30_000;
const SALES_ROOTS = new Set<unknown>(["stats", "dashboard", "competitor"]);
const refetchedOnSale = (key: QueryKey) =>
  SALES_ROOTS.has(key[0]) && !(key[0] === "stats" && key[1] === "sales-records");

/** Run `fn` now, then at most once more per `ms`: a call inside the window
 *  schedules one trailing run at its end, so a change is never lost. */
function throttle(fn: () => void, ms: number) {
  let last = -Infinity;
  let timer: ReturnType<typeof setTimeout> | null = null;
  const run = () => { last = Date.now(); fn(); };
  return {
    call: () => {
      const wait = last + ms - Date.now();
      if (wait <= 0) return run();
      timer ??= setTimeout(() => { timer = null; run(); }, wait);
    },
    cancel: () => { if (timer) clearTimeout(timer); },
  };
}
/** The SSE-relaxed polls (`ssePoll`). When the stream drops, one refetch
 *  re-arms each at its offline rate instead of waiting out the live one. */
const SSE_POLLED: QueryKey[] = [
  ["scheduled-sends"], ["automation-rules"], ["stats", "automation-runs"],
  ["app-errors", "recent"],
];

export function useAccountStateEvents(): void {
  const qc = useQueryClient();
  useEffect(() => {
    const invalidate = (keys: QueryKey[]) => {
      for (const queryKey of keys) void qc.invalidateQueries({ queryKey });
    };

    const pending = new Map<string, QueryKey>();
    let flushTimer: ReturnType<typeof setTimeout> | null = null;
    const coalesce = (keys: QueryKey[]) => {
      for (const k of keys) pending.set(JSON.stringify(k), k);
      flushTimer ??= setTimeout(() => {
        flushTimer = null;
        const keys = [...pending.values()];
        pending.clear();
        invalidate(keys);
      }, COALESCE_MS);
    };

    const offs = Object.entries(KEYS).map(([type, keysFor]) =>
      eventBus.on(type, (e: EventEnvelope) => {
        const keys = keysFor(e.__account_id, (e[type] ?? {}) as Body);
        if (COALESCED.has(type)) coalesce(keys);
        else invalidate(keys);
      }),
    );

    // The relay could not replay what this tab missed: refetch everything.
    // Leading refetch, then at most one trailing one per window, so a resync
    // that lands while the first refetch is in flight is not lost.
    const resync = throttle(() => void qc.invalidateQueries(), RESYNC_MIN_MS);
    offs.push(eventBus.on("resync", resync.call), resync.cancel);

    const sale = throttle(
      () => void qc.invalidateQueries({ predicate: (q) => refetchedOnSale(q.queryKey) }), SALES_MIN_MS);
    offs.push(eventBus.on("transaction_recorded", sale.call), sale.cancel);

    let wasConnected = false;
    offs.push(eventBus.onStateChange((connected) => {
      // Idle mode closed it on purpose: its polls are paused too (useIdleMode).
      if (wasConnected && !connected && !eventBus.isPaused()) invalidate(SSE_POLLED);
      wasConnected = connected;
    }));

    return () => {
      offs.forEach((off) => off());
      if (flushTimer) clearTimeout(flushTimer);
    };
  }, [qc]);
}
