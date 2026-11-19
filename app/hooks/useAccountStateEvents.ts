"use client";

/**
 * useAccountStateEvents — turn the relay's account-state SSE events into
 * react-query invalidations, so the queries they cover can drop their fast
 * polls to a slow safety poll (see `ssePoll`). Mounted once, in ScopeProvider.
 *
 * The relay already scopes these to the signed-in principal's Creators and
 * Agency; nothing here filters. `creator_warmed` (the App-open warm read a
 * Creator) reaches every tab that can access the Creator, whatever its scope;
 * it also arms that Creator's money-list and count reads at once
 * (lib/ofReadGate.ts: an unleased Creator reads nothing until then). It
 * carries the warmed roster and notifications counts, written into the cache,
 * not re-read; the rail and bell lists re-read only when what is cached was
 * read before the warm (`warmMark`).
 *
 * `transaction_recorded` (a sale landed in the ledger, sent after its commit by
 * the OF ingest, the WS pump and the Fansly lane) refetches the open reports
 * and dashboard, so they are live without a poll: at once, then at most once
 * more per SALES_MIN_MS. Not the infinite Sales records list, which would
 * re-walk every loaded page; its Refresh button covers it.
 */

import { useEffect } from "react";
import { useQueryClient, type Query, type QueryKey } from "@tanstack/react-query";
import { eventBus, type EventEnvelope } from "@/lib/events";
import { APPLIED_SETTINGS_KEY } from "@/lib/appliedSettings";
import { invalidateVaultQueries } from "@/lib/vaultInvalidation";
import { armRead } from "@/lib/ofReadGate";
import { writeWarmedRosterCount, type RosterCount } from "@/hooks/useRosterCounts";

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
    ...(b.kind === "full_ai_chat" ? [byAccount("full-ai-today", aid)] : []),
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
/** `creator_warmed`'s body (service/app_open_warm.py `_publish`): the warmed entries' values, when the relay
 *  still held them, and its epoch ms. */
interface WarmBody { roster?: RosterCount; notif_count?: number; now?: number }

/** What a warm does to one cached query of its Creator when it comes:
 *  - `write` the value the event carries, no read;
 *  - `must` re-read at the flush: a read in flight now may have been served before the warm;
 *  - `unless` re-read at the flush unless a read ends first: what it holds (data or an error) is from before;
 *  - `skip`: never read; its first read, from now on, is served the warm's entries. */
export type WarmMark = "write" | "must" | "unless" | "skip";

export function warmMark(
  s: { fetchStatus: string; dataUpdatedAt: number; errorUpdatedAt: number }, hasValue: boolean,
): WarmMark {
  if (s.fetchStatus === "fetching") return "must";
  if (hasValue) return "write";
  return s.dataUpdatedAt > 0 || s.errorUpdatedAt > 0 ? "unless" : "skip";
}

/** The SSE-relaxed polls (`ssePoll`). When the stream drops, one refetch
 *  re-arms each at its offline rate instead of waiting out the live one. */
const SSE_POLLED: QueryKey[] = [
  ["scheduled-sends"], ["automation-rules"], ["stats", "automation-runs"],
  ["app-errors", "recent"], ["roster-counts"], ["full-ai-today"],
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

    // The warm's re-reads, per query hash, flushed COALESCE_MS after the first (a warm lands Creator by Creator).
    // A read ending after the warm came drops an `unless` (it was served the warm's entries); a `must`'s first
    // ending is the read in flight when the warm came, so it becomes an `unless`.
    const cache = qc.getQueryCache();
    const warmPending = new Map<string, { queryKey: QueryKey; must: boolean }>();
    let warmTimer: ReturnType<typeof setTimeout> | null = null;
    const markWarm = (q: Query, must: boolean) => {
      const had = warmPending.get(q.queryHash);
      warmPending.set(q.queryHash, { queryKey: q.queryKey, must: must || !!had?.must });
      warmTimer ??= setTimeout(() => {
        warmTimer = null;
        const due = [...warmPending.values()];
        warmPending.clear();
        for (const { queryKey } of due) void qc.invalidateQueries({ queryKey, exact: true });
      }, COALESCE_MS);
    };
    offs.push(cache.subscribe((ev) => {
      if (ev.type !== "updated") return;
      const p = warmPending.get(ev.query.queryHash);
      const a = ev.action;
      if (!p || !((a.type === "success" && !a.manual) || a.type === "error")) return;
      if (p.must) p.must = false;
      else warmPending.delete(ev.query.queryHash);
    }));
    const onWarmed = (e: EventEnvelope) => {
      const aid = e.__account_id;
      if (!aid) return;
      const b = (e.creator_warmed ?? {}) as WarmBody;
      const receivedAt = Date.now();
      const roster = b.roster && typeof b.roster.as_of === "number" && b.roster.as_of > 0 ? b.roster : null;
      const count = typeof b.notif_count === "number" ? b.notif_count : null;
      for (const q of cache.findAll({ queryKey: ["roster-counts"] })) {
        // Written even under a read in flight: that read's merge keeps the newer `as_of` (mergeRosterCounts).
        if (roster) writeWarmedRosterCount(qc, q.queryKey, aid, roster, b.now, receivedAt);
        else if (warmMark(q.state, false) !== "skip") markWarm(q, q.state.fetchStatus === "fetching");
      }
      const own = [...cache.findAll({ queryKey: ["of-notif-count", aid] }), ...cache.findAll({ queryKey: ["notif-list", aid] })];
      for (const q of own) {
        const mark = warmMark(q.state, q.queryKey[0] === "of-notif-count" && count !== null);
        if (mark === "write") {
          qc.setQueryData(q.queryKey, count);
          warmPending.delete(q.queryHash);
        } else if (mark !== "skip") markWarm(q, mark === "must");
      }
    };
    // Written, then armed: a count written into an unarmed reader's empty entry is that reader's first read.
    offs.push(eventBus.on("creator_warmed", (e: EventEnvelope) => { onWarmed(e); armRead(e.__account_id); }));

    // The relay could not replay what this tab missed: refetch everything.
    // Leading refetch, then at most one trailing one per window, so a resync
    // that lands while the first refetch is in flight is not lost.
    const resync = throttle(() => void invalidateVaultQueries(qc), RESYNC_MIN_MS);
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
      if (warmTimer) clearTimeout(warmTimer);
    };
  }, [qc]);
}
