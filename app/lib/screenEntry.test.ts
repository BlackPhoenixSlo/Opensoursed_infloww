import { afterEach, describe, expect, it, vi } from "vitest";

import { DEFAULT_PERIOD } from "@/components/home/dashboardControls";
import { periodWindow, type Period } from "./dateRange";
import { bootScreen, cookieValue, rememberDashboardEntry, rememberScope, type DashboardEntry } from "./screenEntry";
import type { Screen } from "./screenKey";

const TOKYO: DashboardEntry = { tz: "Asia/Tokyo", weekStart: "sunday", grid: true };
const ZONE = Intl.DateTimeFormat().resolvedOptions().timeZone;
/** The cookies' decoded values (the Next jar's, `cookieValue`'s): the saved entry, the browser's zone, the scope bit. */
const jar = (c: { entry?: DashboardEntry | string; tz?: string; scope?: string } = {}) => (n: string) => ({
  chatterly_entry: typeof c.entry === "string" ? c.entry : c.entry && JSON.stringify(c.entry),
  chatterly_tz: c.tz,
  chatterly_scope: c.scope,
})[n];
/** The Dashboard bundle's screen for `period` in `tz` / `weekStart`. */
const dashAt = (period: Period, tz: string | null, weekStart: DashboardEntry["weekStart"]): Screen => {
  const [from, to] = periodWindow(period, tz, weekStart);
  return { kind: "dashboard", from, to };
};

describe("bootScreen: which screen a route opens", () => {
  afterEach(() => vi.useRealTimers());

  it.each<[string, string, DashboardEntry, Screen | null]>([
    ["Messages Pro: the inbox bundle's first page", "/messages-pro", TOKYO, { kind: "inbox", cursor: 0 }],
    ["another page: none", "/creators", TOKYO, null],
    ["a Messages Pro sub-route: none", "/messages-pro/x", TOKYO, null],
    ["Dashboard, cards hidden: none", "/", { ...TOKYO, grid: false }, null],
  ])("%s", (_n, path, hint, want) => {
    expect(bootScreen(path, jar({ entry: hint, tz: ZONE }))).toEqual(want);
  });

  it("Dashboard: the saved zone and week start, the URL's window (an unknown one: the default)", () => {
    vi.useFakeTimers({ now: new Date("2026-11-06T12:00:00Z") });
    expect(bootScreen("/?window=month", jar({ entry: TOKYO }))).toEqual(dashAt("month", "Asia/Tokyo", "sunday"));
    const week = dashAt(DEFAULT_PERIOD, "Asia/Tokyo", "sunday");
    expect(bootScreen("/?window=decade", jar({ entry: TOKYO }))).toEqual(week);
    expect(week).not.toEqual(dashAt(DEFAULT_PERIOD, null, "monday"));
  });
});

describe("bootScreen: the one guess, from the cookies", () => {
  afterEach(() => vi.useRealTimers());

  it("Messages Pro needs no cookie; another page: none", () => {
    expect(bootScreen("/messages-pro", jar())).toEqual({ kind: "inbox", cursor: 0 });
    expect(bootScreen("/messages-pro", jar({ scope: "all" }))).toEqual({ kind: "inbox", cursor: 0 });
    expect(bootScreen("/creators", jar({ entry: TOKYO, tz: ZONE }))).toBeNull();
  });

  it("Dashboard: the saved entry's zone wins, else the browser's (Monday); neither: no guess", () => {
    vi.useFakeTimers({ now: new Date("2026-11-06T12:00:00Z") });
    expect(bootScreen("/?window=month", jar({ entry: TOKYO, tz: "Europe/Ljubljana" }))).toEqual(dashAt("month", "Asia/Tokyo", "sunday"));
    expect(bootScreen("/", jar({ tz: ZONE }))).toEqual(dashAt(DEFAULT_PERIOD, ZONE, "monday"));
    expect(bootScreen("/", jar({ entry: "{oops", tz: "Asia/Tokyo" }))).toEqual(dashAt(DEFAULT_PERIOD, "Asia/Tokyo", "monday"));
    expect(bootScreen("/", jar())).toBeNull();
  });

  it("Messages Pro with one Creator saved in scope: no inbox bundle (the page opens none)", () => {
    expect(bootScreen("/messages-pro", jar({ tz: ZONE, scope: "model" }))).toBeNull();
  });

  it("a zone Intl does not know (a junk cookie): null, never a throw", () => {
    expect(() => bootScreen("/", jar({ tz: "Not/AZone" }))).not.toThrow();
    expect(bootScreen("/", jar({ tz: "Not/AZone" }))).toBeNull();
    expect(bootScreen("/", jar({ entry: { ...TOKYO, tz: "Not/AZone" }, tz: ZONE }))).toBeNull();
  });
});

describe("the cookies as the browser writes and AuthGate reads them (cookieValue: decoded, as Next's jar)", () => {
  afterEach(() => {
    for (const n of ["chatterly_entry", "chatterly_scope", "chatterly_x"]) document.cookie = `${n}=; path=/; max-age=0`;
  });
  const read = (n: string) => cookieValue(document.cookie, n);

  it("the dashboard entry round-trips (the same JSON)", () => {
    expect(read("chatterly_entry")).toBeUndefined();
    rememberDashboardEntry(TOKYO);
    expect(bootScreen("/", read)).toEqual(dashAt(DEFAULT_PERIOD, "Asia/Tokyo", "sunday"));
    rememberDashboardEntry({ ...TOKYO, grid: false });
    expect(bootScreen("/", read)).toBeNull();
  });

  it("the scope is one bit: model or all", () => {
    rememberScope(true);
    expect(read("chatterly_scope")).toBe("model");
    expect(bootScreen("/messages-pro", read)).toBeNull();
    rememberScope(false);
    expect(read("chatterly_scope")).toBe("all");
    expect(bootScreen("/messages-pro", read)).toEqual({ kind: "inbox", cursor: 0 });
  });

  it("an undecodable value: none (as Next's jar drops it)", () => {
    document.cookie = "chatterly_x=%E0%A4%A; path=/";
    expect(read("chatterly_x")).toBeUndefined();
  });
});
