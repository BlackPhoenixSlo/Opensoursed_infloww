"use client";

/**
 * The tab's per-Creator Freshness store (lib/creatorFreshness.ts) in React Query: the entry
 * `["creator-freshness", principalId]`, written only through `dispatchCreatorFreshness` (useAccounts' seed,
 * useAccountStateEvents' `creator_refreshed`), never persisted (not in providers' PERSIST_KEYS), never fetched.
 * A dispatch that changes nothing writes nothing, so with the Knob off no entry is ever created.
 * `useCreatorFreshness` reads one Creator's held snapshot without creating the entry.
 */

import { useCallback, useSyncExternalStore } from "react";
import { hashKey, useQueryClient, type QueryClient } from "@tanstack/react-query";

import { usePrincipalId } from "@/hooks/useEmployeeKey";
import {
  creatorFreshnessReducer, EMPTY_FRESHNESS, of, type Action, type CreatorFreshnessState, type HeldFreshness,
} from "@/lib/creatorFreshness";

export const creatorFreshnessKey = (principalId: string) => ["creator-freshness", principalId] as const;

/** Run one action through the reducer and store its result (when it changed). The entry lives for the tab
 *  (`gcTime` Infinity): nothing observes it as a query, and a garbage-collected store would forget a newer event. */
export function dispatchCreatorFreshness(qc: QueryClient, principalId: string, action: Action): void {
  const queryKey = creatorFreshnessKey(principalId);
  const held = qc.getQueryData<CreatorFreshnessState>(queryKey) ?? EMPTY_FRESHNESS;
  const next = creatorFreshnessReducer(held, action);
  if (next === held) return;
  qc.getQueryCache().build(qc, qc.defaultQueryOptions({ queryKey, gcTime: Infinity }));
  qc.setQueryData(queryKey, next);
}

/** The whole store (EMPTY_FRESHNESS while nothing is held), re-rendering when it changes. */
export function useCreatorFreshnessState(): CreatorFreshnessState {
  const qc = useQueryClient();
  const queryKey = creatorFreshnessKey(usePrincipalId());
  const hash = hashKey(queryKey);
  const subscribe = useCallback(
    (onChange: () => void) => qc.getQueryCache().subscribe((ev) => { if (ev.query.queryHash === hash) onChange(); }),
    [qc, hash],
  );
  return useSyncExternalStore(
    subscribe,
    () => qc.getQueryData<CreatorFreshnessState>(queryKey) ?? EMPTY_FRESHNESS,
    () => EMPTY_FRESHNESS,
  );
}

/** The Creator's held snapshot (null: none held, e.g. the Knob is off), re-rendering when the store changes. */
export function useCreatorFreshness(accountId: string | null | undefined): HeldFreshness | null {
  const state = useCreatorFreshnessState();
  return accountId ? of(state, accountId) : null;
}
