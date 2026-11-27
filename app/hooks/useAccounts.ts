"use client";


import { useContext, useEffect, useMemo, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import type { AccountMeta, WatcherAccount } from "@/lib/relay";
import { useUser } from "@/contexts/UserContext";
import { useChatter } from "@/contexts/ChatterContext";
import { chatterAccountsQuery, chatterSeedRows } from "@/lib/chatterAccounts";
import { ownerAccountsQuery, type AccountsResp } from "@/lib/ownerAccounts";
import { accountPlatform, AllPlatformsContext, usePlatform, type Platform } from "@/lib/platform";
import type { SeedRow } from "@/lib/creatorFreshness";
import { dispatchCreatorFreshness } from "@/hooks/useCreatorFreshness";
import { serverOffset, setRelayOffset } from "@/lib/ageClock";

const PAGE_LOADED_AT = Date.now();

export const fromThisPage = (dataUpdatedAt: number): boolean => dataUpdatedAt >= PAGE_LOADED_AT;

export { fetchAccounts, ownerAccountsQuery, type AccountsResp } from "@/lib/ownerAccounts";

export function useAccounts() {
  const { user } = useUser();
  const { chatter } = useChatter();
  const isChatterOnly = !user && !!chatter;

  const ownerQ = useQuery<AccountsResp>({
    ...ownerAccountsQuery(user?.user_id),
    refetchOnWindowFocus: false,
    // Wait for the principal: fetching while user is null hits the unauthed full-list path and poisons the cache.
    enabled: !isChatterOnly && !!user,
  });

  // /admin/accounts is owner-only (403 under a chatter session).
  const chatterQ = useQuery({
    ...chatterAccountsQuery,
    staleTime: 5 * 60_000,
    refetchOnWindowFocus: false,
    enabled: isChatterOnly,
  });

  const chatterRows: AccountMeta[] = useMemo(() => {
    const rows = chatterQ.data || [];
    return rows.map((r) => ({
      id: r.account_id,
      nickname: r.nickname,
      color: r.color,
      platform: r.platform,
      // has_session=true is an assumption; the paused fields below keep a parked model distinguishable from a working one.
      has_session: true,
      session_dead_at: r.session_dead_at,
      session_dead_reason: r.session_dead_reason,
      is_active: r.is_active,
      role: r.role ?? undefined,
      ...(r.freshness ? { freshness: r.freshness } : {}),
    } as AccountMeta));
  }, [chatterQ.data]);

  const qc = useQueryClient();
  const userId = user?.user_id;
  const principalId = userId ?? chatter?.chatter_id ?? "anon";
  const seedRows: SeedRow[] | null = useMemo(() => {
    if (isChatterOnly) return chatterQ.data ? chatterSeedRows(chatterQ.data) : null;
    return ownerQ.data?.accounts ?? null;
  }, [isChatterOnly, chatterQ.data, ownerQ.data]);
  useEffect(() => {
    const key = isChatterOnly ? chatterAccountsQuery.queryKey : ownerAccountsQuery(userId).queryKey;
    const at = qc.getQueryState(key)?.dataUpdatedAt ?? 0;
    if (!seedRows || !fromThisPage(at)) return;
    const relayNow = Math.max(...seedRows.map((r) => r.freshness?.now ?? -Infinity));
    if (Number.isFinite(relayNow)) setRelayOffset(serverOffset(relayNow, at));
    dispatchCreatorFreshness(qc, principalId, { type: "seeded", rows: seedRows, receivedAt: at });
  }, [qc, principalId, seedRows, isChatterOnly, userId]);
  const seenPrincipal = useRef(principalId);
  useEffect(() => {
    if (seenPrincipal.current === principalId) return;
    dispatchCreatorFreshness(qc, seenPrincipal.current, { type: "identityChanged" });
    seenPrincipal.current = principalId;
  }, [qc, principalId]);

  const chatterData: AccountsResp = useMemo(
    () => ({
      accounts: chatterRows.filter((a) => a.role !== "watcher"),
      active_account_id: null,
      // A granted watcher goes to `watchers`, never a Creator roster.
      watchers: chatterRows.filter((a): a is WatcherAccount => a.role === "watcher"),
    }),
    [chatterRows],
  );
  return useMemo(() => {
    if (isChatterOnly) {
      return { ...chatterQ, data: chatterData };
    }
    return ownerQ;
  }, [isChatterOnly, chatterQ.status, chatterQ.dataUpdatedAt, chatterData, ownerQ]);
}

export function useAccountLabel(accountId?: string | null): string {
  const q = useAccounts();
  const all = q.data?.accounts;
  return useMemo(() => {
    if (!accountId) return "";
    return (all ?? []).find((a) => a.id === accountId)?.nickname || accountId;
  }, [all, accountId]);
}

const NO_WATCHERS: WatcherAccount[] = [];

export function useWatcherAccounts(): WatcherAccount[] {
  return useAccounts().data?.watchers ?? NO_WATCHERS;
}

export const ofManagerWatcher = (w: WatcherAccount): boolean => !!w.has_session && w.is_active;

export function useOfManagerAccounts(): AccountMeta[] {
  const creators = usePlatformAccounts();
  const watchers = useWatcherAccounts();
  return useMemo(() => [...creators, ...watchers.filter(ofManagerWatcher)], [creators, watchers]);
}

export function useActiveAccounts(includePending = false): AccountMeta[] {
  const q = useAccounts();
  const all = q.data?.accounts;
  return useMemo(
    () => (all ?? []).filter((a) => a.is_active && (a.has_session || (includePending && a.rosterPending))),
    [all, includePending],
  );
}

// Platform-selector surfaces only: global listeners (toaster, bell, money rail, inbox realtime) read useActiveAccounts so a Fansly shell still hears OnlyFans.
export function usePlatformAccounts(on?: Platform, includePending = false): AccountMeta[] {
  const accounts = useActiveAccounts(includePending);
  const platform = usePlatform();
  const all = useContext(AllPlatformsContext) && on === undefined;
  const selected = on ?? platform;
  return useMemo(
    () => (all ? accounts : accounts.filter((a) => accountPlatform(a) === selected)),
    [accounts, selected, all],
  );
}

export interface GrowthCreator {
  accounts: AccountMeta[];
  accountId: string | null;
  setAccountId: (id: string) => void;
  loading: boolean;
}

export function useGrowthCreator(): GrowthCreator {
  const accounts = useActiveAccounts();
  const loading = useAccounts().isLoading;
  const [picked, setAccountId] = useState<string | null>(null);
  const accountId = picked ?? accounts[0]?.id ?? null;
  return { accounts, accountId, setAccountId, loading };
}
