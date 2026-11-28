import { useEffect, useReducer } from "react";
import { useInfiniteQuery, useQueryClient, type QueryClient, type QueryKey } from "@tanstack/react-query";

import { relay, RelayError } from "@/lib/relay";

import { afterWatchWrite, leakKeys } from "./leakKeys";

import { RECHECK_FOR_MS, RECHECK_MS, refreshCheck } from "./leakRefresh";
import type { LeakPage, LeakWatchRead } from "./leakView";

export const keyInvalid = (e: unknown) => e instanceof RelayError && e.status === 409
  && (e.body as { detail?: { error?: unknown } } | null)?.detail?.error === "key_invalid";

export async function leakRead<T>(qc: QueryClient, path: string, accountId: string | null): Promise<T> {
  try {
    return await relay.get<T>(path, { accountId });
  } catch (e) {
    if (keyInvalid(e)) void qc.invalidateQueries({ queryKey: leakKeys.setupRoot });
    throw e;
  }
}

const withCursor = (path: string, cursor: string | null) =>
  (cursor ? `${path}${path.includes("?") ? "&" : "?"}cursor=${encodeURIComponent(cursor)}` : path);

export const useLeakPages = <T extends LeakPage>(key: QueryKey, path: string, accountId: string | null,
  enabled = true, poll?: () => number | false) => {
  const qc = useQueryClient();
  return useInfiniteQuery({
    queryKey: key,
    enabled,
    initialPageParam: null as string | null,
    getNextPageParam: (last: T) => last.next_cursor ?? undefined,
    queryFn: ({ pageParam }) => leakRead<T>(qc, withCursor(path, pageParam), accountId),
    // eslint-disable-next-line local/no-fixed-polling -- Tracker scan completion has no SSE event
    refetchInterval: () => poll?.() ?? false,
  });
};

export function useRefreshCheck(creatorId: string, accountId: string | null) {
  const qc = useQueryClient();
  const [state, dispatch] = useReducer(refreshCheck, { phase: "idle" });
  const deadline = state.phase === "checking" ? state.started + RECHECK_FOR_MS : null;
  const watch = useLeakPages<LeakWatchRead>(leakKeys.watch(creatorId, accountId), `/admin/leaks/watches/${creatorId}`,
    accountId, true, () => deadline !== null && deadline - Date.now() > RECHECK_MS ? RECHECK_MS : false);
  const row = watch.data?.pages[0];
  const pending = row?.this_week?.state === "pending";
  const fresh = !!row?.this_week && !row.stale;
  const next = row?.next_refresh_at ?? null;
  const at = watch.dataUpdatedAt;
  const checkedAt = row?.last_checked_at ?? null;
  useEffect(() => {
    dispatch({ type: "read", at, pending, fresh, next, checkedAt });
  }, [at, checkedAt, fresh, next, pending]);
  useEffect(() => {
    if (deadline === null) return;
    const expire = setTimeout(() => dispatch({ type: "expired" }), Math.max(0, deadline - Date.now()));
    return () => clearTimeout(expire);
  }, [deadline]);
  useEffect(() => {
    if (state.phase !== "done") return;
    dispatch({ type: "settled" });
    void afterWatchWrite(qc, creatorId);
  }, [creatorId, qc, state.phase]);

  const expired = state.phase === "expired";
  const checking = !expired && (pending || state.phase === "checking");
  return { watch, checking, expired,
    queued: (next: string, queuedAt: string) => dispatch({ type: "acked", at: Date.now(), next, queuedAt }) };
}
