"use client";

/**
 * useOfReadGate — lib/ofReadGate.ts in React, for the money rail, the bell and the count readers: returns each target
 * Creator's gate (`off` / `once` / `live`) from this tab's lease (lib/viewLease `tabLease`) and the armed set. It arms
 * the targets this tab leases, and on a lease gain or a selection refetches, under each of `roots`
 * (`[root, accountId, …]` keys), the target's active queries older than REFRESH_OLDER_MS. It starts from no lease:
 * on mount every Creator the tab leases counts as a gain.
 */

import { useCallback, useEffect, useRef, useSyncExternalStore } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { armedVersion, armRead, gainedOf, isArmed, onArmed, readGate, wantsRefresh, type ReadGate } from "@/lib/ofReadGate";
import { NO_TAB_LEASE, onTabLease, tabLease, type TabLease } from "@/lib/viewLease";

const serverLease = () => NO_TAB_LEASE;
const serverVersion = () => 0;

export function useOfReadGate(accountIds: readonly string[], roots: readonly string[]): (accountId: string) => ReadGate {
  const lease = useSyncExternalStore(onTabLease, tabLease, serverLease);
  const version = useSyncExternalStore(onArmed, armedVersion, serverVersion);
  const qc = useQueryClient();
  const prev = useRef<TabLease>(NO_TAB_LEASE);
  const targetKey = accountIds.join("\n");
  const rootKey = roots.join("\n");

  useEffect(() => {
    const before = prev.current;
    prev.current = lease;
    const targets = new Set(targetKey ? targetKey.split("\n") : []);
    for (const aid of lease.leased) if (targets.has(aid)) armRead(aid);
    const now = Date.now();
    for (const aid of gainedOf(before, lease)) {
      if (!targets.has(aid)) continue;
      for (const root of rootKey.split("\n")) {
        void qc.refetchQueries(
          { queryKey: [root, aid], type: "active", predicate: (q) => wantsRefresh(q.state.dataUpdatedAt, now) },
          { cancelRefetch: false },
        );
      }
    }
  }, [lease, targetKey, rootKey, qc]);

  return useCallback(
    (accountId: string) => readGate({ leased: lease.leased.has(accountId), armed: isArmed(accountId) }),
    // `version` changes on every arm and at the deadline.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [lease, version],
  );
}
