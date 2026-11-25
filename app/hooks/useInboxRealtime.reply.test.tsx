import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import type { OFChatItem } from "@/lib/relay";
import { rosterCountsKey, type RosterCountsResp } from "@/hooks/useRosterCounts";

const A = "1000001";
const B = "1000002";
const FOREIGN = "3000003";
const FAN = 9001001;

type Handler = (env: unknown) => void;
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
vi.mock("@/hooks/useAccounts", () => ({ useActiveAccounts: () => [{ id: A }, { id: B }] }));
vi.mock("@/hooks/useServerScheduledSends", () => ({
  scheduledSendsKey: (a: string, f: number) => ["scheduled-sends", a, f],
}));
vi.mock("@/lib/relay", () => ({ relay: { get: vi.fn(), post: vi.fn() } }));

import { relay } from "@/lib/relay";
import { useInboxRealtime } from "@/hooks/useInboxRealtime";

const ALL_KEY = ["chats", "all", `${A},${B}`, null, null, null, 30] as const;
const UNREAD_KEY = ["chats", "all", `${A},${B}`, "unread", null, null, 30] as const;
const infinite = (rows: OFChatItem[]) => ({ pages: [{ rows, hasMore: false, askedAt: 1 }], pageParams: [0] });

function chatRow(fanId: number, accountId: string, spokeLast: "fan" | "us", unread = 0): OFChatItem {
  return {
    withUser: { id: fanId, name: `fan${fanId}` },
    __accountId: accountId,
    hasUnread: unread > 0,
    unreadMessagesCount: unread,
    lastMessage: {
      id: fanId, text: "old", createdAt: "2026-11-20T09:00:00.000Z",
      fromUser: { id: spokeLast === "fan" ? fanId : Number(accountId) },
    },
  } as OFChatItem;
}

const replied = (accountId: string, fanId = FAN, id = 7001) => ({
  __account_id: accountId,
  chat_responded: {
    fan_id: fanId, by: "Kingsley", at: Date.parse("2026-11-20T10:00:01Z"),
    message: { id, text: "<p>on it</p>", createdAt: "2026-11-20T10:00:00+00:00", mediaCount: 0, price: 0 },
  },
});

let client: QueryClient;
const wrapper = ({ children }: { children: ReactNode }) =>
  <QueryClientProvider client={client}>{children}</QueryClientProvider>;
const fire = (env: unknown) => act(() => { handlers.get("chat_responded")?.forEach((h) => h(env)); });
const rows = (key: readonly unknown[]) =>
  (client.getQueryData(key) as ReturnType<typeof infinite>).pages[0].rows;
const roster = (aid: string) => client.getQueryData<RosterCountsResp>(rosterCountsKey("anon"))?.counts?.[aid];

beforeEach(() => {
  handlers.clear();
  client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } });
});
afterEach(() => { cleanup(); vi.clearAllMocks(); });

describe("useInboxRealtime — chat_responded", () => {
  it("another chatter's reply lifts the fan's All Models row, marks it ours + read, clears owe-reply; no reads", () => {
    client.setQueryData(ALL_KEY, infinite([chatRow(5, B, "fan", 1), chatRow(FAN, A, "fan")]));
    client.setQueryData(UNREAD_KEY, infinite([chatRow(5, B, "fan", 1)]));
    client.setQueryData(rosterCountsKey("anon"), { counts: { [A]: { unread: 0, owe_reply: 3 } } });
    renderHook(() => useInboxRealtime(), { wrapper });

    fire(replied(A));

    const [top, second] = rows(ALL_KEY);
    expect(top.withUser.id).toBe(FAN);
    expect(top.lastMessage).toMatchObject({ id: 7001, text: "<p>on it</p>", fromUser: { id: A } });
    expect(top.hasUnread).toBe(false);
    expect(second.withUser.id).toBe(5);
    expect(rows(UNREAD_KEY).map((c) => c.withUser.id)).toEqual([5]);
    expect(roster(A)).toEqual({ unread: 0, owe_reply: 3 });
    expect(relay.get).not.toHaveBeenCalled();
  });

  it("the same event twice (or after this tab's own bump) moves nothing more", () => {
    client.setQueryData(ALL_KEY, infinite([chatRow(FAN, A, "fan", 2)]));
    client.setQueryData(rosterCountsKey("anon"), { counts: { [A]: { unread: 4, owe_reply: 0 } } });
    renderHook(() => useInboxRealtime(), { wrapper });

    fire(replied(A));
    fire(replied(A));

    expect(roster(A)).toEqual({ unread: 4, owe_reply: 0 });
    expect(rows(ALL_KEY)).toHaveLength(1);
  });

  it("a fan in no cached list, an older relay's bare event, another principal's Creator: nothing, no reads", () => {
    const seeded = infinite([chatRow(5, B, "fan")]);
    client.setQueryData(ALL_KEY, seeded);
    client.setQueryData(rosterCountsKey("anon"), { counts: { [A]: { unread: 0, owe_reply: 1 } } });
    renderHook(() => useInboxRealtime(), { wrapper });

    fire(replied(A, 424242));
    fire({ __account_id: B, chat_responded: { fan_id: 5, by: "K" } });
    fire(replied(FOREIGN, 5));

    expect(client.getQueryData(ALL_KEY)).toBe(seeded);
    expect(roster(A)).toEqual({ unread: 0, owe_reply: 1 });
    expect(relay.get).not.toHaveBeenCalled();
  });
});

describe("useInboxRealtime — Live connection messages leave the cached count alone", () => {
  const msg = (accountId: string, fanId: number, id: number, outbound = false) => ({
    __account_id: accountId,
    ...(outbound ? { __fan_id: fanId } : {}),
    api2_chat_message: {
      id, text: "hey", createdAt: "2026-11-20T10:00:00.000Z",
      fromUser: outbound ? { id: Number(accountId), name: "us" } : { id: fanId, name: "f" },
    },
  });

  it("inbound and outbound, on a loaded and a cold row: roster-counts unchanged, no ?bust=", async () => {
    client.setQueryData(ALL_KEY, infinite([chatRow(FAN, A, "fan"), chatRow(5, A, "us")]));
    const counts = { counts: { [A]: { unread: 2, owe_reply: 1 }, [B]: { unread: 0, owe_reply: 0 } } };
    client.setQueryData(rosterCountsKey("anon"), counts);
    renderHook(() => useInboxRealtime(), { wrapper });
    const send = (env: unknown) => act(() => { handlers.get("api2_chat_message")?.forEach((h) => h(env)); });

    send(msg(A, 5, 8001));
    send(msg(A, FAN, 8002, true));
    send(msg(B, 777001, 8003));
    send(msg(B, 777002, 8004, true));
    await act(async () => { await new Promise((r) => setTimeout(r, 0)); });

    expect(client.getQueryData(rosterCountsKey("anon"))).toBe(counts);
    expect(vi.mocked(relay.get).mock.calls.map(([p]) => String(p)).filter((p) => p.includes("bust="))).toEqual([]);
  });
});
