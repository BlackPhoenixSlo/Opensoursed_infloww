import { describe, expect, it } from "vitest";

import {
  canPost, INITIAL_LEASE, leaseBody, SELECTED_SOURCE, shouldPostNow, sortedIds, union, viewLeaseReducer, type Action,
  type ViewLeaseState,
} from "./viewLeaseState";

const run = (actions: Action[], from: ViewLeaseState = INITIAL_LEASE) => actions.reduce(viewLeaseReducer, from);
const select = (id: string): Action => ({ type: "Hold", source: SELECTED_SOURCE, accountIds: [id] });
const unselect: Action = { type: "Release", source: SELECTED_SOURCE };
const opened: Action = { type: "Opened" };
const posted = (o: boolean): Action => ({ type: "Posted", opened: o });
const hold = (source: string, ...ids: string[]): Action => ({ type: "Hold", source, accountIds: ids });
const release = (source: string): Action => ({ type: "Release", source });
const hidden = (h: boolean): Action => ({ type: "Visibility", hidden: h });
const idle = (i: boolean): Action => ({ type: "Idle", idle: i });

describe("viewLeaseReducer: Opened and Posted", () => {
  it.each<[string, Action[], { ready: boolean; openSent: boolean; opened: boolean }]>([
    ["a fresh load is not ready and its first post carries opened", [], { ready: false, openSent: false, opened: true }],
    ["the stream opening (or the wait) makes it ready", [opened], { ready: true, openSent: false, opened: true }],
    ["Opened twice is one", [opened, opened], { ready: true, openSent: false, opened: true }],
    ["the answered opening post ends opened", [opened, posted(true)], { ready: true, openSent: true, opened: false }],
    ["a renewal without opened leaves it pending", [opened, posted(false)], { ready: true, openSent: false, opened: true }],
    ["later renewals never carry opened again", [opened, posted(true), posted(false)],
      { ready: true, openSent: true, opened: false }],
  ])("%s", (_name, actions, want) => {
    const s = run(actions);
    expect({ ready: s.ready, openSent: s.openSent, opened: leaseBody(s, "t").opened }).toEqual(want);
  });

  it("an action that changes nothing keeps the same state object", () => {
    const s = run([opened, posted(true), select("A")]);
    expect(viewLeaseReducer(s, opened)).toBe(s);
    expect(viewLeaseReducer(s, posted(true))).toBe(s);
    expect(viewLeaseReducer(s, select("A"))).toBe(s);
    expect(viewLeaseReducer(run([]), unselect)).toBe(INITIAL_LEASE);
  });
});

describe("leaseBody: the selected Creator is the first lease source", () => {
  it.each<[string, Action[], { account_ids: string[]; selected: string | null }]>([
    ["nothing selected (the All view, a Settings page)", [opened], { account_ids: [], selected: null }],
    ["a selected Creator is leased and named", [opened, select("B")], { account_ids: ["B"], selected: "B" }],
    ["a new selection replaces it", [opened, select("B"), select("A")], { account_ids: ["A"], selected: "A" }],
    ["back to the All view releases it", [opened, select("B"), unselect], { account_ids: [], selected: null }],
    ["another source's Creators join the union, sorted", [opened, select("B"),
      { type: "Hold", source: "strip", accountIds: ["C", "A", "C"] }], { account_ids: ["A", "B", "C"], selected: "B" }],
  ])("%s", (_name, actions, want) => {
    const b = leaseBody(run(actions), "tab-1");
    expect({ account_ids: b.account_ids, selected: b.selected }).toEqual(want);
    expect(b.tab).toBe("tab-1");
  });

  it("union lists each Creator once", () => {
    expect(union(run([select("A"), { type: "Hold", source: "chat", accountIds: ["A"] }]))).toEqual(["A"]);
  });
});

describe("shouldPostNow", () => {
  const ready = run([opened, posted(true)]);
  it.each<[string, ViewLeaseState, ViewLeaseState, boolean]>([
    ["never before ready, whatever changed", INITIAL_LEASE, run([select("A")]), false],
    ["becoming ready posts the opening post at once", run([select("A")]), run([select("A"), opened]), true],
    ["becoming ready with nothing selected still posts (Settings, Dashboard)", INITIAL_LEASE, run([opened]), true],
    ["a selection posts at once (its Select refresh)", ready, run([select("A")], ready), true],
    ["a changed selection posts at once", run([select("A")], ready), run([select("A"), select("B")], ready), true],
    ["a selection to a Creator already in the union still posts", run([{ type: "Hold", source: "strip",
      accountIds: ["A"] }], ready), run([{ type: "Hold", source: "strip", accountIds: ["A"] }, select("A")], ready), true],
    ["the same selection does not post", run([select("A")], ready), run([select("A"), posted(false)], ready), false],
    ["a union gain posts at once", ready, run([{ type: "Hold", source: "strip", accountIds: ["C"] }], ready), true],
    ["a union loss waits for the next tick", run([{ type: "Hold", source: "strip", accountIds: ["C", "D"] }], ready),
      run([{ type: "Hold", source: "strip", accountIds: ["C"] }], ready), false],
    ["back to the All view (selection to none) posts", run([select("A")], ready), run([select("A"), unselect], ready),
      true],
  ])("%s", (_name, prev, next, want) => {
    expect(shouldPostNow(prev, next)).toBe(want);
  });
});

describe("Hold and Release: the on-screen sources (the open chat, the rail's and the strip's visible rows)", () => {
  it.each<[string, Action[], string[]]>([
    ["the strip's visible tabs are leased", [hold("strip", "B", "A")], ["A", "B"]],
    ["scrolling the strip replaces its set", [hold("strip", "A", "B"), hold("strip", "C", "D")], ["C", "D"]],
    ["sources union, each Creator once", [hold("strip", "A", "B"), hold("rail", "B", "C"), hold("chat", "A")],
      ["A", "B", "C"]],
    ["releasing one source keeps another's hold on the same Creator", [hold("strip", "A", "B"), hold("chat", "A"),
      release("strip")], ["A"]],
    ["releasing every source leases nothing", [hold("strip", "A"), hold("rail", "B"), release("strip"),
      release("rail")], []],
    ["the All view's strip leases only what it shows, nothing selected", [hold("strip", "A", "B")], ["A", "B"]],
  ])("%s", (_name, actions, want) => {
    expect(leaseBody(run([opened, ...actions]), "t").account_ids).toEqual(want);
  });

  it("the All view (nothing selected) names no selected Creator", () => {
    expect(leaseBody(run([opened, hold("strip", "A", "B")]), "t").selected).toBeNull();
  });
});

describe("Visibility and Idle: a hidden or idle tab renews nothing", () => {
  const sent = [opened, posted(true)];
  it.each<[string, Action[], boolean]>([
    ["a ready, visible, active tab posts", sent, true],
    ["not before ready", [], false],
    ["a hidden tab does not", [...sent, hidden(true)], false],
    ["an idle tab does not", [...sent, idle(true)], false],
    ["hidden and idle: not", [...sent, hidden(true), idle(true)], false],
    ["shown again posts", [...sent, hidden(true), hidden(false)], true],
    ["back from Idle mode posts", [...sent, idle(true), idle(false)], true],
    ["shown again while still idle: not", [...sent, idle(true), hidden(true), hidden(false)], false],
    ["a load opening hidden still sends its opening post", [opened, hidden(true)], true],
    ["a load opening in Idle mode still sends its opening post", [opened, idle(true)], true],
  ])("%s", (_name, actions, want) => {
    expect(canPost(run(actions))).toBe(want);
  });

  it("Visibility or Idle that changes nothing keeps the same state object", () => {
    const s = run([opened, hidden(true), idle(true)]);
    expect(viewLeaseReducer(s, hidden(true))).toBe(s);
    expect(viewLeaseReducer(s, idle(true))).toBe(s);
  });

  const ready = run([opened, posted(true), hold("strip", "A")]);
  const away = (a: Action) => run([a], ready);
  it.each<[string, ViewLeaseState, ViewLeaseState, boolean]>([
    ["going hidden posts nothing", ready, away(hidden(true)), false],
    ["going idle posts nothing", ready, away(idle(true)), false],
    ["a union gain while hidden posts nothing", away(hidden(true)), run([hidden(true), hold("strip", "A", "B")], ready),
      false],
    ["a selection while idle posts nothing", away(idle(true)), run([idle(true), select("B")], ready), false],
    ["shown again posts at once", away(hidden(true)), run([hidden(true), hidden(false)], ready), true],
    ["back from Idle mode posts at once", away(idle(true)), run([idle(true), idle(false)], ready), true],
    ["shown again while still idle posts nothing", run([idle(true), hidden(true)], ready),
      run([idle(true), hidden(true), hidden(false)], ready), false],
    ["a union gain posts at once", ready, run([hold("rail", "C")], ready), true],
    ["a union loss (a tab scrolled away) waits for the next tick", run([hold("strip", "A", "B")], ready),
      run([hold("strip", "B")], ready), false],
    ["a released source waits for the next tick", run([hold("chat", "C")], ready),
      run([hold("chat", "C"), release("chat")], ready), false],
  ])("%s", (_name, prev, next, want) => {
    expect(shouldPostNow(prev, next)).toBe(want);
  });

  it("a load that opens hidden sends its opening post at once, leasing nothing; shown, it leases at once", () => {
    const loadHidden = run([hidden(true), hold("strip", "A"), select("B"), opened]);
    expect(shouldPostNow(run([hidden(true), hold("strip", "A"), select("B")]), loadHidden)).toBe(true);
    expect(leaseBody(loadHidden, "t")).toEqual({ tab: "t", account_ids: [], selected: null, opened: true });
    const answered = viewLeaseReducer(loadHidden, posted(true));
    expect(canPost(answered)).toBe(false);
    const shown = viewLeaseReducer(answered, hidden(false));
    expect(shouldPostNow(answered, shown)).toBe(true);
    expect(leaseBody(shown, "t")).toEqual({ tab: "t", account_ids: ["A", "B"], selected: "B", opened: false });
  });

  it("a hidden load's opening post the Relay did not answer is retried by the tick, still leasing nothing", () => {
    const s = run([hidden(true), hold("strip", "A"), opened, posted(false)]);
    expect(canPost(s)).toBe(true);
    expect(leaseBody(s, "t").account_ids).toEqual([]);
    expect(shouldPostNow(s, viewLeaseReducer(s, hold("strip", "A", "B")))).toBe(false);
  });
});

describe("sortedIds: each Creator once, sorted; the same array when nothing changed", () => {
  const prev = ["A", "B"];
  it.each<[string, string[], readonly string[] | undefined, string[], boolean]>([
    ["sorts and drops repeats", ["B", "A", "B"], undefined, ["A", "B"], false],
    ["the same Creators keep the previous array", ["B", "A"], prev, ["A", "B"], true],
    ["a change is a new array", ["A"], prev, ["A"], false],
    ["empty", [], undefined, [], false],
  ])("%s", (_name, ids, before, want, kept) => {
    const got = sortedIds(ids, before);
    expect(got).toEqual(want);
    expect(got === before).toBe(kept);
  });
});
