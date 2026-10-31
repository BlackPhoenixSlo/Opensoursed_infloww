import { describe, expect, it } from "vitest";

import {
  ALL, INITIAL, UNCATEGORIZED, activeEntry, kindOf, livePending, neighbour, scriptsPageReducer,
  type Action, type ScriptsPageState,
} from "./scriptsPageState";

const TAGS = [ALL, "Night", "Opener", "VIP", UNCATEGORIZED];
const SEQS = ["A", "B", "C"];
const st = (over: Partial<ScriptsPageState> = {}): ScriptsPageState => ({ ...INITIAL, ...over });
const opened = (tag: string | null, sequence: string | null = null) => ({ open: { tag, sequence } });
const ids = (s: ScriptsPageState) => [...s.checked].sort((a, b) => a - b);

describe("activeEntry", () => {
  it.each<[string, string | null, readonly string[], string | null]>([
    ["a listed pick", "VIP", TAGS, "VIP"],
    ["a pick no longer listed falls to the first", "Gone", TAGS, ALL],
    ["no pick on Tag is All scripts", null, TAGS, ALL],
    ["no pick on Sequence is the first", null, SEQS, "A"],
    ["nothing listed is none", null, [], null],
  ])("%s", (_n, sel, order, want) => expect(activeEntry(sel, order)).toBe(want));
});

describe("neighbour", () => {
  it.each<[string, readonly string[], string, string | null]>([
    ["the next", SEQS, "A", "B"],
    ["the next, from the middle", SEQS, "B", "C"],
    ["the previous when last", SEQS, "C", "B"],
    ["none when alone", ["A"], "A", null],
    ["none when not listed", SEQS, "Z", null],
    ["the last tag's next is Uncategorized, as drawn", TAGS, "VIP", UNCATEGORIZED],
  ])("%s", (_n, order, name, want) => expect(neighbour(order, name)).toBe(want));
});

describe("livePending", () => {
  it.each<[string, string[], Array<{ tags?: string[] | null }>, string[]]>([
    ["a tag no script carries stays pending", ["Night"], [{ tags: ["VIP"] }, {}], ["Night"]],
    ["a tag a script took is no longer pending", ["Night", "Late"], [{ tags: ["Night"] }, { tags: null }], ["Late"]],
    ["no scripts keeps every pending tag", ["Night"], [], ["Night"]],
  ])("%s", (_n, pending, replies, want) => expect(livePending(pending, replies)).toEqual(want));
});

describe("view and open clear the checked scripts", () => {
  it.each<[string, Partial<ScriptsPageState>, Action, Partial<ScriptsPageState>]>([
    ["a tab", {}, { type: "view", view: "sequences" }, { view: "sequences" }],
    ["Manage scripts", {}, { type: "view", view: "manage" }, { view: "manage" }],
    ["a tab keeps both picks", opened("VIP", "B"), { type: "view", view: "sequences" }, opened("VIP", "B")],
    ["a tag in the sidebar", {}, { type: "open", kind: "tag", name: "VIP" }, { view: "tags", ...opened("VIP") }],
    ["a sequence chip from Tag", opened("VIP"), { type: "open", kind: "sequence", name: "B" },
      { view: "sequences", ...opened("VIP", "B") }],
    ["the open entry again", opened("VIP"), { type: "open", kind: "tag", name: "VIP" }, opened("VIP")],
  ])("%s", (_n, start, action, want) => {
    for (const checked of [new Set([1, 2]), new Set<number>()]) {
      const next = scriptsPageReducer(st({ ...start, checked }), action);
      expect(next).toMatchObject(want);
      expect(next.checked.size).toBe(0);
    }
  });
});

describe("addTag opens the tag and clears the checked scripts", () => {
  it.each<[string, Partial<ScriptsPageState>, Action, Partial<ScriptsPageState>]>([
    ["a new tag (pending)", {}, { type: "addTag", name: "New", pending: true },
      { view: "tags", pendingTags: ["New"], ...opened("New") }],
    ["Add to tag (on the server)", { view: "manage" }, { type: "addTag", name: "VIP", pending: false },
      { view: "tags", pendingTags: [], ...opened("VIP") }],
    ["a second pending tag", { pendingTags: ["New"] }, { type: "addTag", name: "Late", pending: true },
      { pendingTags: ["New", "Late"], ...opened("Late") }],
  ])("%s", (_n, start, action, want) => {
    const next = scriptsPageReducer(st({ ...start, checked: new Set([1]) }), action);
    expect(next).toMatchObject(want);
    expect(next.checked.size).toBe(0);
  });
});

describe("checking scripts", () => {
  it.each<[string, number[], Action, number[]]>([
    ["check adds", [1], { type: "check", ids: [2], on: true }, [1, 2]],
    ["check an already checked", [1], { type: "check", ids: [1], on: true }, [1]],
    ["uncheck one", [1, 2], { type: "check", ids: [1], on: false }, [2]],
    ["uncheck after a delete or remove: only those ids", [1, 2, 3], { type: "check", ids: [1, 3], on: false }, [2]],
    ["uncheck ids not checked", [1], { type: "check", ids: [5], on: false }, [1]],
    ["select all replaces", [9], { type: "setChecked", ids: [1, 2, 3] }, [1, 2, 3]],
    ["select none clears", [1, 2], { type: "setChecked", ids: [] }, []],
  ])("%s", (_n, start, action, want) => {
    expect(ids(scriptsPageReducer(st({ checked: new Set(start) }), action))).toEqual(want);
  });
});

describe("kindOf", () => {
  it.each([["tags", "tag"], ["sequences", "sequence"], ["manage", null]] as const)("%s → %s", (view, want) => {
    expect(kindOf(view)).toBe(want);
  });
});

describe("deleteEntry", () => {
  type Row = [string, Partial<ScriptsPageState>, Action, Partial<ScriptsPageState>, boolean];
  it.each<Row>([
    ["the open tag opens the next", opened("Opener"),
      { type: "deleteEntry", kind: "tag", name: "Opener", order: TAGS }, opened("VIP"), true],
    ["the open last tag opens Uncategorized (the next drawn)", opened("VIP"),
      { type: "deleteEntry", kind: "tag", name: "VIP", order: TAGS }, opened(UNCATEGORIZED), true],
    ["another tag keeps the open one", opened("VIP"),
      { type: "deleteEntry", kind: "tag", name: "Night", order: TAGS }, opened("VIP"), false],
    ["a tag while All scripts is open keeps All scripts", {},
      { type: "deleteEntry", kind: "tag", name: "Night", order: TAGS }, opened(null), false],
    ["a pending tag drops it", { pendingTags: ["Night"] },
      { type: "deleteEntry", kind: "tag", name: "Night", order: TAGS }, { pendingTags: [], ...opened(null) }, false],
    ["the open pending tag drops it and opens the next", { pendingTags: ["Night"], ...opened("Night") },
      { type: "deleteEntry", kind: "tag", name: "Night", order: TAGS }, { pendingTags: [], ...opened("Opener") }, true],
    ["the open sequence opens the next", opened(null, "A"),
      { type: "deleteEntry", kind: "sequence", name: "A", order: SEQS }, opened(null, "B"), true],
    ["the open last sequence opens the previous", opened(null, "C"),
      { type: "deleteEntry", kind: "sequence", name: "C", order: SEQS }, opened(null, "B"), true],
    ["the only sequence opens none", opened(null, "A"),
      { type: "deleteEntry", kind: "sequence", name: "A", order: ["A"] }, opened(null, null), true],
    ["the first sequence shown by default opens the next", opened(null, null),
      { type: "deleteEntry", kind: "sequence", name: "A", order: SEQS }, opened(null, "B"), true],
    ["another sequence keeps the open one", opened("VIP", "C"),
      { type: "deleteEntry", kind: "sequence", name: "A", order: SEQS }, opened("VIP", "C"), false],
    ["a sequence keeps the open tag", opened("VIP", "A"),
      { type: "deleteEntry", kind: "sequence", name: "A", order: SEQS }, opened("VIP", "B"), true],
  ])("%s", (_n, start, action, want, clears) => {
    const next = scriptsPageReducer(st({ checked: new Set([7]), ...start }), action);
    expect(next).toMatchObject(want);
    expect(ids(next)).toEqual(clears ? [] : [7]);
  });
});

describe("renameEntry keeps the checked scripts", () => {
  type Row = [string, Partial<ScriptsPageState>, Action, Partial<ScriptsPageState>];
  it.each<Row>([
    ["the open tag stays open, renamed", opened("VIP"),
      { type: "renameEntry", kind: "tag", from: "VIP", to: "VIPs", order: TAGS }, opened("VIPs")],
    ["another tag keeps the open one", opened("VIP"),
      { type: "renameEntry", kind: "tag", from: "Night", to: "Late", order: TAGS }, opened("VIP")],
    ["another tag while All scripts is open keeps All scripts", {},
      { type: "renameEntry", kind: "tag", from: "Night", to: "Late", order: TAGS }, opened(null)],
    // The page renames a pending tag here only while no script carries it (`livePending`); else on the server.
    ["an open pending tag no script carries is renamed in place", { pendingTags: ["Night", "X"], ...opened("Night") },
      { type: "renameEntry", kind: "tag", from: "Night", to: "Late", order: TAGS },
      { pendingTags: ["Late", "X"], ...opened("Late") }],
    ["a pending tag renamed onto an existing tag opens that tag", { pendingTags: ["Night"], ...opened("Night") },
      { type: "renameEntry", kind: "tag", from: "Night", to: "VIP", order: TAGS },
      { pendingTags: ["VIP"], ...opened("VIP") }],
    ["the open sequence stays open, renamed", opened(null, "B"),
      { type: "renameEntry", kind: "sequence", from: "B", to: "Bee", order: SEQS }, opened(null, "Bee")],
    ["the first sequence shown by default stays open, renamed", opened(null, null),
      { type: "renameEntry", kind: "sequence", from: "A", to: "Aa", order: SEQS }, opened(null, "Aa")],
    ["another sequence keeps the open one", opened("VIP", "B"),
      { type: "renameEntry", kind: "sequence", from: "C", to: "Cee", order: SEQS }, opened("VIP", "B")],
  ])("%s", (_n, start, action, want) => {
    const next = scriptsPageReducer(st({ checked: new Set([7]), ...start }), action);
    expect(next).toMatchObject(want);
    expect(ids(next)).toEqual([7]);
  });
});

describe("reset (another Creator)", () => {
  it("drops the picks, checked scripts and pending tags, and keeps the view", () => {
    const s = st({ view: "sequences", ...opened("VIP", "B"), checked: new Set([1]), pendingTags: ["N"] });
    expect(scriptsPageReducer(s, { type: "reset" })).toEqual({ ...INITIAL, view: "sequences" });
  });
});
