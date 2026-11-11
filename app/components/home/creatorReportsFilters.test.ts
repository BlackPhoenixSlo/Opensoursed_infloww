import { describe, expect, it } from "vitest";
import { type Action, type CreatorReportsFilters, INITIAL_FILTERS, creatorReportsFiltersReducer } from "./creatorReportsFilters";

const picked = new Set(["acct-a"]);
const custom = { from: "2026-10-01", to: "2026-10-14" };

describe("creatorReportsFiltersReducer", () => {
  const cases: { name: string; from: CreatorReportsFilters; action: Action; to: CreatorReportsFilters }[] = [
    {
      name: "a preset keeps the custom days",
      from: { ...INITIAL_FILTERS, preset: "custom", custom },
      action: { type: "preset", preset: "last7" },
      to: { ...INITIAL_FILTERS, preset: "last7", custom },
    },
    {
      name: "custom days are kept",
      from: INITIAL_FILTERS,
      action: { type: "custom", ...custom },
      to: { ...INITIAL_FILTERS, preset: "custom", custom },
    },
    {
      name: "a range change leaves the Creators and the bucket alone",
      from: { ...INITIAL_FILTERS, selectedIds: picked, gran: "week" },
      action: { type: "preset", preset: "last90" },
      to: { ...INITIAL_FILTERS, preset: "last90", selectedIds: picked, gran: "week" },
    },
    {
      name: "select picks Creators",
      from: INITIAL_FILTERS,
      action: { type: "select", ids: picked },
      to: { ...INITIAL_FILTERS, selectedIds: picked },
    },
    {
      name: "select null is every Creator",
      from: { ...INITIAL_FILTERS, selectedIds: picked },
      action: { type: "select", ids: null },
      to: INITIAL_FILTERS,
    },
    {
      name: "gran is the one bucket",
      from: INITIAL_FILTERS,
      action: { type: "gran", gran: "month" },
      to: { ...INITIAL_FILTERS, gran: "month" },
    },
    {
      name: "reset puts range, Creators and bucket back together, keeping the typed days",
      from: { preset: "custom", custom, selectedIds: picked, gran: "hour" },
      action: { type: "reset" },
      to: { ...INITIAL_FILTERS, custom },
    },
  ];
  it.each(cases)("$name", ({ from, action, to }) => {
    expect(creatorReportsFiltersReducer(from, action)).toEqual(to);
  });

  it("starts on the last 30 days, every Creator, Day", () => {
    expect(INITIAL_FILTERS).toEqual({ preset: "last30", custom: { from: null, to: null }, selectedIds: null, gran: "day" });
  });
});
