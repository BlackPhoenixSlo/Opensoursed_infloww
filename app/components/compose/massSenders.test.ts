import { describe, expect, it } from "vitest";

import type { Platform } from "@/lib/platform";

import type { FanOutResult } from "./fanOut";
import { initMassForm, massMessageReducer, type MassForm } from "./massMessageReducer";
import { massSendFrom, massSenders } from "./massSenders";

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
    ["unregistered platform is never an OnlyFans sender", [odd], "onlyfans", []],
    ["mixed list keeps only OnlyFans, in input order", [of2, fs1, legacy, of1], "onlyfans", ["of2", "legacy", "of1"]],
    ["Fansly Platform yields none while Fansly lacks mass_message", [fs1, of1, legacy], "fansly", []],
    ["empty list", [], "onlyfans", []],
  ])("%s", (_label, accounts, platform, want) => {
    expect(ids(massSenders(accounts, platform))).toEqual(want);
  });
});

describe("massSendFrom: the ids the confirm counts and the send POSTs", () => {
  const roster: Row[] = [of1, fs1, of2, legacy];
  const all = (over: Partial<MassForm> = {}): MassForm => ({ ...initMassForm(), allModels: true, ...over });
  const solo = (id: string, over: Partial<MassForm> = {}): MassForm => ({ ...initMassForm(id), ...over });
  const everyone = () => true;
  const fail = (accountId: string): FanOutResult => ({ accountId, ok: false, error: "500" });
  it.each<[string, MassForm, (id: string) => boolean, boolean, string[]]>([
    ["All-models on a mixed roster with a preseeded Fansly id: only the OnlyFans ids", all(), everyone, true, ["of1", "of2", "legacy"]],
    ["an excluded chip is no target", all(), (id) => id !== "of2", true, ["of1", "legacy"]],
    ["the retry: only the failed OnlyFans ids, never the failed Fansly one",
      all({ results: [{ accountId: "of1", ok: true }, fail("fs1"), fail("of2")] }), everyone, true, ["of2", "legacy"]],
    ["a Fansly composer has no target while Fansly lacks mass_message", all({ platform: "fansly" }), everyone, true, []],
    ["one OnlyFans sender", solo("of1"), everyone, true, ["of1"]],
    ["an off-roster OnlyFans Creator (expired session) still sends", solo("ofX"), everyone, true, ["ofX"]],
    ["a Creator whose Platform can't mass message is dropped", solo("fs1", { platform: "fansly" }), everyone, false, []],
    ["no account, no sender", solo("", { accountId: null }), everyone, true, []],
  ])("%s", (_n, form, isIncluded, accountMaySend, want) => {
    expect(massSendFrom(form, roster, isIncluded, accountMaySend)).toEqual(want);
  });
});

it.each([
  ["unknown", []],
  ["fansly", []],
  ["onlyfans", ["of1", "of2"]],
] as const)("forced launch with roster platform %s", (platform, expected) => {
  const form = { ...initMassForm("saved"), allModels: true };
  const resolved = massMessageReducer(form, { type: "launchPlatform", platform });
  expect(massSendFrom(resolved, [of1, of2], () => true, true)).toEqual(expected);
});
