/** The Automated Messages tab's row helpers (automatedRows): Status, the nudge's lines, the settings' cells, dates. */
import { afterEach, describe, expect, it, vi } from "vitest";

import { type NudgeSlots } from "@/hooks/useNudgeConfig";

import { dayOf, extrasCells, shortDate, slotLines, statusOf } from "./automatedRows";

afterEach(() => vi.unstubAllEnvs());

const NOW = Date.parse("2026-10-20T12:00:00Z");
const PAST = "2026-10-19T12:00:00Z";
const FUTURE = "2026-10-21T12:00:00Z";

describe("statusOf", () => {
  it.each([
    // [on, payload, want]
    [false, undefined, "Canceled"],
    [false, { starts_at: FUTURE }, "Canceled"], // off wins over any date
    [true, undefined, "Active"],
    [true, {}, "Active"],
    [true, { starts_at: FUTURE }, "Scheduled"],
    [true, { starts_at: PAST }, "Active"],
    [true, { ends_at: PAST }, "Completed"],
    [true, { ends_at: "2026-10-20T12:00:00Z" }, "Completed"], // the Expiry instant itself is past
    [true, { ends_at: FUTURE }, "Active"],
    [true, { starts_at: PAST, ends_at: FUTURE }, "Active"],
    [true, { starts_at: "not a date" }, "Active"], // a bad stamp is no date
  ] as const)("on=%s %j is %s", (on, payload, want) => {
    expect(statusOf(on, payload as Record<string, unknown> | undefined, NOW)).toBe(want);
  });
});

describe("slotLines", () => {
  it.each<[string, NudgeSlots | undefined, string[]]>([
    ["no slots", undefined, []],
    ["empty", {}, []],
    ["stored order, trimmed, blanks dropped", {
      default: { morning: { text: [" Good morning ", ""] }, night: { text: ["Night"] } },
      weekend: { morning: { text: ["   ", "Sat"] } },
    }, ["Good morning", "Night", "Sat"]],
    ["an entry with no text", { default: { a: { text: [], image: [1] } } }, []],
  ])("%s", (_name, slots, want) => {
    expect(slotLines(slots)).toEqual(want);
  });
});

describe("extrasCells", () => {
  it.each<[string, Record<string, unknown>, string | null, Record<string, string>]>([
    ["nothing set", {}, "UTC",
      { "Attachment(s)": "--", Price: "--", "Start date": "--", "End date": "--" }],
    ["media and a price", { media_ids: [1, 2], price_cents: 1250 }, "UTC",
      { "Attachment(s)": "2 media", Price: "$12.50", "Start date": "--", "End date": "--" }],
    ["a whole-dollar price", { media_ids: [7], price_cents: 500 }, "UTC",
      { "Attachment(s)": "1 media", Price: "$5", "Start date": "--", "End date": "--" }],
    ["a price with no media is no price", { price_cents: 1250 }, "UTC",
      { "Attachment(s)": "--", Price: "--", "Start date": "--", "End date": "--" }],
    ["bad media ids are dropped", { media_ids: [0, -1, "x", 3], price_cents: 300 }, "UTC",
      { "Attachment(s)": "1 media", Price: "$3", "Start date": "--", "End date": "--" }],
    ["dates in the report zone", { starts_at: "2026-12-31T23:30:00Z", ends_at: "2027-01-31T12:00:00Z" }, "Asia/Tokyo",
      { "Attachment(s)": "--", Price: "--", "Start date": "Jan 1, 2027", "End date": "Jan 31, 2027" }],
  ])("%s", (_name, payload, tz, want) => {
    expect(extrasCells(payload, tz)).toEqual(want);
  });
});

describe("extrasCells Price", () => {
  it.each<[unknown, string]>([
    // [price_cents as stored, Price]
    [undefined, "--"],
    [0, "--"],
    [-500, "--"], // not a price: dropped
    [12.5, "--"], // a fraction of a cent is not a stored price
    [1, "$0.01"],
    [99, "$0.99"],
    [100, "$1"],
    [1005, "$10.05"], // the .005-dollar boundary
    [2999, "$29.99"],
    [123_456_789, "$1,234,567.89"], // large
    [999_999_999_99, "$999,999,999.99"],
  ])("%s cents is %s", (cents, want) => {
    const payload = { media_ids: [1], price_cents: cents };
    expect(extrasCells(payload, "UTC").Price).toBe(want);
  });
});

describe("shortDate and dayOf", () => {
  it.each<[string | null, string | null, string | null, string | null]>([
    // [iso, report zone, shortDate, dayOf]
    [null, "UTC", null, null],
    ["", "UTC", null, null],
    ["garbage", "UTC", null, null],
    ["2026-10-19T23:30:00Z", "UTC", "Oct 19, 2026", "2026-10-19"],
    ["2026-10-19T23:30:00Z", "Europe/Ljubljana", "Oct 20, 2026", "2026-10-20"],
    ["2026-01-01T03:00:00Z", "America/New_York", "Dec 31, 2025", "2025-12-31"], // year rollover west of UTC
    ["2024-02-29T12:00:00Z", "UTC", "Feb 29, 2024", "2024-02-29"],
    ["2026-11-01T05:30:00Z", "America/New_York", "Nov 1, 2026", "2026-11-01"], // DST fall back
    ["2026-10-31T10:00:00Z", "Pacific/Kiritimati", "Nov 1, 2026", "2026-11-01"], // UTC+14
    ["2026-10-31T10:00:00Z", "Pacific/Pago_Pago", "Oct 30, 2026", "2026-10-30"], // UTC−11
    ["2026-03-08T07:00:00Z", "America/New_York", "Mar 8, 2026", "2026-03-08"], // DST spring forward
  ])("%s in %s", (iso, tz, short, day) => {
    expect(shortDate(iso, tz)).toBe(short);
    expect(dayOf(iso, tz)).toBe(day);
  });

  it("read the browser's zone when none is saved", () => {
    vi.stubEnv("TZ", "Asia/Tokyo");
    expect(shortDate("2026-12-31T20:00:00Z", null)).toBe("Jan 1, 2027");
    expect(dayOf("2026-12-31T20:00:00Z", null)).toBe("2027-01-01");
  });
});
