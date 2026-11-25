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
export const LEGACY_LOCALSTORAGE_KEY = "chatterly-rq-cache";

let dbPromise: Promise<IDBDatabase> | null = null;
function openDb(): Promise<IDBDatabase> {
  dbPromise ??= new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, 1);
    req.onupgradeneeded = () => req.result.createObjectStore(STORE);
    req.onsuccess = () => {
            // Safari may close an idle connection: reopen next time
      req.result.onclose = () => { dbPromise = null; };
      resolve(req.result);
    };
    req.onerror = () => { dbPromise = null; reject(req.error); };
  });
  return dbPromise;
}

async function run<T>(mode: IDBTransactionMode, op: (s: IDBObjectStore) => IDBRequest<T>): Promise<T> {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE, mode);
    const req = op(tx.objectStore(STORE));
    tx.oncomplete = () => resolve(req.result);
    tx.onerror = tx.onabort = () => reject(tx.error ?? req.error);
  });
}

export function createIdbPersister(): Persister {
  return {
    async persistClient(client) {
      await run("readwrite", (s) => s.put(JSON.stringify(client), KEY)).catch(() => {});
    },
    async restoreClient() {
      const raw = await run("readonly", (s) => s.get(KEY) as IDBRequest<string | undefined>);
      return raw ? (JSON.parse(raw) as PersistedClient) : undefined;
    },
    removeClient: clearPersistedCache,
  };
}

const SAVE_IDLE_TIMEOUT_MS = 1_000;

let dirty = false;
let pendingSave: (() => void) | null = null;
let flushNow: (() => void) | null = null;

export function flushPersistedCache(): void {
  flushNow?.();
}

// blur too: opening a pop-out or new tab must let the new page restore what this one just loaded
const FLUSH_EVENTS = ["pagehide", "blur"] as const;

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

export async function clearPersistedCache(): Promise<void> {
  pendingSave?.();
  pendingSave = null;
  dirty = false;
  if (typeof indexedDB === "undefined") return;
  try {
    await run("readwrite", (s) => s.delete(KEY));
  } catch { }
}
