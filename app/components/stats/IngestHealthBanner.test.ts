/**
 * IngestHealthBanner's strip and row text: `tier` maps an IngestTier to its colours and label, `overallLabel` the
 * strip's sentence (no accounts wins over any tier), `relTime` the "last scan" recency, `truncate` a row's last error,
 * `statusLabel` a row's scan status in words.
 */
import { describe, expect, it } from "vitest";

import { overallLabel, relTime, statusLabel, tier, truncate } from "@/components/stats/IngestHealthBanner";
import type { IngestTier } from "@/hooks/useStats";

describe("tier", () => {
  it.each([
    ["green",  { text: "text-ok",   dot: "bg-ok",   label: "Healthy" }],
    ["yellow", { text: "text-warn", dot: "bg-warn", label: "Watching" }],
    ["red",    { text: "text-err",  dot: "bg-err",  label: "Action needed" }],
  ] as const)("%s", (t, want) => {
    expect(tier(t)).toEqual(want);
  });
});

describe("overallLabel", () => {
  it.each<[IngestTier, number, string]>([
    ["green",  0, "No accounts bound"],
    ["yellow", 0, "No accounts bound"],
    ["red",    0, "No accounts bound"],
    ["green",  1, "All accounts up to date."],
    ["yellow", 1, "One or more accounts behind."],
    ["red",    1, "Ingest paused or erroring."],
    ["green",  12, "All accounts up to date."],
    ["yellow", 12, "One or more accounts behind."],
    ["red",    12, "Ingest paused or erroring."],
  ])("%s × %i", (t, count, want) => {
    expect(overallLabel(t, count)).toBe(want);
  });
});

describe("relTime", () => {
  const AT = "2026-10-15T12:00:00Z";
  it.each([
    // mins,  lastScanAt, text
    [null,    null, "Never scanned"],
    [5,       null, "Never scanned"],
    [null,    AT,   "—"],
    [-3,      AT,   "just now"],
    [0,       AT,   "just now"],
    [0.9,     AT,   "just now"],
    [1,       AT,   "1m ago"],
    [59,      AT,   "59m ago"],
    [59.9,    AT,   "59m ago"],
    [60,      AT,   "1h ago"],
    [1439,    AT,   "23h ago"],
    [1440,    AT,   "1d ago"],
    [2879,    AT,   "1d ago"],
    [2880,    AT,   "2d ago"],
  ] as const)("%s, %s → %s", (mins, at, want) => {
    expect(relTime(mins, at)).toBe(want);
  });
});

describe("truncate", () => {
  it.each([
    // s,                n (default 120), out
    ["abcd",             5,         "abcd"],
    ["abcde",            5,         "abcde"],
    ["abcdef",           5,         "abcd…"],
    ["",                 5,         ""],
    ["x".repeat(119),    undefined, "x".repeat(119)],
    ["x".repeat(120),    undefined, "x".repeat(120)],
    ["x".repeat(121),    undefined, "x".repeat(119) + "…"],
  ] as const)("%#: n=%s", (s, n, want) => {
    expect(truncate(s, n)).toBe(want);
  });
});

describe("statusLabel", () => {
  it.each([
    ["backfill_partial", "backfilling · still working"],
    ["backfill_stalled", "backfill stalled"],
    ["backfill_given_up", "backfill gave up"],
    ["full_walk_failed", "full walk failing"],
    ["error", "error"],
  ])("%s", (status, want) => {
    expect(statusLabel(status)).toBe(want);
  });
});
