import { describe, expect, it } from "vitest";

import {
  EMPTY_RULE, buildRules, initEditor, rulesReducer, rulesValid, saveRefusal, validateRule,
  type Action, type EditorState, type RuleUI,
} from "@/components/growth/smartListEditorState";
import type { SmartPreview } from "@/hooks/useSmartLists";

const P: SmartPreview = { count: 7, total_fans: 50, sample: [] };
const between = (value: string, value2: string): RuleUI => ({ ...EMPTY_RULE, op: "between", value, value2 });
const rule = (patch: Partial<RuleUI>): RuleUI => ({ ...EMPTY_RULE, ...patch });

describe("validateRule", () => {
  it.each<[string, RuleUI, string | null]>([
    ["a non-between rule", EMPTY_RULE, null],
    ["a between with both bounds", between("10", "50"), null],
    ["a between with equal bounds", between("10", "10"), null],
    ["a between missing the upper bound", between("10", ""), "Enter both bounds"],
    ["a between missing the lower bound", between(" ", "50"), "Enter both bounds"],
    ["a between with a non-number", between("10", "abc"), "Bounds must be numbers"],
    ["a between with upper < lower", between("50", "10"), "The upper bound must be at least the lower one"],
    ["money, empty", rule({ value: " " }), "Enter a value"],
    ["money, not a number", rule({ value: "abc" }), "The value must be a number"],
    ["days, empty", rule({ field: "last_active_days", value: "" }), "Enter a value"],
    ["days, a number", rule({ field: "last_active_days", value: "7" }), null],
    ["date, not a number", rule({ field: "last_purchase_at", op: "within_last", value: "x" }), "The value must be a number"],
    ["date, a between", rule({ field: "last_purchase_at", op: "between", value: "3", value2: "" }), "Enter both bounds"],
    ["recent spend, empty days", rule({ field: "recent_spend", days: "" }), "Enter the number of days"],
    ["recent spend, non-number days", rule({ field: "recent_spend", days: "abc" }), "Enter the number of days"],
    ["recent spend, days", rule({ field: "recent_spend", days: "14" }), null],
    ["enum, any value", rule({ field: "status", op: "==", value: "" }), null],
    ["tag, empty", rule({ field: "tag", op: "has", value: "" }), null],
  ])("%s", (_, r, want) => {
    expect(validateRule(r)).toBe(want);
  });
});

/** A state that has a preview of rev 0's rules. */
const previewed = (): EditorState =>
  rulesReducer(initEditor("Whales", null), { type: "previewed", rev: 0, data: P });

describe("rulesReducer", () => {
  it.each<[string, Action]>([
    ["a value edit", { type: "row", i: 0, patch: { value: "200" } }],
    ["an op edit", { type: "row", i: 0, patch: { op: "<=" } }],
    ["a field change", { type: "field", i: 0, field: "status" }],
    ["the match", { type: "match", match: "any" }],
    ["Add condition", { type: "add" }],
    ["Remove condition", { type: "remove", i: 0 }],
  ])("%s drops the preview and the error, bumps rev", (_, action) => {
    const s = rulesReducer({ ...previewed(), err: "boom" }, action);
    expect(s.preview).toBeNull();
    expect(s.err).toBeNull();
    expect(s.rev).toBe(1);
  });

  it.each<[string, Action, Partial<EditorState> | "same"]>([
    ["a preview error of the rules on screen shows", { type: "previewFailed", rev: 1, message: "x" }, { err: "x" }],
    ["a preview error of older rules is dropped", { type: "previewFailed", rev: 0, message: "x" }, "same"],
    ["preview or save start clears the error", { type: "start" }, { err: null }],
    ["a save error shows", { type: "saveFailed", message: "x" }, { err: "x" }],
    ["a preview answer clears the error", { type: "previewed", rev: 1, data: P }, { preview: P, err: null }],
  ])("%s", (_, action, want) => {
    const s0 = { ...rulesReducer(initEditor("", null), { type: "add" }), err: "old" }; // rev 1
    const s = rulesReducer(s0, action);
    if (want === "same") expect(s).toBe(s0);
    else expect(s).toMatchObject(want);
  });

  it("a name edit keeps the preview (the count does not depend on it) and clears the name error", () => {
    const s = rulesReducer(rulesReducer(previewed(), { type: "saveRefused", reason: "name" }), { type: "name", name: "W2" });
    expect(s).toMatchObject({ name: "W2", nameErr: false, preview: P, rev: 0 });
  });

  it("saveRefused flags only a missing name", () => {
    expect(rulesReducer(initEditor(" ", null), { type: "saveRefused", reason: "name" }).nameErr).toBe(true);
    const named = initEditor("W", null);
    expect(rulesReducer(named, { type: "saveRefused", reason: "rules" })).toBe(named);
  });

  it("the same match is a no-op", () => {
    const s = previewed();
    expect(rulesReducer(s, { type: "match", match: "all" })).toBe(s);
  });

  it("a preview answer for older rules is dropped, never shown", () => {
    const edited = rulesReducer(initEditor("", null), { type: "row", i: 0, patch: { value: "5" } });
    expect(rulesReducer(edited, { type: "previewed", rev: 0, data: P })).toBe(edited);
    expect(rulesReducer(edited, { type: "previewed", rev: 1, data: P }).preview).toBe(P);
  });

  it("a field change resets op, value and value2 to the field's defaults", () => {
    const s0 = rulesReducer(initEditor("", null), { type: "row", i: 0, patch: { op: "between", value2: "9" } });
    expect(rulesReducer(s0, { type: "field", i: 0, field: "status" }).rows[0])
      .toMatchObject({ field: "status", op: "==", value: "active", value2: "" });
  });
});

describe("rulesValid / saveRefusal / buildRules", () => {
  it.each<[string, RuleUI[], boolean]>([
    ["the default row", [EMPTY_RULE], true],
    ["a full between", [between("1", "99")], true],
    ["one half-filled between among valid rows", [EMPTY_RULE, between("1", "")], false],
    ["an inverted between", [between("99", "1")], false],
  ])("%s → %s", (_, rows, want) => {
    expect(rulesValid({ rows })).toBe(want);
  });

  it.each<[string, string, RuleUI[], "name" | "rules" | null]>([
    ["a name and valid rows", "W", [EMPTY_RULE], null],
    ["no name", "  ", [EMPTY_RULE], "name"],
    ["a name and an invalid row", "W", [between("1", "")], "rules"],
    ["no name and an invalid row", "", [between("1", "")], "name"],
  ])("saveRefusal: %s → %s", (_, name, rows, want) => {
    expect(saveRefusal({ name, rows })).toBe(want);
  });

  it("builds the wire rules in cents for money", () => {
    expect(buildRules({ match: "any", rows: [between("1", "99.5")] }))
      .toEqual({ match: "any", rules: [{ field: "lifetime_spend", op: "between", value: [100, 9950] }] });
  });

  it("init reads saved rules back into rows", () => {
    const s = initEditor("Low", { match: "all", rules: [{ field: "lifetime_spend", op: "between", value: [100, 9999] }] });
    expect(s.rows[0]).toMatchObject({ op: "between", value: "1", value2: "99.99" });
    expect(rulesValid(s)).toBe(true);
  });
});
