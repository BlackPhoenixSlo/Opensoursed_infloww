import { describe, expect, it } from "vitest";

import {
  AUDIENCE_SAVE_IDLE, audienceSaveReducer, buildPayload, everyoneOn, fanRows, fansReducer, fansSummary,
  initFans, sideOf, type Action, type AudienceSave, type AudienceSaveAction, type FansPick, type OfList,
} from "./fansForm";

const stored = (include: number[], exclude: number[] = []) => ({ include, exclude });
const run = (actions: Action[], from: FansPick = initFans(stored([]))) => actions.reduce(fansReducer, from);
const set = (id: number, side: "include" | "exclude" | "none"): Action => ({ type: "set", id, side });

describe("fansReducer", () => {
  it.each<[string, FansPick, Action[], FansPick]>([
    ["stored every Fan opens empty", initFans(stored([])), [], stored([])],
    ["stored lists open as stored", initFans(stored([1, 2], [3])), [], stored([1, 2], [3])],
    ["an id on both opens excluded (exclude wins)", initFans(stored([1, 5], [5])), [], stored([1], [5])],
    ["include a list", initFans(stored([])), [set(4, "include")], stored([4])],
    ["exclude a list", initFans(stored([])), [set(4, "exclude")], stored([], [4])],
    ["include then exclude moves it", initFans(stored([])), [set(4, "include"), set(4, "exclude")], stored([], [4])],
    ["exclude then include moves it", initFans(stored([], [4])), [set(4, "include")], stored([4])],
    ["neither drops it from both", initFans(stored([4], [6])), [set(4, "none"), set(6, "none")], stored([])],
    ["include twice keeps one", initFans(stored([])), [set(4, "include"), set(4, "include")], stored([4])],
    ["others keep their order", initFans(stored([1, 2, 3])), [set(2, "none"), set(9, "include")], stored([1, 3, 9])],
    ["everyone clears includes, keeps excludes", initFans(stored([1, 2], [3])), [{ type: "everyone" }], stored([], [3])],
    ["reset drops edits", initFans(stored([1])), [set(2, "exclude"), { type: "reset", stored: stored([7], [8]) }], stored([7], [8])],
  ])("%s", (_n, from, actions, want) => {
    expect(run(actions, from)).toEqual(want);
  });
});

describe("sideOf / buildPayload / fansSummary", () => {
  it.each<[number, string]>([[1, "include"], [2, "exclude"], [3, "none"]])("sideOf %s", (id, want) => {
    expect(sideOf(stored([1], [2]), id)).toBe(want);
  });
  it.each<[string, FansPick, { include: number[]; exclude: number[] }]>([
    ["empty = every Fan", stored([]), { include: [], exclude: [] }],
    ["include and exclude go whole", stored([1, 2], [3]), { include: [1, 2], exclude: [3] }],
  ])("buildPayload %s", (_n, s, want) => {
    expect(buildPayload(s)).toEqual(want);
  });
  it("does not alias the pick's arrays", () => {
    const s = stored([1], [2]);
    const out = buildPayload(s);
    expect(out.include).not.toBe(s.include);
    expect(out.exclude).not.toBe(s.exclude);
  });
  it.each<[string, { include: number[]; exclude: number[] }, string]>([
    ["nothing", stored([]), "Every Fan"],
    ["include only", stored([1, 2]), "2 included"],
    ["exclude only", stored([], [3]), "Every Fan · 1 excluded"],
    ["both", stored([1], [3, 4]), "1 included · 2 excluded"],
  ])("fansSummary %s", (_n, s, want) => {
    expect(fansSummary(s)).toBe(want);
  });
});

describe("everyoneOn", () => {
  it.each<[string, FansPick, boolean]>([
    ["nothing picked", stored([]), true],
    ["only excludes", stored([], [3]), true],
    ["a list included", stored([1]), false],
    ["last include back to neither", [set(1, "none")].reduce(fansReducer, stored([1])), true],
    ["include a list flips it off", [set(1, "include")].reduce(fansReducer, stored([])), false],
  ])("%s", (_n, s, want) => {
    expect(everyoneOn(s)).toBe(want);
  });
});

describe("fanRows", () => {
  const LISTS: OfList[] = [
    { id: 11, name: "VIP", usersCount: 4 }, { id: "12", name: "", usersCount: 0 }, { id: "fans", name: "Fans" },
    { id: 0, name: "zero" }, { id: 13, name: "No count" },
  ];
  it("whole-number ids only; a nameless list reads 'List #id'; a missing count reads 0", () => {
    expect(fanRows(LISTS, stored([]))).toEqual([
      { id: 11, name: "VIP", count: 4 }, { id: 12, name: "List #12", count: 0 }, { id: 13, name: "No count", count: 0 },
    ]);
  });
  it("a picked id OF no longer lists shows once as not found, so it can be cleared", () => {
    expect(fanRows([{ id: 11, name: "VIP", usersCount: 4 }], stored([11, 99], [77])).map((r) => [r.id, r.name, r.count])).toEqual([
      [11, "VIP", 4], [99, "List #99 · not found", null], [77, "List #77 · not found", null],
    ]);
  });
});

describe("audienceSaveReducer", () => {
  it.each<[string, AudienceSave, AudienceSaveAction[], AudienceSave]>([
    ["save marks it out", AUDIENCE_SAVE_IDLE, [{ type: "save" }], { phase: "saving" }],
    ["ok reads Saved", AUDIENCE_SAVE_IDLE, [{ type: "save" }, { type: "result", result: { kind: "ok" } }], { phase: "saved" }],
    ["the next edit drops Saved", { phase: "saved" }, [{ type: "edit" }], AUDIENCE_SAVE_IDLE],
    ["the next edit drops the words", { phase: "idle", error: "x" }, [{ type: "edit" }], AUDIENCE_SAVE_IDLE],
    ["an edit while a write is out changes nothing", { phase: "saving" }, [{ type: "edit" }], { phase: "saving" }],
    ["a failure keeps its words", AUDIENCE_SAVE_IDLE,
      [{ type: "save" }, { type: "result", result: { kind: "failed", reason: "x" } }], { phase: "idle", error: "x" }],
    ["the next save clears the words", { phase: "idle", error: "x" }, [{ type: "save" }], { phase: "saving" }],
  ])("%s", (_n, from, actions, want) => {
    expect(actions.reduce(audienceSaveReducer, from)).toEqual(want);
  });
});
