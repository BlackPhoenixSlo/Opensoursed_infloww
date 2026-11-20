import { describe, expect, it } from "vitest";

import {
  creatorFreshnessReducer, EMPTY_FRESHNESS, of, type Action, type CreatorFreshnessState, type Freshness,
} from "./creatorFreshness";

const snap = (over: Partial<Freshness> = {}): Freshness => ({
  account_id: "a1", boot: 1000, seq: 1, now: 5_000, at: 4_000, cycle_s: 600, live: "up", live_since: 3_000,
  values: {}, ...over,
});
const seeded = (rows: { id: string; freshness?: Freshness | null }[], receivedAt = 50): Action =>
  ({ type: "seeded", rows, receivedAt });
const seed = (f: Freshness, receivedAt = 50): Action => seeded([{ id: f.account_id, freshness: f }], receivedAt);
const refreshed = (body: unknown, receivedAt = 60): Action => ({ type: "refreshed", body, receivedAt });
const run = (actions: Action[], from: CreatorFreshnessState = EMPTY_FRESHNESS) =>
  actions.reduce(creatorFreshnessReducer, from);

describe("creatorFreshnessReducer: (boot, seq) order", () => {
  it.each<[string, Action[], Partial<Freshness> & { receivedAt?: number }]>([
    ["a seed is held", [seed(snap())], { seq: 1, at: 4_000, receivedAt: 50 }],
    ["an event is held", [refreshed(snap({ seq: 2 }))], { seq: 2, receivedAt: 60 }],
    ["a late seed loses to a newer event",
      [refreshed(snap({ seq: 3, live: "down", at: 4_000 })), seed(snap({ seq: 2, live: "up", at: 3_000 }), 90)],
      { seq: 3, live: "down", at: 4_000, receivedAt: 60 }],
    ["a newer event replaces a seed", [seed(snap({ seq: 2 })), refreshed(snap({ seq: 3, live: "dead", at: 4_500 }))],
      { seq: 3, live: "dead", at: 4_500, receivedAt: 60 }],
    ["an equal pair keeps the higher `at`",
      [refreshed(snap({ seq: 2, at: 9_000 })), seed(snap({ seq: 2, at: 7_000, now: 9_500 }), 90)],
      { seq: 2, at: 9_000, now: 9_500, receivedAt: 90 }],
    ["an equal pair takes a higher `at`", [seed(snap({ seq: 2, at: 7_000 })), refreshed(snap({ seq: 2, at: 9_000 }))],
      { seq: 2, at: 9_000 }],
    ["`at` null never rolls a held one back", [seed(snap({ at: 7_000 })), refreshed(snap({ at: null }))], { at: 7_000 }],
    ["a new boot replaces whole, `at` included",
      [refreshed(snap({ boot: 1000, seq: 9, at: 9_000 })), seed(snap({ boot: 2000, seq: 0, at: null }), 90)],
      { boot: 2000, seq: 0, at: null, receivedAt: 90 }],
    ["an older boot loses", [seed(snap({ boot: 2000, seq: 0, at: null })), refreshed(snap({ boot: 1000, seq: 9 }))],
      { boot: 2000, seq: 0, at: null }],
  ])("%s", (_name, actions, want) => {
    expect(of(run(actions), "a1")).toMatchObject(want);
  });

  it("an equal pair keeps the higher slot `at`; the winner's slot value stays", () => {
    const s = run([
      refreshed(snap({ seq: 2, values: { unread_total: { n: 4, at: 9_000 } } })),
      seed(snap({ seq: 2, values: { unread_total: { n: 4, at: 7_000 } } }), 90),
    ]);
    expect(of(s, "a1")?.values).toEqual({ unread_total: { n: 4, at: 9_000 } });
    const t = run([
      seed(snap({ seq: 2, values: { unread_total: { n: 4, at: 7_000 }, notif_count: 1 } })),
      refreshed(snap({ seq: 2, values: { unread_total: { n: 4, at: 9_000 }, notif_count: 1 } })),
    ]);
    expect(of(t, "a1")?.values).toEqual({ unread_total: { n: 4, at: 9_000 }, notif_count: 1 });
  });

  it("a new boot replaces slots whole", () => {
    const s = run([
      refreshed(snap({ seq: 5, values: { unread_total: { n: 4, at: 9_000 } } })),
      seed(snap({ boot: 2000, seq: 0, values: { unread_total: null } })),
    ]);
    expect(of(s, "a1")?.values).toEqual({ unread_total: null });
  });

  it("Creators are held apart", () => {
    const s = run([seeded([{ id: "a1", freshness: snap() }, { id: "a2", freshness: snap({ account_id: "a2", seq: 7 }) }])]);
    expect([of(s, "a1")?.seq, of(s, "a2")?.seq, of(s, "a3")]).toEqual([1, 7, null]);
  });
});

describe("creatorFreshnessReducer: no change keeps the state object", () => {
  it.each<[string, Action]>([
    ["a seed with no `freshness` (Knob off)", seeded([{ id: "a1" }, { id: "a2", freshness: null }])],
    ["an empty seed", seeded([])],
    ["a malformed event", refreshed({ account_id: "a1" })],
    ["a non-object event", refreshed(null)],
  ])("%s on an empty store", (_name, action) => {
    expect(creatorFreshnessReducer(EMPTY_FRESHNESS, action)).toBe(EMPTY_FRESHNESS);
  });

  it("the same answer delivered twice", () => {
    const s = run([seed(snap(), 50)]);
    expect(creatorFreshnessReducer(s, seed(snap(), 50))).toBe(s);
  });

  it("an older delivery", () => {
    const s = run([refreshed(snap({ seq: 3 }))]);
    expect(creatorFreshnessReducer(s, seed(snap({ seq: 2, at: 1_000 }), 90))).toBe(s);
  });
});

describe("creatorFreshnessReducer: eviction (Contract 6)", () => {
  const two = () => run([seeded([{ id: "a1", freshness: snap() }, { id: "a2", freshness: snap({ account_id: "a2", seq: 7 }) }])]);
  const held = (s: CreatorFreshnessState) => Object.keys(s).sort();

  it.each<[string, Action, string[]]>([
    ["a row without `freshness` drops its Creator", seeded([{ id: "a1", freshness: snap() }, { id: "a2" }]), ["a1"]],
    ["a row with `freshness` null drops it", seeded([{ id: "a1", freshness: snap() }, { id: "a2", freshness: null }]), ["a1"]],
    ["a Creator missing from the answer is dropped", seeded([{ id: "a2", freshness: snap({ account_id: "a2", seq: 7 }) }]), ["a2"]],
    ["the Knob off (no row carries it) drops every one", seeded([{ id: "a1" }, { id: "a2" }]), []],
    ["an empty answer drops every one", seeded([]), []],
    ["`identityChanged` clears all", { type: "identityChanged" }, []],
  ])("%s", (_name, action, want) => {
    expect(held(creatorFreshnessReducer(two(), action))).toEqual(want);
  });

  it("a kept Creator keeps its newer snapshot over an older seed row", () => {
    const s = run([refreshed(snap({ seq: 5, at: 9_000 })), seeded([{ id: "a1", freshness: snap({ seq: 2, at: 1_000 }) }])]);
    expect(of(s, "a1")).toMatchObject({ seq: 5, at: 9_000 });
  });

  it.each<[string, Action]>([
    ["an answer carrying every held Creator", seeded([{ id: "a1", freshness: snap() }, { id: "a2", freshness: snap({ account_id: "a2", seq: 7 }) }])],
  ])("keeps the state object: %s", (_name, action) => {
    const s = two();
    expect(creatorFreshnessReducer(s, action)).toBe(s);
  });

  it("`identityChanged` on an empty store keeps the state object", () => {
    expect(creatorFreshnessReducer(EMPTY_FRESHNESS, { type: "identityChanged" })).toBe(EMPTY_FRESHNESS);
  });
});

describe("creatorFreshnessReducer: `confirmed` (the ping's `fresh`) moves `at` forward only", () => {
  const confirmed = (fresh: unknown, now = 9_900, receivedAt = 70): Action =>
    ({ type: "confirmed", fresh: fresh as Record<string, number>, now, receivedAt });
  const slot = { unread_total: { n: 4, at: 4_500 } };

  it.each<[string, Action[], Partial<Freshness> & { receivedAt?: number }]>([
    ["a later `at` moves it, with the ping's skew pair", [seed(snap({ at: 4_000 })), confirmed({ a1: 9_000 })],
      { seq: 1, at: 9_000, now: 9_900, receivedAt: 70 }],
    ["an earlier `at` never rolls it back", [seed(snap({ at: 4_000 })), confirmed({ a1: 3_000 })],
      { at: 4_000, now: 5_000, receivedAt: 50 }],
    ["a held `at` null takes it", [seed(snap({ at: null })), confirmed({ a1: 9_000 })], { at: 9_000 }],
    ["`seq` and `boot` stay", [seed(snap({ boot: 2000, seq: 7 })), confirmed({ a1: 9_000 })],
      { boot: 2000, seq: 7, at: 9_000 }],
    ["a later event still replaces it, `at` kept at the max",
      [seed(snap({ seq: 1, at: 4_000 })), confirmed({ a1: 9_000 }), refreshed(snap({ seq: 2, at: 4_000, live: "down" }))],
      { seq: 2, at: 9_000, live: "down" }],
  ])("%s", (_name, actions, want) => {
    expect(of(run(actions), "a1")).toMatchObject(want);
  });

  it("never moves a slot's `at`", () => {
    const s = run([seed(snap({ values: slot })), confirmed({ a1: 9_000 })]);
    expect(of(s, "a1")?.values).toEqual(slot);
  });

  it("moves each Creator on its own", () => {
    const s = run([
      seeded([{ id: "a1", freshness: snap({ at: 4_000 }) }, { id: "a2", freshness: snap({ account_id: "a2", at: 6_000 }) }]),
      confirmed({ a1: 9_000, a2: 5_000 }),
    ]);
    expect([of(s, "a1")?.at, of(s, "a2")?.at]).toEqual([9_000, 6_000]);
  });

  it.each<[string, Action]>([
    ["an unheld Creator (no snapshot to move)", confirmed({ a9: 9_000 })],
    ["no later `at`", confirmed({ a1: 4_000 })],
    ["an empty `fresh`", confirmed({})],
    ["a non-number `at`", confirmed({ a1: "9000" })],
    ["a malformed `fresh`", confirmed(null)],
    ["an array `fresh`", confirmed([9_000])],
  ])("keeps the state object: %s", (_name, action) => {
    const s = run([seed(snap({ at: 4_000 }))]);
    expect(creatorFreshnessReducer(s, action)).toBe(s);
  });
});
