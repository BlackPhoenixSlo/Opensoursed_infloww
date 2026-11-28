"use client";


import { useMemo } from "react";
import { useQueries, type Query } from "@tanstack/react-query";

import { useAccounts } from "@/hooks/useAccounts";
import { accountCan } from "@/lib/platform";
import { relay } from "@/lib/relay";

export interface TransactionRow {
  amount?: number;
  net?: number;
  createdAt?: string;
  user?: { id?: number };
  id?: string;
  description?: string;
  status?: string;
}
interface TransactionsResp { list?: TransactionRow[]; hasMore?: boolean }

const PAGE_SIZE = 50;
const MAX_PAGES = 1;

async function fetchAllPages(accountId: string): Promise<TransactionRow[]> {
  const all: TransactionRow[] = [];
  for (let page = 0; page < MAX_PAGES; page++) {
    const resp = await relay.get<TransactionsResp>(
      `/api/of/v2/payouts/transactions?limit=${PAGE_SIZE}&offset=${page * PAGE_SIZE}`,
      { accountId },
    );
    const rows = resp.list ?? [];
    all.push(...rows);
    if (!resp.hasMore || rows.length < PAGE_SIZE) break;
  }
  return all;
}

// Tips start differently, so they never count as PPV.
const PPV_PREFIXES = ["Payment for message from ", "Message from "];
const REVERSED_STATUSES = new Set(["undo", "pending_return"]);

function isPpvPurchase(row: TransactionRow): boolean {
  const d = row.description ?? "";
  return PPV_PREFIXES.some((p) => d.startsWith(p)) && !REVERSED_STATUSES.has(row.status ?? "");
}

export interface FanActivity {
  lastPurchase: Map<string, string>;
  recentSpend: Map<string, number>;
  lastPpvPurchase: Map<string, string>;
}

export function useFanActivity(accountIds: string[]): FanActivity & { loaded: boolean } {
  const accountsQ = useAccounts();
  const roster = accountsQ.data;
  const waiting = accountsQ.isLoading;
  const ids = useMemo(() => {
    if (waiting) return [];
    const known = [...(roster?.accounts ?? []), ...(roster?.watchers ?? [])];
    return accountIds.filter((id) => accountCan(known, id, "fan_activity"));
  }, [accountIds, roster, waiting]);
  const queries = useQueries({
    queries: ids.map((aid) => ({
      queryKey: ["last-purchases", aid] as const,
      enabled: !!aid,
      staleTime: 24 * 60 * 60_000,
      gcTime: 24 * 60 * 60_000,
      refetchOnMount: (q: Query<TransactionRow[]>) => q.state.isInvalidated,
      refetchOnWindowFocus: false,
      refetchOnReconnect: false,
      queryFn: () => fetchAllPages(aid),
    })),
  });

  const updatedKey = queries.map((q) => q.dataUpdatedAt).join("|");
  const loaded = !waiting && queries.every((q) => !q.isPending);
  return useMemo(
    () => ({ ...fanActivityFrom(ids.map((aid, i) => [aid, queries[i]?.data] as const)), loaded }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [updatedKey, ids, loaded],
  );
}

export function fanActivityFrom(
  feeds: ReadonlyArray<readonly [string, TransactionRow[] | undefined]>,
): FanActivity {
  const lastPurchase = new Map<string, string>();
  const recentSpend = new Map<string, number>();
  const lastPpvPurchase = new Map<string, string>();
  for (const [aid, rows] of feeds) {
    if (!aid || !rows) continue;
    for (const row of rows) {
      const uid = row.user?.id;
      if (!uid) continue;
      const ts = row.createdAt;
      const amount = typeof row.amount === "number" ? row.amount : (row.net ?? 0);
      if (amount <= 0) continue;
      const key = `${aid}:${uid}`;
      if (ts && !lastPurchase.has(key)) lastPurchase.set(key, ts);
      if (ts && !lastPpvPurchase.has(key) && isPpvPurchase(row)) lastPpvPurchase.set(key, ts);
      recentSpend.set(key, (recentSpend.get(key) ?? 0) + Math.round(amount * 100));
    }
  }
  return { lastPurchase, recentSpend, lastPpvPurchase };
}

export function useLastPurchases(accountIds: string[]): Map<string, string> {
  return useFanActivity(accountIds).lastPurchase;
}
