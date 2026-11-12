import { afterEach, describe, expect, it, vi } from "vitest";

import { metricPath, parseMarkers, readMarker, windowRange } from "./markers";

describe("readMarker", () => {
  it.each([
    ["data", "revenue|today|this", { kind: "data", metric: "revenue", window: "today", scope: "this" }],
    ["data", "per_model|last_month|all", { kind: "data", metric: "per_model", window: "last_month", scope: "all" }],
    ["data", " top_tippers | 7d | all ", { kind: "data", metric: "top_tippers", window: "7d", scope: "all" }],
    ["data", "unread|now|all", { kind: "data", metric: "unread", window: "now", scope: "all" }],
    ["chat", "@lena_99", { kind: "chat", handle: "lena_99" }],
  ])("%s:%s is valid", (kind, body, want) => {
    expect(readMarker(kind, body)).toEqual(want);
  });

  it.each([
    ["data", "online_fans|now|all"], // dropped metric
    ["data", "revenue|forever|this"],
    ["data", "revenue|today|mine"],
    ["data", "revenue|today"],
    ["data", "revenue|today|this|extra"],
    ["data", "unread|today|this"], // unread is live only
    ["data", "revenue|now|this"], // a range metric needs a range
    ["chat", "lena"], // no @
    ["chat", "@"],
    ["chat", "@lena smith"],
  ])("%s:%s is invalid", (kind, body) => {
    expect(readMarker(kind, body)).toBeNull();
  });
});

describe("parseMarkers", () => {
  it.each<[string, string, string, number]>([
    ["no marker: text untouched", "Growth → Auto Post.  Then  save.", "Growth → Auto Post.  Then  save.", 0],
    ["invalid marker dropped silently", "Here you go [[data:online_fans|now|all]].", "Here you go.", 0],
    ["marker kept, text around it clean", "Here is today's revenue: [[data:revenue|today|this]]", "Here is today's revenue:", 1],
    [
      "digits and currency stripped in the marker's sentence",
      "You made $1,234.50 from 12 fans today [[data:revenue|today|this]]. Settings has 3 tabs.",
      "You made from fans today. Settings has 3 tabs.",
      1,
    ],
    ["percent and k stripped", "Up 40% to 1.2k [[data:revenue|7d|all]].", "Up to.", 1],
    ["a window's day count stays", "Over the last 7 days [[data:revenue|7d|this]] you made $900.", "Over the last 7 days you made.", 1],
    ["a handle's digits stay", "Your top fan @fan99 tipped $50 [[data:top_tippers|today|this]].", "Your top fan @fan99 tipped.", 1],
    ["chat marker becomes the handle", "Open [[chat:@lena]] to reply.", "Open @lena to reply.", 1],
    ["figures outside a data sentence stay", "Open [[chat:@lena]], she spent $40.", "Open @lena, she spent $40.", 1],
    ["an invalid data marker's sentence loses its figures too", "You made $999 [[data:revenue|today|bad]]. Settings has 3 tabs.", "You made. Settings has 3 tabs.", 0],
    [
      "a data marker past the cap: its sentence loses its figures too",
      "A [[data:revenue|today|this]]. B [[data:revenue|7d|this]]. C made $999 [[data:revenue|30d|this]].",
      "A. B. C made.",
      2,
    ],
  ])("%s", (_name, input, text, n) => {
    const r = parseMarkers(input);
    expect(r.text).toBe(text);
    expect(r.markers).toHaveLength(n);
  });

  it("keeps only the first 2 valid markers; the rest are dropped (a chat one keeps its handle as text)", () => {
    const r = parseMarkers(
      "[[data:bogus]] A [[data:revenue|today|this]] B [[data:top_spenders|7d|this]] C [[data:per_model|30d|all]] D [[chat:@zed]].",
    );
    expect(r.markers).toEqual([
      { kind: "data", metric: "revenue", window: "today", scope: "this" },
      { kind: "data", metric: "top_spenders", window: "7d", scope: "this" },
    ]);
    expect(r.text).toBe("A B C D @zed.");
  });

  it("leaves a list item's wrap indent alone", () => {
    expect(parseMarkers("- one [[chat:@a]]\n  more").text).toBe("- one @a\n  more");
  });
});

describe("windowRange", () => {
  afterEach(() => vi.useRealTimers());

  it.each<[string, string, string]>([
    ["today", "2026-11-12T00:00:00.000Z", "2026-11-12T23:59:59.999Z"],
    ["yesterday", "2026-11-11T00:00:00.000Z", "2026-11-11T23:59:59.999Z"],
    ["7d", "2026-11-06T00:00:00.000Z", "2026-11-12T23:59:59.999Z"],
    ["30d", "2026-10-14T00:00:00.000Z", "2026-11-12T23:59:59.999Z"],
    ["this_month", "2026-11-01T00:00:00.000Z", "2026-11-30T23:59:59.999Z"],
    ["last_month", "2026-10-01T00:00:00.000Z", "2026-10-31T23:59:59.999Z"],
  ])("%s in UTC", (w, from, to) => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-11-12T15:00:00Z"));
    expect(windowRange(w as Parameters<typeof windowRange>[0], "UTC")).toEqual([from, to]);
  });

  it("last_month across a year end, in the report zone", () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2027-01-05T12:00:00Z"));
    expect(windowRange("last_month", "America/New_York")).toEqual(["2026-12-01T05:00:00.000Z", "2027-01-01T04:59:59.999Z"]);
  });

  it("now has no range", () => {
    expect(windowRange("now", null)).toBeNull();
  });
});

describe("metricPath", () => {
  const range: [string, string] = ["2026-11-12T00:00:00.000Z", "2026-11-12T23:59:59.999Z"];
  it.each<[Parameters<typeof metricPath>[0], string | null, string]>([
    ["revenue", "1001", "/admin/stats/revenue?from=2026-11-12T00%3A00%3A00.000Z&to=2026-11-12T23%3A59%3A59.999Z&account_id=1001&group_by=kind"],
    ["per_model", null, "/admin/stats/per-model?from=2026-11-12T00%3A00%3A00.000Z&to=2026-11-12T23%3A59%3A59.999Z"],
    ["top_spenders", "1001", "/admin/stats/fan-report?from=2026-11-12T00%3A00%3A00.000Z&to=2026-11-12T23%3A59%3A59.999Z&account_id=1001&sort=total&limit=5"],
    ["top_tippers", null, "/admin/top-tippers?from=2026-11-12T00%3A00%3A00.000Z&to=2026-11-12T23%3A59%3A59.999Z&limit=5"],
  ])("%s (account %s)", (metric, account, path) => {
    expect(metricPath(metric, range, account)).toBe(path);
  });
});
