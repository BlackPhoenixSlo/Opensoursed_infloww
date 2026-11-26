import { afterEach, describe, expect, it, vi } from "vitest";

import { chatListAccountKey } from "@/hooks/useChatList";
import { relay } from "./relay";
import { askCells, currentCellMap, forgetCellMap, loadCellMap } from "./cellMap";
import { fetchAccounts } from "./ownerAccounts";
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
      expect(r.accounts.map((a) => [a.id, a.nickname ?? null, a.has_session])).toEqual([["10", "Ten", true], ["20", null, true]]);
    } finally {
      vi.useRealTimers();
      meta.remove();
    }
  });
});
