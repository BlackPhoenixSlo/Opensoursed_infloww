import { describe, expect, it } from "vitest";

import {
  buildPayload, chatterGroupOf, initForm, splitInboxFormReducer, type Action, type SplitInboxForm,
} from "./splitInboxForm";

const START = initForm({ group_count: 3, assignments: { "11": 2 }, chatter_groups: { c1: 1, c2: 3 } });
const run = (actions: Action[], from: SplitInboxForm = START) => actions.reduce(splitInboxFormReducer, from);

describe("splitInboxFormReducer + buildPayload", () => {
  it.each<[string, Action[], ReturnType<typeof buildPayload>]>([
    ["untouched saves the stored split", [], { group_count: 3, assignments: { "11": 2 }, chatter_groups: { c1: 1, c2: 3 } }],
    ["bind a new chatter", [{ type: "bindChatter", chatterId: "c3", group: 2 }],
      { group_count: 3, assignments: { "11": 2 }, chatter_groups: { c1: 1, c2: 3, c3: 2 } }],
    ["All unbinds", [{ type: "bindChatter", chatterId: "c1", group: null }],
      { group_count: 3, assignments: { "11": 2 }, chatter_groups: { c2: 3 } }],
    ["move a Fan", [{ type: "moveFan", fanId: "12", group: 3 }],
      { group_count: 3, assignments: { "11": 2, "12": 3 }, chatter_groups: { c1: 1, c2: 3 } }],
    ["lowered count drops moves and bindings above it", [{ type: "count", n: 2 }],
      { group_count: 2, assignments: { "11": 2 }, chatter_groups: { c1: 1 } }],
    ["count down then up keeps the binding", [{ type: "count", n: 1 }, { type: "count", n: 3 }],
      { group_count: 3, assignments: { "11": 2 }, chatter_groups: { c1: 1, c2: 3 } }],
  ])("%s", (_name, actions, want) => {
    expect(buildPayload(run(actions))).toEqual(want);
  });

  it("missing chatter_groups starts empty", () => {
    expect(initForm({ group_count: 2, assignments: {} }).chatterGroups).toEqual({});
  });
});

describe("chatterGroupOf", () => {
  it.each<[string, Action[], string, number | null]>([
    ["bound", [], "c1", 1],
    ["unbound", [], "c9", null],
    ["above a lowered count shows All", [{ type: "count", n: 2 }], "c2", null],
  ])("%s", (_name, actions, chatter, want) => {
    expect(chatterGroupOf(run(actions), chatter)).toBe(want);
  });
});
