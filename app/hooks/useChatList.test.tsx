import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";
import { act, cleanup, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider, focusManager, useQuery } from "@tanstack/react-query";

vi.mock("@/lib/relay", async (orig) => ({ ...(await orig<typeof import("@/lib/relay")>()), relay: { get: vi.fn() }, relayFocus: () => null }));
vi.mock("@/lib/perfLog", () => ({
  perfOpId: () => "op-test",
  perfLog: vi.fn(),
  perfDelivered: vi.fn(),
  perfError: vi.fn(),
  perfPaintPending: vi.fn(),
  perfPaintOnce: vi.fn(),
}));

let mockScope: { kind: "model"; accountId: string } | { kind: "all" } =
  { kind: "model", accountId: "acct-a" };
let mockAccounts: { id: string; platform?: string }[] = [{ id: "acct-a" }];

vi.mock("@/contexts/ScopeContext", () => ({
  useScope: () => ({
    scope: mockScope,
    setScope: vi.fn(),
    accountId: mockScope.kind === "model" ? mockScope.accountId : null,
    eventScope: "all",
  }),
}));
vi.mock("@/hooks/useAccounts", () => ({
  useAccounts: () => {
    const roster = useQuery<{ account_id: string; platform?: string }[]>({
      queryKey: ["chatter", "self", "accounts"], enabled: false,
    }).data;
    return { data: { accounts: mockScope.kind === "all" ? mockAccounts : roster?.map((a) => ({ id: a.account_id, platform: a.platform })) } };
  },
  useActiveAccounts: () => mockAccounts,
  usePlatformAccounts: () => mockAccounts,
}));
type SseHandler = (env: unknown, rawType?: string) => void;
const sseHandlers = new Map<string, Set<SseHandler>>();
let ssePaused = false;
vi.mock("@/lib/events", () => ({
  eventBus: {
    on(type: string, fn: SseHandler) {
      let set = sseHandlers.get(type);
      if (!set) { set = new Set(); sseHandlers.set(type, set); }
      set.add(fn);
      return () => set.delete(fn);
    },
    isConnected: () => false,
    isPaused: () => ssePaused,
  },
}));
vi.mock("@/hooks/useServerScheduledSends", () => ({
  scheduledSendsKey: (a: string, f: number) => ["scheduled-sends", a, f],
}));

import {
  IDLE_POLL_MS, chatsQueryKey, headPollDelay, prefetchModelChatList, refreshChatHead, shareChatPages, useCachedChatPages,
  useChatList, type ChatListFilter,
} from "@/hooks/useChatList";
import { useInboxRealtime } from "@/hooks/useInboxRealtime";
import { flipCachedReadState } from "@/hooks/useAccountStateEvents";
import { applyCachedReply } from "@/hooks/useInboxRealtime";
import { patchChatListAfterSend } from "@/hooks/useSendMessage";
import { setRelayOffset } from "@/lib/ageClock";
import { RelayError, chatListRetry, relay, type OFChatItem } from "@/lib/relay";
import { PLATFORM_KEY, resetPlatformForTests, setPlatform } from "@/lib/platform";
import { noteRoster, resetUnknownAccounts } from "@/lib/unknownAccounts";
const relayGet = relay.get as unknown as Mock;

const POLL_MS = 90_000;

function row(id: number, createdAt: string): OFChatItem {
  return {
    withUser: { id },
    lastMessage: { id: id * 100, text: `msg-${id}`, createdAt },
    unreadMessagesCount: 0,
  } as OFChatItem;
}

let serve: (accountId: string, offset: number) => { list: OFChatItem[]; hasMore: boolean };

interface ChatCall { offset: number; filter: string | null; accountId?: string; refresh?: boolean }

function chatCalls(): ChatCall[] {
  return relayGet.mock.calls
    .filter((c) => String(c[0]).startsWith("/api/of/v2/chats"))
    .map((c) => {
      const qs = new URLSearchParams(String(c[0]).split("?")[1] ?? "");
      return {
        offset: Number(qs.get("offset") ?? 0),
        filter: qs.get("filter"),
        accountId: (c[1] as { accountId?: string } | undefined)?.accountId,
        refresh: (c[3] as { refresh?: boolean } | undefined)?.refresh,
      };
    });
}

const MODEL_KEY = ["chats", "model", "acct-a", null, null, null, 25] as const;

function watchFetching() {
  let saw = false;
  const stop = client.getQueryCache().subscribe(() => {
    if (client.getQueryState(MODEL_KEY)?.fetchStatus === "fetching") saw = true;
  });
  return { saw: () => saw, stop };
}

let client: QueryClient;
function wrapper({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
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

beforeEach(() => {
  vi.useFakeTimers();
  sseHandlers.clear();
  ssePaused = false;
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  client.setQueryData(["chatter", "self", "accounts"], [{ account_id: "acct-a", platform: "onlyfans" }]);
  mockScope = { kind: "model", accountId: "acct-a" };
  mockAccounts = [{ id: "acct-a" }];
  serve = () => ({ list: [], hasMore: false });
  relayGet.mockReset();
  relayGet.mockImplementation(async (path: string, ctx?: { accountId?: string }) => {
    if (path.startsWith("/admin/fans/")) {
      const ids = (new URLSearchParams(path.split("?")[1] ?? "").get("ids") ?? "")
        .split(",").filter(Boolean);
      const fans: Record<string, unknown> = {};
      for (const id of ids) {
        fans[id] = {
          id: Number(id), name: `fan-${id}`, username: `fan${id}`,
          avatar: null, customNickname: null,
        };
      }
      return { fans };
    }
    if (path.startsWith("/api/of/v2/chats")) {
      const qs = new URLSearchParams(path.split("?")[1] ?? "");
      return serve(ctx?.accountId ?? "", Number(qs.get("offset") ?? 0));
    }
    throw new Error(`unexpected relay.get ${path}`);
  });
});

afterEach(() => {
  cleanup();
  client.clear();
  vi.useRealTimers();
});

async function renderThreePages(params: Parameters<typeof useChatList>[0] = {}) {
  serve = (_aid, offset) => {
    if (offset === 0) return { list: [row(10, "2026-08-25T10:00:00Z"), row(9, "2026-08-25T09:00:00Z")], hasMore: true };
    if (offset === 25) return { list: [row(8, "2026-08-25T08:00:00Z"), row(7, "2026-08-25T07:00:00Z")], hasMore: true };
    if (offset === 50) return { list: [row(6, "2026-08-25T06:00:00Z")], hasMore: true };
    return { list: [], hasMore: false };
  };
  const h = renderHook(() => useChatList(params), { wrapper });
  await until("page 0", () => h.result.current.data.length === 2);
  await act(async () => { await h.result.current.loadMore("auto"); });
  await act(async () => { await h.result.current.loadMore("auto"); });
  await until("pages 0-2", () => h.result.current.data.length === 5);
  relayGet.mockClear();
  return h;
}

describe("useChatList periodic refresh", () => {
  it("re-reads ONLY the head page on the 90s poll, however deep the list is", async () => {
    await renderThreePages();
    const poll = watchFetching();

    await settle(POLL_MS);
    poll.stop();

    expect(chatCalls()).toEqual([
      expect.objectContaining({ offset: 0, accountId: "acct-a" }),
    ]);
    expect(poll.saw()).toBe(false);
  });

  it("still re-walks EVERY loaded page on a manual refresh", async () => {
    const h = await renderThreePages();

    await act(async () => { await h.result.current.refresh(); });

    expect(chatCalls().map((c) => c.offset)).toEqual([0, 25, 50]);
    expect(chatCalls()[0].refresh).toBe(true);
  });

  it("polls the head every 30 s while idle mode has SSE paused", async () => {
    await renderThreePages();
    ssePaused = true;
    act(() => { focusManager.setFocused(false); });
    try {
      await settle(IDLE_POLL_MS);
      expect(chatCalls().map((c) => c.offset)).toEqual([0]);
      await settle(IDLE_POLL_MS);
      expect(chatCalls().map((c) => c.offset)).toEqual([0, 0]);
    } finally {
      act(() => { focusManager.setFocused(undefined); });
    }
  });

  it.each([{ filter: "pinned" as const }, { query: "fan" }, { listId: "folder" }])(
    "skips idle polling for %o", async (params) => {
      ssePaused = true;
      serve = () => ({ list: [row(10, "2026-08-25T10:00:00Z")], hasMore: false });
      const h = renderHook(() => useChatList(params), { wrapper });
      await until("page 0", () => h.result.current.data.length === 1);
      relayGet.mockClear();
      await settle(POLL_MS);
      expect(chatCalls()).toEqual([]);
    },
  );

  it("rearms polling for a filtered view when idle mode resumes before SSE reconnects", async () => {
    serve = () => ({ list: [row(10, "2026-08-25T10:00:00Z")], hasMore: false });
    const h = renderHook(() => useChatList({ filter: "pinned" }), { wrapper });
    await until("page 0", () => h.result.current.data.length === 1);
    relayGet.mockClear();

    act(() => {
      ssePaused = true;
      focusManager.setFocused(false);
    });
    await settle(POLL_MS);
    expect(chatCalls()).toEqual([]);

    act(() => {
      focusManager.setFocused(undefined);
      ssePaused = false;
    });
    await settle();
    await settle(POLL_MS);
    expect(chatCalls().map((c) => c.offset)).toEqual([0]);
  });

  it("pulls a hidden tab's 5-minute tick in to 30 s when idle mode starts", async () => {
    const hidden = vi.spyOn(document, "hidden", "get").mockReturnValue(true);
    try {
      await renderThreePages();
      await settle(60_000);
      expect(chatCalls()).toEqual([]);
      ssePaused = true;
      act(() => { focusManager.setFocused(false); });
      await settle(IDLE_POLL_MS);
      expect(chatCalls().map((c) => c.offset)).toEqual([0]);
    } finally {
      act(() => { focusManager.setFocused(undefined); });
      hidden.mockRestore();
    }
  });

  it("reads the head at once on tab return, once for visibilitychange + focus", async () => {
    await renderThreePages();
    await settle(10_000);
    act(() => {
      document.dispatchEvent(new Event("visibilitychange"));
      window.dispatchEvent(new Event("focus"));
    });
    await settle();
    expect(chatCalls().map((c) => c.offset)).toEqual([0]);
  });

  it("does not leave a poll interval that also walks the deep pages", async () => {
    const h = await renderThreePages();

    await settle(POLL_MS);
    await settle(POLL_MS);

    expect(chatCalls().map((c) => c.offset)).toEqual([0, 0]);
    expect(h.result.current.data.length).toBe(5);
  });

  it("renders a row promoted into the fresh head page exactly once, from the head", async () => {
    const h = await renderThreePages();

    serve = (_aid, offset) => {
      if (offset === 0) {
        return {
          list: [row(6, "2026-08-25T11:00:00Z"), row(10, "2026-08-25T10:00:00Z")],
          hasMore: true,
        };
      }
      throw new Error(`poll must not read offset ${offset}`);
    };

    await settle(POLL_MS);
    await until("head page spliced", () => h.result.current.data[0]?.withUser.id === 6);

    const ids = h.result.current.data.map((c) => c.withUser.id);
    expect(ids.filter((id) => id === 6)).toHaveLength(1);
    expect(ids[0]).toBe(6);
    expect(h.result.current.data[0].lastMessage?.createdAt).toBe("2026-08-25T11:00:00Z");
    expect(ids).toEqual([6, 10, 8, 7]);
  });

  it("recovers a row the fresh head page displaced, on manual refresh", async () => {
    const h = await renderThreePages();
    let promoted = false;
    serve = (_aid, offset) => {
      if (offset === 0) {
        return promoted
          ? { list: [row(6, "2026-08-25T11:00:00Z"), row(10, "2026-08-25T10:00:00Z")], hasMore: true }
          : { list: [row(10, "2026-08-25T10:00:00Z"), row(9, "2026-08-25T09:00:00Z")], hasMore: true };
      }
      if (offset === 25) {
        return promoted
          ? { list: [row(9, "2026-08-25T09:00:00Z"), row(8, "2026-08-25T08:00:00Z")], hasMore: true }
          : { list: [row(8, "2026-08-25T08:00:00Z"), row(7, "2026-08-25T07:00:00Z")], hasMore: true };
      }
      return { list: [row(7, "2026-08-25T07:00:00Z")], hasMore: true };
    };
    promoted = true;

    await settle(POLL_MS);
    await until("head spliced", () => h.result.current.data[0]?.withUser.id === 6);
    expect(h.result.current.data.map((c) => c.withUser.id)).not.toContain(9);

    await act(async () => { await h.result.current.refresh(); });
    await until("fan 9 back", () => h.result.current.data.some((c) => c.withUser.id === 9));
    expect(h.result.current.data.map((c) => c.withUser.id)).toEqual([6, 10, 9, 8, 7]);
  });

  it("keeps the next-page offset aligned after a head-only poll", async () => {
    const h = await renderThreePages();

    serve = (_aid, offset) => {
      if (offset === 0) return { list: [row(11, "2026-08-25T12:00:00Z")], hasMore: true };
      if (offset === 75) return { list: [row(5, "2026-08-25T05:00:00Z")], hasMore: false };
      throw new Error(`unexpected offset ${offset}`);
    };

    await settle(POLL_MS);
    expect(chatCalls().map((c) => c.offset)).toEqual([0]);
    await until("head page spliced", () => h.result.current.data[0]?.withUser.id === 11);
    relayGet.mockClear();
    await act(async () => { await h.result.current.loadMore("auto"); });
    await until("page 3", () => h.result.current.data.some((c) => c.withUser.id === 5));

    expect(chatCalls().map((c) => c.offset)).toEqual([75]);
    expect(h.result.current.data.map((c) => c.withUser.id)).toContain(5);
  });

  it("re-reads offset 0 per account in unified scope", async () => {
    mockScope = { kind: "all" };
    mockAccounts = [{ id: "acct-a" }, { id: "acct-b" }, { id: "acct-c" }];
    serve = (aid, offset) => {
      const base = aid.charCodeAt(5) * 10;
      if (offset === 0) return { list: [row(base + 1, "2026-08-25T10:00:00Z")], hasMore: true };
      return { list: [row(base + 2, "2026-08-25T08:00:00Z")], hasMore: false };
    };
    const h = renderHook(() => useChatList(), { wrapper });
    await until("3 accounts x page 0", () => h.result.current.data.length === 3);
    await act(async () => { await h.result.current.loadMore("auto"); });
    await until("3 accounts x 2 pages", () => h.result.current.data.length === 6);
    relayGet.mockClear();

    await settle(POLL_MS);

    const calls = chatCalls();
    expect(calls.map((c) => c.offset)).toEqual([0, 0, 0]);
    expect(calls.map((c) => c.accountId).sort()).toEqual(["acct-a", "acct-b", "acct-c"]);
  });

  it("carries the active filter on the poll", async () => {
    await renderThreePages({ filter: "unread" });

    await settle(POLL_MS);

    expect(chatCalls()).toEqual([expect.objectContaining({ offset: 0, filter: "unread" })]);
  });

  it("polls a single-page list the same way — one head read, no spinner", async () => {
    serve = () => ({ list: [row(10, "2026-08-25T10:00:00Z")], hasMore: false });
    const h = renderHook(() => useChatList(), { wrapper });
    await until("page 0", () => h.result.current.data.length === 1);
    relayGet.mockClear();
    const poll = watchFetching();

    serve = () => ({ list: [row(11, "2026-08-25T11:00:00Z")], hasMore: false });
    await settle(POLL_MS);
    await until("head spliced", () => h.result.current.data[0]?.withUser.id === 11);
    poll.stop();

    expect(chatCalls().map((c) => c.offset)).toEqual([0]);
    expect(poll.saw()).toBe(false);

    const manual = watchFetching();
    await act(async () => { await h.result.current.refresh(); });
    manual.stop();
    expect(manual.saw()).toBe(true);
  });

  it("keeps polling a list whose initial fetch errored", async () => {
    serve = () => { throw new Error("relay down"); };
    const h = renderHook(() => useChatList(), { wrapper });
    await until("errored", () => h.result.current.isError);
    relayGet.mockClear();
    serve = () => ({ list: [row(10, "2026-08-25T10:00:00Z")], hasMore: false });

    await settle(POLL_MS);
    await until("recovered", () => h.result.current.data.length === 1);

    expect(chatCalls().map((c) => c.offset)).toEqual([0]);
  });

  it("backs the poll off to 5 minutes while the document is hidden", async () => {
    const hidden = vi.spyOn(document, "hidden", "get").mockReturnValue(true);
    try {
      await renderThreePages();

      await settle(POLL_MS);
      expect(chatCalls()).toEqual([]);

      await settle(5 * 60_000);
      expect(chatCalls().map((c) => c.offset)).toEqual([0]);
    } finally {
      hidden.mockRestore();
    }
  });
});

function fireInbound(fanId: number, text: string, createdAt: string) {
  act(() => {
    sseHandlers.get("api2_chat_message")?.forEach((h) => h({
      __account_id: "acct-a",
      api2_chat_message: {
        id: fanId * 1000, text,
        fromUser: { id: fanId, name: `fan-${fanId}` },
        createdAt,
      },
    }));
  });
}

describe("headPollDelay", () => {
  it.each([
    [{ paused: false, hidden: false, connected: false, idlePoll: false }, 90_000],
    [{ paused: false, hidden: false, connected: true, idlePoll: true }, 300_000],
    [{ paused: false, hidden: true, connected: false, idlePoll: false }, 300_000],
    [{ paused: true, hidden: false, connected: false, idlePoll: true }, 30_000],
    [{ paused: true, hidden: true, connected: false, idlePoll: true }, 30_000],
    [{ paused: true, hidden: false, connected: false, idlePoll: false }, null],
  ])("%o → %s", (s, ms) => { expect(headPollDelay(s)).toBe(ms); });
});

describe("useChatList head poll x useInboxRealtime", () => {
  it("SSE still lifts a DEEP row to the head, and the poll leaves that intact", async () => {
    const h = await renderThreePages();
    renderHook(() => useInboxRealtime(), { wrapper });

    fireInbound(6, "hey", "2026-08-25T11:00:00Z");
    await until("sse bump", () => h.result.current.data[0]?.withUser.id === 6);
    expect(h.result.current.data[0].lastMessage?.text).toBe("hey");

    serve = (_aid, offset) => {
      if (offset === 0) {
        return {
          list: [row(6, "2026-08-25T11:00:00Z"), row(10, "2026-08-25T10:00:00Z")],
          hasMore: true,
        };
      }
      throw new Error(`poll must not read offset ${offset}`);
    };
    await settle(POLL_MS);
    await until("head spliced", () => h.result.current.data[0]?.lastMessage?.text !== "hey");

    expect(chatCalls().map((c) => c.offset)).toEqual([0]);
    expect(h.result.current.data[0].withUser.id).toBe(6);

    serve = (_aid, offset) => {
      if (offset === 75) return { list: [row(4, "2026-08-25T04:00:00Z")], hasMore: false };
      throw new Error(`unexpected offset ${offset}`);
    };
    relayGet.mockClear();
    await act(async () => { await h.result.current.loadMore("auto"); });
    expect(chatCalls().map((c) => c.offset)).toEqual([75]);
  });

  it("a poll whose Relay window predates the DM does not take the lifted row back", async () => {
    const h = await renderThreePages();
    renderHook(() => useInboxRealtime(), { wrapper });
    fireInbound(8, "hey", new Date().toISOString());
    await until("sse bump", () => h.result.current.data[0]?.withUser.id === 8);

    await settle(POLL_MS);
    await until("poll read", () => chatCalls().length > 0);
    await settle(); await settle();

    expect(h.result.current.data[0].withUser.id).toBe(8);
    expect(h.result.current.data[0].lastMessage?.text).toBe("hey");
  });

  it("All Models: a permanently failing Creator retains its loaded rows without extending paging", async () => {
    mockScope = { kind: "all" };
    mockAccounts = [{ id: "acct-a" }, { id: "acct-b" }];
    serve = (aid, offset) => ({
      list: [row(aid === "acct-a" ? 10 : 20 + offset, "2026-08-25T10:00:00Z")],
      hasMore: aid === "acct-b" && offset === 0,
    });
    const h = renderHook(() => useChatList({ filter: "unread" }), { wrapper });
    await until("page 0", () => h.result.current.hasMore);
    await act(async () => { await h.result.current.loadMore("auto"); });
    await until("page 1", () => h.result.current.data.some((c) => c.withUser.id === 45));
    const initial = serve;
    relayGet.mockClear();
    serve = (aid, offset) => {
      if (aid === "acct-b") throw new Error("429");
      return initial(aid, offset);
    };
    await act(async () => { await h.result.current.refresh(); });
    await until("paging ends after the partial refresh", () => !h.result.current.hasMore);
    expect(chatCalls().map((c) => c.offset)).toEqual([0, 0]);
    await act(async () => { await h.result.current.loadMore("auto"); });
    expect(chatCalls().map((c) => c.offset)).toEqual([0, 0]);
    expect(h.result.current.data.some((c) => c.withUser.id === 45)).toBe(true);
  });

  it("All Models: a poll where one Creator's read fails keeps that Creator's rows", async () => {
    mockScope = { kind: "all" };
    mockAccounts = [{ id: "acct-a" }, { id: "acct-b" }];
    serve = (aid) => aid === "acct-a"
      ? { list: [row(10, "2026-08-25T10:00:00Z")], hasMore: false }
      : { list: [{ ...row(20, "2026-08-25T09:00:00Z"), __accountId: "acct-b" } as OFChatItem], hasMore: false };
    const h = renderHook(() => useChatList({}), { wrapper });
    await until("page 0", () => h.result.current.data.length === 2);
    renderHook(() => useInboxRealtime(), { wrapper });
    act(() => {
      sseHandlers.get("api2_chat_message")?.forEach((fn) => fn({
        __account_id: "acct-b",
        api2_chat_message: { id: 777, text: "b-new", fromUser: { id: 20, name: "x" }, createdAt: "2026-08-25T11:00:00Z" },
      }));
    });
    await until("sse bump", () => h.result.current.data[0]?.lastMessage?.text === "b-new");

    relayGet.mockClear();
    serve = (aid) => {
      if (aid === "acct-b") throw Object.assign(new Error("429"), { status: 429 });
      return { list: [row(10, "2026-08-25T10:00:00Z")], hasMore: false };
    };
    await settle(POLL_MS);
    await until("poll read", () => chatCalls().length >= 2);
    await settle(); await settle();

    expect(h.result.current.data.map((c) => `${c.__accountId}:${c.withUser.id}:${c.lastMessage?.text}`))
      .toEqual(["acct-b:20:b-new", "acct-a:10:msg-10"]);
  });
});

describe("useChatList Unread chip x useInboxRealtime", () => {
  it("a read fan's new message enters the Unread list at the top", async () => {
    serve = () => ({ list: [{ ...row(10, "2026-08-25T10:00:00Z"), hasUnread: true, unreadMessagesCount: 1 }], hasMore: false });
    const h = renderHook(() => useChatList({ filter: "unread" }), { wrapper });
    await until("page 0", () => h.result.current.data.length === 1);
    renderHook(() => useInboxRealtime(), { wrapper });
    fireInbound(8, "hey", "2026-08-25T11:00:00Z");
    await until("sse add", () => h.result.current.data.length === 2);
    expect(h.result.current.data.map((c) => c.withUser.id)).toEqual([8, 10]);
    expect(h.result.current.data[0].lastMessage?.text).toBe("hey");
  });
});

describe("useChatList OF params: order, OF's own filters, enabled (the OF mirror's chat list)", () => {
  it("order=old is sent, lists the oldest chat first and gets its own key (the default key is unchanged)", async () => {
    serve = () => ({ list: [row(1, "2026-08-25T10:00:00Z"), row(2, "2026-08-20T10:00:00Z"), row(3, "2026-08-22T10:00:00Z")], hasMore: false });
    const h = renderHook(() => useChatList({ order: "old" }), { wrapper });
    await until("rows", () => h.result.current.data.length === 3);
    const path = String(relayGet.mock.calls.find((c) => String(c[0]).startsWith("/api/of/v2/chats"))![0]);
    expect(new URLSearchParams(path.split("?")[1]).get("order")).toBe("old");
    expect(h.result.current.data.map((c) => c.withUser.id)).toEqual([2, 3, 1]);
    expect(client.getQueryData([...MODEL_KEY, "old"])).toBeDefined();
    expect(client.getQueryData(MODEL_KEY)).toBeUndefined();
    expect(h.result.current.pages?.[0].map((c) => c.withUser.id)).toEqual([2, 3, 1]);
  });
  it("passes OF's who_tipped and unread_tips filters and a list_id through", async () => {
    const h = renderHook(() => useChatList({ filter: "who_tipped", listId: "following" }), { wrapper });
    await until("fetched", () => h.result.current.isSuccess);
    const qs = new URLSearchParams(String(relayGet.mock.calls.find((c) => String(c[0]).startsWith("/api/of/v2/chats"))![0]).split("?")[1]);
    expect([qs.get("filter"), qs.get("list_id"), qs.get("order")]).toEqual(["who_tipped", "following", "recent"]);
    h.unmount();
    relayGet.mockClear();
    const u = renderHook(() => useChatList({ filter: "unread_tips" }), { wrapper });
    await until("fetched", () => u.result.current.isSuccess);
    expect(chatCalls().map((c) => c.filter)).toEqual(["unread_tips"]);
  });
  it("enabled false: no fetch and no poll", async () => {
    renderHook(() => useChatList({ enabled: false }), { wrapper });
    await settle(POLL_MS + 1);
    expect(chatCalls()).toEqual([]);
  });
});

describe("useChatList: a filter a Creator's Platform cannot honour reads nothing for her", () => {
  const GATED: Array<[string, ChatListFilter | null, string | null]> = [
    ["pinned", "pinned", null], ["priority", "priority", null], ["who_tipped", "who_tipped", null],
    ["unread_tips", "unread_tips", null], ["a folder", null, "700000001"],
  ];
  const OPEN: Array<[string, ChatListFilter | null, string | null]> = [["All", null, null], ["unread", "unread", null]];
  const FAN_OF: Record<string, number> = { "acct-a": 1, "acct-b": 2, "acct-f": 3 };
  const sent = () => relayGet.mock.calls
    .filter((c) => String(c[0]).startsWith("/api/of/v2/chats"))
    .map((c) => [c[0], c[1]]);
  const asFansly = (id: string) => client.setQueryData(["chatter", "self", "accounts"], [{ account_id: id, platform: "fansly" }]);
  beforeEach(() => {
    serve = (aid) => ({ list: [row(FAN_OF[aid], "2026-08-25T10:00:00Z")], hasMore: false });
  });
  afterEach(() => {
    window.localStorage.removeItem(PLATFORM_KEY);
    resetPlatformForTests();
  });

  it("waits for the roster before reading cold Pinned, then uses the original OnlyFans key and request", async () => {
    client.removeQueries({ queryKey: ["chatter", "self", "accounts"] });
    const h = renderHook(() => useChatList({ filter: "pinned" }), { wrapper });
    await settle();
    expect(sent()).toEqual([]);

    act(() => { client.setQueryData(["chatter", "self", "accounts"], [{ account_id: "acct-a", platform: "onlyfans" }]); });
    await until("OnlyFans rows", () => h.result.current.data.length === 1);
    expect(sent()).toEqual([["/api/of/v2/chats?limit=25&offset=0&order=recent&filter=pinned", { accountId: "acct-a", priority: "user", caller: "mount" }]]);
    expect(client.getQueryData(["chats", "model", "acct-a", "pinned", null, null, 25])).toBeDefined();
  });

  it("reads Pinned with the original key and request for a legacy chatter Creator", async () => {
    client.setQueryData(["chatter", "self", "accounts"], [{ account_id: "acct-a" }]);
    const h = renderHook(() => useChatList({ filter: "pinned" }), { wrapper });
    await settle();
    expect(sent()).toEqual([["/api/of/v2/chats?limit=25&offset=0&order=recent&filter=pinned", { accountId: "acct-a", priority: "user", caller: "mount" }]]);
    expect(client.getQueryData(["chats", "model", "acct-a", "pinned", null, null, 25])).toBeDefined();
    expect(h.result.current.data.map((c) => c.withUser.id)).toEqual([1]);
  });

  it("reads nothing and settles empty when a cold Pinned Creator resolves to Fansly", async () => {
    client.removeQueries({ queryKey: ["chatter", "self", "accounts"] });
    const h = renderHook(() => useChatList({ filter: "pinned" }), { wrapper });
    await settle();
    act(() => { asFansly("acct-a"); });
    await settle(POLL_MS);
    expect(sent()).toEqual([]);
    expect(h.result.current.isSuccess).toBe(true);
    expect(h.result.current.data).toEqual([]);
    expect(h.result.current.hasMore).toBe(false);
  });

  it.each(GATED)("an OnlyFans Creator while the switch says Fansly, %s: read as before", async (_n, filter, listId) => {
    setPlatform("fansly");
    const h = renderHook(() => useChatList({ filter, listId }), { wrapper });
    await until("row", () => h.result.current.data.length === 1);
    const qs = new URLSearchParams({ limit: "25", offset: "0", order: "recent" });
    if (filter) qs.set("filter", filter);
    if (listId) qs.set("list_id", listId);
    expect(sent()).toEqual([[`/api/of/v2/chats?${qs.toString()}`, { accountId: "acct-a", priority: "user", caller: "mount" }]]);
    expect(client.getQueryData(chatsQueryKey("model", "acct-a", { filter, listId }))).toBeDefined();
  });

  it.each(GATED)("a Fansly Creator whose Platform resolves after two pages were read, %s: none of her rows remain", async (_n, filter, listId) => {
    mockScope = { kind: "model", accountId: "acct-f" };
    mockAccounts = [{ id: "acct-f", platform: "fansly" }];
    client.setQueryData(["chatter", "self", "accounts"], [{ account_id: "acct-f", platform: "onlyfans" }]);
    serve = (_aid, offset) => offset === 0
      ? { list: [row(3, "2026-08-25T10:00:00Z")], hasMore: true }
      : { list: [row(4, "2026-08-25T09:00:00Z")], hasMore: false };
    const h = renderHook(() => useChatList({ filter, listId }), { wrapper });
    await until("page 0", () => h.result.current.data.length === 1);
    await act(async () => { await h.result.current.loadMore("auto"); });
    await until("page 1", () => h.result.current.data.length === 2);
    relayGet.mockClear();

    act(() => { asFansly("acct-f"); });
    await until("emptied", () => h.result.current.data.length === 0 && !h.result.current.isPlaceholderData);
    expect(h.result.current.hasMore).toBe(false);
    expect(h.result.current.isFetching).toBe(false);
    await settle(POLL_MS);
    expect(h.result.current.data).toEqual([]);
    expect(sent()).toEqual([]);
  });

  it.each(GATED)("All Models, %s: no Fansly request or row on load and poll; OnlyFans reads exactly as without her", async (_n, filter, listId) => {
    mockScope = { kind: "all" };
    mockAccounts = [{ id: "acct-a" }, { id: "acct-b", platform: "onlyfans" }];
    const ofOnly = renderHook(() => useChatList({ filter, listId }), { wrapper });
    await until("OnlyFans-only list", () => ofOnly.result.current.isSuccess);
    const want = sent();
    expect(want.map(([, ctx]) => (ctx as { accountId: string }).accountId)).toEqual(["acct-a", "acct-b"]);
    ofOnly.unmount();
    client.clear();
    relayGet.mockClear();

    mockAccounts = [{ id: "acct-a" }, { id: "acct-f", platform: "fansly" }, { id: "acct-b", platform: "onlyfans" }];
    const h = renderHook(() => useChatList({ filter, listId }), { wrapper });
    await until("mixed list", () => h.result.current.isSuccess);
    expect(sent()).toEqual(want);
    expect(h.result.current.data.map((c) => c.__accountId).sort()).toEqual(["acct-a", "acct-b"]);
    expect(h.result.current.hasMore).toBe(false);
    expect(h.result.current.isFetching).toBe(false);
    relayGet.mockClear();
    await settle(POLL_MS);
    expect(sent().map(([, ctx]) => (ctx as { accountId: string }).accountId).sort()).toEqual(["acct-a", "acct-b"]);
  });

  it.each(OPEN)("All Models, %s: the Fansly Creator is read", async (_n, filter, listId) => {
    mockScope = { kind: "all" };
    mockAccounts = [{ id: "acct-a" }, { id: "acct-f", platform: "fansly" }];
    const h = renderHook(() => useChatList({ filter, listId }), { wrapper });
    await until("list", () => h.result.current.data.length === 2);
    expect(sent().map(([, ctx]) => (ctx as { accountId: string }).accountId)).toEqual(["acct-a", "acct-f"]);
  });

  it.each(GATED)("one Fansly Creator, %s: no request on load or poll, an empty settled page", async (_n, filter, listId) => {
    mockScope = { kind: "model", accountId: "acct-f" };
    mockAccounts = [{ id: "acct-f", platform: "fansly" }];
    asFansly("acct-f");
    const h = renderHook(() => useChatList({ filter, listId }), { wrapper });
    await until("settled", () => h.result.current.isSuccess);
    expect(h.result.current.data).toEqual([]);
    expect(h.result.current.hasMore).toBe(false);
    expect(h.result.current.isFetching).toBe(false);
    expect(h.result.current.fetchedLive).toBe(true);
    await settle(POLL_MS);
    expect(sent()).toEqual([]);
  });

  it.each(OPEN)("one Fansly Creator, %s: she is read", async (_n, filter, listId) => {
    mockScope = { kind: "model", accountId: "acct-f" };
    mockAccounts = [{ id: "acct-f", platform: "fansly" }];
    asFansly("acct-f");
    const h = renderHook(() => useChatList({ filter, listId }), { wrapper });
    await until("row", () => h.result.current.data.length === 1);
    expect(sent().map(([, ctx]) => (ctx as { accountId: string }).accountId)).toEqual(["acct-f"]);
  });

  it.each([...OPEN, ...GATED])("one OnlyFans Creator, %s: the same request and rows as before", async (_n, filter, listId) => {
    const h = renderHook(() => useChatList({ filter, listId }), { wrapper });
    await until("row", () => h.result.current.data.length === 1);
    const qs = new URLSearchParams({ limit: "25", offset: "0", order: "recent" });
    if (filter) qs.set("filter", filter);
    if (listId) qs.set("list_id", listId);
    expect(sent()).toEqual([[`/api/of/v2/chats?${qs.toString()}`, { accountId: "acct-a", priority: "user", caller: "mount" }]]);
    expect(h.result.current.data.map((c) => [c.__accountId, c.withUser.id])).toEqual([["acct-a", 1]]);
  });
});

describe("useChatList fetchedLive: rows read from OF in this page load", () => {
  const unread = (id: number) => ({ ...row(id, `2026-08-25T${String(20 - id).padStart(2, "0")}:00:00Z`), unreadMessagesCount: 1 }) as OFChatItem;
  function restore(pages: OFChatItem[][], updatedAt = Date.now()) {
    const rows = pages.map((list, i) => {
      const hasMore = i < pages.length - 1;
      return {
        rows: list.map((c) => ({ ...c, __accountId: "acct-a", hasUnread: true })),
        hasMore, moreAccounts: hasMore ? ["acct-a"] : [], scanned: list.length,
      };
    });
    client.setQueryData(MODEL_KEY, { pages: rows, pageParams: pages.map((_, i) => i * 25) }, { updatedAt });
  }

  it("is true once the mount fetch lands", async () => {
    serve = () => ({ list: [unread(1)], hasMore: false });
    const h = renderHook(() => useChatList(), { wrapper });
    expect(h.result.current.fetchedLive).toBe(false);
    await until("fetched", () => h.result.current.fetchedLive);
  });

  it("is false for a list restored from disk until a read of OF (the head poll) lands", async () => {
    restore([[unread(1), unread(2)]]);
    serve = () => ({ list: [unread(1), unread(2)], hasMore: false });
    const h = renderHook(() => useChatList(), { wrapper });
    await until("rows", () => h.result.current.data.length === 2);
    await settle(1_000);
    expect(chatCalls()).toEqual([]);
    expect(h.result.current.fetchedLive).toBe(false);

    await settle(POLL_MS);
    await until("live after the poll", () => h.result.current.fetchedLive);
  });

  it("a live event before the mount fetch lands does not make a restored list live", async () => {
    restore([[unread(1), unread(2)]], Date.now() - 60_000);
    let land!: () => void;
    serve = () => new Promise((r) => { land = () => r({ list: [unread(1), unread(2)], hasMore: false }); }) as unknown as ReturnType<typeof serve>;
    const h = renderHook(() => useChatList(), { wrapper });
    renderHook(() => useInboxRealtime(), { wrapper });
    await until("mount fetch asked", () => chatCalls().length === 1);

    fireInbound(9, "new", "2026-08-25T21:00:00Z");
    await until("fan 9 on top", () => h.result.current.data[0]?.withUser.id === 9);
    expect(h.result.current.fetchedLive).toBe(false);

    await act(async () => { land(); });
    await until("live once the fetch lands", () => h.result.current.fetchedLive);
  });

  it("a live event keeps a fetched list live", async () => {
    serve = () => ({ list: [unread(1)], hasMore: false });
    const h = renderHook(() => useChatList(), { wrapper });
    renderHook(() => useInboxRealtime(), { wrapper });
    await until("fetched", () => h.result.current.fetchedLive);
    fireInbound(9, "new", "2026-08-25T21:00:00Z");
    await until("fan 9 on top", () => h.result.current.data[0]?.withUser.id === 9);
    expect(h.result.current.fetchedLive).toBe(true);
  });

  it("stays true across a remount in the same page load (navigating between list pages)", async () => {
    serve = () => ({ list: [unread(1)], hasMore: false });
    const first = renderHook(() => useChatList(), { wrapper });
    await until("fetched", () => first.result.current.fetchedLive);
    first.unmount();
    relayGet.mockClear();

    const second = renderHook(() => useChatList(), { wrapper });
    expect(second.result.current.fetchedLive).toBe(true);
    await settle(1_000);
    expect(chatCalls()).toEqual([]);
  });

  it("stays false when the refetch over a restored list fails past page 0", async () => {
    restore([[unread(1)], [unread(2)]], Date.now() - 60_000);
    serve = (_aid, offset) => {
      if (offset > 0) throw new Error("page 1 down");
      return { list: [unread(1)], hasMore: true };
    };
    const h = renderHook(() => useChatList(), { wrapper });
    await until("refetch failed", () => h.result.current.isError);
    expect(chatCalls().map((c) => c.offset)).toEqual([0, 25]);
    expect(h.result.current.fetchedLive).toBe(false);
  });

  it("is false while another view's rows stand in for this one", async () => {
    serve = () => ({ list: [unread(1)], hasMore: false });
    const h = renderHook(({ filter }) => useChatList({ filter }), {
      wrapper, initialProps: { filter: null as "unread" | null },
    });
    await until("fetched", () => h.result.current.fetchedLive);

    serve = () => new Promise(() => {}) as unknown as ReturnType<typeof serve>;
    h.rerender({ filter: "unread" });
    await settle();
    expect(h.result.current.isPlaceholderData).toBe(true);
    expect(h.result.current.fetchedLive).toBe(false);
  });
});

describe("useChatList placeholderData: which previous rows stand in", () => {
  it("keeps only OnlyFans placeholder rows while Pinned loads in a mixed All Models inbox", async () => {
    mockScope = { kind: "all" };
    mockAccounts = [{ id: "acct-a" }, { id: "acct-f", platform: "fansly" }];
    serve = (aid) => ({ list: [row(aid === "acct-a" ? 1 : 2, "2026-08-25T10:00:00Z")], hasMore: false });
    const h = renderHook(({ filter }) => useChatList({ filter }), {
      wrapper, initialProps: { filter: null as ChatListFilter | null },
    });
    await until("both Creators", () => h.result.current.data.length === 2);
    serve = () => new Promise(() => {}) as unknown as ReturnType<typeof serve>;
    h.rerender({ filter: "pinned" });
    expect(h.result.current.data.map((c) => c.__accountId)).toEqual(["acct-a"]);
    expect(h.result.current.isPlaceholderData).toBe(true);
  });

  it("All Models keeps the previous rows while a session drops out of the set", async () => {
    mockScope = { kind: "all" };
    mockAccounts = [{ id: "acct-a" }, { id: "acct-b" }];
    serve = (aid) => ({ list: aid === "acct-a" ? [row(1, "2026-08-25T10:00:00Z")] : [row(2, "2026-08-25T09:00:00Z")], hasMore: false });
    const h = renderHook(() => useChatList(), { wrapper });
    await until("both accounts' rows", () => h.result.current.data.length === 2);

    serve = () => new Promise(() => {}) as unknown as ReturnType<typeof serve>;
    mockAccounts = [{ id: "acct-a" }];
    h.rerender();
    await settle();
    expect(h.result.current.isPlaceholderData).toBe(true);
    expect(h.result.current.data.map((c) => c.withUser.id)).toEqual([1, 2]);
  });
});

describe("shareChatPages: rows shared by (account, fan), not by index", () => {
  const row = (fanId: number, text = "hi") => ({
    __accountId: "1", withUser: { id: fanId }, lastMessage: { id: fanId, text },
  }) as OFChatItem;
  const data = (rows: OFChatItem[]) => ({ pages: [{ rows, hasMore: false, moreAccounts: [], scanned: rows.length }], pageParams: [0] });

  it("a row moved to the top keeps every other row's object", () => {
    const [a, b, c] = [row(1), row(2), row(3)];
    const out = shareChatPages(data([a, b, c]), data([row(3, "new"), row(1), row(2)])) as ReturnType<typeof data>;
    expect(out.pages[0].rows[1]).toBe(a);
    expect(out.pages[0].rows[2]).toBe(b);
    expect(out.pages[0].rows[0]).not.toBe(c);
    expect(out.pages[0].rows[0].lastMessage?.text).toBe("new");
  });

  it("data equal to what is cached is the cached data", () => {
    const prev = data([row(1), row(2)]);
    expect(shareChatPages(prev, data([row(1), row(2)]))).toBe(prev);
  });
});

describe("unenriched", () => {
  it("skips a fan the enrichment named in the last ENRICH_TTL_MS, per Creator", async () => {
    const { unenriched, ENRICH_TTL_MS } = await import("./useChatList");
    const qc = new QueryClient();
    const now = Date.parse("2026-08-25T10:00:00Z");
    qc.setQueryData(["of-user", "A", 1], { id: 1, enrichedAt: now - 1 });
    qc.setQueryData(["of-user", "A", 2], { id: 2, enrichedAt: now - ENRICH_TTL_MS });
    expect(unenriched([1, 2, 3], "A", now, qc)).toEqual([2, 3]);
    expect(unenriched([1], "B", now, qc)).toEqual([1]);
  });

  it("a name a notification seeded is still enriched; an enriched one isn't re-asked within the TTL", async () => {
    const { enrichWithUsers } = await import("./useChatList");
    const { seedName } = await import("@/components/toastStore");
    const qc = new QueryClient();
    const chats = [{ ...row(1, "2026-08-25T10:00:00Z"), __accountId: "seed-acct" }];
    const byIds = () => relayGet.mock.calls.filter((c) => String(c[0]).startsWith("/admin/fans/seed-acct/by-ids")).length;
    seedName(qc, "seed-acct", 1, { name: "From a toast" });
    await enrichWithUsers(chats, "seed-acct", qc);
    expect(byIds()).toBe(1);
    seedName(qc, "seed-acct", 1, { name: "From a toast" });
    await enrichWithUsers(chats, "seed-acct", qc);
    expect(byIds()).toBe(1);
  });

  it("an identity switch (the cache cleared) names every fan again", async () => {
    const { enrichWithUsers } = await import("./useChatList");
    const qc = new QueryClient();
    const chats = [{ ...row(1, "2026-08-25T10:00:00Z"), __accountId: "switch-acct" }];
    const byIds = () => relayGet.mock.calls.filter((c) => String(c[0]).startsWith("/admin/fans/switch-acct/by-ids")).length;
    await enrichWithUsers(chats, "switch-acct", qc);
    await enrichWithUsers(chats, "switch-acct", qc);
    expect(byIds()).toBe(1);
    qc.clear();
    const out = await enrichWithUsers(chats, "switch-acct", qc);
    expect(byIds()).toBe(2);
    expect(out[0].withUser.name).toBe("fan-1");
  });
});

describe("useChatList head poll x a write during its read", () => {
  it("a row patched while the head read is out keeps the patch, and the head's other rows land (no whole-head discard)", async () => {
    const h = await renderThreePages();
    let answer!: (page: { list: OFChatItem[]; hasMore: boolean }) => void;
    serve = (_aid, offset) => {
      if (offset !== 0) throw new Error(`poll must not read offset ${offset}`);
      return new Promise((r) => { answer = r; }) as unknown as { list: OFChatItem[]; hasMore: boolean };
    };
    await settle(POLL_MS);
    expect(chatCalls().map((c) => c.offset)).toEqual([0]);

    flipCachedReadState(client, "acct-a", { fanId: 10, unread: false, at: null });
    await settle();
    answer({ list: [{ ...row(10, "2026-08-25T10:00:00Z"), hasUnread: true, unreadMessagesCount: 1 },
      { ...row(9, "2026-08-25T09:30:00Z"), lastMessage: { id: 901, text: "news", createdAt: "2026-08-25T09:30:00Z" } }],
    hasMore: true });
    await settle();
    await settle();

    const byId = (id: number) => h.result.current.data.find((c) => c.withUser.id === id)!;
    expect(byId(10).hasUnread).toBe(false);
    expect(byId(10).unreadMessagesCount).toBe(0);
    expect(byId(9).lastMessage?.text).toBe("news");
    await settle(15_000);
    expect(chatCalls().map((c) => c.offset)).toEqual([0]);
  });
});

describe("useChatList head poll x a newer manual Refresh (W30-mu #43)", () => {
  it("a slow head read that answers after a Refresh asked later leaves the Refresh's rows", async () => {
    const h = await renderTwoPages();
    const open: Array<{ offset: number; r: (p: { list: OFChatItem[]; hasMore: boolean }) => void }> = [];
    serve = (_aid, offset) => new Promise((r) => { open.push({ offset, r }); }) as unknown as
      { list: OFChatItem[]; hasMore: boolean };
    await settle(POLL_MS);
    expect(open.map((o) => o.offset)).toEqual([0]);
    let done = false;
    void h.result.current.refresh().finally(() => { done = true; });
    await until("refresh page 0 asked", () => open.length === 2);
    open[1].r({ list: [row(11, "2026-08-25T11:00:00Z"), row(10, "2026-08-25T10:00:00Z")], hasMore: true });
    await until("refresh page 1 asked", () => open.length === 3);
    open[2].r({ list: [row(8, "2026-08-25T08:00:00Z")], hasMore: false });
    await until("refresh settled", () => done);
    expect(h.result.current.data[0].withUser.id).toBe(11);
    open[0].r({ list: [unreadRow(10, "2026-08-25T10:00:00Z"), row(9, "2026-08-25T09:00:00Z")], hasMore: true });
    await settle();
    await settle();
    expect(h.result.current.data.map((c) => c.withUser.id)).toEqual([11, 10, 8]);
    expect(h.result.current.data[1].hasUnread).toBeFalsy();
  });
});

function manualServe() {
  const open = new Map<number, Array<(p: { list: OFChatItem[]; hasMore: boolean }) => void>>();
  serve = (_aid, offset) => new Promise((r) => {
    open.set(offset, [...(open.get(offset) ?? []), r]);
  }) as unknown as { list: OFChatItem[]; hasMore: boolean };
  return {
    asked: (offset: number) => (open.get(offset) ?? []).length > 0,
    answer(offset: number, list: OFChatItem[], hasMore = true) {
      const [r, ...rest] = open.get(offset) ?? [];
      if (!r) throw new Error(`no open read at offset ${offset}`);
      open.set(offset, rest);
      r({ list, hasMore });
    },
  };
}

const unreadRow = (id: number, createdAt: string): OFChatItem => ({ ...row(id, createdAt), hasUnread: true, unreadMessagesCount: 1 });

async function renderTwoPages() {
  serve = (_aid, offset) => offset === 0
    ? { list: [unreadRow(10, "2026-08-25T10:00:00Z"), row(9, "2026-08-25T09:00:00Z")], hasMore: true }
    : { list: [unreadRow(8, "2026-08-25T08:00:00Z"), row(7, "2026-08-25T07:00:00Z")], hasMore: false };
  const h = renderHook(() => useChatList(), { wrapper });
  await until("page 0", () => h.result.current.data.length === 2);
  await act(async () => { await h.result.current.loadMore("auto"); });
  await until("pages 0-1", () => h.result.current.data.length === 4);
  return h;
}

describe("useChatList commit: a read started before a live write never undoes it (W30-mu #12)", () => {
  const byId = (h: { result: { current: { data: OFChatItem[] } } }, id: number) =>
    h.result.current.data.find((c) => c.withUser.id === id)!;

  it("a Refresh whose page 0 was read before a read flip, page 1 after: the flip stands on page 0", async () => {
    const h = await renderTwoPages();
    const srv = manualServe();
    let done = false;
    void h.result.current.refresh().finally(() => { done = true; });
    await until("page 0 asked", () => srv.asked(0));
    srv.answer(0, [unreadRow(10, "2026-08-25T10:00:00Z"), row(9, "2026-08-25T09:00:00Z")]);
    await until("page 1 asked", () => srv.asked(25));
    act(() => flipCachedReadState(client, "acct-a", { fanId: 10, unread: false, at: null }));
    await settle();
    expect(byId(h, 10).hasUnread).toBe(false);
    srv.answer(25, [unreadRow(8, "2026-08-25T08:00:00Z"), row(7, "2026-08-25T07:00:00Z")], false);
    await until("refresh settled", () => done);
    expect(byId(h, 10).hasUnread).toBe(false);
    expect(byId(h, 10).unreadMessagesCount).toBe(0);
    expect(byId(h, 8).hasUnread).toBe(true);
  });

  it("a loadMore in flight across a flip re-commits the pages it captured with the flip on them", async () => {
    serve = (_aid, offset) => offset === 0
      ? { list: [unreadRow(10, "2026-08-25T10:00:00Z"), row(9, "2026-08-25T09:00:00Z")], hasMore: true }
      : { list: [], hasMore: false };
    const h = renderHook(() => useChatList(), { wrapper });
    await until("page 0", () => h.result.current.data.length === 2);
    const srv = manualServe();
    let done = false;
    void h.result.current.loadMore("auto").finally(() => { done = true; });
    await until("page 1 asked", () => srv.asked(25));
    act(() => flipCachedReadState(client, "acct-a", { fanId: 10, unread: false, at: null }));
    srv.answer(25, [row(8, "2026-08-25T08:00:00Z")], false);
    await until("loadMore settled", () => done);
    expect(byId(h, 10).hasUnread).toBe(false);
    expect(byId(h, 8)).toBeTruthy();
  });

  it("reply, then read flip, then a stale Refresh: the row keeps the reply's preview and the read", async () => {
    const h = await renderTwoPages();
    const srv = manualServe();
    let done = false;
    void h.result.current.refresh().finally(() => { done = true; });
    await until("page 0 asked", () => srv.asked(0));
    act(() => {
      applyCachedReply(client, "acct-a", {
        fanId: 10, id: 5555, createdAt: "2026-08-25T10:30:00Z", text: "our reply", mediaCount: 0, price: 0, at: null,
      });
      flipCachedReadState(client, "acct-a", { fanId: 10, unread: false, at: null });
    });
    srv.answer(0, [unreadRow(10, "2026-08-25T10:00:00Z"), row(9, "2026-08-25T09:00:00Z")]);
    await until("page 1 asked", () => srv.asked(25));
    srv.answer(25, [unreadRow(8, "2026-08-25T08:00:00Z"), row(7, "2026-08-25T07:00:00Z")], false);
    await until("refresh settled", () => done);
    expect(byId(h, 10).lastMessage?.text).toBe("our reply");
    expect(byId(h, 10).hasUnread).toBe(false);
  });

  it("mark-all, then a newer inbound DM, then a stale Refresh: every row read but the DM's, which stays unread", async () => {
    const h = await renderTwoPages();
    renderHook(() => useInboxRealtime(), { wrapper });
    const srv = manualServe();
    let done = false;
    void h.result.current.refresh().finally(() => { done = true; });
    await until("page 0 asked", () => srv.asked(0));
    act(() => flipCachedReadState(client, "acct-a", { fanId: null, unread: false, at: Date.parse("2026-08-25T10:10:00Z") }));
    fireInbound(9, "after the mark", "2026-08-25T10:20:00Z");
    srv.answer(0, [unreadRow(10, "2026-08-25T10:00:00Z"), row(9, "2026-08-25T09:00:00Z")]);
    await until("page 1 asked", () => srv.asked(25));
    srv.answer(25, [row(8, "2026-08-25T08:00:00Z"), row(7, "2026-08-25T07:00:00Z")], false);
    await until("refresh settled", () => done);
    expect(byId(h, 10).hasUnread).toBe(false);
    expect(byId(h, 8).hasUnread).toBeFalsy();
    expect(byId(h, 9).hasUnread).toBe(true);
    expect(byId(h, 9).lastMessage?.text).toBe("after the mark");
    expect(h.result.current.data[0].withUser.id).toBe(9);
  });
});

describe("useChatList askedAt on the Relay's clock (W30-mu #14)", () => {
  afterEach(() => setRelayOffset(0));

  it("a tab clock 60 s ahead: a flip the Relay made after the page was asked still applies", async () => {
    setRelayOffset(60_000);
    serve = () => ({ list: [unreadRow(10, "2026-08-25T10:00:00Z")], hasMore: false });
    const h = renderHook(() => useChatList(), { wrapper });
    await until("page 0", () => h.result.current.data.length === 1);
    act(() => flipCachedReadState(client, "acct-a", { fanId: 10, unread: false, at: Date.now() - 60_000 + 5_000 }));
    await settle();
    expect(h.result.current.data[0].hasUnread).toBe(false);
  });

  it("a tab clock 30 s ahead: a send replayed over a page holding a newer fan DM leaves the DM's preview and unread (W30-mu #30)", async () => {
    setRelayOffset(30_000);
    const h = await renderTwoPages();
    const srv = manualServe();
    let done = false;
    void h.result.current.refresh().finally(() => { done = true; });
    await until("page 0 asked", () => srv.asked(0));
    act(() => patchChatListAfterSend(client, "acct-a", 10,
      { fromUserId: "acct-a", fromUserName: "me", text: "our send", mediaCount: 0, price: 0 }));
    const dmAt = new Date(Date.now() - 30_000 + 5_000).toISOString();
    srv.answer(0, [{ ...unreadRow(10, dmAt), lastMessage: { id: 7777, text: "fan DM", createdAt: dmAt } } as OFChatItem,
      row(9, "2026-08-25T09:00:00Z")]);
    await until("page 1 asked", () => srv.asked(25));
    srv.answer(25, [row(8, "2026-08-25T08:00:00Z")], false);
    await until("refresh settled", () => done);
    const fan = h.result.current.data.find((c) => c.withUser.id === 10)!;
    expect(fan.lastMessage?.text).toBe("fan DM");
    expect(fan.hasUnread).toBe(true);
  });
});

describe("useCachedChatPages: another list's entry, subscribed without an observer (W30-mu #20)", () => {
  it("re-renders on a live patch of that entry and never fetches it", async () => {
    const key = chatsQueryKey("model", "acct-a", { filter: "unread" });
    client.setQueryData(key, { pages: [{ rows: [unreadRow(10, "2026-08-25T10:00:00Z")], hasMore: false, moreAccounts: [], scanned: 1 }], pageParams: [0] });
    const h = renderHook(() => useCachedChatPages(key), { wrapper });
    expect(h.result.current?.pages[0]).toMatchObject({ rows: [{ withUser: { id: 10 } }] });
    act(() => { client.setQueryData(key, { pages: [{ rows: [], hasMore: false, moreAccounts: [], scanned: 0 }], pageParams: [0] }); });
    expect(h.result.current?.pages[0]).toMatchObject({ rows: [] });
    expect(relayGet).not.toHaveBeenCalled();
  });
});

describe("chat-list paging budget, replay cap and caller tags (chatlist-429 01-05)", () => {
  type Served = { list: OFChatItem[]; hasMore: boolean; split_version?: string };
  const tagged = () => relayGet.mock.calls
    .filter((c) => String(c[0]).startsWith("/api/of/v2/chats"))
    .map((c) => {
      const ctx = (c[1] ?? {}) as { accountId?: string; caller?: string; intent?: string };
      return { offset: Number(new URLSearchParams(String(c[0]).split("?")[1]).get("offset")), caller: ctx.caller, intent: ctx.intent };
    });
  const at = (offset: number, ids: number[], hasMore = true): Served => ({
    list: ids.map((id, i) => row(id, `2026-08-25T${String(23 - Math.floor(offset / 25)).padStart(2, "0")}:${String(59 - i).padStart(2, "0")}:00Z`)),
    hasMore,
  });
  function cache(pages: number[][], updatedAt = Date.now() - 60_000) {
    client.setQueryData(MODEL_KEY, {
      pages: pages.map((ids) => ({
        rows: at(0, ids).list.map((c) => ({ ...c, __accountId: "acct-a" })), hasMore: true, moreAccounts: ["acct-a"], scanned: ids.length,
      })),
      pageParams: pages.map((_, i) => i * 25),
    }, { updatedAt });
  }
  const SIX = [[1, 2], [3, 4], [5, 6], [7, 8], [9, 10], [11, 12]];

  it("a stale 6-page list re-reads only offsets 0-75; pages 5-6 come from the cache", async () => {
    cache(SIX);
    serve = (_a, offset) => at(offset, [offset + 100, offset + 101]);
    const h = renderHook(() => useChatList(), { wrapper });
    await until("walk landed", () => h.result.current.data[0]?.withUser.id === 100 && !h.result.current.isFetching);
    expect(tagged()).toEqual([0, 25, 50, 75].map((offset) => ({ offset, caller: "replay", intent: undefined })));
    expect(h.result.current.pages?.length).toBe(6);
    expect(h.result.current.data.slice(-4).map((c) => c.withUser.id)).toEqual([9, 10, 11, 12]);
  });

  it.each([["old", "new"], [undefined, "new"], ["old", undefined], ["same", "same"]])(
    "replays a split inbox tail only when its version agrees (%s → %s)", async (cachedVersion, freshVersion) => {
      const cachedRows = new Map([
        [0, row(7, new Date(Date.now() - 60_000).toISOString())],
        [3, row(8, "2026-08-25T20:58:00Z")],
        [4, row(9, "2026-08-25T19:59:00Z")],
      ]);
      client.setQueryData(MODEL_KEY, {
        pages: SIX.map((_, i) => {
          const cached = cachedRows.get(i);
          return {
            rows: cached ? [{ ...cached, __accountId: "acct-a" }] : [],
            hasMore: true, moreAccounts: ["acct-a"], scanned: 2,
            splitVersions: cachedVersion ? { "acct-a": cachedVersion } : undefined,
          };
        }),
        pageParams: SIX.map((_, i) => i * 25),
      }, { updatedAt: Date.now() - 60_000 });
      serve = (_a, offset) => ({ ...at(offset, [offset + 100]), split_version: freshVersion });
      const h = renderHook(() => useChatList(), { wrapper });
      await until("walk landed", () => h.result.current.data.some((c) => c.withUser.id === 100) && !h.result.current.isFetching);
      const equal = cachedVersion === freshVersion;
      expect(h.result.current.pages).toHaveLength(equal ? 6 : 4);
      const cachedIds = h.result.current.data.map((c) => c.withUser.id).filter((id) => Number(id) < 100);
      expect(cachedIds).toEqual(equal ? [7, 8, 9] : []);
      expect(h.result.current.hasMore).toBe(true);
      expect(tagged().map((c) => c.offset)).toEqual([0, 25, 50, 75]);
    },
  );

  it("a rank shift between fresh page 1 and cached page 5 shows that fan once, from the fresh page", async () => {
    cache(SIX);
    serve = (_a, offset) => (offset === 0 ? at(0, [9, 1]) : at(offset, [offset + 100]));
    const h = renderHook(() => useChatList(), { wrapper });
    await until("walk landed", () => h.result.current.data[0]?.withUser.id === 9 && !h.result.current.isFetching);
    const ids = h.result.current.data.map((c) => c.withUser.id);
    expect(ids.filter((id) => id === 9)).toHaveLength(1);
    expect(ids).toEqual([9, 1, 125, 150, 175, 10, 11, 12]);
    expect(h.result.current.pages?.[4].map((c) => c.withUser.id)).toEqual([9, 10]);
  });

  it.each([1, 3])("keeps every cached row after a head shift of %i", async (shift) => {
    const original = Array.from({ length: 150 }, (_, i) => i + 1);
    const inserted = Array.from({ length: shift }, (_, i) => 151 + i);
    const ranked = [...inserted, ...original];
    const page = (ids: number[]) => ids.map((id) => row(id, new Date(Date.UTC(2026, 7, 25) - ranked.indexOf(id) * 60_000).toISOString()));
    client.setQueryData(MODEL_KEY, {
      pages: Array.from({ length: 6 }, (_, i) => ({
        rows: page(original.slice(i * 25, (i + 1) * 25)).map((c) => ({ ...c, __accountId: "acct-a" })),
        hasMore: true, moreAccounts: ["acct-a"], scanned: 25,
      })),
      pageParams: [0, 25, 50, 75, 100, 125],
    }, { updatedAt: Date.now() - 60_000 });
    serve = (_a, offset) => ({ list: page(ranked.slice(offset, offset + 25)), hasMore: true });
    const h = renderHook(() => useChatList(), { wrapper });
    await until("walk landed", () => h.result.current.data[0]?.withUser.id === 151 && !h.result.current.isFetching);
    expect(h.result.current.data.map((c) => c.withUser.id)).toEqual(ranked);
    expect(tagged().map((c) => c.offset)).toEqual([0, 25, 50, 75]);
  });

  it("drops replayed Unread pages and restores deep paging by explicit request", async () => {
    const key = chatsQueryKey("model", "acct-a", { filter: "unread" });
    const recent = new Date(Date.now() - 60_000).toISOString();
    client.setQueryData(key, {
      pages: SIX.map((ids) => ({
        rows: ids.map((id) => ({ ...row(id, recent), __accountId: "acct-a", unreadMessagesCount: 1 })),
        hasMore: true, moreAccounts: ["acct-a"], scanned: ids.length,
      })),
      pageParams: [0, 25, 50, 75, 100, 125],
    }, { updatedAt: Date.now() - 60_000 });
    serve = (_a, offset) => at(offset, [offset + 100]);
    const h = renderHook(() => useChatList({ filter: "unread" }), { wrapper });
    await until("walk landed", () => h.result.current.data[0]?.withUser.id === 100 && !h.result.current.isFetching);
    expect(h.result.current.data.map((c) => c.withUser.id)).toEqual([100, 125, 150, 175]);
    expect(tagged().map((c) => c.offset)).toEqual([0, 25, 50, 75]);
    expect(h.result.current.hasMore).toBe(true);
    await act(async () => { await h.result.current.loadMore("loadmore"); });
    expect(tagged().at(-1)).toEqual({ offset: 100, caller: "loadmore", intent: "explicit" });
  });

  it("the hover prefetch of the same stale 6-page list re-reads only offsets 0-75, tagged prefetch", async () => {
    cache(SIX);
    serve = (_a, offset) => at(offset, [offset + 100]);
    await act(async () => { await prefetchModelChatList(client, "acct-a"); });
    expect(tagged()).toEqual([0, 25, 50, 75].map((offset) => ({ offset, caller: "prefetch", intent: undefined })));
    expect((client.getQueryData(MODEL_KEY) as { pages: unknown[] }).pages).toHaveLength(6);
  });

  it("two loadMore in one tick: one offset-25 request, tagged by the call that started it", async () => {
    serve = (_a, offset) => at(offset, [offset + 1]);
    const h = renderHook(() => useChatList(), { wrapper });
    await until("page 0", () => h.result.current.data.length === 1 && !h.result.current.isFetching);
    relayGet.mockClear();
    await act(async () => {
      void h.result.current.loadMore("autofill");
      void h.result.current.loadMore("loadmore");
    });
    await until("page 1", () => h.result.current.data.length === 2);
    expect(tagged()).toEqual([{ offset: 25, caller: "autofill", intent: undefined }]);
  });

  it("a click during a 3-page replay: 0, 25, 50 once each, then exactly one 75 with explicit intent", async () => {
    cache([[1], [2], [3]]);
    const gates: Array<() => void> = [];
    serve = (_a, offset) => new Promise((r) => gates.push(() => r(at(offset, [offset + 100])))) as unknown as Served;
    const h = renderHook(() => useChatList(), { wrapper });
    await until("walk out", () => tagged().length === 1);
    await act(async () => { void h.result.current.loadMore("loadmore"); void h.result.current.loadMore("scroll"); });
    for (let i = 0; i < 4; i++) {
      await until(`read ${i}`, () => gates.length > 0);
      await act(async () => gates.shift()!());
    }
    await until("page 4", () => h.result.current.pages?.length === 4 && !h.result.current.isFetching);
    await settle(10);
    expect(tagged()).toEqual([
      ...[0, 25, 50].map((offset) => ({ offset, caller: "replay", intent: undefined })),
      { offset: 75, caller: "loadmore", intent: "explicit" },
    ]);
  });

  it("past the automatic budget only a click or a fresh scroll pages, one page each", async () => {
    cache([[1], [2], [3], [4]], Date.now());
    serve = (_a, offset) => at(offset, [offset + 100]);
    const h = renderHook(() => useChatList(), { wrapper });
    await until("restored", () => h.result.current.pages?.length === 4);
    for (const caller of ["autofill", "fill", "search", "auto"] as const) {
      await act(async () => { await h.result.current.loadMore(caller, 0); });
    }
    expect(tagged()).toEqual([]);
    await act(async () => { await h.result.current.loadMore("loadmore", 0); });
    expect(tagged()).toEqual([{ offset: 100, caller: "loadmore", intent: "explicit" }]);
    await act(async () => { await h.result.current.loadMore("autofill", 0); });
    expect(tagged()).toHaveLength(1);
  });

  it("a clicked deep page that fails once is retried with the same explicit intent", async () => {
    client.setQueryDefaults(["chats"], { retry: chatListRetry, retryDelay: 0 });
    focusManager.setFocused(true);
    cache([[1], [2], [3], [4]], Date.now());
    let failed = false;
    serve = (_a, offset) => {
      if (offset === 100 && !failed) { failed = true; throw new RelayError(502, { detail: "upstream 500" }); }
      return at(offset, [offset + 100]);
    };
    const h = renderHook(() => useChatList(), { wrapper });
    await until("restored", () => h.result.current.pages?.length === 4);
    await act(async () => { void h.result.current.loadMore("loadmore", 0); });
    await until("page 5", () => h.result.current.pages?.length === 5);
    focusManager.setFocused(undefined);
    expect(tagged()).toEqual([0, 1].map(() => ({ offset: 100, caller: "loadmore", intent: "explicit" })));
  });

  it.each<[number, number, boolean]>([[1, 25, true], [2, 7, true], [2, 8, false], [3, 0, true]])(
    "automatic paging with %i pages and %i rows on screen: asks the next page %s", async (pages, visible, asks) => {
      cache(Array.from({ length: pages }, (_, i) => [i + 1]), Date.now());
      serve = (_a, offset) => at(offset, [offset + 100]);
      const h = renderHook(() => useChatList(), { wrapper });
      await until("restored", () => h.result.current.pages?.length === pages);
      await act(async () => { await h.result.current.loadMore("autofill", visible); });
      expect(tagged().length).toBe(asks ? 1 : 0);
    },
  );

  it.each([428, 429])("All Models: a %i from one Creator fails the page; nothing partial is committed and paging stays open", async (status) => {
    mockScope = { kind: "all" };
    mockAccounts = [{ id: "acct-a" }, { id: "acct-b" }];
    serve = (aid, offset) => {
      if (offset > 0 && aid === "acct-b") throw new RelayError(status, {});
      return { list: [{ ...row(aid === "acct-a" ? 10 + offset : 20 + offset, "2026-08-25T10:00:00Z"), __accountId: aid } as OFChatItem], hasMore: offset === 0 };
    };
    const h = renderHook(() => useChatList(), { wrapper });
    await until("page 0", () => h.result.current.data.length === 2 && !h.result.current.isFetching);
    await act(async () => { await h.result.current.loadMore("loadmore").catch(() => {}); });
    await until("failed", () => h.result.current.isError);
    expect(h.result.current.pages?.length).toBe(1);
    expect(h.result.current.hasMore).toBe(true);
  });

  it("a cold mount is tagged mount, the head poll poll", async () => {
    serve = (_a, offset) => at(offset, [1], false);
    renderHook(() => useChatList(), { wrapper });
    await until("page 0", () => tagged().length === 1);
    await settle(POLL_MS);
    await until("poll", () => tagged().length === 2);
    expect(tagged().map((c) => c.caller)).toEqual(["mount", "poll"]);
  });

  it("warm-up refreshes each populated view head with its own request parameters", async () => {
    cache([[1], [2]], Date.now());
    const filtered = chatsQueryKey("model", "acct-a", { filter: "unread", limit: 20, order: "old" });
    client.setQueryData(filtered, client.getQueryData(MODEL_KEY));
    const inactive = Array.from({ length: 30 }, (_, i) => chatsQueryKey("model", "acct-a", { query: `search-${i}` }));
    for (const key of inactive) client.setQueryData(key, client.getQueryData(MODEL_KEY));
    renderHook(() => useChatList(), { wrapper });
    renderHook(() => useChatList({ filter: "unread", limit: 20, order: "old" }), { wrapper });
    await refreshChatHead(client, { kind: "model", accountId: "acct-a" }, [{ id: "acct-a" }]);
    expect(chatCalls()).toEqual([
      expect.objectContaining({ offset: 0, filter: null }),
      expect.objectContaining({ offset: 0, filter: "unread" }),
    ]);
    expect(relayGet.mock.calls[1][0]).toContain("limit=20&offset=0&order=old");
    expect(inactive.every((key) => client.getQueryState(key)?.isInvalidated)).toBe(true);
    expect((client.getQueryData(filtered) as { pages: unknown[] }).pages).toHaveLength(2);
  });

  it("the warm-up head refresh waits for a walk already out, then reads offset 0 once, tagged warmup", async () => {
    cache([[1], [2]]);
    const gates: Array<() => void> = [];
    serve = (_a, offset) => new Promise((r) => gates.push(() => r(at(offset, [offset + 100])))) as unknown as Served;
    const h = renderHook(() => useChatList(), { wrapper });
    await until("walk out", () => tagged().length === 1);
    let done = false;
    void refreshChatHead(client, { kind: "model", accountId: "acct-a" }, [{ id: "acct-a" }]).then(() => { done = true; });
    await act(async () => gates.shift()!());
    await until("read 25", () => gates.length > 0);
    expect(tagged().filter((c) => c.caller === "warmup")).toEqual([]);
    serve = (_a, offset) => at(offset, [999]);
    await act(async () => gates.shift()!());
    await until("head refreshed", () => done);
    await settle();
    expect(tagged().map((c) => [c.offset, c.caller])).toEqual([[0, "replay"], [25, "replay"], [0, "warmup"]]);
    expect(h.result.current.data.map((c) => c.withUser.id)).toEqual([999, 125]);
  });
});

describe("useChatList: a Creator the Relay does not know is asked once, then left alone", () => {
  const unknown = () => new RelayError(404, { detail: { error: "unknown_account", message: "Unknown account_id 'acct-x'" } });
  const callsFor = (id: string) => chatCalls().filter((c) => c.accountId === id).length;

  beforeEach(() => {
    resetUnknownAccounts();
    client.setQueryDefaults(["chats"], { retry: chatListRetry, retryDelay: 0 });
  });
  afterEach(resetUnknownAccounts);

  it("one Creator: one read, no retry, no poll; the list says she is disconnected", async () => {
    mockScope = { kind: "model", accountId: "acct-x" };
    serve = () => { throw unknown(); };
    const h = renderHook(() => useChatList(), { wrapper });
    await until("marked", () => h.result.current.unknownAccount);
    await settle(POLL_MS * 3);
    expect(callsFor("acct-x")).toBe(1);
    expect(h.result.current.isError).toBe(false);
    expect(h.result.current.data).toEqual([]);
  });

  it("All Models: the unknown Creator drops out of the poll, the others keep polling", async () => {
    mockScope = { kind: "all" };
    mockAccounts = [{ id: "acct-a" }, { id: "acct-x" }];
    serve = (aid) => {
      if (aid === "acct-x") throw unknown();
      return { list: [row(1, "2026-08-25T10:00:00Z")], hasMore: false };
    };
    const h = renderHook(() => useChatList(), { wrapper });
    await until("page 0", () => h.result.current.data.length === 1);
    await settle(POLL_MS * 3);
    expect(callsFor("acct-x")).toBe(1);
    expect(callsFor("acct-a")).toBeGreaterThanOrEqual(3);
    expect(h.result.current.unknownAccount).toBe(false);
  });

  it("a roster refetch clears the mark: she is read again and, back, her chats show", async () => {
    mockScope = { kind: "model", accountId: "acct-x" };
    noteRoster("owner", 1);
    serve = () => { throw unknown(); };
    const h = renderHook(() => useChatList(), { wrapper });
    await until("marked", () => h.result.current.unknownAccount);
    serve = () => ({ list: [row(7, "2026-08-25T10:00:00Z")], hasMore: false });
    act(() => noteRoster("owner", 2));
    await until("back", () => h.result.current.data.length === 1);
    expect(h.result.current.unknownAccount).toBe(false);
    expect(callsFor("acct-x")).toBe(2);
  });

  it("All Models with every Creator unknown: the poll timer disarms", async () => {
    mockScope = { kind: "all" };
    mockAccounts = [{ id: "acct-x" }];
    serve = () => { throw unknown(); };
    const timers = vi.spyOn(globalThis, "setTimeout");
    renderHook(() => useChatList(), { wrapper });
    await until("asked", () => callsFor("acct-x") === 1);
    await settle();
    timers.mockClear();
    await settle(POLL_MS * 3);
    expect(timers.mock.calls.filter(([, ms]) => ms === POLL_MS)).toEqual([]);
    expect(callsFor("acct-x")).toBe(1);
    timers.mockRestore();
  });

  it("a plain 404 still retries once", async () => {
    mockScope = { kind: "model", accountId: "acct-x" };
    serve = () => { throw new RelayError(404, { detail: "Not Found" }); };
    const h = renderHook(() => useChatList(), { wrapper });
    await until("failed", () => h.result.current.isError);
    expect(callsFor("acct-x")).toBe(2);
    expect(h.result.current.unknownAccount).toBe(false);
  });
});
