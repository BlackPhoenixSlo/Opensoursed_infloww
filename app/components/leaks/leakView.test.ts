import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import {
  dayLabel, entryNote, headerFacts, LEGEND, nextCheck, pausedLabel, PILL_LABEL, rosterNotes, seenNote, timeline, untrack,
  when, withoutCreator, withSnooze, type Leak, type LeakCounts, type LeakEvent, type LeakRemovalPage, type LeakRoster,
  type LeakRosterRow,
} from "./leakView";

const V1 = join(__dirname, "..", "..", "..", "service", "tests", "fixtures", "leak_tracker_v1");
const golden = (name: string) => JSON.parse(readFileSync(join(V1, `${name}.json`), "utf8")).response;
const DRILL: (Leak & { events: LeakEvent[] })[] = golden("creator_leaks").leaks;

const NOW = new Date("2026-11-27T12:00:00Z");
const UTC = "UTC";
const TOKYO = "Asia/Tokyo";
const LA = "America/Los_Angeles";

const ZERO: LeakCounts = {
  live: 0, cached: 0, gone: 0, listed: 0, not_checked: 0, new_today: 0, found_on_first_scan: 0, came_back_30d: 0,
};
const MIA_COUNTS: LeakCounts = {
  cached: 1, came_back_30d: 1, found_on_first_scan: 3, gone: 0, listed: 1, live: 1, new_today: 1, not_checked: 1,
};
const WEEK = { since: "2026-11-21", state: "complete", new: 1, first_scan: 0, came_back: 0, gone: 0 } as const;
const row = (over: Partial<LeakRosterRow> = {}): LeakRosterRow => ({
  account_id: "acc-a", name: "Creator A", platform: "onlyfans", username: "miavale", display_name: "Mia Vale",
  on: true, synced: true, reachable: true, seeded: true, paused: false, paused_since: null,
  last_checked_at: "2026-11-27T04:05:00Z", next_check_at: "2026-11-28T04:00:00Z", counts: MIA_COUNTS, this_week: WEEK, ...over,
});

describe("when", () => {
  it.each([
    ["the same day", "2026-11-27T06:12:00Z", UTC, "Today 06:12"],
    ["the day before", "2026-11-26T23:50:00Z", UTC, "Yesterday 23:50"],
    ["older", "2026-11-20T09:00:00Z", UTC, "20 Nov 09:00"],
    ["another year", "2025-12-31T09:00:00Z", UTC, "31 Dec 2025 09:00"],
    ["in the viewer's zone, past midnight there", "2026-11-26T21:12:00Z", TOKYO, "Today 06:12"],
    ["in the viewer's zone, still yesterday there", "2026-11-27T04:05:00Z", LA, "Yesterday 20:05"],
    ["unparsable", "yesterday-ish", UTC, null],
    ["empty", "", UTC, null],
  ])("%s", (_label, iso, tz, want) => {
    expect(when(iso, NOW, tz)).toBe(want);
  });
});

describe("nextCheck", () => {
  it.each([
    ["early next morning", "2026-11-28T04:00:00Z", UTC, "Next check tonight"],
    ["this evening", "2026-11-28T04:00:00Z", LA, "Next check tonight"],
    ["later today in daylight", "2026-11-28T04:00:00Z", TOKYO, "Next check tomorrow 13:00"],
    ["later today", "2026-11-27T15:00:00Z", UTC, "Next check today 15:00"],
    ["tomorrow afternoon", "2026-11-28T13:00:00Z", UTC, "Next check tomorrow 13:00"],
    ["further out", "2026-11-30T04:00:00Z", UTC, "Next check 30 Nov 04:00"],
    ["unparsable", "2026-13-45T99:00:00Z", UTC, null],
  ])("%s", (_label, iso, tz, want) => {
    expect(nextCheck(iso, NOW, tz)).toBe(want);
  });
});

describe("dayLabel", () => {
  it.each([
    ["2026-11-20T09:00:00Z", UTC, "20 Nov"],
    ["2026-11-20T23:30:00Z", TOKYO, "21 Nov"],
    ["2025-11-20T09:00:00Z", UTC, "20 Nov 2025"],
    ["not a date", UTC, null],
  ])("%s in %s", (iso, tz, want) => {
    expect(dayLabel(iso, NOW, tz)).toBe(want);
  });
});

describe("pausedLabel", () => {
  it.each<[string, Partial<LeakRosterRow>, string | null]>([
    ["on and not paused", {}, null],
    ["switched off, the service not told yet", { on: false }, "Paused"],
    ["switched off and paused by the service", { on: false, paused: true, paused_since: "2026-11-20T09:00:00Z" }, "Paused since 20 Nov"],
    ["on but paused by the flag or a deactivated Creator", { paused: true, paused_since: "2026-11-20T09:00:00Z" }, "Paused since 20 Nov"],
    ["paused since an unparsable time", { paused: true, paused_since: "not a date" }, "Paused"],
  ])("%s", (_label, over, want) => {
    expect(pausedLabel(row(over), NOW, UTC)).toBe(want);
  });
});

describe("entryNote", () => {
  it.each<[string, Partial<LeakRosterRow>, string]>([
    ["Leaks up now and new this week", {}, "1 up now · 1 new this week"],
    ["the week's read finds more", { this_week: { ...WEEK, new: 2 } }, "1 up now · 2 new this week"],
    ["the week's read finds none new", { this_week: { ...WEEK, new: 0, first_scan: 3 } }, "1 up now"],
    ["no week read: counts.new_today is not a fallback", { this_week: null }, "1 up now"],
    ["only first-scan Leaks", { this_week: null, counts: { ...ZERO, live: 2, listed: 1, found_on_first_scan: 3 } }, "Found on first scan · 3"],
    ["a seed that found nothing", { this_week: { ...WEEK, new: 0 }, counts: ZERO, last_checked_at: null }, "Found on first scan · 0"],
    ["not seeded yet", { seeded: false, counts: ZERO, last_checked_at: null }, "Not checked yet"],
    ["unknown to the service yet", { seeded: false, counts: null, last_checked_at: null, next_check_at: null }, "Not checked yet"],
    ["paused by the service", { paused: true, paused_since: "2026-11-20T09:00:00Z" }, "Paused since 20 Nov"],
    ["switched off locally", { on: false, paused: false, paused_since: null }, "Paused"],
    ["paused since an unparsable time", { paused: true, paused_since: "not a date" }, "Paused"],
    ["service not reachable", { reachable: false, seeded: false, counts: null }, "Not reachable"],
  ])("%s", (_label, over, want) => {
    expect(entryNote(row(over), NOW, UTC)).toBe(want);
  });
});

describe("rosterNotes", () => {
  const roster = (over: Partial<LeakRoster> = {}): LeakRoster => ({
    rows: [row(), row({ account_id: "acc-c", seeded: false, counts: null, last_checked_at: null })],
    untracked: [{ account_id: "acc-b", name: "Creator B" }],
    stale: false,
    fetched_at: "2026-11-27T11:00:00Z",
    ...over,
  });

  it("one line per Creator, untracked ones Not tracked", () => {
    expect(rosterNotes(roster(), NOW, UTC)).toEqual({
      "acc-a": "1 up now · 1 new this week", "acc-c": "Not checked yet", "acc-b": "Not tracked",
    });
  });

  it("a stale copy adds each row's last checked time, never fetched_at", () => {
    expect(rosterNotes(roster({ stale: true }), NOW, UTC)).toEqual({
      "acc-a": "1 up now · 1 new this week · last checked Today 04:05", "acc-c": "Not checked yet", "acc-b": "Not tracked",
    });
  });

  it("an unparsable last checked time drops the suffix instead of crashing", () => {
    const rows = [row({ last_checked_at: "garbage" })];
    expect(rosterNotes(roster({ stale: true, rows }), NOW, UTC)).toEqual({
      "acc-a": "1 up now · 1 new this week", "acc-b": "Not tracked",
    });
  });
});

describe("untrack", () => {
  const roster: LeakRoster = {
    rows: [row(), row({ account_id: "acc-c", name: "Creator C" })],
    untracked: [{ account_id: "acc-b", name: "Creator B" }],
    stale: true,
    fetched_at: "2026-11-27T11:00:00Z",
  };

  it.each([
    ["acc-a", ["acc-c"], ["acc-b", "acc-a"]],
    ["acc-c", ["acc-a"], ["acc-b", "acc-c"]],
    ["acc-b", ["acc-a", "acc-c"], ["acc-b"]],
    ["acc-x", ["acc-a", "acc-c"], ["acc-b"]],
  ])("deleting %s", (id, rows, untracked) => {
    const out = untrack(roster, id);
    expect(out.rows.map((r) => r.account_id)).toEqual(rows);
    expect(out.untracked.map((u) => u.account_id)).toEqual(untracked);
    expect([out.stale, out.fetched_at]).toEqual([true, "2026-11-27T11:00:00Z"]);
  });

  it("keeps the row's name and reads Not tracked", () => {
    const out = untrack(roster, "acc-a");
    expect(out.untracked.at(-1)).toEqual({ account_id: "acc-a", name: "Creator A" });
    expect(rosterNotes(out, NOW, UTC)["acc-a"]).toBe("Not tracked");
  });
});

describe("withoutCreator", () => {
  const leak = (account_id: string) => ({ ...DRILL[0], account_id });
  const page = { leaks: [leak("acc-a"), leak("acc-b"), leak("acc-a")], next_cursor: "c2", stale: false };

  it.each([
    ["acc-a", ["acc-b"]],
    ["acc-b", ["acc-a", "acc-a"]],
    ["acc-x", ["acc-a", "acc-b", "acc-a"]],
  ])("drops %s's Leaks only", (id, left) => {
    const out = withoutCreator(page, id);
    expect(out.leaks?.map((l) => l.account_id)).toEqual(left);
    expect(out.next_cursor).toBe("c2");
  });

  it("an unreachable page stays as it is", () => {
    const down = { leaks: null, next_cursor: null, stale: false };
    expect(withoutCreator(down, "acc-a")).toBe(down);
  });
});

describe("withSnooze", () => {
  const page: LeakRemovalPage = {
    leaks: [], next_cursor: "c2", stale: false,
    removal: { status: "none", view: "offer", notices_updated_at: null, stale: false, counts: null, offer_snoozed_until: null },
    offer: { brand: "Example Removal", contact_url: "https://removal.example/contact", angle: "clean", n: 0 },
  };
  const until = "2026-12-04T12:00:00Z";

  it.each([
    ["with an offer", page, { ...page, removal: { ...page.removal!, offer_snoozed_until: until }, offer: null }],
    ["without an offer", { ...page, offer: null }, { ...page, offer: null }],
    ["without removal", { ...page, removal: null }, { ...page, removal: null }],
  ] as const)("%s", (_label, before, after) => {
    expect(withSnooze(before, until)).toEqual(after);
  });
});

describe("PILL_LABEL and LEGEND", () => {
  it("names every pill and the legend explains each, Cached and Listed included", () => {
    expect(PILL_LABEL).toEqual({ live: "Live", cached: "Cached", gone: "Gone", listed: "Listed", not_checked: "Not checked yet" });
    expect(LEGEND.map(([p]) => p)).toEqual(["live", "cached", "gone", "listed", "not_checked"]);
    expect(Object.fromEntries(LEGEND)).toMatchObject({
      cached: "Gone from the site, but Google still shows it.",
      listed: "A Mega, Telegram or file-host link: listed, never opened.",
    });
  });
});

describe("seenNote", () => {
  const [, fresh, folder] = DRILL;
  it.each<[string, Leak, string, string]>([
    ["a seeded Leak reads Found on first scan, never new", folder, "2026-11-20T12:00:00Z", "Found on first scan · 20 Nov"],
    ["seeded today is still not new", { ...folder, first_seen_at: "2026-11-27T04:02:00Z" }, NOW.toISOString(), "Found on first scan · 27 Nov"],
    ["first seen on today's UTC day", fresh, NOW.toISOString(), "New today"],
    ["first seen on an earlier day", fresh, "2026-11-29T12:00:00Z", "First seen 27 Nov"],
  ])("%s", (_label, leak, now, want) => {
    expect(seenNote(leak, new Date(now), UTC)).toBe(want);
  });

  it("New today follows the UTC day, not the viewer's", () => {
    expect(seenNote({ ...fresh, first_seen_at: "2026-11-26T23:30:00Z" }, NOW, TOKYO)).toBe("First seen 27 Nov");
  });
});

describe("timeline", () => {
  it.each<[string, number, string[]]>([
    ["a media Leak found in Google Images", 0, ["27 Nov Found via Google Images"]],
    ["a fresh Leak", 1, ["27 Nov Found via Google"]],
    ["a seeded folder", 2, ["20 Nov Found on first scan"]],
    ["a Leak that came back keeps the last four", 3, ["20 Nov Found on first scan", "21 Nov Up", "23 Nov Gone", "25 Nov Came back"]],
    ["a Leak that went down", 4, ["20 Nov Found on first scan", "21 Nov Up", "26 Nov Gone"]],
  ])("%s", (_label, i, want) => {
    expect(timeline(DRILL[i].events, NOW, UTC)).toEqual(want);
  });

  it("skips event types it does not know and a Google sighting on its own day reads Seen in Google", () => {
    expect(timeline([
      { at: "2026-11-20T09:05:00Z", type: "seen", data: { first_scan: false, source: "mega_index" } },
      { at: "2026-11-22T09:05:00Z", type: "google_seen", data: {} },
      { at: "2026-11-23T09:05:00Z", type: "notice", data: {} },
      { at: "2026-11-24T09:05:00Z", type: "status", data: { from: "live", to: "blocked" } },
    ], NOW, UTC)).toEqual(["20 Nov Found via the Mega index", "22 Nov Seen in Google"]);
  });

  it.each<[string, Record<string, unknown>, string[]]>([
    ["visible", { visible: true }, ["22 Nov Seen in Google"]],
    ["not visible", { visible: false }, ["22 Nov Not seen in Google"]],
    ["unknown", { visible: null }, []],
  ])("a Google sighting %s", (_label, data, want) => {
    expect(timeline([{ at: "2026-11-22T09:05:00Z", type: "google_seen", data }], NOW, UTC)).toEqual(want);
  });
});

describe("headerFacts", () => {
  it.each<[string, Partial<LeakRosterRow>, ReturnType<typeof headerFacts>]>([
    ["counts, tracking on, last checked", {}, {
      counts: [["Up now", "1", "1 cached"], ["Gone", "0", null], ["Listed", "1", null], ["New this week", "1", null]],
      tracking: "Tracking on", checked: "Last checked Today 04:05",
    }],
    ["no cached Leak", { counts: { ...MIA_COUNTS, cached: 0 } }, {
      counts: [["Up now", "1", null], ["Gone", "0", null], ["Listed", "1", null], ["New this week", "1", null]],
      tracking: "Tracking on", checked: "Last checked Today 04:05",
    }],
    ["paused, never checked", { paused: true, paused_since: "2026-11-20T09:00:00Z", last_checked_at: null }, {
      counts: [["Up now", "1", "1 cached"], ["Gone", "0", null], ["Listed", "1", null], ["New this week", "1", null]],
      tracking: "Paused since 20 Nov", checked: "Next check tonight",
    }],
    ["New this week from the week's read", { this_week: { ...WEEK, new: 4 } }, {
      counts: [["Up now", "1", "1 cached"], ["Gone", "0", null], ["Listed", "1", null], ["New this week", "4", null]],
      tracking: "Tracking on", checked: "Last checked Today 04:05",
    }],
    ["no week read hides New this week", { this_week: null }, {
      counts: [["Up now", "1", "1 cached"], ["Gone", "0", null], ["Listed", "1", null]],
      tracking: "Tracking on", checked: "Last checked Today 04:05",
    }],
    ["not seeded yet", { seeded: false, counts: null, last_checked_at: null, next_check_at: null }, {
      counts: null, tracking: "Tracking on", checked: "Not checked yet",
    }],
    ["not reachable", { reachable: false, seeded: false, counts: null, last_checked_at: null }, {
      counts: null, tracking: "Tracking on", checked: "Not reachable",
    }],
  ])("%s", (_label, over, want) => {
    expect(headerFacts(row(over), NOW, UTC)).toEqual(want);
  });
});
