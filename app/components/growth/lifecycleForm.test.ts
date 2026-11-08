import { describe, expect, it } from "vitest";

import type { LifecycleMessageConfig } from "@/hooks/useLifecycleMessageConfig";

import {
  buildPayload, canSubmit, initLifecycle, lifecycleIssues, lifecycleReducer,
  type LifecycleAction, type LifecycleDraft, type LifecycleRules,
} from "./lifecycleForm";

const EXAMPLE = "Default script";
const CONFIG: LifecycleMessageConfig = {
  enabled: false, text: "", hours: null, messages: [],
  media_ids: [], price_cents: 0, starts_at: null, ends_at: null, unsend_minutes: 0, frequency: "once",
};
const cfg = (over: Partial<LifecycleMessageConfig> = {}) => ({ ...CONFIG, ...over });
const run = (actions: LifecycleAction[], init = cfg()): LifecycleDraft =>
  actions.reduce(lifecycleReducer, initLifecycle(init, EXAMPLE));
const EXPIRY: LifecycleRules = { hours: { min: 1, max: 120 }, refusal: null };
const PLAIN: LifecycleRules = { refusal: null };
/** The extras a default draft collects (frequency on, as the old inline code asked). */
const EXTRAS = { media_ids: [], price_cents: 0, starts_at: null, ends_at: null, unsend_minutes: 0, frequency: "once" };

describe("initLifecycle", () => {
  it.each<[string, LifecycleMessageConfig, string[][]]>([
    ["nothing saved: Infloww's default script", cfg(), [[EXAMPLE]]],
    ["an older config with only text", cfg({ text: "old" }), [["old"]]],
    ["saved messages win; an empty variant list is one blank",
      cfg({ messages: [{ variants: ["a", "b"], follow_ups: [], discount: null }, { variants: [], follow_ups: [], discount: null }] }),
      [["a", "b"], [""]]],
  ])("%s", (_, c, variants) => {
    expect(initLifecycle(c, EXAMPLE).messages.map((m) => m.variants)).toEqual(variants);
  });
  it("hours default to 24; a saved discount's months become text", () => {
    const s = initLifecycle(cfg({ hours: 48, messages: [{ variants: ["a"], follow_ups: [{ text: "f", delay_minutes: 30 }],
      discount: { percent: 20, months: 3 } }] }), EXAMPLE);
    expect(s.hours).toBe("48");
    expect(s.messages[0]).toEqual({ variants: ["a"], followUps: [{ text: "f", delay: "30" }], discount: { percent: 20, months: "3" } });
    expect(initLifecycle(cfg(), EXAMPLE).hours).toBe("24");
  });
});

// Same input → the body the old inline onSubmit built (HEAD LifecycleMessageEditor.tsx):
// { enabled, messages: clean, ...(copy.hours ? { hours: n } : {}), ...collected }.
describe("buildPayload pins the old inline save", () => {
  it.each<[string, LifecycleAction[], LifecycleRules, unknown]>([
    ["untouched, off, no hours knob", [], PLAIN,
      { enabled: false, messages: [{ variants: [EXAMPLE], follow_ups: [], discount: null }], ...EXTRAS }],
    ["expiry: hours as a number, variants trimmed, blanks dropped", [
      { type: "setEnabled", on: true }, { type: "setHours", hours: "36" },
      { type: "patchMessage", i: 0, patch: { variants: [" hi ", "  "], discount: { percent: 15, months: "2" } } },
      { type: "addMessage" },
    ], EXPIRY, {
      enabled: true, messages: [{ variants: ["hi"], follow_ups: [], discount: { percent: 15, months: 2 } }],
      hours: 36, ...EXTRAS,
    }],
    ["follow-ups cleaned, a removed message gone, extras frequency", [
      { type: "addMessage" },
      { type: "patchMessage", i: 1, patch: { variants: ["two"], followUps: [{ text: " f ", delay: "60" }, { text: "", delay: "x" }] } },
      { type: "removeMessage", i: 0 },
      { type: "patchExtras", patch: { frequency: "every" } },
    ], PLAIN, {
      enabled: false, messages: [{ variants: ["two"], follow_ups: [{ text: "f", delay_minutes: 60 }], discount: null }],
      ...EXTRAS, frequency: "every",
    }],
    ["off with every message blank saves no messages", [{ type: "patchMessage", i: 0, patch: { variants: [""] } }], PLAIN,
      { enabled: false, messages: [], ...EXTRAS }],
  ])("%s", (_, actions, rules, body) => {
    const s = run(actions);
    expect(canSubmit(s, rules)).toBe(true);
    expect(buildPayload(s, rules)).toEqual(body);
  });
});

describe("one gate: lifecycleIssues / canSubmit / buildPayload agree", () => {
  it.each<[string, LifecycleAction[], LifecycleRules, Partial<ReturnType<typeof lifecycleIssues>>]>([
    ["hours out of range", [{ type: "setHours", hours: "0" }], EXPIRY, { badHours: true }],
    ["hours not whole", [{ type: "setHours", hours: "1.5" }], EXPIRY, { badHours: true }],
    ["on with no text", [{ type: "setEnabled", on: true }, { type: "patchMessage", i: 0, patch: { variants: [" "] } }], PLAIN,
      { missingText: true }],
    ["a follow-up delay out of range", [{ type: "patchMessage", i: 0, patch: { followUps: [{ text: "f", delay: "0" }] } }], PLAIN,
      { invalid: true }],
    ["discount months out of range", [{ type: "patchMessage", i: 0, patch: { discount: { percent: 10, months: "13" } } }], PLAIN,
      { invalid: true }],
    ["switched on on a free page", [{ type: "setEnabled", on: true }], { refusal: "free page" }, { refused: true }],
    ["a price without media", [{ type: "patchExtras", patch: { price: "5" } }], PLAIN, { problem: "Add media to set a price" }],
  ])("%s", (_, actions, rules, flagged) => {
    const s = run(actions);
    expect(lifecycleIssues(s, rules)).toMatchObject(flagged);
    expect(canSubmit(s, rules)).toBe(false);
    expect(buildPayload(s, rules)).toBeNull();
  });
  it("a free page still lets an on Trigger be switched off and saved", () => {
    const s = run([{ type: "setEnabled", on: false }], cfg({ enabled: true }));
    expect(buildPayload(s, { refusal: "free page" })).toMatchObject({ enabled: false });
  });
  it("hours outside an expiry Trigger are not checked", () => {
    expect(canSubmit(run([{ type: "setHours", hours: "abc" }]), PLAIN)).toBe(true);
  });
});
