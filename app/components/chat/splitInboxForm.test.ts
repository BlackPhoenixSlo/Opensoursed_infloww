import type { Scope } from "@/contexts/ScopeContext";
import { describe, expect, it } from "vitest";

import type { SplitInboxConfig, SplitInboxEdits } from "@/lib/splitInbox";
import {
  allowedGroups, buildEdits, chatterGroupOf, fanGroupOf, initialForm, scopeChatters, shownGroupCount,
  splitInboxFormReducer, widestGroupCount, type Action, type ScopeChatter,
} from "./splitInboxForm";

const ONE = new Map<string, SplitInboxConfig>([
  ["a", { group_count: 3, assignments: { "11": 2, "13": 1 }, chatter_groups: { c1: 1, c2: 3 } }],
]);
const TWO = new Map<string, SplitInboxConfig>([
  ["a", { group_count: 2, assignments: { f1: 2 }, chatter_groups: { c1: 1, c2: 2 } }],
  ["b", { group_count: 3, assignments: { f9: 3 }, chatter_groups: { c1: 1, c2: 3 } }],
]);
const CHATTERS: ScopeChatter[] = [
  { id: "c1", name: "C1", models: ["a", "b"] },
  { id: "c2", name: "C2", models: ["a", "b"] },
  { id: "c3", name: "C3", models: ["b"] },
];
const ONLY_A = (id: string): ScopeChatter => ({ id, name: id, models: ["a"] });
const run = (actions: Action[]) => actions.reduce(splitInboxFormReducer, initialForm);

describe("buildEdits", () => {
  it.each<[string, Action[], string[], Omit<SplitInboxEdits, "account_ids"> | null, Scope["kind"]?]>([
    ["untouched: nothing to save", [], ["a"], null],
    ["count only", [{ type: "count", n: 2 }], ["a"], { group_count: 2 }],
    ["several Creators: the save also sets the default for new ones", [{ type: "count", n: 2 }], ["a", "b"],
      { group_count: 2, as_default: true }, "all"],
    ["All Models with one Creator saves the default", [{ type: "count", n: 2 }], ["a"],
      { group_count: 2, as_default: true }, "all"],
    ["bind and unbind, nothing else", [
      { type: "bindChatter", chatterId: "c3", group: 2 }, { type: "bindChatter", chatterId: "c1", group: null },
    ], ["a"], { chatter_groups: { c3: 2, c1: null } }],
    ["last pick for a chatter wins", [
      { type: "bindChatter", chatterId: "c1", group: 2 }, { type: "bindChatter", chatterId: "c1", group: 3 },
    ], ["a"], { chatter_groups: { c1: 3 } }],
    ["one Creator: fan moves ride along", [{ type: "moveFan", fanId: "12", group: 3 }], ["a"],
      { assignments: { "12": 3 } }],
    ["several Creators: fan moves never sent, so nothing to save", [{ type: "moveFan", fanId: "12", group: 3 }],
      ["a", "b"], null, "all"],
    ["All Models with one Creator ignores fan moves", [{ type: "moveFan", fanId: "12", group: 3 }], ["a"],
      null, "all"],
    ["count down then up sends only the last count", [{ type: "count", n: 1 }, { type: "count", n: 3 }], ["a"],
      { group_count: 3 }],
    ["a binding above a lowered count is sent as an unbind, as shown", [
      { type: "count", n: 4 }, { type: "bindChatter", chatterId: "c1", group: 3 }, { type: "count", n: 2 },
    ], ["a"], { group_count: 2, chatter_groups: { c1: null } }],
    ["a fan move above a lowered count is not sent", [
      { type: "count", n: 4 }, { type: "moveFan", fanId: "11", group: 4 }, { type: "moveFan", fanId: "12", group: 2 },
      { type: "count", n: 3 },
    ], ["a"], { group_count: 3, assignments: { "12": 2 } }],
  ])("%s", (_name, actions, ids, want, scope = "model") => {
    expect(buildEdits(run(actions), ids, scope)).toEqual(want && { account_ids: ids, ...want });
  });
});

describe("shownGroupCount / widestGroupCount", () => {
  const counts = (...ns: number[]) => new Map(ns.map((n, i) => [String(i), { group_count: n, assignments: {} }]));
  it.each<[string, Action[], Map<string, SplitInboxConfig>, number | null, number]>([
    ["one Creator: its count", [], ONE, 3, 3],
    ["every Creator agrees", [], counts(3, 3), 3, 3],
    ["they differ: Mixed, widest is the largest", [], counts(2, 4, 1), null, 4],
    ["none", [], counts(), 1, 1],
    ["a picked count overrides", [{ type: "count", n: 1 }], counts(2, 4), 1, 1],
  ])("%s", (_name, actions, stored, shown, widest) => {
    expect(shownGroupCount(run(actions), stored)).toBe(shown);
    expect(widestGroupCount(run(actions), stored)).toBe(widest);
  });
});

describe("allowedGroups", () => {
  it.each<[string, Action[], ScopeChatter, number[]]>([
    ["Mixed: the smallest count of the chatter's Creators", [], CHATTERS[0], [1, 2]],
    ["Mixed: only the chatter's Creators", [], CHATTERS[2], [1, 2, 3]],
    ["a picked count overrides", [{ type: "count", n: 4 }], CHATTERS[0], [1, 2, 3, 4]],
  ])("%s", (_name, actions, chatter, want) => {
    expect(allowedGroups(run(actions), TWO, chatter)).toEqual(want);
  });
});

describe("chatterGroupOf", () => {
  it.each<[string, Map<string, SplitInboxConfig>, Action[], ScopeChatter, number | null | "mixed"]>([
    ["one Creator: bound", ONE, [], ONLY_A("c1"), 1],
    ["one Creator: unbound", ONE, [], ONLY_A("c9"), null],
    ["one Creator: above a lowered count shows All", ONE, [{ type: "count", n: 2 }], ONLY_A("c2"), null],
    ["one Creator: count down then up keeps the binding", ONE,
      [{ type: "count", n: 1 }, { type: "count", n: 3 }], ONLY_A("c2"), 3],
    ["same binding everywhere", TWO, [], CHATTERS[0], 1],
    ["different bindings: mixed", TWO, [], CHATTERS[1], "mixed"],
    ["unbound everywhere", TWO, [], CHATTERS[2], null],
    ["edited wins", TWO, [{ type: "bindChatter", chatterId: "c2", group: 2 }], CHATTERS[1], 2],
    ["edited to All", TWO, [{ type: "bindChatter", chatterId: "c1", group: null }], CHATTERS[0], null],
    ["count 2 drops b's 3: still mixed (2 vs All)", TWO, [{ type: "count", n: 2 }], CHATTERS[1], "mixed"],
    ["edited above a lowered count shows All", TWO,
      [{ type: "count", n: 4 }, { type: "bindChatter", chatterId: "c1", group: 3 }, { type: "count", n: 2 }],
      CHATTERS[0], null],
  ])("%s", (_name, stored, actions, chatter, want) => {
    expect(chatterGroupOf(run(actions), stored, chatter)).toBe(want);
  });
});

describe("fanGroupOf", () => {
  const a = ONE.get("a")!;
  it.each<[string, Action[], string, number]>([
    ["a stored move", [], "11", 2],
    ["no move: id mod N + 1", [], "12", 1],
    ["an edited move wins", [{ type: "moveFan", fanId: "11", group: 3 }], "11", 3],
    ["a move above a lowered count falls back to the mod", [{ type: "moveFan", fanId: "12", group: 3 }, { type: "count", n: 2 }],
      "12", 1],
    ["a move above a lowered count falls back to the stored move", [
      { type: "moveFan", fanId: "13", group: 3 }, { type: "count", n: 2 },
    ], "13", 1],
  ])("%s", (_name, actions, fan, want) => {
    expect(fanGroupOf(run(actions), a, fan)).toBe(want);
  });
});

describe("scopeChatters", () => {
  it("lists non-owners who see any in-scope Creator, with only those Creators", () => {
    const roster = [
      { chatter_id: "o", display_name: "Owner", kind: "owner" as const, account_ids: null },
      { chatter_id: "all", display_name: "All", kind: "login" as const, account_ids: null },
      { chatter_id: "one", display_name: "One", kind: "login" as const, account_ids: ["b", "z"] },
      { chatter_id: "out", display_name: "Out", kind: "login" as const, account_ids: ["z"] },
    ];
    expect(scopeChatters(roster, ["a", "b"])).toEqual([
      { id: "all", name: "All", models: ["a", "b"] },
      { id: "one", name: "One", models: ["b"] },
    ]);
  });
});
