import { describe, expect, it } from "vitest";

import type { AutomationRule } from "@/hooks/useAutomations";
import { initialState, reactivateReducer, rulePatch, ruleToForm, type ReactivateState } from "./promoReactivateForm";

const rule = (over: Partial<AutomationRule> = {}) => ({
  id: 9, kind: "promo_reactivate", is_enabled: true, every_seconds: 1800,
  payload: { dry_run: false, max_reactivations: 3 }, ...over,
}) as AutomationRule;

describe("ruleToForm", () => {
  it.each([
    ["no rule: off, dry run on, hourly, no cap", null, { enabled: false, dryRun: true, everyMinutes: 60, maxCycles: 0 }],
    ["a saved rule", rule(), { enabled: true, dryRun: false, everyMinutes: 30, maxCycles: 3 }],
    ["a rule with no dry_run knob stays dry", rule({ payload: {} }), { enabled: true, dryRun: true, everyMinutes: 30, maxCycles: 0 }],
  ])("%s", (_, r, want) => expect(ruleToForm(r)).toEqual(want));
});

describe("rulePatch", () => {
  it.each([
    [30, { every_seconds: 1800 }],
    [0, { every_seconds: 60 }],
    [1.4, { every_seconds: 60 }],
  ])("every %s min", (everyMinutes, want) =>
    expect(rulePatch({ enabled: true, dryRun: true, everyMinutes, maxCycles: 2 }))
      .toEqual({ ...want, payload: { max_reactivations: 2, dry_run: true } }));
});

describe("reactivateReducer", () => {
  const open: ReactivateState = { ...initialState(rule()), settings: true };
  it.each<[string, ReactivateState, Parameters<typeof reactivateReducer>[1], Partial<ReactivateState>]>([
    ["toggle sets the switch and clears notes", { ...initialState(), err: "x", msg: "y" }, { type: "toggle", on: true },
      { form: { ...initialState().form, enabled: true }, err: null, msg: null }],
    ["a failed toggle flips back with the error", { ...initialState(), form: { ...initialState().form, enabled: true } },
      { type: "toggleFailed", on: true, err: "boom" }, { form: initialState().form, err: "boom" }],
    ["openSettings opens and clears", { ...initialState(), msg: "Saved." }, { type: "openSettings" },
      { settings: true, msg: null, err: null }],
    ["Cancel drops edits but keeps the switch", { ...open, form: { ...open.form, enabled: false, everyMinutes: 5 } },
      { type: "closeSettings", rule: rule() }, { settings: false, form: { ...ruleToForm(rule()), enabled: false } }],
    ["saved closes with a notice", open, { type: "saved" }, { settings: false, msg: "Saved." }],
    ["failed keeps the pop-up open", open, { type: "failed", err: "Save failed" }, { settings: true, err: "Save failed" }],
    ["edit patches the knobs", open, { type: "edit", patch: { dryRun: true, maxCycles: 0 } },
      { form: { ...open.form, dryRun: true, maxCycles: 0 } }],
  ])("%s", (_, state, action, want) => expect(reactivateReducer(state, action)).toMatchObject(want));
});
