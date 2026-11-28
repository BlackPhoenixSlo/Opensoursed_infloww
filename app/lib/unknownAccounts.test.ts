import { afterEach, describe, expect, it } from "vitest";

import {
  initialUnknown, markUnknown, noteRoster, resetUnknownAccounts, seenNow, unknownIds, unknownReducer,
  type Action, type UnknownState,
} from "./unknownAccounts";

const run = (actions: Action[], from: UnknownState = initialUnknown) => actions.reduce(unknownReducer, from);
const roster = (principal: string, at: number): Action => ({ type: "roster", principal, roster: at });
const unknown = (id: string, principal: string | null, at: number | null): Action =>
  ({ type: "unknown", id, seen: { principal, roster: at } });

describe("unknownReducer", () => {
  it.each<[string, Action[], string[]]>([
    ["marked under the current roster", [roster("u1", 5), unknown("a", "u1", 5)], ["a"]],
    ["marked before any roster", [unknown("a", null, null)], ["a"]],
    ["roster refetch clears", [roster("u1", 5), unknown("a", "u1", 5), roster("u1", 9)], []],
    ["principal change clears", [roster("u1", 5), unknown("a", "u1", 5), roster("u2", 5)], []],
    ["same roster again keeps", [roster("u1", 5), unknown("a", "u1", 5), roster("u1", 5)], ["a"]],
    ["404 asked under an older roster ignored", [roster("u1", 5), roster("u1", 9), unknown("a", "u1", 5)], []],
    ["404 asked under another principal ignored", [roster("u1", 5), roster("u2", 5), unknown("a", "u1", 5)], []],
    ["two Creators", [roster("u1", 5), unknown("a", "u1", 5), unknown("b", "u1", 5)], ["a", "b"]],
  ])("%s", (_name, actions, want) => {
    expect([...run(actions).ids].sort()).toEqual(want);
  });

  it("no-op actions keep the same state object", () => {
    const s = run([roster("u1", 5), unknown("a", "u1", 5)]);
    expect(unknownReducer(s, roster("u1", 5))).toBe(s);
    expect(unknownReducer(s, unknown("a", "u1", 5))).toBe(s);
    expect(unknownReducer(s, unknown("b", "u1", 4))).toBe(s);
  });
});

describe("unknown accounts store", () => {
  afterEach(resetUnknownAccounts);

  it("a mark taken with seenNow holds until the roster changes", () => {
    noteRoster("u1", 1);
    markUnknown("a", seenNow());
    expect(unknownIds().has("a")).toBe(true);
    noteRoster("u1", 2);
    expect(unknownIds().has("a")).toBe(false);
  });
});
