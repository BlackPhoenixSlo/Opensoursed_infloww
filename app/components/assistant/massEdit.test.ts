import { describe, expect, it } from "vitest";

import {
  changeLines, diffLine, editApplyBody, editPlanText, editResultsOf, editSlotsFrom, isLiveIncrease, resultHeadline,
  resultLines, type EditDiff, type EditRule, type MassEditSlots,
} from "./massEdit";

const d = (field: EditDiff["field"], before: unknown, after: unknown, label = "L"): EditDiff => ({ field, label, before, after });
const rule = (id: number, model: string, diffs: EditDiff[], is_enabled = true): EditRule => ({
  id, account_id: model.toLowerCase(), account_name: model, name: `Rule ${id}`, is_enabled, version: `v${id}`, diffs,
});
const SLOTS: MassEditSlots = {
  scope: "all", match: null, changes: { unsend_after_hours: 0 }, already: 2,
  skipped: [{ id: 9, name: "Old", account_name: "Bea", reason: "has no message to change" }],
  rules: [rule(1, "Ava", [d("unsend_after_hours", 8, null, "Unsend after")]),
    rule(2, "Ava", [d("unsend_after_hours", 0.5, null, "Unsend after")], false),
    rule(3, "Bea", [d("unsend_after_hours", 24, null, "Unsend after")])],
};

describe("diffLine / changeLines", () => {
  it.each<[EditDiff, string]>([
    [d("unsend_after_hours", 8, null, "Unsend after"), "Unsend after 8h → never"],
    [d("unsend_after_hours", 0.5, 2, "Unsend after"), "Unsend after 30 min → 2h"],
    [d("every_seconds", 3600, 1800, "Every"), "Every 1h → 30 min"],
    [d("online_only", true, false, "Online fans only"), "Online fans only on → off"],
    [d("exclude_last_chat_hours", 1, null, "Skip"), "Skip 1h → off"],
    [d("price", null, 15, "Price"), "Price free → $15"],
    [d("media_count", 1, 3, "Photos per mass"), "Photos per mass 1 → 3"],
    [d("is_enabled", true, false, "Enabled"), "Enabled on → off"],
  ])("%o → %s", (diff, want) => expect(diffLine(diff)).toBe(want));

  it("lists every change in the spec, switch-off last", () => {
    expect(changeLines({ unsend_after_hours: 0, every_seconds: 7200, online_only: false, exclude_last_chat_hours: 0, disable_rule: true }))
      .toEqual(["Unsend after → never", "Every → 2h", "Online fans only → off", "Skip fans chatted with recently → off", "Switch off"]);
  });
});

describe("isLiveIncrease", () => {
  it.each<[string, EditRule, boolean]>([
    ["shorter interval on an enabled rule", rule(1, "A", [d("every_seconds", 3600, 1800)]), true],
    ["longer interval", rule(1, "A", [d("every_seconds", 3600, 7200)]), false],
    ["fewer skip-recent hours", rule(1, "A", [d("exclude_last_chat_hours", 3, null)]), true],
    ["online-only off", rule(1, "A", [d("online_only", true, false)]), true],
    ["a price change", rule(1, "A", [d("price", null, 10)]), true],
    ["unsend off sends no more", rule(1, "A", [d("unsend_after_hours", 8, null)]), false],
    ["switching off", rule(1, "A", [d("is_enabled", true, false)]), false],
    ["a disabled rule is never live", rule(1, "A", [d("every_seconds", 3600, 600)], false), false],
  ])("%s", (_, r, want) => expect(isLiveIncrease(r)).toBe(want));
});

describe("editPlanText", () => {
  it("headline, change, rules grouped per model, already + skipped notes", () => {
    const t = editPlanText(SLOTS);
    expect(t.headline).toBe("3 rules · 2 models");
    expect(t.changes).toEqual(["Unsend after → never"]);
    expect(t.groups.map((g) => [g.model, g.rules.map((r) => r.id)])).toEqual([["Ava", [1, 2]], ["Bea", [3]]]);
    expect(t.groups[0].rules[1].lines).toEqual(["Unsend after 30 min → never"]);
    expect(t.notes).toEqual(["2 rules already set — left alone", "Skipped “Old” (Bea): has no message to change"]);
  });
  it("marks LIVE per rule", () => {
    const t = editPlanText({ ...SLOTS, rules: [rule(1, "A", [d("every_seconds", 3600, 600)]), rule(2, "A", [d("every_seconds", 3600, 600)], false)] });
    expect(t.groups[0].rules.map((r) => r.live)).toEqual([true, false]);
  });
});

describe("apply round trip", () => {
  it("body carries ids + versions and the change spec only", () => {
    expect(editApplyBody("1001", SLOTS)).toEqual({
      account_id: "1001", rules: [{ id: 1, version: "v1" }, { id: 2, version: "v2" }, { id: 3, version: "v3" }],
      changes: { unsend_after_hours: 0 },
    });
  });
  it("results: one per planned rule; a missing answer reads as not changed", () => {
    const res = editResultsOf({ results: [{ id: 1, ok: true }, { id: 3, ok: false, reason: "changed since you saw it" }, "junk"] }, SLOTS);
    expect(res).toEqual([{ id: 1, ok: true }, { id: 2, ok: false, reason: "no answer from the server" },
      { id: 3, ok: false, reason: "changed since you saw it" }]);
    expect(resultHeadline(res)).toBe("Changed 1 of 3 rules");
    expect(resultLines(res, SLOTS).map((l) => l.text)).toEqual([
      "✓ Rule 1 · Ava", "Rule 2 · Ava — no answer from the server", "Rule 3 · Bea — changed since you saw it"]);
    expect(editResultsOf(null, SLOTS).every((r) => !r.ok)).toBe(true);
  });
});

describe("editSlotsFrom", () => {
  it("reads junk defensively", () => {
    expect(editSlotsFrom(null)).toBeNull();
    expect(editSlotsFrom({ rules: [{ id: "x" }, { id: 4, version: "v", account_id: "a" }] })).toEqual({
      scope: "this", match: null, changes: {}, already: 0, skipped: [],
      rules: [{ id: 4, version: "v", account_id: "a", account_name: "a", name: "", is_enabled: false, diffs: [] }],
    });
  });
});
