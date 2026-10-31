/**
 * The React Query snapshot store: one IndexedDB record, shared by every tab of
 * the origin (the pop-out included), so it is the same cross-tab cache the
 * localStorage persister was — without localStorage's ~5MB origin quota, which
 * the snapshot used to fill and so starve every other localStorage write.
 *
 * Dependency-free on purpose: three one-shot requests are all a persister needs.
 */
import type { DehydrateOptions } from "@tanstack/react-query";
import {
  persistQueryClientRestore,
  persistQueryClientSave,
  type PersistQueryClientOptions,
  type PersistedClient,
  type Persister,
} from "@tanstack/react-query-persist-client";

import { onIdle } from "@/lib/idle";

const DB_NAME = "chatterly-rq";
const STORE = "snapshot";
const KEY = "cache";
/** The localStorage key the snapshot lived under before IndexedDB. */
export const LEGACY_LOCALSTORAGE_KEY = "chatterly-rq-cache";

let dbPromise: Promise<IDBDatabase> | null = null;
function openDb(): Promise<IDBDatabase> {
  dbPromise ??= new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, 1);
    req.onupgradeneeded = () => req.result.createObjectStore(STORE);
    req.onsuccess = () => {
      // The browser may close an idle connection (Safari does): reopen next time.
      req.result.onclose = () => { dbPromise = null; };
      resolve(req.result);
    };
    req.onerror = () => { dbPromise = null; reject(req.error); };
  });
  return dbPromise;
}

/** One request in its own transaction; resolves once the transaction COMMITS,
 *  so an awaited delete is on disk before a hard navigation tears the page down. */
async function run<T>(mode: IDBTransactionMode, op: (s: IDBObjectStore) => IDBRequest<T>): Promise<T> {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE, mode);
    const req = op(tx.objectStore(STORE));
    tx.oncomplete = () => resolve(req.result);
    tx.onerror = tx.onabort = () => reject(tx.error ?? req.error);
  });
}

/** Async persister over the store above: one write per call, the snapshot
 *  stored as a JSON string. Throttling is `persistQueryClientLazily`'s job. */
export function createIdbPersister(): Persister {
  return {
    async persistClient(client) {
      // A failed write (quota, private mode) only costs the next tab its warm start.
      await run("readwrite", (s) => s.put(JSON.stringify(client), KEY)).catch(() => {});
    },
    async restoreClient() {
      const raw = await run("readonly", (s) => s.get(KEY) as IDBRequest<string | undefined>);
      return raw ? (JSON.parse(raw) as PersistedClient) : undefined;
    },
    removeClient: clearPersistedCache,
  };
}

/** How long a due save may wait for the browser to go idle. */
const SAVE_IDLE_TIMEOUT_MS = 1_000;

/** The cache changed since the last save. */
let dirty = false;
/** Cancels the save scheduled for the dirty cache, if any. */
let pendingSave: (() => void) | null = null;
/** The live persister's flush (save now), while one is wired. */
let flushNow: (() => void) | null = null;

/** Save the snapshot now, not on the throttle: for a write the next page load must show (a reload a second
 *  after it would otherwise restore the snapshot from before it). A no-op with no persister wired. */
export function flushPersistedCache(): void {
  flushNow?.();
}

/** Window events that write the snapshot now: the tab hiding or going away,
 *  and the window losing focus — which is what opening a pop-out or a new tab
 *  does, so the new page restores what this one just loaded. */
const FLUSH_EVENTS = ["pagehide", "blur"] as const;

/**
 * `persistQueryClient` with the save off the hot path. The library's version
 * dehydrates the whole cache on EVERY cache event (a fetch's start and end, each
 * of the chat list enrichment's per-Fan writes) and only throttles the write.
 * Here a cache event just marks the snapshot dirty; one save — dehydrate,
 * stringify, write — runs `throttleMs` after the first change, in an idle
 * callback, and again on a flush event. A hidden tab doesn't save on a timer
 * (it saved as it hid, and the visible tab's snapshot is the fresher one): it
 * saves on its next flush event, or once it is visible again.
 *
 * `dehydrateOptions` is called once per save, so it may rank the cache then.
 */
export function persistQueryClientLazily({
  throttleMs,
  dehydrateOptions,
  ...options
}: Omit<PersistQueryClientOptions, "dehydrateOptions"> & {
  throttleMs: number;
  dehydrateOptions: () => DehydrateOptions;
}): [unsubscribe: () => void, restored: Promise<void>] {
  const save = () => {
    pendingSave = null;
    if (!dirty) return;
    dirty = false;
    persistQueryClientSave({ ...options, dehydrateOptions: dehydrateOptions() }).catch(() => {});
  };
  const schedule = () => {
    if (pendingSave || !dirty || document.visibilityState === "hidden") return;
    const timer = setTimeout(() => { pendingSave = onIdle(save, SAVE_IDLE_TIMEOUT_MS); }, throttleMs);
    pendingSave = () => clearTimeout(timer);
  };
  const flush = () => {
    pendingSave?.();
    save();
  };
  const onCacheEvent = (event: { type: string }) => {
    if (event.type !== "added" && event.type !== "removed" && event.type !== "updated") return;
    dirty = true;
    schedule();
  };
  const onVisibility = () => (document.visibilityState === "hidden" ? flush() : schedule());

  let stopped = false;
  let unsubscribe = () => { stopped = true; };
  const restored = persistQueryClientRestore(options).then(() => {
    if (stopped) return;
    const { queryClient } = options;
    const unsubQueries = queryClient.getQueryCache().subscribe(onCacheEvent);
    const unsubMutations = queryClient.getMutationCache().subscribe(onCacheEvent);
    document.addEventListener("visibilitychange", onVisibility);
    for (const e of FLUSH_EVENTS) window.addEventListener(e, flush);
    flushNow = flush;
    unsubscribe = () => {
      stopped = true;
      if (flushNow === flush) flushNow = null;
      unsubQueries();
      unsubMutations();
      document.removeEventListener("visibilitychange", onVisibility);
      for (const e of FLUSH_EVENTS) window.removeEventListener(e, flush);
      pendingSave?.();
      pendingSave = null;
    };
  });
  return [() => unsubscribe(), restored];
}

/** Drop the snapshot, and forget the unsaved changes that could re-stamp it.
 *  Readwrite transactions on one store commit in creation order, so this lands
 *  after any write already in flight. Never rejects. */
export async function clearPersistedCache(): Promise<void> {
  pendingSave?.();
  pendingSave = null;
  dirty = false;
  if (typeof indexedDB === "undefined") return;
  try {
    await run("readwrite", (s) => s.delete(KEY));
  } catch { /* nothing persisted, or no IndexedDB: nothing to drop */ }
}
