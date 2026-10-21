/**
 * The React Query snapshot store: one IndexedDB record, shared by every tab of
 * the origin (the pop-out included), so it is the same cross-tab cache the
 * localStorage persister was — without localStorage's ~5MB origin quota, which
 * the snapshot used to fill and so starve every other localStorage write.
 *
 * Dependency-free on purpose: three one-shot requests are all a persister needs.
 */
import type { PersistedClient, Persister } from "@tanstack/react-query-persist-client";

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

let pendingWrite: ReturnType<typeof setTimeout> | null = null;

/** Async persister over the store above. Writes are throttled (the latest
 *  snapshot wins), stored as a JSON string like the sync persister did. */
export function createIdbPersister(throttleTime: number): Persister {
  let latest: PersistedClient;
  return {
    persistClient(client) {
      latest = client;
      if (pendingWrite !== null) return;
      pendingWrite = setTimeout(() => {
        pendingWrite = null;
        // A failed write (quota, private mode) only costs the next tab its warm start.
        run("readwrite", (s) => s.put(JSON.stringify(latest), KEY)).catch(() => {});
      }, throttleTime);
    },
    async restoreClient() {
      const raw = await run("readonly", (s) => s.get(KEY) as IDBRequest<string | undefined>);
      return raw ? (JSON.parse(raw) as PersistedClient) : undefined;
    },
    removeClient: clearPersistedCache,
  };
}

/** Drop the snapshot, and any throttled write still waiting to re-stamp it.
 *  Readwrite transactions on one store commit in creation order, so this lands
 *  after any write already in flight. Never rejects. */
export async function clearPersistedCache(): Promise<void> {
  if (pendingWrite !== null) {
    clearTimeout(pendingWrite);
    pendingWrite = null;
  }
  if (typeof indexedDB === "undefined") return;
  try {
    await run("readwrite", (s) => s.delete(KEY));
  } catch { /* nothing persisted, or no IndexedDB: nothing to drop */ }
}
