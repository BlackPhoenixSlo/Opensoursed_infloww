/**
 * useChatMessages — merge-on-poll (frontend-review-lows fix).
 *
 * Pre-fix the background refetchInterval poll did `return list`, so React
 * Query overwrote the whole cache with just the freshest top page — wiping any
 * load-older pages the user had scrolled up to fetch AND any in-flight
 * optimistic rows. The fix folds the fresh top page INTO the existing cache
 * (mergeTopPage): fresh wins for overlapping ids, older loaded pages stay in
 * front, optimistic / just-arrived rows stay at the tail, and nothing
 * duplicates.
 *
 * These tests drive the real hook through that exact sequence — cold fetch →
 * load-older → optimistic append → poll/refetch — and assert the cache the
 * poll leaves behind. Against the pre-fix `return list` the older pages and
 * the optimistic row would be gone, so the central test fails there.
 */
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";
import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { mergeOlderPage, mergeTopPage, orderThread, prefetchChatMessages, selectMessages, useChatMessages } from "@/hooks/useChatMessages";
import type { OFMessage, OFMessagesResp } from "@/lib/relay";
import { UNREAD_WARM_REUSE_MS } from "@/hooks/useUnreadMessagesPrefetch";

// The hook talks to the relay + an SSE event bus + a perf logger. Stub them all
// so the test only exercises the cache-merge contract.
vi.mock("@/lib/relay", () => ({ relay: { get: vi.fn() } }));
vi.mock("@/lib/events", () => ({
  eventBus: { isConnected: () => false, onStateChange: () => () => {} },
}));
vi.mock("@/lib/perfLog", () => ({
  perfOpId: () => "op",
  perfLog: () => {},
  perfDelivered: () => {},
  perfError: () => {},
  perfPaintPending: () => {},
  perfPaintOnce: () => {},
}));

import { relay } from "@/lib/relay";
const relayGet = relay.get as unknown as Mock;

const ACCT = "acct1";
const FAN = 42;
const KEY = ["messages", ACCT, FAN] as const;

function msg(id: number | string, over: Partial<OFMessage> = {}): OFMessage {
  return {
    id,
    text: `m${id}`,
    fromUser: { id: 7 },
    createdAt: "2026-06-04T12:00:00.000Z",
    media: [],
    ...over,
  } as OFMessage;
}

// The relay returns OF's newest-first ("desc") order; the hook reverses it to
// oldest→newest before caching.
function resp(descRows: OFMessage[], hasMore = true) {
  return { list: descRows, hasMore };
}

let client: QueryClient;
function wrapper({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

const ids = (rows?: OFMessage[]) => (rows ?? []).map((m) => String(m.id));

/** A read that never answers, failing once aborted as the real client's does,
 *  so the prefetch it holds ends (and unmarks its thread) when cancelled. */
const heldUntilAborted = (signal?: AbortSignal) => new Promise((_r, reject) => {
  signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")));
});

beforeEach(() => {
  client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  relayGet.mockReset();
});
afterEach(() => { cleanup(); });

describe("useChatMessages merge-on-poll", () => {
  it("cold fetch into an empty cache stores the page as-is (oldest→newest)", async () => {
    relayGet.mockResolvedValue(resp([msg(5), msg(4), msg(3)], true));
    renderHook(() => useChatMessages({ accountId: ACCT, fanId: FAN }), { wrapper });
    await waitFor(() => expect(client.getQueryData<OFMessage[]>(KEY)).toBeDefined());
    expect(ids(client.getQueryData<OFMessage[]>(KEY))).toEqual(["3", "4", "5"]);
  });

  it("a poll merges the fresh top page WITHOUT dropping older pages or optimistic rows", async () => {
    // 1) cold fetch → cache = [3,4,5]
    let top = resp([msg(5), msg(4), msg(3)], true);
    const older = resp([msg(2), msg(1)], false);
    relayGet.mockImplementation((url: string) =>
      Promise.resolve(url.includes("before_id=") ? older : top),
    );
    const { result } = renderHook(
      () => useChatMessages({ accountId: ACCT, fanId: FAN }),
      { wrapper },
    );
    await waitFor(() => expect(ids(client.getQueryData(KEY))).toEqual(["3", "4", "5"]));

    // 2) scroll-up load-older → cache = [1,2,3,4,5]
    await act(async () => { await result.current.loadOlder(); });
    expect(ids(client.getQueryData(KEY))).toEqual(["1", "2", "3", "4", "5"]);

    // 3) optimistic send appends a pending negative-id row at the tail.
    act(() => {
      result.current.appendLocal(msg(-1, { _tempId: -1, _pending: true, text: "sending…" }));
    });
    expect(ids(client.getQueryData(KEY))).toEqual(["1", "2", "3", "4", "5", "-1"]);

    // 4) the background poll returns a fresh top page: id 5 edited, new id 6,
    //    overlapping 3/4. A bare `return list` would clobber the cache down to
    //    just this page — wiping the older pages [1,2] and the optimistic row.
    top = resp([msg(6), msg(5, { text: "EDITED" }), msg(4), msg(3)], true);
    await act(async () => { await result.current.refetch(); });

    const after = client.getQueryData<OFMessage[]>(KEY);
    // older pages kept in front, fresh page in the middle, optimistic at tail.
    expect(ids(after)).toEqual(["1", "2", "3", "4", "5", "6", "-1"]);
    // no duplicate ids survived the merge.
    expect(new Set(ids(after)).size).toBe(ids(after).length);
    // fresh wins for the overlapping id.
    expect(after!.find((m) => String(m.id) === "5")!.text).toBe("EDITED");
    // the optimistic row is still pending (not wiped by the poll).
    expect(after!.find((m) => m._tempId === -1)?._pending).toBe(true);
  });

  it("gap-heal: load-older cursors from the FETCHED pages, not a persisted old block", async () => {
    // The Asian-yakuza shape (fan 800000667): a persisted localStorage cache
    // restores welcome-era rows (ids 1,2), then the head fetch lands [100,101]
    // — leaving an unfetched gap 3..99. Pre-fix loadOlder cursored off the
    // cache MINIMUM (1): OF answered "nothing older than the first message",
    // hasMore latched false, and the UI painted "Start of conversation." over
    // an invisible two-day hole. Post-fix the cursor is the oldest FETCHED id
    // (100), so scrolling up walks INTO the gap and heals it, id-ordered.
    // Backdate the restored snapshot past staleTime so mounting refetches the
    // head page — matching the real persisted-cache flow (restored data is
    // hours old, the head fetch always fires on open).
    client.setQueryData(KEY, [msg(1), msg(2)], { updatedAt: Date.now() - 60_000 });
    relayGet.mockImplementation((url: string) => {
      if (url.includes("before_id=100")) {
        return Promise.resolve(resp([msg(99), msg(98)], true)); // the gap page
      }
      if (url.includes("before_id=")) {
        // before_id=1 (the pre-fix dead-end): nothing predates the welcome.
        return Promise.resolve(resp([], false));
      }
      return Promise.resolve(resp([msg(101), msg(100)], true)); // head page
    });
    const { result } = renderHook(
      () => useChatMessages({ accountId: ACCT, fanId: FAN }),
      { wrapper },
    );
    await waitFor(() =>
      expect(ids(client.getQueryData(KEY))).toEqual(["1", "2", "100", "101"]));

    await act(async () => { await result.current.loadOlder(); });

    // Cursor must have been the fetched 100, not the cached 1 — the gap page
    // landed and slotted between the persisted block and the head page.
    const olderCalls = relayGet.mock.calls
      .map((c) => String(c[0])).filter((u) => u.includes("before_id="));
    expect(olderCalls).toHaveLength(1);
    expect(olderCalls[0]).toContain("before_id=100");
    expect(ids(client.getQueryData(KEY))).toEqual(["1", "2", "98", "99", "100", "101"]);
    // hasMore stays true — the walk continues into the rest of the gap
    // instead of latching "Start of conversation".
    expect(result.current.hasOlder).toBe(true);
  });

  it("a new chat in the same hook starts its own cursor and hasMore (the OF mirror keeps one instance across chats)", async () => {
    const B = 43;
    relayGet.mockImplementation((url: string) => {
      if (url.includes(`/chats/${FAN}/`)) return Promise.resolve(resp(url.includes("before_id=") ? [] : [msg(201), msg(200)], false));
      if (url.includes("before_id=")) return Promise.resolve(resp([msg(9)], true));
      return Promise.resolve(resp([msg(11), msg(10)], true));
    });
    const { result, rerender } = renderHook(
      ({ fanId }: { fanId: number }) => useChatMessages({ accountId: ACCT, fanId }),
      { wrapper, initialProps: { fanId: FAN } },
    );
    await waitFor(() => expect(ids(result.current.data)).toEqual(["200", "201"]));
    expect(result.current.hasOlder).toBe(false); // chat A: OF says nothing older
    rerender({ fanId: B });
    expect(result.current.hasOlder).toBe(true); // chat B starts fresh, before its first page lands
    await waitFor(() => expect(ids(result.current.data)).toEqual(["10", "11"]));
    await act(async () => { await result.current.loadOlder(); });
    const older = relayGet.mock.calls.map((c) => String(c[0])).filter((u) => u.includes("before_id="));
    expect(older).toEqual([`/api/of/v2/chats/${B}/messages?limit=30&order=desc&before_id=10`]); // B's cursor, never A's 200
    expect(ids(client.getQueryData(["messages", ACCT, B]))).toEqual(["9", "10", "11"]);
  });

  it("a poll that exactly overlaps the cache neither duplicates nor reorders", async () => {
    relayGet.mockResolvedValue(resp([msg(5), msg(4), msg(3)], true));
    const { result } = renderHook(
      () => useChatMessages({ accountId: ACCT, fanId: FAN }),
      { wrapper },
    );
    await waitFor(() => expect(ids(client.getQueryData(KEY))).toEqual(["3", "4", "5"]));

    await act(async () => { await result.current.refetch(); });

    // Same ids, same order, no growth from the overlap.
    expect(ids(client.getQueryData(KEY))).toEqual(["3", "4", "5"]);
  });
});

// The load-older pager (olderPager.ts) as the hook drives it: bounded requests,
// a Retry state instead of a hot loop, sticky exhaustion.
describe("useChatMessages load-older pager", () => {
  const olderUrls = () => relayGet.mock.calls.map((c) => String(c[0])).filter((u) => u.includes("before_id="));
  const mount = (fanId = FAN) => renderHook(
    ({ f }: { f: number }) => useChatMessages({ accountId: ACCT, fanId: f }), { wrapper, initialProps: { f: fanId } },
  );

  it("a hung older page is aborted at 15 s: the pager shows Retry, and Retry loads", async () => {
    let stall = true;
    relayGet.mockImplementation((url: string, _ctx: unknown, signal?: AbortSignal) => {
      if (!url.includes("before_id=")) return Promise.resolve(resp([msg(11), msg(10)], true));
      if (stall) return new Promise((_r, reject) => signal?.addEventListener("abort", () => reject(signal.reason)));
      return Promise.resolve(resp([msg(9)], true));
    });
    const { result } = mount();
    await waitFor(() => expect(ids(result.current.data)).toEqual(["10", "11"]));
    vi.useFakeTimers();
    try {
      let p!: Promise<unknown>;
      act(() => { p = result.current.loadOlder(); });
      expect(result.current.isLoadingOlder).toBe(true);
      const signal = relayGet.mock.calls.at(-1)?.[2] as AbortSignal;
      expect(signal).toBeInstanceOf(AbortSignal);
      await act(async () => { vi.advanceTimersByTime(14_999); });
      expect(result.current.isLoadingOlder).toBe(true);
      await act(async () => {
        vi.advanceTimersByTime(1);
        await expect(p).rejects.toMatchObject({ name: "TimeoutError" });
      });
      expect(signal.aborted).toBe(true);
      expect(result.current.isLoadingOlder).toBe(false);
      expect(result.current.olderFailed).toBe(true);
      expect(result.current.hasOlder).toBe(true);
    } finally {
      vi.useRealTimers();
    }
    stall = false;
    await act(async () => { await result.current.loadOlder(); });
    expect(result.current.olderFailed).toBe(false);
    expect(ids(result.current.data)).toEqual(["9", "10", "11"]);
  });

  it.each<[string, () => Promise<OFMessagesResp>]>([
    ["a 502", () => Promise.reject(Object.assign(new Error("502"), { status: 502 }))],
    ["an empty page that still says hasMore", () => Promise.resolve(resp([], true))],
    ["a page that does not get below the cursor", () => Promise.resolve(resp([msg(11), msg(10)], true))],
  ])("%s leaves the pager in Retry, not loading or idle (no auto re-fire)", async (_name, older) => {
    relayGet.mockImplementation((url: string) =>
      url.includes("before_id=") ? older() : Promise.resolve(resp([msg(11), msg(10)], true)));
    const { result } = mount();
    await waitFor(() => expect(ids(result.current.data)).toEqual(["10", "11"]));
    await act(async () => { await result.current.loadOlder().catch(() => {}); });
    expect(result.current).toMatchObject({ olderFailed: true, isLoadingOlder: false, hasOlder: true });
    expect(olderUrls()).toHaveLength(1);
  });

  it("an exhausted chat stays exhausted across a head poll that says hasMore", async () => {
    relayGet.mockImplementation((url: string) => Promise.resolve(
      url.includes("before_id=") ? resp([msg(9)], false) : resp([msg(11), msg(10)], true),
    ));
    const { result } = mount();
    await waitFor(() => expect(ids(result.current.data)).toEqual(["10", "11"]));
    await act(async () => { await result.current.loadOlder(); });
    expect(result.current.hasOlder).toBe(false);
    await act(async () => { await result.current.refetch(); }); // the poll: head says hasMore
    expect(result.current.hasOlder).toBe(false);
    await act(async () => { await result.current.loadOlder(); });
    expect(olderUrls()).toHaveLength(1); // exhausted: no second OF call
  });

  it("a chat switch aborts the old chat's older page and leaves the new chat idle", async () => {
    const B = 44;
    const signals: AbortSignal[] = [];
    relayGet.mockImplementation((url: string, _ctx: unknown, signal?: AbortSignal) => {
      if (!url.includes("before_id=")) return Promise.resolve(resp([msg(11), msg(10)], true));
      signals.push(signal!);
      return new Promise((_r, reject) => signal?.addEventListener("abort", () => reject(signal.reason)));
    });
    const { result, rerender } = mount();
    await waitFor(() => expect(ids(result.current.data)).toEqual(["10", "11"]));
    let p!: Promise<{ added: number; hasMore: boolean }>;
    act(() => { p = result.current.loadOlder(); });
    rerender({ f: B });
    await expect(p).resolves.toEqual({ added: 0, hasMore: false });
    expect(signals[0].aborted).toBe(true);
    expect(result.current).toMatchObject({ isLoadingOlder: false, olderFailed: false, hasOlder: true });
  });

  it("unmount aborts the older page in flight", async () => {
    const signals: AbortSignal[] = [];
    relayGet.mockImplementation((url: string, _ctx: unknown, signal?: AbortSignal) => {
      if (!url.includes("before_id=")) return Promise.resolve(resp([msg(11), msg(10)], true));
      signals.push(signal!);
      return new Promise(() => {});
    });
    const { result, unmount } = mount();
    await waitFor(() => expect(ids(result.current.data)).toEqual(["10", "11"]));
    act(() => { void result.current.loadOlder(); });
    unmount();
    expect(signals[0].aborted).toBe(true);
  });

  it("a mount riding a prefetch whose head page said nothing older starts exhausted (no OF read to learn it)", async () => {
    const F = 45;
    relayGet.mockResolvedValue(resp([msg(2), msg(1)], false));
    await prefetchChatMessages(client, ACCT, F, { staleTime: 60_000 });
    const { result } = renderHook(
      () => useChatMessages({ accountId: ACCT, fanId: F, prefetchWindowMs: 60_000 }), { wrapper },
    );
    expect(result.current.hasOlder).toBe(false);
    await act(async () => { await result.current.loadOlder(); });
    expect(relayGet).toHaveBeenCalledTimes(1); // the prefetch alone
  });
});

// mergeOlderPage keeps oldest→newest order even when a load-older page lands
// INSIDE a gap (cached rows exist both older and newer than it) — the blind
// prepend it replaced assumed every fetched-older row predated the whole cache.
describe("useChatMessages headSettled (the cursor is fetch-derived)", () => {
  it("a fresh cached thread this mount never read is not settled: its cursor would be the cache minimum", async () => {
    client.setQueryData(KEY, [msg(1), msg(2)], { updatedAt: Date.now() });
    const { result } = renderHook(() => useChatMessages({ accountId: ACCT, fanId: FAN }), { wrapper });
    await act(async () => { await new Promise((r) => setTimeout(r, 20)); });
    expect(relayGet).not.toHaveBeenCalled();
    expect(result.current.dataUpdatedAt).toBeGreaterThan(0);
    expect(result.current.headSettled).toBe(false);
  });

  it("this mount's own head read settles it, and a chat switch unsettles it until the new chat's read", async () => {
    let release: () => void = () => {};
    relayGet.mockResolvedValueOnce(resp([msg(5), msg(4)], true));
    const { result, rerender } = renderHook(
      ({ fan }: { fan: number }) => useChatMessages({ accountId: ACCT, fanId: fan }),
      { wrapper, initialProps: { fan: FAN } },
    );
    expect(result.current.headSettled).toBe(false);
    await waitFor(() => expect(result.current.headSettled).toBe(true));
    relayGet.mockImplementationOnce(() => new Promise((r) => { release = () => r(resp([msg(9)], true)); }));
    rerender({ fan: FAN + 1 });
    expect(result.current.headSettled).toBe(false);
    release();
    await waitFor(() => expect(result.current.headSettled).toBe(true));
  });

  it("a mount riding a prefetched head page in the cache is settled without a read of its own", async () => {
    relayGet.mockResolvedValue(resp([msg(101), msg(100)], true));
    await prefetchChatMessages(client, ACCT, FAN, { staleTime: 60_000 });
    relayGet.mockClear();
    const { result } = renderHook(
      () => useChatMessages({ accountId: ACCT, fanId: FAN, prefetchWindowMs: 60_000 }), { wrapper },
    );
    expect(result.current.headSettled).toBe(true);
    expect(relayGet).not.toHaveBeenCalled();
  });
});

describe("prefetchChatMessages", () => {
  it("opening the chat mid-prefetch cancels the background read and refetches on the user lane", async () => {
    const signals: (AbortSignal | undefined)[] = [];
    relayGet.mockImplementation((_path: string, ctx: { priority?: string }, signal?: AbortSignal) => {
      signals.push(signal);
      if (ctx.priority === "background") return heldUntilAborted(signal);
      return Promise.resolve(resp([msg(2), msg(1)], false));
    });
    void prefetchChatMessages(client, ACCT, FAN);
    await waitFor(() => expect(relayGet).toHaveBeenCalledTimes(1));

    renderHook(() => useChatMessages({ accountId: ACCT, fanId: FAN }), { wrapper });

    await waitFor(() => expect(ids(client.getQueryData(KEY))).toEqual(["1", "2"]));
    expect(relayGet.mock.calls.map((c) => c[1])).toEqual([
      { accountId: ACCT, priority: "background" },
      { accountId: ACCT },
    ]);
    expect(signals[0]?.aborted).toBe(true);
  });

  it("a live message cached mid-prefetch (dated 0: not a read) still moves the read to the user lane, and survives it", async () => {
    const signals: (AbortSignal | undefined)[] = [];
    let land!: () => void;
    relayGet.mockImplementation((_path: string, ctx: { priority?: string }, signal?: AbortSignal) => {
      signals.push(signal);
      if (ctx.priority === "background") return heldUntilAborted(signal);
      return new Promise((r) => { land = () => r(resp([msg(2), msg(1)], true)); });
    });
    void prefetchChatMessages(client, ACCT, FAN);
    await waitFor(() => expect(relayGet).toHaveBeenCalledTimes(1));
    // What useInboxRealtime writes for a live message during a first read.
    client.setQueryData(KEY, [msg(3, { createdAt: "2026-06-04T13:00:00.000Z" })], { updatedAt: 0 });

    renderHook(() => useChatMessages({ accountId: ACCT, fanId: FAN }), { wrapper });
    await waitFor(() => expect(relayGet).toHaveBeenCalledTimes(2));
    expect(signals[0]?.aborted).toBe(true);
    expect(relayGet.mock.calls[1][1]).toEqual({ accountId: ACCT });
    expect(ids(client.getQueryData(KEY))).toEqual(["3"]);

    land();
    await waitFor(() => expect(ids(client.getQueryData(KEY))).toEqual(["1", "2", "3"]));
  });

  it("a prefetch that doesn't yield on open (a Fan List press) is joined, not cancelled", async () => {
    let land!: () => void;
    relayGet.mockImplementation(() => new Promise((r) => { land = () => r(resp([msg(2), msg(1)], false)); }));
    void prefetchChatMessages(client, ACCT, FAN, { yieldOnOpen: false });
    await waitFor(() => expect(relayGet).toHaveBeenCalledTimes(1));

    renderHook(() => useChatMessages({ accountId: ACCT, fanId: FAN }), { wrapper });
    await act(async () => { await new Promise((r) => setTimeout(r, 20)); });
    land();
    await waitFor(() => expect(ids(client.getQueryData(KEY))).toEqual(["1", "2"]));
    expect(relayGet).toHaveBeenCalledTimes(1);
  });

  it("lets the prefetch finish when the opened chat has a read thread already", async () => {
    relayGet.mockResolvedValueOnce(resp([msg(1)], false));
    await prefetchChatMessages(client, ACCT, FAN);
    let release!: () => void;
    const signals: (AbortSignal | undefined)[] = [];
    relayGet.mockImplementation((_path: string, _ctx: unknown, signal?: AbortSignal) => {
      signals.push(signal);
      return new Promise((r) => { release = () => r(resp([msg(2), msg(1)], false)); });
    });
    relayGet.mockClear();
    void prefetchChatMessages(client, ACCT, FAN, { staleTime: 0 });
    await waitFor(() => expect(relayGet).toHaveBeenCalledTimes(1));

    renderHook(() => useChatMessages({ accountId: ACCT, fanId: FAN }), { wrapper });
    release();

    await waitFor(() => expect(ids(client.getQueryData(KEY))).toEqual(["1", "2"]));
    expect(relayGet).toHaveBeenCalledTimes(1);
    expect(signals[0]?.aborted).toBe(false);
  });

  it("a 60 s prefetch window keeps a 30 s-old thread fresh for both the prefetch and the mount", async () => {
    client.setQueryData(KEY, [msg(1)], { updatedAt: Date.now() - 30_000 });
    relayGet.mockResolvedValue(resp([msg(2), msg(1)], false));
    await prefetchChatMessages(client, ACCT, FAN, { staleTime: 60_000 });
    const { result } = renderHook(
      () => useChatMessages({ accountId: ACCT, fanId: FAN, prefetchWindowMs: 60_000 }), { wrapper },
    );
    await waitFor(() => expect(ids(result.current.data)).toEqual(["1"]));
    await act(async () => { await new Promise((r) => setTimeout(r, 20)); });
    expect(relayGet).not.toHaveBeenCalled();
  });

  it("a mount that rides a prefetched head page cursors load-older from that page, not a cached old block below a gap", async () => {
    client.setQueryData(KEY, [msg(1), msg(2)], { updatedAt: Date.now() - 120_000 });
    relayGet.mockImplementation((url: string) => Promise.resolve(
      url.includes("before_id=") ? resp([msg(99), msg(98)], true) : resp([msg(101), msg(100)], true),
    ));
    await prefetchChatMessages(client, ACCT, FAN, { staleTime: 60_000 });
    expect(ids(client.getQueryData(KEY))).toEqual(["1", "2", "100", "101"]);

    const { result } = renderHook(
      () => useChatMessages({ accountId: ACCT, fanId: FAN, prefetchWindowMs: 60_000 }), { wrapper },
    );
    await act(async () => { await result.current.loadOlder(); });
    const calls = relayGet.mock.calls.map((c) => String(c[0]));
    expect(calls.filter((u) => !u.includes("before_id="))).toHaveLength(1); // the prefetch alone
    expect(calls.filter((u) => u.includes("before_id="))).toEqual([
      `/api/of/v2/chats/${FAN}/messages?limit=30&order=desc&before_id=100`,
    ]);
  });

  it("an inbox reopen inside UNREAD_WARM_REUSE_MS scrolls up from the unread warm's head page, not from the first open's deeper pages below the gap (fetch-diet 16)", async () => {
    const pages: Record<string, OFMessagesResp> = {
      head1: resp([msg(101), msg(100)], true), "100": resp([msg(99), msg(98)], true),
      head2: resp([msg(121), msg(120)], true), "120": resp([msg(119), msg(118)], true),
    };
    let head = "head1";
    relayGet.mockImplementation((url: string) =>
      Promise.resolve(pages[url.match(/before_id=(\d+)/)?.[1] ?? head]));
    const open = () => renderHook(
      () => useChatMessages({ accountId: ACCT, fanId: FAN, prefetchWindowMs: UNREAD_WARM_REUSE_MS }), { wrapper });

    const first = open();
    await waitFor(() => expect(ids(client.getQueryData(KEY))).toEqual(["100", "101"]));
    await act(async () => { await first.result.current.loadOlder(); });
    first.unmount();
    // 20 Fan DMs later the unread warm reads the head again (thread stale by then).
    head = "head2";
    await prefetchChatMessages(client, ACCT, FAN, { staleTime: 0 });
    relayGet.mockClear();

    const reopened = open();
    await act(async () => { await reopened.result.current.loadOlder(); });
    expect(relayGet.mock.calls.map((c) => String(c[0]))).toEqual([
      `/api/of/v2/chats/${FAN}/messages?limit=30&order=desc&before_id=120`,
    ]);
  });

  it("a mount with no prefetch window (no prefetchWindowMs) cursors load-older from the cache minimum, as before", async () => {
    client.setQueryData(KEY, [msg(1), msg(2)], { updatedAt: Date.now() - 120_000 });
    relayGet.mockImplementation((url: string) => Promise.resolve(
      url.includes("before_id=") ? resp([], false) : resp([msg(101), msg(100)], true),
    ));
    await prefetchChatMessages(client, ACCT, FAN);
    const { result } = renderHook(() => useChatMessages({ accountId: ACCT, fanId: FAN }), { wrapper });
    expect(result.current.olderCursor()).toBe(1);
  });

  it("without one, the 15 s default refetches that thread", async () => {
    client.setQueryData(KEY, [msg(1)], { updatedAt: Date.now() - 30_000 });
    relayGet.mockResolvedValue(resp([msg(2), msg(1)], false));
    await prefetchChatMessages(client, ACCT, FAN);
    expect(relayGet).toHaveBeenCalledTimes(1);
  });
});

describe("mergeOlderPage", () => {
  it("the common no-gap page prepends below existing history", () => {
    expect(ids(mergeOlderPage([msg(3), msg(4)], [msg(1), msg(2)])))
      .toEqual(["1", "2", "3", "4"]);
  });

  it("a page landing inside a gap slots id-ordered between the blocks", () => {
    expect(ids(mergeOlderPage([msg(1), msg(100)], [msg(50), msg(51)])))
      .toEqual(["1", "50", "51", "100"]);
  });

  it("returns the SAME prev reference for an empty page", () => {
    const prev = [msg(1), msg(2)];
    expect(mergeOlderPage(prev, [])).toBe(prev);
  });

  it("overlapping ids dedupe (FRESH row wins), new ones insert", () => {
    // Fresh-wins is the same doctrine as mergeTopPage and it is what lets an
    // OF page upgrade a media-less mirror-seeded row. Cache-wins here (the
    // old rule) froze scrolled-up history in its seed form forever.
    const cached = msg(2, { media: [] });
    const fresh = msg(2, { media: [{ id: 9, type: "photo" }] });
    const merged = mergeOlderPage([cached, msg(3)], [msg(1), fresh]);
    expect(ids(merged)).toEqual(["1", "2", "3"]);
    expect(merged.find((m) => String(m.id) === "2")).toBe(fresh);
  });

  it("optimistic + mass-placeholder rows keep their tail position", () => {
    const prev = [
      msg(1),
      msg(100),
      msg(5_000_000_000_000_042), // mass placeholder — tail-pinned
      msg(-1, { _tempId: -1, _pending: true }),
    ];
    expect(ids(mergeOlderPage(prev, [msg(50)])))
      .toEqual(["1", "50", "100", "5000000000000042", "-1"]);
  });

  // plans/blast-splice B.3 — an unsent mass message is immortal below the head
  // page without this: the local seed paints it, a 4h-old blast is far older than
  // the 30-row head page, so the one merge that could retire it never sees it.
  it("drops a cached real row the page covers but does not contain", () => {
    const prev = [msg(10), msg(20), msg(30)];
    // The fetched page spans [10, 30] and does NOT contain 20 → gone on OF.
    expect(ids(mergeOlderPage(prev, [msg(10), msg(30)])))
      .toEqual(["10", "30"]);
  });

  it("keeps cached rows OUTSIDE the fetched id range, drops only the one inside", () => {
    // 5 is below the page's floor and 99 above its ceiling — neither absence is
    // evidence of anything, and dropping them would delete a gap the cursor has
    // not walked yet. 20 sits inside [10, 30] and the page does not have it.
    const prev = [msg(5), msg(20), msg(99)];
    expect(ids(mergeOlderPage(prev, [msg(10), msg(30)])))
      .toEqual(["5", "10", "30", "99"]);
  });

  it("leaves placeholders, tips and optimistic rows alone inside the range", () => {
    // None of these can ever come back from an OF page, so their absence from
    // one says nothing. A tip's 6e15 id sorts by created_at, hence the stamp.
    const prev = [
      msg(10),
      msg(5_000_000_000_000_042),
      msg(6_000_000_000_000_042, { isTip: true, createdAt: "2026-06-04T12:00:01.000Z" }),
      msg(-1, { _tempId: -1, _pending: true }),
      msg(30),
    ];
    expect(ids(mergeOlderPage(prev, [msg(10), msg(30)])))
      .toEqual(["10", "30", "6000000000000042", "5000000000000042", "-1"]);
  });

  it("a synthetic row IN THE PAGE cannot stretch the range over the thread", () => {
    // THE PINNED OUTLIER, written down because the rule rests on it: if a 5e15
    // placeholder counted toward `max`, every cached real row above the page
    // would look deleted and the whole thread above it would vanish.
    const prev = [msg(10), msg(20), msg(4_000_000_000_000)];
    const page = [msg(10), msg(5_000_000_000_000_042)];
    expect(ids(mergeOlderPage(prev, page)))
      .toEqual(["10", "20", "4000000000000", "5000000000000042"]);
  });

  it("a tip row slots by created_at among the loaded history, not the tail", () => {
    // A tip dated between msg(1) and msg(100) belongs in the middle — its 6e15
    // id must not exile it to the bottom (the bug that hid sales on scroll).
    const prev = [
      msg(1, { createdAt: "2026-06-01T09:00:00.000Z" }),
      msg(100, { createdAt: "2026-06-03T09:00:00.000Z" }),
      msg(-1, { _tempId: -1, _pending: true, createdAt: "2026-06-04T09:00:00.000Z" }),
    ];
    const tip = msg(6_000_000_000_000_042, {
      isTip: true, createdAt: "2026-06-02T09:00:00.000Z",
    });
    expect(ids(mergeOlderPage(prev, [tip])))
      .toEqual(["1", "6000000000000042", "100", "-1"]);
  });
});

// orderThread is the canonical ordering primitive both merges delegate to:
// real rows + ledger tips (6e15) by created_at (id tie-break), optimistic and
// mass placeholders pinned at the tail.
describe("orderThread", () => {
  it("sorts real rows by created_at, id-tie-break on equal timestamps", () => {
    // Equal timestamps → id order (== time order for real OF rows).
    const out = orderThread([msg(7), msg(3), msg(5)]);
    expect(ids(out)).toEqual(["3", "5", "7"]);
  });

  it("returns the SAME reference when already ordered (structural sharing)", () => {
    const rows = [msg(3), msg(5), msg(7)];
    expect(orderThread(rows)).toBe(rows);
  });

  it("slots a tip into time position and tail-pins optimistic + placeholders", () => {
    const rows = [
      msg(10, { createdAt: "2026-06-01T00:00:00.000Z" }),
      msg(30, { createdAt: "2026-06-03T00:00:00.000Z" }),
      msg(6_000_000_000_000_001, { createdAt: "2026-06-02T00:00:00.000Z", isTip: true }),
      msg(5_000_000_000_000_001), // mass placeholder → tail
      msg(-1, { _tempId: -1 }),   // optimistic → tail
    ];
    expect(ids(orderThread(rows))).toEqual([
      "10", "6000000000000001", "30", "5000000000000001", "-1",
    ]);
  });

  it("naive-UTC (zone-less) tip timestamps normalize before comparing", () => {
    const rows = [
      msg(20, { createdAt: "2026-06-02T00:00:00.000Z" }),
      msg(6_000_000_000_000_009, { createdAt: "2026-06-01 00:00:00", isTip: true }),
    ];
    // The tip (Jun 1, naive) precedes the Jun 2 real row.
    expect(ids(orderThread(rows))).toEqual(["6000000000000009", "20"]);
  });
});

// mergeTopPage classifies a cached row not in the fresh page by its id span.
// The deleted-on-OF drop is the orphan fix: a PPV/message unsent upstream
// vanishes from OF's response but used to linger pinned to the bottom.
describe("mergeTopPage", () => {
  it("drops a cached row inside the page's id span but absent from fresh (deleted on OF)", () => {
    // msg(5) sits between fresh's min(3) and max(7) but OF didn't return it → gone.
    const out = mergeTopPage([msg(3), msg(5), msg(7)], [msg(3), msg(7)]);
    expect(ids(out)).toEqual(["3", "7"]);
  });

  it("the Adrian orphan case: an in-range unsent row at the tail is dropped, not kept", () => {
    // Real shape: a morning opener/PPV (id 100) the fan-thread fetch still spans
    // (min 50 .. max 200) but OF no longer returns → drop.
    const out = mergeTopPage(
      [msg(100), msg(150), msg(200)],
      [msg(50), msg(150), msg(200)],
    );
    expect(ids(out)).toEqual(["50", "150", "200"]);
    expect(ids(out)).not.toContain("100");
  });

  it("keeps scrolled-up history below the page (id < minFreshId) at the front", () => {
    const out = mergeTopPage([msg(1), msg(2)], [msg(5), msg(6)]);
    expect(ids(out)).toEqual(["1", "2", "5", "6"]);
  });

  it("keeps a newer-than-page race row (id > maxFreshId) at the tail", () => {
    const out = mergeTopPage([msg(9)], [msg(5), msg(6)]);
    expect(ids(out)).toEqual(["5", "6", "9"]);
  });

  it("keeps an in-flight optimistic row (id <= 0) at the tail, never drops it", () => {
    const out = mergeTopPage([msg(-1)], [msg(5)]);
    expect(ids(out)).toEqual(["5", "-1"]);
  });

  it("an empty/failed fetch never nukes the cache", () => {
    const out = mergeTopPage([msg(3), msg(5)], []);
    expect(ids(out)).toEqual(["3", "5"]);
  });

  it("combined: keep history, drop the deleted middle, keep the race row", () => {
    const out = mergeTopPage([msg(1), msg(4), msg(9)], [msg(3), msg(5)]);
    expect(ids(out)).toEqual(["1", "3", "5", "9"]);
  });

  it("empty prev → returns fresh unchanged", () => {
    const fresh = [msg(5), msg(6)];
    expect(mergeTopPage([], fresh)).toBe(fresh);
  });
});

// Mass-broadcast placeholders (service/attribution.py's 5e15 id band, seeded
// via /admin/messages or emit_live SSE) sit above every real OF id, so the
// id-span drop can never retire one — pre-fix they rode the "newer than the
// page" branch forever and long-unsent ppv_send blasts haunted the thread
// whenever a chat opened through the DB seed (e.g. from a notification).
// mergeTopPage now judges the band by TIME: once fresh proves the thread past
// the placeholder's send time (+10min queue-lag grace), an uncorroborated
// placeholder is stale.
describe("mergeTopPage — mass placeholder band", () => {
  const BAND = 5_000_000_000_000_123; // any id ≥ 5e15
  const NOW = Date.parse("2026-07-02T10:00:30.000Z"); // fixed clock for the age rule

  it("drops a stale placeholder once fresh covers a later time", () => {
    const stale = msg(BAND, { createdAt: "2026-06-26T15:15:00.000Z" });
    const fresh = [
      msg(50, { createdAt: "2026-07-01T09:00:00.000Z" }),
      msg(60, { createdAt: "2026-07-02T10:00:00.000Z" }),
    ];
    expect(ids(mergeTopPage([msg(50), stale], fresh, NOW))).toEqual(["50", "60"]);
  });

  it("keeps a just-sent placeholder that is still the newest thing (live bridge)", () => {
    const justSent = msg(BAND, { createdAt: "2026-07-02T10:00:05.000Z" });
    const fresh = [msg(60, { createdAt: "2026-07-02T10:00:00.000Z" })];
    expect(ids(mergeTopPage([justSent], fresh, NOW))).toEqual(["60", String(BAND)]);
  });

  it("keeps a placeholder within the queue-lag grace window", () => {
    // Fan replied 5min after the blast was queued — inside the 10min grace,
    // the still-delivering broadcast must not be dropped.
    const queued = msg(BAND, { createdAt: "2026-07-02T10:00:00.000Z" });
    const fresh = [msg(60, { createdAt: "2026-07-02T10:05:00.000Z" })];
    expect(ids(mergeTopPage([queued], fresh, Date.parse("2026-07-02T10:05:30.000Z"))))
      .toEqual(["60", String(BAND)]);
  });

  it("quiet fan: placeholders NEWER than every real row still expire by age", () => {
    // The screenshot shape: fan silent for 9 days, six stale ppv_send
    // placeholders are the newest things in the thread. No fresh row ever
    // lands past them, so the grace rule can't fire — the 1h bridge ceiling
    // must retire them (pre-fix persisted caches kept them forever).
    const blasts = [
      msg(BAND, { createdAt: "2026-06-26T15:15:00.000Z" }),
      msg(BAND + 1, { createdAt: "2026-07-01T10:48:00.000Z" }),
    ];
    const fresh = [msg(60, { createdAt: "2026-06-23T09:00:00.000Z" })]; // 9d-old real
    expect(ids(mergeTopPage([msg(60), ...blasts], fresh, NOW))).toEqual(["60"]);
  });

  it("normalizes a zone-less (naive-UTC) placeholder timestamp before comparing", () => {
    // DB-seed rows carry tz-naive isoformat; parsed as viewer-local it could
    // skew hours either way. toUtcIso pins it to UTC → still dropped.
    const stale = msg(BAND, { createdAt: "2026-06-26 15:15:00" });
    const fresh = [msg(60, { createdAt: "2026-07-02T10:00:00.000Z" })];
    expect(ids(mergeTopPage([stale], fresh, NOW))).toEqual(["60"]);
  });

  it("an empty fetch keeps a fresh placeholder but expires one past the ceiling", () => {
    const justSent = msg(BAND, { createdAt: "2026-07-02T10:00:00.000Z" });
    const expired = msg(BAND + 1, { createdAt: "2026-06-26T15:15:00.000Z" });
    expect(ids(mergeTopPage([justSent, expired], [], NOW))).toEqual([String(BAND)]);
  });

  it("a placeholder never widens the fresh id span for real-row classification", () => {
    // If BAND ever leaked into fresh (it can't come from OF, but guard), real
    // cached rows must not be mass-dropped by an id span stretched to 5e15.
    const out = mergeTopPage(
      [msg(70, { createdAt: "2026-07-02T11:00:00.000Z" })],
      [msg(60, { createdAt: "2026-07-02T10:00:00.000Z" }), msg(BAND)],
      NOW,
    );
    expect(ids(out)).toContain("70");
  });

  it("select guard: a rehydrated poisoned cache never paints expired placeholders, even with NO successful fetch", async () => {
    // The persisted-localStorage vector: a pre-fix snapshot restores stale
    // 5e15 tails into the cache, and the OF fetch FAILS (expired session,
    // 429). mergeTopPage never runs — the query's select must filter on the
    // render path so the dead blast never reaches MessageList.
    relayGet.mockRejectedValue(new Error("of session expired"));
    const stale = msg(5_000_000_000_000_777, { createdAt: "2020-01-01T00:00:00.000Z" });
    client.setQueryData(KEY, [msg(50), stale]);
    const { result } = renderHook(
      () => useChatMessages({ accountId: ACCT, fanId: FAN }),
      { wrapper },
    );
    await waitFor(() => expect(ids(result.current.data)).toEqual(["50"]));
  });

  it("ledger-tip rows (6e15 band) are PERMANENT — never expired by the staleness rules", () => {
    // transaction_ingest._TIP_MSG_ID_BASE synthesizes inline tip bubbles at
    // 6e15+tx.id. They're months-old by design, OF can never corroborate
    // them, and the DB seed is their only render path — both staleness rules
    // (fresh-covers-later-time AND the 1h ceiling) must leave them alone. And
    // because the tip predates the fresh page, orderThread slots it BEFORE the
    // fresh row by created_at (not pinned to the id-sorted tail, which is what
    // hid March tips below today's chat and made them vanish on scroll-up).
    const oldTip = msg(6_000_000_000_000_042, {
      createdAt: "2026-04-01T09:00:00.000Z", isTip: true,
    });
    const fresh = [msg(60, { createdAt: "2026-07-02T10:00:00.000Z" })];
    expect(ids(mergeTopPage([oldTip], fresh, NOW)))
      .toEqual(["6000000000000042", "60"]);
  });

  it("a tip newer than the fresh page slots AFTER it (time order, not id-tail)", () => {
    // A tip that arrived after the newest real row belongs at the bottom — but
    // by TIME, not because its 6e15 id happens to be huge. Prove the position
    // is driven by created_at: same setup, tip now dated past the fresh row.
    const newTip = msg(6_000_000_000_000_099, {
      createdAt: "2026-07-02T10:05:00.000Z", isTip: true,
    });
    const fresh = [msg(60, { createdAt: "2026-07-02T10:00:00.000Z" })];
    expect(ids(mergeTopPage([newTip], fresh, NOW)))
      .toEqual(["60", "6000000000000099"]);
  });

  it("a tip BETWEEN two real rows lands in its chronological slot", () => {
    const tip = msg(6_000_000_000_000_050, {
      createdAt: "2026-07-02T09:30:00.000Z", isTip: true,
    });
    const fresh = [
      msg(40, { createdAt: "2026-07-02T09:00:00.000Z" }),
      msg(60, { createdAt: "2026-07-02T10:00:00.000Z" }),
    ];
    // Tip sits between the 09:00 and 10:00 messages.
    expect(ids(mergeTopPage([tip], fresh, NOW)))
      .toEqual(["40", "6000000000000050", "60"]);
  });
});

// selectMessages is the render-path guard: dedup + expired-placeholder drop
// applied to whatever the cache holds, fetch or no fetch.
describe("selectMessages", () => {
  const NOW = Date.parse("2026-07-02T12:00:00.000Z");
  const BAND = 5_000_000_000_000_123;

  it("drops an expired placeholder, keeps a fresh one, never touches tips or real rows", () => {
    const rows = [
      msg(50, { createdAt: "2026-01-01T00:00:00.000Z" }),               // real, old → keep
      msg(BAND, { createdAt: "2026-06-26T15:15:00.000Z" }),             // placeholder, expired → drop
      msg(BAND + 1, { createdAt: "2026-07-02T11:55:00.000Z" }),         // placeholder, 5min → keep
      msg(6_000_000_000_000_042, { createdAt: "2026-01-01T00:00:00.000Z", isTip: true }), // tip → keep
    ];
    expect(ids(selectMessages(rows, NOW)))
      .toEqual(["50", String(BAND + 1), "6000000000000042"]);
  });

  it("still dedups repeated ids, first occurrence wins", () => {
    const rows = [msg(5), msg(5), msg(6)];
    expect(ids(selectMessages(rows, NOW))).toEqual(["5", "6"]);
  });

  it("returns the SAME reference when nothing changed (structural sharing)", () => {
    const rows = [msg(5), msg(6)];
    expect(selectMessages(rows, NOW)).toBe(rows);
  });
});
