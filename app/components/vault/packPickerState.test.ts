import { describe, expect, it } from "vitest";

import type { PackCandidate } from "@/hooks/useVaultCache";

import {
  buildFilePayload,
  buildPayload,
  canFile,
  canFileTicked,
  canPress,
  canSubmit,
  focusedId,
  initialPickerState,
  isTicked,
  keyAction,
  pickerReducer,
  possibleOnly,
  rungTally,
  shownRung,
  tickedVerdicts,
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
    ["tick records an untick override", [{ type: "tick", mediaId: 5, on: false }],
      initialPickerState, st({ ticks: { 5: false } })],
    ["retick overrides the untick", [{ type: "tick", mediaId: 5, on: false }, { type: "tick", mediaId: 5, on: true }],
      initialPickerState, st({ ticks: { 5: true } })],
    ["a saved reject is never re-ticked by its preselect",
      [{ type: "saved", verdicts: [{ media_id: 5, rung: null }, { media_id: 6, rung: "tease" }] }],
      st({ draft: { 5: null } }), st({ ticks: { 5: false } })],
    ["saved drops what was sent, keeps a verdict changed meanwhile",
      [{ type: "saved", verdicts: [{ media_id: 1, rung: "tease" }, { media_id: 2, rung: "nude" }] }],
      st({ draft: { 1: "tease", 2: "nude-body", 3: null } }), st({ draft: { 2: "nude-body", 3: null } })],
  ])("%s", (_name, actions, from, want) => {
    expect(run(actions, from)).toEqual(want);
  });

  it("tick is the same state when unchanged", () => {
    const s = st({ ticks: { 5: false } });
    expect(pickerReducer(s, { type: "tick", mediaId: 5, on: false })).toBe(s);
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

  it("never files a Jev body that is not free-safe on the free rung; other rungs and unknown stay open", () => {
    const unsafe = item(9, { jev: true, free_ok: false });
    const at = { ...ctx, focused: unsafe };
    expect(keyAction("1", at)).toBeNull();
    expect(keyAction("2", at)).toEqual({ type: "rule", mediaId: 9, rung: "nude", order: ORDER });
    expect(keyAction("x", at)).toEqual({ type: "rule", mediaId: 9, rung: null, order: ORDER });
    expect(keyAction("1", { ...ctx, focused: item(10, { free_ok: null }) })).not.toBeNull();
  });

  it("with nothing focused only the moves act", () => {
    expect(keyAction("1", { ...ctx, focused: null })).toBeNull();
    expect(keyAction("Enter", { ...ctx, focused: null })).toBeNull();
    expect(keyAction("j", { ...ctx, focused: null })).toEqual({ type: "move", delta: 1, order: ORDER });
  });
});

describe("canFile", () => {
  it.each<[string, Partial<PackCandidate>, string, boolean]>([
    ["jev unsafe, free rung", { jev: true, free_ok: false }, "tease", false],
    ["jev unsafe, paid rung", { jev: true, free_ok: false }, "nude-body", true],
    ["jev unsafe, middle rung", { jev: true, free_ok: false }, "nude", true],
    ["jev safe, free rung", { jev: true, free_ok: true }, "tease", true],
    ["no jev answer, free rung", { free_ok: null }, "tease", true],
    ["field absent (older relay), free rung", {}, "tease", true],
    ["video, paid rung: photos only", { kind: "video", jev: false }, "nude-body", false],
    ["video, free rung: photos only", { kind: "video", free_ok: true }, "tease", false],
    ["gif, middle rung: photos only", { kind: "gif" }, "nude", false],
  ])("%s", (_name, over, rung, want) => {
    expect(canFile(item(1, over), rung, RUNGS)).toBe(want);
  });
});

describe("preselect", () => {
  // P1/P2 Jev preselected (P2 a safe tease), Q a suggestion below the gate (not preselected), N no suggestion,
  // U preselected but its suggestion is the free rung and Jev says not free-safe (server never does this), S saved,
  // V a preselected video (server never does this either), M a possible one (below the gate, flagged preselect by
  // mistake: still never ticked by itself).
  const P1 = item(11, { suggested: "nude", preselect: true, jev: true, free_ok: true });
  const P2 = item(12, { suggested: "tease", preselect: true, jev: true, free_ok: true });
  const Q = item(13, { suggested: "nude", preselect: false });
  const N = item(14, { preselect: false, jev: true });
  const U = item(15, { suggested: "tease", preselect: true, jev: true, free_ok: false });
  const S = item(16, { rung: "nude", suggested: "nude", preselect: true });
  const V = item(17, { kind: "video", suggested: "nude", preselect: true });
  const M = item(18, { suggested: "nude", preselect: true, possible: true, jev: true, free_ok: true });
  const LIST = [P1, P2, Q, N, U, S, V, M];
  const ticked = (s: PickerState) => LIST.filter((c) => isTicked(c, s, RUNGS)).map((c) => c.media_id);

  it.each<[string, PickerState, number[]]>([
    ["arrive ticked: preselected, undecided, filable", initialPickerState, [11, 12]],
    ["untick", st({ ticks: { 11: false } }), [12]],
    ["retick a suggestion below the gate", st({ ticks: { 13: true } }), [11, 12, 13]],
    ["no suggestion can never be ticked", st({ ticks: { 14: true } }), [11, 12]],
    ["never the free rung for an unsafe body", st({ ticks: { 15: true } }), [11, 12]],
    ["a saved tile is not ticked", st({ ticks: { 16: true } }), [11, 12]],
    ["a video is never ticked (photos only)", st({ ticks: { 17: true } }), [11, 12]],
    ["a pressed rung (draft) replaces the tick", st({ draft: { 11: "nude-body" } }), [12]],
    ["a draft reject replaces the tick", st({ draft: { 12: null } }), [11]],
    ["a possible one only by the operator's tick", st({ ticks: { 18: true } }), [11, 12, 18]],
  ])("isTicked %s", (_n, s, want) => {
    expect(ticked(s)).toEqual(want);
  });

  it("tickedVerdicts files each ticked tile on its suggestion", () => {
    expect(tickedVerdicts(LIST, initialPickerState, RUNGS)).toEqual([
      { media_id: 11, rung: "nude" }, { media_id: 12, rung: "tease" },
    ]);
  });

  it.each<[string, PickerState, { media_id: number; rung: string | null }[]]>([
    ["ticked only", initialPickerState, [{ media_id: 11, rung: "nude" }, { media_id: 12, rung: "tease" }]],
    ["changed rung rides as the draft verdict", st({ draft: { 12: "nude" } }),
      [{ media_id: 11, rung: "nude" }, { media_id: 12, rung: "nude" }]],
    ["untick + draft elsewhere", st({ ticks: { 11: false }, draft: { 14: "nude-body", 13: null } }),
      [{ media_id: 12, rung: "tease" }, { media_id: 13, rung: null }, { media_id: 14, rung: "nude-body" }]],
  ])("buildFilePayload %s", (_n, s, want) => {
    expect(buildFilePayload(LIST, s, RUNGS)).toEqual(want);
  });

  it.each<[string, PickerState, boolean, boolean]>([
    ["ticked", initialPickerState, false, true],
    ["busy", initialPickerState, true, false],
    ["all unticked", st({ ticks: { 11: false, 12: false } }), false, false],
  ])("canFileTicked %s", (_n, s, busy, want) => {
    expect(canFileTicked(LIST, s, RUNGS, busy)).toBe(want);
  });

  it("Save still sends only the draft, never a tick", () => {
    expect(buildPayload(initialPickerState)).toEqual([]);
  });
});

describe("possibleOnly", () => {
  const C = item(1, { preselect: true });
  const M = item(2, { possible: true });
  const FILED = item(3, { rung: "nude" });
  it.each<[string, PackCandidate[], boolean]>([
    ["empty", [], false],
    ["a confident one left", [C, M], false],
    ["possible ones only", [M, item(4, { possible: true })], true],
    ["possible ones plus filed ones", [M, FILED], true],
    ["filed only (nothing queued)", [FILED], false],
    ["a filed possible one does not count", [C, item(5, { rung: "tease", possible: true })], false],
  ])("%s", (_n, all, want) => {
    expect(possibleOnly(all)).toBe(want);
  });
});

describe("canPress", () => {
  const UNSAFE = { jev: true, free_ok: false };
  it.each<[string, Partial<PackCandidate>, PickerState["draft"], string, boolean]>([
    // Already filed on the free rung before the guard: the press unfiles it, so it stays pressable.
    ["unsafe, saved on tease: tease unfiles", { ...UNSAFE, rung: "tease", unsafe_on_free: true }, {}, "tease", true],
    ["unsafe, saved on tease, drafted off: tease refused", { ...UNSAFE, rung: "tease" }, { 1: null }, "tease", false],
    ["unsafe, drafted on tease: tease unfiles", UNSAFE, { 1: "tease" }, "tease", true],
    ["unsafe, merely suggested tease: refused", { ...UNSAFE, suggested: "tease" }, {}, "tease", false],
    ["unsafe, on nude: tease refused", { ...UNSAFE, rung: "nude" }, {}, "tease", false],
    ["unsafe, saved on tease: nude allowed", { ...UNSAFE, rung: "tease" }, {}, "nude", true],
    ["safe, unfiled: tease allowed", { jev: true, free_ok: true }, {}, "tease", true],
    // A clip filed before photos-only: its rung unfiles it, no other rung files it.
    ["video, saved on nude: nude unfiles", { kind: "video", rung: "nude" }, {}, "nude", true],
    ["video, saved on nude: body refused", { kind: "video", rung: "nude" }, {}, "nude-body", false],
    ["video, drafted off: nude refused", { kind: "video", rung: "nude" }, { 1: null }, "nude", false],
  ])("%s", (_name, over, draft, rung, want) => {
    expect(canPress(item(1, over), rung, RUNGS, draft)).toBe(want);
  });
});
