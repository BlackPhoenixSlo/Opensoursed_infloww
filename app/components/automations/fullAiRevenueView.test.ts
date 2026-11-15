import { describe, expect, it } from "vitest";

import { FLOOR_LINE, NO_HOLDOUT, revenueView, type FullAiRevenueApi, type RevenueArmApi } from "./fullAiRevenueView";

const arm = (fans: number, complete: number, cents: number): RevenueArmApi => ({
  fans, complete, in_window: fans - complete, cents, cents_per_fan: complete ? Math.round(cents / complete) : null,
});
const api = (over: Partial<FullAiRevenueApi>): FullAiRevenueApi => ({
  live_since: "2026-11-01T10:00:00Z", note: NO_HOLDOUT, arms: { all: arm(3, 2, 2468) }, routes: [], ...over,
});

describe("revenueView", () => {
  it("not live: nothing but the flag", () => {
    expect(revenueView(api({ live_since: null, arms: {}, routes: [] }))).toEqual({ live: false });
  });

  it.each<[string, FullAiRevenueApi, { perFan: string[]; honesty: string | null; delta: string | null }]>([
    ["live, nobody complete: mean is —, not $0", api({ arms: { all: arm(4, 0, 0) } }),
      { perFan: ["—"], honesty: NO_HOLDOUT, delta: null }],
    ["one Arm: the no-holdout line", api({}), { perFan: ["$12.34"], honesty: NO_HOLDOUT, delta: null }],
    ["two Arms under the floor: both means + floor line, no delta",
      api({ note: FLOOR_LINE, arms: { holdout: arm(100, 90, 90 * 500), treatment: arm(400, 479, 479 * 1234) } }),
      { perFan: ["$12.34", "$5"], honesty: FLOOR_LINE, delta: null }],
    ["two Arms, one at the floor one under: still no delta",
      api({ note: FLOOR_LINE, arms: { treatment: arm(600, 480, 480 * 1000), holdout: arm(500, 479, 479 * 500) } }),
      { perFan: ["$10", "$5"], honesty: FLOOR_LINE, delta: null }],
    ["two Arms over the floor: delta shown",
      api({ note: FLOOR_LINE, arms: { treatment: arm(600, 500, 500 * 1234), holdout: arm(600, 480, 480 * 1000) } }),
      { perFan: ["$12.34", "$10"], honesty: null, delta: "Full AI − Holdout: +$2.34 per Fan (14 days)" }],
  ])("%s", (_n, input, want) => {
    const v = revenueView(input);
    if (!v.live) throw new Error("expected live");
    expect({ perFan: v.arms.map((a) => a.perFan), honesty: v.honesty, delta: v.delta }).toEqual(want);
  });

  it("arm row: since date, fans, complete, in window", () => {
    const v = revenueView(api({}));
    if (!v.live) throw new Error("expected live");
    expect(v.since).toBe("2026-11-01");
    expect(v.arms).toEqual([{ arm: "all", label: "Enrolled Fans", fans: 3, complete: 2, inWindow: 1, perFan: "$12.34" }]);
  });

  it("routes: 0 offers hidden, rate and cents → $", () => {
    const v = revenueView(api({ routes: [
      { route: "sell_now", offers: 4, bought: 1, cents: 1234 },
      { route: "tease", offers: 0, bought: 0, cents: 0 },
      { route: "make_right", offers: 3, bought: 0, cents: 0 },
    ] }));
    if (!v.live) throw new Error("expected live");
    expect(v.routes).toEqual([
      { route: "sell_now", label: "Sell now", offers: 4, bought: 1, rate: "25%", money: "$12.34" },
      { route: "make_right", label: "Make right", offers: 3, bought: 0, rate: "0%", money: "$0" },
    ]);
  });
});
