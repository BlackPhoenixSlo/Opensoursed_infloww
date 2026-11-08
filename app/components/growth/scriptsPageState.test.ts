import { describe, expect, it } from "vitest";

import type { SavedReply, SavedReplySequenceMeta } from "@/lib/relay";

import {
  ALL, INITIAL, UNCATEGORIZED, activeEntry, byName, entryIds, firstGap, kindOf, livePending, matchesSearch, neighbour,
  nextStep, scriptRows, scriptsPageReducer, selectionOf, sequenceDates, sequenceHeader, sequenceOrder,
  sequenceSteps, sequencesOf, tagCountsOf,
  type Action, type ScriptsPageState, type SeqSort, type SeqSortBy, type SortBy, type SortOrder, type View,
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
      { type: "deleteEntry", kind: "tag", name: "Opener", order: TAGS, account: null }, opened("VIP"), true],
    ["the open last tag opens Uncategorized (the next drawn)", opened("VIP"),
      { type: "deleteEntry", kind: "tag", name: "VIP", order: TAGS, account: null }, opened(UNCATEGORIZED), true],
    ["another tag keeps the open one", opened("VIP"),
      { type: "deleteEntry", kind: "tag", name: "Night", order: TAGS, account: null }, opened("VIP"), false],
    ["a tag while All scripts is open keeps All scripts", {},
      { type: "deleteEntry", kind: "tag", name: "Night", order: TAGS, account: null }, opened(null), false],
    ["a pending tag drops it", { pendingTags: ["Night"] },
      { type: "deleteEntry", kind: "tag", name: "Night", order: TAGS, account: null }, { pendingTags: [], ...opened(null) }, false],
    ["the open pending tag drops it and opens the next", { pendingTags: ["Night"], ...opened("Night") },
      { type: "deleteEntry", kind: "tag", name: "Night", order: TAGS, account: null }, { pendingTags: [], ...opened("Opener") }, true],
    ["the open sequence opens the next", opened(null, "A"),
      { type: "deleteEntry", kind: "sequence", name: "A", order: SEQS, account: null }, opened(null, "B"), true],
    ["the open last sequence opens the previous", opened(null, "C"),
      { type: "deleteEntry", kind: "sequence", name: "C", order: SEQS, account: null }, opened(null, "B"), true],
    ["the only sequence opens none", opened(null, "A"),
      { type: "deleteEntry", kind: "sequence", name: "A", order: ["A"], account: null }, opened(null, null), true],
    ["the first sequence shown by default opens the next", opened(null, null),
      { type: "deleteEntry", kind: "sequence", name: "A", order: SEQS, account: null }, opened(null, "B"), true],
    ["another sequence keeps the open one", opened("VIP", "C"),
      { type: "deleteEntry", kind: "sequence", name: "A", order: SEQS, account: null }, opened("VIP", "C"), false],
    ["a sequence keeps the open tag", opened("VIP", "A"),
      { type: "deleteEntry", kind: "sequence", name: "A", order: SEQS, account: null }, opened("VIP", "B"), true],
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
      { type: "renameEntry", kind: "tag", from: "VIP", to: "VIPs", order: TAGS, account: null }, opened("VIPs")],
    ["another tag keeps the open one", opened("VIP"),
      { type: "renameEntry", kind: "tag", from: "Night", to: "Late", order: TAGS, account: null }, opened("VIP")],
    ["another tag while All scripts is open keeps All scripts", {},
      { type: "renameEntry", kind: "tag", from: "Night", to: "Late", order: TAGS, account: null }, opened(null)],
    // The page renames a pending tag here only while no script carries it (`livePending`); else on the server.
    ["an open pending tag no script carries is renamed in place", { pendingTags: ["Night", "X"], ...opened("Night") },
      { type: "renameEntry", kind: "tag", from: "Night", to: "Late", order: TAGS, account: null },
      { pendingTags: ["Late", "X"], ...opened("Late") }],
    ["a pending tag renamed onto an existing tag opens that tag", { pendingTags: ["Night"], ...opened("Night") },
      { type: "renameEntry", kind: "tag", from: "Night", to: "VIP", order: TAGS, account: null },
      { pendingTags: ["VIP"], ...opened("VIP") }],
    ["the open sequence stays open, renamed", opened(null, "B"),
      { type: "renameEntry", kind: "sequence", from: "B", to: "Bee", order: SEQS, account: null }, opened(null, "Bee")],
    ["the first sequence shown by default stays open, renamed", opened(null, null),
      { type: "renameEntry", kind: "sequence", from: "A", to: "Aa", order: SEQS, account: null }, opened(null, "Aa")],
    ["another sequence keeps the open one", opened("VIP", "B"),
      { type: "renameEntry", kind: "sequence", from: "C", to: "Cee", order: SEQS, account: null }, opened("VIP", "B")],
  ])("%s", (_n, start, action, want) => {
    const next = scriptsPageReducer(st({ checked: new Set([7]), ...start }), action);
    expect(next).toMatchObject(want);
    expect(ids(next)).toEqual([7]);
  });
});

describe("reset (another Creator)", () => {
  it("drops the picks, checked scripts and pending tags, keeps the view and takes the Creator", () => {
    const s = st({ view: "sequences", ...opened("VIP", "B"), checked: new Set([1]), pendingTags: ["N"], account: "a" });
    expect(scriptsPageReducer(s, { type: "reset", account: "b" })).toEqual({ ...INITIAL, view: "sequences", account: "b" });
  });

  it("keeps the busy ids: a run still out on the last Creator's scripts keeps their rows waiting on return", () => {
    const next = scriptsPageReducer(st({ busy: new Set([1, 2]) }), { type: "reset", account: "b" });
    expect([...next.busy]).toEqual([1, 2]);
  });

  it.each<[string, Partial<ScriptsPageState>]>([
    ["a failed run's error", { error: "HTTP 500" }],
    ["an open name prompt", { modal: { kind: "name", prompt: { kind: "rename", entry: "tag", from: "VIP" } } }],
    ["an open Share dialog", { modal: { kind: "share", ids: [1] } }],
    ["an open search with text", { search: { open: true, q: "9pm" } }],
    ["all of them at once", {
      error: "HTTP 500", modal: { kind: "excel" }, search: { open: true, q: "x" },
    }],
  ])("clears %s", (_n, start) => {
    const next = scriptsPageReducer(st(start), { type: "reset", account: "b" });
    expect(next).toMatchObject({ error: null, modal: null, search: { open: false, q: "" } });
  });

  it.each<[SortBy, SortOrder]>([["name", "asc"], ["recent", "asc"], ["name", "desc"]])(
    "keeps the sort (%s, %s): a view preference",
    (by, order) => {
      const next = scriptsPageReducer(st({ sort: { by, order }, error: "x" }), { type: "reset", account: "b" });
      expect(next.sort).toEqual({ by, order });
    },
  );
});

/** A run's end on Creator `account` (the page's initial null unless given). */
const end = (ids: number[], error: string | null = null, account: string | null = null): Action =>
  ({ type: "runEnd", ids, error, account });

describe("All models", () => {
  it.each<[string, Partial<ScriptsPageState>, Action, Partial<ScriptsPageState>]>([
    ["opening it closes the Creator's overlay and drops its checked scripts",
      { account: "a", modal: { kind: "share", ids: [1] }, checked: new Set([1, 2]) }, { type: "allModels" },
      { account: "a", allModels: true, modal: null, checked: new Set() }],
    ["opening it keeps the Creator's view and open entries",
      { account: "a", view: "sequences", ...opened("VIP", "B") }, { type: "allModels" },
      { account: "a", allModels: true, view: "sequences", ...opened("VIP", "B") }],
    ["a Creator's pick leaves it", { account: "a", allModels: true }, { type: "reset", account: "b" },
      { account: "b", allModels: false }],
    ["the same Creator's pick leaves it too", { account: "a", allModels: true }, { type: "reset", account: "a" },
      { account: "a", allModels: false }],
  ])("%s", (_n, start, action, want) => {
    expect(scriptsPageReducer(st(start), action)).toEqual(st(want));
  });
});

describe("runs: busy ids, the last error and the ticks", () => {
  type Row = [string, Partial<ScriptsPageState>, Action[], number[], string | null, number[]];
  it.each<Row>([
    ["start marks its ids busy", {}, [{ type: "runStart", ids: [1, 2] }], [1, 2], null, []],
    ["start clears the last error", { error: "old" }, [{ type: "runStart", ids: [1] }], [1], null, []],
    ["a tag delete's run (no ids) clears the error, nothing busy", { error: "old" },
      [{ type: "runStart", ids: [] }], [], null, []],
    ["end frees its ids and unchecks them (the server took them)", { checked: new Set([1, 2, 7]) },
      [{ type: "runStart", ids: [1, 2] }, end([1, 2])], [], null, [7]],
    ["a failed run's end frees its ids, sets the error and keeps the ticks", { checked: new Set([1]) },
      [{ type: "runStart", ids: [1] }, end([1], "HTTP 500")], [], "HTTP 500", [1]],
    ["overlapping runs: the first's end keeps the other's ids busy", {},
      [{ type: "runStart", ids: [1] }, { type: "runStart", ids: [2, 3] }, end([1])], [2, 3], null, []],
    ["overlapping runs: the second's end keeps the first's", {},
      [{ type: "runStart", ids: [1] }, { type: "runStart", ids: [2] }, end([2])], [1], null, []],
    ["a second run's start clears the first's failure", {},
      [{ type: "runStart", ids: [1] }, end([1], "boom"), { type: "runStart", ids: [2] }], [2], null, []],
  ])("%s", (_n, start, actions, busy, error, checked) => {
    const next = actions.reduce(scriptsPageReducer, st(start));
    expect([...next.busy].sort((a, b) => a - b)).toEqual(busy);
    expect(next.error).toBe(error);
    expect(ids(next)).toEqual(checked);
  });
});

describe("an answer asked on another Creator than the page shows is dropped", () => {
  type Row = [string, Action[], { busy: number[]; error: string | null; checked: number[]; open: Partial<Record<string, string | null>> }];
  // On Creator a, VIP and sequence B open, 1 and 7 ticked.
  const onA = st({ ...opened("VIP", "B"), checked: new Set([1, 7]), account: "a" });
  const toB: Action = { type: "reset", account: "b" };
  const toA: Action = { type: "reset", account: "a" };
  it.each<Row>([
    ["a's failure landing on b: no error, its ids freed",
      [{ type: "runStart", ids: [1] }, toB, end([1], "HTTP 500", "a")],
      { busy: [], error: null, checked: [], open: opened(null).open }],
    ["a's run out at the switch keeps its ids busy until its end",
      [{ type: "runStart", ids: [1] }, toB],
      { busy: [1], error: null, checked: [], open: opened(null).open }],
    ["a's run ending while on b: back on a, no error and nothing busy",
      [{ type: "runStart", ids: [1] }, toB, end([1], "HTTP 500", "a"), toA],
      { busy: [], error: null, checked: [], open: opened(null).open }],
    ["a's run ending after leaving a and coming back: its error shows on a",
      [{ type: "runStart", ids: [1] }, toB, toA, end([1], "HTTP 500", "a")],
      { busy: [], error: "HTTP 500", checked: [], open: opened(null).open }],
    ["a re-pick of a itself keeps a's answers",
      [{ type: "runStart", ids: [1] }, toA, end([1], "HTTP 500", "a")],
      { busy: [], error: "HTTP 500", checked: [], open: opened(null).open }],
    ["b's own failure shows on b",
      [toB, { type: "runStart", ids: [9] }, end([9], "HTTP 500", "b")],
      { busy: [], error: "HTTP 500", checked: [], open: opened(null).open }],
    ["a's success landing on b unchecks nothing of b's",
      [toB, { type: "check", ids: [1], on: true }, end([1], null, "a")],
      { busy: [], error: null, checked: [1], open: opened(null).open }],
    ["a's entry delete landing on b keeps b's open entries",
      [toB, { type: "open", kind: "tag", name: "Night" }, { type: "check", ids: [3], on: true },
        { type: "deleteEntry", kind: "tag", name: "Night", order: TAGS, account: "a" }],
      { busy: [], error: null, checked: [3], open: opened("Night").open }],
    ["a's entry rename landing on b renames nothing",
      [toB, { type: "open", kind: "tag", name: "VIP" },
        { type: "renameEntry", kind: "tag", from: "VIP", to: "VIPs", order: TAGS, account: "a" }],
      { busy: [], error: null, checked: [], open: opened("VIP").open }],
    ["the same answers on a apply",
      [end([1], null, "a"), { type: "deleteEntry", kind: "sequence", name: "B", order: SEQS, account: "a" }],
      { busy: [], error: null, checked: [], open: opened("VIP", "C").open }],
  ])("%s", (_n, actions, want) => {
    const next = actions.reduce(scriptsPageReducer, onA);
    expect([...next.busy].sort((a, b) => a - b)).toEqual(want.busy);
    expect(next.error).toBe(want.error);
    expect(ids(next)).toEqual(want.checked);
    expect(next.open).toEqual(want.open);
  });
});

describe("the overlay and the search", () => {
  it.each<[string, Partial<ScriptsPageState>, Action, Partial<ScriptsPageState>]>([
    ["a name prompt opens", {}, { type: "openModal", modal: { kind: "name", prompt: { kind: "sequence" } } },
      { modal: { kind: "name", prompt: { kind: "sequence" } } }],
    ["Share replaces an open name prompt (one overlay)", { modal: { kind: "name", prompt: { kind: "tag" } } },
      { type: "openModal", modal: { kind: "share" } }, { modal: { kind: "share" } }],
    ["close clears any overlay", { modal: { kind: "import" } }, { type: "closeModal" }, { modal: null }],
    ["the search icon opens the search", {}, { type: "searchToggle" }, { search: { open: true, q: "" } }],
    ["typing sets its text", { search: { open: true, q: "" } }, { type: "searchQ", q: "9pm" },
      { search: { open: true, q: "9pm" } }],
    ["the search icon again closes it and clears its text", { search: { open: true, q: "9pm" } },
      { type: "searchToggle" }, { search: { open: false, q: "" } }],
    ["sort by name keeps the order", {}, { type: "sortBy", by: "name" }, { sort: { by: "name", order: "desc" } }],
    ["sort order keeps the key", { sort: { by: "name", order: "desc" } }, { type: "sortOrder", order: "asc" },
      { sort: { by: "name", order: "asc" } }],
  ])("%s", (_n, start, action, want) => {
    expect(scriptsPageReducer(st(start), action)).toMatchObject(want);
  });

  it("a search and an overlay keep the checked scripts", () => {
    const s = st({ checked: new Set([4]) });
    for (const a of [{ type: "searchToggle" }, { type: "searchQ", q: "x" }, { type: "openModal", modal: { kind: "excel" } },
      { type: "closeModal" }] as Action[]) expect(ids(scriptsPageReducer(s, a))).toEqual([4]);
  });
});

/* ── derivations ─────────────────────────────────────────────────────────── */

const sr = (id: number, over: Partial<SavedReply> = {}): SavedReply =>
  ({ id, account_id: "a", title: `t${id}`, text: `text ${id}`, price: 0, locked_text: false, media: [], ...over });

const LIB: SavedReply[] = [
  sr(1, { title: "Greeting", tags: ["Opener", "VIP"], notes: "use after 9pm", updated_at: "2026-10-01" }),
  sr(2, { title: "Unlock", tags: [], updated_at: "2026-10-02" }),
  sr(3, { title: "ask location", tags: ["Opener"], script_id: "New Sub", script_step: 1, updated_at: "2026-09-01" }),
  sr(4, { title: "answer job", script_id: "New Sub", script_step: 2, updated_at: "2026-09-02" }),
  sr(5, { title: "ask fantasy", script_id: "New Sub", script_step: 2, updated_at: "2026-09-03" }),
];

describe("tagCountsOf and sequencesOf", () => {
  it.each<[string, SavedReply[], string[], Array<[string, number]>]>([
    ["each tag's scripts", LIB, [], [["Opener", 2], ["VIP", 1]]],
    ["a pending tag at 0, first", LIB, ["Night"], [["Night", 0], ["Opener", 2], ["VIP", 1]]],
    ["a pending tag a script carries counts its scripts", LIB, ["VIP"], [["VIP", 1], ["Opener", 2]]],
    ["no scripts: only the pending", [], ["Night"], [["Night", 0]]],
  ])("%s", (_n, replies, pending, want) => expect([...tagCountsOf(replies, pending)]).toEqual(want));

  it("groups by sequence in list order, unsequenced left out", () => {
    const m = sequencesOf([...LIB, sr(6, { script_id: "Alpha", script_step: 1 })]);
    expect([...m.keys()]).toEqual(["New Sub", "Alpha"]);
    expect(m.get("New Sub")!.map((r) => r.id)).toEqual([3, 4, 5]);
  });
});

describe("sequenceSteps and firstGap", () => {
  const seq = (steps: Array<[number, number | null]>) => steps.map(([id, step]) => sr(id, { script_step: step }));
  it.each<[string, Array<[number, number | null]>, string[], number[], number | null]>([
    ["one script a step", [[1, 1], [2, 2], [3, 3]], ["1", "2", "3"], [1, 2, 3], null],
    ["out of order: step order", [[3, 3], [1, 1], [2, 2]], ["1", "2", "3"], [1, 2, 3], null],
    ["a step with options: step.option, by id", [[5, 2], [3, 1], [4, 2]], ["1", "2.1", "2.2"], [3, 4, 5], null],
    ["a skipped step", [[1, 1], [2, 3]], ["1", "3"], [1, 2], 2],
    ["no step 1", [[1, 2]], ["2"], [1], 1],
    ["no step at all is step 0", [[1, null]], ["0"], [1], null],
    ["empty", [], [], [], null],
  ])("%s", (_n, steps, labels, order, gap) => {
    const rows = sequenceSteps(seq(steps));
    expect(rows.map((x) => x.label)).toEqual(labels);
    expect(rows.map((x) => x.r.id)).toEqual(order);
    expect(firstGap(seq(steps))).toBe(gap);
  });
});

describe("nextStep and sequenceDates", () => {
  it.each<[string, SavedReply[], number, { created?: string; modified?: string }]>([
    ["one past the last step", [sr(1, { script_step: 1, created_at: "2026-09-02", updated_at: "2026-09-05" }),
      sr(2, { script_step: 3, created_at: "2026-09-01", updated_at: "2026-09-03" })], 4,
      { created: "2026-09-01", modified: "2026-09-05" }],
    ["a step with options counts once", [sr(1, { script_step: 2 }), sr(2, { script_step: 2 })], 3, {}],
    ["no step at all is step 0", [sr(1, { script_step: null })], 1, {}],
    ["an empty sequence starts at 1, no dates", [], 1, {}],
  ])("%s", (_n, rows, step, dates) => {
    expect(nextStep(rows)).toBe(step);
    expect(sequenceDates(rows)).toEqual({ created: undefined, modified: undefined, ...dates });
  });
});

const meta = (name: string, over: Partial<SavedReplySequenceMeta> = {}): SavedReplySequenceMeta => ({
  name, position: 0, created_by: null, description: null, created_at: null, updated_at: null, ...over,
});

describe("sequenceHeader", () => {
  const rows = [sr(1, { created_at: "2026-09-02", updated_at: "2026-09-05" }), sr(2, { created_at: "2026-09-01" })];
  it.each<[string, SavedReplySequenceMeta | undefined, SavedReply[], ReturnType<typeof sequenceHeader>]>([
    ["no meta: the scripts' dates, no author", undefined, rows,
      { createdBy: undefined, created: "2026-09-01", modified: "2026-09-05" }],
    ["meta dates win for Created on; Last modified is the later", meta("A", {
      created_by: "Ana", created_at: "2025-01-01", updated_at: "2025-02-01" }), rows,
      { createdBy: "Ana", created: "2025-01-01", modified: "2026-09-05" }],
    ["a meta edit after the scripts' is Last modified", meta("A", { updated_at: "2026-10-01" }), rows,
      { createdBy: undefined, created: "2026-09-01", modified: "2026-10-01" }],
    ["empty everything", undefined, [], { createdBy: undefined, created: undefined, modified: undefined }],
  ])("%s", (_n, m, r, want) => expect(sequenceHeader(m, r)).toEqual(want));
});

describe("sequenceOrder", () => {
  const metas = new Map([
    ["Seq 10", meta("Seq 10", { position: 1 })],
    ["Seq 2", meta("Seq 2", { position: 2, updated_at: "2026-01-01" })],
    ["b", meta("b", { position: 0 })],
  ]);
  const seqs = new Map<string, SavedReply[]>([
    ["Seq 10", [sr(1, { updated_at: "2026-05-01" })]],
    ["Seq 2", [sr(2, { updated_at: "2025-01-01" })]],
    ["b", [sr(3, { updated_at: "2026-03-01" })]],
    ["a", [sr(4, { updated_at: "2026-04-01" })]],
  ]);
  it.each<[SeqSort, string[]]>([
    [{ by: "custom", order: "asc" }, ["b", "Seq 10", "Seq 2", "a"]],
    [{ by: "custom", order: "desc" }, ["a", "Seq 2", "Seq 10", "b"]],
    [{ by: "name", order: "asc" }, ["a", "b", "Seq 2", "Seq 10"]],
    [{ by: "name", order: "desc" }, ["Seq 10", "Seq 2", "b", "a"]],
    [{ by: "recent", order: "desc" }, ["Seq 10", "a", "b", "Seq 2"]],
    [{ by: "recent", order: "asc" }, ["Seq 2", "b", "a", "Seq 10"]],
  ])("%j", (sort, want) => expect(sequenceOrder(metas, seqs, sort)).toEqual(want));

  it.each<[string, string, number]>([
    ["Step 2", "Step 10", -1], ["step 1", "STEP 1", 0], ["b", "a", 1],
  ])("byName(%s, %s) is %i", (a, b, sign) => expect(Math.sign(byName(a, b))).toBe(sign));

  it("no meta at all: Custom is by name, numbers by value", () => {
    const seqs = new Map(["x 10", "x 9", "X 1"].map((n) => [n, []]));
    expect(sequenceOrder(new Map(), seqs, INITIAL.seqSort)).toEqual(["X 1", "x 9", "x 10"]);
  });
});

describe("seqSort", () => {
  it.each<[string, SeqSort, SeqSortBy, SeqSort]>([
    ["Custom is the default; picking it again flips", INITIAL.seqSort, "custom", { by: "custom", order: "desc" }],
    ["another sort starts ascending", { by: "custom", order: "desc" }, "name", { by: "name", order: "asc" }],
    ["Recent starts newest first", INITIAL.seqSort, "recent", { by: "recent", order: "desc" }],
    ["Recent again flips to oldest first", { by: "recent", order: "desc" }, "recent", { by: "recent", order: "asc" }],
  ])("%s", (_n, from, by, want) => {
    expect(scriptsPageReducer(st({ seqSort: from }), { type: "seqSort", by }).seqSort).toEqual(want);
  });

  it("survives another Creator", () => {
    const s = scriptsPageReducer(st({ seqSort: { by: "name", order: "desc" } }), { type: "reset", account: "b" });
    expect(s.seqSort).toEqual({ by: "name", order: "desc" });
  });
});

describe("sequencesOf at scale", () => {
  it("groups 10k scripts over 700 sequences in list order, linear time", () => {
    const rows = Array.from({ length: 10_000 }, (_, i) => sr(i, { script_id: `S${i % 700}`, script_step: i }));
    const t = performance.now();
    const m = sequencesOf(rows);
    expect(performance.now() - t).toBeLessThan(200);
    expect(m.size).toBe(700);
    expect(m.get("S5")!.map((r) => r.id).slice(0, 3)).toEqual([5, 705, 1405]);
  });
});

describe("matchesSearch", () => {
  it.each<[string, string, boolean]>([
    ["no text finds all", "", true],
    ["blank text finds all", "   ", true],
    ["the name, case-blind", "greet", true],
    ["the text", "TEXT 1", true],
    ["the notes", "9pm", true],
    ["a tag", "vip", true],
    ["nothing else", "fantasy", false],
  ])("%s", (_n, q, want) => expect(matchesSearch(LIB[0], q)).toBe(want));
});

describe("scriptRows", () => {
  const SEQS = sequencesOf(LIB);
  const rowsOf = (over: Partial<Parameters<typeof scriptRows>[0]>) => scriptRows({
    view: "tags", replies: LIB, sequences: SEQS, activeSeq: null, activeTag: ALL, q: "",
    sort: { by: "recent", order: "desc" }, ...over,
  });
  type Row = [string, Partial<Parameters<typeof scriptRows>[0]>, Array<number | string>];
  const view = (v: View) => ({ view: v });
  it.each<Row>([
    ["Tag, All scripts: every script in list order", {}, [1, 2, 3, 4, 5]],
    ["Tag, Uncategorized: the untagged", { activeTag: UNCATEGORIZED }, [2, 4, 5]],
    ["Tag, a tag: its scripts", { activeTag: "Opener" }, [1, 3]],
    ["Tag, a tag no script carries: none", { activeTag: "Night" }, []],
    ["Tag, searched", { activeTag: "Opener", q: "location" }, [3]],
    ["Sequence: the steps, labelled", { ...view("sequences"), activeSeq: "New Sub" }, ["3:1", "4:2.1", "5:2.2"]],
    ["Sequence, searched: the matching steps keep their labels",
      { ...view("sequences"), activeSeq: "New Sub", q: "fantasy" }, ["5:2.2"]],
    ["Sequence, none open: none", view("sequences"), []],
    ["Manage, Recent descending: the newest edit first", view("manage"), [2, 1, 5, 4, 3]],
    ["Manage, Recent ascending", { ...view("manage"), sort: { by: "recent", order: "asc" } }, [3, 4, 5, 1, 2]],
    ["Manage, Name ascending, case-blind", { ...view("manage"), sort: { by: "name", order: "asc" } }, [4, 5, 3, 1, 2]],
    ["Manage, Name descending", { ...view("manage"), sort: { by: "name", order: "desc" } }, [2, 1, 3, 5, 4]],
    ["Manage, searched over notes", { ...view("manage"), q: "9PM" }, [1]],
    ["Manage ignores the open tag", { ...view("manage"), activeTag: "VIP" }, [2, 1, 5, 4, 3]],
  ])("%s", (_n, over, want) => {
    expect(rowsOf(over).map(({ r, stepLabel }) => (stepLabel ? `${r.id}:${stepLabel}` : r.id))).toEqual(want);
  });

  it.each<[SortOrder, number[]]>([["desc", [3, 2, 1]], ["asc", [1, 2, 3]]])(
    "Manage, Recent %s: equal edit times by id",
    (order, want) => {
      const same = [2, 1, 3].map((id) => sr(id, { updated_at: "2026-10-01" }));
      expect(rowsOf({ view: "manage", replies: same, sort: { by: "recent", order } }).map(({ r }) => r.id)).toEqual(want);
    },
  );
});

describe("entryIds", () => {
  const list = [sr(1, { tags: ["VIP"], script_id: "A" }), sr(2, { tags: [], script_id: "A" }),
    sr(3, { tags: ["VIP", "N"] }), sr(4, { script_id: "B" })];
  it.each<[string, "tag" | "sequence", string, number[]]>([
    ["a tag's tagged scripts", "tag", "VIP", [1, 3]],
    ["a sequence's steps", "sequence", "A", [1, 2]],
    ["a sequence name is no tag", "tag", "A", []],
    ["an unknown entry", "sequence", "Z", []],
  ])("%s", (_n, kind, name, want) => expect(entryIds(kind, name, list)).toEqual(want));
});

describe("selectionOf", () => {
  const rows = [1, 2, 3].map((id) => ({ r: sr(id) }));
  it.each<[string, number[], number[], { checkedInList: number[]; allChecked: boolean; selBusy: boolean }]>([
    ["nothing checked", [], [], { checkedInList: [], allChecked: false, selBusy: false }],
    ["some checked", [1, 3], [], { checkedInList: [1, 3], allChecked: false, selBusy: false }],
    ["all checked", [1, 2, 3], [], { checkedInList: [1, 2, 3], allChecked: true, selBusy: false }],
    ["a checked id not in the list is left out", [2, 9], [], { checkedInList: [2], allChecked: false, selBusy: false }],
    ["a checked script busy: the bar waits", [1, 2], [2], { checkedInList: [1, 2], allChecked: false, selBusy: true }],
    ["a busy script not checked: the bar does not wait", [1], [2], { checkedInList: [1], allChecked: false, selBusy: false }],
    ["busy only outside the list", [1], [9], { checkedInList: [1], allChecked: false, selBusy: false }],
  ])("%s", (_n, checked, busy, want) => {
    expect(selectionOf(rows, new Set(checked), new Set(busy))).toEqual({ listIds: [1, 2, 3], ...want });
  });

  it("an empty list is never all checked", () => {
    expect(selectionOf([], new Set([1]), new Set())).toEqual(
      { listIds: [], checkedInList: [], allChecked: false, selBusy: false });
  });
});
