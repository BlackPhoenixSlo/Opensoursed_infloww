"use client";

/**
 * useRosterCounts — per-model inbox badge counts for the left roster strip.
 *
 *   • unread    → number of CONVERSATIONS with unread messages (blue badge:
 *                 fans waiting to be read).
 *   • owe_reply → conversations READ but the fan spoke last, i.e. we owe a
 *                 reply (orange badge: seen, not yet answered).
 *
 * Backed by GET /admin/accounts/roster-counts, scoped to the signed-in
 * principal. Both principals get badges: an owner sees its own models, a
 * chatter sees the union across every linked owner (the same set its roster
 * strip already renders). The Relay's answer is cached as is: the tab keeps no
 * count of its own. Polls every 5 min (60s while SSE is down) only while some
 * Creator has no live `unread_total` slot: with every
 * slot present the snapshot, the Badge version, mount and the SSE reconnect
 * keep it fresh.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { eventBus, ssePoll } from "@/lib/events";
import { relay } from "@/lib/relay";
import { useOptionalUser } from "@/contexts/UserContext";
import { useOptionalChatter } from "@/contexts/ChatterContext";
import { usePrincipalId } from "@/hooks/useEmployeeKey";
import { ownerAccountsQuery } from "@/lib/ownerAccounts";
import { chatterAccountsQuery, chatterSeedRows } from "@/lib/chatterAccounts";
import { useCreatorFreshnessState } from "@/hooks/useCreatorFreshness";
import { redCircle, shownUnread } from "@/components/chat/redCircle";
import type { SeedRow } from "@/lib/creatorFreshness";

export interface RosterCount {
  unread: number;
  owe_reply: number;
}

export interface RosterCountsResp {
  counts: Record<string, RosterCount>;
}

const EMPTY: Record<string, RosterCount> = {};

/** Per-principal cache key. An owner's counts must never bleed into a chatter's
 *  view (or vice-versa) on an identity switch in the same browser. */
export function rosterCountsKey(principalId: string): readonly [string, string] {
  return ["roster-counts", principalId] as const;
}

const rosterPollNeeded = (rows: readonly SeedRow[]) =>
  rows.some((r) => r.freshness?.values.unread_total == null);

/** Read from the principal's accounts answer, never fetched here; no answer yet polls. */
function useRosterPollNeeded(chatterOnly: boolean, userId: string | undefined): boolean {
  const owner = useQuery({ ...ownerAccountsQuery(userId), enabled: false, select: (d) => rosterPollNeeded(d.accounts) });
  const chatter = useQuery({
    ...chatterAccountsQuery, enabled: false, select: (d) => rosterPollNeeded(chatterSeedRows(d)),
  });
  return (chatterOnly ? chatter.data : owner.data) ?? true;
}

export function useRosterCounts(): Record<string, RosterCount> {
  const { counts } = useRosterCountsRead();
  const freshness = useCreatorFreshnessState();
  const [reachable, setReachable] = useState(() => eventBus.isConnected());
  useEffect(() => eventBus.onStateChange(setReachable), []);
  return useMemo(() => {
    if (!reachable) return counts;
    const display = { ...counts };
    for (const [id, snapshot] of Object.entries(freshness)) {
      const slot = snapshot.values.unread_total;
      if (!slot) continue;
      const fallback = counts[id];
      const unread = shownUnread(redCircle(slot, true, fallback?.unread, true));
      display[id] = { unread, owe_reply: slot.amber ?? fallback?.owe_reply ?? 0 };
    }
    return display;
  }, [counts, freshness, reachable]);
}

/** The counts, and whether their first read is over (answered, failed, or
 *  never asked: no principal) — before it, every count reads 0. */
export function useRosterCountsRead(): { counts: Record<string, RosterCount>; settled: boolean } {
  const user = useOptionalUser()?.user;
  const chatter = useOptionalChatter()?.chatter;
  const principalId = usePrincipalId();
  const poll = useRosterPollNeeded(!user && !!chatter, user?.user_id);

  const q = useQuery<RosterCountsResp>({
    queryKey: rosterCountsKey(principalId),
    queryFn: () => relay.get<RosterCountsResp>("/admin/accounts/roster-counts"),
    enabled: !!user || !!chatter,
    refetchInterval: poll ? ssePoll(5 * 60_000, 60_000) : false,
    staleTime: 30_000,
    refetchOnWindowFocus: false,
  });

  return { counts: q.data?.counts ?? EMPTY, settled: !q.isPending || q.fetchStatus === "idle" };
}

// Module scope: every useRosterCountActions() instance (strip, chat surface, hover) shares one bust per Creator.
const inFlightRefresh = new Map<string, Promise<void>>();

/** Tests only: forget in-flight busts, so one case's bust cannot swallow the next's. */
export function resetRosterCountsModuleState() {
  inFlightRefresh.clear();
}

export interface RosterCountActions {
  /** Rewarm this ONE Creator's count (`?bust=`, under the Relay's shared Hover cooldown) and write its answer as
   *  is. Concurrent calls for one Creator share one request. */
  refreshOne: (accountId: string) => Promise<void>;
}

export function useRosterCountActions(): RosterCountActions {
  const qc = useQueryClient();
  const principalId = usePrincipalId();

  const refreshOne = useCallback<RosterCountActions["refreshOne"]>(
    async (accountId) => {
      if (!accountId) return;
      const cacheKey = `${principalId}:${accountId}`;
      const pending = inFlightRefresh.get(cacheKey);
      if (pending) return pending;
      const run = (async () => {
        // A full read in flight may have been served before the bust: cancelled, so it cannot land after it.
        await qc.cancelQueries({ queryKey: rosterCountsKey(principalId) });
        try {
          const resp = await relay.get<RosterCountsResp>(
            `/admin/accounts/roster-counts?bust=${encodeURIComponent(accountId)}`,
          );
          const fresh = resp?.counts?.[accountId];
          if (fresh) {
            qc.setQueryData<RosterCountsResp>(rosterCountsKey(principalId), (old) => ({
              counts: { ...old?.counts, [accountId]: fresh },
            }));
          }
        } catch {
          // Best-effort: the next snapshot, Badge version or mount read brings the Relay's count.
        }
      })();
      inFlightRefresh.set(cacheKey, run);
      try {
        await run;
      } finally {
        inFlightRefresh.delete(cacheKey);
      }
    },
    [qc, principalId],
  );

  return { refreshOne };
}
