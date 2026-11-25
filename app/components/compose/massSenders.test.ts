import { describe, expect, it } from "vitest";

import type { Platform } from "@/lib/platform";

import { massSenders } from "./massSenders";

type Row = { id: string; platform?: string | null };
const of1: Row = { id: "of1", platform: "onlyfans" };
const of2: Row = { id: "of2", platform: "onlyfans" };
const legacy: Row = { id: "legacy" };
const legacyNull: Row = { id: "legacyNull", platform: null };
const fs1: Row = { id: "fs1", platform: "fansly" };
const odd: Row = { id: "odd", platform: "mym" };

const ids = (rows: Row[]) => rows.map((r) => r.id);

describe("massSenders", () => {
  it.each<[string, Row[], Platform, string[]]>([
    ["Fansly dropped, OnlyFans kept", [fs1, of1], "onlyfans", ["of1"]],
    ["legacy no-platform kept", [legacy, legacyNull], "onlyfans", ["legacy", "legacyNull"]],
    ["unknown platform reads OnlyFans", [odd], "onlyfans", ["odd"]],
    ["mixed list keeps only OnlyFans, in input order", [of2, fs1, legacy, of1], "onlyfans", ["of2", "legacy", "of1"]],
    ["Fansly Platform yields none while Fansly lacks mass_message", [fs1, of1, legacy], "fansly", []],
    ["empty list", [], "onlyfans", []],
  ])("%s", (_label, accounts, platform, want) => {
    expect(ids(massSenders(accounts, platform))).toEqual(want);
  });
});
