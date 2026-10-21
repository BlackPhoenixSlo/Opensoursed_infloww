import { afterEach, describe, expect, it } from "vitest";

import { claimSendGap, resetSendGapForTests, SEND_GAP_MS } from "@/lib/sendGuards";

afterEach(() => resetSendGapForTests());

describe("claimSendGap", () => {
  it("holds a model's second send within the gap, never another model's", () => {
    expect(claimSendGap("a", 10_000)).toBe(true);
    expect(claimSendGap("a", 10_000 + SEND_GAP_MS - 1)).toBe(false);
    expect(claimSendGap("b", 10_001)).toBe(true);
    expect(claimSendGap("a", 10_000 + SEND_GAP_MS)).toBe(true);
  });

  it("keeps no shared clock for a composer with no model", () => {
    expect(claimSendGap(null, 10_000)).toBe(true);
    expect(claimSendGap(null, 10_001)).toBe(true);
    expect(claimSendGap("", 10_002)).toBe(true);   // "" is not where null's sends were recorded
  });
});
