import { describe, expect, it } from "vitest";

import type { RowMeta } from "@/components/vault/VaultImportDetails";

import {
  chosenOf,
  importPickReducer,
  initialPickState,
  type PickAction,
  type PickState,
} from "./importPickReducer";

const A = new File(["a"], "a.jpg");
const B = new File(["b"], "b.jpg");
const C = new File(["c"], "c.mp4");
const NAME = new Map([[A, "a"], [B, "b"], [C, "c"]]);

const run = (s: PickState, ...actions: PickAction[]) => actions.reduce(importPickReducer, s);
const names = (fs: Iterable<File>) => [...fs].map((f) => NAME.get(f)).sort();

/** A, B, C picked; A and B selected; A and C with details. */
function three(): PickState {
  return run(
    initialPickState,
    { type: "pick", files: [A, B, C] },
    { type: "toggle", file: C },
    { type: "edit", files: [A], values: { notes: "n" } },
    { type: "edit", files: [C], values: { price: "5" } },
  );
}

/** The card's invariants: selection and details only ever name picked files. */
function expectConsistent(s: PickState) {
  for (const f of s.selected) expect(s.picked).toContain(f);
  for (const f of s.details.keys()) expect(s.picked).toContain(f);
}

describe("pick", () => {
  it("fills the list, every file selected, no details yet", () => {
    const s = importPickReducer(initialPickState, { type: "pick", files: [A, B] });
    expect(s.picked).toEqual([A, B]);
    expect(names(s.selected)).toEqual(["a", "b"]);
    expect(s.details.size).toBe(0);
  });
  it.each([
    ["a re-pick leaves no details", [B], ["b"]],
    ["an empty pick empties all three", [], []],
  ])("%s", (_, files, sel) => {
    const s = importPickReducer(three(), { type: "pick", files });
    expect(s.picked).toEqual(files);
    expect(s.details.size).toBe(0);
    expect(names(s.selected)).toEqual(sel);
    expectConsistent(s);
  });
  it("copies the caller's array", () => {
    const files = [A];
    const s = importPickReducer(initialPickState, { type: "pick", files });
    files.push(B);
    expect(s.picked).toEqual([A]);
  });
});

describe("remove", () => {
  it.each([
    ["a selected file with details", [A], ["b", "c"], ["b"], ["c"]],
    ["an unselected file with details", [C], ["a", "b"], ["a", "b"], ["a"]],
    ["the bar's delete (the selection)", [A, B], ["c"], [], ["c"]],
    ["every file", [A, B, C], [], [], []],
  ])("%s goes from the list, the selection and the details", (_, files, left, sel, det) => {
    const s = importPickReducer(three(), { type: "remove", files });
    expect(names(s.picked)).toEqual(left);
    expect(names(s.selected)).toEqual(sel);
    expect(names(s.details.keys())).toEqual(det);
    expectConsistent(s);
  });
  it("keeps the list order", () => {
    expect(importPickReducer(three(), { type: "remove", files: [B] }).picked).toEqual([A, C]);
  });
  it("removing nothing is a no-op", () => {
    const s = three();
    expect(importPickReducer(s, { type: "remove", files: [] })).toBe(s);
  });
  it("a file not on the list changes nothing", () => {
    const s = importPickReducer(three(), { type: "remove", files: [new File([""], "x")] });
    expect(s.picked).toEqual([A, B, C]);
    expect(names(s.selected)).toEqual(["a", "b"]);
    expect(names(s.details.keys())).toEqual(["a", "c"]);
  });
});

describe("edit", () => {
  const EDITS: [string, File[], RowMeta, [File, RowMeta][]][] = [
    ["a cell merges into the row's details", [A], { tag: "t" }, [[A, { notes: "n", tag: "t" }]]],
    ["a cell overwrites its own field", [A], { notes: "m" }, [[A, { notes: "m" }]]],
    ["Batch edit writes every given row", [A, B], { category: "7" }, [[A, { notes: "n", category: "7" }], [B, { category: "7" }]]],
  ];
  it.each(EDITS)("%s", (_, files, values, want) => {
    const s = importPickReducer(three(), { type: "edit", files, values });
    for (const [f, v] of want) expect(s.details.get(f)).toEqual(v);
    expect(s.details.get(C)).toEqual({ price: "5" }); // untouched
    expect(s.picked).toEqual([A, B, C]);
    expect(names(s.selected)).toEqual(["a", "b"]);
  });
  it("details for a file that is not picked are dropped", () => {
    const gone = run(three(), { type: "remove", files: [B] });
    const s = importPickReducer(gone, { type: "edit", files: [A, B], values: { notes: "x" } });
    expect(s.details.has(B)).toBe(false);
    expect(s.details.get(A)).toEqual({ notes: "x" });
    expectConsistent(s);
  });
  it("only unpicked files is a no-op", () => {
    const s = run(three(), { type: "remove", files: [B] });
    expect(importPickReducer(s, { type: "edit", files: [B], values: { notes: "x" } })).toBe(s);
  });
  it("does not mutate the previous state", () => {
    const s = three();
    importPickReducer(s, { type: "edit", files: [A], values: { notes: "z" } });
    expect(s.details.get(A)).toEqual({ notes: "n" });
  });
});

describe("toggle / selectAll", () => {
  it.each([
    ["a selected file → off", A, ["b"]],
    ["an unselected file → on", C, ["a", "b", "c"]],
  ])("toggle %s", (_, file, sel) => {
    const s = importPickReducer(three(), { type: "toggle", file });
    expect(names(s.selected)).toEqual(sel);
    expect(s.picked).toEqual([A, B, C]);
    expect(names(s.details.keys())).toEqual(["a", "c"]);
  });
  it("toggle twice restores the tick", () => {
    expect(names(run(three(), { type: "toggle", file: A }, { type: "toggle", file: A }).selected)).toEqual([
      "a",
      "b",
    ]);
  });
  it("a file that is not picked is never selected", () => {
    const s = run(three(), { type: "remove", files: [A] });
    expect(importPickReducer(s, { type: "toggle", file: A })).toBe(s);
  });
  it.each([
    [true, ["a", "b", "c"]],
    [false, []],
  ])("selectAll on=%s", (on, sel) => {
    const s = importPickReducer(three(), { type: "selectAll", on });
    expect(names(s.selected)).toEqual(sel);
    expect(names(s.details.keys())).toEqual(["a", "c"]);
  });
  it("selectAll on an empty list selects nothing", () => {
    expect(importPickReducer(initialPickState, { type: "selectAll", on: true }).selected.size).toBe(0);
  });
});

describe("chosenOf", () => {
  const CHOSEN: [string, PickAction[], File[]][] = [
    ["the selected files, in list order", [{ type: "toggle", file: A }, { type: "toggle", file: A }], [A, B]],
    ["none selected", [{ type: "selectAll", on: false }], []],
    ["all selected", [{ type: "selectAll", on: true }], [A, B, C]],
  ];
  it.each(CHOSEN)("%s", (_, actions, want) => {
    expect(chosenOf(run(three(), ...actions))).toEqual(want);
  });
});
