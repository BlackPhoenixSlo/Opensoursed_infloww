"use client";

/**
 * Top-level client providers. Mounted once in layout.tsx, wraps the
 * entire tree.
 *
 * React Query staleTime/gcTime are already last-access-based; do not add
 * explicit last-used bookkeeping at the query layer.
 *
 * Order matters:
 *
 *   QueryClientProvider — must be outermost so every fetch flows through
 *                         the same cache. Children include the popout
 *                         tab too, which inherits via the IndexedDB
 *                         persister wired below.
 *   IsRestoringProvider — flips queries into "restoring" mode so they
 *                         read from cache but don't fire network until
 *                         the IndexedDB hydrate finishes.
 *   EmployeeProvider    — drives the picker modal + X-Employee-Id header.
 *   ScopeProvider       — passive holder for active scope.
 *
 * QueryClient is created once per browser session via useState's lazy
 * init — Next 16's React 19 strict mode would otherwise re-create it
 * on every render and lose all in-flight cache.
 *
 * **Persistence**: we wire `persistQueryClientLazily` once on mount, which
 * mirrors selected query keys to IndexedDB so popout windows + repeat
 * tab-opens hydrate from disk. We pair it with `IsRestoringProvider` so
 * useQuery hooks DON'T fire network requests during the first render —
 * otherwise they'd race the async restore and the popout tab would
 * re-fetch data that's already sitting in storage. We tracked down
 * this race after pop-out kept reloading vault + messages even though
 * the inbox had already loaded them.
 */

import {
  QueryClient,
  QueryClientProvider,
  IsRestoringProvider,
} from "@tanstack/react-query";
import { ReactQueryDevtools } from "@tanstack/react-query-devtools";
import { useEffect, useState } from "react";

import { UserProvider } from "@/contexts/UserContext";
import { ChatterProvider } from "@/contexts/ChatterContext";
import { EmployeeProvider } from "@/contexts/EmployeeContext";
import { ScopeProvider } from "@/contexts/ScopeContext";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { installGlobalErrorHandlers } from "@/lib/errorReporter";
import { perfBoot } from "@/lib/perfLog";
import { registerImageSW } from "@/lib/registerImageSW";
import { createIdbPersister, LEGACY_LOCALSTORAGE_KEY, persistQueryClientLazily } from "@/lib/rqPersister";

// Bump when the persisted cache shape changes (added/removed fields on
// OFChatItem, etc.) so old persisted snapshots get nuked on read instead
// of silently rendering as garbage.
// v3.2: fan-spend source switched from OF /users/list to local DB
// /admin/fans/{aid}/spend-batch (key renamed from "fan-spend-of" → "fan-spend").
// v3.3: force-evict stale persisted fan identity (of-user/chats/fan) after a
// batch of out-of-band nickname/note rewrites (gen_info backfill) left drawers
// showing pre-regen "<name>/Whale" + old notes across reloads.
// v3.4: evict persisted caches that may hold a poisoned, principal-agnostic
// ["accounts"] full-registry list (see useAccounts.ts — fixed to key by user).
const CACHE_BUSTER = "v3.4";
// Snapshot-level cap — if the user is inactive for this long, the whole
// persisted cache gets dropped. Bumped to 30d so a 2-week vacation
// doesn't nuke everything; the per-query sliding window below handles
// the actual freshness policy.
const PERSIST_MAX_AGE = 30 * 24 * 60 * 60 * 1000;
// Per-query sliding window — a query persists only if it was used (read
// or refetched) within this many ms. Rolls forward on every mount /
// data update so heavily-used queries stay warm forever and forgotten
// ones age out.
const PER_QUERY_MAX_IDLE_MS = 7 * 24 * 60 * 60 * 1000;
// A save at most this long after the cache changes. Opening a pop-out or a
// new tab, hiding or leaving this one saves at once (rqPersister FLUSH_EVENTS),
// so the wait only bounds what a crash loses.
const PERSIST_THROTTLE_MS = 4_000;
// Message threads are most of the snapshot (a thread's rows carry their media,
// ~100KB a thread), and every thread opened or prefetched in the persist window
// would otherwise ride along. Keep the most recently used ones: the open chat,
// the pop-out's, the ones just switched between.
const PERSIST_MAX_THREADS = 30;

// Keys we want shared across tabs: a query is saved when its key starts with
// one of these segment lists. Anything not on this list stays in-memory only.
// Rule for an answer that depends on who is signed in: its key carries the
// principal (`usePrincipalId`; "accounts" files it by user id), so a stale tab
// of the previous login, which keeps saving on its throttle, can only write
// under its own principal and never into the next login's entry. "accounts",
// "applied-settings" and "dashboard/revenue-by-kind" follow it; the older
// per-Creator entries rely on wipeIdentityStorage alone (login, logout, an
// identity change).
const PERSIST_KEYS: ReadonlyArray<readonly string[]> = [
  ["chats"],          // inbox sidebar — biggest popout win
  ["chat-folders"],   // pinned-folder chip strip — avoids 1s lag on tab switch
  ["messages"],       // per-chat thread; popout reuses the inbox's loaded pages
  ["of-me"],          // model account profile — small, reused everywhere
  ["of-user"],        // single-fan profile lookup (popout header)
  ["vault-lists"],    // folders for the Add-to-lists picker (kills 2s lag)
  ["vault-history"],  // per-fan sent/purchased history for picker badges
  ["wall-media"],     // ids posted on the wall — blue ring in vault picker
  ["templates"],      // composer's quick-reply picker
  ["saved-replies"],  // composer's saved replies
  ["fan"],            // local fan-row drawer data
  ["fan-spend"],      // bulk lifetime-spend per chat row (24h staleTime)
  ["fan-chat-media"], // FanDrawer Sales + Unsold PPV galleries — slow OF
                    //   call (3-9s), 30min SWR, 24h gcTime. Surviving
                    //   tab reload / popout open avoids 6s of blank
                    //   "Sales" section every time the drawer re-mounts.
  ["last-purchases"], // payouts transactions feed — staleTime Infinity
  ["employees"],      // employee picker
  ["accounts"],       // active-models sidebar
  ["chatter"],        // chatter principal — me / owners / accounts
  ["applied-settings"], // the Agency's applied settings (report zone, week
                    //   start, permissions), keyed by principal. A return
                    //   visit cuts the Dashboard's days without waiting.
  ["dashboard", "revenue-by-kind"], // the Dashboard's Total earnings (a DB
                    //   sum, keyed by principal): a return visit paints the
                    //   last Total at once, then refreshes it. Its siblings
                    //   under "dashboard" stay in memory.
];

export function shouldPersistKey(queryKey: readonly unknown[]): boolean {
  return PERSIST_KEYS.some((p) => p.every((seg, i) => queryKey[i] === seg));
}

export default function Providers({ children }: { children: React.ReactNode }) {
  const [queryClient] = useState(() => new QueryClient({
    defaultOptions: {
      queries: {
        // Treat everything as fresh for 3 days by default — chatters
        // re-open the tab across days and we don't want to re-fetch
        // half the inbox each time. Per-query overrides at the useQuery
        // call site for things that genuinely need freshness (chat list
        // 30s, online presence 30s, etc.)
        staleTime: 3 * 24 * 60 * 60 * 1000,
        // 7d to match PERSIST_MAX_AGE — keeps queries alive in memory
        // for as long as their persisted copy is valid.
        gcTime:    7 * 24 * 60 * 60 * 1000,
        // Don't refetch on window focus — feels noisy with SSE already
        // keeping things live. Re-enable per-query if a screen needs it.
        refetchOnWindowFocus: false,
        retry: 1,
      },
      mutations: {
        retry: 0,
      },
    },
  }));

  // Starts true so first-render useQuery hooks don't fire network requests
  // before IndexedDB hydration completes — that race is what made the
  // popout tab re-load vault + messages despite them being persisted.
  const [isRestoring, setIsRestoring] = useState(true);

  // Wire the global error reporter once per page load. This catches
  // window-level uncaught exceptions and unhandled promise rejections
  // and POSTs them to /admin/errors. Idempotent — safe under StrictMode
  // double-invoke.
  useEffect(() => {
    installGlobalErrorHandlers();
    // SW for image caching — no-op in dev, lazy register in prod (the old
    // IMAGE_LOAD_PLAN.txt phase C, tag `legacy-ui-final`).
    registerImageSW();
    // Side-effect import: perfLog's module-evaluation mints the tabId
    // and emits the `tab open` event. The call itself is a no-op; we
    // just want the import to land in the boot bundle so the open
    // event fires before lazy-loaded hooks first drag perfLog in.
    perfBoot();
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") {
      setIsRestoring(false);
      return;
    }
    // Track per-query last-used time so the persistence layer can roll
    // a 7-day window forward on every mount / data update. dataUpdatedAt
    // doesn't bump on plain reads from cache (only on fetches), so for
    // long-staleTime queries we'd otherwise evict actively-used data.
    const lastUsed = new Map<string, number>();
    const queryCache = queryClient.getQueryCache();
    // Seed with anything already in cache (rehydrated from a previous
    // session before this effect ran).
    for (const q of queryCache.getAll()) {
      lastUsed.set(q.queryHash, q.state.dataUpdatedAt || Date.now());
    }
    const unsubLastUsed = queryCache.subscribe((event) => {
      // `observerAdded` fires when a component mounts and starts reading
      // the query — that's our "used" signal for infinite-staleTime
      // queries. `updated` fires on every state change (fetch lands,
      // setQueryData, etc.) and covers refetches.
      if (event.type === "observerAdded" || event.type === "updated") {
        lastUsed.set(event.query.queryHash, Date.now());
      } else if (event.type === "removed") {
        lastUsed.delete(event.query.queryHash);
      }
    });

    // The snapshot moved to IndexedDB: drop the old localStorage copy, which
    // could pin the origin at its ~5MB quota and starve every OTHER
    // localStorage write (rail settings, dock spots, notif history, exclude
    // lists). Not migrated — the cache rebuilds itself.
    try { window.localStorage.removeItem(LEGACY_LOCALSTORAGE_KEY); } catch { /* ignore */ }
    const usedAt = (q: { queryHash: string; state: { dataUpdatedAt: number } }) =>
      lastUsed.get(q.queryHash) ?? q.state.dataUpdatedAt;
    const [unsubscribe, restorePromise] = persistQueryClientLazily({
      queryClient,
      persister: createIdbPersister(),
      maxAge: PERSIST_MAX_AGE,
      buster: CACHE_BUSTER,
      throttleMs: PERSIST_THROTTLE_MS,
      // Built per save, so the thread ranking is the cache's at that moment.
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
            // Only persist successful queries on the allowlist. Errored
            // ones aren't worth carrying over — they'll just re-trigger.
            if (q.state.status !== "success") return false;
            if (!shouldPersistKey(q.queryKey)) return false;
            // A caller can keep one query of a persisted prefix in memory only.
            if (q.meta?.persist === false) return false;
            if (q.queryKey[0] === "messages" && !keptThreads.has(q.queryHash)) return false;
            // Per-query sliding window: drop from the snapshot if it
            // hasn't been touched in PER_QUERY_MAX_IDLE_MS.
            return now - usedAt(q) < PER_QUERY_MAX_IDLE_MS;
          },
        };
      },
    });
    // Both arms: a failed restore (no IndexedDB, corrupt snapshot) just boots
    // cold, and must not surface as an unhandled rejection.
    const restored = () => setIsRestoring(false);
    restorePromise.then(restored, restored);
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
                <ErrorBoundary scope="root">{children}</ErrorBoundary>
              </ScopeProvider>
            </EmployeeProvider>
          </ChatterProvider>
        </UserProvider>
      </IsRestoringProvider>
      {/* Devtools only render in development; safe to leave mounted. */}
      {/* bottom-left so the floating button doesn't overlap the Composer's
       *  Send / Send-in-N controls in the chat surface. */}
      <ReactQueryDevtools initialIsOpen={false} buttonPosition="bottom-left" />
    </QueryClientProvider>
  );
}
