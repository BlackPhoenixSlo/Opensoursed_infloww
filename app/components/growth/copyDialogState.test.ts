import { describe, expect, it } from "vitest";

import {
  buildPayload, canSubmit, copyDialogInit, copyDialogReducer, isFull, MAX_SOURCES,
  type CopyDialogAction, type CopyDialogState,
} from "@/components/growth/copyDialogState";

const S = (over: Partial<CopyDialogState> = {}): CopyDialogState => ({ ...copyDialogInit("share"), ...over });
const I = (over: Partial<CopyDialogState> = {}): CopyDialogState => ({ ...copyDialogInit("import"), ...over });
const FIVE = ["a", "b", "c", "d", "e"];

describe("copyDialogReducer", () => {
  const cases: Array<[string, CopyDialogState, CopyDialogAction, CopyDialogState]> = [
    ["toggleAll on sets the flag, leaves picks", S({ picked: ["a"] }), { type: "toggleAll", on: true },
      S({ allCreators: true, picked: ["a"] })],
    ["toggleAll off clears the flag", S({ allCreators: true, picked: ["a"] }), { type: "toggleAll", on: false },
      S({ allCreators: false, picked: ["a"] })],
    ["toggle on adds an id", S(), { type: "toggle", id: "a", on: true }, S({ picked: ["a"] })],
    ["toggle on is idempotent", S({ picked: ["a"] }), { type: "toggle", id: "a", on: true }, S({ picked: ["a"] })],
    ["toggle off removes an id", S({ picked: ["a", "b"] }), { type: "toggle", id: "a", on: false },
      S({ picked: ["b"] })],
    ["import refuses a pick past the cap", I({ picked: FIVE }), { type: "toggle", id: "f", on: true },
      I({ picked: FIVE })],
    ["import at the cap still drops a pick", I({ picked: FIVE }), { type: "toggle", id: "a", on: false },
      I({ picked: ["b", "c", "d", "e"] })],
    ["share has no cap", S({ picked: FIVE }), { type: "toggle", id: "f", on: true },
      S({ picked: [...FIVE, "f"] })],
  ];
  it.each(cases)("%s", (_label, state, action, want) => {
    expect(copyDialogReducer(state, action)).toEqual(want);
  });

  it("appends in pick order", () => {
    let s = copyDialogInit("share");
    for (const id of ["c", "a", "b"]) s = copyDialogReducer(s, { type: "toggle", id, on: true });
    expect(s.picked).toEqual(["c", "a", "b"]);
  });
});

describe("isFull and canSubmit", () => {
  const cases: Array<[string, CopyDialogState, boolean, boolean]> = [
    ["import needs ≥1 source", I(), false, false],
    ["import with one source", I({ picked: ["a"] }), true, false],
    ["import at the cap", I({ picked: FIVE }), MAX_SOURCES === 5, true],
    ["import over the cap", I({ picked: [...FIVE, "f"] }), false, true],
    ["import ignores allCreators", I({ allCreators: true, picked: [] }), false, false],
    ["share needs a pick or the toggle", S(), false, false],
    ["share with a target", S({ picked: ["a"] }), true, false],
    ["share to all creators", S({ allCreators: true, picked: [] }), true, false],
    ["share is never full", S({ picked: FIVE }), true, false],
  ];
  it.each(cases)("%s", (_label, state, submit, full) => {
    expect([canSubmit(state), isFull(state)]).toEqual([submit, full]);
  });
});

describe("buildPayload", () => {
  it("import: picked sources into this Creator", () => {
    expect(buildPayload(I({ picked: ["x", "y"] }), { accountId: "me", ids: [1, 2] })).toEqual({
      fromAccountIds: ["x", "y"], toAccountIds: ["me"], allCreators: false, ids: [1, 2],
    });
  });

  it("share to specific creators", () => {
    expect(buildPayload(S({ picked: ["x", "y"] }), { accountId: "me" })).toEqual({
      fromAccountIds: ["me"], toAccountIds: ["x", "y"], allCreators: false, ids: undefined,
    });
  });

  it("share to all: no targets + the flag, picks ignored", () => {
    expect(buildPayload(S({ allCreators: true, picked: ["x"] }), { accountId: "me", ids: [7] })).toEqual({
      fromAccountIds: ["me"], toAccountIds: [], allCreators: true, ids: [7],
    });
  });
});
