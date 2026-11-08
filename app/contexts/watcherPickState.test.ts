import { describe, expect, it } from "vitest";

import {
  pickOf, resolveWatcherPick, watcherPickReducer,
  type WatcherInputs, type WatcherPick, type WatcherPickState,
} from "@/contexts/watcherPickState";

const W = "w1";
const P: WatcherPick = { id: W, over: "model:c1" };
const EARLY: WatcherPick = { id: W, over: null };
const inp = (o: Partial<WatcherInputs> = {}): WatcherInputs =>
  ({ hydrated: true, outerKey: "model:c1", pickable: [W], loaded: true, ...o });

describe("resolveWatcherPick", () => {
  it.each<[string, WatcherPick | null, WatcherInputs, string | null, WatcherPick | null | "same"]>([
    ["no pick", null, inp(), null, null],
    ["a pick over the outer scope, listed: shown, kept", P, inp(), W, "same"],
    ["the outer scope moved: dropped", P, inp({ outerKey: "model:c2" }), null, null],
    ["not listed once loaded: dropped", P, inp({ pickable: [] }), null, null],
    ["not listed before the list loads: kept, not shown", P, inp({ pickable: [], loaded: false }), null, "same"],
    ["before the saved scope is read: not shown, kept", P, inp({ hydrated: false, outerKey: "all" }), null, "same"],
    ["before the saved scope is read, unlisted once loaded: dropped", P,
      inp({ hydrated: false, outerKey: "all", pickable: [] }), null, null],
    ["before the saved scope is read, list not loaded: kept", P,
      inp({ hydrated: false, pickable: [], loaded: false }), null, "same"],
    ["picked before the saved scope was read: takes the outer scope, shown", EARLY, inp(), W, { id: W, over: "model:c1" }],
    ["picked early, unlisted once loaded: dropped", EARLY, inp({ pickable: [] }), null, null],
    ["picked early, list not loaded: bound, kept", EARLY, inp({ pickable: [], loaded: false }), null,
      { id: W, over: "model:c1" }],
  ])("%s", (_, pick, i, active, next) => {
    const r = resolveWatcherPick(pick, i);
    expect(r.active).toBe(active);
    if (next === "same") expect(r.next).toBe(pick);
    else expect(r.next).toEqual(next);
  });
});

describe("pickOf", () => {
  it.each<[string, Parameters<typeof pickOf>, WatcherPick | null]>([
    ["a watcher, scope read", [{ kind: "model", accountId: W }, [W], true, "model:c1"], P],
    ["a watcher before the scope is read", [{ kind: "model", accountId: W }, [W], false, "all"], EARLY],
    ["a Creator", [{ kind: "model", accountId: "c2" }, [W], true, "model:c1"], null],
    ["all", [{ kind: "all" }, [W], true, "model:c1"], null],
  ])("%s", (_, args, want) => expect(pickOf(...args)).toEqual(want));
});

describe("watcherPickReducer", () => {
  const S0: WatcherPickState = { pick: P, saved: undefined };
  it.each<[string, WatcherPickState, Parameters<typeof watcherPickReducer>[1], WatcherPickState | "same"]>([
    ["a saved pick is saved", { pick: null, saved: undefined }, { type: "pick", pick: P, persist: true }, { pick: P, saved: P }],
    ["persist:false leaves the saved pick", S0, { type: "pick", pick: EARLY, persist: false }, { pick: EARLY, saved: undefined }],
    ["a Creator pick clears the saved pick", S0, { type: "pick", pick: null, persist: true }, { pick: null, saved: null }],
    ["a Pop-out Creator (persist:false) leaves it", { pick: P, saved: P }, { type: "pick", pick: null, persist: false },
      { pick: null, saved: P }],
    ["settle to the same pick: no change", S0, { type: "settle", next: P }, "same"],
    ["settle drop clears the saved pick", S0, { type: "settle", next: null }, { pick: null, saved: null }],
    ["settle bind keeps the saved pick as it is", { pick: EARLY, saved: undefined }, { type: "settle", next: P },
      { pick: P, saved: undefined }],
  ])("%s", (_, s0, a, want) => {
    const s = watcherPickReducer(s0, a);
    if (want === "same") expect(s).toBe(s0);
    else expect(s).toEqual(want);
  });
});
