import { afterEach, describe, expect, it } from "vitest";

import {
  accountCountsKey, bumpAccountCount, fanMruKey, fanStateKey, loadAccountCounts, loadFanMru, loadFanState,
  nextMru, saveFanMru, saveFanState,
} from "./vaultPickerPersist";

afterEach(() => window.localStorage.clear());

describe("storage keys (byte-identical)", () => {
  it.each([
    [fanStateKey("acc", 5), "chatterly:vault-state:acc:5"],
    [fanMruKey("acc", "s9"), "chatterly:vault-mru:acc:s9"],
    [accountCountsKey("acc"), "chatterly:vault-folder-counts:acc"],
    [fanStateKey(null, 5), null],
    [fanStateKey("acc", null), null],
    [fanMruKey(null, 5), null],
    [fanMruKey("acc", null), null],
    [accountCountsKey(null), null],
  ])("%s", (got, want) => expect(got).toBe(want));
  it("fan id 0 still keys", () => expect(fanStateKey("a", 0)).toBe("chatterly:vault-state:a:0"));
});

describe("nextMru", () => {
  it.each<[unknown[], unknown, number | undefined, unknown[]]>([
    [[], 1, undefined, [1]],
    [[1, 2], 3, undefined, [3, 1, 2]],
    [[1, 2, 3], 4, undefined, [4, 1, 2]],
    [[1, 2, 3], 3, undefined, [3, 1, 2]],
    [[1, 2, 3], 1, undefined, [1, 2, 3]],
    [[1, 2, 3], 9, 2, [9, 1]],
  ])("%j + %j (cap %s) → %j", (mru, id, cap, want) => {
    expect(nextMru(mru as never, id as never, cap)).toEqual(want);
  });
});

describe("loaders tolerate bad storage", () => {
  const ls = () => window.localStorage;
  it.each<[string, string | null, unknown]>([
    ["missing", null, null],
    ["corrupt JSON", "{nope", null],
    ["foreign values → defaults", JSON.stringify({ listId: {}, sort: "bogus", type: "audio" }),
      { listId: null, sort: "newest", type: "all" }],
    ["valid", JSON.stringify({ listId: "s1", sort: "oldest", type: "gif" }), { listId: "s1", sort: "oldest", type: "gif" }],
  ])("fan state: %s", (_n, raw, want) => {
    if (raw != null) ls().setItem("chatterly:vault-state:a:1", raw);
    expect(loadFanState("a", 1)).toEqual(want);
  });
  it.each<[string, string | null, unknown[]]>([
    ["missing", null, []],
    ["corrupt JSON", "[1,", []],
    ["not an array", "{\"a\":1}", []],
    ["null / non-number ids dropped, capped", JSON.stringify([null, 4, "x", 5, 6, 7]), [4, 5, 6]],
  ])("mru: %s", (_n, raw, want) => {
    if (raw != null) ls().setItem("chatterly:vault-mru:a:1", raw);
    expect(loadFanMru("a", 1)).toEqual(want);
  });
  it.each<[string, string | null, unknown]>([
    ["missing", null, {}],
    ["corrupt JSON", "{", {}],
    ["null", "null", {}],
    ["valid", "{\"3\":2}", { "3": 2 }],
  ])("account counts: %s", (_n, raw, want) => {
    if (raw != null) ls().setItem("chatterly:vault-folder-counts:a", raw);
    expect(loadAccountCounts("a")).toEqual(want);
  });
});

describe("writers", () => {
  it("round-trips fan state as the same JSON", () => {
    saveFanState("a", 1, { listId: 7, sort: "oldest", type: "video" });
    expect(window.localStorage.getItem("chatterly:vault-state:a:1")).toBe('{"listId":7,"sort":"oldest","type":"video"}');
  });
  it("caps the saved mru", () => {
    saveFanMru("a", 1, [1, 2, 3, 4]);
    expect(window.localStorage.getItem("chatterly:vault-mru:a:1")).toBe("[1,2,3]");
  });
  it("bumps account counts by string id", () => {
    bumpAccountCount("a", 3);
    bumpAccountCount("a", 3);
    bumpAccountCount("a", "s9");
    expect(loadAccountCounts("a")).toEqual({ "3": 2, s9: 1 });
  });
  it("null account / fan → nothing written", () => {
    saveFanState(null, 1, { listId: 1, sort: "newest", type: "all" });
    saveFanState("a", null, { listId: 1, sort: "newest", type: "all" });
    saveFanMru(null, 1, [1]);
    saveFanMru("a", null, [1]);
    bumpAccountCount(null, 1);
    expect(window.localStorage.length).toBe(0);
    expect(loadFanState("a", null)).toBeNull();
    expect(loadFanMru(null, 1)).toEqual([]);
    expect(loadAccountCounts(null)).toEqual({});
  });
});
