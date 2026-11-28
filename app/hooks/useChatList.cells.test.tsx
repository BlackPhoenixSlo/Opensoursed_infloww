import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { resetCellFlagForTests } from "@/lib/cellFlag";
import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { spliceCellHeads, useChatList } from "./useChatList";
import { askCells, forgetCellMap, loadCellMap, useGreyAccounts } from "@/lib/cellMap";
import { useRecentChatsLocal } from "./useRecentChatsLocal";
import { RelayError, relay } from "@/lib/relay";
import { markUnknown, resetUnknownAccounts, seenNow, unknownIds } from "@/lib/unknownAccounts";

const accounts = [{ id: "10", platform: "onlyfans" }, { id: "20", platform: "onlyfans" }];
vi.mock("@/contexts/ScopeContext", () => ({ useScope: () => ({ scope: { kind: "all" } }) }));
vi.mock("@/hooks/useAccounts", () => ({
  useAccounts: () => ({ data: { accounts } }),
  usePlatformAccounts: () => accounts,
}));
vi.mock("@/lib/relay", async (original) => ({
  ...(await original<typeof import("@/lib/relay")>()),
  relay: { get: vi.fn() },
  relayFocus: () => null,
}));

let client: QueryClient;
let meta: HTMLMetaElement;
const get = vi.mocked(relay.get);
function wrapper({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

beforeEach(() => {
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  meta = document.createElement("meta");
  meta.name = "oi-cells";
  document.head.append(meta);
  resetCellFlagForTests();
});
afterEach(() => {
  cleanup();
  client.clear();
  forgetCellMap();
  meta.remove();
  resetCellFlagForTests();
  get.mockReset();
  resetUnknownAccounts();
});

it("explicit paging uses the direct intent and retries a failed Creator's own offset", async () => {
  const calls: [string, string | null, string | undefined][] = [];
  let offline = true;
  get.mockImplementation(async (path, ctx) => {
    const qs = new URLSearchParams(path.split("?")[1]);
    if (path === "/auth/cells") return {
      actor: "test", grant_gen: 1, placement_gen: 1, cells: ["a"],
      accounts: accounts.map(({ id, platform }) => ({ account_id: id, platform, cell: "a" })),
    } as never;
    if (path.startsWith("/admin/screens/inbox")) {
      const ids = qs.get("accounts")!.split(",");
      if (ids.length === 1) calls.push([ids[0], qs.get("cursor"), ctx?.intent]);
      return { answers: ids.map((id) => ({ accountId: id, read: "chats", body: { list: [], hasMore: true } })) } as never;
    }
    if (path.startsWith("/api/of/v2/chats")) {
      calls.push([ctx?.accountId ?? "", qs.get("offset"), ctx?.intent]);
      if (ctx?.accountId === "20" && offline) throw new Error("offline");
      return { list: [], hasMore: true } as never;
    }
    throw new Error(path);
  });
  const hook = renderHook(() => useChatList(), { wrapper });
  await waitFor(() => expect(hook.result.current.hasMore).toBe(true));
  await act(async () => { await hook.result.current.loadMore("loadmore"); });
  offline = false;
  await act(async () => { await hook.result.current.loadMore("loadmore"); });
  expect(calls).toEqual([
    ["10", "25", "explicit"], ["20", "25", "explicit"], ["10", "50", "explicit"], ["20", "25", "explicit"],
  ]);

  offline = true;
  await act(async () => { await hook.result.current.loadMore("loadmore"); });
  offline = false;
  calls.length = 0;
  await act(async () => { await spliceCellHeads(client, new Set(["20"]), new Set(["10", "20"])); });
  expect(calls).toEqual([["20", "0", undefined], ["20", "50", "explicit"]]);
});

it("refreshes every named Creator head and retries the missing tail on All-inbox resync", async () => {
  let offline = true;
  get.mockImplementation(async (path, ctx) => {
    if (path === "/auth/cells") return {
      actor: "test", grant_gen: 1, placement_gen: 1, cells: ["a"],
      accounts: accounts.map(({ id, platform }) => ({ account_id: id, platform, cell: "a" })),
    } as never;
    const qs = new URLSearchParams(path.split("?")[1]);
    const body = { list: [], hasMore: true };
    if (path.startsWith("/admin/screens/inbox")) return {
      answers: qs.get("accounts")!.split(",").map((id) => ({ accountId: id, read: "chats", body })),
    } as never;
    if (offline && ctx?.accountId === "20" && qs.get("offset") === "25") throw new Error("offline");
    return body as never;
  });
  const hook = renderHook(() => useChatList(), { wrapper });
  await waitFor(() => expect(hook.result.current.hasMore).toBe(true));
  await act(async () => { await hook.result.current.loadMore("loadmore"); });

  offline = false;
  get.mockClear();
  const named = new Set(["10", "20"]);
  await act(async () => { await spliceCellHeads(client, named, named); });
  const requests = get.mock.calls.map(([path, ctx]) => {
    const qs = new URLSearchParams(path.split("?")[1]);
    return [qs.get("accounts") ?? ctx?.accountId, Number(qs.get("cursor") ?? qs.get("offset"))];
  });
  expect(requests).toContainEqual(["20", 25]);
  expect(requests).toContainEqual(["10,20", 0]);
});

it("propagates a paging 429 to React Query", async () => {
  get.mockImplementation(async (path, ctx) => {
    if (path === "/auth/cells") return {
      actor: "test", grant_gen: 1, placement_gen: 1, cells: ["a", "b"],
      accounts: accounts.map(({ id, platform }, i) => ({ account_id: id, platform, cell: i ? "b" : "a" })),
    } as never;
    if (path.startsWith("/admin/screens/inbox")) return {
      answers: [{ accountId: ctx?.cellId === "a" ? "10" : "20", read: "chats", body: { list: [], hasMore: true } }],
    } as never;
    throw new RelayError(429, null);
  });
  const hook = renderHook(() => useChatList(), { wrapper });
  await waitFor(() => expect(hook.result.current.hasMore).toBe(true));
  await act(async () => { await hook.result.current.loadMore("loadmore"); });
  expect(client.getQueryCache().findAll({ queryKey: ["chats"] }).map((q) => q.state.error))
    .toContainEqual(expect.objectContaining({ status: 429 }));
});

it("rebuilds offsets from the preceding refetched page after a partial answer", async () => {
  const asked: [string, number][] = [];
  let refetch = false;
  get.mockImplementation(async (path, ctx) => {
    if (path === "/auth/cells") return {
      actor: "test", grant_gen: 1, placement_gen: 1, cells: ["a"],
      accounts: accounts.map(({ id, platform }) => ({ account_id: id, platform, cell: "a" })),
    } as never;
    const qs = new URLSearchParams(path.split("?")[1]);
    const bundled = path.startsWith("/admin/screens/inbox");
    const offset = Number(qs.get(bundled ? "cursor" : "offset"));
    const ids = bundled ? qs.get("accounts")!.split(",") : [ctx!.accountId!];
    if (refetch) asked.push(...ids.map((id): [string, number] => [id, offset]));
    const body = { list: [], hasMore: true };
    if (bundled) return {
      partial: refetch && offset === 25 ? ["20"] : [],
      answers: ids.filter((id) => !(refetch && id === "20" && offset === 25))
        .map((id) => ({ accountId: id, read: "chats", body })),
    } as never;
    return body as never;
  });
  const hook = renderHook(() => useChatList(), { wrapper });
  await waitFor(() => expect(hook.result.current.hasMore).toBe(true));
  await act(async () => { await hook.result.current.loadMore("loadmore"); });
  await act(async () => { await hook.result.current.loadMore("loadmore"); });
  refetch = true;
  await act(async () => { await hook.result.current.refresh(); });
  expect(asked).toEqual([["10", 0], ["20", 0], ["10", 25], ["20", 25], ["10", 50], ["20", 25]]);
});

it("paints healthy cold seed rows and clears their fallback warning after inbox recovery", async () => {
  const row = { __accountId: "10", withUser: { id: 11 } };
  get.mockImplementation(async (path, ctx) => {
    if (path === "/auth/cells") return {
      actor: "test", grant_gen: 1, placement_gen: 1, cells: ["a", "b"],
      accounts: accounts.map(({ id, platform }, i) => ({ account_id: id, platform, cell: i ? "b" : "a" })),
    } as never;
    if (ctx?.cellId === "a") return { list: [row] } as never;
    return new Promise<never>(() => {});
  });
  const hook = renderHook(() => ({ seed: useRecentChatsLocal(), grey: useGreyAccounts() }), { wrapper });
  await waitFor(() => expect(hook.result.current.seed.rows).toEqual([row]), { timeout: 2_000 });
  expect([...hook.result.current.grey]).toEqual(["20"]);
  await act(async () => {
    await askCells(await loadCellMap(), ["20"], undefined, async () => ({ value: null, partial: [] }));
  });
  expect([...hook.result.current.grey]).toEqual([]);
}, 4_000);

const cellsMap = {
  actor: "test", grant_gen: 1, placement_gen: 1, cells: ["a"],
  accounts: accounts.map(({ id, platform }) => ({ account_id: id, platform, cell: "a" })),
};
const bundleAsks = () => get.mock.calls.filter(([path]) => path.startsWith("/admin/screens/inbox"))
  .map(([path]) => new URLSearchParams(path.split("?")[1]).get("accounts"));

it.each([
  ["unknown to the Relay", { read: "chats", status: 404, detail: { error: "unknown_account", message: "Unknown account_id '20'" } }],
  ["not on this screen", { read: "*", status: 404, detail: "not on this screen" }],
])("All Models cell bundle: a Creator %s is marked and left out of the next read", async (_name, gone) => {
  get.mockImplementation(async (path) => {
    if (path === "/auth/cells") return cellsMap as never;
    if (path.startsWith("/admin/screens/inbox")) return {
      answers: new URLSearchParams(path.split("?")[1]).get("accounts")!.split(",").map((id) => id === "20"
        ? { accountId: id, ...gone }
        : { accountId: id, read: "chats", body: { list: [], hasMore: false } }),
    } as never;
    throw new Error(path);
  });
  const hook = renderHook(() => useChatList(), { wrapper });
  await waitFor(() => expect(unknownIds().has("20")).toBe(true));
  await waitFor(() => expect(hook.result.current.isFetching).toBe(false));
  await act(async () => { await client.refetchQueries({ queryKey: ["chats"] }); });
  expect(bundleAsks()).toEqual(["10,20", "10"]);
});

it("All-inbox resync leaves a marked Creator out of the head read and the tail repair", async () => {
  get.mockImplementation(async (path, ctx) => {
    if (path === "/auth/cells") return cellsMap as never;
    const qs = new URLSearchParams(path.split("?")[1]);
    const body = { list: [], hasMore: true };
    if (path.startsWith("/admin/screens/inbox")) return {
      answers: qs.get("accounts")!.split(",").map((id) => ({ accountId: id, read: "chats", body })),
    } as never;
    if (ctx?.accountId === "20" && qs.get("offset") === "25") throw new Error("offline");
    return body as never;
  });
  const hook = renderHook(() => useChatList(), { wrapper });
  await waitFor(() => expect(hook.result.current.hasMore).toBe(true));
  await act(async () => { await hook.result.current.loadMore("loadmore"); });
  markUnknown("20", seenNow());
  get.mockClear();
  const named = new Set(["10", "20"]);
  await act(async () => { await spliceCellHeads(client, named, named); });
  const asked = get.mock.calls.map(([path, ctx]) => new URLSearchParams(path.split("?")[1]).get("accounts") ?? ctx?.accountId);
  expect(asked.some((ids) => ids?.split(",").includes("20"))).toBe(false);
});
