/**
 * Auto-activate campaign's state (PromoReactivateCard only dispatches): the engine form (switch, dry run, cadence,
 * cap), whether the Settings pop-up is open, and the last error / notice. `ruleToForm` reads a saved
 * `promo_reactivate` rule (none: the defaults, dry run on); `rulePatch` is the save the form makes.
 */

import { isDryRun } from "@/lib/runStats";
import type { AutomationRule } from "@/hooks/useAutomations";

export interface RForm {
  enabled: boolean;
  dryRun: boolean;
  everyMinutes: number;
  maxCycles: number;   // 0 = unlimited
}

export interface ReactivateState {
  form: RForm;
  settings: boolean;
  err: string | null;
  msg: string | null;
}

export type Action =
  | { type: "adopt"; rule: AutomationRule | null }
  | { type: "edit"; patch: Partial<Omit<RForm, "enabled">> }
  | { type: "toggle"; on: boolean }
  | { type: "toggleFailed"; on: boolean; err: string }
  | { type: "openSettings" }
  | { type: "closeSettings"; rule: AutomationRule | null }
  | { type: "saved" }
  | { type: "failed"; err: string }
  | { type: "notice"; msg: string }
  | { type: "clear" };

export function ruleToForm(rule: AutomationRule | null): RForm {
  const p = rule?.payload ?? {};
  return {
    enabled: rule?.is_enabled ?? false,
    dryRun: isDryRun(rule),          // default TRUE
    everyMinutes: rule?.every_seconds ? Math.max(1, Math.round(rule.every_seconds / 60)) : 60,
    maxCycles: typeof p.max_reactivations === "number" ? p.max_reactivations : 0,
  };
}

export const initialState = (rule: AutomationRule | null = null): ReactivateState =>
  ({ form: ruleToForm(rule), settings: false, err: null, msg: null });

/** The rule's schedule and payload as the form has them (at least a minute apart). */
export function rulePatch(form: RForm): { every_seconds: number; payload: { max_reactivations: number; dry_run: boolean } } {
  return {
    every_seconds: Math.max(60, Math.round(form.everyMinutes) * 60),
    payload: { max_reactivations: form.maxCycles, dry_run: form.dryRun },
  };
}

export function reactivateReducer(state: ReactivateState, action: Action): ReactivateState {
  switch (action.type) {
    case "adopt": return { ...state, form: ruleToForm(action.rule) };
    case "edit": return { ...state, form: { ...state.form, ...action.patch } };
    case "toggle": return { ...state, form: { ...state.form, enabled: action.on }, err: null, msg: null };
    case "toggleFailed": return { ...state, form: { ...state.form, enabled: !action.on }, err: action.err };
    case "openSettings": return { ...state, settings: true, err: null, msg: null };
    // Cancel drops the pop-up's edits; the switch keeps what it shows.
    case "closeSettings":
      return { ...state, settings: false, err: null, form: { ...ruleToForm(action.rule), enabled: state.form.enabled } };
    case "saved": return { ...state, settings: false, err: null, msg: "Saved." };
    case "failed": return { ...state, err: action.err, msg: null };
    case "notice": return { ...state, err: null, msg: action.msg };
    case "clear": return { ...state, err: null, msg: null };
  }
}
