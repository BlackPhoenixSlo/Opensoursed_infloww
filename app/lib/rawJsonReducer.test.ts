import { describe, expect, it } from "vitest";

import {
  canSubmit, initialRawJson, parseJsonObject, parseJsonObjectOr, rawJsonReducer,
  type RawJsonAction, type RawJsonCodec, type RawJsonState,
} from "./rawJsonReducer";

// ── The reducer over a toy codec: a list of positive ints ─────────────────

const INTS: RawJsonCodec<number[]> = {
  parse(text) {
    const v: unknown = JSON.parse(text);
    if (!Array.isArray(v) || !v.every((n) => Number.isInteger(n) && n > 0)) throw new Error("need positive ints");
    return v as number[];
  },
  format(v) {
    if (v.includes(0)) throw new Error("0 can't be written");
    return JSON.stringify(v);
  },
};
const ints = rawJsonReducer(INTS);
const run = (from: RawJsonState<number[]>, actions: RawJsonAction<number[]>[]) => actions.reduce(ints, from);
const OPEN: RawJsonAction<number[]> = { type: "open" };

describe("rawJsonReducer", () => {
  it.each<[string, RawJsonAction<number[]>[], Partial<RawJsonState<number[]>>]>([
    ["open serializes the value", [OPEN],
      { raw: true, text: "[1,2]", value: [1, 2], invalid: false, error: null }],
    ["a valid edit updates the value", [OPEN, { type: "edit", text: "[3]" }],
      { raw: true, text: "[3]", value: [3], invalid: false, error: null }],
    ["invalid JSON keeps the last valid value", [OPEN, { type: "edit", text: "[3" }],
      { raw: true, text: "[3", value: [1, 2], invalid: true }],
    ["an invalid shape keeps the last valid value", [OPEN, { type: "edit", text: "[-1]" }],
      { raw: true, value: [1, 2], invalid: true, error: "need positive ints" }],
    ["valid → invalid keeps the valid edit", [OPEN, { type: "edit", text: "[7]" }, { type: "edit", text: "[7," }],
      { value: [7], invalid: true }],
    ["invalid → valid clears the error", [OPEN, { type: "edit", text: "x" }, { type: "edit", text: "[4]" }],
      { value: [4], invalid: false, error: null }],
    ["close with a valid buffer leaves raw mode", [OPEN, { type: "edit", text: "[9]" }, { type: "close" }],
      { raw: false, value: [9], error: null }],
    ["close with an invalid buffer stays raw, text kept", [OPEN, { type: "edit", text: "[9" }, { type: "close" }],
      { raw: true, text: "[9", value: [1, 2], invalid: true }],
    ["set replaces the value", [{ type: "set", value: [5] }], { raw: false, value: [5], error: null }],
    ["update maps the current value", [{ type: "update", fn: (v) => [...v, 3] }], { value: [1, 2, 3] }],
    ["set while raw re-formats the text", [OPEN, { type: "edit", text: "[3" }, { type: "set", value: [6] }],
      { raw: true, text: "[6]", value: [6], invalid: false, error: null }],
    ["set while raw to an unformattable value drops to typed, with why", [OPEN, { type: "set", value: [0] }],
      { raw: false, value: [0], invalid: false, error: "0 can't be written" }],
    ["reopening re-serializes the value", [OPEN, { type: "edit", text: "[ 8 ]" }, { type: "close" }, OPEN],
      { raw: true, text: "[8]", value: [8] }],
    ["open that can't format stays typed with the error", [{ type: "set", value: [0] }, OPEN],
      { raw: false, value: [0], error: "0 can't be written" }],
    ["set clears a failed open's error", [{ type: "set", value: [0] }, OPEN, { type: "set", value: [1] }],
      { raw: false, error: null }],
    ["fail shows an error, typed", [{ type: "fail", error: "Save failed" }], { raw: false, error: "Save failed" }],
    ["fail while raw + valid doesn't block close", [OPEN, { type: "fail", error: "Save failed" }, { type: "close" }],
      { raw: false, error: null }],
    ["fail replaces an older error", [{ type: "set", value: [0] }, OPEN, { type: "fail", error: "newer" }],
      { error: "newer" }],
    ["fail while invalid keeps the parse error", [OPEN, { type: "edit", text: "[-1]" }, { type: "fail", error: "x" }],
      { raw: true, invalid: true, error: "need positive ints" }],
    ["an edit clears a save error", [OPEN, { type: "fail", error: "Save failed" }, { type: "edit", text: "[2]" }],
      { error: null }],
  ])("%s", (_name, actions, want) => {
    expect(run(initialRawJson([1, 2]), actions)).toMatchObject(want);
  });

  it("open while raw and close while typed are no-ops", () => {
    const open = run(initialRawJson([1]), [OPEN, { type: "edit", text: "[2]" }]);
    expect(ints(open, OPEN)).toBe(open);
    const typed = initialRawJson([1]);
    expect(ints(typed, { type: "close" })).toBe(typed);
  });

  it.each<[string, RawJsonAction<number[]>[], boolean]>([
    ["typed", [], true],
    ["typed after a failed open", [{ type: "set", value: [0] }, OPEN], true],
    ["raw, valid", [OPEN], true],
    ["raw, valid, after a failed save", [OPEN, { type: "fail", error: "Save failed" }], true],
    ["raw, invalid", [OPEN, { type: "edit", text: "[" }], false],
  ])("canSubmit: %s", (_name, actions, want) => {
    expect(canSubmit(run(initialRawJson([1]), actions))).toBe(want);
  });
});

describe("parseJsonObject", () => {
  it.each<[string, string, Record<string, unknown> | string]>([
    ["blank is {}", " ", {}],
    ["an object", '{"a":1}', { a: 1 }],
    ["not JSON", "{", "X is not valid JSON"],
    ["an array", "[]", "X must be a JSON object, e.g. {…}"],
    ["null", "null", "X must be a JSON object"],
  ])("%s", (_name, text, want) => {
    if (typeof want === "string") expect(() => parseJsonObject(text, "X", "{…}")).toThrow(want);
    else expect(parseJsonObject(text, "X", "{…}")).toEqual(want);
  });
});

describe("parseJsonObjectOr", () => {
  it.each<[string, string, Record<string, unknown> | null, string | null]>([
    ["an object, no error", '{"a":1}', { a: 1 }, null],
    ["not JSON: null + the labelled message", "{", null, "X is not valid JSON"],
    ["an array: null + the labelled message", "[]", null, "X must be a JSON object, e.g. {…}"],
  ])("%s", (_name, text, want, err) => {
    const got: string[] = [];
    expect(parseJsonObjectOr(text, "X", "{…}", (m) => got.push(m))).toEqual(want);
    expect(got).toEqual(err ? [expect.stringContaining(err)] : []);
  });
});
