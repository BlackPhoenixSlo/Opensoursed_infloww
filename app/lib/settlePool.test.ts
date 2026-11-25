import { describe, expect, it } from "vitest";

import { settlePool } from "./settlePool";

function probe(fail: ReadonlySet<number> = new Set()) {
  const state = { inFlight: 0, peak: 0, started: [] as number[] };
  const fn = async (n: number) => {
    state.started.push(n);
    state.peak = Math.max(state.peak, ++state.inFlight);
    await new Promise((r) => setTimeout(r, 2 + (n % 3)));
    state.inFlight -= 1;
    if (fail.has(n)) throw new Error(`no ${n}`);
    return n * 10;
  };
  return { state, fn };
}

describe("settlePool", () => {
  it.each([
    [1, 7, 1],
    [2, 7, 2],
    [2, 1, 1],
    [4, 3, 3],
    [0, 3, 1],
  ])("limit %i over %i items keeps at most %i in flight", async (limit, n, peak) => {
    const { state, fn } = probe();
    const items = Array.from({ length: n }, (_, i) => i);
    const res = await settlePool(items, limit, fn);
    expect(state.peak).toBe(peak);
    expect(state.started).toEqual(items);
    expect(res).toEqual(items.map((i) => ({ status: "fulfilled", value: i * 10 })));
  });

  it("a failure settles in place and never stops the rest", async () => {
    const { fn } = probe(new Set([1, 3]));
    const res = await settlePool([0, 1, 2, 3, 4], 2, fn);
    expect(res.map((r) => r.status)).toEqual(["fulfilled", "rejected", "fulfilled", "rejected", "fulfilled"]);
    expect((res[3] as PromiseRejectedResult).reason).toEqual(new Error("no 3"));
  });

  it("no items: no calls, empty result", async () => {
    const { state, fn } = probe();
    expect(await settlePool([], 2, fn)).toEqual([]);
    expect(state.started).toEqual([]);
  });
});
