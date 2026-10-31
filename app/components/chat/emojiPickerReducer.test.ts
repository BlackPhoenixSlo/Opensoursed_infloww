import { describe, expect, it } from "vitest";

import { CATEGORIES } from "./emojiData";
import {
  emojiPickerReducer as reduce, filterEmojis, initialPickerState as init, tabEmojis, type PickerState,
} from "./emojiPickerReducer";

const first = CATEGORIES[0].items.map(([e]) => e);
const S = (p: Partial<PickerState>): PickerState => ({ ...init, ...p });

describe("emojiPickerReducer", () => {
  it.each<[string, PickerState, Parameters<typeof reduce>[1], Partial<PickerState>]>([
    ["toggled opens", init, { type: "toggled" }, { open: true }],
    ["toggled closes", S({ open: true }), { type: "toggled" }, { open: false }],
    ["closed keeps tab + search", S({ open: true, tab: "food", search: "x" }), { type: "closed" }, { open: false, tab: "food", search: "x" }],
    ["opened resets search, loads recents",
      S({ open: true, search: "cat", tab: "food" }), { type: "opened", recents: ["🐶"], favourites: [] },
      { search: "", recents: ["🐶"], tab: "food", favourites: [] }],
    ["opened with favourites selects the Favourites tab",
      S({ open: true, tab: "food" }), { type: "opened", recents: [], favourites: ["⭐", "💋"] },
      { favourites: ["⭐", "💋"], tab: "favourites" }],
    ["opened with no favourites keeps the tab",
      S({ open: true, tab: "food", favourites: ["⭐"] }), { type: "opened", recents: [], favourites: [] },
      { favourites: [], tab: "food" }],
    ["recentsRefreshed", S({ recents: ["a"] }), { type: "recentsRefreshed", recents: ["b", "a"] }, { recents: ["b", "a"] }],
    ["tabSet", init, { type: "tabSet", tab: "recents" }, { tab: "recents" }],
    ["searchSet", init, { type: "searchSet", search: " Hea" }, { search: " Hea" }],
  ])("%s", (_, state, action, want) => {
    expect(reduce(state, action)).toMatchObject(want);
  });

  it("tab persists across close and reopen", () => {
    let s = reduce(init, { type: "toggled" });
    s = reduce(s, { type: "tabSet", tab: "animals" });
    s = reduce(s, { type: "closed" });
    s = reduce(s, { type: "toggled" });
    s = reduce(s, { type: "opened", recents: [], favourites: [] });
    expect(s.tab).toBe("animals");
  });

  it("starts closed on the first category", () => {
    expect(init).toEqual({ open: false, tab: CATEGORIES[0].id, search: "", recents: [], favourites: [] });
  });
});

describe("tabEmojis", () => {
  it.each<[string, Partial<PickerState>, readonly string[]]>([
    ["a category", { tab: "food" }, CATEGORIES.find((c) => c.id === "food")!.items.map(([e]) => e)],
    ["favourites", { tab: "favourites", favourites: ["⭐"] }, ["⭐"]],
    ["empty favourites -> first category", { tab: "favourites", recents: ["🐶"] }, first],
    ["recents", { tab: "recents", recents: ["🐶", "🐱"] }, ["🐶", "🐱"]],
    ["empty recents -> first category", { tab: "recents", favourites: ["⭐"] }, first],
    ["unknown id -> first category", { tab: "nope" }, first],
  ])("%s", (_, p, want) => {
    expect(tabEmojis(S(p))).toEqual(want);
  });
});

describe("filterEmojis", () => {
  it.each<[string, string, (got: string[]) => void]>([
    ["blank", "   ", (g) => expect(g).toEqual([])],
    ["keyword, trimmed + case-folded", "  EggPlant ", (g) => expect(g).toContain("🍆")],
    ["second keyword of the same emoji", "cock", (g) => expect(g).toContain("🍆")],
    ["the emoji itself (listed twice in the set)", "🍆", (g) => expect(g).toEqual(["🍆", "🍆"])],
    ["no match", "zzzzqq", (g) => expect(g).toEqual([])],
  ])("%s", (_, q, check) => check(filterEmojis(q)));
});
