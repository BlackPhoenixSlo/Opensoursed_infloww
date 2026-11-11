import { describe, expect, it } from "vitest";

import type { VaultMedia } from "@/lib/relay";

import {
  browseFor, browseMapReducer, hiddenByFilter, initialBrowseState, selectionText, vaultBrowseReducer,
  type BrowseAction, type BrowseMap, type BrowseState,
} from "./vaultBrowseReducer";

const m = (id: number, type = "photo") => ({ id, type }) as VaultMedia;
const run = (actions: BrowseAction[], from: BrowseState = initialBrowseState): BrowseState =>
  actions.reduce(vaultBrowseReducer, from);
const ticked = run([{ type: "toggleSelectMode" }, { type: "toggle", media: m(1) }, { type: "toggle", media: m(2, "video") }]);
const ids = (s: BrowseState) => [...s.selected.keys()].sort((a, b) => a - b);

describe("selection", () => {
  it("toggle ticks and unticks, keeping the media", () => {
    expect(ids(ticked)).toEqual([1, 2]);
    expect(ticked.selected.get(2)?.type).toBe("video");
    expect(ids(run([{ type: "toggle", media: m(1) }], ticked))).toEqual([2]);
  });
  it("Select all turns select mode on and ticks exactly the loaded files", () => {
    const s = run([{ type: "selectAll", media: [m(5), m(6), m(7)] }]);
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

describe("a new folder or search clears the ticks (select mode stays)", () => {
  // Bug: the old panel kept `selected` across these, so the bar's actions
  // ("Add to category", "New OF folder with these", "Describe selected") acted
  // on files from the previous folder / search.
  it.each<[string, BrowseAction, Partial<BrowseState>]>([
    ["folder", { type: "folder", id: 29271410 }, { folderId: 29271410 }],
    ["Fansly album snowflake", { type: "folder", id: "900605470987055104" }, { folderId: "900605470987055104" }],
    ["search", { type: "query", value: "beach" }, { query: "beach" }],
  ])("%s", (_name, action, expected) => {
    const s = vaultBrowseReducer(ticked, action);
    expect(s).toMatchObject(expected);
    expect(s.selected.size).toBe(0);
    expect(s.selectMode).toBe(true);
  });

  it("back to All media from a folder clears too", () => {
    const inFolder = run([{ type: "folder", id: 7 }, { type: "toggle", media: m(9) }], ticked);
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

describe("the Photo / Video filter keeps the ticks", () => {
  it("photos, then videos: both stay ticked, media and all", () => {
    const s = run([{ type: "mediaType", value: "photo" }, { type: "mediaType", value: "video" },
                   { type: "toggle", media: m(3, "video") }], ticked);
    expect(s.type).toBe("video");
    expect(ids(s)).toEqual([1, 2, 3]);
    expect(s.selected.get(1)?.type).toBe("photo");
  });
});

describe("hiddenByFilter: ticks the filter hides (every bar action still takes them)", () => {
  const three = run([{ type: "toggle", media: m(3, "gif") }], ticked);   // photo 1, video 2, gif 3
  it.each<[string, BrowseAction[], number, string]>([
    ["All media: none hidden", [], 0, "Selected 3"],
    ["Photo: the video and the gif", [{ type: "mediaType", value: "photo" }], 2, "3 selected · 2 hidden by filter"],
    ["Video: the photo and the gif", [{ type: "mediaType", value: "video" }], 2, "3 selected · 2 hidden by filter"],
    ["GIF: the photo and the video", [{ type: "mediaType", value: "gif" }], 2, "3 selected · 2 hidden by filter"],
    ["Audio: all of them", [{ type: "mediaType", value: "audio" }], 3, "3 selected · 3 hidden by filter"],
  ])("%s", (_n, actions, hidden, text) => {
    const s = run(actions, three);
    expect(hiddenByFilter(s)).toBe(hidden);
    expect(selectionText(s.selected.size, hiddenByFilter(s))).toBe(text);
  });
});

describe("browseMapReducer: one view per model", () => {
  const a = (accountId: string, action: BrowseAction) => ({ accountId, action });
  it("a model's folder, select mode and ticks survive another model's changes", () => {
    let map: BrowseMap = {};
    map = browseMapReducer(map, a("A", { type: "folder", id: 7 }));
    map = browseMapReducer(map, a("A", { type: "toggleSelectMode" }));
    map = browseMapReducer(map, a("A", { type: "toggle", media: m(1) }));
    map = browseMapReducer(map, a("B", { type: "folder", id: 9 }));
    expect(browseFor(map, "A")).toMatchObject({ folderId: 7, selectMode: true });
    expect(ids(browseFor(map, "A"))).toEqual([1]);
    expect(browseFor(map, "B")).toMatchObject({ folderId: 9, selectMode: false });
    expect(browseFor(map, "B").selected.size).toBe(0);
  });
  it("an unknown model reads the initial view; a no-op keeps the map", () => {
    const map: BrowseMap = {};
    expect(browseFor(map, "X")).toBe(initialBrowseState);
    expect(browseMapReducer(map, a("X", { type: "clearSelection" }))).toBe(map);
  });
});
