/** `clockAction`, the clock button's choice behind `useClock().act`, and the DST edges of the Relay's `_to_utc`
 *  rule as `fromZonedInput` and `zonedWeek` apply it: a gap time lands after the jump, an overlap time takes its
 *  first (summer-time) instant, and a DST week is 167 or 169 hours. */
import { describe, expect, it } from "vitest";

import type { ClockStatus } from "@/lib/shifts";
import { clockAction, fromZonedInput, zonedWeek } from "@/lib/shiftsTime";

const OPEN = {
  clock_event_id: 7, employee_id: 1, account_id: null, shift_id: null,
  in_utc: "2026-10-31T08:00:00Z", out_utc: null, close_reason: null,
} as const;

const status = (open: boolean, picks: boolean): ClockStatus => ({
  can_clock: true,
  reason: picks ? "pick_creator" : null,
  open: open ? OPEN : null,
  last_closed: null,
  auto_clock_out_minutes: 30,
  server_now: "2026-10-31T09:00:00Z",
});

describe("clockAction", () => {
  const OUT = { kind: "out", clockEventId: 7 };
  const PICK = { kind: "pick" };
  const IN = { kind: "in" };

  it.each([
    // open,  only,      picks, action
    [true, undefined, false, OUT],
    [true, undefined, true, OUT],
    [true, "in", false, IN],
    [true, "in", true, PICK],
    [false, undefined, false, IN],
    [false, undefined, true, PICK],
    [false, "in", false, IN],
    [false, "in", true, PICK],
  ] as const)("open %s, only %s, picks %s → %o", (open, only, picks, action) => {
    expect(clockAction(status(open, picks), only)).toEqual(action);
  });

  it.each([[undefined], ["in"]] as const)("no cached status, only %s → in", (only) => {
    expect(clockAction(undefined, only)).toEqual(IN);
  });
});

describe("fromZonedInput across DST", () => {
  it.each([
    // Ljubljana springs forward 02:00 CET → 03:00 CEST on 29 Mar 2026.
    ["Europe/Ljubljana", "2026-03-29T01:59", "2026-03-29T00:59:00.000Z"],
    ["Europe/Ljubljana", "2026-03-29T03:00", "2026-03-29T01:00:00.000Z"],
    // Ljubljana falls back 03:00 CEST → 02:00 CET on 25 Oct 2026.
    ["Europe/Ljubljana", "2026-10-25T01:59", "2026-10-24T23:59:00.000Z"],
    ["Europe/Ljubljana", "2026-10-25T03:00", "2026-10-25T02:00:00.000Z"],
    // New York springs forward 02:00 EST → 03:00 EDT on 8 Mar 2026.
    ["America/New_York", "2026-03-08T01:59", "2026-03-08T06:59:00.000Z"],
    ["America/New_York", "2026-03-08T03:00", "2026-03-08T07:00:00.000Z"],
    // New York falls back 02:00 EDT → 01:00 EST on 1 Nov 2026.
    ["America/New_York", "2026-11-01T00:59", "2026-11-01T04:59:00.000Z"],
    ["America/New_York", "2026-11-01T02:00", "2026-11-01T07:00:00.000Z"],
  ])("%s %s outside the change → %s", (tz, value, iso) => {
    expect(fromZonedInput(value, tz)).toBe(iso);
  });

  it.each([
    ["Europe/Ljubljana", "2026-03-29T02:00", "2026-03-29T01:00:00.000Z"],
    ["Europe/Ljubljana", "2026-03-29T02:30", "2026-03-29T01:30:00.000Z"],
    ["America/New_York", "2026-03-08T02:00", "2026-03-08T07:00:00.000Z"],
    ["America/New_York", "2026-03-08T02:30", "2026-03-08T07:30:00.000Z"],
  ])("%s %s in the spring-forward gap keeps the winter offset, landing after the jump → %s", (tz, value, iso) => {
    expect(fromZonedInput(value, tz)).toBe(iso);
  });

  it.each([
    ["Europe/Ljubljana", "2026-10-25T02:00", "2026-10-25T00:00:00.000Z"],
    ["Europe/Ljubljana", "2026-10-25T02:30", "2026-10-25T00:30:00.000Z"],
    ["America/New_York", "2026-11-01T01:00", "2026-11-01T05:00:00.000Z"],
    ["America/New_York", "2026-11-01T01:30", "2026-11-01T05:30:00.000Z"],
  ])("%s %s in the fall-back overlap takes its first (summer-time) instant → %s", (tz, value, iso) => {
    expect(fromZonedInput(value, tz)).toBe(iso);
  });

  it.each([
    ["2026-03-29T02:30", "2026-03-29T02:30:00.000Z"],
    ["2026-10-25T02:30", "2026-10-25T02:30:00.000Z"],
    ["2026-03-08T02:30", "2026-03-08T02:30:00.000Z"],
    ["2026-11-01T01:30", "2026-11-01T01:30:00.000Z"],
  ])("UTC control: %s reads as itself", (value, iso) => {
    expect(fromZonedInput(value, "UTC")).toBe(iso);
  });
});

describe("zonedWeek across DST", () => {
  const hours = (a: Date, b: Date) => (b.getTime() - a.getTime()) / 3_600_000;

  it.each([
    // tz, now (mid-week), first-day midnight (UTC), the DST date, its hours, week hours
    ["Europe/Ljubljana", "2026-03-25T12:00:00Z", "2026-03-22T23:00:00.000Z", "2026-03-29", 23, 167],
    ["Europe/Ljubljana", "2026-10-21T10:00:00Z", "2026-10-18T22:00:00.000Z", "2026-10-25", 25, 169],
    ["America/New_York", "2026-03-04T17:00:00Z", "2026-03-02T05:00:00.000Z", "2026-03-08", 23, 167],
    ["America/New_York", "2026-10-28T16:00:00Z", "2026-10-26T04:00:00.000Z", "2026-11-01", 25, 169],
    // UTC: control, no change
    ["UTC", "2026-03-25T12:00:00Z", "2026-03-23T00:00:00.000Z", "2026-03-29", 24, 168],
  ] as const)("%s Monday week of %s starts %s; %s is %dh, the week %dh", (tz, now, first, dstDate, dstHours, weekHours) => {
    const { days } = zonedWeek(new Date(now), "monday", tz, 0);
    expect(days).toHaveLength(7);
    expect(days.map((d) => d.ddd)).toEqual(["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]);
    expect(days[0].start.toISOString()).toBe(first);
    for (let i = 1; i < 7; i++) expect(days[i].start).toEqual(days[i - 1].end);
    expect(days.map((d) => hours(d.start, d.end))).toEqual(
      days.map((d) => (d.date === dstDate ? dstHours : 24)),
    );
    expect(days[6].date).toBe(dstDate);
    expect(hours(days[0].start, days[6].end)).toBe(weekHours);
  });

  it.each([
    ["Europe/Ljubljana", "2026-03-30T12:00:00Z", "2026-03-28T23:00:00.000Z", 167],
    ["America/New_York", "2026-11-04T16:00:00Z", "2026-11-01T04:00:00.000Z", 169],
  ] as const)("%s Sunday week of %s starts on the DST Sunday %s, %dh long", (tz, now, first, weekHours) => {
    const { days } = zonedWeek(new Date(now), "sunday", tz, 0);
    expect(days).toHaveLength(7);
    expect(days[0].ddd).toBe("Sun");
    expect(days[0].start.toISOString()).toBe(first);
    expect(hours(days[0].start, days[6].end)).toBe(weekHours);
  });
});
