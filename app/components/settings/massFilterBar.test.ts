import { describe, expect, it } from "vitest";

import type { MassMessageRow } from "@/hooks/useMassMessages";

import {
  daysToCover, filterMassRows, initialMassFilter, massCsvRows, massFilterReducer, narrowedBy, NO_MASS_FILTERS,
  type MassFilterAction, type MassFilterState,
} from "./massFilterBar";

const NOW = Date.parse("2026-03-15T12:00:00Z");
const run = (actions: MassFilterAction[], from: MassFilterState = initialMassFilter) => actions.reduce(massFilterReducer, from);

describe("massFilterReducer", () => {
  it.each<[string, MassFilterAction[], Partial<MassFilterState>]>([
    ["typing changes the draft only", [{ type: "draft", patch: { q: "hi" } }],
      { draft: { ...NO_MASS_FILTERS, q: "hi" }, applied: NO_MASS_FILTERS, daysBack: 30 }],
    ["Search applies the trimmed draft", [{ type: "draft", patch: { q: "  hi " } }, { type: "apply", now: NOW }],
      { applied: { ...NO_MASS_FILTERS, q: "hi" }, daysBack: 30 }],
    ["a start inside the window keeps it", [{ type: "draft", patch: { from: "2026-03-01" } }, { type: "apply", now: NOW }],
      { daysBack: 30 }],
    ["a start older than the window widens it", [{ type: "draft", patch: { from: "2026-01-20" } }, { type: "apply", now: NOW }],
      { daysBack: 90 }],
    ["a wider pick is never narrowed by Search", [{ type: "daysBack", days: 365 }, { type: "draft", patch: { from: "2026-03-10" } }, { type: "apply", now: NOW }],
      { daysBack: 365 }],
    ["Reset clears draft and filter, keeps the window",
      [{ type: "daysBack", days: 90 }, { type: "draft", patch: { q: "x", to: "2026-03-02" } }, { type: "apply", now: NOW }, { type: "reset" }],
      { draft: NO_MASS_FILTERS, applied: NO_MASS_FILTERS, daysBack: 90 }],
    ["Reset undoes a window a Sending Date widened", [{ type: "draft", patch: { from: "2025-06-01" } }, { type: "apply", now: NOW }, { type: "reset" }],
      { applied: NO_MASS_FILTERS, daysBack: 30, pickedDays: 30 }],
  ])("%s", (_name, actions, want) => {
    expect(run(actions)).toMatchObject(want);
  });
});

describe("daysToCover", () => {
  it.each<[string, number | null]>([
    ["", null],
    ["nope", null],
    ["2026-03-14", 7],
    ["2026-03-01", 30],
    ["2026-01-01", 90],
    ["2025-06-01", 365],
    ["2020-01-01", 365],
  ])("%s -> %s", (from, want) => {
    expect(daysToCover(from, NOW)).toBe(want);
  });
});

const ROWS: MassMessageRow[] = [
  { id: 1, date: "2026-03-10T23:30:00Z", text: "<p>Spring <b>PROMO</b></p>" },
  { id: 2, date: "2026-03-02T12:00:00Z", text: "good morning" },
  { id: 3, date: null, text: "promo, no date" },
  { id: 4, date: "2026-02-20T12:00:00Z", rawText: "raw promo" },
];
const ids = (rows: MassMessageRow[]) => rows.map((r) => r.id);

describe("filterMassRows", () => {
  it.each<[string, Partial<typeof NO_MASS_FILTERS>, string | null, number[]]>([
    ["no filter keeps all", {}, null, [1, 2, 3, 4]],
    ["search over plain text, any case", { q: "promo" }, null, [1, 3, 4]],
    ["date range, UTC", { from: "2026-03-01", to: "2026-03-10" }, "UTC", [1, 2]],
    ["date range in the report zone shifts the day", { from: "2026-03-11" }, "Asia/Tokyo", [1]],
    ["a row with no date fails a date bound", { q: "promo", to: "2026-12-31" }, "UTC", [1, 4]],
  ])("%s", (_name, f, tz, want) => {
    expect(ids(filterMassRows(ROWS, { ...NO_MASS_FILTERS, ...f }, tz))).toEqual(want);
  });
});

describe("massCsvRows", () => {
  it("writes a header and one plain line per row", () => {
    const rows = massCsvRows([
      { id: 1, date: "2026-03-10T12:00:00Z", text: "<b>hi</b>", isFree: false, isCanceled: true, mediaCount: 2,
        sentCount: 10, viewedCount: 4, purchasedCount: 1, earningsCents: 1250, __accountId: "a" },
    ], (id) => (id === "a" ? "Model A" : "?"));
    expect(rows).toEqual([
      ["Message", "Sent at (UTC)", "Status", "Price", "Media", "Sent", "Viewed", "Purchased", "Earnings", "Creator"],
      ["hi", "2026-03-10T12:00:00Z", "Unsent", "Paid", 2, 10, 4, 1, "12.50", "Model A"],
    ]);
  });
});

describe("narrowedBy", () => {
  it.each<[Partial<typeof NO_MASS_FILTERS>, string]>([
    [{}, ""],
    [{ q: "  " }, ""],
    [{ q: "promo" }, " matching your search"],
    [{ to: "2026-03-02" }, " matching your date"],
    [{ q: "promo", from: "2026-03-01" }, " matching your search/date"],
  ])("%o -> %j", (f, want) => {
    expect(narrowedBy({ ...NO_MASS_FILTERS, ...f })).toBe(want);
  });
});
