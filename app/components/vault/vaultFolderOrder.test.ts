import { describe, expect, it } from "vitest";

import { type FanId } from "@/lib/fanId";

import {
  applyCustomOrder,
  customizeReducer,
  moveFolder,
  type CustomizeAction,
  type CustomizeState,
} from "./vaultFolderOrder";

const ORDER: FanId[] = [1, 2, 3, 4];

describe("moveFolder", () => {
  it.each([
    ["first down to last", 1, 4, [2, 3, 4, 1]],
    ["down one", 2, 3, [1, 3, 2, 4]],
    ["last up to first", 4, 1, [4, 1, 2, 3]],
    ["up one", 3, 2, [1, 3, 2, 4]],
    ["middle up", 3, 1, [3, 1, 2, 4]],
  ] as const)("%s: %s over %s → %j", (_, from, to, want) => {
    expect(moveFolder(ORDER, from, to)).toEqual(want);
    expect(ORDER).toEqual([1, 2, 3, 4]); // never mutates
  });
  it.each([
    ["from === to", 2, 2],
    ["from not in order", 9, 2],
    ["to not in order", 2, 9],
    ["neither in order", 8, 9],
  ] as const)("%s → same array", (_, from, to) => {
    expect(moveFolder(ORDER, from, to)).toBe(ORDER);
  });
  it("keeps string (snowflake) ids", () => {
    expect(moveFolder(["a", "b", "c"], "c", "a")).toEqual(["c", "a", "b"]);
  });
  it("empty order → same array", () => {
    const empty: FanId[] = [];
    expect(moveFolder(empty, 1, 2)).toBe(empty);
  });
});

const run = (s: CustomizeState, ...actions: CustomizeAction[]) => actions.reduce(customizeReducer, s);
const OFF: CustomizeState = null;
const ON: CustomizeState = { order: ORDER, dragged: null };

describe("customizeReducer", () => {
  it("start copies the ids; mode is on", () => {
    const s = customizeReducer(OFF, { type: "start", ids: ORDER });
    expect(s).toEqual({ order: [1, 2, 3, 4], dragged: null });
    expect(s?.order).not.toBe(ORDER);
  });
  it("drag, over, over, drop moves the row and clears the drag", () => {
    const s = run(ON, { type: "drag", id: 1 }, { type: "over", id: 2 }, { type: "over", id: 4 }, { type: "drop" });
    expect(s).toEqual({ order: [2, 3, 4, 1], dragged: null });
  });
  it("cancel turns the mode off from anywhere", () => {
    expect(run(ON, { type: "drag", id: 1 }, { type: "over", id: 3 }, { type: "cancel" })).toEqual(OFF);
  });
  it.each<[string, CustomizeState, CustomizeAction]>([
    ["drag while off", OFF, { type: "drag", id: 1 }],
    ["over while off", OFF, { type: "over", id: 1 }],
    ["over with nothing dragged", ON, { type: "over", id: 2 }],
    ["over itself", { order: ORDER, dragged: 2 }, { type: "over", id: 2 }],
    ["over an unknown id", { order: ORDER, dragged: 2 }, { type: "over", id: 9 }],
    ["drop with nothing dragged", ON, { type: "drop" }],
    ["cancel while off", OFF, { type: "cancel" }],
  ])("%s → same state", (_, s, a) => {
    expect(customizeReducer(s, a)).toBe(s);
  });
});

describe("applyCustomOrder", () => {
  const L = (...ids: FanId[]) => ids.map((id) => ({ id }));
  it.each([
    ["every folder ordered", L(1, 2, 3), [3, 1, 2], [3, 1, 2]],
    ["others keep their slots", L(9, 1, 8, 2, 3), [3, 2, 1], [9, 3, 8, 2, 1]],
    ["an id not in the list is skipped", L(1, 2), [7, 2, 1], [2, 1]],
    ["string and number ids match", L("1", "2"), [2, 1], ["2", "1"]],
    ["empty order: as is", L(1, 2), [], [1, 2]],
  ] as const)("%s", (_, list, order, want) => {
    expect(applyCustomOrder(list, order).map((l) => l.id)).toEqual(want);
  });
});
