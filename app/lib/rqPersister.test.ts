/**
 * rqPersister — the IndexedDB snapshot store behind the React Query persister.
 *
 * Pins what callers rely on:
 *   • cache changes are saved once per throttle window, as the cache stands
 *     at the save (not one dehydrate per change),
 *   • a flush event (blur: a pop-out opening; pagehide) or flushPersistedCache saves at once,
 *   • clearPersistedCache cancels a save still waiting, so an identity wipe
 *     can't be re-stamped with the previous identity's cache,
 *   • a written snapshot restores as the same object.
 *
 * jsdom has no IndexedDB and fake-indexeddb isn't installed, so a minimal stub
 * stands in: one store, requests complete on a microtask, like the real thing.
 */
import { afterAll, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { QueryClient } from "@tanstack/react-query";
import type { PersistedClient } from "@tanstack/react-query-persist-client";

import {
  clearPersistedCache, createIdbPersister, flushPersistedCache, persistQueryClientLazily,
} from "@/lib/rqPersister";

const data = new Map<string, unknown>();
const puts: unknown[] = [];

function stubIndexedDB() {
  type Handler = (() => void) | null;
  const db = {
    onclose: null as Handler,
    createObjectStore: () => {},
    transaction() {
      const request = (run: () => unknown) => {
        const req = { result: undefined as unknown, error: null };
        queueMicrotask(() => { req.result = run(); tx.oncomplete?.(); });
        return req;
      };
      const tx = {
        oncomplete: null as Handler,
        onerror: null as Handler,
        onabort: null as Handler,
        error: null,
        objectStore: () => ({
          put: (v: unknown, k: string) => request(() => { puts.push(v); data.set(k, v); }),
          get: (k: string) => request(() => data.get(k)),
          delete: (k: string) => request(() => { data.delete(k); }),
        }),
      };
      return tx;
    },
  };
  vi.stubGlobal("indexedDB", {
    open() {
      const req = { result: db, error: null, onupgradeneeded: null as Handler, onsuccess: null as Handler, onerror: null as Handler };
      queueMicrotask(() => { req.onupgradeneeded?.(); req.onsuccess?.(); });
      return req;
    },
  });
}

const snapshot = (n: number): PersistedClient => ({
  timestamp: n,
  buster: "test",
  clientState: { queries: [], mutations: [] },
});

beforeAll(() => { stubIndexedDB(); vi.useFakeTimers(); });
afterAll(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });
beforeEach(() => { data.clear(); puts.length = 0; });

/** The keys of the queries in the last snapshot written. */
const savedKeys = () =>
  (JSON.parse(puts.at(-1) as string) as PersistedClient).clientState.queries.map((q) => q.queryKey[0]);

async function lazilyPersisted(throttleMs = 4_000) {
  const queryClient = new QueryClient();
  const dehydrateOptions = vi.fn(() => ({}));
  const [unsubscribe, restored] = persistQueryClientLazily({
    queryClient, persister: createIdbPersister(), buster: "test", throttleMs, dehydrateOptions,
  });
  await restored;
  return { queryClient, dehydrateOptions, unsubscribe };
}

describe("rqPersister", () => {
  it("saves once per throttle window, the cache as it stands then", async () => {
    const { queryClient, dehydrateOptions, unsubscribe } = await lazilyPersisted();
    queryClient.setQueryData(["a"], 1);
    queryClient.setQueryData(["b"], 2);
    queryClient.setQueryData(["a"], 3);
    await vi.advanceTimersByTimeAsync(3_999);
    expect(puts).toEqual([]);

    await vi.advanceTimersByTimeAsync(1_001); // the throttle, then the idle callback's deadline
    expect(dehydrateOptions).toHaveBeenCalledTimes(1);
    expect(puts).toHaveLength(1);
    expect(savedKeys()).toEqual(["a", "b"]);
    unsubscribe();
  });

  it("a blur (a pop-out opening) saves at once", async () => {
    const { queryClient, unsubscribe } = await lazilyPersisted();
    queryClient.setQueryData(["a"], 1);
    window.dispatchEvent(new Event("blur"));
    await vi.advanceTimersByTimeAsync(0);
    expect(savedKeys()).toEqual(["a"]);

    // Nothing changed since: the pending timer was cancelled, no second write.
    await vi.advanceTimersByTimeAsync(10_000);
    expect(puts).toHaveLength(1);
    unsubscribe();
  });

  it("flushPersistedCache saves at once (a write the next page load must see), and is a no-op once unsubscribed", async () => {
    const { queryClient, unsubscribe } = await lazilyPersisted();
    queryClient.setQueryData(["a"], 1);
    flushPersistedCache();
    await vi.advanceTimersByTimeAsync(0);
    expect(savedKeys()).toEqual(["a"]);

    unsubscribe();
    queryClient.setQueryData(["b"], 2);
    flushPersistedCache();
    await vi.advanceTimersByTimeAsync(10_000);
    expect(puts).toHaveLength(1);
  });

  it("a clear cancels the save still waiting, and a later flush has nothing to write", async () => {
    const { queryClient, unsubscribe } = await lazilyPersisted();
    queryClient.setQueryData(["a"], 1);
    await clearPersistedCache();
    window.dispatchEvent(new Event("pagehide"));
    await vi.advanceTimersByTimeAsync(10_000);

    expect(puts).toEqual([]);
    expect(await createIdbPersister().restoreClient()).toBeUndefined();
    unsubscribe();
  });

  it("restores the snapshot it wrote, and nothing once removed", async () => {
    const p = createIdbPersister();
    await p.persistClient(snapshot(3));

    expect(await p.restoreClient()).toEqual(snapshot(3));
    await p.removeClient();
    expect(await p.restoreClient()).toBeUndefined();
  });
});
