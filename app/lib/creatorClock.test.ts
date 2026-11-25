import { describe, expect, it } from "vitest";

import { rangeOffsetLabel, zoneOffsetAt, zoneOffsetNow } from "./creatorClock";

describe("zoneOffsetNow", () => {
  it("derives the label FROM the number, so the two cannot disagree", () => {
    expect(zoneOffsetNow("UTC")).toEqual({ minutes: 0, label: "UTC+0" });
    expect(zoneOffsetNow("Asia/Kolkata")).toEqual({ minutes: 330, label: "UTC+5:30" });
  });

  it("reads a western zone as a whole number of negative hours", () => {
    const ny = zoneOffsetNow("America/New_York");
    expect(ny).not.toBeNull();
    expect([-240, -300]).toContain(ny!.minutes);
    expect(ny!.label).toBe(`UTC${ny!.minutes / 60}`);
  });

  it("returns null for a zone Intl does not know, instead of throwing", () => {
    expect(zoneOffsetNow("Not/AZone")).toBeNull();
  });
});

describe("zoneOffsetAt", () => {
  it.each([
    ["America/New_York", "2026-07-01T12:00:00Z", -240, "UTC-4"],
    ["America/New_York", "2026-12-01T12:00:00Z", -300, "UTC-5"],
    ["America/New_York", "2026-11-01T05:59:00Z", -240, "UTC-4"],
    ["America/New_York", "2026-11-01T06:00:00Z", -300, "UTC-5"],
    ["Europe/Paris", "2026-07-01T12:00:00Z", 120, "UTC+2"],
    ["Europe/Paris", "2026-12-01T12:00:00Z", 60, "UTC+1"],
    ["Asia/Kolkata", "2026-07-01T12:00:00Z", 330, "UTC+5:30"],
    ["UTC", "2026-07-01T12:00:00Z", 0, "UTC+0"],
    ["Australia/Sydney", "2026-01-15T12:00:00Z", 660, "UTC+11"],
    ["Australia/Sydney", "2026-07-01T12:00:00Z", 600, "UTC+10"],
  ])("%s at %s → %s", (tz, iso, minutes, label) => {
    expect(zoneOffsetAt(tz, Date.parse(iso))).toEqual({ minutes, label });
    expect(zoneOffsetAt(tz, new Date(iso))).toEqual({ minutes, label });
  });

  it("zoneOffsetNow is zoneOffsetAt now", () => {
    expect(zoneOffsetNow("America/New_York")).toEqual(zoneOffsetAt("America/New_York", Date.now()));
  });

  it("returns null for a zone Intl does not know", () => {
    expect(zoneOffsetAt("Not/AZone", 0)).toBeNull();
  });
});

describe("rangeOffsetLabel", () => {
  it.each([
    ["inside one period", "America/New_York", "2026-07-01T04:00:00Z", "2026-07-16T04:00:00Z", "America/New_York (UTC-4)"],
    ["crossing DST end", "America/New_York", "2026-10-20T04:00:00Z", "2026-11-11T05:00:00Z", "America/New_York (UTC-4 → UTC-5)"],
    ["ending just before DST end", "America/New_York", "2026-10-20T04:00:00Z", "2026-11-01T05:59:59.999Z", "America/New_York (UTC-4)"],
    ["crossing DST start", "America/New_York", "2026-03-01T05:00:00Z", "2026-03-20T04:00:00Z", "America/New_York (UTC-5 → UTC-4)"],
    ["no DST", "Asia/Kolkata", "2026-01-01T00:00:00Z", "2026-12-01T00:00:00Z", "Asia/Kolkata (UTC+5:30)"],
    ["unknown zone", "Not/AZone", "2026-07-01T04:00:00Z", "2026-07-16T04:00:00Z", "Not/AZone"],
  ])("%s", (_, tz, from, to, label) => {
    expect(rangeOffsetLabel(tz, Date.parse(from), Date.parse(to))).toBe(label);
  });
});
