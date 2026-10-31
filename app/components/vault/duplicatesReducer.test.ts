import { describe, expect, it } from "vitest";

import type { HideDupesResult } from "@/hooks/useVaultCache";

import {
  allOff,
  doneText,
  duplicatesReducer,
  hidePayload,
  initialDupesState,
  selectedIdsOf,
  type DupesAction,
  type DupesPhase,
  type DupesState,
} from "./duplicatesReducer";

const RESULT: HideDupesResult = { hidden: 2, hidden_ids: [11, 12], refused: {} };

const PHASES: Record<DupesPhase["kind"], DupesPhase> = {
  idle: { kind: "idle" },
  confirming: { kind: "confirming", frozenIds: [11, 12], threshold: 2 },
  hiding: { kind: "hiding", frozenIds: [11, 12], done: 0 },
  done: { kind: "done", result: RESULT, total: 2 },
  error: { kind: "error", msg: "boom" },
};

function at(kind: DupesPhase["kind"], deselected: number[] = [13]): DupesState {
  return { threshold: 2, deselected: new Set(deselected), phase: PHASES[kind] };
}

const run = (s: DupesState, ...actions: DupesAction[]) => actions.reduce(duplicatesReducer, s);
const numeric = (ids: Iterable<number>) => [...ids].sort((a, b) => a - b);

describe("initialDupesState", () => {
  it("is idle at threshold 2 with nothing unticked", () => {
    expect(initialDupesState()).toEqual({ threshold: 2, deselected: new Set(), phase: { kind: "idle" } });
  });
});

describe("selectedIdsOf", () => {
  const clusters = [
    { dupes: [{ media_id: 11 }, { media_id: 12 }] },
    { dupes: [{ media_id: 13 }] },
  ];
  it.each([
    [[], [11, 12, 13]],
    [[12], [11, 13]],
    [[11, 12, 13], []],
  ])("deselected %j → %j", (off, want) => {
    expect(selectedIdsOf(clusters, new Set(off))).toEqual(want);
  });
});

describe("allOff", () => {
  it.each([
    [[], false],
    [[11], false],
    [[11, 12], true],
    [[11, 12, 99], true],
  ])("deselected %j → %s", (off, want) => {
    expect(allOff([11, 12], new Set(off))).toBe(want);
  });
});

describe("threshold", () => {
  it.each([
    ["idle", "idle"],
    ["confirming", "idle"], // the bug: confirm used to stay on for an unreviewed scan
    ["done", "idle"],
    ["error", "idle"],
  ] as const)("in %s → %s, unticked set reset, new threshold", (from, to) => {
    const s = duplicatesReducer(at(from), { type: "threshold", v: 4 });
    expect(s.phase.kind).toBe(to);
    expect(s.threshold).toBe(4);
    expect(s.deselected.size).toBe(0);
    expect(hidePayload(s)).toBeNull();
  });
});

describe("toggle / toggleSet", () => {
  it.each([
    ["idle", "idle"],
    ["confirming", "idle"], // ticking a box cancels the confirm, never edits the frozen set
    ["done", "done"],
    ["error", "error"],
  ] as const)("toggle in %s → %s", (from, to) => {
    const s = duplicatesReducer(at(from), { type: "toggle", id: 11 });
    expect(s.phase.kind).toBe(to);
    expect(numeric(s.deselected)).toEqual([11, 13]);
  });
  it("toggle twice restores the tick", () => {
    const s = run(at("idle", []), { type: "toggle", id: 11 }, { type: "toggle", id: 11 });
    expect(s.deselected.size).toBe(0);
  });
  it.each([
    ["some on → all off", [13], [11, 12, 13]],
    ["all on → all off", [], [11, 12, 13]],
    ["all off → all on", [11, 12, 13], []],
    ["other sets untouched", [99], [11, 12, 13, 99]],
  ])("toggleSet %s", (_, off, want) => {
    const s = duplicatesReducer(at("idle", off), { type: "toggleSet", ids: [11, 12, 13] });
    expect(numeric(s.deselected)).toEqual(want);
  });
  it("toggleSet while confirming returns to idle", () => {
    expect(duplicatesReducer(at("confirming"), { type: "toggleSet", ids: [11] }).phase.kind).toBe(
      "idle",
    );
  });
});

describe("confirm / cancel", () => {
  it.each(["idle", "done", "error"] as const)("confirm from %s freezes the ids and threshold", (from) => {
    const ids = [11, 12];
    const s = duplicatesReducer(at(from), { type: "confirm", ids });
    expect(s.phase).toEqual({ kind: "confirming", frozenIds: [11, 12], threshold: 2 });
    ids.push(99); // a later change to the caller's array cannot leak in
    expect(hidePayload(s)).toEqual({ ids: [11, 12], threshold: 2 });
  });
  it("confirm in confirming is ignored", () => {
    const s = at("confirming");
    expect(duplicatesReducer(s, { type: "confirm", ids: [99] })).toBe(s);
  });
  it("confirm with nothing selected is ignored", () => {
    const s = at("idle");
    expect(duplicatesReducer(s, { type: "confirm", ids: [] })).toBe(s);
  });
  it("cancel: confirming → idle, keeps the unticked set", () => {
    const s = duplicatesReducer(at("confirming"), { type: "cancel" });
    expect(s.phase.kind).toBe("idle");
    expect([...s.deselected]).toEqual([13]);
  });
  it.each(["idle", "done", "error"] as const)("cancel in %s is ignored", (from) => {
    const s = at(from);
    expect(duplicatesReducer(s, { type: "cancel" })).toBe(s);
  });
});

describe("hidePayload", () => {
  it.each(["idle", "hiding", "done", "error"] as const)("is null in %s", (kind) => {
    expect(hidePayload(at(kind))).toBeNull();
  });
  it("sends the threshold frozen at confirm, not the live one", () => {
    const s: DupesState = { ...at("confirming"), threshold: 4 };
    expect(hidePayload(s)).toEqual({ ids: [11, 12], threshold: 2 });
  });
});

describe("hide lifecycle", () => {
  it("hideStart → progress → hideOk sends and reports the frozen set", () => {
    let s = run(at("idle", []), { type: "confirm", ids: [11, 12] });
    expect(hidePayload(s)).toEqual({ ids: [11, 12], threshold: 2 });
    s = duplicatesReducer(s, { type: "hideStart" });
    expect(s.phase).toEqual({ kind: "hiding", frozenIds: [11, 12], done: 0 });
    expect(hidePayload(s)).toBeNull(); // no second request while one is out
    s = duplicatesReducer(s, { type: "progress", done: 1 });
    expect(s.phase).toEqual({ kind: "hiding", frozenIds: [11, 12], done: 1 });
    s = duplicatesReducer(s, { type: "hideOk", result: RESULT });
    expect(s.phase).toEqual({ kind: "done", result: RESULT, total: 2 });
  });
  it("hideFail (a first batch failed: nothing went) → error{msg}", () => {
    const s = duplicatesReducer(at("hiding"), { type: "hideFail", msg: "nope" });
    expect(s.phase).toEqual({ kind: "error", msg: "nope" });
  });
  it.each<[string, HideDupesResult, number, string]>([
    ["all removed", RESULT, 2, "Removed 2 copies from the OnlyFans vault."],
    ["one removed", { hidden: 1, hidden_ids: [11], refused: {} }, 1, "Removed 1 copy from the OnlyFans vault."],
    ["a later batch failed: what went, of what was sent, then the error",
      { hidden: 250, hidden_ids: [], refused: {}, of_error: "nope", not_hidden: [12] }, 251,
      "Removed 250 of 251, then failed: nope"],
  ])("doneText, %s", (_, result, total, want) => {
    expect(doneText(result, total)).toBe(want);
  });
  it.each([
    { type: "threshold", v: 4 },
    { type: "toggle", id: 11 },
    { type: "toggleSet", ids: [11, 12] },
    { type: "confirm", ids: [99] },
    { type: "cancel" },
    { type: "hideStart" },
  ] as DupesAction[])("$type is ignored while hiding", (a) => {
    const s = at("hiding");
    expect(duplicatesReducer(s, a)).toBe(s);
  });
  it.each(["idle", "done", "error"] as const)("hideStart in %s is ignored", (from) => {
    const s = at(from);
    expect(duplicatesReducer(s, { type: "hideStart" })).toBe(s);
  });
  it.each(["idle", "confirming", "done", "error"] as const)(
    "progress / hideOk / hideFail in %s are ignored",
    (from) => {
      const s = at(from);
      expect(duplicatesReducer(s, { type: "progress", done: 1 })).toBe(s);
      expect(duplicatesReducer(s, { type: "hideOk", result: RESULT })).toBe(s);
      expect(duplicatesReducer(s, { type: "hideFail", msg: "x" })).toBe(s);
    },
  );
});
