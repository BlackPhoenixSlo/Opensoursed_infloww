import { describe, expect, it } from "vitest";

import type { MassMessageRow } from "@/hooks/useMassMessages";
import {
  BULK_MIN_AGE_H,
  bulkCounts,
  bulkTargets,
  isActionable,
  isFreeTextOld,
  olderThanHours,
  visibleMassRows,
  type BulkAction,
} from "./massUnsendRules";

const NOW = Date.parse("2026-10-31T12:00:00Z");
const H = 3_600_000;
const ago = (ms: number) => new Date(NOW - ms).toISOString();
const OLD = ago(5 * H);

/** An actionable free text broadcast of Creator "a", 5 h old, unless `over` says otherwise. */
const row = (id: number, over: Partial<MassMessageRow> = {}): MassMessageRow => ({
  id, date: OLD, isFree: true, mediaCount: 0, canUnsend: true, isCanceled: false, __accountId: "a", ...over,
});

describe("olderThanHours (the 4 h age gate)", () => {
  it.each([
    ["exactly 4 h", ago(4 * H), true],
    ["1 ms under 4 h", ago(4 * H - 1), false],
    ["5 h", ago(5 * H), true],
    ["in the future", ago(-H), false],
    ["no date", null, false],
    ["empty date", "", false],
    ["bad date", "not a date", false],
  ])("%s -> %s", (_label, date, want) => {
    expect(olderThanHours(row(1, { date }), BULK_MIN_AGE_H, NOW)).toBe(want);
  });
});

describe("isFreeTextOld", () => {
  it.each([
    ["free text, old", {}, true],
    ["free GIF-only, old (a GIF is not an image)", { giphyId: "g1" }, true],
    ["free with an image", { mediaCount: 1 }, false],
    ["paid text", { isFree: false }, false],
    ["isFree missing", { isFree: undefined }, false],
    ["free text, fresh", { date: ago(H) }, false],
  ] as const)("%s -> %s", (_label, over, want) => {
    expect(isFreeTextOld(row(1, over as Partial<MassMessageRow>), NOW)).toBe(want);
  });
});

describe("isActionable", () => {
  it.each([
    ["live", {}, true],
    ["already unsent", { isCanceled: true }, false],
    ["canUnsend false", { canUnsend: false }, false],
    ["canUnsend missing", { canUnsend: undefined }, false],
    ["no accountId", { __accountId: undefined }, false],
  ] as const)("%s -> %s", (_label, over, want) => {
    expect(isActionable(row(1, over as Partial<MassMessageRow>))).toBe(want);
  });
});

/** Two Creators' rows: every kind the bar tells apart. */
const ROWS: MassMessageRow[] = [
  row(1),                                              // a free text, old
  row(2, { giphyId: "g" }),                            // a free GIF-only, old
  row(3, { mediaCount: 2 }),                           // a free image, old
  row(4, { isFree: false }),                           // a paid text, old
  row(5, { isFree: false, mediaCount: 1 }),            // a paid image, old
  row(6, { date: ago(4 * H) }),                        // a free text, exactly 4 h
  row(7, { date: ago(4 * H - 1) }),                    // a free text, just under 4 h
  row(8, { date: null }),                              // a free text, no date
  row(9, { date: "garbage" }),                         // a free text, bad date
  row(10, { mediaCount: 1, date: ago(H) }),            // a free image, fresh
  row(11, { isCanceled: true }),                       // a already unsent
  row(12, { canUnsend: false }),                       // a OF says no
  row(13, { __accountId: undefined }),                 // no Creator
  row(21, { __accountId: "b" }),                       // b free text, old
  row(22, { __accountId: "b", mediaCount: 1 }),        // b free image, old
  row(23, { __accountId: "b", date: ago(H) }),         // b free text, fresh
  row(24, { __accountId: "b", isCanceled: true }),     // b already unsent
];
const ids = (rs: MassMessageRow[]) => rs.map((r) => r.id);

describe("bulkTargets: the rows a bulk unsend picks", () => {
  it.each<[string, string[], BulkAction, number[]]>([
    ["all models, Unsend all", [], "all", [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 21, 22, 23]],
    ["all models, non-image", [], "non-image", [1, 2, 4, 6, 21]],
    ["all models, with images", [], "with-image", [3, 5, 22]],
    ["all models, free text", [], "free-text-old", [1, 2, 6, 21]],
    ["chip a, Unsend all", ["a"], "all", [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]],
    ["chip a, non-image", ["a"], "non-image", [1, 2, 4, 6]],
    ["chip a, with images", ["a"], "with-image", [3, 5]],
    ["chip a, free text", ["a"], "free-text-old", [1, 2, 6]],
    ["chip b, Unsend all", ["b"], "all", [21, 22, 23]],
    ["chip b, free text", ["b"], "free-text-old", [21]],
    ["chip b, with images", ["b"], "with-image", [22]],
    ["chips a + b, free text", ["a", "b"], "free-text-old", [1, 2, 6, 21]],
    ["chip of a model with no rows", ["c"], "all", []],
  ])("%s", (_label, chips, action, want) => {
    expect(ids(bulkTargets(ROWS, new Set(chips), action, NOW))).toEqual(want);
  });

  it("never picks an unsent, un-unsendable or Creator-less row, whatever the action", () => {
    for (const action of ["all", "non-image", "with-image", "free-text-old"] as const) {
      const got = ids(bulkTargets(ROWS, new Set(), action, NOW));
      for (const bad of [11, 12, 13, 24]) expect(got).not.toContain(bad);
    }
  });

  it("is the same rows the age gate lets through as time moves: row 7 joins 1 ms later", () => {
    expect(ids(bulkTargets(ROWS, new Set(["a"]), "free-text-old", NOW + 1))).toEqual([1, 2, 6, 7]);
  });
});

describe("bulkCounts", () => {
  it.each<[string[], Record<BulkAction, number>]>([
    [[], { all: 13, "non-image": 5, "with-image": 3, "free-text-old": 4 }],
    [["b"], { all: 3, "non-image": 1, "with-image": 1, "free-text-old": 1 }],
  ])("chips %j", (chips, want) => {
    expect(bulkCounts(ROWS, new Set(chips), NOW)).toEqual(want);
  });
});

describe("visibleMassRows", () => {
  it.each<[string, string[], boolean, number[]]>([
    ["all, unsent hidden", [], true, [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 13, 21, 22, 23]],
    ["all, unsent shown", [], false, ids(ROWS)],
    ["chip b, unsent hidden", ["b"], true, [21, 22, 23]],
    ["chip b, unsent shown", ["b"], false, [21, 22, 23, 24]],
  ])("%s", (_label, chips, hide, want) => {
    expect(ids(visibleMassRows(ROWS, new Set(chips), hide))).toEqual(want);
  });
});
