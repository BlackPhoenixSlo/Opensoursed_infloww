/**
 * lib/dateRange — the reports' hour-precision ranges (roadmap W5 5.4): `toLocalIso` reads YYYY-MM-DDTHH:00 as that
 * wall-clock hour in the report time zone, and `priorRange` gives the window of equal length before, on the wall
 * clock, for the change against the previous period; `presetRange` gives exactly N calendar days through today, and
 * `dateBounds` a real day on Feb 29.
 */
import { afterEach, describe, expect, it, vi } from "vitest";

import { PRESET_DAYS, dateBounds, presetRange, priorRange, shiftYears, toLocalIso } from "@/lib/dateRange";

describe("presetRange", () => {
  afterEach(() => vi.useRealTimers());

  it("covers exactly N calendar days, today included", () => {
    vi.useFakeTimers({ now: new Date("2026-10-20T12:00:00Z") });
    expect(presetRange("day", "UTC")).toEqual(["2026-10-20", "2026-10-20"]);
    expect(presetRange("7d", "UTC")).toEqual(["2026-10-14", "2026-10-20"]);
    expect(presetRange("30d", "UTC")).toEqual(["2026-09-21", "2026-10-20"]);
    expect(presetRange("90d", "UTC")).toEqual(["2026-07-23", "2026-10-20"]);
    expect(presetRange("365d", "UTC")).toEqual(["2025-10-21", "2026-10-20"]);
    for (const p of ["day", "7d", "30d", "90d", "365d"] as const) {
      const [from, to] = presetRange(p, "UTC");
      expect((Date.parse(to) - Date.parse(from)) / 86_400_000 + 1).toBe(PRESET_DAYS[p]);
    }
  });
});

describe("dateBounds", () => {
  afterEach(() => vi.useRealTimers());

  it("runs a year back to two days ahead", () => {
    vi.useFakeTimers({ now: new Date("2026-10-20T12:00:00Z") });
    expect(dateBounds("UTC")).toEqual(["2025-10-20", "2026-10-22"]);
  });

  it("gives a real day on Feb 29", () => {
    vi.useFakeTimers({ now: new Date("2028-02-29T12:00:00Z") });
    expect(dateBounds("UTC")).toEqual(["2027-03-01", "2028-03-02"]);
    expect(shiftYears("2028-02-29", 1)).toBe("2029-03-01");
    expect(shiftYears("2027-03-01", 1)).toBe("2028-03-01");
  });
});

describe("toLocalIso at hour precision", () => {
  it("places the hour in a zone half an hour off UTC", () => {
    // Asia/Kolkata is UTC+5:30: 3 PM is 09:30Z; the 9 AM hour ends 1 ms before 10 AM, 04:30Z.
    expect(toLocalIso("2026-10-01T15:00", false, "Asia/Kolkata")).toBe("2026-10-01T09:30:00.000Z");
    expect(toLocalIso("2026-10-01T09:00", true, "Asia/Kolkata")).toBe("2026-10-01T04:29:59.999Z");
  });

  it("starts the hour a daylight-saving end repeats at its first run and ends it after its second", () => {
    // New York, Sun 1 Nov 2026: 2 AM EDT (06:00Z) goes back to 1 AM EST, so 1 AM runs 05:00Z to 07:00Z.
    expect(toLocalIso("2026-11-01T01:00", false, "America/New_York")).toBe("2026-11-01T05:00:00.000Z");
    expect(toLocalIso("2026-11-01T01:00", true, "America/New_York")).toBe("2026-11-01T06:59:59.999Z");
    expect(toLocalIso("2026-11-01T02:00", false, "America/New_York")).toBe("2026-11-01T07:00:00.000Z");
  });

  it("still passes an instant through", () => {
    expect(toLocalIso("2026-10-01T09:30:00.000Z", false, "Asia/Kolkata")).toBe("2026-10-01T09:30:00.000Z");
  });
});

describe("priorRange", () => {
  it("gives whole days for whole days, placed per day across a daylight-saving end", () => {
    expect(priorRange("2026-10-08", "2026-10-14")).toEqual(["2026-10-01", "2026-10-07"]);
    const [f, t] = priorRange("2026-11-01", "2026-11-07")!;
    expect([f, t]).toEqual(["2026-10-25", "2026-10-31"]);
    // Sun 25 Oct 00:00 EDT through Sat 31 Oct 23:59:59.999 EDT.
    expect([toLocalIso(f, false, "America/New_York"), toLocalIso(t, true, "America/New_York")])
      .toEqual(["2026-10-25T04:00:00.000Z", "2026-11-01T03:59:59.999Z"]);
  });

  it("keeps the wall-clock hours of an hour-precision range", () => {
    // Tue 13 Oct 3 PM through Wed 14 Oct 9 AM is 19 hours: the 19 before run Mon 12 Oct 8 PM through 13 Oct 2 PM.
    expect(priorRange("2026-10-13T15:00", "2026-10-14T09:00")).toEqual(["2026-10-12T20:00", "2026-10-13T14:00"]);
    // One side at an hour, the other a whole day: 6 AM on the 13th through the 14th is 42 hours.
    expect(priorRange("2026-10-13T06:00", "2026-10-14")).toEqual(["2026-10-11T12:00", "2026-10-13T05:00"]);
  });

  it("has none without both ends or with the end first", () => {
    expect(priorRange(null, "2026-10-14")).toBeNull();
    expect(priorRange("2026-10-14", "2026-10-13")).toBeNull();
  });
});
