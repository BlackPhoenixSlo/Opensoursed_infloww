import { afterEach, describe, expect, it, vi } from "vitest";

import { resetCellFlagForTests } from "@/lib/cellFlag";
import { chatListAccountKey } from "@/hooks/useChatList";
import { QueryClient } from "@tanstack/react-query";
import { relay, STALE_CELL_GEN_EVENT } from "./relay";
import { askCells, currentCellMap, forgetCellMap, loadCellMap, refreshCellMap } from "./cellMap";
import { fetchAccounts, ownerAccountsQuery, type AccountsResp } from "./ownerAccounts";
import type { CellMap } from "./cellInbox";

const MAP: CellMap = {
  actor: "user:u1", grant_gen: 4, placement_gen: 2, cells: ["s02", "s03"],
  accounts: [{ platform: "onlyfans", account_id: "10", cell: "s02" }, { platform: "onlyfans", account_id: "20", cell: "s03" }],
};
const ALL = { kind: "all" } as Parameters<typeof chatListAccountKey>[0];

afterEach(() => { forgetCellMap(); vi.restoreAllMocks(); });

describe("chat list key", () => {
  it("env unset (no Cell map): the key is main's", () => {
    expect(chatListAccountKey(ALL, [{ id: "20" }, { id: "10" }])).toBe("10,20");
  });

  it("with a Cell map: actor, grant and Placement generations ride the key; forgetting drops them", async () => {
    vi.spyOn(relay, "get").mockResolvedValue(MAP);
    await loadCellMap();
    expect(chatListAccountKey(ALL, [{ id: "10" }])).toBe("10,@user:u1:4:2");
    forgetCellMap();
    expect(currentCellMap()).toBeNull();
    expect(chatListAccountKey(ALL, [{ id: "10" }])).toBe("10");
  });
});

describe("askCells", () => {
  it("one Cell timing out marks only its own Creators; the other answers", async () => {
    const got = await askCells(MAP, ["10", "20"], undefined, async ({ cell }) => {
      if (cell === "s02") throw Object.assign(new Error("slow"), { name: "TimeoutError" });
      return { value: cell, partial: [] };
    });
    expect(got.map((r) => [r.cell, r.ok])).toEqual([["s02", false], ["s03", true]]);
  });

  it("an outer abort is rethrown, not counted against a Cell", async () => {
    const ac = new AbortController();
    ac.abort();
    await expect(askCells(MAP, ["10"], ac.signal, async () => { throw new Error("aborted"); })).rejects.toThrow("aborted");
  });
});

describe("cell-mode roster", () => {
  it("a Cell that has not answered within the roster wait keeps its Creators as bare rows", async () => {
    const meta = document.createElement("meta");
    meta.name = "oi-cells";
    document.head.appendChild(meta);
    resetCellFlagForTests();
    vi.useFakeTimers({ toFake: ["setTimeout"] });
    try {
      vi.spyOn(relay, "get").mockImplementation(((path: string, ctx?: { cellId?: string }) => {
        if (path === "/auth/cells") return Promise.resolve(MAP);
        if (ctx?.cellId === "s02") return Promise.resolve({ accounts: [{ id: "10", nickname: "Ten", has_session: true }] });
        return new Promise(() => {});
      }) as typeof relay.get);
      const got = fetchAccounts();
      await vi.advanceTimersByTimeAsync(1_000);
      const r = await got;
      expect(r.accounts).toEqual([
        expect.objectContaining({ id: "10", nickname: "Ten", has_session: true }),
        { id: "20", platform: "onlyfans", is_active: true, proxy_down: true, rosterPending: true },
      ]);
    } finally {
      vi.useRealTimers();
      meta.remove();
      resetCellFlagForTests();
    }
  });
});

it("reloads once and keeps the prior grants when the control Cell fails", async () => {
  const get = vi.spyOn(relay, "get").mockResolvedValueOnce(MAP).mockRejectedValueOnce(new Error("offline"));
  await loadCellMap();
  const reload = refreshCellMap();
  expect(refreshCellMap()).toBe(reload);
  await expect(reload).rejects.toThrow("offline");
  expect(currentCellMap()).toBe(MAP);
  const revoked = { ...MAP, grant_gen: 5, accounts: [] };
  get.mockResolvedValueOnce(revoked);
  await expect(refreshCellMap()).resolves.toBe(revoked);
  expect(currentCellMap()).toBe(revoked);
});

it("dedupes refresh events from relay failures", async () => {
  const get = vi.spyOn(relay, "get").mockResolvedValue(MAP);
  const moved = { ...MAP, placement_gen: 3 };
  await loadCellMap();
  const pending = Promise.withResolvers<CellMap>();
  get.mockReturnValueOnce(pending.promise);
  for (const reason of ["stale", "not_owner", "actor_stale"]) {
    window.dispatchEvent(new CustomEvent(STALE_CELL_GEN_EVENT, { detail: { reason } }));
  }
  expect(get).toHaveBeenCalledTimes(2);
  pending.resolve(moved);
  await expect(refreshCellMap()).resolves.toBe(moved);
  expect(currentCellMap()).toBe(moved);
});

it("keeps the cached roster after the paint deadline, then publishes the late answer", async () => {
  const meta = document.createElement("meta");
  meta.name = "oi-cells";
  document.head.appendChild(meta);
  resetCellFlagForTests();
  const client = new QueryClient();
  const options = ownerAccountsQuery("u1");
  const late = Promise.withResolvers<unknown>();
  vi.useFakeTimers({ toFake: ["setTimeout"] });
  try {
    vi.spyOn(relay, "get").mockImplementation(async (path, ctx) => {
      if (path === "/auth/cells") return MAP as never;
      if (ctx?.cellId === "s02") return { accounts: [{ id: "10", nickname: "Ten" }] } as never;
      return late.promise as Promise<never>;
    });
    const first = client.fetchQuery(options);
    await vi.advanceTimersByTimeAsync(1_000);
    expect((await first).accounts.map((a) => a.nickname)).toEqual(["Ten", undefined]);
    late.resolve({ accounts: [{ id: "20", nickname: "Twenty" }] });
    await vi.advanceTimersByTimeAsync(0);
    expect(client.getQueryData<AccountsResp>(options.queryKey)?.accounts.map((a) => a.nickname))
      .toEqual(["Ten", "Twenty"]);
    vi.mocked(relay.get).mockRejectedValue(new Error("offline"));
    const next = await client.fetchQuery({ ...options, staleTime: 0 });
    expect(next.accounts.map((a) => a.nickname)).toEqual(["Ten", "Twenty"]);
  } finally {
    client.clear();
    vi.useRealTimers();
    meta.remove();
    resetCellFlagForTests();
  }
});

it("backs off sequential routing failures and lets stale generation bypass once", async () => {
  vi.useFakeTimers();
  try {
    const get = vi.spyOn(relay, "get").mockResolvedValue(MAP);
    const signal = (reason: string) => window.dispatchEvent(new CustomEvent(STALE_CELL_GEN_EVENT, { detail: { reason } }));
    await loadCellMap();
    signal("stale");
    await refreshCellMap();
    expect(get).toHaveBeenCalledTimes(2);
    signal("stale");
    signal("not_owner");
    signal("not_owner");
    expect(get).toHaveBeenCalledTimes(2);
    await vi.advanceTimersByTimeAsync(1_000);
    expect(get).toHaveBeenCalledTimes(3);
  } finally {
    vi.useRealTimers();
  }
});

it("aborts a stalled map read and permits a later refresh", async () => {
  const nativeTimeout = AbortSignal.timeout.bind(AbortSignal);
  vi.spyOn(AbortSignal, "timeout").mockImplementation(() => nativeTimeout(10));
  const get = vi.spyOn(relay, "get").mockImplementationOnce((_path, _ctx, signal) => new Promise((_resolve, reject) => {
    if (!signal) return reject(new Error("missing deadline"));
    signal.addEventListener("abort", () => reject(signal.reason), { once: true });
  })).mockResolvedValue(MAP);
  await expect(loadCellMap()).rejects.toMatchObject({ name: "TimeoutError" });
  await expect(refreshCellMap()).resolves.toBe(MAP);
  expect(get).toHaveBeenCalledTimes(2);
});
