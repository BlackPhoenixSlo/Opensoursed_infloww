"use client";


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
import { CREATOR_POOL, settlePool } from "@/lib/settlePool";

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
  automationKind?: string | null;
  funnelName?: string | null;
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

// Not a useMemo on queries.map(q => q.data): on a cold load that list is empty and React compares only the old length, so it never recomputed.
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
      staleTime: 5 * 60 * 1000,
      gcTime: 30 * 60 * 1000,
      refetchOnWindowFocus: false,
      placeholderData: (prev: MassMessageRow[] | undefined) => prev,
    })),
    combine: combineQueries,
  });

  const isLoading = queries.some((q) => q.isLoading);
  const isFetching = queries.some((q) => q.isFetching);
  const error = queries.find((q) => q.error)?.error as Error | undefined;

  return { rows, isLoading, isFetching, error, queries, daysBack, limit };
}

async function refreshAccount(accountId: string, daysBack: number, limit: number): Promise<number> {
  const qs = new URLSearchParams({
    account_id: accountId,
    days_back: String(daysBack),
    limit: String(limit),
  });
  const resp = await relay.post<AdminRefreshResp>(`/admin/mass-messages/refresh?${qs.toString()}`, undefined);
  return resp.written;
}

export function useRefreshMassMessages() {
  const qc = useQueryClient();
  return useMutation<
    { accountId: string; written: number }[],
    Error,
    { accountIds: string[]; daysBack: number; limit?: number }
  >({
    mutationFn: async ({ accountIds, daysBack, limit = 100 }) => {
      const res = await settlePool(accountIds, CREATOR_POOL, async (accountId) => ({
        accountId,
        written: await refreshAccount(accountId, daysBack, limit),
      }));
      const failed = res.find((r) => r.status === "rejected");
      if (failed) throw failed.reason;
      return res.flatMap((r) => (r.status === "fulfilled" ? [r.value] : []));
    },
    onSuccess: (_data, vars) => {
      vars.accountIds.forEach((accountId) => {
        qc.invalidateQueries({ queryKey: [KEY_PREFIX, accountId] });
      });
    },
  });
}

export interface MassQueueSending {
  queueId: number;
  accountId: string;
}

interface QueueFrame {
  id?: number;
  isCanceled?: boolean;
}

export function useMassQueueProgress(accountIds: string[], daysBack: number, limit = 100): MassQueueSending[] {
  const qc = useQueryClient();
  const [inFlight, setInFlight] = useState<Map<number, MassQueueSending>>(() => new Map());
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
    // No count while sending: an update frame's total/pending are untrustworthy (the first carries total -1).
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
    const clear = (accounts: readonly string[] | null) => setInFlight((m) => {
      const next = new Map([...m].filter(([, q]) => accounts !== null && !accounts.includes(q.accountId)));
      return next.size === m.size ? m : next;
    });
    const offResync = eventBus.on("resync", (env) => clear(Array.isArray(env.accounts) ? env.accounts.map(String) : null));
    const offState = eventBus.onStreamState((c) => { if (!c.connected) clear(c.accounts); });
    return () => {
      offUpdate();
      offFinish();
      offResync();
      offState();
    };
  }, [qc]);

  return [...inFlight.values()];
}

export async function cancelMassMessage(
  qc: QueryClient,
  { id, accountId }: { id: number; accountId: string },
): Promise<unknown> {
  const res = await relay.delete(`/api/of/v2/messages/queue/${id}`, { accountId });
  patchRowInCaches(qc, accountId, id);
  qc.invalidateQueries({ queryKey: [KEY_PREFIX, accountId] });
  return res;
}

export function useCancelMassMessage() {
  const qc = useQueryClient();
  return useMutation<unknown, Error, { id: number; accountId: string }>({
    mutationFn: (vars) => cancelMassMessage(qc, vars),
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
