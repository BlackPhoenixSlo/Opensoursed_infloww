import { describe, expect, it } from "vitest";

import { initialBrowseState, vaultBrowseReducer, type BrowseAction, type BrowseState } from "./vaultBrowseReducer";

const run = (actions: BrowseAction[], from: BrowseState = initialBrowseState): BrowseState =>
  actions.reduce(vaultBrowseReducer, from);
const ticked = run([{ type: "toggleSelectMode" }, { type: "toggle", id: 1 }, { type: "toggle", id: 2 }]);
const ids = (s: BrowseState) => [...s.selected].sort((a, b) => a - b);

describe("selection", () => {
  it("toggle ticks and unticks", () => {
    expect(ids(ticked)).toEqual([1, 2]);
    expect(ids(run([{ type: "toggle", id: 1 }], ticked))).toEqual([2]);
  });
  it("Select all turns select mode on and ticks exactly the loaded files", () => {
    const s = run([{ type: "selectAll", ids: [5, 6, 7] }]);
    expect(s.selectMode).toBe(true);
    expect(ids(s)).toEqual([5, 6, 7]);
  });
  it("leaving or entering select mode drops the ticks", () => {
    const off = run([{ type: "toggleSelectMode" }], ticked);
    expect(off.selectMode).toBe(false);
    expect(off.selected.size).toBe(0);
  });
  it("clearSelection empties; on an empty set it is a no-op", () => {
    expect(run([{ type: "clearSelection" }], ticked).selected.size).toBe(0);
    const empty = run([{ type: "clearSelection" }], ticked);
    expect(vaultBrowseReducer(empty, { type: "clearSelection" })).toBe(empty);
  });
});

describe("a new view of the vault clears the ticks (select mode stays)", () => {
  // Bug: the old panel kept `selected` across these, so the bar's actions
  // ("Add to category", "New OF folder with these", "Describe selected") acted
  // on files from the previous folder / type / search.
  it.each<[string, BrowseAction, Partial<BrowseState>]>([
    ["folder", { type: "folder", id: 29271410 }, { folderId: 29271410 }],
    ["Fansly album snowflake", { type: "folder", id: "900605470987055104" }, { folderId: "900605470987055104" }],
    ["media type", { type: "mediaType", value: "video" }, { type: "video" }],
    ["search", { type: "query", value: "beach" }, { query: "beach" }],
  ])("%s", (_name, action, expected) => {
    const s = vaultBrowseReducer(ticked, action);
    expect(s).toMatchObject(expected);
    expect(s.selected.size).toBe(0);
    expect(s.selectMode).toBe(true);
  });

  it("back to All media from a folder clears too", () => {
    const inFolder = run([{ type: "folder", id: 7 }, { type: "toggle", id: 9 }], ticked);
    const s = vaultBrowseReducer(inFolder, { type: "folder", id: null });
    expect(s.folderId).toBeNull();
    expect(s.selected.size).toBe(0);
  });

  it.each<[string, BrowseAction]>([
    ["folder", { type: "folder", id: null }],
    ["media type", { type: "mediaType", value: "all" }],
    ["search", { type: "query", value: "" }],
  ])("re-picking the same %s keeps the ticks (same object)", (_name, action) => {
    expect(vaultBrowseReducer(ticked, action)).toBe(ticked);
  });
});
