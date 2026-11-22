import { describe, expect, it } from "vitest";

import {
  diffLine, editApplyBody, editPlanText, editResultsOf, editSlotsFrom, isLive, resultHeadline,
  resultLines, type EditDiff, type EditRule, type MassEditSlots,
} from "./massEdit";

const d = (field: EditDiff["field"], text: string, live = false, label = "L"): EditDiff => ({ field, label, text, live });
const rule = (id: number, model: string, diffs: EditDiff[], is_enabled = true): EditRule => ({
  id, account_id: model.toLowerCase(), account_name: model, name: `Rule ${id}`, is_enabled, version: `v${id}`, diffs,
});
const SLOTS: MassEditSlots = {
  scope: "all", match: null, changes: { unsend_after_hours: 0 }, change_lines: ["Unsend after → never"], already: 2,
  skipped: [{ id: 9, name: "Old", account_name: "Bea", reason: "has no message to change" }],
  rules: [rule(1, "Ava", [d("unsend_after_hours", "Unsend after 8h → never")]),
    rule(2, "Ava", [d("unsend_after_hours", "Unsend after 30 min → never")], false),
    rule(3, "Bea", [d("unsend_after_hours", "Unsend after 24h → never")])],
};

describe("diffLine (rwl W30 F12: the server's text, never re-formatted)", () => {
  it("shows the server line verbatim — every prior value with its count included", () => {
    expect(diffLine(d("price", "Price $5 (1 message), $50 (2 messages) → $10")))
      .toBe("Price $5 (1 message), $50 (2 messages) → $10");
  });
});

// rwl W30 S1: the server judges LIVE over every message's prior value; the card only shows it.
describe("isLive", () => {
  it.each<[string, EditRule, boolean]>([
    ["a diff the server marked live", rule(1, "A", [d("online_only", "Online only on (1), off (1) → off", true)]), true],
    ["one live diff among several", rule(1, "A", [d("unsend_after_hours", "x"), d("price", "y", true)]), true],
    ["none live", rule(1, "A", [d("unsend_after_hours", "x"), d("is_enabled", "y")]), false],
    ["no diffs", rule(1, "A", []), false],
  ])("%s", (_, r, want) => expect(isLive(r)).toBe(want));
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
  it.each<[string, number, string[]]>([
    ["3 skips: all named", 3, ["Skipped “R0”: why", "Skipped “R1”: why", "Skipped “R2”: why"]],
    ["4 skips: 3 named, 1 counted", 4, ["Skipped “R0”: why", "Skipped “R1”: why", "Skipped “R2”: why", "1 more rule skipped"]],
    ["500 skips: 3 named, the rest counted (rwl W30 D1)", 500,
      ["Skipped “R0”: why", "Skipped “R1”: why", "Skipped “R2”: why", "497 more rules skipped"]],
  ])("skips: %s", (_name, n, want) => {
    const skipped = Array.from({ length: n }, (_, i) => ({ id: i, name: `R${i}`, account_id: "a", account_name: "", reason: "why" }));
    expect(editPlanText({ ...SLOTS, already: 0, skipped }).notes).toEqual(want);
  });
  it("marks LIVE per rule", () => {
    const t = editPlanText({ ...SLOTS, rules: [rule(1, "A", [d("every_seconds", "Every 1h → 10 min", true)]),
      rule(2, "A", [d("every_seconds", "Every 1h → 10 min")], false)] });
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
  it("a diff without the server's text (or an unknown field) is dropped, never shown as a bare label", () => {
    const s = editSlotsFrom({ rules: [{ id: 1, version: "v", account_id: "a", diffs: [
      { field: "price", label: "Price", before: 5, after: 10 },
      { field: "price", label: "Price", text: "Price $5 → $10", live: true },
      { field: "nope", label: "N", text: "x", live: true },
      { field: "media_count", label: "Photos", text: "Photos 1 → 3", live: "yes" }] }] });
    expect(s!.rules[0].diffs).toEqual([{ field: "price", label: "Price", text: "Price $5 → $10", live: true },
      { field: "media_count", label: "Photos", text: "Photos 1 → 3", live: false }]);
  });
  it("reads junk defensively", () => {
    expect(editSlotsFrom(null)).toBeNull();
    expect(editSlotsFrom({ rules: [{ id: "x" }, { id: 4, version: "v", account_id: "a" }] })).toEqual({
      scope: "this", match: null, changes: {}, change_lines: [], already: 0, skipped: [],
      rules: [{ id: 4, version: "v", account_id: "a", account_name: "a", name: "", is_enabled: false, diffs: [] }],
    });
  });
});
