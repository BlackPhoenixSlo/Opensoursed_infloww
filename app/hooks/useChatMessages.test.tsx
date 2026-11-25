import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";
import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { mergeOlderPage, mergeTopPage, orderThread, prefetchChatMessages, selectMessages, useChatMessages } from "@/hooks/useChatMessages";
import type { OFMessage, OFMessagesResp } from "@/lib/relay";
import { THREAD_KEEP } from "@/lib/threadCache";
import { setPlatform } from "@/lib/platform";
import { UNREAD_WARM_REUSE_MS } from "@/hooks/useUnreadMessagesPrefetch";

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

function resp(descRows: OFMessage[], hasMore = true) {
  return { list: descRows, hasMore };
}

let client: QueryClient;
function wrapper({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

const ids = (rows?: OFMessage[]) => (rows ?? []).map((m) => String(m.id));

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

    await act(async () => { await result.current.loadOlder(); });
    expect(ids(client.getQueryData(KEY))).toEqual(["1", "2", "3", "4", "5"]);

    act(() => {
      result.current.appendLocal(msg(-1, { _tempId: -1, _pending: true, text: "sending…" }));
    });
    expect(ids(client.getQueryData(KEY))).toEqual(["1", "2", "3", "4", "5", "-1"]);

    top = resp([msg(6), msg(5, { text: "EDITED" }), msg(4), msg(3)], true);
    await act(async () => { await result.current.refetch(); });

    const after = client.getQueryData<OFMessage[]>(KEY);
    expect(ids(after)).toEqual(["1", "2", "3", "4", "5", "6", "-1"]);
    expect(new Set(ids(after)).size).toBe(ids(after).length);
    expect(after!.find((m) => String(m.id) === "5")!.text).toBe("EDITED");
    expect(after!.find((m) => m._tempId === -1)?._pending).toBe(true);
  });

  it("gap-heal: load-older cursors from the FETCHED pages, not a persisted old block", async () => {
    client.setQueryData(KEY, [msg(1), msg(2)], { updatedAt: Date.now() - 60_000 });
    relayGet.mockImplementation((url: string) => {
      if (url.includes("before_id=100")) {
        return Promise.resolve(resp([msg(99), msg(98)], true));
      }
      if (url.includes("before_id=")) {
        return Promise.resolve(resp([], false));
      }
      return Promise.resolve(resp([msg(101), msg(100)], true));
    });
    const { result } = renderHook(
      () => useChatMessages({ accountId: ACCT, fanId: FAN }),
      { wrapper },
    );
    await waitFor(() =>
      expect(ids(client.getQueryData(KEY))).toEqual(["1", "2", "100", "101"]));

    await act(async () => { await result.current.loadOlder(); });

    const olderCalls = relayGet.mock.calls
      .map((c) => String(c[0])).filter((u) => u.includes("before_id="));
    expect(olderCalls).toHaveLength(1);
    expect(olderCalls[0]).toContain("before_id=100");
    expect(ids(client.getQueryData(KEY))).toEqual(["1", "2", "98", "99", "100", "101"]);
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
    expect(result.current.hasOlder).toBe(false);
    rerender({ fanId: B });
    expect(result.current.hasOlder).toBe(true);
    await waitFor(() => expect(ids(result.current.data)).toEqual(["10", "11"]));
    await act(async () => { await result.current.loadOlder(); });
    const older = relayGet.mock.calls.map((c) => String(c[0])).filter((u) => u.includes("before_id="));
    expect(older).toEqual([`/api/of/v2/chats/${B}/messages?limit=30&order=desc&before_id=10`]);
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

    expect(ids(client.getQueryData(KEY))).toEqual(["3", "4", "5"]);
  });
});

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

  it("an older page's rows and the idle pager commit in one render (no idle frame over the old rows)", async () => {
    relayGet.mockImplementation((url: string) => Promise.resolve(
      url.includes("before_id=") ? resp([msg(9), msg(8)], true) : resp([msg(11), msg(10)], true),
    ));
    const seen: string[] = [];
    const { result } = renderHook(() => {
      const h = useChatMessages({ accountId: ACCT, fanId: FAN });
      seen.push(`${h.isLoadingOlder}:${ids(h.data).join(",")}`);
      return h;
    }, { wrapper });
    await waitFor(() => expect(ids(result.current.data)).toEqual(["10", "11"]));
    seen.length = 0;
    const prevAct = (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT;
    (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = false;
    try {
      await result.current.loadOlder();
      await waitFor(() => expect(seen.at(-1)).toBe("false:8,9,10,11"));
    } finally {
      (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = prevAct;
    }
    expect(seen).not.toContain("false:10,11");
    expect(seen.at(-1)).toBe("false:8,9,10,11");
  });

  it("an exhausted chat stays exhausted across a head poll that says hasMore", async () => {
    relayGet.mockImplementation((url: string) => Promise.resolve(
      url.includes("before_id=") ? resp([msg(9)], false) : resp([msg(11), msg(10)], true),
    ));
    const { result } = mount();
    await waitFor(() => expect(ids(result.current.data)).toEqual(["10", "11"]));
    await act(async () => { await result.current.loadOlder(); });
    expect(result.current.hasOlder).toBe(false);
    await act(async () => { await result.current.refetch(); });
    expect(result.current.hasOlder).toBe(false);
    await act(async () => { await result.current.loadOlder(); });
    expect(olderUrls()).toHaveLength(1);
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
    expect(relayGet).toHaveBeenCalledTimes(1);
  });
});

describe("useChatMessages trim on leave", () => {
  const many = (from: number, to: number) => Array.from({ length: to - from + 1 }, (_, i) => msg(from + i));
  const tick = () => act(async () => { await new Promise((r) => setTimeout(r, 0)); });

  beforeEach(() => {
    client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity, staleTime: Infinity } } });
  });

  it("leaving a deep-scrolled chat trims it to THREAD_KEEP newest rows plus optimistic ones, dataUpdatedAt kept", async () => {
    client.setQueryData(KEY, [...many(1, 300), msg(-1, { _tempId: -1, _pending: true })], { updatedAt: 1234 });
    const { unmount } = renderHook(() => useChatMessages({ accountId: ACCT, fanId: FAN }), { wrapper });
    unmount();
    await tick();
    const rows = client.getQueryData<OFMessage[]>(KEY)!;
    expect(rows).toHaveLength(THREAD_KEEP + 1);
    expect(ids(rows).slice(0, 2)).toEqual([String(300 - THREAD_KEEP + 1), String(300 - THREAD_KEEP + 2)]);
    expect(ids(rows).at(-1)).toBe("-1");
    expect(client.getQueryState(KEY)?.dataUpdatedAt).toBe(1234);
  });

  it("a chat switch trims the chat left behind, not the one opened", async () => {
    const B = 46;
    client.setQueryData(KEY, many(1, 200));
    client.setQueryData(["messages", ACCT, B], many(1, 200));
    const { rerender } = renderHook(
      ({ f }: { f: number }) => useChatMessages({ accountId: ACCT, fanId: f }), { wrapper, initialProps: { f: FAN } },
    );
    rerender({ f: B });
    await tick();
    expect(client.getQueryData<OFMessage[]>(KEY)).toHaveLength(THREAD_KEEP);
    expect(client.getQueryData<OFMessage[]>(["messages", ACCT, B])).toHaveLength(200);
  });

  it("a thread another pane still shows keeps its rows", async () => {
    client.setQueryData(KEY, many(1, 200));
    const other = renderHook(() => useChatMessages({ accountId: ACCT, fanId: FAN }), { wrapper });
    const { unmount } = renderHook(() => useChatMessages({ accountId: ACCT, fanId: FAN }), { wrapper });
    unmount();
    await tick();
    expect(client.getQueryData<OFMessage[]>(KEY)).toHaveLength(200);
    other.unmount();
  });

  it("a trimmed thread reopens with older history to load, cursoring from its oldest kept row", async () => {
    client.setQueryData(KEY, many(1, 200));
    renderHook(() => useChatMessages({ accountId: ACCT, fanId: FAN }), { wrapper }).unmount();
    await tick();
    const { result } = renderHook(() => useChatMessages({ accountId: ACCT, fanId: FAN }), { wrapper });
    expect(result.current.hasOlder).toBe(true);
    expect(result.current.olderCursor()).toBe(200 - THREAD_KEEP + 1);
  });

  it("the cache-minimum cursor skips a ledger tip sorted to the top (no synthetic before_id)", async () => {
    client.setQueryData(KEY, [msg(6_000_000_000_000_123), ...many(50, 60)]);
    const { result } = renderHook(() => useChatMessages({ accountId: ACCT, fanId: FAN }), { wrapper });
    expect(result.current.olderCursor()).toBe(50);
  });
});

describe("load-older keeps Fansly message ids exact, and skips only the numeric synthetic band", () => {
  const SNOW = 900604711209099264n;
  const s = (k: number) => (SNOW + BigInt(k)).toString();
  const at = (k: number) => new Date(Date.UTC(2026, 5, 4, 12, 0, k)).toISOString();
  const sm = (k: number) => msg(s(k), { createdAt: at(k) });
  const FS_FAN = "900604711209000001";
  const FS_KEY = ["messages", ACCT, FS_FAN] as const;
  const olderUrls = () => relayGet.mock.calls.map((c) => String(c[0])).filter((u) => u.includes("before_id="));
  afterEach(() => { setPlatform("onlyfans"); });

  const starts = ["fetched head", "prefetch head", "cache only"] as const;
  const grid = starts.flatMap((start) => (["onlyfans", "fansly"] as const).map((sw) => [start, sw] as const));

  it.each(grid)("%s, switch %s: two pages send the exact string before_id", async (start, sw) => {
    expect(String(Number(s(100)))).not.toBe(s(100));
    setPlatform(sw);
    const pages: Record<string, OFMessagesResp> = {
      [s(100)]: resp([sm(99), sm(98)], true),
      [s(98)]: resp([sm(97), sm(96)], true),
    };
    relayGet.mockImplementation((url: string) =>
      Promise.resolve(pages[url.match(/before_id=(\d+)/)?.[1] ?? ""] ?? resp([sm(101), sm(100)], true)));
    if (start === "prefetch head") await prefetchChatMessages(client, ACCT, FS_FAN, { staleTime: 60_000 });
    if (start === "cache only") client.setQueryData(FS_KEY, [sm(100), sm(101)], { updatedAt: Date.now() });
    const { result } = renderHook(() => useChatMessages({
      accountId: ACCT, fanId: FS_FAN, prefetchWindowMs: start === "prefetch head" ? 60_000 : undefined,
    }), { wrapper });
    if (start === "fetched head") await waitFor(() => expect(result.current.headSettled).toBe(true));
    if (start === "prefetch head") expect(result.current.headSettled).toBe(true);
    expect(result.current.olderCursor()).toBe(s(100));
    await act(async () => { await result.current.loadOlder(); });
    await act(async () => { await result.current.loadOlder(); });
    expect(olderUrls()).toEqual([
      `/api/of/v2/chats/${FS_FAN}/messages?limit=30&order=desc&before_id=${s(100)}`,
      `/api/of/v2/chats/${FS_FAN}/messages?limit=30&order=desc&before_id=${s(98)}`,
    ]);
  });

  it.each([["onlyfans" as const], ["fansly" as const]])("an OnlyFans page (switch %s) skips a 5e15 placeholder and a 6e15 tip", async (sw) => {
    setPlatform(sw);
    client.setQueryData(KEY, [msg(5_000_000_000_000_001), msg(6_000_000_000_000_002), msg(50), msg(51)], { updatedAt: Date.now() });
    relayGet.mockResolvedValue(resp([], false));
    const { result } = renderHook(() => useChatMessages({ accountId: ACCT, fanId: FAN }), { wrapper });
    expect(result.current.olderCursor()).toBe(50);
    await act(async () => { await result.current.loadOlder(); });
    expect(olderUrls()).toEqual([`/api/of/v2/chats/${FAN}/messages?limit=30&order=desc&before_id=50`]);
  });
});

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

describe("background reads peek (a plain head read marks the chat read on OF)", () => {
  const head = `/api/of/v2/chats/${FAN}/messages?limit=30&order=desc`;
  const paths = () => relayGet.mock.calls.map((c) => c[0] as string);

  it("prefetchChatMessages asks peek=1, on the background lane and as a press's user-lane warm-up", async () => {
    relayGet.mockResolvedValue(resp([msg(1)], false));
    await prefetchChatMessages(client, ACCT, FAN);
    await prefetchChatMessages(client, ACCT, 43, { user: true, yieldOnOpen: false });
    expect(paths()).toEqual([`${head}&peek=1`, `/api/of/v2/chats/43/messages?limit=30&order=desc&peek=1`]);
    expect(relayGet.mock.calls.map((c) => c[1])).toEqual([
      { accountId: ACCT, priority: "background" },
      { accountId: ACCT, priority: undefined },
    ]);
  });

  it("useChatMessages reads plain by default; with peek its mount and poll both peek", async () => {
    relayGet.mockResolvedValue(resp([msg(1)], false));
    const plain = renderHook(() => useChatMessages({ accountId: ACCT, fanId: FAN }), { wrapper });
    await waitFor(() => expect(relayGet).toHaveBeenCalledTimes(1));
    expect(paths()).toEqual([head]);
    plain.unmount();

    client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
    relayGet.mockClear();
    renderHook(() => useChatMessages({ accountId: ACCT, fanId: FAN, peek: true }), { wrapper });
    await waitFor(() => expect(relayGet).toHaveBeenCalledTimes(1));
    await act(async () => { await client.refetchQueries({ queryKey: KEY }); });
    expect(paths()).toEqual([`${head}&peek=1`, `${head}&peek=1`]);
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
    expect(calls.filter((u) => !u.includes("before_id="))).toHaveLength(1);
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
      msg(5_000_000_000_000_042),
      msg(-1, { _tempId: -1, _pending: true }),
    ];
    expect(ids(mergeOlderPage(prev, [msg(50)])))
      .toEqual(["1", "50", "100", "5000000000000042", "-1"]);
  });

  it("drops a cached real row the page covers but does not contain", () => {
    const prev = [msg(10), msg(20), msg(30)];
    expect(ids(mergeOlderPage(prev, [msg(10), msg(30)])))
      .toEqual(["10", "30"]);
  });

  it("keeps cached rows OUTSIDE the fetched id range, drops only the one inside", () => {
    const prev = [msg(5), msg(20), msg(99)];
    expect(ids(mergeOlderPage(prev, [msg(10), msg(30)])))
      .toEqual(["5", "10", "30", "99"]);
  });

  it("leaves placeholders, tips and optimistic rows alone inside the range", () => {
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
    const prev = [msg(10), msg(20), msg(4_000_000_000_000)];
    const page = [msg(10), msg(5_000_000_000_000_042)];
    expect(ids(mergeOlderPage(prev, page)))
      .toEqual(["10", "20", "4000000000000", "5000000000000042"]);
  });

  it("a tip row slots by created_at among the loaded history, not the tail", () => {
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

describe("orderThread", () => {
  it("sorts real rows by created_at, id-tie-break on equal timestamps", () => {
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
      msg(5_000_000_000_000_001),
      msg(-1, { _tempId: -1 }),
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
    expect(ids(orderThread(rows))).toEqual(["6000000000000009", "20"]);
  });
});

describe("mergeTopPage", () => {
  it("drops a cached row inside the page's id span but absent from fresh (deleted on OF)", () => {
    const out = mergeTopPage([msg(3), msg(5), msg(7)], [msg(3), msg(7)]);
    expect(ids(out)).toEqual(["3", "7"]);
  });

  it("the Adrian orphan case: an in-range unsent row at the tail is dropped, not kept", () => {
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

  it("Fansly string ids never bound the page span, so a row unsent upstream is kept (known gap)", () => {
    const [a, b, c] = ["900539700124344400", "900539700124344401", "900539700124344402"];
    expect(ids(mergeTopPage([msg(a), msg(b), msg(c)], [msg(a), msg(c)]))).toEqual([a, b, c]);
    expect(ids(mergeOlderPage([msg(a), msg(b), msg(c)], [msg(a), msg(c)]))).toContain(b);
  });

  it("empty prev → returns fresh unchanged", () => {
    const fresh = [msg(5), msg(6)];
    expect(mergeTopPage([], fresh)).toBe(fresh);
  });
});

describe("mergeTopPage — mass placeholder band", () => {
  const BAND = 5_000_000_000_000_123;
  const NOW = Date.parse("2026-07-02T10:00:30.000Z");

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
    const queued = msg(BAND, { createdAt: "2026-07-02T10:00:00.000Z" });
    const fresh = [msg(60, { createdAt: "2026-07-02T10:05:00.000Z" })];
    expect(ids(mergeTopPage([queued], fresh, Date.parse("2026-07-02T10:05:30.000Z"))))
      .toEqual(["60", String(BAND)]);
  });

  it("quiet fan: placeholders NEWER than every real row still expire by age", () => {
    const blasts = [
      msg(BAND, { createdAt: "2026-06-26T15:15:00.000Z" }),
      msg(BAND + 1, { createdAt: "2026-07-01T10:48:00.000Z" }),
    ];
    const fresh = [msg(60, { createdAt: "2026-06-23T09:00:00.000Z" })];
    expect(ids(mergeTopPage([msg(60), ...blasts], fresh, NOW))).toEqual(["60"]);
  });

  it("normalizes a zone-less (naive-UTC) placeholder timestamp before comparing", () => {
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
    const out = mergeTopPage(
      [msg(70, { createdAt: "2026-07-02T11:00:00.000Z" })],
      [msg(60, { createdAt: "2026-07-02T10:00:00.000Z" }), msg(BAND)],
      NOW,
    );
    expect(ids(out)).toContain("70");
  });

  it("select guard: a rehydrated poisoned cache never paints expired placeholders, even with NO successful fetch", async () => {
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
    const oldTip = msg(6_000_000_000_000_042, {
      createdAt: "2026-04-01T09:00:00.000Z", isTip: true,
    });
    const fresh = [msg(60, { createdAt: "2026-07-02T10:00:00.000Z" })];
    expect(ids(mergeTopPage([oldTip], fresh, NOW)))
      .toEqual(["6000000000000042", "60"]);
  });

  it("a tip newer than the fresh page slots AFTER it (time order, not id-tail)", () => {
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
    expect(ids(mergeTopPage([tip], fresh, NOW)))
      .toEqual(["40", "6000000000000050", "60"]);
  });
});

describe("selectMessages", () => {
  const NOW = Date.parse("2026-07-02T12:00:00.000Z");
  const BAND = 5_000_000_000_000_123;

  it("drops an expired placeholder, keeps a fresh one, never touches tips or real rows", () => {
    const rows = [
      msg(50, { createdAt: "2026-01-01T00:00:00.000Z" }),
      msg(BAND, { createdAt: "2026-06-26T15:15:00.000Z" }),
      msg(BAND + 1, { createdAt: "2026-07-02T11:55:00.000Z" }),
      msg(6_000_000_000_000_042, { createdAt: "2026-01-01T00:00:00.000Z", isTip: true }),
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

describe("peek: background reads never mark the chat read on OF", () => {
  const urls = () => relayGet.mock.calls.map((c) => String(c[0]));

  it("a prefetch asks the relay to peek, on the background and the user lane", async () => {
    relayGet.mockResolvedValue(resp([msg(2), msg(1)], false));
    await prefetchChatMessages(client, ACCT, FAN, { staleTime: 0 });
    await prefetchChatMessages(client, ACCT, FAN, { staleTime: 0, user: true });
    expect(relayGet.mock.calls.map((c) => c[1])).toEqual([
      { accountId: ACCT, priority: "background" },
      { accountId: ACCT },
    ]);
    expect(urls().every((u) => u.includes("peek=1"))).toBe(true);
    expect(urls()).toHaveLength(2);
  });

  it("the hook reads plain by default", async () => {
    relayGet.mockResolvedValue(resp([msg(2), msg(1)], false));
    const { result } = renderHook(() => useChatMessages({ accountId: ACCT, fanId: FAN }), { wrapper });
    await waitFor(() => expect(relayGet).toHaveBeenCalledTimes(1));
    await act(async () => { await result.current.refetch(); });
    expect(urls()).toHaveLength(2);
    expect(urls().some((u) => u.includes("peek"))).toBe(false);
  });

  it("with `peek` on, the mount and the poll both peek", async () => {
    relayGet.mockResolvedValue(resp([msg(2), msg(1)], false));
    const { result } = renderHook(() => useChatMessages({ accountId: ACCT, fanId: FAN, peek: true }), { wrapper });
    await waitFor(() => expect(relayGet).toHaveBeenCalledTimes(1));
    await act(async () => { await result.current.refetch(); });
    expect(urls()).toHaveLength(2);
    expect(urls().every((u) => u.includes("peek=1"))).toBe(true);
  });
});

it("orders equal-time Fansly messages by their exact ids", () => {
  const older = msg("900539700124344321");
  const newer = msg("900539700124344322");
  expect(orderThread([newer, older])).toEqual([older, newer]);
  expect(mergeOlderPage([newer], [older])).toEqual([older, newer]);
});
