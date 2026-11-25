"use client";


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

export function rosterCountsKey(principalId: string): readonly [string, string] {
  return ["roster-counts", principalId] as const;
}

const rosterPollNeeded = (rows: readonly SeedRow[]) =>
  rows.some((r) => r.freshness?.values.unread_total == null);

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

const inFlightRefresh = new Map<string, Promise<void>>();

export function resetRosterCountsModuleState() {
  inFlightRefresh.clear();
}

export interface RosterCountActions {
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
        // A full read in flight may have been served before the bust: cancel so it cannot land after it.
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
