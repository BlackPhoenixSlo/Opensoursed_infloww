import { describe, expect, it } from "vitest";

import { compareFanIds, fanIdFromParam, isValidFanId, lastMessageFromFan, sameUserId, type FanId } from "@/lib/fanId";

const FANSLY_ME = "700237824869654528";
const FANSLY_FAN = "500365665494917120";
const OF_ME = 8000149;
const OF_FAN = 582413509;

const chat = (fromId: number | string | null) => ({
  lastMessage: fromId == null ? null : { fromUser: { id: fromId } },
});

describe("sameUserId", () => {
  it("matches across the number/string split the two platforms create", () => {
    expect(sameUserId(FANSLY_ME, FANSLY_ME)).toBe(true);
    expect(sameUserId(OF_ME, String(OF_ME))).toBe(true);
    expect(sameUserId(FANSLY_ME, FANSLY_FAN)).toBe(false);
  });

  it("never claims a match on a missing id", () => {
    expect(sameUserId(null, null)).toBe(false);
    expect(sameUserId(undefined, FANSLY_ME)).toBe(false);
    expect(sameUserId(FANSLY_ME, undefined)).toBe(false);
  });
});

describe("lastMessageFromFan", () => {
  it("is FALSE once we replied on Fansly — the bug that pinned the yellow dot", () => {
    expect(lastMessageFromFan(chat(FANSLY_ME), FANSLY_ME)).toBe(false);
    expect(chat(FANSLY_ME).lastMessage!.fromUser.id !== Number(FANSLY_ME)).toBe(true);
  });

  it("is TRUE when the fan really did speak last", () => {
    expect(lastMessageFromFan(chat(FANSLY_FAN), FANSLY_ME)).toBe(true);
    expect(lastMessageFromFan(chat(OF_FAN), String(OF_ME))).toBe(true);
  });

  it("keeps working on the OnlyFans side (numeric ids, string accountId)", () => {
    expect(lastMessageFromFan(chat(OF_ME), String(OF_ME))).toBe(false);
  });

  it("says nothing is owed when there is no last message to judge", () => {
    expect(lastMessageFromFan(chat(null), FANSLY_ME)).toBe(false);
    expect(lastMessageFromFan({ lastMessage: { fromUser: {} } }, FANSLY_ME)).toBe(false);
    expect(lastMessageFromFan(null, FANSLY_ME)).toBe(false);
  });
});

describe("fanIdFromParam", () => {
  it("keeps a Fansly snowflake EXACT, as a string", () => {
    const raw = "900604711209099264";
    expect(fanIdFromParam(raw)).toBe(raw);
    // The bug, for the record: float64 cannot hold this id.
    expect(Number(raw)).toBe(900604711209099300);
    expect(String(Number(raw))).not.toBe(raw);
  });

  it("keeps an OnlyFans-sized id a NUMBER so its query keys match the inbox's", () => {
    expect(fanIdFromParam("582413509")).toBe(582413509);
    expect(fanIdFromParam("8000149")).toBe(8000149);
  });

  it("round-trips every id the popout is handed", () => {
    for (const raw of ["900604711209099264", "700237824869654528", "500365665494917120", "582413509", "1"]) {
      expect(String(fanIdFromParam(raw))).toBe(raw);
    }
  });

  it("returns null for a param that is not an id, so the page can say so", () => {
    for (const bad of ["", "  ", "abc", "12.5", "-5", "1e21", null, undefined]) {
      expect(fanIdFromParam(bad as string | null | undefined)).toBeNull();
    }
  });
});

describe("compareFanIds", () => {
  it("orders numerically for same-width ids", () => {
    expect(compareFanIds(100, 200)).toBeLessThan(0);
    expect(compareFanIds(200, 100)).toBeGreaterThan(0);
    expect(compareFanIds(100, 100)).toBe(0);
  });

  it("ranks a longer (bigger) snowflake above a short OnlyFans id", () => {
    expect(compareFanIds(OF_FAN, FANSLY_FAN)).toBeLessThan(0);
    expect(compareFanIds(FANSLY_FAN, OF_FAN)).toBeGreaterThan(0);
  });

  it("distinguishes snowflakes that float64 would collapse together", () => {
    // These two differ only past the 2^53 boundary: as numbers they are EQUAL.
    const a = "900604711209099264";
    const b = "900604711209099265";
    expect(Number(a)).toBe(Number(b));
    expect(compareFanIds(a, b)).toBeLessThan(0);
  });

  it("sorts a mixed list stably and totally", () => {
    const ids = [FANSLY_FAN, OF_FAN, FANSLY_ME, 100, "100"];
    const once = [...ids].sort(compareFanIds);
    expect([...once].sort(compareFanIds)).toEqual(once);
    expect(once.map(String)).not.toEqual(ids.map(String));
  });

  it("agrees with sameUserId on every id shape the wire actually sends", () => {
    const pairs: Array<[FanId, FanId]> = [[7, "7"], [OF_FAN, String(OF_FAN)], [FANSLY_FAN, FANSLY_FAN]];
    for (const [a, b] of pairs) {
      expect(sameUserId(a, b)).toBe(true);
      expect(compareFanIds(a, b)).toBe(0);
    }
    expect(compareFanIds("7", "9")).toBeLessThan(0);
  });

  it("does not throw on a missing id", () => {
    expect(compareFanIds(null, undefined)).toBe(0);
    expect(compareFanIds(null, OF_FAN)).toBeLessThan(0);
  });
});

describe("isValidFanId", () => {
  it("accepts the shapes both platforms actually send", () => {
    expect(isValidFanId(FANSLY_FAN)).toBe(true);
    expect(isValidFanId(OF_FAN)).toBe(true);
    expect(isValidFanId("900604711209099264")).toBe(true);
  });

  it("rejects zero — an integer, but never a fan", () => {
    for (const z of [0, "0", "000"]) expect(isValidFanId(z)).toBe(false);
    expect(fanIdFromParam("0")).toBeNull();
    expect(fanIdFromParam("000")).toBeNull();
  });

  it("rejects garbage that Number.isFinite would have waved through", () => {
    for (const bad of ["abc", "1e21", "-5", "12.5", "", null, undefined, {}, []]) {
      expect(isValidFanId(bad)).toBe(false);
    }
  });

  it("rejects a NUMBER that is not a safe integer — its digits are already rounded", () => {
    for (const bad of [2 ** 53, 1.5, NaN, Infinity]) expect(isValidFanId(bad)).toBe(false);
    expect(isValidFanId(7)).toBe(true);
    expect(isValidFanId(String(2 ** 53))).toBe(true);
  });
});
