"use client";


import { useCallback, useRef, useSyncExternalStore } from "react";
import { hashKey, useQueryClient, type QueryClient } from "@tanstack/react-query";

import { usePrincipalId } from "@/hooks/useEmployeeKey";
import * as ageClock from "@/lib/ageClock";
import {
  creatorFreshnessReducer, EMPTY_FRESHNESS, of, type Action, type CreatorFreshnessState, type HeldFreshness,
} from "@/lib/creatorFreshness";

export const creatorFreshnessKey = (principalId: string) => ["creator-freshness", principalId] as const;

export function dispatchCreatorFreshness(qc: QueryClient, principalId: string, action: Action): void {
  const queryKey = creatorFreshnessKey(principalId);
  const held = qc.getQueryData<CreatorFreshnessState>(queryKey) ?? EMPTY_FRESHNESS;
  const next = creatorFreshnessReducer(held, action);
  if (next === held) return;
  // gcTime Infinity: nothing observes the entry, and a collected store would forget a newer event.
  qc.getQueryCache().build(qc, qc.defaultQueryOptions({ queryKey, gcTime: Infinity }));
  qc.setQueryData(queryKey, next);
}

export function useFreshnessSelect<T>(
  select: (state: CreatorFreshnessState | undefined) => T,
  { same = Object.is, clock = false, server }: { same?: (a: T, b: T) => boolean; clock?: boolean; server: T },
): T {
  const qc = useQueryClient();
  const queryKey = creatorFreshnessKey(usePrincipalId());
  const hash = hashKey(queryKey);
  const subscribe = useCallback((onChange: () => void) => {
    const offStore = qc.getQueryCache().subscribe((ev) => { if (ev.query.queryHash === hash) onChange(); });
    const offClock = clock ? ageClock.subscribe(onChange) : () => {};
    return () => { offStore(); offClock(); };
  }, [qc, hash, clock]);
  const last = useRef<{ v: T } | null>(null);
  const snapshot = () => {
    const next = select(qc.getQueryCache().get<CreatorFreshnessState>(hash)?.state.data);
    if (!last.current || !same(last.current.v, next)) last.current = { v: next };
    return last.current.v;
  };
  return useSyncExternalStore(subscribe, snapshot, () => server);
}

export function useCreatorFreshnessState(): CreatorFreshnessState {
  return useFreshnessSelect((s) => s ?? EMPTY_FRESHNESS, { server: EMPTY_FRESHNESS });
}

export function useCreatorFreshness(accountId: string | null | undefined): HeldFreshness | null {
  const state = useCreatorFreshnessState();
  return accountId ? of(state, accountId) : null;
}
