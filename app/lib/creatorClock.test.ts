import { describe, expect, it } from "vitest";

import { zoneOffsetNow } from "./creatorClock";

/**
 * The creator clock. Assertions are RELATIVE or pinned to a zone with no DST —
 * a fixture pinned to a wall clock would go red twice a year on its own.
 */
describe("zoneOffsetNow", () => {
  it("derives the label FROM the number, so the two cannot disagree", () => {
    expect(zoneOffsetNow("UTC")).toEqual({ minutes: 0, label: "UTC+0" });
    // Kolkata is +5:30 year-round — no DST, so this is safe to pin, and it proves
    // the label carries the half hour instead of truncating it away.
    expect(zoneOffsetNow("Asia/Kolkata")).toEqual({ minutes: 330, label: "UTC+5:30" });
  });

  it("reads a western zone as a whole number of negative hours", () => {
    const ny = zoneOffsetNow("America/New_York");
    expect(ny).not.toBeNull();
    // -240 (EDT) or -300 (EST) depending on the season; either is a whole hour.
    expect([-240, -300]).toContain(ny!.minutes);
    expect(ny!.label).toBe(`UTC${ny!.minutes / 60}`);
  });

  it("returns null for a zone Intl does not know, instead of throwing", () => {
    expect(zoneOffsetNow("Not/AZone")).toBeNull();
  });
});
