import { describe, expect, it } from "vitest";

import {
  buildPayload, canSubmit, copyDialogReducer, COPY_DIALOG_INITIAL, MAX_SOURCES,
  type CopyDialogAction, type CopyDialogState,
} from "@/components/growth/copyDialogState";

const S = (over: Partial<CopyDialogState> = {}): CopyDialogState => ({ ...COPY_DIALOG_INITIAL, ...over });

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
    ["reset clears everything", S({ allCreators: true, picked: ["a", "b"] }), { type: "reset" }, COPY_DIALOG_INITIAL],
  ];
  it.each(cases)("%s", (_label, state, action, want) => {
    expect(copyDialogReducer(state, action)).toEqual(want);
  });

  it("appends in pick order", () => {
    let s = COPY_DIALOG_INITIAL;
    for (const id of ["c", "a", "b"]) s = copyDialogReducer(s, { type: "toggle", id, on: true });
    expect(s.picked).toEqual(["c", "a", "b"]);
  });
});

describe("canSubmit", () => {
  const cases: Array<[string, CopyDialogState, "import" | "share", boolean]> = [
    ["import needs ≥1 source", S(), "import", false],
    ["import with one source", S({ picked: ["a"] }), "import", true],
    ["import at the cap", S({ picked: ["a", "b", "c", "d", "e"] }), "import", MAX_SOURCES === 5],
    ["import over the cap", S({ picked: ["a", "b", "c", "d", "e", "f"] }), "import", false],
    ["import ignores allCreators", S({ allCreators: true, picked: [] }), "import", false],
    ["share needs a pick or the toggle", S(), "share", false],
    ["share with a target", S({ picked: ["a"] }), "share", true],
    ["share to all creators", S({ allCreators: true, picked: [] }), "share", true],
  ];
  it.each(cases)("%s", (_label, state, mode, want) => {
    expect(canSubmit(state, mode)).toBe(want);
  });
});

describe("buildPayload", () => {
  it("import: picked sources into this Creator", () => {
    expect(buildPayload(S({ picked: ["x", "y"] }), { mode: "import", accountId: "me", ids: [1, 2] })).toEqual({
      from_account_ids: ["x", "y"], to_account_ids: ["me"], all_creators: false, ids: [1, 2],
    });
  });

  it("share to specific creators", () => {
    expect(buildPayload(S({ picked: ["x", "y"] }), { mode: "share", accountId: "me" })).toEqual({
      from_account_ids: ["me"], to_account_ids: ["x", "y"], all_creators: false, ids: undefined,
    });
  });

  it("share to all: empty to_account_ids + the flag, picks ignored", () => {
    expect(buildPayload(S({ allCreators: true, picked: ["x"] }), { mode: "share", accountId: "me", ids: [7] })).toEqual({
      from_account_ids: ["me"], to_account_ids: [], all_creators: true, ids: [7],
    });
  });
});
