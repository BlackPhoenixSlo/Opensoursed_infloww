import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";
import { act, cleanup, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";

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

import { PREFETCH_QUIET_MS, useUnreadMessagesPrefetch } from "@/hooks/useUnreadMessagesPrefetch";
import { USER_INPUT_EVENTS } from "@/lib/idle";
import { relay, type OFChatItem } from "@/lib/relay";
const relayGet = relay.get as unknown as Mock;

function unread(id: number, { aid = "acct-a", lastId = id * 100 } = {}): OFChatItem {
  return {
    __accountId: aid,
    withUser: { id },
    lastMessage: { id: lastId, createdAt: "2026-08-25T10:00:00Z" },
    hasUnread: true,
    unreadMessagesCount: 1,
  } as OFChatItem;
}
const read = (id: number) => ({ ...unread(id), hasUnread: false, unreadMessagesCount: 0 }) as OFChatItem;
const unreads = (...ids: number[]) => ids.map((id) => unread(id));

let serveMessages: (path: string, signal?: AbortSignal) => unknown;
function messageCalls() {
  return relayGet.mock.calls.map((c) => ({
    aid: (c[1] as { accountId: string }).accountId,
    fanId: Number(String(c[0]).split("/")[5]),
    priority: (c[1] as { priority?: string }).priority,
  }));
}
const warmedFans = () => messageCalls().map((c) => c.fanId);

let client: QueryClient;
function wrapper({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
function renderWarm(rows: OFChatItem[], ready = true, tiers?: readonly number[]) {
  return renderHook(
    (p: { rows: OFChatItem[]; ready: boolean }) => useUnreadMessagesPrefetch(p.rows, p.ready, tiers),
    { wrapper, initialProps: { rows, ready } },
  );
}

async function settle(ms = 1) {
  await act(async () => { await vi.advanceTimersByTimeAsync(ms); });
}
async function until(label: string, cond: () => boolean, tries = 30) {
  for (let i = 0; i < tries; i++) {
    if (cond()) return;
    await settle();
  }
  throw new Error(`timed out waiting for: ${label}`);
}
const userInput = (type: string) => act(() => { window.dispatchEvent(new Event(type)); });

let idleRequests = 0;
beforeEach(() => {
  vi.useFakeTimers();
  client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } });
  serveMessages = async () => ({ list: [], hasMore: false });
  relayGet.mockReset();
  relayGet.mockImplementation(async (path: string, _ctx: unknown, signal?: AbortSignal) => serveMessages(path, signal));
  idleRequests = 0;
  vi.stubGlobal("requestIdleCallback", (cb: IdleRequestCallback) => {
    idleRequests += 1;
    return setTimeout(() => cb({ didTimeout: false, timeRemaining: () => 50 }), 0);
  });
  vi.stubGlobal("cancelIdleCallback", (id: number) => clearTimeout(id));
});

afterEach(() => {
  cleanup();
  client.clear();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  vi.useRealTimers();
});

describe("useUnreadMessagesPrefetch: the first tier", () => {
  it("warms the top 3 unread chats one at a time on the background lane", async () => {
    const release: (() => void)[] = [];
    serveMessages = () => new Promise((r) => release.push(() => r({ list: [], hasMore: false })));
    renderWarm([unread(1), read(2), unread(3), unread(4), unread(5)]);

    for (const n of [1, 2, 3]) {
      await until(`read ${n}`, () => messageCalls().length === n);
      await settle();
      expect(messageCalls()).toHaveLength(n);
      release.shift()!();
    }
    await settle();
    expect(messageCalls()).toEqual([1, 3, 4].map((fanId) => ({ aid: "acct-a", fanId, priority: "background" })));
    expect(client.getQueryData(["messages", "acct-a", 1])).toEqual([]);
    expect(relayGet.mock.calls.every(([path]) => String(path).endsWith("&peek=1"))).toBe(true);
  });

  it("warms nothing until ready", async () => {
    const h = renderWarm(unreads(1, 2), false);
    await settle(10 * PREFETCH_QUIET_MS);
    expect(messageCalls()).toEqual([]);

    h.rerender({ rows: unreads(1, 2), ready: true });
    await until("warmed", () => messageCalls().length === 2);
  });

  it("follows the order given and skips a Fan we restricted", async () => {
    const restricted = { ...unread(4), withUser: { id: 4, isRestricted: true, badgeExcluded: true } } as OFChatItem;
    renderWarm([unread(5), restricted, unread(3), unread(2), unread(1)]);
    await until("tier 1", () => messageCalls().length === 3);
    await settle();
    expect(warmedFans()).toEqual([5, 3, 2]);
  });

  it("warms a muted unread chat", async () => {
    const muted = { ...unread(4), isMutedNotifications: true } as OFChatItem;
    renderWarm([unread(5), muted, unread(3), unread(2)]);
    await until("tier 1", () => messageCalls().length === 3);
    await settle();
    expect(warmedFans()).toEqual([5, 4, 3]);
  });

  it("warms each chat on its own account across creators", async () => {
    renderWarm([unread(1), unread(2, { aid: "acct-b" }), unread(3, { aid: "acct-b" }), unread(4)]);
    await until("tier 1", () => messageCalls().length === 3);
    await settle();
    expect(messageCalls().map((c) => `${c.aid}:${c.fanId}`)).toEqual(["acct-a:1", "acct-b:2", "acct-b:3"]);
  });

  it("skips a chat whose cached thread already holds its last message", async () => {
    client.setQueryData(["messages", "acct-a", 1], [{ id: 100, text: "cached" }]);
    renderWarm(unreads(1, 2));
    await until("warmed", () => messageCalls().length === 1);
    await settle();
    expect(warmedFans()).toEqual([2]);
  });

  it("new rows re-cut the tier: an uncached chat on top is warmed, a chat whose thread holds its message is not", async () => {
    const h = renderWarm(unreads(1, 2, 3));
    await until("tier 1", () => messageCalls().length === 3);

    h.rerender({ rows: unreads(9, 1, 2, 3), ready: true });
    await until("fan 9 warmed", () => messageCalls().length === 4);
    expect(warmedFans()[3]).toBe(9);

    client.setQueryData(["messages", "acct-a", 8], [{ id: 800, text: "current" }]);
    h.rerender({ rows: unreads(8, 9, 1, 2, 3), ready: true });
    await settle(10);
    expect(warmedFans()).toEqual([1, 2, 3, 9]);
  });

  it("does not re-fire on the same rows, only on a new message", async () => {
    const h = renderWarm(unreads(1, 2));
    await until("warmed", () => messageCalls().length === 2);

    await settle(5 * 60_000);
    h.rerender({ rows: unreads(1, 2), ready: true });
    await settle(10);
    expect(messageCalls()).toHaveLength(2);

    h.rerender({ rows: [unread(2, { lastId: 999 }), unread(1)], ready: true });
    await until("new message re-warms", () => messageCalls().length === 3);
    await settle();
    expect(warmedFans()).toEqual([1, 2, 2]);
  });
});

describe("useUnreadMessagesPrefetch: the idle tiers", () => {
  function holdRead(fanId: number) {
    let release = () => {};
    serveMessages = (path, signal) => path.includes(`/chats/${fanId}/`)
      ? new Promise((resolve, reject) => {
        release = () => resolve({ list: [], hasMore: false });
        signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")));
      })
      : Promise.resolve({ list: [], hasMore: false });
    return { land: () => release() };
  }
  async function toFan4Warm(rows = unreads(1, 2, 3, 4, 5)) {
    const h = renderWarm(rows);
    await until("tier 1", () => messageCalls().length === 3);
    await settle(PREFETCH_QUIET_MS + 100);
    await until("tier 2 reading fan 4", () => messageCalls().length === 4);
    return { h, signal: relayGet.mock.calls[3][2] as AbortSignal };
  }

  it("warms the next 2 and the 2 after each only after a quiet window, and nothing past them, every warm a peek", async () => {
    renderWarm(unreads(1, 2, 3, 4, 5, 6, 7, 8));
    await until("tier 1", () => messageCalls().length === 3);

    await settle(PREFETCH_QUIET_MS - 500);
    expect(warmedFans()).toEqual([1, 2, 3]);
    await settle(1_000);
    await until("tier 2", () => messageCalls().length === 5);
    expect(idleRequests).toBeGreaterThan(0);

    await settle(PREFETCH_QUIET_MS - 500);
    expect(warmedFans()).toEqual([1, 2, 3, 4, 5]);
    await settle(1_000);
    await until("tier 3", () => messageCalls().length === 7);

    await settle(10 * PREFETCH_QUIET_MS);
    expect(warmedFans()).toEqual([1, 2, 3, 4, 5, 6, 7]);
    expect(messageCalls().every((c) => c.priority === "background")).toBe(true);
    expect(relayGet.mock.calls.every(([path]) => String(path).endsWith("&peek=1"))).toBe(true);
  });

  it("one tier keeps the warm to the first: no quiet window, no listener", async () => {
    const added = vi.spyOn(window, "addEventListener");
    renderWarm(unreads(1, 2, 3, 4, 5), true, [3]);
    await until("tier 1", () => messageCalls().length === 3);
    await settle(10 * PREFETCH_QUIET_MS);
    expect(warmedFans()).toEqual([1, 2, 3]);
    expect(idleRequests).toBe(0);
    expect(added.mock.calls.map((c) => c[0])).not.toContain("pointerdown");
  });

  it("input during the quiet window postpones the tier", async () => {
    renderWarm(unreads(1, 2, 3, 4, 5));
    await until("tier 1", () => messageCalls().length === 3);

    await settle(PREFETCH_QUIET_MS - 500);
    userInput("pointermove");
    await settle(PREFETCH_QUIET_MS - 500);
    userInput("scroll");
    await settle(PREFETCH_QUIET_MS - 500);
    expect(warmedFans()).toEqual([1, 2, 3]);

    await settle(1_000);
    await until("tier 2", () => messageCalls().length === 5);
  });

  it("input aborts an idle tier's in-flight warm and stops the tier; the aborted chat is never warmed again for that message", async () => {
    holdRead(4);
    const { h, signal: first } = await toFan4Warm();
    expect(first.aborted).toBe(false);

    userInput("keydown");
    await settle();
    expect(first.aborted).toBe(true);
    expect(client.getQueryState(["messages", "acct-a", 4])?.fetchStatus).toBe("idle");
    await settle(PREFETCH_QUIET_MS - 500);
    expect(warmedFans()).toEqual([1, 2, 3, 4]);

    await settle(1_000);
    await until("tier 2 again", () => messageCalls().length === 5);
    for (let i = 0; i < 3; i++) {
      await settle(PREFETCH_QUIET_MS + 100);
      userInput("keydown");
    }
    await settle(10 * PREFETCH_QUIET_MS);
    expect(warmedFans()).toEqual([1, 2, 3, 4, 5]);

    h.rerender({ rows: [...unreads(1, 2, 3), unread(4, { lastId: 401 }), unread(5)], ready: true });
    await settle(PREFETCH_QUIET_MS + 100);
    await until("fan 4 again, for its new message", () => messageCalls().length === 6);
    expect(warmedFans()[5]).toBe(4);
  });

  it("an idle tier leaves a thread that is open and fetching alone, and input does not cancel it", async () => {
    let landOpen!: () => void;
    const open = renderHook(() => useQuery({
      queryKey: ["messages", "acct-a", 4],
      queryFn: () => new Promise<unknown[]>((r) => { landOpen = () => r([{ id: 400, text: "opened" }]); }),
    }), { wrapper });
    renderWarm(unreads(1, 2, 3, 4, 5));
    await until("tier 1", () => messageCalls().length === 3);
    await settle(PREFETCH_QUIET_MS + 100);
    await until("tier 2", () => messageCalls().length === 4);
    expect(warmedFans()).toEqual([1, 2, 3, 5]);

    userInput("pointerdown");
    await settle();
    expect(client.getQueryState(["messages", "acct-a", 4])?.fetchStatus).toBe("fetching");
    await act(async () => { landOpen(); });
    await until("the open thread's read lands", () => open.result.current.data?.length === 1);
  });

  it("input does not cancel a warm a view has since joined by opening the thread", async () => {
    holdRead(4);
    const { signal: warm } = await toFan4Warm();

    renderHook(() => useQuery({ queryKey: ["messages", "acct-a", 4], queryFn: () => [] }), { wrapper });
    await settle();
    userInput("keydown");
    await settle();
    expect(warm.aborted).toBe(false);
    expect(client.getQueryState(["messages", "acct-a", 4])?.fetchStatus).toBe("fetching");
  });

  it("ready going false does not abort an idle tier's warm in flight, and starts no new warm until ready again", async () => {
    const fan4 = holdRead(4);
    const rows = unreads(1, 2, 3, 4, 5);
    const { h, signal: warm } = await toFan4Warm(rows);

    h.rerender({ rows, ready: false });
    await settle();
    expect(warm.aborted).toBe(false);
    expect(client.getQueryState(["messages", "acct-a", 4])?.fetchStatus).toBe("fetching");

    await act(async () => { fan4.land(); });
    await settle(10 * PREFETCH_QUIET_MS);
    expect(warmedFans()).toEqual([1, 2, 3, 4]);

    h.rerender({ rows, ready: true });
    await settle(PREFETCH_QUIET_MS + 100);
    await until("fan 5", () => messageCalls().length === 5);
    expect(warmedFans()).toEqual([1, 2, 3, 4, 5]);
  });

  it("warms the current list, not the tier as cut: a chat read mid-tier is not fetched, and stays unclaimed", async () => {
    const fan4 = holdRead(4);
    const { h } = await toFan4Warm();

    h.rerender({ rows: [...unreads(1, 2, 3, 4), read(5)], ready: true });
    await act(async () => { fan4.land(); });
    await settle(10 * PREFETCH_QUIET_MS);
    expect(warmedFans()).toEqual([1, 2, 3, 4]);

    h.rerender({ rows: unreads(1, 2, 3, 4, 5), ready: true });
    await settle(PREFETCH_QUIET_MS + 100);
    await until("fan 5", () => messageCalls().length === 5);
    expect(warmedFans()).toEqual([1, 2, 3, 4, 5]);
  });

  it("a first-tier warm queued mid idle tier goes next, not after the whole tier", async () => {
    const fan4 = holdRead(4);
    const { h } = await toFan4Warm();

    h.rerender({ rows: unreads(9, 1, 2, 3, 4, 5), ready: true });
    await settle();
    await act(async () => { fan4.land(); });
    await until("fans 9 and 5", () => messageCalls().length === 6);
    expect(warmedFans()).toEqual([1, 2, 3, 4, 9, 5]);
  });

  it("input while an idle warm is queued behind a first-tier warm stops it when its turn comes, and leaves it unclaimed", async () => {
    const fan4 = holdRead(4);
    const { h } = await toFan4Warm();

    const fan9 = holdRead(9);
    h.rerender({ rows: unreads(9, 1, 2, 3, 4, 5), ready: true });
    await settle();
    await act(async () => { fan4.land(); });
    await until("fan 9 in flight", () => messageCalls().length === 5);
    const fan9Signal = relayGet.mock.calls[4][2] as AbortSignal;

    userInput("keydown");
    await settle();
    expect(fan9Signal.aborted).toBe(false);
    await act(async () => { fan9.land(); });
    await settle(PREFETCH_QUIET_MS - 500);
    expect(warmedFans()).toEqual([1, 2, 3, 4, 9]);

    await settle(1_000);
    await until("fan 5", () => messageCalls().length === 6);
    expect(warmedFans()).toEqual([1, 2, 3, 4, 9, 5]);
  });

  it("runs no idle tier while the tab is hidden", async () => {
    const hidden = vi.spyOn(document, "hidden", "get").mockReturnValue(true);
    try {
      renderWarm(unreads(1, 2, 3, 4, 5));
      await until("tier 1", () => messageCalls().length === 3);
      await settle(10 * PREFETCH_QUIET_MS);
      expect(warmedFans()).toEqual([1, 2, 3]);
      expect(idleRequests).toBe(0);

      hidden.mockReturnValue(false);
      act(() => { document.dispatchEvent(new Event("visibilitychange")); });
      await settle(PREFETCH_QUIET_MS + 100);
      await until("tier 2", () => messageCalls().length === 5);
    } finally {
      hidden.mockRestore();
    }
  });

  it("unmounting leaves no timer, no listener and no warm running", async () => {
    holdRead(4);
    const mine = new Set<string>([...USER_INPUT_EVENTS, "scroll", "visibilitychange"]);
    const spies = [window, document].flatMap((t) => [vi.spyOn(t, "addEventListener"), vi.spyOn(t, "removeEventListener")]);
    const unbalanced = () => {
      const n = new Map<string, number>();
      spies.forEach((spy, i) => spy.mock.calls.forEach(([type]) => n.set(type, (n.get(type) ?? 0) + (i % 2 ? -1 : 1))));
      return [...n].filter(([type, d]) => mine.has(type) && d !== 0);
    };

    const quiet = renderWarm(unreads(1, 2, 3, 4, 5));
    await until("tier 1", () => messageCalls().length === 3);
    await settle(PREFETCH_QUIET_MS - 500);
    quiet.unmount();
    await settle();
    expect(vi.getTimerCount()).toBe(0);

    relayGet.mockClear();
    client.clear();
    const { h: warming, signal: warm } = await toFan4Warm();
    warming.unmount();
    await settle();
    expect(warm.aborted).toBe(true);
    expect(vi.getTimerCount()).toBe(0);

    await settle(10 * PREFETCH_QUIET_MS);
    expect(warmedFans()).toEqual([1, 2, 3, 4]);
    expect(unbalanced()).toEqual([]);
  });
});
