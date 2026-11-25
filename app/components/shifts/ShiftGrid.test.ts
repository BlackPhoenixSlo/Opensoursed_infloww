import { describe, expect, it } from "vitest";

import { dayLabel, employeeLine, longDate, untilDate } from "@/components/shifts/ShiftGrid";
import type { ShiftEmployee, ShiftOccurrence, ZonedDay } from "@/lib/shifts";

const occ = (employees: ShiftEmployee[]): ShiftOccurrence => ({
  shift_id: 1,
  occurrence_start: "2026-10-15T22:00:00Z",
  occurrence_end: "2026-10-16T06:00:00Z",
  start_utc: "2026-10-15T22:00:00Z",
  end_utc: "2026-10-16T06:00:00Z",
  tz: "UTC",
  repeat_days: null,
  repeat_until: null,
  employees,
  accounts: [],
});
const ann = { id: 1, display_name: "Ann" };
const bo = { id: 2, display_name: "Bo" };
const cy = { id: 3, display_name: "Cy" };

describe("dayLabel", () => {
  const day = (date: string, ddd: string, dd: string): ZonedDay =>
    ({ start: new Date(0), end: new Date(0), date, ddd, dd, today: false });
  it.each([
    ["2026-03-08",   "Sun", "08", "Sun 8 Mar"],
    ["2026-01-01",   "Thu", "01", "Thu 1 Jan"],
    ["2026-10-15",   "Thu", "15", "Thu 15 Oct"],
    ["2026-12-31",   "Thu", "31", "Thu 31 Dec"],
  ] as const)("%s → %s", (date, ddd, dd, want) => {
    expect(dayLabel(day(date, ddd, dd))).toBe(want);
  });
});

describe("employeeLine", () => {
  it.each([
    ["none",               [],              "No employee"],
    ["one",                [ann],           "Ann"],
    ["two",                [ann, bo],       "Ann +1"],
    ["three",              [ann, bo, cy],   "Ann +2"],
    ["blank name",         [{ id: 4, display_name: "" }],       ""],
    ["blank name + other", [{ id: 4, display_name: "" }, ann],  " +1"],
  ] as const)("%s", (_l, employees, want) => {
    expect(employeeLine(occ([...employees]))).toBe(want);
  });
});

describe("longDate", () => {
  it.each([
    ["overnight start, UTC",                "2026-10-15T22:00:00Z", "UTC",              "Thursday, October 15, 2026"],
    ["overnight start, moves forward",      "2026-10-15T22:00:00Z", "Asia/Kolkata",     "Friday, October 16, 2026"],
    ["overnight end, New York",             "2026-10-16T06:00:00Z", "America/New_York", "Friday, October 16, 2026"],
    ["moves back a day",                    "2026-11-01T03:59:00Z", "America/New_York", "Saturday, October 31, 2026"],
    ["US DST start, 2-digit day",           "2026-03-08T07:30:00Z", "America/New_York", "Sunday, March 08, 2026"],
    ["US DST end, repeated hour",           "2026-11-01T06:30:00Z", "America/New_York", "Sunday, November 01, 2026"],
  ] as const)("%s", (_l, iso, tz, want) => {
    expect(longDate(iso, tz)).toBe(want);
  });
});

describe("untilDate", () => {
  it.each([
    ["2026-12-31", "Dec. 31, 2026"],
    ["2026-01-05", "Jan. 5, 2026"],
    ["2027-03-08", "Mar. 8, 2027"],
    ["",           "undefined. undefined, 0"],
    ["nope",       "undefined. undefined, NaN"],
    ["2026-13-01", "undefined. 1, 2026"],
  ] as const)("%j → %s", (date, want) => {
    expect(untilDate(date)).toBe(want);
  });
});
