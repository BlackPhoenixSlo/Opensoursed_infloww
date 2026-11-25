import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider, QueryObserver } from "@tanstack/react-query";

import type { OFChatItem } from "@/lib/relay";

const MODEL_A = "1000001";
const MODEL_B = "1000002";
const FAN_A = 9001001;
const FAN_B = 111;
const FAN_AB = 222;

type Handler = (env: unknown, rawType?: string) => void;
const handlers = new Map<string, Set<Handler>>();
vi.mock("@/lib/events", () => ({
  eventBus: {
    on(type: string, fn: Handler) {
      let set = handlers.get(type);
      if (!set) { set = new Set(); handlers.set(type, set); }
      set.add(fn);
      return () => set!.delete(fn);
    },
  },
}));
vi.mock("@/hooks/useAccounts", () => ({
  useActiveAccounts: () => [{ id: "1000001" }, { id: "1000002" }],
}));
vi.mock("@/hooks/useServerScheduledSends", () => ({
  scheduledSendsKey: (a: string, f: number) => ["scheduled-sends", a, f],
}));

// eslint-disable-next-line import/first
import { useInboxRealtime } from "@/hooks/useInboxRealtime";
// eslint-disable-next-line import/first
import { chatsQueryKey } from "@/hooks/useChatList";
// eslint-disable-next-line import/first
import { CHATS_PAGE } from "@/lib/ofMirrorDataQueries";

function chatRow(fanId: number, accountId: string): OFChatItem {
  return {
    withUser: { id: fanId, name: `fan${fanId}` },
    __accountId: accountId,
    hasUnread: false,
    unreadMessagesCount: 0,
    lastMessage: {
      id: fanId,
      text: "old",
      fromUser: { id: fanId },
      createdAt: "2026-06-04T00:00:00.000Z",
    },
  } as OFChatItem;
}

type Page = { rows: OFChatItem[]; hasMore: boolean };
type Infinite = { pages: Page[]; pageParams: unknown[] };
const infinite = (rows: OFChatItem[]): Infinite => ({
  pages: [{ rows, hasMore: false }],
  pageParams: [undefined],
});

const KEY_A = ["chats", "model", MODEL_A, null, null, null, 25] as const;
const KEY_B = ["chats", "model", MODEL_B, null, null, null, 25] as const;
const KEY_ALL = ["chats", "all", `${MODEL_A},${MODEL_B}`, null, null, null, 25] as const;

const ids = (inf: Infinite | undefined) =>
  (inf?.pages.flatMap((p) => p.rows) ?? []).map((r) => r.withUser.id);

let client: QueryClient;
function wrapper({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function fire(env: unknown) {
  act(() => {
    handlers.get("api2_chat_message")?.forEach((h) => h(env));
  });
}

beforeEach(() => {
  handlers.clear();
  client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } });
});
afterEach(() => { cleanup(); vi.clearAllMocks(); });

describe("useInboxRealtime cross-model injection guard", () => {
  it("an inbound DM for model A lands in A + all, NOT in model B's list", () => {
    client.setQueryData(KEY_A, infinite([chatRow(FAN_AB, MODEL_A)]));
    client.setQueryData(KEY_B, infinite([chatRow(FAN_B, MODEL_B)]));
    client.setQueryData(KEY_ALL, infinite([chatRow(FAN_B, MODEL_B), chatRow(FAN_AB, MODEL_A)]));

    renderHook(() => useInboxRealtime(), { wrapper });

    fire({
      __account_id: MODEL_A,
      api2_chat_message: {
        id: 9001,
        text: "Y wait",
        fromUser: { id: FAN_A, name: "newfan" },
        createdAt: "2026-06-21T17:22:00.000Z",
      },
    });

    expect(ids(client.getQueryData<Infinite>(KEY_B))).toEqual([FAN_B]);

    const a = client.getQueryData<Infinite>(KEY_A)!;
    expect(ids(a)[0]).toBe(FAN_A);
    expect(a.pages[0].rows[0].unreadMessagesCount).toBe(1);
    expect(a.pages[0].rows[0].__accountId).toBe(MODEL_A);

    expect(ids(client.getQueryData<Infinite>(KEY_ALL))[0]).toBe(FAN_A);
  });

  it("bumps an EXISTING row even in a cache whose scope wouldn't re-create it", () => {
    client.setQueryData(KEY_ALL, infinite([chatRow(FAN_B, MODEL_B), chatRow(FAN_AB, MODEL_A)]));
    renderHook(() => useInboxRealtime(), { wrapper });

    fire({
      __account_id: MODEL_A,
      api2_chat_message: {
        id: 9100,
        text: "back again",
        fromUser: { id: FAN_AB, name: "fan222" },
        createdAt: "2026-06-21T18:00:00.000Z",
      },
    });

    const all = client.getQueryData<Infinite>(KEY_ALL)!;
    expect(ids(all)).toEqual([FAN_AB, FAN_B]);
    expect(all.pages[0].rows[0].lastMessage?.text).toBe("back again");
  });
});

describe("useInboxRealtime writes only the chat lists a message changes", () => {
  const fanWrote = (id: number, fanId = FAN_AB) => fire({
    __account_id: MODEL_A,
    api2_chat_message: { id, text: "hi", fromUser: { id: fanId, name: `fan${fanId}` }, createdAt: "2026-06-21T18:00:00.000Z" },
  });

  it("a list without the fan, and a page without the fan, keep their references", () => {
    const deeper = { rows: [chatRow(333, MODEL_A)], hasMore: false };
    client.setQueryData(KEY_A, { pages: [{ rows: [chatRow(FAN_AB, MODEL_A)], hasMore: true }, deeper], pageParams: [0, 25] });
    client.setQueryData(KEY_B, infinite([chatRow(FAN_B, MODEL_B)]));
    const bBefore = client.getQueryData(KEY_B);
    renderHook(() => useInboxRealtime(), { wrapper });

    fanWrote(9200);

    expect(client.getQueryData(KEY_B)).toBe(bBefore);
    const a = client.getQueryData<Infinite>(KEY_A)!;
    expect(a.pages[0].rows[0].lastMessage?.id).toBe(9200);
    expect(a.pages[1]).toBe(deeper);
  });

  it("does not insert a read row into Unread while the thread is open", () => {
    const unreadKey = ["chats", "model", MODEL_A, "unread", null, null, 25] as const;
    client.setQueryData(KEY_A, infinite([chatRow(FAN_AB, MODEL_A)]));
    client.setQueryData(unreadKey, infinite([]));
    const observer = new QueryObserver(client, { queryKey: ["messages", MODEL_A, FAN_AB], queryFn: async () => [] });
    const unsubscribe = observer.subscribe(() => {});
    try {
      renderHook(() => useInboxRealtime(), { wrapper });
      fanWrote(9300);
      expect(client.getQueryData<Infinite>(unreadKey)?.pages[0].rows).toEqual([]);
    } finally {
      unsubscribe();
    }
  });

  it("inserts a DM already present in All into the Unread view without counting it twice", () => {
    const unreadKey = ["chats", "model", MODEL_A, "unread", null, null, 25] as const;
    client.setQueryData(KEY_A, infinite([chatRow(FAN_AB, MODEL_A)]));
    renderHook(() => useInboxRealtime(), { wrapper });
    fanWrote(9300);
    const known = client.getQueryData<Infinite>(KEY_A)!;
    client.setQueryData(unreadKey, infinite([]));
    fanWrote(9300);
    expect(client.getQueryData(KEY_A)).toBe(known);
    expect(client.getQueryData<Infinite>(unreadKey)?.pages[0].rows).toEqual(known.pages[0].rows);
    expect(known.pages[0].rows[0].unreadMessagesCount).toBe(1);
    expect(client.getQueryData<Infinite>(unreadKey)?.pages[0].rows[0].__accountId).toBe(MODEL_A);
  });

  it("preserves the prior row's account when a new DM inserts it into Unread", () => {
    const unreadKey = ["chats", "all", `${MODEL_A},${MODEL_B}`, "unread", null, null, 25] as const;
    client.setQueryData(KEY_A, infinite([chatRow(FAN_AB, MODEL_A)]));
    client.setQueryData(unreadKey, infinite([chatRow(FAN_AB, MODEL_B)]));
    renderHook(() => useInboxRealtime(), { wrapper });

    fanWrote(9300);

    const rows = client.getQueryData<Infinite>(unreadKey)?.pages[0].rows;
    expect(rows?.map((row) => [row.__accountId, row.lastMessage?.id])).toEqual([
      [MODEL_A, 9300], [MODEL_B, FAN_AB],
    ]);
  });

  it("the same message delivered twice writes once and counts its unread once", () => {
    client.setQueryData(KEY_A, infinite([chatRow(FAN_B, MODEL_A), chatRow(FAN_AB, MODEL_A)]));
    renderHook(() => useInboxRealtime(), { wrapper });

    fanWrote(9300);
    const once = client.getQueryData<Infinite>(KEY_A)!;
    fanWrote(9300);

    expect(client.getQueryData(KEY_A)).toBe(once);
    expect(once.pages[0].rows[0].unreadMessagesCount).toBe(1);
  });
});

describe("useInboxRealtime mounted app-wide", () => {
  const fanWrote = (id: number, account = MODEL_A, fanId = FAN_AB) => fire({
    __account_id: account,
    api2_chat_message: { id, text: "live", fromUser: { id: fanId, name: `fan${fanId}` }, createdAt: "2026-06-21T19:00:00.000Z" },
  });

  it("mounted twice (app-wide listener + a leftover page mount), one message counts one unread", () => {
    client.setQueryData(KEY_A, infinite([chatRow(FAN_B, MODEL_A), chatRow(FAN_AB, MODEL_A)]));
    renderHook(() => useInboxRealtime(), { wrapper });
    renderHook(() => useInboxRealtime(), { wrapper });
    expect(handlers.get("api2_chat_message")?.size).toBe(2);

    fanWrote(9400);

    const a = client.getQueryData<Infinite>(KEY_A)!;
    expect(ids(a)).toEqual([FAN_AB, FAN_B]);
    expect(a.pages[0].rows[0].unreadMessagesCount).toBe(1);
    expect(a.pages[0].rows[0].hasUnread).toBe(true);
  });

  it("patches OF Manager's chat lists (its own page size) on any page, and keeps another model's clean", () => {
    const mirrorA = chatsQueryKey("model", MODEL_A, { limit: CHATS_PAGE });
    const mirrorUnreadA = chatsQueryKey("model", MODEL_A, { filter: "unread", limit: CHATS_PAGE });
    const mirrorB = chatsQueryKey("model", MODEL_B, { limit: CHATS_PAGE });
    client.setQueryData(mirrorA, infinite([chatRow(FAN_AB, MODEL_A)]));
    client.setQueryData(mirrorUnreadA, infinite([]));
    client.setQueryData(mirrorB, infinite([chatRow(FAN_B, MODEL_B)]));
    const bBefore = client.getQueryData(mirrorB);
    renderHook(() => useInboxRealtime(), { wrapper });

    fanWrote(9500, MODEL_A, FAN_A);

    expect(ids(client.getQueryData<Infinite>(mirrorA))).toEqual([FAN_A, FAN_AB]);
    expect(ids(client.getQueryData<Infinite>(mirrorUnreadA))).toEqual([FAN_A]);
    expect(client.getQueryData(mirrorB)).toBe(bBefore);
  });
});

describe("useInboxRealtime Creator echo (her send from OF web/app: no fromUser, chatUserId = the Fan)", () => {
  it("appends to the open thread and moves the Fan's row with her text, unread untouched", () => {
    const row = { ...chatRow(FAN_AB, MODEL_A), hasUnread: true, unreadMessagesCount: 2 } as OFChatItem;
    const unread = chatsQueryKey("model", MODEL_A, { filter: "unread" });
    client.setQueryData(unread, infinite([]));
    client.setQueryData(KEY_A, infinite([chatRow(FAN_B, MODEL_A), row]));
    client.setQueryData(["messages", MODEL_A, FAN_AB], [
      { id: 1, text: "old", fromUser: { id: FAN_AB }, createdAt: "2026-06-04T00:00:00.000Z" },
    ]);
    renderHook(() => useInboxRealtime(), { wrapper });

    fire({
      __account_id: MODEL_A,
      api2_chat_message: { id: 9400, text: "<p>hey :)</p>", chatUserId: FAN_AB, toUser: { id: FAN_AB },
                           createdAt: "2026-06-21T18:00:00+00:00" },
    });

    const thread = client.getQueryData<{ id: number; fromUser: { id: number } }[]>(["messages", MODEL_A, FAN_AB])!;
    expect(thread.map((m) => m.id)).toEqual([1, 9400]);
    expect(thread[1].fromUser.id).toBe(Number(MODEL_A));
    const top = client.getQueryData<Infinite>(KEY_A)!.pages[0].rows[0];
    expect(top.withUser.id).toBe(FAN_AB);
    expect(top.lastMessage?.text).toBe("<p>hey :)</p>");
    expect(top.lastMessage?.fromUser?.id).toBe(Number(MODEL_A));
    expect(top.unreadMessagesCount).toBe(2);
    expect(ids(client.getQueryData<Infinite>(unread))).toEqual([]);
  });
});
