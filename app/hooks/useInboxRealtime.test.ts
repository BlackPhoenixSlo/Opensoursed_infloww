import { describe, it, expect, vi, beforeEach, afterEach, type Mock } from "vitest";
import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { relay, type OFMessage, type OFMessagesResp } from "@/lib/relay";
import { prefetchChatMessages, useChatMessages } from "@/hooks/useChatMessages";
import { dropTombstoned } from "@/lib/threadCache";

type Handler = (env: unknown) => void;
const handlers = new Map<string, Set<Handler>>();
vi.mock("@/lib/events", () => ({
  eventBus: {
    isConnected: () => false,
    onStateChange: () => () => {},
    on(type: string, fn: Handler) {
      let set = handlers.get(type);
      if (!set) { set = new Set(); handlers.set(type, set); }
      set.add(fn);
      return () => set!.delete(fn);
    },
  },
}));
vi.mock("@/hooks/useAccounts", () => ({ useActiveAccounts: () => [{ id: "900539700124344320" }, { id: "500" }] }));
vi.mock("@/lib/relay", () => ({ relay: { get: vi.fn(), post: vi.fn() } }));

import { insertByCreatedAt, resolveChatTarget, toUtcIso, useInboxRealtime } from "./useInboxRealtime";

const row = (id: number, createdAt: string): OFMessage =>
  ({ id, createdAt }) as unknown as OFMessage;
const ids = (list: OFMessage[]) => list.map((m) => m.id);

describe("resolveChatTarget", () => {
  it("inbound → targets the sender's chat", () => {
    const t = resolveChatTarget({
      __account_id: "100",
      api2_chat_message: { id: 5, fromUser: { id: 777 } },
    });
    expect(t).toMatchObject({ accountId: "100", fanId: 777, isOutbound: false, fromId: 777 });
  });

  it("outbound with __fan_id → targets the recipient, not the sender", () => {
    const t = resolveChatTarget({
      __account_id: "100",
      __fan_id: 888,
      api2_chat_message: { id: 6, fromUser: { id: 100 } },
    });
    expect(t).toMatchObject({ accountId: "100", fanId: 888, isOutbound: true, fromId: 100 });
  });

  it("outbound falls back to toUser.id when __fan_id is absent", () => {
    const t = resolveChatTarget({
      __account_id: "100",
      api2_chat_message: { id: 7, fromUser: { id: 100 }, toUser: { id: 999 } },
    });
    expect(t).toMatchObject({ fanId: 999, isOutbound: true });
  });

  it("outbound with NO recipient is unroutable → null (legacy skip preserved)", () => {
    expect(
      resolveChatTarget({
        __account_id: "100",
        api2_chat_message: { id: 8, fromUser: { id: 100 } },
      }),
    ).toBeNull();
  });

  it("malformed events → null", () => {
    expect(resolveChatTarget({})).toBeNull();
    expect(resolveChatTarget({ __account_id: "100" })).toBeNull();
    expect(resolveChatTarget({ __account_id: "100", api2_chat_message: { id: 9 } })).toBeNull();
  });

  it("Creator echo (no fromUser) → outbound to chatUserId, msg stamped as the Creator's", () => {
    const t = resolveChatTarget({
      __account_id: "100",
      api2_chat_message: { id: 11, text: "<p>hey :)</p>", chatUserId: 337, toUser: { id: 337 } },
    });
    expect(t).toMatchObject({ accountId: "100", fanId: 337, isOutbound: true, fromId: 100 });
    expect(t?.msg.fromUser).toEqual({ id: 100 });
  });

  it("echo without a valid chatUserId, a non-numeric account, or a mass copy → null", () => {
    expect(resolveChatTarget({ __account_id: "100", api2_chat_message: { id: 12, chatUserId: "x" as unknown as number } })).toBeNull();
    expect(resolveChatTarget({ __account_id: "abc", api2_chat_message: { id: 13, chatUserId: 337 } })).toBeNull();
    expect(resolveChatTarget({ __account_id: "100", api2_chat_message: { id: 14, chatUserId: 337, isFromQueue: true } })).toBeNull();
  });

  it("non-numeric fromUser id → null", () => {
    expect(
      resolveChatTarget({
        __account_id: "100",
        api2_chat_message: { id: 10, fromUser: { id: "abc" as unknown as number } },
      }),
    ).toBeNull();
  });
});

describe("toUtcIso", () => {
  it("tags a zone-less wall clock as UTC", () => {
    expect(toUtcIso("2026-06-14 09:36:17")).toBe("2026-06-14T09:36:17.000Z");
  });

  it("truncates sub-millisecond precision on a zone-less value", () => {
    expect(toUtcIso("2026-06-14 09:36:17.000000")).toBe("2026-06-14T09:36:17.000Z");
  });

  it("passes through an already-zoned value (Z and +00:00 offset)", () => {
    expect(toUtcIso("2026-06-14T09:36:17Z")).toBe("2026-06-14T09:36:17.000Z");
    expect(toUtcIso("2026-06-14T09:36:17+00:00")).toBe("2026-06-14T09:36:17.000Z");
  });

  it("empty/undefined → a valid current ISO string", () => {
    expect(toUtcIso(undefined)).toMatch(/Z$/);
    expect(toUtcIso("")).toMatch(/Z$/);
  });

  it("unparseable garbage → returned unchanged (never throws)", () => {
    expect(toUtcIso("not a date")).toBe("not a date");
  });
});

describe("insertByCreatedAt", () => {
  it("a genuinely-newest message appends at the tail (the common path)", () => {
    const prev = [row(1, "2026-06-14T08:00:00Z"), row(2, "2026-06-14T09:00:00Z")];
    expect(ids(insertByCreatedAt(prev, row(3, "2026-06-14T10:00:00Z")))).toEqual([1, 2, 3]);
  });

  it("the bug case: an OLDER live row drops into the middle, not the bottom", () => {
    const prev = [
      row(10, "2026-06-14T17:23:00Z"),
      row(11, "2026-06-14T19:23:00Z"),
      row(12, "2026-06-14T20:04:00Z"),
    ];
    const out = insertByCreatedAt(prev, row(9, "2026-06-14T09:36:00Z"));
    expect(ids(out)).toEqual([9, 10, 11, 12]);
  });

  it("inserts between the right neighbours", () => {
    const prev = [
      row(1, "2026-06-14T08:00:00Z"),
      row(3, "2026-06-14T10:00:00Z"),
    ];
    expect(ids(insertByCreatedAt(prev, row(2, "2026-06-14T09:00:00Z")))).toEqual([1, 2, 3]);
  });

  it("ties keep arrival order (new equal-timestamp row goes after existing)", () => {
    const prev = [row(1, "2026-06-14T09:00:00Z")];
    expect(ids(insertByCreatedAt(prev, row(2, "2026-06-14T09:00:00Z")))).toEqual([1, 2]);
  });

  it("sorts a zone-less live row consistently against zoned REST rows", () => {
    const prev = [
      row(1, "2026-06-14T09:00:00Z"),
      row(3, "2026-06-14T10:00:00Z"),
    ];
    expect(ids(insertByCreatedAt(prev, row(2, "2026-06-14 09:30:00")))).toEqual([1, 2, 3]);
  });

  it("empty cache → single row", () => {
    expect(ids(insertByCreatedAt([], row(1, "2026-06-14T09:00:00Z")))).toEqual([1]);
  });
});

describe("useInboxRealtime — chat_message_deleted", () => {
  const AID = "900539700124344320";
  const FAN = "900000000000000042";
  const OTHER_FAN = "900000000000000043";
  const snow = (id: string) => ({ id, createdAt: "2026-11-28T00:00:00Z" }) as unknown as OFMessage;
  const sids = (list?: OFMessage[]) => (list ?? []).map((m) => String(m.id));
  let client: QueryClient;
  const wrapper = ({ children }: { children: ReactNode }) =>
    createElement(QueryClientProvider, { client }, children);
  const fire = (env: unknown) => act(() => { handlers.get("chat_message_deleted")?.forEach((h) => h(env)); });
  const deleted = (id: string, fan_id: string, aid = AID) =>
    ({ chat_message_deleted: { id, fan_id }, __account_id: aid });

  beforeEach(() => {
    handlers.clear();
    client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } });
  });
  afterEach(() => { cleanup(); });

  it("evicts the id from that Fan's Thread and leaves the other Thread and other account alone", () => {
    client.setQueryData(["messages", AID, FAN], [snow("700000000000000001"), snow("700000000000000002")]);
    client.setQueryData(["messages", AID, OTHER_FAN], [snow("700000000000000002"), snow("700000000000000003")]);
    client.setQueryData(["messages", "500", FAN], [snow("700000000000000002")]);
    renderHook(() => useInboxRealtime(), { wrapper });

    fire(deleted("700000000000000002", FAN));

    expect(sids(client.getQueryData(["messages", AID, FAN]))).toEqual(["700000000000000001"]);
    expect(sids(client.getQueryData(["messages", AID, OTHER_FAN]))).toEqual(["700000000000000002", "700000000000000003"]);
    expect(sids(client.getQueryData(["messages", "500", FAN]))).toEqual(["700000000000000002"]);
  });

  it("a Thread keyed by a numeric fan id is matched by the string fan_id", () => {
    client.setQueryData(["messages", "500", 77], [{ id: 1 } as OFMessage, { id: 2 } as OFMessage]);
    renderHook(() => useInboxRealtime(), { wrapper });

    fire(deleted("2", "77", "500"));

    expect(sids(client.getQueryData(["messages", "500", 77]))).toEqual(["1"]);
  });

  it("tombstones the id for that account so a later page cannot restore it", () => {
    renderHook(() => useInboxRealtime(), { wrapper });

    fire(deleted("700000000000000009", FAN));

    const page = [snow("700000000000000008"), snow("700000000000000009")];
    expect(sids(dropTombstoned(AID, page))).toEqual(["700000000000000008"]);
    expect(dropTombstoned("600", page)).toBe(page);
  });

  it("an account outside the roster or a malformed frame changes nothing", () => {
    const list = [snow("700000000000000011")];
    client.setQueryData(["messages", "999", FAN], list);
    client.setQueryData(["messages", AID, FAN], list);
    renderHook(() => useInboxRealtime(), { wrapper });

    fire(deleted("700000000000000011", FAN, "999"));
    fire({ chat_message_deleted: { id: "700000000000000011" }, __account_id: AID });
    fire({ chat_message_deleted: { fan_id: FAN }, __account_id: AID });

    expect(client.getQueryData(["messages", "999", FAN])).toBe(list);
    expect(client.getQueryData(["messages", AID, FAN])).toBe(list);
    expect(dropTombstoned("999", list)).toBe(list);
  });
});

describe("useChatMessages with the listener: an unsent Fansly message stays gone", () => {
  const ACCT = "900539700124344320";
  const BASE = 900404711209099264n;
  const s = (k: number) => (BASE + BigInt(k)).toString();
  const sm = (k: number) =>
    ({ id: s(k), text: `m${k}`, fromUser: { id: 7 }, media: [], createdAt: new Date(Date.UTC(2026, 10, 28, 4, 0, k)).toISOString() }) as unknown as OFMessage;
  const resp = (descRows: OFMessage[], hasMore = true) => ({ list: descRows, hasMore });
  const sids = (rows?: OFMessage[]) => (rows ?? []).map((m) => String(m.id));
  const FS_FAN = "900404711209000001";
  const FS_KEY = ["messages", ACCT, FS_FAN] as const;
  const relayGet = relay.get as unknown as Mock;
  const olderUrls = () => relayGet.mock.calls.map((c) => String(c[0])).filter((u) => u.includes("before_id="));
  let client: QueryClient;
  const wrapper = ({ children }: { children: ReactNode }) =>
    createElement(QueryClientProvider, { client }, children);
  const unsend = (k: number) => act(() => {
    handlers.get("chat_message_deleted")?.forEach((h) =>
      h({ chat_message_deleted: { id: s(k), fan_id: FS_FAN }, __account_id: ACCT }));
  });
  const mount = () => renderHook(() => {
    useInboxRealtime();
    return useChatMessages({ accountId: ACCT, fanId: FS_FAN });
  }, { wrapper });

  beforeEach(() => {
    handlers.clear();
    relayGet.mockReset();
    client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  });
  afterEach(() => { cleanup(); });

  it("a head response in flight when the message is unsent resolves without it", async () => {
    let release!: (r: OFMessagesResp) => void;
    let hold = false;
    relayGet.mockImplementation(() => hold
      ? new Promise<OFMessagesResp>((r) => { release = r; })
      : Promise.resolve(resp([sm(3), sm(2), sm(1)], true)));
    const { result } = mount();
    await waitFor(() => expect(sids(result.current.data)).toEqual([s(1), s(2), s(3)]));

    hold = true;
    let p!: Promise<unknown>;
    act(() => { p = result.current.refetch(); });
    unsend(2);
    expect(sids(client.getQueryData(FS_KEY))).toEqual([s(1), s(3)]);
    await act(async () => { release(resp([sm(3), sm(2), sm(1)], true)); await p; });

    expect(sids(client.getQueryData(FS_KEY))).toEqual([s(1), s(3)]);
    await waitFor(() => expect(sids(result.current.data)).toEqual([s(1), s(3)]));
  });

  it("an older page (served from cache) still holding the id does not restore it", async () => {
    relayGet.mockImplementation((url: string) => Promise.resolve(
      url.includes("before_id=") ? resp([sm(12), sm(11)], false) : resp([sm(15), sm(14), sm(13)], true)));
    const { result } = mount();
    await waitFor(() => expect(sids(result.current.data)).toEqual([s(13), s(14), s(15)]));

    unsend(12);
    await act(async () => { await result.current.loadOlder(); });

    expect(sids(client.getQueryData(FS_KEY))).toEqual([s(11), s(13), s(14), s(15)]);
    expect(sids(result.current.data)).toEqual([s(11), s(13), s(14), s(15)]);
  });

  it("an older page holding only unsent ids still moves the cursor below it", async () => {
    relayGet.mockImplementation((url: string) => {
      if (url.includes(`before_id=${s(23)}`)) return Promise.resolve(resp([sm(22), sm(21)], true));
      if (url.includes(`before_id=${s(21)}`)) return Promise.resolve(resp([sm(20)], false));
      return Promise.resolve(resp([sm(25), sm(24), sm(23)], true));
    });
    const { result } = mount();
    await waitFor(() => expect(sids(result.current.data)).toEqual([s(23), s(24), s(25)]));

    unsend(22);
    unsend(21);
    await act(async () => { await result.current.loadOlder(); });
    expect(sids(result.current.data)).toEqual([s(23), s(24), s(25)]);
    expect(result.current.hasOlder).toBe(true);

    await act(async () => { await result.current.loadOlder(); });
    expect(olderUrls()).toEqual([
      `/api/of/v2/chats/${FS_FAN}/messages?limit=30&order=desc&before_id=${s(23)}`,
      `/api/of/v2/chats/${FS_FAN}/messages?limit=30&order=desc&before_id=${s(21)}`,
    ]);
    expect(sids(result.current.data)).toEqual([s(20), s(23), s(24), s(25)]);
  });

  it("a background prefetch in flight when the message is unsent stores the page without it", async () => {
    let release!: (r: OFMessagesResp) => void;
    relayGet.mockImplementation(() => new Promise<OFMessagesResp>((r) => { release = r; }));
    renderHook(() => useInboxRealtime(), { wrapper });
    const p = prefetchChatMessages(client, ACCT, FS_FAN);
    await waitFor(() => expect(relayGet).toHaveBeenCalled());

    unsend(42);
    await act(async () => { release(resp([sm(42), sm(41)], true)); await p; });

    expect(sids(client.getQueryData(FS_KEY))).toEqual([s(41)]);
  });

  it("a row written back into the cache after the unsend is not shown", async () => {
    relayGet.mockResolvedValue(resp([sm(32), sm(31)], true));
    const { result } = mount();
    await waitFor(() => expect(sids(result.current.data)).toEqual([s(31), s(32)]));

    unsend(32);
    act(() => { client.setQueryData(FS_KEY, [sm(31), sm(32)]); });

    await waitFor(() => expect(sids(client.getQueryData(FS_KEY))).toEqual([s(31), s(32)]));
    await waitFor(() => expect(sids(result.current.data)).toEqual([s(31)]));
  });
});
