import { beforeEach, describe, expect, it, vi, type Mock } from "vitest";
import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { InfiniteQueryObserver, QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("@/lib/relay", async (orig) => ({
  ...(await orig<typeof import("@/lib/relay")>()),
  relay: { post: vi.fn(), get: vi.fn() },
}));
vi.mock("@/hooks/useVaultCache", () => ({
  invalidateVaultGrid: vi.fn(async () => {}),
  mirrorItemsKey: (accountId: string) => ["vault-mirror-items", accountId],
}));

import { invalidateVaultGrid } from "@/hooks/useVaultCache";
import {
  ofUnreachable, refreshVaultFromOf, reloadBrokenThumbs, useOfRefresh, vaultBrowseSource, vaultPickerSource, vaultWholeSource,
  type VaultSource,
} from "@/hooks/vaultRefresh";
import { relay, RelayError } from "@/lib/relay";

const post = relay.post as unknown as Mock;
const reload = invalidateVaultGrid as unknown as Mock;

// R2-6: only "OnlyFans could not be reached" reads as the saved-vault note; anything else is an error.
describe("ofUnreachable", () => {
  it.each<[string, unknown, boolean]>([
    ["relay 502 (OF failed)", new RelayError(502, null), true],
    ["relay 504 (OF timed out)", new RelayError(504, null), true],
    ["no answer (network)", new TypeError("Failed to fetch"), true],
    ["401", new RelayError(401, null), false],
    ["403", new RelayError(403, null), false],
    ["422", new RelayError(422, null), false],
  ])("%s", (_n, e, want) => expect(ofUnreachable(e)).toBe(want));
});

// F1/F15: the whole-set rule (picker grid, whole-vault/folder downloads, focus prefetch): a partial mirror never.
describe("vaultWholeSource", () => {
  it.each<[string, Parameters<typeof vaultWholeSource>[0], VaultSource]>([
    ["summary not in yet", undefined, "live"],
    ["no summary (chatter's 403)", null, "live"],
    ["nothing collected", { count: 0, complete: false }, "live"],
    ["partial mirror (first pages only)", { count: 300, complete: false }, "live"],
    ["`complete` missing", { count: 300 }, "live"],
    ["walk done but empty", { count: 0, complete: true }, "live"],
    ["walk done, media held", { count: 300, complete: true }, "mirror"],
    // H1 (#329): a restricted chatter's count is its folders' only; `complete` is still the whole-vault flag.
    ["restricted chatter, walk done, its folders hold media", { count: 12, complete: true }, "mirror"],
  ])("%s", (_n, summary, want) => expect(vaultWholeSource(summary)).toBe(want));
});

// U4: the picker waits for the summary's first answer; it never paints the live listing over a collected vault.
describe("vaultPickerSource", () => {
  const done = { count: 300, complete: true };
  it.each<[string, Parameters<typeof vaultPickerSource>[0], VaultSource | "pending"]>([
    ["summary in flight", { data: undefined, isLoading: true }, "pending"],
    ["summary failed (chatter's 403)", { data: undefined, isLoading: false }, "live"],
    ["summary disabled (no Creator)", { data: undefined, isLoading: false }, "live"],
    ["collected vault", { data: done, isLoading: false }, "mirror"],
    ["partial mirror", { data: { count: 300, complete: false }, isLoading: false }, "live"],
    ["cached answer while refetching", { data: done, isLoading: false }, "mirror"],
    ["null answer", { data: null, isLoading: false }, "live"],
  ])("%s", (_n, summary, want) => expect(vaultPickerSource(summary)).toBe(want));

  // #15: a summary read that never answers must not hold the grid on Loading for good.
  it.each<[string, Parameters<typeof vaultPickerSource>[0], VaultSource | "pending"]>([
    ["still in flight after the wait", { data: undefined, isLoading: true }, "live"],
    ["late answer: collected vault", { data: done, isLoading: false }, "mirror"],
    ["late answer: partial mirror", { data: { count: 300, complete: false }, isLoading: false }, "live"],
  ])("waited out, %s", (_n, summary, want) => expect(vaultPickerSource(summary, true)).toBe(want));
});

// F15: the browse rule (manager grid, its thumb reload + selection download): a partial mirror is the mirror.
describe("vaultBrowseSource", () => {
  it.each<[string, Parameters<typeof vaultBrowseSource>[0], VaultSource]>([
    ["summary not in yet", undefined, "live"],
    ["nothing collected", { count: 0, complete: false }, "live"],
    ["partial mirror (collector page cap, never complete)", { count: 300, complete: false }, "mirror"],
    ["`complete` missing", { count: 300 }, "mirror"],
    ["walk done, media held", { count: 300, complete: true }, "mirror"],
    // H1 (#329): a restricted chatter's own folders' count.
    ["restricted chatter, its folders hold media", { count: 12, complete: false }, "mirror"],
  ])("%s", (_n, summary, want) => expect(vaultBrowseSource(summary)).toBe(want));
});

// F17/F18: both grids' Refresh mutation.
describe("useOfRefresh", () => {
  beforeEach(() => { post.mockReset(); reload.mockClear(); cleanup(); });

  function mountRefresh(scope: string | null) {
    const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
    const wrapper = ({ children }: { children: ReactNode }) => createElement(QueryClientProvider, { client }, children);
    const refreshed = vi.fn();
    const h = renderHook(({ s }: { s: string | null }) => useOfRefresh(s, { refreshed }), {
      wrapper, initialProps: { s: scope },
    });
    return { ...h, refreshed };
  }

  it.each<[string, () => Promise<unknown>, string | null]>([
    ["synced: no note", async () => ({}), null],
    ["OF unreachable: the saved-vault note", async () => { throw new RelayError(502, null); }, "Couldn't reach OnlyFans, showing saved vault"],
    ["another failure: Refresh failed", async () => { throw new RelayError(403, null); }, "Refresh failed"],
  ])("%s", async (_n, impl, want) => {
    post.mockImplementation(impl);
    const { result, refreshed } = mountRefresh("A");
    act(() => result.current.mutate(null));
    await waitFor(() => expect(refreshed).toHaveBeenCalledWith("A"));
    await waitFor(() => expect(result.current.isPending).toBe(false));
    expect(result.current.note).toBe(want);
  });

  it("settles for the Creator it ran for, not the one on screen; a switch frees the button", async () => {
    let settle!: () => void;
    post.mockImplementation(() => new Promise<void>((r) => { settle = r; }));
    const { result, rerender, refreshed } = mountRefresh("A");
    act(() => result.current.mutate(null));
    await waitFor(() => expect(result.current.isPending).toBe(true));
    rerender({ s: "B" });
    await waitFor(() => expect(result.current.isPending).toBe(false));
    await act(async () => settle());
    await waitFor(() => expect(refreshed).toHaveBeenCalledOnce());
    expect(refreshed).toHaveBeenCalledWith("A");
    expect(result.current.note).toBeNull();
  });

  // F24: pending lives with the Creator's mutation, not the observer: a reopen (or switch back) mid-sync stays
  // disabled, so no second POST /admin/vault-ai/sync.
  it.each<[string, (string | null)[]]>([
    ["close + reopen", [null, "A"]],
    ["switch to B and back", ["B", "A"]],
  ])("%s mid-sync: still pending for A, free for others", async (_n, path) => {
    let settle!: () => void;
    post.mockImplementation(() => new Promise<void>((r) => { settle = r; }));
    const { result, rerender } = mountRefresh("A");
    act(() => result.current.mutate(null));
    await waitFor(() => expect(result.current.isPending).toBe(true));
    for (const s of path) {
      rerender({ s });
      expect(result.current.isPending).toBe(s === "A");
    }
    await act(async () => settle());
    await waitFor(() => expect(result.current.isPending).toBe(false));
    expect(post).toHaveBeenCalledOnce();
  });

  it("closing (scope null) drops the note, so a reopen starts clean", async () => {
    post.mockRejectedValue(new RelayError(403, null));
    const { result, rerender } = mountRefresh("A");
    act(() => result.current.mutate(null));
    await waitFor(() => expect(result.current.note).toBe("Refresh failed"));
    rerender({ s: null });
    await waitFor(() => expect(result.current.note).toBeNull());
    rerender({ s: "A" });
    expect(result.current.note).toBeNull();
  });
});

describe("refreshVaultFromOf", () => {
  const qc = new QueryClient();
  beforeEach(() => { post.mockReset(); reload.mockClear(); });

  it("synced: true, grid reloaded", async () => {
    post.mockResolvedValue({});
    await expect(refreshVaultFromOf(qc, "1", null)).resolves.toBe(true);
    expect(post.mock.calls[0][0]).toBe("/admin/vault-ai/sync?account_id=1");
    expect(reload).toHaveBeenCalledOnce();
  });

  it("OF unreachable: false, grid still reloaded", async () => {
    post.mockRejectedValue(new RelayError(502, null));
    await expect(refreshVaultFromOf(qc, "1", 7)).resolves.toBe(false);
    expect(post.mock.calls[0][0]).toBe("/admin/vault-ai/sync?account_id=1&of_folder_id=7");
    expect(reload).toHaveBeenCalledOnce();
  });

  it("another failure: thrown, after the grid reloaded", async () => {
    const e = new RelayError(403, null);
    post.mockRejectedValue(e);
    await expect(refreshVaultFromOf(qc, "1", null)).rejects.toBe(e);
    expect(reload).toHaveBeenCalledOnce();
  });
});

// R3-6: what each source reloads for broken thumbnails. The mirror: its items again. The live listing (fetch-diet 17):
// every loaded page of the view on screen through the relay's age gate, page 1 first, put back in place; no cache
// drop (POST), so page 1 joins the picker open's own revalidate; a view not on screen is only marked stale.
describe("reloadBrokenThumbs", () => {
  it("mirror: the mirror's items again", async () => {
    const log: string[] = [];
    post.mockReset();
    const qc = new QueryClient();
    vi.spyOn(qc, "invalidateQueries").mockImplementation(async (f) => { log.push(`invalidate ${JSON.stringify(f?.queryKey)}`); });
    await reloadBrokenThumbs(qc, "1", "mirror");
    expect(log).toEqual(['invalidate ["vault-mirror-items","1"]']);
    expect(post).not.toHaveBeenCalled();
  });

  it("live: each loaded page read with revalidate=1, in order, and put back; no cache drop", async () => {
    post.mockReset();
    const get = relay.get as unknown as Mock;
    get.mockReset();
    get.mockImplementation(async (url: string) => ({ list: [{ id: Number(/offset=(\d+)/.exec(url)![1]) + 1 }], hasMore: true }));
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
    const shown = ["vault-media", "1", "all", null, "newest", ""];
    const hidden = ["vault-media", "1", "photo", null, "newest", ""];
    const old = { pages: [{ list: [{ id: 9 }], hasMore: true }, { list: [{ id: 8 }], hasMore: false }], pageParams: [0, 24] };
    qc.setQueryData(shown, old);
    qc.setQueryData(hidden, old);
    const unsub = new InfiniteQueryObserver(qc, {
      queryKey: shown, queryFn: async () => ({ list: [], hasMore: false }), initialPageParam: 0,
      getNextPageParam: () => undefined,
    }).subscribe(() => {});
    await reloadBrokenThumbs(qc, "1", "live");
    unsub();
    expect(post).not.toHaveBeenCalled();
    const urls = get.mock.calls.map(([u]) => u as string);
    expect(urls).toHaveLength(2);
    expect(urls.map((u) => [/offset=(\d+)/.exec(u)![1], u.includes("revalidate=1"), u.includes("type=all")]))
      .toEqual([["0", true, true], ["24", true, true]]);
    expect(qc.getQueryData(shown)).toEqual({
      pages: [{ list: [{ id: 1 }], hasMore: true }, { list: [{ id: 25 }], hasMore: true }], pageParams: [0, 24],
    });
    expect(qc.getQueryData(hidden)).toEqual(old);
    expect(qc.getQueryState(hidden)?.isInvalidated).toBe(true);
  });
});
