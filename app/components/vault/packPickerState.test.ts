import { describe, expect, it } from "vitest";

import type { PackCandidate } from "@/hooks/useVaultCache";

import {
  buildPayload,
  canSubmit,
  focusedId,
  initialPickerState,
  keyAction,
  pickerReducer,
  rungTally,
  shownRung,
  visibleCandidates,
  type PickerAction,
  type PickerState,
} from "./packPickerState";

const RUNGS = ["tease", "nude", "nude-body"];
const item = (media_id: number, over: Partial<PackCandidate> = {}): PackCandidate => ({
  media_id, kind: "photo", rung: null, suggested: null, tier: null, score: 0.5, description: "", ...over,
});
const A = item(1, { suggested: "nude" });
const B = item(2, { suggested: "nude-body", tier: 10 });
const C = item(3);
const FILED = item(4, { rung: "tease", suggested: "nude" });
const ALL = [A, B, C, FILED];
const ORDER = [1, 2, 3];
const run = (actions: PickerAction[], from: PickerState = initialPickerState) => actions.reduce(pickerReducer, from);
const st = (over: Partial<PickerState>): PickerState => ({ ...initialPickerState, ...over });

describe("pickerReducer", () => {
  it.each<[string, PickerAction[], PickerState, PickerState]>([
    ["rule files the tile and hands focus to the next shown", [{ type: "rule", mediaId: 1, rung: "tease", order: ORDER }],
      initialPickerState, st({ draft: { 1: "tease" }, focus: 2 })],
    ["rule on the last tile hands focus back one", [{ type: "rule", mediaId: 3, rung: null, order: ORDER }],
      initialPickerState, st({ draft: { 3: null }, focus: 2 })],
    ["confirm takes the suggestion", [{ type: "confirm", item: B, order: ORDER }],
      initialPickerState, st({ draft: { 2: "nude-body" }, focus: 3 })],
    ["confirm with no suggestion only moves", [{ type: "confirm", item: C, order: [3, 1] }],
      initialPickerState, st({ focus: 1 })],
    ["confirm on a saved tile never re-files it", [{ type: "confirm", item: FILED, order: [4, 1] }],
      initialPickerState, st({ focus: 1 })],
    ["confirm on a ruled tile keeps the verdict", [{ type: "confirm", item: A, order: ORDER }],
      st({ draft: { 1: null } }), st({ draft: { 1: null }, focus: 2 })],
    ["move steps from the first shown when nothing is focused", [{ type: "move", delta: 1, order: ORDER }],
      initialPickerState, st({ focus: 2 })],
    ["move clamps at both ends", [{ type: "move", delta: 9, order: ORDER }, { type: "move", delta: -1, order: ORDER },
      { type: "move", delta: -9, order: ORDER }], initialPickerState, st({ focus: 1 })],
    ["filter resets focus", [{ type: "filter", value: "nude" }], st({ focus: 3 }), st({ filter: "nude", focus: null })],
    ["saved drops what was sent, keeps a verdict changed meanwhile",
      [{ type: "saved", verdicts: [{ media_id: 1, rung: "tease" }, { media_id: 2, rung: "nude" }] }],
      st({ draft: { 1: "tease", 2: "nude-body", 3: null } }), st({ draft: { 2: "nude-body", 3: null } })],
  ])("%s", (_name, actions, from, want) => {
    expect(run(actions, from)).toEqual(want);
  });

  it("focus is the same state when unchanged", () => {
    const s = st({ focus: 2 });
    expect(pickerReducer(s, { type: "focus", mediaId: 2 })).toBe(s);
  });
});

describe("views", () => {
  it.each<[string, PickerState, number[]]>([
    ["undecided: never ruled, suggestions included", st({ draft: { 3: null } }), [1, 2]],
    ["a rung: saved and unsaved on it", st({ filter: "tease", draft: { 1: "tease" } }), [1, 4]],
    ["all", st({ filter: "all" }), [1, 2, 3, 4]],
  ])("visibleCandidates %s", (_n, s, want) => {
    expect(visibleCandidates(ALL, s).map((c) => c.media_id)).toEqual(want);
  });

  it.each<[string, PackCandidate, PickerState["draft"], { rung: string | null; suggested: boolean }]>([
    ["untouched: the suggestion", A, {}, { rung: "nude", suggested: true }],
    ["no suggestion", C, {}, { rung: null, suggested: false }],
    ["ruled beats the suggestion", A, { 1: "tease" }, { rung: "tease", suggested: false }],
    ["rejected shows nothing", A, { 1: null }, { rung: null, suggested: false }],
    ["saved beats the suggestion", FILED, {}, { rung: "tease", suggested: false }],
  ])("shownRung %s", (_n, c, draft, want) => {
    expect(shownRung(c, draft)).toEqual(want);
  });

  it("tally counts verdicts and saved rungs, never suggestions", () => {
    expect(rungTally(ALL, { 1: "nude", 4: "nude-body" })).toEqual({ nude: 1, "nude-body": 1 });
  });

  it("focusedId falls back to the first shown", () => {
    expect(focusedId(st({ focus: 9 }), ORDER)).toBe(1);
    expect(focusedId(st({ focus: 3 }), ORDER)).toBe(3);
    expect(focusedId(st({}), [])).toBeNull();
  });
});

describe("submit", () => {
  it.each<[string, PickerState, boolean, boolean]>([
    ["nothing ruled", initialPickerState, false, false],
    ["a verdict", st({ draft: { 1: null } }), false, true],
    ["busy", st({ draft: { 1: "tease" } }), true, false],
  ])("canSubmit %s", (_n, s, busy, want) => {
    expect(canSubmit(s, busy)).toBe(want);
  });

  it("buildPayload sends only verdicts, by media id; suggestions never", () => {
    expect(buildPayload(st({ draft: { 3: null, 1: "nude-body" } }))).toEqual([
      { media_id: 1, rung: "nude-body" }, { media_id: 3, rung: null },
    ]);
  });
});

describe("keyAction", () => {
  const ctx = { focused: A, rungs: RUNGS, order: ORDER, cols: 4 };
  it.each<[string, PickerAction | null]>([
    ["1", { type: "rule", mediaId: 1, rung: "tease", order: ORDER }],
    ["3", { type: "rule", mediaId: 1, rung: "nude-body", order: ORDER }],
    ["4", null],
    ["x", { type: "rule", mediaId: 1, rung: null, order: ORDER }],
    ["X", { type: "rule", mediaId: 1, rung: null, order: ORDER }],
    ["Enter", { type: "confirm", item: A, order: ORDER }],
    ["j", { type: "move", delta: 1, order: ORDER }],
    ["k", { type: "move", delta: -1, order: ORDER }],
    ["ArrowRight", { type: "move", delta: 1, order: ORDER }],
    ["ArrowDown", { type: "move", delta: 4, order: ORDER }],
    ["ArrowUp", { type: "move", delta: -4, order: ORDER }],
    ["a", null],
  ])("%s", (key, want) => {
    expect(keyAction(key, ctx)).toEqual(want);
  });

  it("with nothing focused only the moves act", () => {
    expect(keyAction("1", { ...ctx, focused: null })).toBeNull();
    expect(keyAction("Enter", { ...ctx, focused: null })).toBeNull();
    expect(keyAction("j", { ...ctx, focused: null })).toEqual({ type: "move", delta: 1, order: ORDER });
  });
});
