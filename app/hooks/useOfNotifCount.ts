"use client";

/**
 * useOfNotifCount — a Creator's OnlyFans notification count
 * (`/api/of/v2/users/notifications/count`, its `all`), under the
 * `["of-notif-count", accountId]` key the OF Manager Creator column reads too,
 * so every reader shares one cache entry. `accountId` null reads nothing (the
 * callers pass null for a Dead-session Creator). A failed read counts 0.
 * Re-read only while this tab leases the Creator; an unleased one reads once
 * armed and then only on its next `creator_warmed` (lib/ofReadGate.ts), which
 * carries the warmed count: written into this entry, no read
 * (hooks/useAccountStateEvents.ts).
 * `staleMs`: how long a read stays fresh (OF Manager's column: 60 s, as Infloww's).
 *
 * `useMarkOfNotifsRead` lowers that count the only way OF does: its mark-read write
 * (`POST /users/notifications/read`, what OF web sends when a notifications tab opens).
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { skipToken, useQueries, useQuery, useQueryClient, type QueryKey } from "@tanstack/react-query";

import { cachedCountSum, markAllTargets } from "@/components/notificationBellReducer";
import { useOfReadGate } from "@/hooks/useOfReadGate";
import { relay } from "@/lib/relay";
import { gateOptions } from "@/lib/ofReadGate";

interface NotifCountResp { all?: number }

const NO_IDS: readonly string[] = [];
/** The count's key, for the lease-gain refetch. */
export const COUNT_ROOTS = ["of-notif-count"] as const;

export function useOfNotifCount(accountId: string | null, staleMs = 30_000) {
  const gate = useOfReadGate(accountId ? [accountId] : NO_IDS, COUNT_ROOTS)(accountId ?? "");
  const { enabled, ...gated } = gateOptions(gate);
  const q = useQuery<number>({
    queryKey: ["of-notif-count", accountId],
    // A badge: background (queued behind clicks, lib/relaySchedule), dropped when its screen goes (signal).
    queryFn: accountId && enabled !== false
      ? async ({ signal }) => Number((await relay.get<NotifCountResp>(
        "/api/of/v2/users/notifications/count", { accountId, priority: "background" }, signal))?.all) || 0
      : skipToken,
    staleTime: staleMs,
    retry: false,
    ...gated,
  });
  return { count: q.isError ? 0 : q.data ?? 0, refetch: q.refetch };
}

/** The Relay's mark-read route (service/server.py `of_notifications_mark_read`): All, no type. */
export const NOTIF_READ_PATH = "/api/of/v2/users/notifications/read";

/**
 * Mark a Creator's OnlyFans notifications read: one OF write. Its answer's
 * `counters` (the count route's shape) is written into the count entry, so
 * every badge reading it drops at once; without them the entry is re-read
 * (the Relay dropped its cached count). A failed write leaves the count as
 * it was and resolves false.
 */
export function useMarkOfNotifsRead() {
  const qc = useQueryClient();
  return useCallback(async (accountId: string): Promise<boolean> => {
    let resp: { counters?: NotifCountResp } | undefined;
    try {
      resp = await relay.post<{ counters?: NotifCountResp }>(NOTIF_READ_PATH, undefined, { accountId });
    } catch {
      return false;
    }
    const all = resp?.counters?.all;
    // A count read still in flight (the panel-close re-read) may predate the write: drop it.
    await qc.cancelQueries({ queryKey: ["of-notif-count", accountId] });
    if (typeof all === "number") qc.setQueryData<number>(["of-notif-count", accountId], all);
    else void qc.invalidateQueries({ queryKey: ["of-notif-count", accountId] });
    return true;
  }, [qc]);
}

const countKey = (accountId: string) => ["of-notif-count", accountId] as const;

/**
 * These Creators' counts summed from the cache only: disabled observers (no
 * read) that re-sum as any entry changes (a `creator_warmed`, a reader, a
 * mark-read) and keep the entries cached while shown.
 */
export function useCachedOfNotifSum(ids: readonly string[]): number {
  const qs = useQueries({ queries: ids.map((id) => ({ queryKey: countKey(id), queryFn: skipToken })) });
  const data = new Map(ids.map((id, i) => [id, qs[i]?.data as number | undefined]));
  return cachedCountSum(ids, (id) => data.get(id));
}

/**
 * "Mark all read" over live Creators: one mark-read each, serially (up to 50
 * Creators, each an OF write on its own proxy), skipping any whose cached
 * count is 0. A second call while one runs does nothing.
 */
export function useMarkAllOfNotifsRead() {
  const qc = useQueryClient();
  const markOfNotifsRead = useMarkOfNotifsRead();
  const [marking, setMarking] = useState(false);
  const running = useRef(false);
  const markAll = useCallback(async (liveIds: readonly string[]) => {
    if (running.current) return;
    running.current = true;
    setMarking(true);
    try {
      for (const id of markAllTargets(liveIds, (aid) => qc.getQueryData<number>(countKey(aid)))) {
        await markOfNotifsRead(id);
      }
    } finally {
      running.current = false;
      setMarking(false);
    }
  }, [qc, markOfNotifsRead]);
  return { marking, markAll };
}

/**
 * A notifications page's mark-read: one `useMarkOfNotifsRead` write per Creator per mount (A → B → A is still one
 * write for A), once `ready` (its list answered, so unread rows are drawn as unread first); never per render or on a
 * timer. A write that went through re-reads `reread` (the page's own tab counts).
 */
export function useMarkNotifsReadOnce(accountId: string | null, ready: boolean, reread: QueryKey) {
  const qc = useQueryClient();
  const mark = useMarkOfNotifsRead();
  const done = useRef(new Set<string>());
  // `reread` is a fresh array each render: the effect re-runs, and `done` keeps it to one write.
  useEffect(() => {
    if (!ready || !accountId || done.current.has(accountId)) return;
    done.current.add(accountId);
    void mark(accountId).then((ok) => {
      if (ok) void qc.invalidateQueries({ queryKey: reread, exact: true });
    });
  }, [ready, accountId, mark, qc, reread]);
}
