import { describe, expect, it } from "vitest";

import type { TrackingLink, TrackingSummary } from "@/hooks/useGrowth";
import {
  CAME_FROM, INITIAL_VIEW, OPENED_IN, breakdownRows, countryLabel, dayLabel, hasCountries, sparkBars,
  statsRequest, statsViewReducer, summaryCards, verifiedSummary, type Action, type StatsView,
} from "./redirectStats";

const run = (actions: Action[], from: StatsView = INITIAL_VIEW) => actions.reduce(statsViewReducer, from);

describe("statsViewReducer", () => {
  it.each<[string, Action[], StatsView]>([
    ["starts closed at 30 days", [], { openId: null, days: 30 }],
    ["toggle opens", [{ type: "toggle", id: 7 }], { openId: 7, days: 30 }],
    ["toggle again closes", [{ type: "toggle", id: 7 }, { type: "toggle", id: 7 }], { openId: null, days: 30 }],
    ["toggle another switches, days kept", [{ type: "setDays", days: 90 }, { type: "toggle", id: 7 }, { type: "toggle", id: 8 }],
      { openId: 8, days: 90 }],
    ["setDays while open", [{ type: "toggle", id: 7 }, { type: "setDays", days: 7 }], { openId: 7, days: 7 }],
  ])("%s", (_n, actions, want) => {
    expect(run(actions)).toEqual(want);
  });

  it.each<[string, Action]>([
    ["same days", { type: "setDays", days: 30 }],
  ])("a no-op (%s) keeps the same object", (_n, a) => {
    const s = run([{ type: "toggle", id: 7 }]);
    expect(statsViewReducer(s, a)).toBe(s);
  });
});

describe("statsRequest", () => {
  it.each<[StatsView, string | null, number[], ReturnType<typeof statsRequest>]>([
    [{ openId: null, days: 30 }, "a", [7], null],
    [{ openId: 7, days: 90 }, null, [7], null],
    [{ openId: 7, days: 90 }, "a", [7], { linkId: 7, days: 90 }],
    [{ openId: 7, days: 90 }, "a", [8], null],
   ])("%j with %s", (v, aid, ids, want) => {
    expect(statsRequest(v, aid, ids)).toEqual(want);
  });
});

describe("breakdownRows", () => {
  const rows = [
    { key: "", clicks: 50 }, { key: "instagram", clicks: 20 }, { key: "tiktok", clicks: 10 },
    { key: "bot", clicks: 8 }, { key: "facebook", clicks: 6 }, { key: "threads", clicks: 4 }, { key: "zzz", clicks: 2 },
  ];
  it("labels, top 5, rest folded into Other, whole percents", () => {
    expect(breakdownRows(rows, 100, OPENED_IN)).toEqual([
      { key: "", label: "Browser", clicks: 50, pct: 50 },
      { key: "instagram", label: "Instagram app", clicks: 20, pct: 20 },
      { key: "tiktok", label: "TikTok app", clicks: 10, pct: 10 },
      { key: "bot", label: "Bots & link previews", clicks: 8, pct: 8 },
      { key: "facebook", label: "Facebook app", clicks: 6, pct: 6 },
      { key: "__rest", label: "Other", clicks: 6, pct: 6 },
    ]);
  });
  it.each<[string, Parameters<typeof breakdownRows>, string[], number[]]>([
    ["no fold when ≤ top", [[{ key: "x", clicks: 3 }], 3, CAME_FROM], ["X"], [100]],
    ["rest merges into a shown Other", [[{ key: "other", clicks: 4 }, { key: "x", clicks: 3 }, { key: "reddit", clicks: 1 }], 8, CAME_FROM, 2],
      ["Other", "X"], [63, 38]],
    ["unknown key keeps the key", [[{ key: "mastodon", clicks: 1 }], 1, CAME_FROM], ["mastodon"], [100]],
    ["direct", [[{ key: "", clicks: 1 }], 1, CAME_FROM], ["Direct / unknown"], [100]],
    ["zero total → 0%", [[{ key: "x", clicks: 0 }], 0, CAME_FROM], ["X"], [0]],
    ["country labels", [[{ key: "DE", clicks: 1 }, { key: "XX", clicks: 1 }], 2, countryLabel], ["🇩🇪 DE", "Unknown"], [50, 50]],
  ])("%s", (_n, args, labels, pcts) => {
    const out = breakdownRows(...args);
    expect(out.map((r) => r.label)).toEqual(labels);
    expect(out.map((r) => r.pct)).toEqual(pcts);
    expect(out.reduce((a, r) => a + r.clicks, 0)).toBe(args[0].reduce((a, r) => a + r.clicks, 0));
  });
});

describe("small helpers", () => {
  it.each<[Array<{ key: string; clicks: number }>, boolean]>([
    [[], false], [[{ key: "XX", clicks: 9 }], false], [[{ key: "XX", clicks: 9 }, { key: "US", clicks: 1 }], true],
    [[{ key: "US", clicks: 0 }], false],
  ])("hasCountries(%j) = %s", (rows, want) => {
    expect(hasCountries(rows)).toBe(want);
  });

  it.each<[string, string]>([["DE", "🇩🇪 DE"], ["XX", "Unknown"], ["T1", "Unknown"], ["de", "Unknown"]])("countryLabel(%s)", (c, want) => {
    expect(countryLabel(c)).toBe(want);
  });

  it.each<[string, string]>([["2026-11-01", "Nov 1"], ["2026-01-31", "Jan 31"]])("dayLabel(%s)", (d, want) => {
    expect(dayLabel(d)).toBe(want);
  });

  it("sparkBars: 7 slots in 56px, zero a 1px baseline, the max full height, any click ≥ 2px", () => {
    const b = sparkBars([0, 3, 6, 0, 1, 0, 100], 20);
    expect(b).toHaveLength(7);
    expect(b.map((x) => x.h)).toEqual([1, 2, 2, 1, 2, 1, 20]);
    expect(b.map((x) => x.zero)).toEqual([true, false, false, true, false, true, false]);
    expect(b.every((x) => x.y + x.h === 20 && x.w === 6)).toBe(true);
    expect(b[6].x + b[6].w).toBeLessThanOrEqual(56);
    expect(sparkBars([0, 0, 0]).map((x) => x.h)).toEqual([1, 1, 1]);
  });
});

describe("summaryCards", () => {
  const s: TrackingSummary = { tz: null, today: "2026-11-11", clicks: { today: 12, d7: 340, d30: 1210 },
    top: { id: 7, name: "Linktree", clicks: 800 }, spark: {}, verified_clicks: 498 };
  it("shows verified clicks only when gate is available and enabled", () => {
    expect(summaryCards(s, null).map((c) => c.key)).toEqual(["today", "d7", "d30", "top"]);
    expect(summaryCards(s, 498).at(-1)).toMatchObject({ key: "verified", value: "498", sub: "clicks passed the bot check" });
  });
  it.each([
    [false, false, null], [false, true, null], [true, false, null], [true, true, 498],
  ])("availability %s and gate %s yield %s", (available, gated, want) => {
    expect(verifiedSummary(s, [{ bot_check: gated } as TrackingLink], available)).toBe(want);
  });
});
