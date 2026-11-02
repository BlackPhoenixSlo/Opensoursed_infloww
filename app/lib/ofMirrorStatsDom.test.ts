import { afterAll, describe, expect, it, vi } from "vitest";
import { agendaText, at, count, dateOf, dayText, money, num, ofCount, pad, timeText, wallOf, zero, type Wall } from "./ofMirrorStatsDom";

// The host zone pinned before any import (a formatter built at module load would keep the old zone): Kathmandu,
// +05:45 all year, no DST, matching no zone named here, so `tz: null` (the browser's clock) expectations are literals
// that fail if the module ignored the host zone. Restored after the file.
vi.hoisted(() => vi.stubEnv("TZ", "Asia/Kathmandu"));
afterAll(() => vi.unstubAllEnvs());

describe("num (a number, or a numeric string)", () => {
  it.each<[unknown, number | null]>([
    [0, 0],
    [1234.5, 1234.5],
    [-3, -3],
    ["43", 43],
    [" 43 ", 43],
    ["1e3", 1000],
    ["0x10", 16], // Number("0x10"): hex strings pass as numbers
    ["1,234.5", null], // grouped strings are not numbers
    ["", null],
    ["   ", null],
    ["abc", null],
    [null, null],
    [undefined, null],
    [NaN, null],
    [Infinity, null],
    [-Infinity, null],
    [true, null],
    [{}, null],
    [[1], null],
  ])("num(%j) -> %j", (v, want) => {
    expect(num(v)).toBe(want);
  });
});

describe("money (OF's $ figure; none: empty)", () => {
  it.each<[unknown, string]>([
    [1234.5, "$1,234.50"],
    ["1234.5", "$1,234.50"],
    [0, "$0.00"],
    [-12.3, "-$12.30"],
    [0.005, "$0.01"],
    ["1,234.5", ""],
    ["", ""],
    [null, ""],
    [undefined, ""],
    [NaN, ""],
  ])("money(%j) -> %j", (v, want) => {
    expect(money(v)).toBe(want);
  });
  it("money(-0.004) -> \"-$0.00\": a sub-cent negative keeps its sign, though zero(-0.004) is true", () => {
    // Edge case OF never sends (its amounts are whole cents): usd rounds to 0.00 and the signed zero is kept.
    expect(money(-0.004)).toBe("-$0.00");
    expect(zero(-0.004)).toBe(true);
  });
});

describe("count (a grouped number between spaces; none: the dash)", () => {
  it.each<[unknown, string]>([
    [1234, " 1,234 "],
    [1234.5, " 1,234.5 "],
    ["43", " 43 "],
    [0, " 0 "],
    ["1,234", " — "],
    ["", " — "],
    [null, " — "],
    [NaN, " — "],
  ])("count(%j) -> %j", (v, want) => {
    expect(count(v)).toBe(want);
  });
});

describe("at (the value at a dotted path)", () => {
  const body = { a: { b: { c: 7 }, list: [10, { x: "y" }], zero: 0, empty: "" }, top: null };
  it.each<[unknown, string, unknown]>([
    [body, "a.b.c", 7],
    [body, "a.b", { c: 7 }],
    [body, "a.list.0", 10],
    [body, "a.list.1.x", "y"],
    [body, "a.list.5", undefined],
    [body, "a.zero", 0],
    [body, "a.empty", ""],
    [body, "a.zero.deeper", undefined], // a primitive on the way: undefined
    [body, "top", null],
    [body, "top.x", undefined],
    [body, "missing", undefined],
    [body, "missing.deeper", undefined],
    [body, "", undefined],
    [null, "a", undefined],
    [undefined, "a", undefined],
    ["str", "length", undefined],
  ])("at(%j, %j) -> %j", (b, path, want) => {
    expect(at(b, path)).toEqual(want);
  });
});

describe("zero (|v| under half a cent)", () => {
  it.each<[number | null, boolean]>([
    [0, true],
    [-0, true],
    [0.004, true],
    [-0.004, true],
    [0.0049, true],
    [0.005, false],
    [-0.005, false],
    [1, false],
    [null, false],
  ])("zero(%j) -> %j", (v, want) => {
    expect(zero(v)).toBe(want);
  });
});

describe("ofCount (an integer grouped, anything else as sent)", () => {
  it.each<[unknown, string]>([
    [1234, "1,234"],
    [1234567, "1,234,567"],
    [0, "0"],
    [-1234, "-1,234"],
    [1234.5, "1234.5"],
    [NaN, "NaN"],
    ["1234", "1234"],
    ["43", "43"],
    ["", ""],
    [true, "true"],
    [null, "—"],
    [undefined, "—"],
  ])("ofCount(%j) -> %j", (v, want) => {
    expect(ofCount(v)).toBe(want);
  });
});

describe("dateOf (an ISO string OF sent, else null)", () => {
  it.each<[unknown, number | null]>([
    ["2026-10-25T00:30:00Z", Date.UTC(2026, 9, 25, 0, 30)],
    ["2026-10-25T02:30:00+02:00", Date.UTC(2026, 9, 25, 0, 30)],
    ["", null],
    ["not a date", null],
    [1761352200000, null],
    [null, null],
    [undefined, null],
    [new Date(0), null],
  ])("dateOf(%j)", (v, want) => {
    const d = dateOf(v);
    if (want === null) expect(d).toBeNull();
    else expect(d?.getTime()).toBe(want);
  });
});

describe("pad (two digits)", () => {
  it.each<[number, string]>([
    [0, "00"],
    [5, "05"],
    [9, "09"],
    [10, "10"],
    [59, "59"],
    [123, "123"],
    [-1, "-1"],
  ])("pad(%j) -> %j", (n, want) => {
    expect(pad(n)).toBe(want);
  });
});

// ---------------------------------------------------------------- the wall clock

// EU DST ends 2026-10-25 01:00Z (Ljubljana CEST+2 -> CET+1); US DST ends 2026-11-01 06:00Z (New York EDT-4 -> EST-5).
const EU_BEFORE = new Date("2026-10-25T00:30:00Z");
const EU_AFTER = new Date("2026-10-25T01:30:00Z");
const US_BEFORE = new Date("2026-11-01T05:30:00Z");
const US_AFTER = new Date("2026-11-01T06:30:00Z");
const NOON_NY = new Date("2026-03-05T17:00:00Z"); // 12:00 EST
const MIDNIGHT_LJ = new Date("2026-01-04T23:05:09Z"); // 00:05:09 CET, Jan 5

const w = (y: number, m: number, d: number, h: number, mi: number, s = 0): Wall => ({ y, m, d, h, mi, s });

describe("wallOf (the wall clock of an instant in a zone)", () => {
  it.each<[string, Date, string, Wall]>([
    ["EU before fall-back, Ljubljana", EU_BEFORE, "Europe/Ljubljana", w(2026, 10, 25, 2, 30)],
    ["EU after fall-back, Ljubljana (same wall hour again)", EU_AFTER, "Europe/Ljubljana", w(2026, 10, 25, 2, 30)],
    ["EU before fall-back, New York (still EDT)", EU_BEFORE, "America/New_York", w(2026, 10, 24, 20, 30)],
    ["EU after fall-back, New York (still EDT)", EU_AFTER, "America/New_York", w(2026, 10, 24, 21, 30)],
    ["US before fall-back, New York", US_BEFORE, "America/New_York", w(2026, 11, 1, 1, 30)],
    ["US after fall-back, New York (same wall hour again)", US_AFTER, "America/New_York", w(2026, 11, 1, 1, 30)],
    ["US after fall-back, Ljubljana (CET)", US_AFTER, "Europe/Ljubljana", w(2026, 11, 1, 7, 30)],
    ["midnight is hour 0 (h23), seconds kept", MIDNIGHT_LJ, "Europe/Ljubljana", w(2026, 1, 5, 0, 5, 9)],
    ["UTC", EU_BEFORE, "UTC", w(2026, 10, 25, 0, 30)],
  ])("%s", (_name, at, tz, want) => {
    expect(wallOf(at, tz)).toEqual(want);
  });

  it("the host zone pin took effect (+05:45)", () => {
    for (const at of [EU_BEFORE, US_AFTER, NOON_NY, MIDNIGHT_LJ]) expect(at.getTimezoneOffset()).toBe(-345);
  });
  // tz null: the runtime's zone (the pinned Kathmandu, +05:45).
  it.each<[Date, Wall]>([
    [EU_BEFORE, w(2026, 10, 25, 6, 15)],
    [EU_AFTER, w(2026, 10, 25, 7, 15)],
    [US_BEFORE, w(2026, 11, 1, 11, 15)],
    [US_AFTER, w(2026, 11, 1, 12, 15)],
    [MIDNIGHT_LJ, w(2026, 1, 5, 4, 50, 9)],
  ])("tz null is the host's clock (%s)", (at, want) => {
    expect(wallOf(at, null)).toEqual(want);
  });
});

describe("dayText / timeText / agendaText", () => {
  it.each<[Date, string | null, string, string, string, string]>([
    // at, tz, dayText, dayText(dayPad false), timeText, agendaText
    [EU_BEFORE, "Europe/Ljubljana", "Oct 25, 2026", "Oct 25, 2026", "02:30 am", "Oct 25, 2026, 02:30 am"],
    [EU_AFTER, "Europe/Ljubljana", "Oct 25, 2026", "Oct 25, 2026", "02:30 am", "Oct 25, 2026, 02:30 am"],
    [EU_BEFORE, "America/New_York", "Oct 24, 2026", "Oct 24, 2026", "08:30 pm", "Oct 24, 2026, 08:30 pm"],
    [EU_AFTER, "America/New_York", "Oct 24, 2026", "Oct 24, 2026", "09:30 pm", "Oct 24, 2026, 09:30 pm"],
    [US_BEFORE, "America/New_York", "Nov 01, 2026", "Nov 1, 2026", "01:30 am", "Nov 1, 2026, 01:30 am"],
    [US_AFTER, "America/New_York", "Nov 01, 2026", "Nov 1, 2026", "01:30 am", "Nov 1, 2026, 01:30 am"],
    [US_AFTER, "Europe/Ljubljana", "Nov 01, 2026", "Nov 1, 2026", "07:30 am", "Nov 1, 2026, 07:30 am"],
    [NOON_NY, "America/New_York", "Mar 05, 2026", "Mar 5, 2026", "12:00 pm", "Mar 5, 2026, 12:00 pm"],
    [MIDNIGHT_LJ, "Europe/Ljubljana", "Jan 05, 2026", "Jan 5, 2026", "12:05 am", "Jan 5, 2026, 12:05 am"],
  ])("%s in %s", (at, tz, day, dayNoPad, time, agenda) => {
    expect(dayText(at, tz)).toBe(day);
    expect(dayText(at, tz, true)).toBe(day);
    expect(dayText(at, tz, false)).toBe(dayNoPad);
    expect(timeText(at, tz)).toBe(time);
    expect(agendaText(at, tz)).toBe(agenda);
  });

  it.each<[Date, string, string, string, string]>([
    // at, dayText, dayText(dayPad false), timeText, agendaText: in the pinned host zone (Kathmandu, +05:45)
    [EU_BEFORE, "Oct 25, 2026", "Oct 25, 2026", "06:15 am", "Oct 25, 2026, 06:15 am"],
    [EU_AFTER, "Oct 25, 2026", "Oct 25, 2026", "07:15 am", "Oct 25, 2026, 07:15 am"],
    [US_BEFORE, "Nov 01, 2026", "Nov 1, 2026", "11:15 am", "Nov 1, 2026, 11:15 am"],
    [US_AFTER, "Nov 01, 2026", "Nov 1, 2026", "12:15 pm", "Nov 1, 2026, 12:15 pm"],
    [NOON_NY, "Mar 05, 2026", "Mar 5, 2026", "10:45 pm", "Mar 5, 2026, 10:45 pm"],
    [MIDNIGHT_LJ, "Jan 05, 2026", "Jan 5, 2026", "04:50 am", "Jan 5, 2026, 04:50 am"],
  ])("tz null formats the host's clock (%s)", (at, day, dayNoPad, time, agenda) => {
    expect(dayText(at, null)).toBe(day);
    expect(dayText(at, null, false)).toBe(dayNoPad);
    expect(timeText(at, null)).toBe(time);
    expect(agendaText(at, null)).toBe(agenda);
  });
});
