import { describe, expect, it } from "vitest";

import {
  clampValue, dayAllowed, joinValue, minuteOptions, monthGrid, setTimePart, shiftMonth, splitValue, type DateMode,
} from "./ifDateValue";

describe("ifDateValue", () => {
  it.each<[DateMode, string, { day: string; time: string }]>([
    ["date", "2026-11-13", { day: "2026-11-13", time: "" }],
    ["date", "", { day: "", time: "" }],
    ["date", "nope", { day: "", time: "" }],
    ["time", "09:30", { day: "", time: "09:30" }],
    ["time", "09:30:15", { day: "", time: "09:30" }],
    ["datetime-local", "2026-11-13T21:05", { day: "2026-11-13", time: "21:05" }],
    ["datetime-local", "2026-11-13", { day: "2026-11-13", time: "" }],
  ])("splits %s %j", (mode, value, want) => {
    expect(splitValue(mode, value)).toEqual(want);
  });

  it.each<[DateMode, string, string, string]>([
    ["date", "2026-11-13", "10:00", "2026-11-13"],
    ["time", "", "10:00", "10:00"],
    ["datetime-local", "2026-11-13", "10:00", "2026-11-13T10:00"],
    ["datetime-local", "2026-11-13", "", "2026-11-13T00:00"],
    ["datetime-local", "", "10:00", ""],
  ])("joins %s %s %s", (mode, day, time, want) => {
    expect(joinValue(mode, day, time)).toBe(want);
  });

  it("builds a Sunday-first six-week grid", () => {
    const g = monthGrid("2026-11"); // Nov 1 2026 is a Sunday
    expect(g).toHaveLength(42);
    expect(g[0]).toBe("2026-11-01");
    expect(g[41]).toBe("2026-12-12");
    expect(monthGrid("2026-02")[0]).toBe("2026-02-01"); // Sunday too
    expect(monthGrid("2026-10")[0]).toBe("2026-09-27");
  });

  it.each([["2026-01", -1, "2025-12"], ["2026-12", 1, "2027-01"], ["2026-05", 0, "2026-05"]] as const)(
    "shifts %s by %i", (m, by, want) => expect(shiftMonth(m, by)).toBe(want));

  it.each([
    ["2026-11-13", undefined, undefined, true],
    ["2026-11-13", "2026-11-14", undefined, false],
    ["2026-11-13", undefined, "2026-11-12", false],
    ["2026-11-13", "2026-11-13T23:00", "2026-11-13T01:00", true],
  ] as const)("allows %s within [%s, %s]: %s", (d, min, max, want) => {
    expect(dayAllowed(d, min, max)).toBe(want);
  });

  it.each([[undefined, 60], ["60", 60], [300, 12], [3600, 1], [30, 60]] as const)(
    "step %s gives %i minutes", (step, n) => expect(minuteOptions(step)).toHaveLength(n));

  it("replaces one part of a time", () => {
    expect(setTimePart("", "h", 9)).toBe("09:00");
    expect(setTimePart("09:45", "h", 13)).toBe("13:45");
    expect(setTimePart("09:45", "m", 5)).toBe("09:05");
  });
});

describe("clampValue", () => {
  it.each([
    ["2026-11-13T00:00", "2026-11-13T14:30", undefined, "2026-11-13T14:30"],
    ["2026-11-14T00:00", "2026-11-13T14:30", undefined, "2026-11-14T00:00"],
    ["2026-11-20T09:00", undefined, "2026-11-20T08:00", "2026-11-20T08:00"],
    ["2026-11-13", "2026-11-13T14:30", undefined, "2026-11-13"],
    ["07:00", "08:00", undefined, "08:00"],
    ["", "2026-11-13T14:30", undefined, ""],
  ])("%s min=%s max=%s -> %s", (v, min, max, out) => expect(clampValue(v, min, max)).toBe(out));
});
