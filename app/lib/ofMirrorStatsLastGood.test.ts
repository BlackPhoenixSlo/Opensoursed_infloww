import { beforeEach, describe, expect, it } from "vitest";
import { clearIdentityMemory } from "@/contexts/UserContext";
import { forgetAll, lastGoodKey, recall, remember, selectionOf, shownFor } from "./ofMirrorStatsLastGood";

beforeEach(() => forgetAll());

describe("lastGoodKey", () => {
  it.each([
    ["a1", "30d", "/api/of/v2/users/me/stats/overview?by=story&start=2026-10-19&end=2026-11-18", "a1|30d|/api/of/v2/users/me/stats/overview?by=story"],
    ["a1", "30d", "/api/of/v2/users/me/stats/overview?end=2026-11-19&by=story&start=2026-10-20", "a1|30d|/api/of/v2/users/me/stats/overview?by=story"],
    ["a1", "7d", "/api/of/v2/payouts/transactions?startDate=x&limit=10&endDate=y", "a1|7d|/api/of/v2/payouts/transactions?limit=10"],
    ["a1", "7d", "/api/of/v2/streaks/top", "a1|7d|/api/of/v2/streaks/top?"],
    [null, "7d", "/x", null],
    ["a1", "7d", null, null],
  ])("%s %s %s", (acct, period, route, want) => expect(lastGoodKey(acct, period, route)).toBe(want));

  it("keeps Creators, periods and picks apart", () => {
    const k = (a: string, p: string, by: string) => lastGoodKey(a, p, `/r?by=${by}&start=1&end=2`);
    expect(new Set([k("a", "30d", "tips"), k("b", "30d", "tips"), k("a", "7d", "tips"), k("a", "30d", "views")]).size).toBe(4);
  });

  it("Statements' first page: its clock-made marker does not move the key; a later page's marker does", () => {
    const first = (m: number) => lastGoodKey("a", "d30", `/api/of/v2/payouts/transactions?limit=10&startDate=2026-10-23+00%3A00%3A00&marker=${m}`);
    expect(first(1763800000)).toBe(first(1763800060));
    const later = (m: number) => lastGoodKey("a", "d30", `/api/of/v2/payouts/transactions?limit=10&offset=10&marker=${m}`);
    expect(later(1)).not.toBe(later(2));
  });

  it("Activity Streak: the calendar month it reads is part of the key (October's failed read never recalls November)", () => {
    const streaks = (start: string, end: string) => lastGoodKey("a", "d30", `/api/of/v2/streaks?${new URLSearchParams({ start, end })}`);
    expect(streaks("2026-10-01 00:00:00", "2026-10-31 23:59:59")).not.toBe(streaks("2026-11-01 00:00:00", "2026-11-22 08:00:00"));
    expect(streaks("2026-11-01 00:00:00", "2026-11-22 08:00:00")).toBe(streaks("2026-11-01 00:00:00", "2026-11-22 08:05:00"));
  });
});

describe("selectionOf", () => {
  it.each([
    ["this month in October vs November: different selections", { key: "m0", startApi: "2026-10-01 00:00:00" }, { key: "m0", startApi: "2026-11-01 00:00:00" }, false],
    ["this month, same month: one selection", { key: "m0", startApi: "2026-11-01 00:00:00" }, { key: "m0", startApi: "2026-11-01 00:00:00" }, true],
    ["a rolling window stays its key", { key: "d30", startApi: "2026-10-01 00:00:00" }, { key: "d30", startApi: "2026-10-02 00:00:00" }, true],
  ] as const)("%s", (_n, a, b, same) => expect(selectionOf(a) === selectionOf(b)).toBe(same));
});

describe("shownFor", () => {
  const key = "a|30d|/r?";
  it.each([
    ["a good read: its data, no mark, remembered", { data: { n: 1 }, failed: false, at: 10 }, undefined, { data: { n: 1 }, asOf: null }, { data: { n: 1 }, at: 10 }],
    ["still loading: nothing, nothing remembered", { data: undefined, failed: false, at: 0 }, undefined, { data: undefined, asOf: null }, undefined],
    ["a failed re-read keeps its own data", { data: { n: 2 }, failed: true, at: 20 }, { data: { n: 1 }, at: 10 }, { data: { n: 2 }, asOf: 20 }, { data: { n: 1 }, at: 10 }],
    ["a failed first read: the last good answer", { data: undefined, failed: true, at: 0 }, { data: { n: 1 }, at: 10 }, { data: { n: 1 }, asOf: 10 }, { data: { n: 1 }, at: 10 }],
    ["never a good read: blank", { data: undefined, failed: true, at: 0 }, undefined, { data: undefined, asOf: null }, undefined],
  ])("%s", (_name, r, before, want, after) => {
    if (before) remember(key, before.data, before.at);
    expect(shownFor(key, r)).toEqual(want);
    expect(recall(key)).toEqual(after);
  });

  it("a refused read (401/403/404: permanent) never shows a remembered answer", () => {
    remember(key, { n: 1 }, 10);
    expect(shownFor(key, { data: undefined, failed: true, at: 0, permanent: true })).toEqual({ data: undefined, asOf: null });
  });

  it("a refused re-read (403 after a good read) shows no figures, neither its own data nor the remembered ones", () => {
    shownFor(key, { data: { n: 1 }, failed: false, at: 10 });
    expect(shownFor(key, { data: { n: 1 }, failed: true, at: 10, permanent: true })).toEqual({ data: undefined, asOf: null });
  });

  it("an identity switch (clearIdentityMemory) forgets every remembered answer", () => {
    remember(key, { n: 1 }, 10);
    clearIdentityMemory();
    expect(recall(key)).toBeUndefined();
  });

  it("a failed read never overwrites the last good answer", () => {
    shownFor(key, { data: 1, failed: false, at: 5 });
    shownFor(key, { data: undefined, failed: true, at: 0 });
    expect(recall(key)).toEqual({ data: 1, at: 5 });
  });

  it("drops the oldest past its cap", () => {
    for (let i = 0; i < 401; i++) remember(`k${i}`, i, i);
    expect(recall("k0")).toBeUndefined();
    expect(recall("k400")).toEqual({ data: 400, at: 400 });
  });
});
