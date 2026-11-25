import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createElement, type ReactNode } from "react";
import { QueryClient, QueryClientProvider, QueryObserver } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";

const h = vi.hoisted(() => ({ post: vi.fn(), flush: vi.fn() }));
vi.mock("@/lib/relay", async (orig) => {
  const mod = await orig<typeof import("@/lib/relay")>();
  return { ...mod, relay: { ...mod.relay, post: h.post } };
});
vi.mock("@/lib/rqPersister", async (orig) => {
  const mod = await orig<typeof import("@/lib/rqPersister")>();
  return { ...mod, flushPersistedCache: h.flush };
});

import { loadFolderSort, saveFolderSort } from "@/components/vault/vaultFolderSort";
import {
  OF_SEARCH_MS, describeAllBody, hideDuplicates, invalidateVaultGrid, mirrorItemsKey, sortOfFolders, useOfSearch,
} from "@/hooks/useVaultCache";


const AID = "1000001";

beforeEach(() => {
  h.post.mockReset();
  h.flush.mockReset();
  window.localStorage.clear();
});
afterEach(() => window.localStorage.clear());

describe("sortOfFolders saves the sort label and returns it", () => {
  it.each([
    ["a sort and order (OF-mirror, new-post dialog)", { sort: "name", order: "desc" }, { sort: "name", order: "desc" }],
    ["a custom order (the rail's Done) keeps the order", { customOrder: [3, 1, 2] }, { sort: "custom", order: "asc" }],
  ] as const)("%s", async (_, opts, want) => {
    h.post.mockResolvedValue({});
    saveFolderSort(AID, { sort: "recent", order: "asc" });
    expect(await sortOfFolders(AID, opts)).toEqual(want);
    expect(loadFolderSort(AID)).toEqual(want);
  });

  it("a sort OF refused leaves the label", async () => {
    h.post.mockRejectedValue(new Error("502"));
    saveFolderSort(AID, { sort: "recent", order: "asc" });
    await expect(sortOfFolders(AID, { sort: "name", order: "desc" })).rejects.toThrow("502");
    expect(loadFolderSort(AID)).toEqual({ sort: "recent", order: "asc" });
  });
});

describe("invalidateVaultGrid", () => {
  it("saves the query snapshot after marking the vault queries stale", () => {
    const qc = new QueryClient();
    let staleAtFlush: boolean | undefined;
    qc.setQueryData(["vault-lists", AID], { list: [] });
    h.flush.mockImplementation(() => {
      staleAtFlush = qc.getQueryState(["vault-lists", AID])?.isInvalidated;
    });
    invalidateVaultGrid(qc, AID);
    expect(h.flush).toHaveBeenCalledTimes(1);
    expect(staleAtFlush).toBe(true);
  });
});

describe("hideDuplicates", () => {
  const ids = Array.from({ length: 501 }, (_, i) => i + 1);
  const ok = (batch: number[]) => ({ hidden: batch.length, hidden_ids: batch, refused: {} });
  const batchOf = (call: unknown[]) => (call[1] as { media_ids: number[] }).media_ids;

  it("a first batch that fails throws", async () => {
    h.post.mockRejectedValueOnce(new Error("boom"));
    await expect(hideDuplicates(AID, ids)).rejects.toThrow("boom");
  });

  it("a later batch that throws stops with it and the rest not hidden", async () => {
    h.post.mockImplementationOnce((_p, body) => Promise.resolve(ok(body.media_ids))).mockRejectedValueOnce(new Error("boom"));
    const onProgress = vi.fn();
    const res = await hideDuplicates(AID, ids, { onProgress });
    expect(h.post).toHaveBeenCalledTimes(2);
    expect(res).toMatchObject({ hidden: 250, of_error: "boom", not_hidden: ids.slice(250) });
    expect(onProgress.mock.calls.map(([done]) => done)).toEqual([250, 250]);
  });

  it("a later batch OF half refused stops the same way", async () => {
    h.post
      .mockImplementationOnce((_p, body) => Promise.resolve(ok(body.media_ids)))
      .mockImplementationOnce((_p, body) =>
        Promise.resolve({ hidden: 10, hidden_ids: body.media_ids.slice(0, 10), refused: {}, of_error: "half", not_hidden: body.media_ids.slice(10) }));
    const onProgress = vi.fn();
    const res = await hideDuplicates(AID, ids, { onProgress });
    expect(h.post).toHaveBeenCalledTimes(2);
    expect(res).toMatchObject({ hidden: 260, of_error: "half", not_hidden: ids.slice(260) });
    expect(onProgress.mock.calls.map(([done]) => done)).toEqual([250, 260]);
  });

  it("every batch answered: all hidden, no stop", async () => {
    h.post.mockImplementation((_p, body) => Promise.resolve(ok(body.media_ids)));
    const res = await hideDuplicates(AID, ids);
    expect(h.post.mock.calls.map(batchOf).map((b) => b.length)).toEqual([250, 250, 1]);
    expect(res).toEqual({ hidden: 501, hidden_ids: ids, refused: {} });
  });
});

describe("useOfSearch", () => {
  const setup = (query: string, enabled = true) => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const wrapper = ({ children }: { children: ReactNode }) => createElement(QueryClientProvider, { client: qc }, children);
    return { qc, ...renderHook(() => useOfSearch(AID, query, enabled), { wrapper }) };
  };

  it("searching until OF answered AND the mirror grid refetched with it", async () => {
    let answer!: (v: unknown) => void;
    h.post.mockReturnValue(new Promise((r) => { answer = r; }));
    let refetched!: () => void;
    const { qc, result } = setup("leggings");
    qc.setQueryData(mirrorItemsKey(AID), {});
    const unsub = new QueryObserver(qc, {
      queryKey: mirrorItemsKey(AID), staleTime: Infinity,
      queryFn: () => new Promise<unknown>((r) => { refetched = () => r({}); }),
    }).subscribe(() => {});
    const grid = qc.getQueryCache().find({ queryKey: mirrorItemsKey(AID) })!;
    expect(result.current.searching).toBe(true);
    expect(h.post).toHaveBeenCalledWith("/admin/vault-ai/search-of", { account_id: AID, query: "leggings" }, { accountId: AID },
                                        expect.any(AbortSignal));
    answer({ ids: [1], count: 1, source: "of" });
    await waitFor(() => expect(grid.state.fetchStatus).toBe("fetching"));
    expect(result.current.searching).toBe(true);
    refetched();
    await waitFor(() => expect(result.current).toMatchObject({ searching: false, failed: false }));
    unsub();
  });

  it("a failed OF search stops searching and says so (never a false empty)", async () => {
    h.post.mockRejectedValue(new Error("502"));
    const { result } = setup("leggings");
    await waitFor(() => expect(result.current).toMatchObject({ searching: false, failed: true }));
    expect(h.post).toHaveBeenCalledTimes(1);
  });

  it.each([["OF's search never answers", "post", true], ["the grid's refetch never answers", "grid", false]] as const)(
    "%s: searching ends after OF_SEARCH_MS, failed %s", async (_n, hang, failed) => {
      vi.useFakeTimers({ shouldAdvanceTime: true });
      try {
        h.post.mockImplementation((_p: string, _b: unknown, _c: unknown, signal?: AbortSignal) => (hang === "post"
          ? new Promise((_, no) => signal?.addEventListener("abort", () => no(signal.reason)))
          : Promise.resolve({ ids: [1], count: 1, source: "of" })));
        const { qc, result } = setup("leggings");
        qc.setQueryData(mirrorItemsKey(AID), {});
        const unsub = new QueryObserver(qc, { queryKey: mirrorItemsKey(AID), staleTime: Infinity,
                                              queryFn: () => new Promise<unknown>(() => {}) }).subscribe(() => {});
        expect(result.current.searching).toBe(true);
        await vi.advanceTimersByTimeAsync(OF_SEARCH_MS);
        await waitFor(() => expect(result.current.searching).toBe(false));
        expect(result.current).toMatchObject({ failed });
        if (!failed) return unsub();
        h.post.mockResolvedValue({ ids: [], count: 0, source: "of" });
        unsub();
        result.current.retry();
        await waitFor(() => expect(result.current).toMatchObject({ searching: false, failed: false }));
      } finally {
        vi.useRealTimers();
      }
    });
  it("unmounting (the picker closed) aborts OF's search request", async () => {
    let sig: AbortSignal | undefined;
    h.post.mockImplementation((_p: string, _b: unknown, _c: unknown, signal?: AbortSignal) => {
      sig = signal;
      return new Promise(() => {});
    });
    const { unmount } = setup("leggings");
    await waitFor(() => expect(h.post).toHaveBeenCalledTimes(1));
    unmount();
    await waitFor(() => expect(sig?.aborted).toBe(true));
  });
  it.each([["of", 1], ["of_partial", 2]] as const)("a %s answer, searched again: %s OF call(s)", async (source, calls) => {
    h.post.mockResolvedValue({ ids: [1], count: 1, source });
    const { qc, result, unmount } = setup("leggings");
    await waitFor(() => expect(result.current).toMatchObject({ searching: false }));
    unmount();
    const wrapper = ({ children }: { children: ReactNode }) => createElement(QueryClientProvider, { client: qc }, children);
    const again = renderHook(() => useOfSearch(AID, "leggings", true), { wrapper });
    await waitFor(() => expect(again.result.current).toMatchObject({ searching: false }));
    expect(h.post).toHaveBeenCalledTimes(calls);
  });

  it.each([["no query", "", true], ["the grid not on the mirror", "leggings", false]] as const)(
    "%s: no OF call, not searching", (_, query, enabled) => {
      const { result } = setup(query, enabled);
      expect(result.current).toMatchObject({ searching: false, failed: false });
      expect(h.post).not.toHaveBeenCalled();
    });
});

describe("describeAllBody", () => {
  it.each([
    [undefined, "all"],
    [0, "all"],
    [-5, "all"],
    [0.5, "all"],
    [2000, 2000],
    [12.7, 12],
  ])("limit %s -> %s", (limit, want) => {
    expect(describeAllBody({ restage: true, limit })).toEqual(
      { force: false, restage: true, prompt_version: "v2", limit: want });
  });
});
