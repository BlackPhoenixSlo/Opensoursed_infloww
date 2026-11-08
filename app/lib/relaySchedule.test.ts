import { describe, expect, it } from "vitest";

import {
  PER_CREATOR, SLOW_CAP, admissible, initialSchedule, isSlow, scheduleReducer,
  type Action, type ScheduleState,
} from "@/lib/relaySchedule";

const run = (actions: Action[], s: ScheduleState = initialSchedule) => actions.reduce(scheduleReducer, s);
const enq = (id: number, accountId: string | null = `c${id}`): Action => ({ type: "enqueue", job: { id, accountId, screen: false } });
const start = (...ids: number[]): Action => ({ type: "start", ids });
/** A read the open screen's bundle covers, gone out per Creator. */
const scr = (id: number, accountId: string | null = `c${id}`): Action => ({ type: "enqueue", job: { id, accountId, screen: true } });
const reserve = (on = true): Action => ({ type: "reserve", on });
const slow: Action = { type: "net", effectiveType: "3g" };

describe("isSlow", () => {
  it.each<[string, ScheduleState["net"], boolean]>([
    ["nothing known (Safari)", null, false],
    ["4g", { effectiveType: "4g" }, false],
    ["3g", { effectiveType: "3g" }, true],
    ["2g", { effectiveType: "2g" }, true],
    ["slow-2g", { effectiveType: "slow-2g" }, true],
    ["4g with Save-Data", { effectiveType: "4g", saveData: true }, true],
    ["no type, no Save-Data", { saveData: false }, false],
  ])("%s", (_name, net, want) => {
    expect(isSlow({ net })).toBe(want);
  });
});

describe("admissible", () => {
  it.each<[string, Action[], number[]]>([
    ["empty queue", [], []],
    ["one read per Creator: all at once", [enq(1), enq(2), enq(3)], [1, 2, 3]],
    ["PER_CREATOR of one Creator's, in arrival order", [enq(1, "a"), enq(2, "a"), enq(3, "a"), enq(4, "b")], [1, 2, 4]],
    ["reads on the wire take their Creator's slots", [enq(1, "a"), enq(2, "a"), start(1), enq(3, "a"), enq(4, "b")], [2, 4]],
    ["a Creator's lane full: its reads wait, others go", [enq(1, "a"), enq(2, "a"), start(1, 2), enq(3, "a"), enq(4, "b")], [4]],
    ["a done read frees its Creator's slot", [enq(1, "a"), enq(2, "a"), enq(3, "a"), start(1, 2), { type: "done", id: 1 }], [3]],
    ["unscoped reads share one lane", [enq(1, null), enq(2, null), enq(3, null)], [1, 2]],
    ["focus Creator's reads first and past the lane",
      [enq(1, "a"), enq(2, "b"), enq(3, "b"), enq(4, "b"), { type: "focus", accountId: "b" }], [2, 3, 4, 1]],
    ["focus Creator's reads with its lane full",
      [enq(1, "f"), enq(2, "f"), start(1, 2), enq(3, "f"), { type: "focus", accountId: "f" }], [3]],
    ["focus on a Creator with nothing queued changes nothing", [enq(1), enq(2), { type: "focus", accountId: "zz" }], [1, 2]],
    ["starved link: SLOW_CAP in all", [slow, ...[1, 2, 3, 4, 5, 6].map((i) => enq(i))], [1, 2, 3, 4].slice(0, SLOW_CAP)],
    ["starved link: focus reads past SLOW_CAP",
      [slow, ...[1, 2, 3, 4, 5].map((i) => enq(i, "f")), enq(9), { type: "focus", accountId: "f" }], [1, 2, 3, 4, 5]],
    ["the screen's reads before the rest, in arrival order",
      [enq(1, "a"), enq(2, "a"), enq(3, "a"), scr(4, "a"), scr(5, "b")], [4, 5, 1]],
    ["no reserve: the rest fill a Creator's lane, a later screen read waits",
      [enq(1, "a"), enq(2, "a"), start(1, 2), scr(3, "a")], []],
    ["reserve: the rest take PER_CREATOR - 1 of a Creator, its last slot is the screen's (fan-list-chips: two held "
      + "rail feeds, then the chat list)",
      [reserve(), enq(1, "a"), enq(2, "a"), scr(3, "a"), enq(4, "b")], [3, 1, 4]],
    ["reserve: a screen read arriving after the rest took their slot still starts",
      [reserve(), enq(1, "a"), enq(2, "a"), start(1), scr(3, "a")], [3]],
    ["reserve: the screen's reads may take every slot", [reserve(), scr(1, "a"), scr(2, "a"), scr(3, "a")], [1, 2]],
    ["reserve off again: the rest take the whole lane", [reserve(), reserve(false), enq(1, "a"), enq(2, "a")], [1, 2]],
    ["focus reads before the screen's", [scr(1, "a"), enq(2, "f"), { type: "focus", accountId: "f" }], [2, 1]],
    ["starved link: the screen's reads take SLOW_CAP first",
      [slow, ...[1, 2, 3, 4].map((i) => enq(i)), ...[5, 6, 7, 8].map((i) => scr(i))], [5, 6, 7, 8].slice(0, SLOW_CAP)],
  ])("%s", (_name, actions, want) => {
    expect(admissible(run(actions))).toEqual(want);
  });
  it("reserve on a lane of 1 leaves the rest 1 slot, never 0", () => {
    expect(admissible(run([reserve(), enq(1, "a")], { ...initialSchedule, perCreator: 1 }))).toEqual([1]);
  });
  it("PER_CREATOR is the relay's background lane (service/server.py)", () => {
    expect(PER_CREATOR).toBe(2);
  });
});

describe("scheduleReducer", () => {
  it("start moves jobs from the queue to the wire", () => {
    const s = run([enq(1), enq(2), enq(3), start(1, 3)]);
    expect(s.queue.map((j) => j.id)).toEqual([2]);
    expect(s.onWire.map((j) => j.id)).toEqual([1, 3]);
  });
  it("done drops a queued read (aborted before its slot) and a running one", () => {
    const s = run([enq(1), enq(2), start(1), { type: "done", id: 2 }, { type: "done", id: 1 }]);
    expect(s.queue).toEqual([]);
    expect(s.onWire).toEqual([]);
  });
  it("same focus returns the same state", () => {
    const s = run([{ type: "focus", accountId: "a" }]);
    expect(scheduleReducer(s, { type: "focus", accountId: "a" })).toBe(s);
  });
  it("reserve toggles; the same value returns the same state", () => {
    const s = run([reserve()]);
    expect(s.reserve).toBe(true);
    expect(scheduleReducer(s, reserve())).toBe(s);
    expect(scheduleReducer(s, reserve(false)).reserve).toBe(false);
  });
  it("net replaces the browser's estimate", () => {
    const s = run([slow, { type: "net", effectiveType: "4g" }]);
    expect(s.net).toEqual({ effectiveType: "4g", saveData: undefined });
    expect(isSlow(s)).toBe(false);
  });
});
