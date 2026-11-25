import { describe, expect, it } from "vitest";

import {
  CAPABILITIES, PLATFORMS, PLATFORM_KEY, PLATFORM_NAME, accountPlatform, can, getPlatform, resetPlatformForTests,
  type Capability, type Platform,
} from "@/lib/platform";

describe("can", () => {
  const rows: [Platform | null, Capability, boolean][] = [
    ...CAPABILITIES.map((c) => ["onlyfans", c, true] as [Platform, Capability, boolean]),
    ...CAPABILITIES.map((c) => ["fansly", c, false] as [Platform, Capability, boolean]),
    ...CAPABILITIES.map((c) => [null, c, false] as [null, Capability, boolean]),
  ];
  it.each(rows)("%s can %s → %s", (p, cap, want) => {
    expect(can(p, cap)).toBe(want);
  });

  it("lists 14 Capabilities, OnlyFans lacking none and Fansly all", () => {
    expect(CAPABILITIES).toHaveLength(14);
    expect(PLATFORMS.map((p) => [p.key, p.lacks.length])).toEqual([["onlyfans", 0], ["fansly", 14]]);
  });
});

describe("Platform names and keys read from the table", () => {
  it("PLATFORM_NAME is each row's label", () => {
    expect(PLATFORM_NAME).toEqual({ onlyfans: "OnlyFans", fansly: "Fansly" });
  });

  it.each<[string, { platform?: string | null }, Platform]>([
    ["missing", {}, "onlyfans"],
    ["null", { platform: null }, "onlyfans"],
    ["unknown", { platform: "mym" }, "onlyfans"],
    ["onlyfans", { platform: "onlyfans" }, "onlyfans"],
    ["fansly", { platform: "fansly" }, "fansly"],
  ])("accountPlatform: %s platform", (_, a, want) => {
    expect(accountPlatform(a)).toBe(want);
  });

  it.each<[string | null, Platform]>([[null, "onlyfans"], ["fansly", "fansly"], ["mym", "onlyfans"], ["onlyfans", "onlyfans"]])(
    "stored switch %s reads %s",
    (raw, want) => {
      if (raw === null) window.localStorage.removeItem(PLATFORM_KEY);
      else window.localStorage.setItem(PLATFORM_KEY, raw);
      resetPlatformForTests();
      expect(getPlatform()).toBe(want);
      window.localStorage.removeItem(PLATFORM_KEY);
      resetPlatformForTests();
    },
  );
});
