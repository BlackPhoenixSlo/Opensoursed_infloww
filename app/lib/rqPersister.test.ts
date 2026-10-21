/**
 * rqPersister — the IndexedDB snapshot store behind the React Query persister.
 *
 * Pins the three behaviours the localStorage persister had and callers rely on:
 *   • writes are throttled and the LATEST snapshot wins (pop-out flush window),
 *   • clearPersistedCache cancels a write still waiting in the throttle, so an
 *     identity wipe can't be re-stamped with the previous identity's cache,
 *   • a written snapshot restores as the same object.
 *
 * jsdom has no IndexedDB and fake-indexeddb isn't installed, so a minimal stub
 * stands in: one store, requests complete on a microtask, like the real thing.
 */
import { afterAll, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import type { PersistedClient } from "@tanstack/react-query-persist-client";

import { clearPersistedCache, createIdbPersister } from "@/lib/rqPersister";

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

describe("rqPersister", () => {
  it("throttles writes and stores only the latest snapshot", async () => {
    const p = createIdbPersister(250);
    p.persistClient(snapshot(1));
    p.persistClient(snapshot(2));
    await vi.advanceTimersByTimeAsync(249);
    expect(puts).toEqual([]);

    await vi.advanceTimersByTimeAsync(1);
    expect(puts).toEqual([JSON.stringify(snapshot(2))]);
  });

  it("a clear cancels the write still waiting in the throttle", async () => {
    const p = createIdbPersister(250);
    p.persistClient(snapshot(1));
    await clearPersistedCache();
    await vi.advanceTimersByTimeAsync(1_000);

    expect(puts).toEqual([]);
    expect(await p.restoreClient()).toBeUndefined();
  });

  it("restores the snapshot it wrote, and nothing once removed", async () => {
    const p = createIdbPersister(250);
    p.persistClient(snapshot(3));
    await vi.advanceTimersByTimeAsync(250);

    expect(await p.restoreClient()).toEqual(snapshot(3));
    await p.removeClient();
    expect(await p.restoreClient()).toBeUndefined();
  });
});
