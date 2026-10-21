import { describe, expect, it } from "vitest";

import { trialDaysLeft } from "@/lib/freeTrial";

const DAY = 24 * 60 * 60 * 1000;
const START = Date.parse("2026-10-01T12:00:00Z");

describe("trialDaysLeft", () => {
  it("counts 7 days left right after registering and 1 on the last day", () => {
    expect(trialDaysLeft("2026-10-01T12:00:00Z", START + 1000)).toBe(7);
    expect(trialDaysLeft("2026-10-01T12:00:00Z", START + 2.5 * DAY)).toBe(5);
    expect(trialDaysLeft("2026-10-01T12:00:00Z", START + 7 * DAY - 1000)).toBe(1);
  });

  it("is 0 once 7 days have passed", () => {
    expect(trialDaysLeft("2026-10-01T12:00:00Z", START + 7 * DAY)).toBe(0);
    expect(trialDaysLeft("2026-10-01T12:00:00Z", START + 30 * DAY)).toBe(0);
  });

  it("is null without a usable registration time", () => {
    expect(trialDaysLeft(undefined)).toBeNull();
    expect(trialDaysLeft(null)).toBeNull();
    expect(trialDaysLeft("not a date")).toBeNull();
  });
});
