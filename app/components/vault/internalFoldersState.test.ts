/** The Inflowwww folders editor's reducer and rules (`internalFoldersState.ts`), as tables. Every name is fake. */
import { describe, expect, it } from "vitest";

import type { InternalFolder } from "@/hooks/useInternalFolders";
import type { VaultMedia } from "@/lib/relay";

import {
  addedNote, ALL, barActions, buildAdd, buildRemove, buildReorder, countsText, errorNote, foldersReducer, INITIAL,
  kindNote, nameError, reorderTarget, sections, type Action, type FoldersState, type ReorderDir,
} from "./internalFoldersState";

const media = (id: number) => ({ id, type: "photo" }) as VaultMedia;
const folder = (id: number, name: string, kind: InternalFolder["kind"], items = 0, photos = items, videos = 0): InternalFolder =>
  ({ id, name, kind, items, photos, videos, of_list_id: null });
const run = (actions: Action[], from: FoldersState = INITIAL) => actions.reduce(foldersReducer, from);
const ticked = (...ids: number[]) => run(ids.map((id) => ({ type: "toggle", media: media(id) }) as Action), { ...INITIAL, openId: 7 });

describe("foldersReducer", () => {
  it("opening a folder is a new view; the same folder again changes nothing", () => {
    const dirty = run([{ type: "mediaType", value: "video" }, { type: "query", value: "red" }, { type: "toggle", media: media(1) }],
      { ...INITIAL, openId: 7, notice: { tone: "ok", text: "x" } });
    expect(foldersReducer(dirty, { type: "open", id: 7 })).toBe(dirty);
    expect(foldersReducer(dirty, { type: "open", id: 8 })).toEqual({ ...INITIAL, openId: 8 });
    expect(foldersReducer(dirty, { type: "open", id: null })).toEqual(INITIAL);
  });

  it("a tick turns select mode on; a second tick takes it off; leaving select mode drops them", () => {
    const one = ticked(1, 2);
    expect(one.selectMode).toBe(true);
    expect([...one.selected.keys()]).toEqual([1, 2]);
    expect([...foldersReducer(one, { type: "toggle", media: media(1) }).selected.keys()]).toEqual([2]);
    const off = foldersReducer(one, { type: "toggleSelectMode" });
    expect([off.selectMode, off.selected.size]).toEqual([false, 0]);
    expect([...foldersReducer(INITIAL, { type: "selectAll", media: [media(4), media(5)] }).selected.keys()]).toEqual([4, 5]);
  });

  it("a new search drops the ticks (they may be out of view); the type filter keeps them", () => {
    const s = ticked(1);
    // Typing alone changes nothing but the box: the query settles later.
    expect(foldersReducer(s, { type: "draft", value: "re" })).toEqual({ ...s, draft: "re" });
    expect(foldersReducer(s, { type: "query", value: "red" }).selected.size).toBe(0);
    expect(foldersReducer(s, { type: "query", value: "" })).toBe(s);
    expect(foldersReducer(s, { type: "mediaType", value: "video" }).selected.size).toBe(1);
  });

  it.each<[string, Action, { selected: number; dialog: boolean; openId: FoldersState["openId"]; tone: string }]>([
    ["a remove clears the ticks and the dialog", { type: "done", text: "ok" }, { selected: 0, dialog: false, openId: 7, tone: "ok" }],
    ["a reorder keeps the ticks", { type: "done", text: "ok", keepSelection: true }, { selected: 2, dialog: false, openId: 7, tone: "ok" }],
    ["a create opens the new folder", { type: "done", text: "ok", openId: 9 }, { selected: 0, dialog: false, openId: 9, tone: "ok" }],
    ["a delete goes back to the list", { type: "done", text: "ok", openId: null }, { selected: 0, dialog: false, openId: null, tone: "ok" }],
    ["a failure keeps the ticks and the dialog", { type: "failed", text: "no" }, { selected: 2, dialog: true, openId: 7, tone: "err" }],
  ])("%s", (_name, action, want) => {
    const busy = run([{ type: "dialog", dialog: { kind: "target", mode: "move" } }, { type: "start", busy: "Moving…" }], ticked(1, 2));
    expect(busy.busy).toBe("Moving…");
    const s = foldersReducer(busy, action);
    expect({ selected: s.selected.size, dialog: s.dialog !== null, openId: s.openId, tone: s.notice?.tone }).toEqual(want);
    expect(s.busy).toBe("");
  });

  it("no dialog opens or closes while a write is in flight; a start clears the last notice", () => {
    const busy = run([{ type: "failed", text: "no" }, { type: "start", busy: "Saving…" }]);
    expect(busy.notice).toBeNull();
    expect(foldersReducer(busy, { type: "dialog", dialog: { kind: "create" } })).toBe(busy);
  });
});

describe("the list", () => {
  const list = [folder(1, "feet-nude", "pack", 3), folder(2, "AI-mass", "ai", 9, 6, 3), folder(3, "beach", "own")];

  it("sections: Yours, AI folders, Feet pack; empty ones left out", () => {
    expect(sections(list).map((s) => [s.title, s.folders.map((f) => f.id)])).toEqual(
      [["Yours", [3]], ["AI folders", [2]], ["Feet pack", [1]]]);
    expect(sections([list[1]]).map((s) => s.kind)).toEqual(["ai"]);
  });

  it.each([
    [folder(1, "a", "own", 0), "empty"],
    [folder(1, "a", "own", 1), "1 photo"],
    [folder(1, "a", "own", 15, 12, 3), "12 photos · 3 videos"],
    [folder(1, "a", "own", 4, 0, 1), "1 video · 3 other"],
  ])("countsText %#", (f, want) => expect(countsText(f)).toBe(want));

  it("kindNote: said for generated and pack folders only", () => {
    expect(kindNote("ai")).toMatch(/becomes yours/);
    expect(kindNote("pack")).toMatch(/photos only/);
    expect(kindNote("own")).toBe("");
  });

  it.each<[string, number | null, string]>([
    ["  ", null, "Name it first."],
    ["x".repeat(121), null, "120 characters at most."],
    ["beach", null, "A folder with this name already exists."],
    [" beach ", 3, ""],
    ["pool", null, ""],
  ])("nameError(%j, %j)", (text, id, want) => expect(nameError(text, list, id)).toBe(want));
});

describe("barActions", () => {
  it.each<[string, Parameters<typeof barActions>, string]>([
    ["the list", [null, 3], ""],
    ["All media adds", [ALL, 3], "add"],
    ["All media, no folder to add to", [ALL, 0], ""],
    ["a folder", [7, 3], "remove copy move reorder"],
    ["the only folder", [7, 1], "remove reorder"],
    ["a folder under a filter", [7, 3, true], "remove copy move"],
  ])("%s", (_n, args, want) => {
    const on = Object.entries(barActions(...args)).filter(([, v]) => v).map(([k]) => k).join(" ");
    expect(on).toBe(want);
  });
});

describe("reorderTarget", () => {
  const items = [1, 2, 3, 4, 5].map((id) => ({ id }));
  /** The folder after the press (the relay's `place_before`), or null when the press is off. */
  const after = (sel: number[], dir: ReorderDir, hasMore = false) => {
    const t = reorderTarget(items, new Set(sel), dir, hasMore);
    if (!t) return null;
    const rest = items.map((m) => m.id).filter((id) => !t.ids.includes(id));
    const at = t.before === null ? rest.length : rest.indexOf(t.before);
    return [...rest.slice(0, at), ...t.ids, ...rest.slice(at)].join("");
  };

  it.each<[number[], ReorderDir, string | null]>([
    [[3], "first", "31245"],
    [[1], "first", null],
    [[1, 2], "first", null],
    [[2, 4], "first", "24135"],
    [[3], "earlier", "13245"],
    [[1], "earlier", null],
    [[3, 4], "earlier", "13425"],
    [[1, 3], "earlier", "13245"],
    [[3], "later", "12435"],
    [[4], "later", "12354"],
    [[5], "later", null],
    [[3, 5], "later", "12435"],
    [[3], "last", "12453"],
    [[5], "last", null],
    [[4, 5], "last", null],
    [[1, 2, 3, 4, 5], "first", null],
    [[1, 2, 3, 4, 5], "last", null],
    [[], "first", null],
  ])("%j %s → %s", (sel, dir, want) => expect(after(sel, dir)).toBe(want));

  it("with unloaded pages: Last still goes to the folder's end; Later past the loaded page is off", () => {
    expect(reorderTarget(items, new Set([5]), "last", true)).toEqual({ ids: [5], before: null });
    expect(reorderTarget(items, new Set([4]), "later", true)).toBeNull();
    expect(reorderTarget(items, new Set([5]), "later", true)).toBeNull();
    expect(after([3], "later", true)).toBe("12435");
  });
});

describe("request bodies and lines", () => {
  const sel = ticked(5, 2).selected;

  it("carry the ticks in tick order; a move names its source", () => {
    expect(buildAdd("a1", sel, null)).toEqual({ account_id: "a1", media_ids: [5, 2] });
    expect(buildAdd("a1", sel, 7)).toEqual({ account_id: "a1", media_ids: [5, 2], move_from: 7 });
    expect(buildRemove("a1", sel)).toEqual({ account_id: "a1", media_ids: [5, 2] });
    expect(buildReorder("a1", { ids: [2, 5], before: null })).toEqual({ account_id: "a1", media_ids: [2, 5], before: null });
  });

  it.each([
    [{ added: 3, already: 0 }, true, "Moved 3 to beach"],
    [{ added: 2, already: 1 }, false, "Added 2 to beach · 1 already there"],
  ])("addedNote %#", (res, moved, want) => expect(addedNote(res, "beach", moved)).toBe(want));

  it.each([
    ["A feet pack is photos only: 1 of these are not photos.", "A feet pack is photos only: 1 of these are not photos."],
    ['{"error":"folder_not_found"}', "Couldn't save that. Reload and try again."],
    ["relay 500", "Couldn't save that. Reload and try again."],
    ["", "Couldn't save that. Reload and try again."],
  ])("errorNote(%j)", (text, want) => expect(errorNote(text)).toBe(want));
});
