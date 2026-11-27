"use client";


import {
  QueryClient,
  QueryClientProvider,
  IsRestoringProvider,
} from "@tanstack/react-query";
import { ReactQueryDevtools } from "@tanstack/react-query-devtools";
import { useEffect, useMemo, useState } from "react";

import { UserProvider } from "@/contexts/UserContext";
import { ChatterProvider } from "@/contexts/ChatterContext";
import { EmployeeProvider } from "@/contexts/EmployeeContext";
import { ScopeProvider, useDropWatcherScope } from "@/contexts/ScopeContext";
import { useWatcherAccounts } from "@/hooks/useAccounts";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { installGlobalErrorHandlers } from "@/lib/errorReporter";
import { perfBoot } from "@/lib/perfLog";
import { registerImageSW } from "@/lib/registerImageSW";
import { listenNotificationClicks } from "@/lib/webPush";
import { createIdbPersister, LEGACY_LOCALSTORAGE_KEY, persistQueryClientLazily } from "@/lib/rqPersister";
import { onScreenRefreshed } from "@/lib/screenBundle";
import { THREAD_KEEP, trimThread } from "@/lib/threadCache";
import { STALE_CELL_GEN_EVENT, chatListRetry, type OFMessage } from "@/lib/relay";

// Bump when the persisted cache shape changes, else old snapshots render as garbage.
const CACHE_BUSTER = "v3.4";
// snapshot cap: 30d so a two-week vacation does not drop everything; the per-query window below sets freshness
const PERSIST_MAX_AGE = 30 * 24 * 60 * 60 * 1000;
const PER_QUERY_MAX_IDLE_MS = 7 * 24 * 60 * 60 * 1000;
const PERSIST_THROTTLE_MS = 4_000;
// threads are most of the snapshot (~100KB each incl. media): keep only the most recently used
const PERSIST_MAX_THREADS = 30;

// Answers depending on who is signed in carry the principal in their key: a stale tab of the previous login cannot write into the next login's entry
const PERSIST_KEYS: ReadonlyArray<readonly string[]> = [
  ["chats"],
  ["chat-folders"],
  ["messages"],
  ["of-me"],
  ["of-user"],
  ["vault-lists"],
  ["vault-history"],
  ["wall-media"],
  ["templates"],
  ["saved-replies"],
  ["fan"],
  ["fan-spend"],
  ["fan-chat-media"],
  ["last-purchases"],
  ["employees"],
  ["accounts"],
  ["chatter"],
  ["applied-settings"],
  ["dashboard", "revenue-by-kind"],
  ["dashboard", "revenue-reversed-by-kind"],
  ["of-profile"],
  ["of-sub-counts"],
  ["of-new-fans"],
  ["of-notif-count"],
];

export function shouldPersistKey(queryKey: readonly unknown[]): boolean {
  return PERSIST_KEYS.some((p) => p.every((seg, i) => queryKey[i] === seg));
}

function DropWatcherScope() {
  const watchers = useWatcherAccounts();
  const ids = useMemo(() => watchers.map((w) => w.id), [watchers]);
  useDropWatcherScope(ids);
  return null;
}

export default function Providers({ children }: { children: React.ReactNode }) {
  // lazy init: StrictMode would re-create the client every render and lose in-flight cache
  const [queryClient] = useState(() => {
    const qc = new QueryClient({
      defaultOptions: {
        queries: {
          // chatters re-open tabs across days; per-query overrides where freshness matters
          staleTime: 3 * 24 * 60 * 60 * 1000,
          gcTime:    7 * 24 * 60 * 60 * 1000,
          refetchOnWindowFocus: false,
          retry: 1,
        },
        mutations: {
          retry: 0,
        },
      },
    });
    qc.setQueryDefaults(["chats"], { retry: chatListRetry });
    return qc;
  });

  // true until the IndexedDB restore ends: otherwise queries race it and refetch what is already persisted
  const [isRestoring, setIsRestoring] = useState(true);

  useEffect(() => {
    installGlobalErrorHandlers();
    registerImageSW();
    const unlistenPush = listenNotificationClicks();
    perfBoot();
    return unlistenPush;
  }, []);

  useEffect(() => onScreenRefreshed((queryKey) => { void queryClient.invalidateQueries({ queryKey }); }), [queryClient]);

  useEffect(() => {
    const refetch = (event: Event) => {
      const reason = (event as CustomEvent).detail?.reason;
      if (!reason || reason === "stale") void queryClient.invalidateQueries({ refetchType: "active" });
    };
    window.addEventListener(STALE_CELL_GEN_EVENT, refetch);
    return () => window.removeEventListener(STALE_CELL_GEN_EVENT, refetch);
  }, [queryClient]);

  useEffect(() => {
    if (typeof window === "undefined") {
      setIsRestoring(false);
      return;
    }
    const lastUsed = new Map<string, number>();
    const queryCache = queryClient.getQueryCache();
    for (const q of queryCache.getAll()) {
      lastUsed.set(q.queryHash, q.state.dataUpdatedAt || Date.now());
    }
    // the restore's thread trim is not a use: it must not reorder the MRU ranking that picks persisted threads
    let trimming = false;
    const unsubLastUsed = queryCache.subscribe((event) => {
      if (trimming) return;
      // observerAdded = read from cache (dataUpdatedAt does not bump on reads), updated = fetch/set
      if (event.type === "observerAdded" || event.type === "updated") {
        lastUsed.set(event.query.queryHash, Date.now());
      } else if (event.type === "removed") {
        lastUsed.delete(event.query.queryHash);
      }
    });

    // the old localStorage copy could pin the origin at its ~5MB quota and starve every other localStorage write
    try { window.localStorage.removeItem(LEGACY_LOCALSTORAGE_KEY); } catch { }
    const usedAt = (q: { queryHash: string; state: { dataUpdatedAt: number } }) =>
      lastUsed.get(q.queryHash) ?? q.state.dataUpdatedAt;
    const [unsubscribe, restorePromise] = persistQueryClientLazily({
      queryClient,
      persister: createIdbPersister(),
      maxAge: PERSIST_MAX_AGE,
      buster: CACHE_BUSTER,
      throttleMs: PERSIST_THROTTLE_MS,
      dehydrateOptions: () => {
        const keptThreads = new Set(
          queryCache.findAll({ queryKey: ["messages"], predicate: (q) => q.state.status === "success" })
            .sort((a, b) => usedAt(b) - usedAt(a))
            .slice(0, PERSIST_MAX_THREADS)
            .map((q) => q.queryHash),
        );
        const now = Date.now();
        return {
          shouldDehydrateQuery: (q) => {
            if (q.state.status !== "success") return false;
            if (!shouldPersistKey(q.queryKey)) return false;
            if (q.meta?.persist === false) return false;
            if (q.queryKey[0] === "messages" && !keptThreads.has(q.queryHash)) return false;
            return now - usedAt(q) < PER_QUERY_MAX_IDLE_MS;
          },
        };
      },
    });
    const restored = () => setIsRestoring(false);
    const trimRestored = () => {
      trimming = true;
      try {
        for (const q of queryCache.findAll({ queryKey: ["messages"] })) {
          const list = q.state.data;
          if (!Array.isArray(list)) continue;
          const next = trimThread(list as OFMessage[], THREAD_KEEP);
          if (next !== list) queryClient.setQueryData(q.queryKey, next, { updatedAt: q.state.dataUpdatedAt });
        }
      } finally {
        trimming = false;
      }
    };
    // threads persisted before trimming existed come back whole (one scroll-up reopened ~5,000 rows): trim before observers are told
    restorePromise.then(() => {
      try { trimRestored(); } catch { }
      restored();
    }, restored);
    return () => {
      unsubLastUsed();
      unsubscribe();
    };
  }, [queryClient]);

  return (
    <QueryClientProvider client={queryClient}>
      <IsRestoringProvider value={isRestoring}>
        <UserProvider>
          <ChatterProvider>
            <EmployeeProvider>
              <ScopeProvider>
                <DropWatcherScope />
                <ErrorBoundary scope="root">{children}</ErrorBoundary>
              </ScopeProvider>
            </EmployeeProvider>
          </ChatterProvider>
        </UserProvider>
      </IsRestoringProvider>
      <ReactQueryDevtools initialIsOpen={false} buttonPosition="bottom-left" />
    </QueryClientProvider>
  );
}
