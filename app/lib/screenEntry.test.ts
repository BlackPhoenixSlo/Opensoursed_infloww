import { afterEach, describe, expect, it, vi } from "vitest";

import { periodWindow } from "./dateRange";
import { ENTRY_COOKIE, entryScreen, parseDashboardEntry, readDashboardEntry, rememberDashboardEntry, type DashboardEntry } from "./screenEntry";

const TOKYO: DashboardEntry = { tz: "Asia/Tokyo", weekStart: "sunday", grid: true };

describe("entryScreen", () => {
  afterEach(() => vi.useRealTimers());

  it.each<[string, string, string, DashboardEntry | null, ReturnType<typeof entryScreen> | "dash"]>([
    ["Messages Pro: the inbox bundle", "/messages-pro", "", null, { kind: "inbox" }],
    ["another page: none", "/creators", "", TOKYO, null],
    ["a Messages Pro sub-route: none", "/messages-pro/x", "", null, null],
    ["Dashboard, nothing saved: browser zone, Monday, this week", "/", "", null, "dash"],
    ["Dashboard, cards hidden: none", "/", "", { ...TOKYO, grid: false }, null],
  ])("%s", (_n, path, search, hint, want) => {
    const got = entryScreen(path, search, hint);
    if (want === "dash") {
      const [from, to] = periodWindow("week", null, "monday");
      expect(got).toEqual({ kind: "dashboard", from, to });
    } else expect(got).toEqual(want);
  });

  it("Dashboard: the saved zone and week start, the URL's window (an unknown one: the default)", () => {
    vi.useFakeTimers({ now: new Date("2026-11-06T12:00:00Z") });
    const [from, to] = periodWindow("month", "Asia/Tokyo", "sunday");
    expect(entryScreen("/", "?window=month", TOKYO)).toEqual({ kind: "dashboard", from, to });
    const [wf, wt] = periodWindow("week", "Asia/Tokyo", "sunday");
    expect(entryScreen("/", "?window=decade", TOKYO)).toEqual({ kind: "dashboard", from: wf, to: wt });
    expect(wf).not.toBe(periodWindow("week", null, "monday")[0]);
  });
});

describe("dashboard entry storage", () => {
  afterEach(() => window.localStorage.clear());

  it("round trip; junk or nothing: null", () => {
    expect(readDashboardEntry()).toBeNull();
    rememberDashboardEntry(TOKYO);
    expect(readDashboardEntry()).toEqual(TOKYO);
    window.localStorage.setItem("chatterly:dashboard-entry", "{oops");
    expect(readDashboardEntry()).toBeNull();
    window.localStorage.setItem("chatterly:dashboard-entry", JSON.stringify({ tz: 3, weekStart: "friday" }));
    expect(readDashboardEntry()).toBeNull();
  });

  it("the saved entry's copy for the server (lib/inlineBoot.server.ts): a cookie, the same JSON", () => {
    rememberDashboardEntry(TOKYO);
    const raw = document.cookie.split("; ").find((c) => c.startsWith(`${ENTRY_COOKIE}=`))!.slice(ENTRY_COOKIE.length + 1);
    expect(parseDashboardEntry(decodeURIComponent(raw))).toEqual(TOKYO);
  });
});
