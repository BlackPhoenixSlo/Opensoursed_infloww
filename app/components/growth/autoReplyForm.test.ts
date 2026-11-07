import { describe, expect, it } from "vitest";

import { unsaved } from "@/components/automations/sentDraft";
import type { AutoreplyConfig } from "@/hooks/useAutoreplyConfig";
import {
  answersWith, autoReplyReducer, brainPayload, brainSeed, buildPayload, canSubmit, draftFromConfig, effortChoices,
  initState, randomiseOn, type AutoReplyAction, type AutoReplyDraft, type AutoReplyEdit, type BrainPick, type NumberKey,
} from "./autoReplyForm";

/** service/automations/autoreply.py `_defaults()`. */
const DEFAULTS: AutoreplyConfig = {
  enabled: false, silence_min_minutes: 24, silence_max_minutes: 1115, step_in_max_minutes: 0,
  max_nudges: 1, min_gap_minutes: 5, last_n_messages: 12, quiet_hours_json: null,
  info_not_required: true, folders_enabled: true, list_ids: [], folder_max_spend_cents: null,
  new_fans_enabled: false, new_fan_hours: 72, new_fan_max_spend_cents: 1_000,
  describe_photos: false, skip_photo_only: false,
};

/** The draft after `actions`, from `from`. */
const run = (actions: AutoReplyEdit[], from: AutoReplyDraft = draftFromConfig(DEFAULTS)) =>
  actions.reduce(autoReplyReducer, { draft: from, sent: null }).draft;

describe("round trip: buildPayload(draftFromConfig(c), c) = c", () => {
  it.each<[string, AutoreplyConfig]>([
    ["engine defaults", DEFAULTS],
    ["all on", {
      ...DEFAULTS, enabled: true, silence_min_minutes: 10, step_in_max_minutes: 20,
      list_ids: [11, 22, 33], folder_max_spend_cents: 12_345, new_fans_enabled: true,
      new_fan_hours: 48, new_fan_max_spend_cents: 2_550, describe_photos: true, skip_photo_only: true,
      quiet_hours_json: [2, 7],
    }],
    ["delay 0, fixed", { ...DEFAULTS, enabled: true, silence_min_minutes: 0, step_in_max_minutes: 0 }],
    ["API bounds (delay past the page's 240, top spend caps, 1h / 8760h windows)", {
      ...DEFAULTS, silence_min_minutes: 1440, step_in_max_minutes: 2880, folder_max_spend_cents: 10_000_000,
      new_fan_hours: 8760, new_fan_max_spend_cents: 10_000_000,
    }],
    ["zero caps, 1h window, folders off", {
      ...DEFAULTS, folders_enabled: false, folder_max_spend_cents: 0, new_fans_enabled: true,
      new_fan_hours: 1, new_fan_max_spend_cents: 0,
    }],
    ["odd cents", { ...DEFAULTS, folder_max_spend_cents: 1, new_fan_max_spend_cents: 99_999 }],
  ])("%s", (_name, c) => {
    expect(buildPayload(draftFromConfig(c), c)).toEqual(c);
  });

  it("keeps every stored key the page does not edit; the PUT body carries even unknown ones (the API drops them)", () => {
    const stored = { ...DEFAULTS, max_nudges: 3, quiet_hours_json: [22, 6], future_knob: "x" } as AutoreplyConfig;
    expect(buildPayload(draftFromConfig(stored), stored)).toEqual(stored);
  });

  it("a sparse stored blob is filled from the effective config", () => {
    const stored: AutoreplyConfig = { enabled: true };
    const out = buildPayload(draftFromConfig({ ...DEFAULTS, ...stored }), stored);
    expect(out).toEqual({
      enabled: true, silence_min_minutes: 24, step_in_max_minutes: 0, folders_enabled: true, list_ids: [],
      folder_max_spend_cents: null, new_fans_enabled: false, new_fan_hours: 72, new_fan_max_spend_cents: 1_000,
      describe_photos: false, skip_photo_only: false,
    });
  });

  it.each<[string, Partial<AutoreplyConfig>, number]>([
    // A range the page cannot express is normalised to [d, 2d] on save (unchanged from before).
    ["a non-2x range", { silence_min_minutes: 10, step_in_max_minutes: 30 }, 20],
    ["equal = no spread", { silence_min_minutes: 10, step_in_max_minutes: 10 }, 0],
    ["a range over a 0 delay", { silence_min_minutes: 0, step_in_max_minutes: 15 }, 0],
  ])("step-in: %s", (_name, c, want) => {
    const cfg = { ...DEFAULTS, ...c };
    expect(buildPayload(draftFromConfig(cfg), cfg).step_in_max_minutes).toBe(want);
  });
});

describe("edits", () => {
  it("each edit lands in its payload field", () => {
    const s = run([
      { type: "switch", k: "enabled", on: true },
      { type: "number", k: "delay", raw: "7" },
      { type: "switch", k: "randomise", on: true },
      { type: "toggleFolder", id: "22" },
      { type: "toggleFolder", id: "11" },
      { type: "switch", k: "capOn", on: true },
      { type: "number", k: "cap", raw: "12.5" },
      { type: "switch", k: "newOn", on: true },
      { type: "number", k: "newHours", raw: "48" },
      { type: "number", k: "newMax", raw: "3" },
      { type: "switch", k: "describe", on: true },
      { type: "switch", k: "skipPhotoOnly", on: true },
    ]);
    expect(buildPayload(s, DEFAULTS)).toEqual({
      ...DEFAULTS, enabled: true, silence_min_minutes: 7, step_in_max_minutes: 14, list_ids: [22, 11],
      folder_max_spend_cents: 1_250, new_fans_enabled: true, new_fan_hours: 48, new_fan_max_spend_cents: 300,
      describe_photos: true, skip_photo_only: true,
    });
  });

  it("toggleFolder twice unticks", () => {
    const s = run([{ type: "toggleFolder", id: "11" }, { type: "toggleFolder", id: "11" }]);
    expect(s.folders.size).toBe(0);
  });

  it.each<{ k: NumberKey; raw: string; want: number }>([
    { k: "delay", raw: "7", want: 7 },
    { k: "delay", raw: "300", want: 240 },
    { k: "delay", raw: "-5", want: 0 },
    { k: "newHours", raw: "0", want: 1 },
    { k: "newHours", raw: "9000", want: 8760 },
    { k: "newHours", raw: "", want: 1 },
    { k: "newHours", raw: "abc", want: 1 },
    { k: "cap", raw: "200000", want: 100_000 },
    { k: "newMax", raw: "-1", want: 0 },
  ])("number $k='$raw' is clamped to $want", ({ k, raw, want }) => {
    expect(run([{ type: "number", k, raw }])[k]).toBe(want);
  });

  it("randomise is kept but off at delay 0, and back when the delay is", () => {
    const s0 = run([{ type: "number", k: "delay", raw: "5" }, { type: "switch", k: "randomise", on: true },
      { type: "number", k: "delay", raw: "0" }]);
    expect(randomiseOn(s0)).toBe(false);
    expect(buildPayload(s0, DEFAULTS).step_in_max_minutes).toBe(0);
    const s1 = run([{ type: "number", k: "delay", raw: "6" }], s0);
    expect(randomiseOn(s1)).toBe(true);
    expect(buildPayload(s1, DEFAULTS).step_in_max_minutes).toBe(12);
  });

  it("every edit returns a new draft (the page's Saved reads draft === the draft sent)", () => {
    const d = draftFromConfig(DEFAULTS);
    expect(run([{ type: "switch", k: "enabled", on: false }], d)).not.toBe(d);
  });
});

describe("unsaved: 'Saved' only while nothing changed since the last Save sent", () => {
  const delay: AutoReplyAction = { type: "number", k: "delay", raw: "9" };
  it.each<[string, AutoReplyAction[], boolean]>([
    ["no Save yet", [], true],
    ["an edit, no Save yet", [delay], true],
    ["Save", [{ type: "saved" }], false],
    ["edit then Save", [delay, { type: "saved" }], false],
    ["Save, then an edit while it is in flight", [{ type: "saved" }, delay], true],
    ["Save, an edit, Save again", [{ type: "saved" }, delay, { type: "saved" }], false],
    ["an edit back to the sent value still counts", [{ type: "saved" },
      { type: "switch", k: "enabled", on: true }, { type: "switch", k: "enabled", on: false }], true],
  ])("%s", (_name, actions, want) => {
    expect(unsaved(actions.reduce(autoReplyReducer, initState(DEFAULTS)))).toBe(want);
  });

  it("saved keeps the draft", () => {
    const s = initState(DEFAULTS);
    expect(autoReplyReducer(s, { type: "saved" }).draft).toBe(s.draft);
  });
});

describe("canSubmit", () => {
  it.each<[string, Partial<AutoReplyDraft>, boolean]>([
    ["on, folders only", { enabled: true, foldersOn: true, newOn: false }, true],
    ["on, new fans only", { enabled: true, foldersOn: false, newOn: true }, true],
    ["on, both", { enabled: true, foldersOn: true, newOn: true }, true],
    ["on, neither: nobody qualifies", { enabled: true, foldersOn: false, newOn: false }, false],
    ["off, neither: nothing runs, may save", { enabled: false, foldersOn: false, newOn: false }, true],
  ])("%s", (_name, patch, want) => {
    expect(canSubmit({ ...draftFromConfig(DEFAULTS), ...patch })).toBe(want);
  });
});

/** A slice of account_config_api's GET: the house model, one model with efforts, one without. */
const BRAIN = (model: string | null, reasoning_effort: string | null = ""): BrainPick => ({
  default_model: "deepseek-v4-flash",
  model_options: ["deepseek-v4-flash", "deepseek-v4-pro", "claude-opus-5-5"],
  effort_options: { "deepseek-v4-flash": [], "deepseek-v4-pro": ["low", "medium", "high"], "claude-opus-5-5": [] },
  config: { model, reasoning_effort },
});

describe("model: the account's reply model", () => {
  it.each<[string, BrainPick | null, string, string]>([
    ["no config read: Default", null, "", ""],
    ["null: Default", BRAIN(null), "", ""],
    ["a pin", BRAIN("claude-opus-5-5"), "claude-opus-5-5", ""],
    ["a pin with its served effort", BRAIN("deepseek-v4-pro", "high"), "deepseek-v4-pro", "high"],
    ["a retired id runs the default", BRAIN("grok-4-1-fast", "high"), "", ""],
    ["an effort the model does not take", BRAIN("claude-opus-5-5", "high"), "claude-opus-5-5", ""],
  ])("seed: %s", (_n, b, model, effort) => {
    expect(brainSeed(b)).toEqual({ model, effort });
    expect(draftFromConfig(DEFAULTS, b)).toMatchObject({ model, effort });
  });

  it.each<[string, BrainPick, AutoReplyEdit[], string, string[], string]>([
    ["Default answers with the server's default; no effort", BRAIN(null), [], "deepseek-v4-flash", [], ""],
    ["pick claude", BRAIN(null), [{ type: "model", model: "claude-opus-5-5" }], "claude-opus-5-5", [], ""],
    ["pick pro: its efforts", BRAIN(null), [{ type: "model", model: "deepseek-v4-pro" }],
      "deepseek-v4-pro", ["low", "medium", "high"], ""],
    ["a new model resets effort to its pin", BRAIN("deepseek-v4-pro", "high"),
      [{ type: "model", model: "deepseek-v4-pro" }], "deepseek-v4-pro", ["low", "medium", "high"], ""],
    ["effort edit", BRAIN("deepseek-v4-pro"), [{ type: "effort", effort: "low" }],
      "deepseek-v4-pro", ["low", "medium", "high"], "low"],
  ])("%s", (_n, b, actions, runs, efforts, effort) => {
    const d = run(actions, draftFromConfig(DEFAULTS, b));
    expect(answersWith(d, b)).toBe(runs);
    expect(effortChoices(d, b)).toEqual(efforts);
    expect(d.effort).toBe(effort);
  });

  it.each<[string, BrainPick, AutoReplyEdit[], { model: string | null; reasoning_effort: string | null } | null]>([
    ["untouched: no PUT", BRAIN("claude-opus-5-5"), [], null],
    ["re-picked the same: no PUT", BRAIN("claude-opus-5-5"), [{ type: "model", model: "claude-opus-5-5" }], null],
    ["retired id untouched: no PUT", BRAIN("grok-4-1-fast"), [], null],
    ["Default -> claude", BRAIN(null), [{ type: "model", model: "claude-opus-5-5" }],
      { model: "claude-opus-5-5", reasoning_effort: null }],
    ["claude -> Default = null", BRAIN("claude-opus-5-5"), [{ type: "model", model: "" }],
      { model: null, reasoning_effort: null }],
    ["effort only", BRAIN("deepseek-v4-pro", "high"), [{ type: "effort", effort: "low" }],
      { model: "deepseek-v4-pro", reasoning_effort: "low" }],
  ])("brainPayload: %s", (_n, b, actions, want) => {
    const d = run(actions, draftFromConfig(DEFAULTS, b));
    const out = brainPayload(d, b);
    expect(out && { model: out.model, reasoning_effort: out.reasoning_effort }).toEqual(want);
  });

  it("echoes the rest of the stored brain (the PUT replaces it)", () => {
    const b = { ...BRAIN(null), config: { model: null, reasoning_effort: "", persona: "Ella.", cotag_username: "x" } };
    const d = run([{ type: "model", model: "claude-opus-5-5" }], draftFromConfig(DEFAULTS, b));
    expect(brainPayload(d, b)).toEqual({ model: "claude-opus-5-5", reasoning_effort: null, persona: "Ella.", cotag_username: "x" });
  });

  it("model edits leave the autoreply blob alone and count as unsaved", () => {
    const s0 = initState(DEFAULTS, BRAIN(null));
    const s1 = autoReplyReducer(autoReplyReducer(s0, { type: "saved" }), { type: "model", model: "claude-opus-5-5" });
    expect(unsaved(s1)).toBe(true);
    expect(buildPayload(s1.draft, DEFAULTS)).toEqual(buildPayload(s0.draft, DEFAULTS));
  });
});
