/**
 * The Auto Story form (AutoStoriesTab, /growth/auto-story): its state, a pure reducer (the page only dispatches —
 * a person's clicks and the help bot's "Do it for me" steps alike, docs/spec/assistant-do-mode.md D13), `saveGap` /
 * `canSubmit` (Save's own gate), `buildTrigger` / `buildPayload` (what Save stores) and `sameForm` (dirty or not).
 */

import type { AutomationRule } from "@/hooks/useAutomations";
import { boolKnob } from "@/lib/boolKnob";

export type Mode = "clock" | "interval";

export interface FormState {
  folderId: number | null;
  mediaIds: number[];       // explicit image pool — combines with the folder
  mode: Mode;
  times: string[];          // ["09:00", …] for clock mode
  everyHours: number;       // interval mode
  perRun: number;
  hoursToLive: number;      // 0 = keep
  removeVaultDupe: boolean; // hide the re-uploaded vault copy (default ON)
  maxRuns: number | null;   // null = run forever
  enabled: boolean;
}

export const DEFAULT_FORM: FormState = {
  folderId: null,
  mediaIds: [],
  mode: "clock",
  times: ["09:00"],
  everyHours: 6,
  perRun: 1,
  hoursToLive: 6,
  removeVaultDupe: true,
  maxRuns: null,
  enabled: true,
};

/** The time "Add time" adds. */
export const NEW_TIME = "12:00";

export type AutoStoriesAction =
  /** The saved rule (or the blank form) loaded into the form. */
  | { type: "load"; form: FormState }
  | { type: "set"; patch: Partial<FormState> }
  | { type: "addTime" }
  | { type: "setTime"; index: number; value: string }
  | { type: "removeTime"; index: number };

export function autoStoriesReducer(s: FormState, a: AutoStoriesAction): FormState {
  switch (a.type) {
    case "load":
      return a.form;
    case "set":
      return { ...s, ...a.patch };
    case "addTime":
      return { ...s, times: [...s.times, NEW_TIME] };
    case "setTime":
      if (a.index < 0 || a.index >= s.times.length) return s;
      return { ...s, times: s.times.map((t, i) => (i === a.index ? a.value : t)) };
    case "removeTime":
      if (a.index < 0 || a.index >= s.times.length) return s;
      return { ...s, times: s.times.filter((_, i) => i !== a.index) };
  }
}

export function ruleToForm(rule: AutomationRule): FormState {
  const t = rule.trigger ?? {};
  const p = rule.payload ?? {};
  const clock = Array.isArray(t.daily_at) && t.daily_at.length > 0;
  return {
    folderId: typeof p.folder_id === "number" ? p.folder_id : null,
    mediaIds: Array.isArray(p.media_files)
      ? (p.media_files as unknown[]).filter((x): x is number => typeof x === "number")
      : [],
    mode: clock ? "clock" : "interval",
    times: clock ? (t.daily_at as string[]) : ["09:00"],
    everyHours: t.every_seconds ? Math.max(1, Math.round(t.every_seconds / 3600)) : 6,
    perRun: typeof p.per_run === "number" ? p.per_run : 1,
    hoursToLive: typeof p.hours_to_live === "number" ? p.hours_to_live : 0,
    // Default ON: only an explicit `false` opts a rule out. Through `boolKnob`,
    // because `auto_stories` reads the same key through `_common.bool_knob` —
    // and this pair used to be the one that disagreed (see the ⚠️ beside
    // `remove_dupe` in auto_stories.py).
    removeVaultDupe: boolKnob(p.remove_vault_dupe, true),
    maxRuns: typeof t.max_runs === "number" ? t.max_runs : null,
    enabled: rule.is_enabled,
  };
}

/** Why Save refuses this form, or null. */
export function saveGap(f: FormState): string | null {
  if (!f.folderId && f.mediaIds.length === 0) return "Pick a vault folder or an image pool first.";
  if (f.mode === "clock" && f.times.length === 0) return "Add at least one time.";
  return null;
}

export const canSubmit = (f: FormState): boolean => saveGap(f) === null;

/** `tzOffsetMinutes`: minutes to add to UTC for the user's local time (+120 for UTC+2); clock mode stores it. */
export function buildTrigger(f: FormState, tzOffsetMinutes: number) {
  const max_runs = f.maxRuns && f.maxRuns > 0 ? f.maxRuns : undefined;
  if (f.mode === "clock") {
    return { daily_at: f.times, tz_offset_minutes: tzOffsetMinutes, max_runs };
  }
  return { every_seconds: Math.max(1, Math.round(f.everyHours)) * 3600, max_runs };
}

export function buildPayload(f: FormState): Record<string, unknown> {
  const p: Record<string, unknown> = {
    folder_id: f.folderId,
    per_run: Math.max(1, Math.round(f.perRun)),
    hours_to_live: Math.max(0, Math.round(f.hoursToLive)),
    remove_vault_dupe: f.removeVaultDupe,
  };
  // Explicit image pool combines with the folder (backend unions them).
  if (f.mediaIds.length) p.media_files = f.mediaIds;
  return p;
}

/** Same form, field by field (an unsaved edit = not the same as what was loaded). */
export function sameForm(a: FormState, b: FormState): boolean {
  const same = (x: unknown[], y: unknown[]) => x.length === y.length && x.every((v, i) => v === y[i]);
  return a.folderId === b.folderId && same(a.mediaIds, b.mediaIds) && a.mode === b.mode && same(a.times, b.times)
    && a.everyHours === b.everyHours && a.perRun === b.perRun && a.hoursToLive === b.hoursToLive
    && a.removeVaultDupe === b.removeVaultDupe && a.maxRuns === b.maxRuns && a.enabled === b.enabled;
}
