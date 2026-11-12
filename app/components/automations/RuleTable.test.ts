import { describe, expect, it } from "vitest";

import type { AutomationRunRow } from "@/hooks/useStats";
import { parseStats, runSummary } from "./RuleTable";
import { ruleStatus, runStatus, type PillTone } from "./StatusPill";

const T0 = "2026-10-31T10:00:00Z";
const run = (stats_json: string | null, started_at: string | null = T0): AutomationRunRow => ({
  id: 1, account_id: "a1", kind: "auto_posts", started_at, completed_at: null,
  status: "ok", stats_json, error_text: null,
});

describe("parseStats", () => {
  it.each<[string, string | null, Record<string, unknown> | null]>([
    ["null", null, null],
    ["empty string", "", null],
    ["literal {}", "{}", null],
    ["{} with spaces is an empty object", "{ }", {}],
    ["garbage", "not json", null],
    ["truncated json", '{"sent": 3', null],
    ["array", "[1,2]", null],
    ["json null", "null", null],
    ["number", "42", null],
    ["string", '"ok"', null],
    ["object", '{"sent":3,"dry_run":true}', { sent: 3, dry_run: true }],
  ])("%s", (_, s, want) => {
    expect(parseStats(s)).toEqual(want);
  });
});

describe("runSummary", () => {
  it.each<[string, string | null, string, (string | null)?]>([
    ["no stats", null, ""],
    ["empty stats", "{}", ""],
    ["garbage stats", "{oops", ""],
    ["array stats", "[]", ""],
    ["missing fields", '{"other":1}', ""],
    ["dry run", '{"dry_run":true}', "dry run"],
    ["dry_run false", '{"dry_run":false}', ""],
    ["dry_run string is truthy", '{"dry_run":"false"}', "dry run"],
    ["post id number", '{"of_post_id":123}', "post #123"],
    ["post id string ignored", '{"of_post_id":"123"}', ""],
    ["delete window", '{"delete_at":"2026-10-31T16:00:00Z"}', "auto-deletes after 6 h"],
    ["delete window rounds to 0.1 h", '{"delete_at":"2026-10-31T11:32:00Z"}', "auto-deletes after 1.5 h"],
    ["delete before start ignored", '{"delete_at":"2026-10-31T09:00:00Z"}', ""],
    ["delete_at garbage ignored", '{"delete_at":"soon"}', ""],
    ["delete_at number ignored", '{"delete_at":1730000000}', ""],
    ["delete window without started_at", '{"delete_at":"2026-10-31T16:00:00Z"}', "", null],
    ["sent", '{"sent":3}', "sent 3"],
    ["sent 0 hidden", '{"sent":0}', ""],
    ["sent string ignored", '{"sent":"3"}', ""],
    ["remaining", '{"remaining":2}', "2 left"],
    ["remaining 0 hidden", '{"remaining":0}', ""],
    ["skipped with reason", '{"status":"skipped","reason":"no_media"}', "skipped (no_media)"],
    ["reason without skipped", '{"status":"ok","reason":"no_media"}', ""],
    ["skipped without reason", '{"status":"skipped"}', ""],
    [
      "all bits in order",
      '{"dry_run":true,"of_post_id":7,"delete_at":"2026-10-31T12:00:00Z","sent":5,"remaining":1,"status":"skipped","reason":"cap"}',
      "dry run · post #7 · auto-deletes after 2 h · sent 5 · 1 left · skipped (cap)",
    ],
  ])("%s", (_, stats, want, started = T0) => {
    expect(runSummary(run(stats, started))).toBe(want);
  });
});

describe("ruleStatus", () => {
  const last = (status: string) => ({ status, started_at: T0, completed_at: null, error_text: null, stats: null });
  it.each<[string, boolean, string | null, string, PillTone]>([
    ["off, never run", false, null, "Paused", "warn"],
    ["off beats a failed run", false, "error", "Paused", "warn"],
    ["off beats a running run", false, "running", "Paused", "warn"],
    ["on, never run", true, null, "Active", "ok"],
    ["on, last ok", true, "ok", "Active", "ok"],
    ["on, last skipped", true, "skipped", "Active", "ok"],
    ["on, last failed", true, "error", "Failed", "err"],
    ["on, running", true, "running", "Running", "active"],
  ])("%s", (_, is_enabled, st, label, tone) => {
    const s = ruleStatus({ is_enabled, last_run: st ? last(st) : null });
    expect([s.label, s.tone]).toEqual([label, tone]);
  });
});

describe("runStatus", () => {
  it.each<[string, string, PillTone]>([
    ["ok", "Done", "ok"],
    ["error", "Failed", "err"],
    ["running", "Running", "active"],
    ["skipped", "Skipped", "idle"],
    ["", "Unknown", "idle"],
  ])("%s", (st, label, tone) => {
    const s = runStatus(st);
    expect([s.label, s.tone]).toEqual([label, tone]);
  });
});
