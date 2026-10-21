"use client";

/**
 * useFanSpend — bulk lifetime-spend lookup for ChatList row chips.
 *
 * Reads from our local SQLite (`/admin/fans/{aid}/spend-batch`), which the
 * WS pump + event-transcoder keep within seconds of OF for any active fan.
 * This is dramatically faster than the old `/users/list?view=x` round-trip
 * (one SQL query vs N OF API calls) and survives a tab close because the
 * query is persisted by providers.tsx.
 *
 * If a fan has never been touched by the pump (cold-start, brand new fan),
 * the DB returns no row and the spend is unknown: the row shows the photo
 * and no pill — the next chat-list tick will enrich the fan and the WS pump
 * will populate spend on first purchase/tip event.
 *
 * Cap is 200 ids per call (backend enforces); we chunk at 200 to match.
 */

import { useCallback, useMemo } from "react";
import { useQueries, useQueryClient } from "@tanstack/react-query";

import { relay, type OFChatItem } from "@/lib/relay";
import { compareFanIds, type FanId } from "@/lib/fanId";

export interface FanSpend {
  /** Lifetime total in cents. */
  spend_cents: number;
  /** ISO timestamp when the subscription ends, or null. */
  expired_at: string | null;
  /** Subscription status string: "active", "expired", etc. */
  subscription_status: string | null;
}

/** The spend-batch reply cached under `["fan-spend", aid, ids]`. */
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

/** One spend-batch request: an account and up to CHUNK of its fan ids,
 *  comma-joined (`key`). */
interface SpendGroup { accountId: string; key: string }

/** The fan set as `aid\tid,id,…` lines, one per CHUNK-sized group — ids
 *  sorted so the same set always yields the same keys (not `a - b`, which is
 *  NaN on a snowflake — see compareFanIds). */
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
    for (const c of chunk(Array.from(idSet).sort(compareFanIds), CHUNK)) {
      lines.push(`${aid}\t${c.join(",")}`);
    }
  }
  return lines.join("\n");
}

/** `rows` as spend-batch groups. `rows` changes identity on every SSE patch;
 *  the groups only when the fan set does — so query keys stay stable. */
function useSpendGroups(rows: OFChatItem[]): SpendGroup[] {
  const sig = spendGroupsSig(rows);
  return useMemo(() => (sig ? sig.split("\n") : []).map((line) => {
    const [accountId, key] = line.split("\t");
    return { accountId, key };
  }), [sig]);
}

/** The key and fetcher for a group's spend. */
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

// One `select` per account, kept for the module's life: react-query re-runs
// a select whose identity changed on every render, and a fresh Map each time
// re-renders the observer — a loop.
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
): { spend: Map<string, FanSpend>; settled: boolean } {
  const spend = new Map<string, FanSpend>();
  for (const r of results) {
    if (!r.data) continue;
    for (const [k, v] of r.data) spend.set(k, v);
  }
  return { spend, settled: results.every((r) => !r.isFetching && !r.isPending) };
}

/** Spend for `rows`' fans, keyed `aid:fid`, fresh for `staleTime`; `persist`
 *  keeps it in the persisted cache (providers.tsx reads `meta.persist`).
 *    • `settled` — every account's spend query has finished fetching.
 *    • `refetch` — refetch exactly these queries, optionally only
 *      `accountIds`'. Stable while the fan set is.
 *  A re-key keeps showing the same account's previous data until the new key
 *  lands. */
export function useFanSpendBatch(
  rows: OFChatItem[],
  { staleTime, persist }: { staleTime: number; persist: boolean },
): {
  spend: Map<string, FanSpend>;
  settled: boolean;
  refetch: (accountIds?: ReadonlySet<string>) => Promise<unknown>;
} {
  const qc = useQueryClient();
  const groups = useSpendGroups(rows);
  const { spend, settled } = useQueries({
    queries: groups.map((g) => ({
      ...spendBatchQuery(g),
      staleTime,
      meta: { persist },
      // Previous data only from the SAME account.
      placeholderData: (
        prev: SpendBatchResp | undefined,
        prevQuery: { queryKey: readonly unknown[] } | undefined,
      ) => (prevQuery?.queryKey[1] === g.accountId ? prev : undefined),
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
  return { spend, settled, refetch };
}

/** The Fan List chips' spend: 24h fresh (the DB is kept fresh by the WS pump
 *  + transcoder, so no re-fetch on tab focus or interval) and persisted, so
 *  the chip survives a reload. */
export function useFanSpend(rows: OFChatItem[]): Map<string, FanSpend> {
  return useFanSpendBatch(rows, { staleTime: DAY_MS, persist: true }).spend;
}
