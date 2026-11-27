import { describe, expect, it } from "vitest";

import type { CellMap } from "./cellInbox";
import {
  accountLive, allLive, blocked, cellBusReducer, downAccounts, INITIAL_CELL_BUS, liveChanges, planStreams, protoOf,
  mapLoadReducer, resyncAction, streamDiff, type CellBusAction, type CellBusState,
} from "./cellBusReducer";

const MAP: CellMap = {
  actor: "admin:1", grant_gen: 1, placement_gen: 2, cells: ["s02", "s01"], control: "c0",
  accounts: [
    { platform: "onlyfans", account_id: "10", cell: "s01" },
    { platform: "onlyfans", account_id: "11", cell: "s01" },
    { platform: "onlyfans", account_id: "20", cell: "s02" },
  ],
};
const run = (actions: CellBusAction[], from: CellBusState = INITIAL_CELL_BUS) => actions.reduce(cellBusReducer, from);
const plan = (proto: "ok" | "h1" | "unknown" = "ok", scope: "all" | `model:${string}` = "all"): CellBusAction =>
  ({ type: "Plan", map: MAP, scope, proto });
const live = (cell: string, v = true): CellBusAction => ({ type: "Live", cell, live: v });

describe("protoOf", () => {
  it.each([["h2", "ok"], ["h3", "ok"], ["h3-29", "ok"], ["http/1.1", "h1"], ["http/1.0", "h1"], ["", "unknown"],
    [undefined, "unknown"]] as const)("%s → %s", (hop, want) => expect(protoOf(hop)).toBe(want));
});

describe("planStreams", () => {
  it("all: control first, then each data Cell with its Creators", () => {
    expect(planStreams(MAP, "all")).toEqual([
      { cell: "c0", scope: "all", accounts: [] },
      { cell: "s01", scope: "all", accounts: ["10", "11"] },
      { cell: "s02", scope: "all", accounts: ["20"] },
    ]);
  });
  it("model scope opens only that Creator's Cell plus control", () => {
    expect(planStreams(MAP, "model:20")).toEqual([
      { cell: "c0", scope: "all", accounts: [] },
      { cell: "s02", scope: "model:20", accounts: ["20"] },
    ]);
  });
  it("restricted chatter: only the Cells the map names", () => {
    expect(planStreams({ ...MAP, cells: ["s02"] }, "all").map((p) => p.cell)).toEqual(["c0", "s02"]);
  });
  it("no control in the map → data Cells only", () => {
    expect(planStreams({ ...MAP, control: null }, "all").map((p) => p.cell)).toEqual(["s01", "s02"]);
  });
});

describe("s02 stale, s01 + control live", () => {
  const s = run([plan(), live("c0"), live("s01"), live("s02"), live("s02", false)]);
  it.each([["10", true], ["11", true], ["20", false], ["99", false]] as const)("account %s live=%s", (id, want) =>
    expect(accountLive(s, id)).toBe(want));
  it("head-poll plan and grey set are s02's Creators only", () => expect([...downAccounts(s)]).toEqual(["20"]));
  it("not all live", () => expect(allLive(s)).toBe(false));
  it("reports only s02's flip", () => {
    const before = run([plan(), live("c0"), live("s01"), live("s02")]);
    expect(liveChanges(before, s)).toEqual([{ cell: "s02", live: false, accounts: ["20"] }]);
  });
});

describe("cellBusReducer", () => {
  it("never-connected stream is not down (no grey before first open)", () => {
    expect([...downAccounts(run([plan()]))]).toEqual([]);
  });
  it("all live once every planned stream opened", () => {
    expect(allLive(run([plan(), live("c0"), live("s01"), live("s02")]))).toBe(true);
  });
  it("h1 plans no streams and blocks", () => {
    const s = run([plan("h1")]);
    expect(s.planned).toEqual([]);
    expect(blocked(s)).toBe(true);
    expect(allLive(s)).toBe(false);
  });
  it("unknown protocol still opens streams", () => {
    const s = run([plan("unknown")]);
    expect(s.planned.length).toBe(3);
    expect(blocked(s)).toBe(false);
  });
  it("Live for an unplanned Cell is ignored", () => {
    const s = run([plan()]);
    expect(cellBusReducer(s, live("s99"))).toBe(s);
  });
  it("same Live twice returns the same state", () => {
    const s = run([plan(), live("s01")]);
    expect(cellBusReducer(s, live("s01"))).toBe(s);
  });
  it("re-plan keeps liveness of kept Cells, drops removed ones", () => {
    const s = run([plan(), live("s01"), live("s02"), plan("ok", "model:20")]);
    expect(s.live).toEqual({ s02: true });
  });
});

it("disconnects removed Creators and connects Creators placed on live control", () => {
  const before = run([plan(), live("c0"), live("s01"), live("s02")]);
  const moved = { ...MAP, accounts: MAP.accounts.map((a) => a.account_id === "10" ? { ...a, cell: "c0" } : a) };
  const next = run([{ type: "Plan", map: moved, scope: "model:10", proto: "ok" }], before);
  expect(accountLive(next, "10")).toBe(true);
  expect(liveChanges(before, next)).toContainEqual({ cell: "s02", live: false, accounts: ["20"] });
});

describe("streamDiff", () => {
  const all = planStreams(MAP, "all");
  it("scope all → model:20 closes s01, rescopes s02", () => {
    const d = streamDiff(all, planStreams(MAP, "model:20"));
    expect(d.open).toEqual([]);
    expect(d.close).toEqual(["s01"]);
    expect(d.rescope.map((p) => p.cell)).toEqual(["s02"]);
  });
  it("same plan → nothing", () => expect(streamDiff(all, all)).toEqual({ open: [], close: [], rescope: [] }));
  it("first plan opens all", () => expect(streamDiff([], all).open.length).toBe(3));
});

describe("resyncAction", () => {
  const placed = new Set(["10", "11", "20"]);
  it.each<[string, unknown[], string[], string]>([
    ["merged inbox names both Cells, s02 resynced → splice", ["chats", "list", "10,11,20", "@t"], ["20"], "splice"],
    ["merged inbox fully in resynced Cell → invalidate", ["chats", "list", "10,11", "@t"], ["10", "11"], "invalidate"],
    ["one Creator's thread in resynced Cell", ["chat-messages", "20", "5"], ["20"], "invalidate"],
    ["fan id equal to a Creator id does not select the thread", ["messages", "10", "20"], ["20"], "skip"],
    ["other Cell's thread survives", ["chat-messages", "10", "5"], ["20"], "skip"],
    ["object key part", ["mass-messages", { accountId: "20" }], ["20"], "invalidate"],
    ["agency key on a Cell resync is kept", ["roster-counts"], ["20"], "skip"],
    ["control resync refetches agency keys", ["roster-counts"], [], "invalidate"],
    ["control resync leaves Cell data", ["chat-messages", "10", "5"], [], "skip"],
    ["unknown family falls back to invalidation", ["unknown", "10", { accountId: "20" }], ["20"], "invalidate"],
    ["numeric account in key", ["vault", 20], ["20"], "invalidate"],
  ])("%s", (_n, key, accounts, want) => expect(resyncAction(key, new Set(accounts), placed)).toBe(want));
});

it.each<[
  Parameters<typeof mapLoadReducer>[0], Parameters<typeof mapLoadReducer>[1], ReturnType<typeof mapLoadReducer>,
]>([
  [{ phase: "ready", delay: 5_000 }, "start", { phase: "loading", delay: 5_000 }],
  [{ phase: "loading", delay: 5_000 }, "denied", { phase: "denied" }],
  [{ phase: "loading", delay: 5_000 }, "failed", { phase: "waiting", delay: 5_000 }],
  [{ phase: "waiting", delay: 5_000 }, "retry", { phase: "ready", delay: 10_000 }],
  [{ phase: "waiting", delay: 40_000 }, "retry", { phase: "ready", delay: 60_000 }],
  [{ phase: "denied" }, "start", { phase: "denied" }],
  [{ phase: "denied" }, "reset", { phase: "ready", delay: 5_000 }],
  [{ phase: "waiting", delay: 40_000 }, "reset", { phase: "ready", delay: 5_000 }],
])("map load %j + %s becomes %j", (state, action, expected) => {
  expect(mapLoadReducer(state, action)).toEqual(expected);
});

it("retries a missing tail before invalidating a fully affected inbox", () => {
  expect(resyncAction(["chats", "all", "10"], new Set(["10"]), new Set(["10"]), true)).toBe("retryTail");
});
