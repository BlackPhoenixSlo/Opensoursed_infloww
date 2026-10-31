import { describe, expect, it, vi } from "vitest";

import {
  fanOutLocked, fanOutNote, fanOutReducer, fanOutTargets, includedTargets, initFanOut, noTargetsReason, runFanOut,
  summarizeFanOut,
  type FanOutAction, type FanOutResult, type FanOutState,
} from "@/components/compose/fanOut";

const ok = (accountId: string): FanOutResult => ({ accountId, ok: true });
const bad = (accountId: string): FanOutResult => ({ accountId, ok: false, error: "500" });
const run = (s: FanOutState, ...actions: FanOutAction[]) => actions.reduce(fanOutReducer, s);

describe("fanOutReducer — the send-lifecycle slice", () => {
  it.each<[string, FanOutState, FanOutAction[], FanOutState]>([
    ["progress is {done,total}", initFanOut(), [{ type: "progress", done: 1, total: 3 }],
      { progress: { done: 1, total: 3 }, results: null }],
    ["results land and clear progress", initFanOut(),
      [{ type: "progress", done: 2, total: 2 }, { type: "results", v: [ok("a"), bad("b")] }],
      { progress: null, results: [ok("a"), bad("b")] }],
    ["a retry's results merge by account (not replace)", initFanOut(),
      [{ type: "results", v: [ok("a"), bad("b"), bad("c")] }, { type: "results", v: [ok("b"), bad("c")] }],
      { progress: null, results: [ok("a"), ok("b"), bad("c")] }],
    ["discardResults (Start over) drops the results", { progress: null, results: [ok("a")] },
      [{ type: "discardResults" }], initFanOut()],
    ["BUG: discardResults is refused while a round is in flight (the retry's merge would forget a)",
      { progress: { done: 0, total: 1 }, results: [ok("a"), bad("b")] },
      [{ type: "discardResults" }, { type: "results", v: [ok("b")] }],
      { progress: null, results: [ok("a"), ok("b")] }],
  ])("%s", (_n, start, actions, want) => {
    expect(run(start, ...actions)).toEqual(want);
  });

  it("discardResults on nothing is a no-op (same reference)", () => {
    const s = initFanOut();
    expect(fanOutReducer(s, { type: "discardResults" })).toBe(s);
  });

  it("keeps the rest of a bigger form", () => {
    const s = { ...initFanOut(), text: "hi" };
    expect(fanOutReducer(s, { type: "results", v: [ok("a")] }).text).toBe("hi");
  });
});

describe("fanOutLocked — content locks once any model took it", () => {
  it.each<[string, FanOutState, boolean]>([
    ["no send yet", initFanOut(), false],
    ["every model failed (nothing went out: editing is safe)", { progress: null, results: [bad("a"), bad("b")] }, false],
    ["a partial round", { progress: null, results: [ok("a"), bad("b")] }, true],
    ["a retry still failing", { progress: null, results: [ok("a"), ok("b"), bad("c")] }, true],
    ["BUG: round 1 in flight (no results yet; its body already built)", { progress: { done: 0, total: 2 }, results: null }, true],
    ["a retry of all-failed in flight", { progress: { done: 1, total: 2 }, results: [bad("a"), bad("b")] }, true],
  ])("%s", (_n, s, want) => {
    expect(fanOutLocked(s)).toBe(want);
  });
});

describe("includedTargets — the included accounts and the fan-out's targets", () => {
  it("filters by the include set (chip order) and skips the models that took it", () => {
    const accounts = [{ id: "a" }, { id: "b" }, { id: "c" }];
    expect(includedTargets(accounts, (id) => id !== "c", [ok("a"), bad("b")]))
      .toEqual({ included: [{ id: "a" }, { id: "b" }], targets: ["b"] });
  });
});

describe("fanOutTargets — a retry never re-sends to a model that took it", () => {
  it.each<[string, FanOutResult[] | null, string[], string[]]>([
    ["first send: every included model", null, ["a", "b", "c"], ["a", "b", "c"]],
    ["retry: only the failed", [ok("a"), bad("b"), ok("c")], ["a", "b", "c"], ["b"]],
    ["retry: a newly included model too", [ok("a"), bad("b")], ["a", "b", "d"], ["b", "d"]],
    ["retry: a failed model excluded since is skipped", [ok("a"), bad("b")], ["a"], []],
  ])("%s", (_n, results, included, want) => {
    expect(fanOutTargets(results, included)).toEqual(want);
  });
});

describe("summarizeFanOut / fanOutNote / noTargetsReason", () => {
  it.each<[string, FanOutResult[] | null, string | null]>([
    ["no results: no note", null, null],
    ["all ok: no note", [ok("a")], null],
    ["counts every outstanding failure, all rounds merged", [ok("a"), ok("b"), bad("c")], "2/3 succeeded"],
    ["all failed", [bad("a"), bad("b")], "0/2 succeeded"],
  ])("fanOutNote: %s", (_n, results, want) => {
    expect(fanOutNote(results)).toBe(want);
  });
  it("summarizeFanOut", () => expect(summarizeFanOut([ok("a"), bad("b")])).toBe("1/2 succeeded"));
  it.each<[string, FanOutResult[] | null, string]>([
    ["nothing included before any send", null, "No models picked for broadcast"],
    ["the failed models excluded after a round", [ok("a"), bad("b")], "Nothing to retry: every failed model is excluded"],
  ])("noTargetsReason: %s", (_n, results, want) => {
    expect(noTargetsReason(results)).toBe(want);
  });
});

describe("runFanOut — one send per target, in order, never throws", () => {
  it("records each outcome and reports progress after each", async () => {
    const send = vi.fn(async (aid: string) => { if (aid === "b") throw new Error("HTTP 500"); });
    const progress: Array<[number, number]> = [];
    const out = await runFanOut(["a", "b", "c"], send, (p) => progress.push([p.done, p.total]));
    expect(send.mock.calls.map((c) => c[0])).toEqual(["a", "b", "c"]);
    expect(out).toEqual([ok("a"), { accountId: "b", ok: false, error: "HTTP 500" }, ok("c")]);
    expect(progress).toEqual([[0, 3], [1, 3], [2, 3], [3, 3]]);
  });
  it("sends one at a time (serial, like the per-model OF session)", async () => {
    let inFlight = 0;
    let peak = 0;
    await runFanOut(["a", "b", "c"], async () => {
      peak = Math.max(peak, ++inFlight);
      await new Promise((r) => setTimeout(r, 1));
      inFlight--;
    });
    expect(peak).toBe(1);
  });
  it("no targets: no sends, empty results", async () => {
    const send = vi.fn();
    expect(await runFanOut([], send)).toEqual([]);
    expect(send).not.toHaveBeenCalled();
  });
});
