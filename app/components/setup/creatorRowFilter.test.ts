import { describe, expect, it } from "vitest";

import { NO_FILTERS, type CreatorFilters } from "@/components/setup/CreatorFilterBar";
import { keepAccount, keepDraft, type AccountRow, type RowFilter } from "./creatorRowFilter";

const A: AccountRow = {
  id: "acc-1", names: ["Nick", "acc-1", "Ava Creator"], platform: null, tag: "VIP", isActive: true, conn: () => "Connected",
};
const F = (patch: Partial<CreatorFilters> = {}, rest: Partial<RowFilter> = {}): RowFilter =>
  ({ filters: { ...NO_FILTERS, ...patch }, connWired: true, ...rest });

describe("keepAccount", () => {
  it.each<[string, Partial<AccountRow>, RowFilter, boolean]>([
    ["no filters keeps it", {}, F(), true],
    ["search hits the Creator name, any case, trimmed", {}, F({ q: "  ava " }), true],
    ["search hits the id", {}, F({ q: "acc-1" }), true],
    ["search misses", {}, F({ q: "zed" }), false],
    ["no platform counts as OnlyFans", {}, F({ platform: "onlyfans" }), true],
    ["other platform", {}, F({ platform: "fansly" }), false],
    ["tag matches", {}, F({ tag: "VIP" }), true],
    ["tag differs", {}, F({ tag: "New" }), false],
    ["conn matches", {}, F({ conn: "Connected" }), true],
    ["conn differs", {}, F({ conn: "Disconnected" }), false],
    ["conn filter off when the health read failed", {}, F({ conn: "Disconnected" }, { connWired: false }), true],
    ["Activated keeps an active row", {}, F({ status: "Activated" }), true],
    ["Deactivated hides an active row", {}, F({ status: "Deactivated" }), false],
    ["Deactivated keeps an inactive row", { isActive: false }, F({ status: "Deactivated" }), true],
    ["Employee with access", {}, F({}, { picked: { account_ids: ["acc-1"] } }), true],
    ["Employee without access", {}, F({}, { picked: { account_ids: ["acc-2"] } }), false],
    ["Employee with every Creator", {}, F({}, { picked: { account_ids: null } }), true],
  ])("%s", (_name, row, f, want) => {
    expect(keepAccount({ ...A, ...row }, f)).toBe(want);
  });

  it("reads connectivity only with the Connectivity filter on", () => {
    let reads = 0;
    const row = { ...A, conn: () => { reads += 1; return "Connected"; } };
    keepAccount(row, F());
    expect(reads).toBe(0);
    keepAccount(row, F({ conn: "Connected" }));
    expect(reads).toBe(1);
  });
});

describe("keepDraft", () => {
  it.each<[string, string, RowFilter, boolean]>([
    ["no filters keeps it", "Ava", F(), true],
    ["search hits", "Ava", F({ q: "av" }), true],
    ["search misses", "Ava", F({ q: "zed" }), false],
    ["any platform hides it", "Ava", F({ platform: "onlyfans" }), false],
    ["any tag hides it", "Ava", F({ tag: "VIP" }), false],
    ["a picked Employee hides it", "Ava", F({}, { picked: { account_ids: null } }), false],
    ["Activated keeps it", "Ava", F({ status: "Activated" }), true],
    ["Deactivated hides it", "Ava", F({ status: "Deactivated" }), false],
    ["Pending connection keeps it", "Ava", F({ conn: "Pending connection" }), true],
    ["another conn label hides it", "Ava", F({ conn: "Connected" }), false],
    ["another conn label hides it with the health read failed too", "Ava", F({ conn: "Connected" }, { connWired: false }), false],
  ])("%s", (_name, name, f, want) => {
    expect(keepDraft(name, f)).toBe(want);
  });
});
