"use client";


import { useCallback, useMemo } from "react";
import { useQueries, useQueryClient } from "@tanstack/react-query";

import { relay, type OFChatItem } from "@/lib/relay";
import { compareFanIds, type FanId } from "@/lib/fanId";

export interface FanSpend {
  spend_cents: number;
  expired_at: string | null;
  subscription_status: string | null;
}

export interface SpendBatchResp {
  spend: Record<string, {
    spend_cents: number;
    last_purchase_at: string | null;
    subscription_status: string | null;
    expired_at: string | null;
  }>;
}

const CHUNK = 200;
const DAY_MS = 24 * 60 * 60 * 1000;

function chunk<T>(arr: T[], size: number): T[][] {
  const out: T[][] = [];
  for (let i = 0; i < arr.length; i += size) out.push(arr.slice(i, i + size));
  return out;
}

interface SpendGroup { accountId: string; key: string }

function spendGroupsSig(rows: OFChatItem[]): string {
  const byAcct = new Map<string, Set<FanId>>();
  for (const r of rows) {
    const aid = r.__accountId;
    if (!aid) continue;
    if (!byAcct.has(aid)) byAcct.set(aid, new Set());
    byAcct.get(aid)!.add(r.withUser.id);
  }
  const lines: string[] = [];
  for (const [aid, idSet] of byAcct) {
    // Sorted so one set always yields the same keys; not `a - b`, NaN on a snowflake id.
    for (const c of chunk(Array.from(idSet).sort(compareFanIds), CHUNK)) {
      lines.push(`${aid}\t${c.join(",")}`);
    }
  }
  return lines.join("\n");
}

function useSpendGroups(rows: OFChatItem[]): SpendGroup[] {
  const sig = spendGroupsSig(rows);
  return useMemo(() => (sig ? sig.split("\n") : []).map((line) => {
    const [accountId, key] = line.split("\t");
    return { accountId, key };
  }), [sig]);
}

function spendBatchQuery(g: SpendGroup) {
  return {
    queryKey: ["fan-spend", g.accountId, g.key] as const,
    queryFn: () => {
      const qs = new URLSearchParams({ ids: g.key });
      return relay.get<SpendBatchResp>(`/admin/fans/${g.accountId}/spend-batch?${qs.toString()}`);
    },
    refetchOnWindowFocus: false,
  };
}

// One select per account for the module's life: a fresh select/Map each render re-renders the observer in a loop.
const selectByAccount = new Map<string, (resp: SpendBatchResp) => Map<string, FanSpend>>();
function selectSpendFor(accountId: string) {
  let fn = selectByAccount.get(accountId);
  if (!fn) {
    fn = (resp) => {
      const m = new Map<string, FanSpend>();
      for (const [fidStr, entry] of Object.entries(resp.spend ?? {})) {
        m.set(`${accountId}:${fidStr}`, {
          spend_cents: entry.spend_cents,
          expired_at: entry.expired_at,
          subscription_status: entry.subscription_status,
        });
      }
      return m;
    };
    selectByAccount.set(accountId, fn);
  }
  return fn;
}

function combineSpend(
  results: Array<{ data?: Map<string, FanSpend>; isFetching: boolean; isPending: boolean }>,
): { spend: Map<string, FanSpend>; settled: boolean; loaded: boolean } {
  const spend = new Map<string, FanSpend>();
  for (const r of results) {
    if (!r.data) continue;
    for (const [k, v] of r.data) spend.set(k, v);
  }
  return {
    spend,
    settled: results.every((r) => !r.isFetching && !r.isPending),
    loaded: results.every((r) => !r.isPending),
  };
}

export function useFanSpendBatch(
  rows: OFChatItem[],
  { staleTime, persist }: { staleTime: number; persist: boolean },
): {
  spend: Map<string, FanSpend>;
  settled: boolean;
  loaded: boolean;
  refetch: (accountIds?: ReadonlySet<string>) => Promise<unknown>;
} {
  const qc = useQueryClient();
  const groups = useSpendGroups(rows);
  const { spend, settled, loaded } = useQueries({
    queries: groups.map((g) => ({
      ...spendBatchQuery(g),
      staleTime,
      meta: { persist },
      select: selectSpendFor(g.accountId),
    })),
    combine: combineSpend,
  });
  const refetch = useCallback(
    (accountIds?: ReadonlySet<string>) => Promise.all(
      groups
        .filter((g) => !accountIds || accountIds.has(g.accountId))
        .map((g) => qc.refetchQueries({ queryKey: spendBatchQuery(g).queryKey, exact: true })),
    ),
    [qc, groups],
  );
  return { spend, settled, loaded, refetch };
}

export function useFanSpend(rows: OFChatItem[]): { spend: Map<string, FanSpend>; loaded: boolean } {
  return useFanSpendBatch(rows, { staleTime: DAY_MS, persist: true });
}
