"use client";


import { useCallback, useEffect, useReducer, useRef } from "react";
import { skipToken, useQueries, useQuery, useQueryClient, type QueryClient, type QueryKey } from "@tanstack/react-query";

import { cachedCountSum, initialMarkAll, markAllReducer, markAllTargets } from "@/components/notificationBellReducer";
import { useOfReadGate } from "@/hooks/useOfReadGate";
import { relay } from "@/lib/relay";
import { gateOptions } from "@/lib/ofReadGate";
import { lastNotifArrival } from "@/lib/notifSettings";

interface NotifCountResp { all?: number }

const NO_IDS: readonly string[] = [];
export const COUNT_ROOTS = ["of-notif-count"] as const;

const countAskedAt = new WeakMap<QueryClient, Map<string, number>>();
function askedAt(qc: QueryClient): Map<string, number> {
  let m = countAskedAt.get(qc);
  if (!m) countAskedAt.set(qc, (m = new Map()));
  return m;
}

export function useOfNotifCount(accountId: string | null, staleMs = 30_000) {
  const qc = useQueryClient();
  const gate = useOfReadGate(accountId ? [accountId] : NO_IDS, COUNT_ROOTS)(accountId ?? "");
  const { enabled, ...gated } = gateOptions(gate);
  const q = useQuery<number>({
    queryKey: ["of-notif-count", accountId],
    queryFn: accountId && enabled !== false
      ? async ({ signal }) => {
        const asked = Date.now();
        const n = Number((await relay.get<NotifCountResp>(
          "/api/of/v2/users/notifications/count", { accountId, priority: "background" }, signal))?.all) || 0;
        askedAt(qc).set(accountId, asked);
        return n;
      }
      : skipToken,
    staleTime: staleMs,
    retry: false,
    ...gated,
  });
  return { count: q.isError ? 0 : q.data ?? 0, refetch: q.refetch };
}

export const NOTIF_READ_PATH = "/api/of/v2/users/notifications/read";

export function useMarkOfNotifsRead() {
  const qc = useQueryClient();
  return useCallback(async (accountId: string): Promise<boolean> => {
    let resp: { counters?: NotifCountResp } | undefined;
    const asked = Date.now();
    try {
      resp = await relay.post<{ counters?: NotifCountResp }>(NOTIF_READ_PATH, undefined, { accountId });
    } catch {
      return false;
    }
    const all = resp?.counters?.all;
    // A count read in flight (panel-close re-read) may predate the write: drop it.
    await qc.cancelQueries({ queryKey: ["of-notif-count", accountId] });
    if (typeof all === "number") {
      qc.setQueryData<number>(["of-notif-count", accountId], all);
      askedAt(qc).set(accountId, asked);
    } else void qc.invalidateQueries({ queryKey: ["of-notif-count", accountId] });
    return true;
  }, [qc]);
}

const countKey = (accountId: string) => ["of-notif-count", accountId] as const;

export function useCachedOfNotifSum(ids: readonly string[]): number {
  const qs = useQueries({ queries: ids.map((id) => ({ queryKey: countKey(id), queryFn: skipToken })) });
  const data = new Map(ids.map((id, i) => [id, qs[i]?.data as number | undefined]));
  return cachedCountSum(ids, (id) => data.get(id));
}

export function useMarkAllOfNotifsRead() {
  const qc = useQueryClient();
  const markOfNotifsRead = useMarkOfNotifsRead();
  const [{ marking, status }, dispatch] = useReducer(markAllReducer, initialMarkAll);
  const running = useRef(false);
  const markAll = useCallback(async (liveIds: readonly string[]): Promise<boolean> => {
    if (running.current) return false;
    running.current = true;
    dispatch({ type: "start" });
    let failed = 0;
    const readAt = (aid: string) => {
      const landed = qc.getQueryState(countKey(aid))?.dataUpdatedAt ?? 0;
      const asked = askedAt(qc).get(aid);
      return asked === undefined ? landed : Math.min(landed, asked);
    };
    const targets = markAllTargets(liveIds, (aid) => qc.getQueryData<number>(countKey(aid)), readAt, lastNotifArrival());
    try {
      for (const id of targets) {
        if (!(await markOfNotifsRead(id))) failed++;
      }
    } finally {
      running.current = false;
      dispatch({ type: "done", failed, of: targets.length });
    }
    return failed === 0;
  }, [qc, markOfNotifsRead]);
  return { marking, markAll, status };
}

export function useMarkNotifsReadOnce(accountId: string | null, ready: boolean, reread: QueryKey) {
  const qc = useQueryClient();
  const mark = useMarkOfNotifsRead();
  const done = useRef(new Set<string>());
  useEffect(() => {
    if (!ready || !accountId || done.current.has(accountId)) return;
    done.current.add(accountId);
    void mark(accountId).then((ok) => {
      if (ok) void qc.invalidateQueries({ queryKey: reread, exact: true });
    });
  }, [ready, accountId, mark, qc, reread]);
}
