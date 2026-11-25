import { afterEach, describe, expect, it, vi } from "vitest";

import { addDays, createdDay, dayKey, monthStartBefore } from "./frameDates";

afterEach(() => vi.unstubAllEnvs());

const ZONES = ["UTC", "America/New_York", "Asia/Tokyo"];

describe.each(ZONES)("browser TZ %s", (zone) => {
  it.each([
    ["2026-01-31", 1, "2026-02-01"],
    ["2026-04-30", 1, "2026-05-01"],
    ["2026-03-01", -1, "2026-02-28"],
    ["2024-03-01", -1, "2024-02-29"],
    ["2024-02-28", 1, "2024-02-29"],
    ["2023-02-28", 1, "2023-03-01"],
    ["2026-12-31", 1, "2027-01-01"],
    ["2027-01-01", -1, "2026-12-31"],
    ["2026-01-05", -7, "2025-12-29"],
    ["2026-03-08", 1, "2026-03-09"],
    ["2026-03-29", -1, "2026-03-28"],
    ["2026-11-01", 1, "2026-11-02"],
    ["2026-10-25", -30, "2026-09-25"],
    ["2026-10-31", 0, "2026-10-31"],
  ])("addDays(%s, %i) is %s", (day, n, want) => {
    vi.stubEnv("TZ", zone);
    expect(addDays(day, n)).toBe(want);
  });

  it.each([
    ["2026-10-31", 6, "2026-04-01"],
    ["2026-03-31", 1, "2026-02-01"],
    ["2024-02-29", 12, "2023-02-01"],
    ["2025-03-01", 12, "2024-03-01"],
    ["2026-01-15", 6, "2025-07-01"],
    ["2026-06-30", 12, "2025-06-01"],
    ["2026-12-31", 12, "2025-12-01"],
    ["2026-03-08", 6, "2025-09-01"],
    ["2026-11-01", 6, "2026-05-01"],
  ])("monthStartBefore(%s, %i) is %s", (day, m, want) => {
    vi.stubEnv("TZ", zone);
    expect(monthStartBefore(day, m)).toBe(want);
  });

  it.each([
    ["2026-12-31T23:30:00Z", "UTC", "2026-12-31"],
    ["2026-12-31T16:00:00Z", "Asia/Tokyo", "2027-01-01"],
    ["2027-01-01T03:00:00Z", "America/New_York", "2026-12-31"],
    ["2024-02-29T12:00:00Z", "UTC", "2024-02-29"],
    ["2026-03-08T06:59:59Z", "America/New_York", "2026-03-08"],
    ["2026-03-08T07:00:00Z", "America/New_York", "2026-03-08"],
    ["2026-03-08T04:59:59Z", "America/New_York", "2026-03-07"],
    ["2026-11-01T05:30:00Z", "America/New_York", "2026-11-01"],
    ["2026-11-01T06:30:00Z", "America/New_York", "2026-11-01"],
    ["2026-11-02T04:59:59Z", "America/New_York", "2026-11-01"],
    ["2026-10-25T00:30:00Z", "Europe/Ljubljana", "2026-10-25"],
    ["2026-10-31T10:00:00Z", "Pacific/Kiritimati", "2026-11-01"],
    ["2026-10-31T10:00:00Z", "Pacific/Pago_Pago", "2026-10-30"],
  ])("dayKey(%s, %s) is %s", (iso, tz, want) => {
    vi.stubEnv("TZ", zone);
    expect(dayKey(new Date(iso), tz)).toBe(want);
  });

  it.each([
    [null, "UTC", null],
    ["", "UTC", null],
    ["garbage", "UTC", null],
    ["2026-10-19T23:30:00", "UTC", "2026-10-19"],
    ["2026-10-19 23:30:00", "UTC", "2026-10-19"],
    ["2026-10-19T23:30:00", "Europe/Ljubljana", "2026-10-20"],
    ["2026-12-31T16:00:00", "Asia/Tokyo", "2027-01-01"],
    ["2027-01-01T03:00:00Z", "America/New_York", "2026-12-31"],
    ["2024-02-29T23:59:59+00:00", "UTC", "2024-02-29"],
    ["2026-11-01T05:30:00", "America/New_York", "2026-11-01"],
  ])("createdDay(%s, %s) is %s", (created_at, tz, want) => {
    vi.stubEnv("TZ", zone);
    expect(createdDay({ created_at }, tz)).toBe(want);
  });

  it("dayKey with no report zone reads the browser's", () => {
    vi.stubEnv("TZ", zone);
    const at = new Date("2026-12-31T20:00:00Z");
    expect(dayKey(at, null)).toBe(zone === "Asia/Tokyo" ? "2027-01-01" : "2026-12-31");
  });
});
