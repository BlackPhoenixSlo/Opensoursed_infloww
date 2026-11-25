import { describe, expect, it } from "vitest";

import { DEFAULT_KEYS, colsOf, hiddenCols, moveCol, shownKeys, toggleCol } from "./creatorCols";
import { STAT_COLS } from "./reportsMath";

describe("shownKeys", () => {
  it.each([
    [null, DEFAULT_KEYS],
    [undefined, DEFAULT_KEYS],
    [[], []],
    [["ppvsSent", "tips"], ["ppvsSent", "tips"]],
    [["gone", "tips", "tips"], ["tips"]],
  ])("%j → %j", (stored, want) => expect(shownKeys(stored as string[] | null)).toEqual(want));
});

describe("toggleCol", () => {
  it.each([
    [["tips", "message"], "tips", ["message"]],
    [["totalSubscriptionsEarnings", "message"], "tips", ["totalSubscriptionsEarnings", "tips", "message"]],
    [["tips"], "ppvsSent", ["tips", "ppvsSent"]],
    [["ppvsSent", "totalEarnings"], "tips", ["tips", "ppvsSent", "totalEarnings"]],
    [["tips"], "nope", ["tips"]],
  ])("%j toggle %s → %j", (keys, key, want) => expect(toggleCol(keys, key)).toEqual(want));
});

describe("moveCol", () => {
  it.each([
    [["a", "b", "c"], "b", -1, ["b", "a", "c"]],
    [["a", "b", "c"], "b", 1, ["a", "c", "b"]],
    [["a", "b", "c"], "a", -1, ["a", "b", "c"]],
    [["a", "b", "c"], "c", 1, ["a", "b", "c"]],
    [["a", "b"], "z", 1, ["a", "b"]],
  ] as const)("%j move %s by %d → %j", (keys, key, dir, want) => expect(moveCol(keys, key, dir)).toEqual(want));
});

it("colsOf keeps the given order; hiddenCols the capture's", () => {
  expect(colsOf(["ppvsSent", "tips"]).map((c) => c.key)).toEqual(["ppvsSent", "tips"]);
  const hidden = hiddenCols(DEFAULT_KEYS).map((c) => c.key);
  expect(hidden).toEqual(STAT_COLS.filter((c) => !c.show).map((c) => c.key));
});
