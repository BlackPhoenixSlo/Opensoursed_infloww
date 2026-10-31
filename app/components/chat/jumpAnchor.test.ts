import { describe, expect, it } from "vitest";

import { ANCHOR_MAX_PAGES, anchorNext, newBackfillIds, type AnchorStep } from "./jumpAnchor";

describe("ANCHOR_MAX_PAGES", () => {
  it("keeps the 6-page bound", () => {
    expect(ANCHOR_MAX_PAGES).toBe(6);
  });
});

describe("anchorNext", () => {
  const idle = { loading: false, found: false, pages: 0, hasOlder: true, loadingOlder: false };
  it.each<[string, Partial<Parameters<typeof anchorNext>[0]>, AnchorStep]>([
    ["the thread still loading waits", { loading: true }, "wait"],
    ["loading waits even when found", { loading: true, found: true }, "wait"],
    ["found jumps", { found: true }, "jump"],
    ["found jumps even past the bound", { found: true, pages: 9, hasOlder: false }, "jump"],
    ["found jumps while an older page loads", { found: true, pages: 2, loadingOlder: true }, "jump"],
    ["no older history waits", { hasOlder: false }, "wait"],
    ["an older page in flight waits", { pages: 3, loadingOlder: true }, "wait"],
    ["first page loads", {}, "loadOlder"],
    ["sixth page loads", { pages: 5 }, "loadOlder"],
    ["seventh page gives up", { pages: 6 }, "giveUp"],
    ["past the bound gives up", { pages: 7 }, "giveUp"],
  ])("%s", (_, input, out) => {
    expect(anchorNext({ ...idle, ...input })).toBe(out);
  });
});

describe("newBackfillIds", () => {
  it.each<[string, string[], string[], string[]]>([
    ["nothing seen keeps all, in order", [], ["3", "1", "2"], ["3", "1", "2"]],
    ["drops seen ids", ["1"], ["1", "2"], ["2"]],
    ["all seen is empty", ["1", "2"], ["2", "1"], []],
    ["a repeated id once", [], ["5", "5", "6"], ["5", "6"]],
    ["snowflakes past 2^53 stay distinct", ["9007199254740993"],
      ["9007199254740993", "9007199254740992"], ["9007199254740992"]],
    ["no ids", ["1"], [], []],
  ])("%s", (_, seen, ids, out) => {
    expect(newBackfillIds(new Set(seen), ids)).toEqual(out);
  });

  it("does not mutate seen", () => {
    const seen = new Set(["1"]);
    newBackfillIds(seen, ["2", "3"]);
    expect([...seen]).toEqual(["1"]);
  });
});
