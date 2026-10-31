import { describe, expect, it } from "vitest";

import {
  audienceError, audienceReducer, buildAudiencePayload, initAudience, massExcludeListId,
  type AudienceAction, type AudienceState,
} from "@/components/audience/audienceReducer";

const run = (s: AudienceState, ...actions: AudienceAction[]) => actions.reduce(audienceReducer, s);
const inc = (id: string): AudienceAction => ({ type: "toggleInclude", id });
const exc = (id: string): AudienceAction => ({ type: "toggleExclude", id });
const acct = (id: string | null): AudienceAction => ({ type: "setAccount", id });
const seed = (listId: string | null, accountId = "acc1"): AudienceAction => ({ type: "seedExclude", accountId, listId });
/** PriorityMass's start (the system default) and FunnelLaunchPanel's start. */
const pm = () => initAudience("acc1");
const fl = () => initAudience("acc1", ["fans"]);

describe("audienceReducer — include / exclude", () => {
  it.each<[string, AudienceAction[], string[], string[]]>([
    ["include a list", [inc("L")], ["fans", "L"], []],
    ["exclude a list", [exc("L")], ["fans"], ["L"]],
    ["include then exclude moves it out", [inc("L"), exc("L")], ["fans"], ["L"]],
    ["exclude then include moves it in", [exc("L"), inc("L")], ["fans", "L"], []],
    ["include untoggle", [inc("L"), inc("L")], ["fans"], []],
    ["exclude untoggle", [exc("L"), exc("L")], ["fans"], []],
  ])("%s (never both)", (_n, actions, includes, excludes) => {
    const s = run(fl(), ...actions);
    expect([...s.includes]).toEqual(includes);
    expect([...s.excludes]).toEqual(excludes);
    expect([...s.includes].filter((id) => s.excludes.has(id))).toEqual([]);
  });
});

describe("audienceReducer — standing exclude seed", () => {
  it.each<[string, AudienceAction[], string[], string[]]>([
    ["seeds the list", [seed("M")], ["fans"], ["M"]],
    ["the account has none: nothing", [seed(null)], ["fans"], []],
    ["seeds once: a manual untick sticks", [seed("M"), exc("M"), seed("M")], ["fans"], []],
    ["no list yet, then one appears: still once", [seed(null), seed("M")], ["fans"], []],
    ["additive to manual excludes", [exc("X"), seed("M")], ["fans"], ["X", "M"]],
    ["never a list the operator included", [inc("M"), seed("M")], ["fans", "M"], []],
    ["another account's lists: ignored", [seed("M", "acc2")], ["fans"], []],
  ])("%s", (_n, actions, includes, excludes) => {
    const s = run(fl(), ...actions);
    expect([...s.includes]).toEqual(includes);
    expect([...s.excludes]).toEqual(excludes);
  });
});

describe("audienceReducer — account change", () => {
  it.each<[string, () => AudienceState, AudienceAction[], string | null, string[], string[]]>([
    ["A → B resets to fans + following, no excludes", fl, [inc("L"), exc("X"), seed("M"), acct("acc2")],
      "acc2", ["fans", "following"], []],
    ["A → B re-arms the seed", fl, [seed("M"), acct("acc2"), seed("N", "acc2")], "acc2", ["fans", "following"], ["N"]],
    ["A → null resets too", pm, [inc("following"), exc("X"), acct(null)], null, ["fans", "following"], []],
    ["null → A (the picker's first pick) keeps the clicks", () => initAudience(null),
      [inc("following"), exc("X"), acct("acc1")], "acc1", ["fans"], ["X"]],
  ])("%s", (_n, start, actions, accountId, includes, excludes) => {
    const s = run(start(), ...actions);
    expect(s.accountId).toBe(accountId);
    expect([...s.includes]).toEqual(includes);
    expect([...s.excludes]).toEqual(excludes);
  });
  it("the same account again is a no-op (same state object)", () => {
    const s = run(pm(), inc("L"));
    expect(audienceReducer(s, acct("acc1"))).toBe(s);
  });
});

describe("massExcludeListId / audienceError", () => {
  it.each<[string, Array<{ id: number | string; name?: string }>, string | null]>([
    ["exact name", [{ id: 1, name: "VIP" }, { id: 2, name: "MASSDMEXCLUDE" }], "2"],
    ["trimmed, any case", [{ id: 3, name: " massDMexclude " }], "3"],
    ["none", [{ id: 1, name: "VIP" }, { id: 4 }], null],
  ])("massExcludeListId: %s", (_n, lists, want) => {
    expect(massExcludeListId(lists)).toBe(want);
  });
  it.each<[string, AudienceAction[], string | null]>([
    ["the defaults can send", [], null],
    ["a list alone can send", [inc("fans"), inc("following"), inc("L")], null],
    ["nothing included", [inc("fans"), inc("following")], "Pick at least one audience to include."],
  ])("audienceError: %s", (_n, actions, want) => {
    expect(audienceError(run(pm(), ...actions))).toBe(want);
  });
});

describe("buildAudiencePayload — lists in insertion order", () => {
  it.each<[string, () => AudienceState, AudienceAction[], { user_lists: string[]; excluded_user_lists: string[] }]>([
    ["PriorityMass untouched", pm, [], { user_lists: ["fans", "following"], excluded_user_lists: [] }],
    ["PriorityMass: following off, list in, list out", pm, [inc("following"), inc("101"), exc("202")],
      { user_lists: ["fans", "101"], excluded_user_lists: ["202"] }],
    ["PriorityMass: list out then in (appended after the systems)", pm, [exc("101"), inc("101"), exc("202"), exc("303")],
      { user_lists: ["fans", "following", "101"], excluded_user_lists: ["202", "303"] }],
    ["PriorityMass: fans off and back on goes last", pm, [inc("fans"), inc("101"), inc("fans")],
      { user_lists: ["following", "101", "fans"], excluded_user_lists: [] }],
    ["Funnel untouched, MASSDMEXCLUDE seeded", fl, [seed("900")], { user_lists: ["fans"], excluded_user_lists: ["900"] }],
    ["Funnel: following in, list out, seed unticked", fl, [seed("900"), inc("following"), exc("101"), exc("900")],
      { user_lists: ["fans", "following"], excluded_user_lists: ["101"] }],
    ["Funnel: excluded list moved to include", fl, [seed("900"), exc("101"), inc("101")],
      { user_lists: ["fans", "101"], excluded_user_lists: ["900"] }],
  ])("%s", (_n, start, actions, body) => {
    expect(buildAudiencePayload(run(start(), ...actions))).toEqual(body);
  });
});
