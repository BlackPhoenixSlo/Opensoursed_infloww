import { describe, expect, it } from "vitest";

import type { SplitInboxConfig } from "@/lib/splitInbox";
import {
  allChatterGroupOf, allowedGroups, buildPayloads, initialAllForm, scopeChatters, selectedGroupCount, shownGroupCount, splitInboxAllFormReducer,
  type AllAction, type ScopeChatter, type SplitInboxAllForm,
} from "./splitInboxAllForm";

const STORED = new Map<string, SplitInboxConfig>([
  ["a", { group_count: 2, assignments: { f1: 2 }, chatter_groups: { c1: 1, c2: 2 } }],
  ["b", { group_count: 3, assignments: { f9: 3 }, chatter_groups: { c1: 1, c2: 3 } }],
]);
const CHATTERS: ScopeChatter[] = [
  { id: "c1", name: "C1", models: ["a", "b"] },
  { id: "c2", name: "C2", models: ["a", "b"] },
  { id: "c3", name: "C3", models: ["b"] },
];
const run = (actions: AllAction[], from: SplitInboxAllForm = initialAllForm) =>
  actions.reduce(splitInboxAllFormReducer, from);

describe("selectedGroupCount", () => {
  it.each<[string, number[], number | null]>([
    ["every Creator agrees", [3, 3], 3],
    ["they differ", [2, 4, 1], null],
    ["none", [], 1],
  ])("%s", (_name, counts, want) => {
    const stored = new Map(counts.map((n, i) => [String(i), { group_count: n, assignments: {} }]));
    expect(selectedGroupCount(initialAllForm, stored)).toBe(want);
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

describe("allChatterGroupOf", () => {
  it.each<[string, AllAction[], string, number | null | "mixed"]>([
    ["same binding everywhere", [], "c1", 1],
    ["different bindings: mixed", [], "c2", "mixed"],
    ["unbound everywhere", [], "c3", null],
    ["edited wins", [{ type: "bindChatter", chatterId: "c2", group: 2 }], "c2", 2],
    ["edited to All", [{ type: "bindChatter", chatterId: "c1", group: null }], "c1", null],
    ["count 2 drops b's 3: still mixed (2 vs All)", [{ type: "count", n: 2 }], "c2", "mixed"],
    ["edited above the count shows All", [{ type: "bindChatter", chatterId: "c1", group: 3 }, { type: "count", n: 2 }],
      "c1", null],
  ])("%s", (_name, actions, chatter, want) => {
    expect(allChatterGroupOf(run(actions), STORED, CHATTERS.find((c) => c.id === chatter)!)).toBe(want);
  });

  it("agrees once the count drops both bindings", () => {
    const stored = new Map<string, SplitInboxConfig>([
      ["a", { group_count: 3, assignments: {}, chatter_groups: { c2: 3 } }],
      ["b", { group_count: 3, assignments: {} }],
    ]);
    expect(allChatterGroupOf(initialAllForm, stored, CHATTERS[1])).toBe("mixed");
    expect(allChatterGroupOf(run([{ type: "count", n: 2 }], initialAllForm), stored, CHATTERS[1])).toBe(null);
  });
});

describe("allowedGroups", () => {
  it.each<[string, AllAction[], ScopeChatter, number[]]>([
    ["Mixed uses the smallest count for a shared chatter", [], CHATTERS[0], [1, 2]],
    ["Mixed uses only the chatter's models", [], CHATTERS[2], [1, 2, 3]],
    ["a selected count overrides stored counts", [{ type: "count", n: 4 }], CHATTERS[0], [1, 2, 3, 4]],
  ])("%s", (_name, actions, chatter, want) => {
    expect(allowedGroups(run(actions), STORED, chatter)).toEqual(want);
  });
});

describe("shownGroupCount", () => {
  it.each<[string, AllAction[], number]>([
    ["Mixed shows the largest stored count", [], 3],
    ["a selected count overrides stored counts", [{ type: "count", n: 1 }], 1],
  ])("%s", (_name, actions, want) => {
    expect(shownGroupCount(run(actions), STORED)).toBe(want);
  });
});

describe("buildPayloads", () => {
  it.each<[string, AllAction[], Record<string, SplitInboxConfig>]>([
    ["untouched: no payloads", [], {}],
    ["count 2 only updates b and drops its out-of-range entries", [{ type: "count", n: 2 }], {
      b: { group_count: 2, assignments: {}, chatter_groups: { c1: 1 } },
    }],
    ["count 4 updates both Creators", [{ type: "count", n: 4 }], {
      a: { ...STORED.get("a")!, group_count: 4 },
      b: { ...STORED.get("b")!, group_count: 4 },
    }],
    ["a binding lands only on the Creators the chatter sees", [{ type: "bindChatter", chatterId: "c3", group: 2 }], {
      b: { group_count: 3, assignments: { f9: 3 }, chatter_groups: { c1: 1, c2: 3, c3: 2 } },
    }],
    ["binding to the stored group is a no-op", [{ type: "bindChatter", chatterId: "c1", group: 1 }], {}],
    ["All unbinds everywhere; a mixed chatter left alone keeps each binding",
      [{ type: "bindChatter", chatterId: "c1", group: null }], {
        a: { group_count: 2, assignments: { f1: 2 }, chatter_groups: { c2: 2 } },
        b: { group_count: 3, assignments: { f9: 3 }, chatter_groups: { c2: 3 } },
      }],
    ["setting a mixed chatter makes it common", [{ type: "bindChatter", chatterId: "c2", group: 1 }], {
      a: { group_count: 2, assignments: { f1: 2 }, chatter_groups: { c1: 1, c2: 1 } },
      b: { group_count: 3, assignments: { f9: 3 }, chatter_groups: { c1: 1, c2: 1 } },
    }],
  ])("%s", (_name, actions, want) => {
    expect(Object.fromEntries(buildPayloads(run(actions), STORED, CHATTERS))).toEqual(want);
  });

  it("preserves a Creator's new group after an untouched form sees refreshed configs", () => {
    const initial = new Map(STORED);
    initial.set("b", { group_count: 2, assignments: {} });
    const state = initialAllForm;
    expect(selectedGroupCount(state, initial)).toBe(2);
    expect(selectedGroupCount(state, STORED)).toBeNull();
    expect(buildPayloads(state, STORED, CHATTERS).size).toBe(0);
    expect(shownGroupCount(state, STORED)).toBe(3);
    expect(state.groupCount).toBeNull();
  });

  it("missing chatter_groups starts empty", () => {
    const stored = new Map([["a", { group_count: 1, assignments: {} }]]);
    expect(buildPayloads(initialAllForm, stored, CHATTERS).size).toBe(0);
    expect(buildPayloads(run([{ type: "count", n: 2 }], initialAllForm), stored, CHATTERS).get("a"))
      .toEqual({ group_count: 2, assignments: {}, chatter_groups: {} });
  });
});
