import { describe, expect, it } from "vitest";

import type { AutomationRule } from "@/hooks/useAutomations";
import {
  autoStoriesReducer, buildPayload, buildTrigger, canSubmit, DEFAULT_FORM, ruleToForm, sameForm, saveGap,
  type AutoStoriesAction, type FormState,
} from "./autoStoriesForm";

const run = (actions: AutoStoriesAction[], from: FormState = DEFAULT_FORM) => actions.reduce(autoStoriesReducer, from);
const withFolder: FormState = { ...DEFAULT_FORM, folderId: 11 };

describe("autoStoriesReducer", () => {
  it.each<[string, AutoStoriesAction[], Partial<FormState>]>([
    ["set patches only its fields", [{ type: "set", patch: { mode: "interval", everyHours: 4 } }],
      { mode: "interval", everyHours: 4, times: ["09:00"], perRun: 1 }],
    ["addTime adds 12:00", [{ type: "addTime" }], { times: ["09:00", "12:00"] }],
    ["setTime edits one", [{ type: "addTime" }, { type: "setTime", index: 1, value: "20:00" }], { times: ["09:00", "20:00"] }],
    ["setTime out of range is a no-op", [{ type: "setTime", index: 3, value: "20:00" }], { times: ["09:00"] }],
    ["removeTime drops one", [{ type: "addTime" }, { type: "removeTime", index: 0 }], { times: ["12:00"] }],
    ["load replaces the whole form", [{ type: "set", patch: { perRun: 3 } }, { type: "load", form: withFolder }],
      { folderId: 11, perRun: 1 }],
  ])("%s", (_name, actions, want) => {
    expect(run(actions)).toMatchObject(want);
  });

  it("an out-of-range time edit keeps the same state object", () => {
    expect(autoStoriesReducer(DEFAULT_FORM, { type: "removeTime", index: -1 })).toBe(DEFAULT_FORM);
  });
});

describe("saveGap / canSubmit", () => {
  it.each<[string, FormState, string | null]>([
    ["blank form: no source", DEFAULT_FORM, "Pick a vault folder or an image pool first."],
    ["a folder is enough", withFolder, null],
    ["an image pool is enough", { ...DEFAULT_FORM, mediaIds: [5] }, null],
    ["clock mode needs a time", { ...withFolder, times: [] }, "Add at least one time."],
    ["interval mode needs none", { ...withFolder, mode: "interval", times: [] }, null],
  ])("%s", (_name, form, gap) => {
    expect(saveGap(form)).toBe(gap);
    expect(canSubmit(form)).toBe(gap === null);
  });
});

describe("buildTrigger / buildPayload", () => {
  it.each<[string, FormState, Record<string, unknown>]>([
    ["clock with the tz offset", { ...withFolder, times: ["09:00", "20:00"] },
      { daily_at: ["09:00", "20:00"], tz_offset_minutes: 120, max_runs: undefined }],
    ["interval in whole hours", { ...withFolder, mode: "interval", everyHours: 3.6, maxRuns: 30 },
      { every_seconds: 4 * 3600, max_runs: 30 }],
    ["interval at least an hour", { ...withFolder, mode: "interval", everyHours: 0 }, { every_seconds: 3600, max_runs: undefined }],
  ])("trigger: %s", (_name, form, want) => {
    expect(buildTrigger(form, 120)).toEqual(want);
  });

  it.each<[string, FormState, Record<string, unknown>]>([
    ["defaults", withFolder, { folder_id: 11, per_run: 1, hours_to_live: 6, remove_vault_dupe: true }],
    ["clamped and rounded", { ...withFolder, perRun: 0, hoursToLive: -2 }, { folder_id: 11, per_run: 1, hours_to_live: 0, remove_vault_dupe: true }],
    ["an image pool joins", { ...withFolder, mediaIds: [7, 8] },
      { folder_id: 11, per_run: 1, hours_to_live: 6, remove_vault_dupe: true, media_files: [7, 8] }],
  ])("payload: %s", (_name, form, want) => {
    expect(buildPayload(form)).toEqual(want);
  });
});

describe("ruleToForm / sameForm", () => {
  const rule = {
    id: 1, kind: "auto_stories", is_enabled: false,
    trigger: { every_seconds: 4 * 3600, max_runs: 30 },
    payload: { folder_id: 11, per_run: 2, hours_to_live: 0, remove_vault_dupe: false },
  } as unknown as AutomationRule;

  it("reads a saved interval rule", () => {
    expect(ruleToForm(rule)).toEqual({
      folderId: 11, mediaIds: [], mode: "interval", times: ["09:00"], everyHours: 4, perRun: 2, hoursToLive: 0,
      removeVaultDupe: false, maxRuns: 30, enabled: false,
    });
  });

  it.each<[string, FormState, boolean]>([
    ["equal copies", { ...DEFAULT_FORM, times: ["09:00"] }, true],
    ["a time changed", { ...DEFAULT_FORM, times: ["10:00"] }, false],
    ["enabled flipped", { ...DEFAULT_FORM, enabled: false }, false],
    ["a pool added", { ...DEFAULT_FORM, mediaIds: [1] }, false],
  ])("%s", (_name, form, same) => {
    expect(sameForm(DEFAULT_FORM, form)).toBe(same);
  });
});
