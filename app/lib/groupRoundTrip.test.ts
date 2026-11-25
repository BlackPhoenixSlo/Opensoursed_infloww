import { describe, expect, it } from "vitest";

import { parseSlotsParam } from "@/lib/groupChannel";

describe("parseSlotsParam id fidelity", () => {
  it("preserves a Fansly snowflake exactly", () => {
    const fanId = "900604711209099264";
    const round = parseSlotsParam(`700237824869654528:${fanId}`);
    expect(round).toHaveLength(1);
    expect(String(round[0].fanId)).toBe(fanId);
    // The old behaviour, pinned so it cannot silently return.
    expect(String(Number(fanId))).toBe("900604711209099300");
  });

  it("keeps a numeric OnlyFans id a number, so its keys still match the inbox", () => {
    const round = parseSlotsParam("acc:582413509");
    expect(round[0].fanId).toBe(582413509);
  });

  it("still drops malformed slots, including the zero the old `> 0` guard caught", () => {
    expect(parseSlotsParam("acc:0,acc:-1,acc:abc,:5,garbage")).toEqual([]);
  });

  it("de-duplicates the same fan across id shapes", () => {
    expect(parseSlotsParam("acc:7,acc:7")).toHaveLength(1);
  });
});
