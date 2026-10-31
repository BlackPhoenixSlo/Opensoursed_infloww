import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { PerModelRow } from "@/hooks/useStats";

import {
  type ColCtx, type RevResp, DEFAULT_RANGE, STAT_COLS, cellCsv, creatorDayRows, creatorRows, datePresets, daysFrom,
  grossOf, netMissingNote, netOf, rollUp, sumKinds, viewOf,
} from "./reportsMath";

const col = (key: string) => STAT_COLS.find((c) => c.key === key)!;
const gross: ColCtx = { hours: 24, agencyCents: 10_000, net: false };
const netCtx: ColCtx = { ...gross, net: true };

describe("rollUp", () => {
  it.each([
    ["day, month boundary", ["2026-01-31", "2026-02-01"], [1, 2], "day",
      [{ label: "Jan 31", value: 1 }, { label: "Feb 1", value: 2 }]],
    ["day, year boundary", ["2026-12-31", "2027-01-01"], [3, 4], "day",
      [{ label: "Dec 31", value: 3 }, { label: "Jan 1", value: 4 }]],
    ["week, seven days from the first, month boundary",
      ["2026-01-28", "2026-01-29", "2026-01-30", "2026-01-31", "2026-02-01", "2026-02-02", "2026-02-03", "2026-02-04"],
      [1, 1, 1, 1, 1, 1, 1, 5], "week",
      [{ label: "Jan 28", value: 7 }, { label: "Feb 4", value: 5 }]],
    ["week, year boundary", daysFrom("2026-12-26", "2027-01-02"), [1, 2, 3, 4, 5, 6, 7, 8], "week",
      [{ label: "Dec 26", value: 28 }, { label: "Jan 2", value: 8 }]],
    ["month, month boundary", ["2026-01-30", "2026-01-31", "2026-02-01"], [1, 2, 3], "month",
      [{ label: "Jan 26", value: 3 }, { label: "Feb 26", value: 3 }]],
    ["month, year boundary", ["2026-12-31", "2027-01-01", "2027-01-02"], [5, 1, 1], "month",
      [{ label: "Dec 26", value: 5 }, { label: "Jan 27", value: 2 }]],
    ["missing values count 0", ["2026-01-01", "2026-01-02"], [7], "day",
      [{ label: "Jan 1", value: 7 }, { label: "Jan 2", value: 0 }]],
  ] as const)("%s", (_name, days, values, p, want) => {
    expect(rollUp([...days], [...values], p)).toEqual(want);
  });
});

describe("daysFrom", () => {
  it.each([
    ["from unset", null, "2026-01-02", []],
    ["to unset", "2026-01-01", null, []],
    ["both unset", null, null, []],
    ["inverted range", "2026-01-05", "2026-01-01", []],
    ["one day", "2026-03-01", "2026-03-01", ["2026-03-01"]],
    ["year boundary", "2026-12-30", "2027-01-02", ["2026-12-30", "2026-12-31", "2027-01-01", "2027-01-02"]],
    ["leap day", "2028-02-28", "2028-03-01", ["2028-02-28", "2028-02-29", "2028-03-01"]],
  ] as const)("%s", (_name, from, to, want) => {
    expect(daysFrom(from, to)).toEqual(want);
  });
});

describe("sumKinds", () => {
  const qs: { data?: RevResp }[] = [
    { data: { rows: [
      { day: null, kind: "subscription", total_cents: 1000, count: 1, net_cents: 800 },
      { day: null, kind: "rebill", total_cents: 500, count: 1, net_cents: 400 },
      // No net from OnlyFans yet: counts 0 in net.
      { day: null, kind: "tip", total_cents: 300, count: 1, net_cents: null as unknown as number },
      { day: null, kind: "ppv_post", total_cents: 200, count: 1 },
    ] } },
    { data: { rows: [{ day: null, kind: "referral", total_cents: 50, count: 1, net_cents: 40 }, { day: null, kind: null, total_cents: 7, count: 1, net_cents: 5 }] } },
    {},
  ];
  it.each([
    ["gross", grossOf, { subscriptions: 1500, tips: 300, posts: 200, messages: 0, streams: 0, referrals: 50, other: 7 }],
    ["net (net_cents null or absent → 0)", netOf, { subscriptions: 1200, tips: 0, posts: 0, messages: 0, streams: 0, referrals: 40, other: 5 }],
  ] as const)("%s", (_name, money, want) => {
    expect(sumKinds(qs, money)).toEqual(want);
  });
});

describe("cellCsv", () => {
  const m = {
    account_id: "a1", display_name: 'Ann, "the" Best', total_revenue_cents: 123_456, total_net_revenue_cents: 98_765,
    revenue_by_kind: { tip: 1999, subscription: 1000, ppv: 500 }, avg_reply_seconds: 185, messages_sent: 1234,
  } as unknown as PerModelRow;
  it.each([
    ["usd total in dollars, two decimals", "totalEarnings", gross, 1234.56],
    ["usd total, net read", "totalEarnings", netCtx, 987.65],
    ["usd with no net read while net is on → empty", "tips", netCtx, ""],
    ["usd per kind, gross", "tips", gross, 19.99],
    ["pct rounded to two decimals", "engagementEarningsRatio", gross, 249.9],
    ["dur as text", "replyTime", gross, "3m 05s"],
    ["int as a number", "messagesSent", gross, 1234],
    ["no relay field → empty", "ofRanking", gross, ""],
  ] as const)("%s", (_name, key, ctx, want) => {
    expect(cellCsv(col(key), m, ctx)).toEqual(want);
  });
  it("leaves quoting to the writer: a name with commas and quotes stays verbatim", () => {
    expect(creatorRows([col("totalEarnings")], [m], gross)).toEqual([
      ["Creator", "Total earnings"],
      ['Ann, "the" Best', 1234.56],
    ]);
  });
});

describe("netMissingNote", () => {
  it.each([
    [1, "Net", "1 sale in this period has no net figure from OnlyFans yet, so Net leaves it out."],
    [3, "Net", "3 sales in this period have no net figure from OnlyFans yet, so Net leaves them out."],
    [1, "net earnings", "1 sale in this period has no net figure from OnlyFans yet, so net earnings leave it out."],
    [3, "net earnings", "3 sales in this period have no net figure from OnlyFans yet, so net earnings leave them out."],
  ] as const)("%i %s", (n, noun, want) => {
    expect(netMissingNote(n, noun)).toBe(want);
  });
});

describe("creatorDayRows", () => {
  const ann = { account_id: "a1", display_name: "Ann" } as unknown as PerModelRow;
  const bob = { account_id: "b2", display_name: "" } as unknown as PerModelRow;
  const reads: Record<string, RevResp> = {
    a1: { rows: [{ day: "2026-01-01", kind: null, total_cents: 1500, count: 2, net_cents: 1200, by_kind: [
      { kind: "subscription", total_cents: 1000, count: 1, net_cents: 800 },
      { kind: "ppv", total_cents: 500, count: 1, net_cents: 400 },
    ] }] },
    b2: { rows: [] },
  };
  const read = (id: string) => Promise.resolve(reads[id]);
  const header = ["Creator", "Day", "Total earnings", "Subscription", "Tips", "Posts", "Messages", "Streams"];
  it.each([
    ["gross", false, [
      header,
      ["Ann", "2026-01-01", 15, 10, 0, 0, 5, 0],
      ["Ann", "2026-01-02", 0, 0, 0, 0, 0, 0],
      ["b2", "2026-01-01", 0, 0, 0, 0, 0, 0],
      ["b2", "2026-01-02", 0, 0, 0, 0, 0, 0],
    ]],
    ["net", true, [
      header,
      ["Ann", "2026-01-01", 12, 8, 0, 0, 4, 0],
      ["Ann", "2026-01-02", 0, 0, 0, 0, 0, 0],
      ["b2", "2026-01-01", 0, 0, 0, 0, 0, 0],
      ["b2", "2026-01-02", 0, 0, 0, 0, 0, 0],
    ]],
  ] as const)("%s: header order (no Referrals), a row per Creator per day", async (_name, net, want) => {
    expect(await creatorDayRows([ann, bob], ["2026-01-01", "2026-01-02"], net, read)).toEqual(want);
  });
});

describe("datePresets", () => {
  beforeEach(() => { vi.useFakeTimers(); vi.setSystemTime(new Date("2026-03-15T12:00:00Z")); });
  afterEach(() => { vi.useRealTimers(); });
  it("the bundle's presets in order, Last N days through today, the five months before whole", () => {
    expect(datePresets("UTC")).toEqual([
      { key: "custom", label: "Custom", days: ["2026-03-09", "2026-03-15"] },
      { key: "last7", label: "Last 7 days", days: ["2026-03-09", "2026-03-15"] },
      { key: "last30", label: "Last 30 days", days: ["2026-02-14", "2026-03-15"] },
      { key: "last90", label: "Last 90 days", days: ["2025-12-16", "2026-03-15"] },
      { key: "last365", label: "Last 365 days", days: ["2025-03-16", "2026-03-15"] },
      { key: "year", label: "2026", days: ["2026-01-01", "2026-03-15"] },
      { key: "month", label: "March", days: ["2026-03-01", "2026-03-15"] },
      { key: "month-1", label: "February", days: ["2026-02-01", "2026-02-28"] },
      { key: "month-2", label: "January", days: ["2026-01-01", "2026-01-31"] },
      { key: "month-3", label: "December", days: ["2025-12-01", "2025-12-31"] },
      { key: "month-4", label: "November", days: ["2025-11-01", "2025-11-30"] },
      { key: "month-5", label: "October", days: ["2025-10-01", "2025-10-31"] },
    ]);
  });
  it("DEFAULT_RANGE is Last 7 days", () => {
    expect(datePresets("UTC").find((p) => p.key === DEFAULT_RANGE)?.label).toBe("Last 7 days");
  });
});

describe("viewOf", () => {
  const ok = { isError: false, isPending: false };
  const pending = { isError: false, isPending: true };
  const failed = { isError: true, isPending: false };
  it.each([
    ["no reads, rows", [], true, "ready"],
    ["no reads, no rows", [], false, "empty"],
    ["all answered, rows", [ok, ok], true, "ready"],
    ["all answered, no rows", [ok, ok], false, "empty"],
    ["one pending", [ok, pending], true, "loading"],
    ["pending beats empty", [pending], false, "loading"],
    ["an error beats a pending read before it", [pending, failed], true, "error"],
    ["an error beats empty", [failed], false, "error"],
  ] as const)("%s", (_name, reads, hasRows, want) => {
    expect(viewOf(reads, hasRows)).toBe(want);
  });
});
