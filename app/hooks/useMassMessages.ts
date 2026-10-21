"use client";

/**
 * useMassMessages — list + cancel past mass-message broadcasts.
 *
 * Reads from the relay's local SQLite cache (`mass_broadcast_cache`) via
 * `/admin/mass-messages` for a snappy first render. The Refresh button
 * triggers POST `/admin/mass-messages/refresh`, which pulls from OF +
 * upserts the cache + returns the fresh rows in one roundtrip.
 *
 * The previous live-OF passthrough (`/api/of/v2/users/me/stats/messages/group`)
 * still works and write-throughs into the same cache — used as a fallback
 * if the DB is empty on first ever visit (no cached rows yet).
 *
 * Each row stamped with `__accountId` so cancel routes through the
 * right session.
 */

import {
  useMutation,
  useQueries,
  useQueryClient,
  type QueryClient,
  type UseQueryResult,
} from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { eventBus, type EventEnvelope } from "@/lib/events";
import { relay, type VaultFiles } from "@/lib/relay";

const KEY_PREFIX = "mass-messages";

export interface MassMessageRow {
  id: number;
  date?: string | null;
  text?: string | null;
  rawText?: string | null;
  giphyId?: string | null;
  isFree?: boolean;
  isTip?: boolean;
  mediaCount?: number;
  media?: Array<{
    id: number;
    type?: string;
    files?: VaultFiles | null;
  }>;
  previews?: number[];
  sentCount?: number;
  viewedCount?: number;
  isCanceled?: boolean;
  canUnsend?: boolean;
  unsendSeconds?: number | null;
  template?: string | null;
  fetched_at?: string | null;
  /** Which automation produced this broadcast (joined via mass_runs.queue_id).
   *  null = a manual UI broadcast or a pre-0032 run. */
  automationKind?: string | null;
  /** Funnel/campaign name when the broadcast ran a funnel. */
  funnelName?: string | null;
  /** Buyers and their sum (cents, at the copy's price) from OUR rows of this
   *  broadcast's copies — no OF read; a floor for a list-audience blast. */
  purchasedCount?: number;
  earningsCents?: number;
  __accountId?: string;
}

interface AdminListResp {
  account_id: string;
  days_back: number;
  items: MassMessageRow[];
}

interface AdminRefreshResp extends AdminListResp {
  written: number;
}

export interface MassMessagesOptions {
  daysBack?: number;
  limit?: number;
}

async function fetchCached(accountId: string, daysBack: number, limit: number): Promise<MassMessageRow[]> {
  const qs = new URLSearchParams({
    account_id: accountId,
    days_back: String(daysBack),
    limit: String(limit),
  });
  const resp = await relay.get<AdminListResp>(`/admin/mass-messages?${qs.toString()}`);
  return (resp.items ?? []).map((it) => ({ ...it, __accountId: accountId }));
}

/** Flatten + sort the per-account rows inside `useQueries`' `combine`, which
 *  re-runs only when a query result changes and structurally shares its
 *  output, so `rows` keeps its reference across renders. Module-level so the
 *  function reference is stable. (A `useMemo` keyed on `queries.map(q =>
 *  q.data)` broke on a cold load: that list is empty while the Creators load,
 *  React compares only the old length, so the memo never recomputed.) */
function combineQueries(queries: UseQueryResult<MassMessageRow[]>[]) {
  const rows = queries
    .flatMap((q) => q.data ?? [])
    .sort((a, b) => {
      const ta = a.date ? new Date(a.date).getTime() : 0;
      const tb = b.date ? new Date(b.date).getTime() : 0;
      return tb - ta;
    });
  return { queries, rows };
}

export function useMassMessages(accountIds: string[], opts: MassMessagesOptions = {}) {
  const daysBack = opts.daysBack ?? 30;
  const limit = opts.limit ?? 100;

  const { queries, rows } = useQueries({
    queries: accountIds.map((accountId) => ({
      queryKey: [KEY_PREFIX, accountId, daysBack, limit] as const,
      queryFn: () => fetchCached(accountId, daysBack, limit),
      // Cache is local SQLite — practically instant + cheap to re-read,
      // but we still get React Query's de-duplication across mounts.
      staleTime: 5 * 60 * 1000,   // 5min before considered stale
      gcTime: 30 * 60 * 1000,     // keep in memory across nav for 30min
      refetchOnWindowFocus: false,
      // Hold the previously-rendered rows during refetch/key-change so
      // the list doesn't flicker to empty when `daysBack` changes.
      placeholderData: (prev: MassMessageRow[] | undefined) => prev,
    })),
    combine: combineQueries,
  });

  const isLoading = queries.some((q) => q.isLoading);
  const isFetching = queries.some((q) => q.isFetching);
  const error = queries.find((q) => q.error)?.error as Error | undefined;

  return { rows, isLoading, isFetching, error, queries, daysBack, limit };
}

/** Pull one account's broadcasts from OF into the relay's cache. */
async function refreshAccount(accountId: string, daysBack: number, limit: number): Promise<number> {
  const qs = new URLSearchParams({
    account_id: accountId,
    days_back: String(daysBack),
    limit: String(limit),
  });
  const resp = await relay.post<AdminRefreshResp>(`/admin/mass-messages/refresh?${qs.toString()}`, undefined);
  return resp.written;
}

/** Hit OF + upsert into the cache for every account, then invalidate
 *  the read queries so they pick up the fresh rows. One mutation call
 *  fans out to N accounts. */
export function useRefreshMassMessages() {
  const qc = useQueryClient();
  return useMutation<
    { accountId: string; written: number }[],
    Error,
    { accountIds: string[]; daysBack: number; limit?: number }
  >({
    mutationFn: async ({ accountIds, daysBack, limit = 100 }) => {
      const results = await Promise.all(
        accountIds.map(async (accountId) => ({
          accountId,
          written: await refreshAccount(accountId, daysBack, limit),
        })),
      );
      return results;
    },
    onSuccess: (_data, vars) => {
      // Invalidate every per-account list query; React Query will
      // refetch from the DB and pick up the new rows.
      vars.accountIds.forEach((accountId) => {
        qc.invalidateQueries({ queryKey: [KEY_PREFIX, accountId] });
      });
    },
  });
}

/** A broadcast OF is still delivering: its queue id and Creator. */
export interface MassQueueSending {
  queueId: number;
  accountId: string;
}

interface QueueFrame {
  id?: number;
  isCanceled?: boolean;
}

/**
 * The listed Creators' broadcasts OF is still delivering (`chat_queue_update` / `chat_queue_finish` SSE frames,
 * service/events.py). A sent broadcast is not in the cache until OF lists it, so the in-flight ones come back here
 * rather than as rows; the finish frame drops it and refreshes that Creator's list from OF, so the new row lands with
 * its sent count. No count while sending: an update frame's `total` and `pending` are not trustworthy (the first
 * carries `total: -1`), only the finish frame's, and the refreshed row shows that. A cancelled queue is dropped, and
 * so is everything on a `resync` or a lost stream, since a finish frame may have been missed.
 */
export function useMassQueueProgress(accountIds: string[], daysBack: number, limit = 100): MassQueueSending[] {
  const qc = useQueryClient();
  const [inFlight, setInFlight] = useState<Map<number, MassQueueSending>>(() => new Map());
  // Read inside the listeners, so a new Creators list or range doesn't resubscribe.
  const scope = useRef({ accountIds, daysBack, limit });
  useEffect(() => {
    scope.current = { accountIds, daysBack, limit };
  });

  useEffect(() => {
    const frameOf = (env: EventEnvelope, type: string) => {
      const accountId = env.__account_id;
      const f = env[type] as QueueFrame | undefined;
      if (!accountId || !scope.current.accountIds.includes(accountId) || typeof f?.id !== "number") return null;
      return { accountId, queueId: f.id, f };
    };
    const drop = (queueId: number) => setInFlight((m) => {
      if (!m.has(queueId)) return m;
      const next = new Map(m);
      next.delete(queueId);
      return next;
    });
    const offUpdate = eventBus.on("chat_queue_update", (env) => {
      const got = frameOf(env, "chat_queue_update");
      if (!got) return;
      if (got.f.isCanceled) return drop(got.queueId);
      setInFlight((m) => (m.has(got.queueId)
        ? m
        : new Map(m).set(got.queueId, { queueId: got.queueId, accountId: got.accountId })));
    });
    const offFinish = eventBus.on("chat_queue_finish", (env) => {
      const got = frameOf(env, "chat_queue_finish");
      if (!got) return;
      drop(got.queueId);
      const { daysBack: days, limit: max } = scope.current;
      void refreshAccount(got.accountId, days, max)
        .catch(() => undefined)
        .then(() => qc.invalidateQueries({ queryKey: [KEY_PREFIX, got.accountId] }));
    });
    const clear = () => setInFlight((m) => (m.size ? new Map() : m));
    const offResync = eventBus.on("resync", clear);
    const offState = eventBus.onStateChange((connected) => { if (!connected) clear(); });
    return () => {
      offUpdate();
      offFinish();
      offResync();
      offState();
    };
  }, [qc]);

  return [...inFlight.values()];
}

export function useCancelMassMessage() {
  const qc = useQueryClient();
  return useMutation<unknown, Error, { id: number; accountId: string }>({
    mutationFn: ({ id, accountId }) =>
      relay.delete(`/api/of/v2/messages/queue/${id}`, { accountId }),
    onSuccess: (_data, { accountId, id }) => {
      // Optimistically flip the row's `isCanceled` so the UI stops
      // showing it as unsendable without waiting for the refetch.
      patchRowInCaches(qc, accountId, id);
      qc.invalidateQueries({ queryKey: [KEY_PREFIX, accountId] });
    },
  });
}

function patchRowInCaches(qc: QueryClient, accountId: string, queueId: number): void {
  qc.getQueryCache()
    .findAll({ queryKey: [KEY_PREFIX, accountId] })
    .forEach((q) => {
      const rows = q.state.data as MassMessageRow[] | undefined;
      if (!rows) return;
      const next = rows.map((r) =>
        r.id === queueId
          ? { ...r, isCanceled: true, canUnsend: false, unsendSeconds: 0 }
          : r,
      );
      qc.setQueryData(q.queryKey, next);
    });
}
