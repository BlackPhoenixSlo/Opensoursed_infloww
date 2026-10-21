/** `calcMinutes`, Infloww's Clocked hours format (bundle `calcMinutes$1` @11228512; "0min" seen live, w5-a), and the
 *  Shift schedule's Agency-zone week (`zonedWeek`, page-parity ticket 18). */
import { describe, expect, it } from "vitest";

import {
  calcMinutes, employeeColours, fmtShiftTime, gmtOffset, weekRangeLabel, zonedWeek, type ShiftOccurrence,
} from "@/lib/shifts";

describe("calcMinutes", () => {
  it.each([
    [0, "0min"], [45, "45min"], [60, "1h"], [125, "2h 5min"], [450, "7h 30min"], [74_040, "1,234h"], [74_041, "1,234h 1min"],
  ])("%d minutes reads %j", (m, text) => {
    expect(calcMinutes(m)).toBe(text);
  });
});

describe("zonedWeek", () => {
  // Wed 21 Oct 2026 12:00 in Ljubljana (CEST); Sunday 25 Oct falls back at 03:00.
  const NOW = new Date("2026-10-21T10:00:00Z");
  const iso = (d: Date) => d.toISOString();

  it("cuts the fall-back week at Ljubljana midnights, one day 25 hours long", () => {
    const { days } = zonedWeek(NOW, "monday", "Europe/Ljubljana", 0);
    expect(days).toHaveLength(7);
    expect(days.map((d) => `${d.ddd} ${d.dd}`)).toEqual(["Mon 19", "Tue 20", "Wed 21", "Thu 22", "Fri 23", "Sat 24", "Sun 25"]);
    expect(iso(days[0].start)).toBe("2026-10-18T22:00:00.000Z");
    expect(iso(days[6].start)).toBe("2026-10-24T22:00:00.000Z");
    expect(iso(days[6].end)).toBe("2026-10-25T23:00:00.000Z");
    const hours = days.map((d) => (d.end.getTime() - d.start.getTime()) / 3_600_000);
    expect(hours).toEqual([24, 24, 24, 24, 24, 24, 25]);
    expect(days.map((d) => d.today)).toEqual([false, false, true, false, false, false, false]);
    expect(days.every((d, i) => i === 0 || d.start.getTime() === days[i - 1].end.getTime())).toBe(true);
    expect(weekRangeLabel(days)).toBe("19 Oct – 25 Oct 2026");
  });

  it("starts on Sunday for a Sunday-start Agency", () => {
    const { days } = zonedWeek(NOW, "sunday", "Europe/Ljubljana", 0);
    expect(days[0]).toMatchObject({ date: "2026-10-18", ddd: "Sun" });
    expect(iso(days[0].start)).toBe("2026-10-17T22:00:00.000Z");
    expect(days[6].date).toBe("2026-10-24");
  });

  it("steps whole weeks either way, and nothing is today away from this week", () => {
    const back = zonedWeek(NOW, "monday", "Europe/Ljubljana", -1).days;
    expect(back[0].date).toBe("2026-10-12");
    expect(iso(back[0].start)).toBe("2026-10-11T22:00:00.000Z");
    const next = zonedWeek(NOW, "monday", "Europe/Ljubljana", 1).days;
    expect(next[0].date).toBe("2026-10-26");
    expect(iso(next[0].start)).toBe("2026-10-25T23:00:00.000Z");
    expect([...back, ...next].some((d) => d.today)).toBe(false);
  });

  it("reads today in the zone, not in UTC", () => {
    // 23:30Z on Sunday 18 Oct is already Monday 19 Oct in Ljubljana.
    const { days } = zonedWeek(new Date("2026-10-18T23:30:00Z"), "monday", "Europe/Ljubljana", 0);
    expect(days[0]).toMatchObject({ date: "2026-10-19", today: true });
  });
});

describe("Shift tile helpers", () => {
  it("prints times as h:mm A and offsets as GMT±hh:mm in the zone", () => {
    expect(fmtShiftTime("2026-10-13T13:00:00Z", "America/New_York")).toBe("9:00 AM");
    expect(fmtShiftTime("2026-10-13T21:05:00Z", "America/New_York")).toBe("5:05 PM");
    expect(fmtShiftTime("2026-10-13T04:00:00Z", "America/New_York")).toBe("12:00 AM");
    expect(gmtOffset("2026-10-15T08:00:00Z", "Europe/Ljubljana")).toBe("GMT+02:00");
    expect(gmtOffset("2026-11-15T08:00:00Z", "America/New_York")).toBe("GMT-05:00");
    expect(gmtOffset("2026-11-15T08:00:00Z", "Asia/Kolkata")).toBe("GMT+05:30");
  });

  it("hands out Infloww's Employee colours in first-seen order", () => {
    const occ = (ids: number[]) => ({ employees: ids.map((id) => ({ id, display_name: String(id) })) }) as ShiftOccurrence;
    const colour = employeeColours([occ([42]), occ([41, 42]), occ([7])]);
    expect([colour(42), colour(41), colour(7)]).toEqual(["#FF7875", "#FFC069", "#D3F261"]);
  });
});
