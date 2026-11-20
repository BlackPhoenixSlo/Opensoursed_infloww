import { describe, expect, it } from "vitest";

import { reachHint } from "@/components/compose/audienceReach";

const LISTS = [{ id: 1, name: "VIP", usersCount: 30 }, { id: 2, name: "Whales", usersCount: 1 }, { id: 3, name: "New" }];
const form = (p: { all?: boolean; inc?: string[]; exc?: string[]; sIn?: number[]; sEx?: number[] } = {}) => ({
  allModels: p.all ?? false,
  includes: new Set(p.inc ?? []),
  excludes: new Set(p.exc ?? []),
  smartInclude: new Set(p.sIn ?? []),
  smartExclude: new Set(p.sEx ?? []),
});

describe("reachHint", () => {
  it.each<[string, ReturnType<typeof form>, string | null]>([
    ["nothing picked", form(), null],
    ["all-models mode", form({ all: true, inc: ["1"] }), null],
    ["one list: an upper bound", form({ inc: ["2"] }), "Reach: up to 1 fan from custom lists"],
    ["overlapping lists sum as up to", form({ inc: ["1", "2"] }), "Reach: up to 31 fans from custom lists"],
    ["a list with no count adds 0", form({ inc: ["1", "3"] }), "Reach: up to 30 fans from custom lists"],
    ["custom + system", form({ inc: ["fans", "1"] }), "Reach: up to 30 fans from custom lists + system audience"],
    ["system only: no number", form({ inc: ["fans", "following"] }), "Reach: system audience"],
    ["an excluded list hides the number", form({ inc: ["1"], exc: ["2"] }), "Reach: counted on send (Smart Lists or excluded lists picked)"],
    ["a Smart List include hides it", form({ inc: ["1"], sIn: [7] }), "Reach: counted on send (Smart Lists or excluded lists picked)"],
    ["a Smart List exclude alone hides it", form({ sEx: [7] }), "Reach: counted on send (Smart Lists or excluded lists picked)"],
  ])("%s", (_name, f, want) => {
    expect(reachHint(f, LISTS)).toBe(want);
  });
});
