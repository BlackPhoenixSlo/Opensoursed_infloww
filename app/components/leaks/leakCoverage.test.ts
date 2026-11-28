import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import {
  DAY_MARKER_LABEL, dayMarker, FRESHNESS, LANE_ORDER, laneRows, rosterChips, skippedNames, weekLine, weekStrip,
  type DayState, type LaneName, type LeakLane, type LeakWeek, type WeekStrip,
} from "./leakCoverage";

const V1 = join(__dirname, "..", "..", "..", "service", "tests", "fixtures", "leak_tracker_v1");
const golden = (name: string) => JSON.parse(readFileSync(join(V1, `${name}.json`), "utf8")).response;
const GOLDEN: LeakLane[] = golden("creator_one").lanes;
const ROSTER: { this_week: LeakWeek; paused: boolean }[] = golden("creators").creators;

const NOW = new Date("2026-11-27T12:00:00Z");
const lane = (over: Partial<LeakLane> = {}): LeakLane => ({
  lane: "google_full", cadence: "weekly", state: "ok", reason: null, last_success_at: "2026-11-27T09:00:00Z",
  last_attempt_at: "2026-11-27T09:00:00Z", next_attempt_on: "2026-12-04", trimmed: [], ...over,
});
const one = (l: LeakLane) => laneRows([l], NOW).find((r) => r.lane === l.lane)!;
const TRIMMED = [{ field: "alias:2", value: "Mia V" }, { field: "alias:0", value: "miavale.x" },
  { field: "x", value: "miavale" }, { field: "instagram", value: "mia.vale" }];

describe("laneRows", () => {
  it("lists all five weekly lanes in order with their labels, filling a missing one as Not run yet", () => {
    const rows = laneRows([lane({ lane: "mega_lookup", cadence: "daily" })], NOW);
    expect(rows.map((r) => [r.lane, r.label])).toEqual([
      ["origin_probe", "Link check"], ["mega_lookup", "Mega"], ["listing_recheck", "Leak-site pages"],
      ["google_full", "Google full search"], ["registry_crawl", "Leak-site search"],
    ]);
    expect(rows.filter((r) => r.lane !== "mega_lookup").every((r) => r.chip === "Not run yet")).toBe(true);
  });

  it("reads the service golden", () => {
    expect(laneRows(GOLDEN, NOW).map(({ label, chip, lastOk, next, note }) => [label, chip, lastOk, next, note])).toEqual([
      ["Link check", "OK", "last OK 8 h ago", "next attempt Sat 28 Nov", null],
      ["Mega", "Failed", "last OK 1 d ago", "next attempt Sat 28 Nov", null],
      ["Leak-site pages", "Not run yet", null, null, null],
      ["Google full search", "Not run yet", null, null, null],
      ["Leak-site search", "Not run yet", null, null, null],
    ]);
  });

  it.each<[string, Partial<LeakLane>, string, string | null]>([
    ["ok", {}, "OK", null],
    ["ok with a stray reason", { reason: "cap_global" }, "OK", null],
    ["failed", { state: "failed", reason: "lane_failed" }, "Failed", null],
    ["failed, Google", { state: "failed", reason: "google_failed" }, "Failed", "Google didn't load; no other search engine is used"],
    ["reduced, Google failed", { state: "reduced", reason: "google_failed" }, "Reduced", "Google didn't load; no other search engine is used"],
    ["reduced, listings rotated", { lane: "listing_recheck", state: "reduced", reason: "listing_rotated" }, "Reduced",
      "Too many pages to re-read in one day, so each is re-read every few days"],
    ["reduced, global cap", { state: "reduced", reason: "cap_global" }, "Reduced", "The removal service's daily search limit is used up"],
    ["reduced, month cap", { state: "reduced", reason: "cap_tenant_month" }, "Reduced", "Your agency's monthly search allowance is used up"],
    ["reduced, judge cap", { state: "reduced", reason: "judge_cap" }, "Reduced", "The daily limit for checking results is used up"],
    ["reduced, no reason", { state: "reduced" }, "Reduced", null],
    ["waiting, global cap", { state: "waiting", reason: "cap_global" }, "Waiting on budget", "The removal service's daily search limit is used up"],
    ["waiting, month cap", { state: "waiting", reason: "cap_tenant_month" }, "Waiting on budget", "Your agency's monthly search allowance is used up"],
    ["waiting, judge cap", { state: "waiting", reason: "judge_cap" }, "Waiting on budget", "The daily limit for checking results is used up"],
    ["waiting, Creator cap", { state: "waiting", reason: "creator_cap" }, "Waiting on budget", "Your agency's Creator limit is reached"],
    ["waiting, crawl unfinished", { lane: "registry_crawl", state: "waiting", reason: "lane_failed" }, "Waiting",
      "Not finished; it carries on the next day"],
    ["waiting, an unknown reason", { state: "waiting", reason: "no_browserbase_key" }, "Waiting", null],
    ["never", { state: "never", last_success_at: null, next_attempt_on: null }, "Not run yet", null],
    ["paused", { state: "paused", reason: null, next_attempt_on: null }, "Paused", null],
  ])("%s", (_label, over, chip, note) => {
    const r = one(lane(over));
    expect([r.chip, r.note, r.tone]).toEqual([chip, note, over.state ?? "ok"]);
  });

  it.each<[string, Partial<LeakLane>, string | null, string | null]>([
    ["minutes", { last_success_at: "2026-11-27T11:15:00Z" }, "last OK 45 min ago", "next attempt Fri 4 Dec"],
    ["just now", { last_success_at: "2026-11-27T12:00:00Z" }, "last OK just now", "next attempt Fri 4 Dec"],
    ["days", { last_success_at: "2026-11-20T12:00:00Z", next_attempt_on: "2026-12-01" }, "last OK 7 d ago", "next attempt Tue 1 Dec"],
    ["next year", { next_attempt_on: "2027-01-01" }, "last OK 3 h ago", "next attempt Fri 1 Jan 2027"],
    ["never ran OK", { state: "failed", last_success_at: null }, null, "next attempt Fri 4 Dec"],
    ["paused keeps its last success, no next attempt", { state: "paused", next_attempt_on: "2026-11-28" }, "last OK 3 h ago", null],
    ["never has no last OK", { state: "never" }, null, "next attempt Fri 4 Dec"],
    ["an unreadable date", { last_success_at: "soon", next_attempt_on: "next week" }, null, null],
  ])("last OK and next attempt: %s", (_label, over, lastOk, next) => {
    const r = one(lane(over));
    expect([r.lastOk, r.next]).toEqual([lastOk, next]);
  });

  it.each<[string, Partial<LeakLane>, string[]]>([
    ["trimmed aliases and socials in drop order", { state: "reduced", reason: "cap_global", trimmed: TRIMMED },
      ["Mia V", "miavale.x", "X", "Instagram"]],
    ["only Instagram", { state: "reduced", reason: "cap_tenant_month", trimmed: [TRIMMED[3]] }, ["Instagram"]],
    ["nothing trimmed", { state: "reduced", reason: "google_failed" }, []],
    ["paused keeps the last skip", { state: "paused", trimmed: [TRIMMED[1]] }, ["miavale.x"]],
    ["never has none", { state: "never", trimmed: TRIMMED }, []],
  ])("skipped: %s", (_label, over, skipped) => {
    expect(one(lane(over)).skipped).toEqual(skipped);
  });

  it("no row text says next full search", () => {
    const states: Partial<LeakLane>[] = [{}, { state: "waiting", reason: "cap_global" }, { state: "reduced", reason: "cap_global", trimmed: TRIMMED },
      { state: "failed", reason: "lane_failed" }, { state: "never" }, { state: "paused" }, { state: "waiting", reason: "lane_failed" }];
    for (const over of states) {
      for (const name of LANE_ORDER) {
        const text = JSON.stringify(one(lane({ ...over, lane: name as LaneName })));
        expect(text.toLowerCase()).not.toContain("next full search");
      }
    }
  });
});

describe("skippedNames", () => {
  it("names aliases by value and socials by network", () => {
    expect(skippedNames(TRIMMED)).toEqual(["Mia V", "miavale.x", "X", "Instagram"]);
  });
});

describe("FRESHNESS", () => {
  it("states the promise and never says next full search", () => {
    expect(FRESHNESS).toBe("Each Creator is checked once a week on its scan day, and again when an Owner or Admin presses Refresh now "
      + "(at most once a day). Images, videos and new sites show after the next check.");
    expect(FRESHNESS.toLowerCase()).not.toContain("next full search");
  });
});

const day = (over: Partial<LeakWeek> = {}): LeakWeek => ({
  since: "2026-11-21", state: "complete", new: 0, first_scan: 0, came_back: 0, gone: 0, ...over,
});
const watch = (week: LeakWeek | null, over: { paused?: boolean; on?: boolean } = {}) =>
  ({ this_week: week, paused: false, on: true, ...over });
const strip = (over: Partial<WeekStrip> = {}): WeekStrip =>
  ({ new: 0, cameBack: 0, gone: 0, firstRun: 0, checked: 0, partial: 0, total: 0, ...over });

describe("weekStrip", () => {
  it("reads the service golden: a paused watch is outside the total", () => {
    expect(weekStrip(ROSTER.map((c) => watch(c.this_week, { paused: c.paused })))).toEqual(strip({ new: 1, cameBack: 1, gone: 2, checked: 1, total: 1 }));
  });

  it.each<[string, ReturnType<typeof watch>[], WeekStrip | null]>([
    ["nothing tracked", [], null],
    ["no watch carries a week yet", [watch(null), watch(null, { paused: true })], null],
    ["sums the week's counts", [watch(day({ new: 2, came_back: 1, gone: 3 })), watch(day({ new: 1, gone: 1 }))],
      strip({ new: 3, cameBack: 1, gone: 4, checked: 2, total: 2 })],
    ["first-run finds count apart from new", [watch(day({ first_scan: 12 })), watch(day({ new: 1, first_scan: 2 }))],
      strip({ new: 1, firstRun: 14, checked: 2, total: 2 })],
    ["a first-run watch still checking", [watch(day({ state: "pending", first_scan: 5 })), watch(day())],
      strip({ firstRun: 5, checked: 1, total: 2 })],
    ["pending watches are counted but not checked", [watch(day({ state: "pending" })), watch(day({ state: "pending" }))],
      strip({ total: 2 })],
    ["partial and reduced days are partial", [watch(day({ state: "partial", new: 1 })), watch(day({ state: "coverage_reduced" })),
      watch(day())], strip({ new: 1, checked: 1, partial: 2, total: 3 })],
    ["paused by the service, by the flag or switched off stay outside the total",
      [watch(day({ state: "paused" })), watch(day(), { paused: true }), watch(null, { on: false }), watch(day())],
      strip({ checked: 1, total: 1 })],
    ["a watch with no day read yet is counted but not checked", [watch(null), watch(day())], strip({ checked: 1, total: 2 })],
    ["a paused watch's counts still add to the sums", [watch(day({ state: "paused", new: 2, gone: 1, first_scan: 4 })),
      watch(day({ new: 1 }), { paused: true }), watch(day({ came_back: 1 }), { on: false }), watch(day())],
      strip({ new: 3, cameBack: 1, gone: 1, firstRun: 4, checked: 1, total: 1 })],
  ])("%s", (_label, watches, want) => {
    expect(weekStrip(watches)).toEqual(want);
  });
});

describe("weekLine", () => {
  it.each<[string, WeekStrip, string]>([
    ["a quiet week", strip({ checked: 3, total: 3 }), "0 new this week · 0 came back · 0 gone · checked 3 of 3"],
    ["the week's change", strip({ new: 2, cameBack: 1, gone: 4, checked: 2, total: 3 }),
      "2 new this week · 1 came back · 4 gone · checked 2 of 3"],
    ["partial when non-zero", strip({ checked: 1, partial: 2, total: 3 }), "0 new this week · 0 came back · 0 gone · checked 1 of 3 · 2 partial"],
    ["first scans when non-zero", strip({ new: 1, firstRun: 14, checked: 2, total: 2 }),
      "1 new this week · 0 came back · 0 gone · checked 2 of 2 · 14 found on first scans"],
    ["both", strip({ firstRun: 5, partial: 1, total: 2 }),
      "0 new this week · 0 came back · 0 gone · checked 0 of 2 · 1 partial · 5 found on first scans"],
  ])("%s", (_label, s, want) => {
    expect(weekLine(s)).toBe(want);
  });
});

describe("dayMarker", () => {
  it.each<[string, LeakWeek | null, string | null]>([
    ["complete", day(), null],
    ["partial", day({ state: "partial" }), "Partial check"],
    ["coverage_reduced", day({ state: "coverage_reduced" }), "Reduced"],
    ["pending", day({ state: "pending" }), "Checking…"],
    ["paused", day({ state: "paused" }), "Paused"],
    ["no week read", null, null],
  ])("%s", (_label, week, label) => {
    const m = dayMarker(week);
    expect(m && DAY_MARKER_LABEL[m]).toBe(label);
  });

  it("covers every day state", () => {
    const states: DayState[] = ["pending", "complete", "partial", "coverage_reduced", "paused"];
    expect(states.map((state) => dayMarker(day({ state })))).toEqual(["pending", null, "partial", "reduced", "paused"]);
  });
});

describe("rosterChips", () => {
  it("maps each row with a day marker to its chip and leaves the rest out", () => {
    expect(rosterChips([
      { account_id: "acc-a", this_week: day() },
      { account_id: "acc-b", this_week: null },
      { account_id: "acc-c", this_week: day({ state: "paused" }) },
      { account_id: "acc-d", this_week: day({ state: "partial" }) },
      { account_id: "acc-e", this_week: day({ state: "pending" }) },
      { account_id: "acc-f", this_week: day({ state: "coverage_reduced" }) },
    ])).toEqual({ "acc-c": "Paused", "acc-d": "Partial check", "acc-e": "Checking…", "acc-f": "Reduced" });
    expect(rosterChips([])).toEqual({});
  });
});
