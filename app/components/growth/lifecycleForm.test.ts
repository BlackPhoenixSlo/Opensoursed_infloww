import { describe, expect, it } from "vitest";

import type { LifecycleMessageConfig } from "@/hooks/useLifecycleMessageConfig";

import {
  buildPayload, canSubmit, initLifecycle, lifecycleIssues, lifecycleReducer, lifecycleRefusal,
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

describe("a Platform that lacks the Trigger: refused on, always switchable off", () => {
  const LACKS = "platform_lacks:renewal_state";
  const NOT_HERE: LifecycleRules = { hours: { min: 1, max: 120 }, refusal: lifecycleRefusal("Nearing expiry", LACKS, null) };
  const DISCOUNTED = cfg({ enabled: true, hours: 24, messages: [{ variants: ["hi"], follow_ups: [], discount: { percent: 10, months: 1 } }] });

  it.each<[string, string | null, string | null, string | null]>([
    ["the GET refusal wins and reads not on this platform", LACKS, "free page", "Nearing expiry: not on this platform"],
    ["no GET refusal falls back to the free-page one", null, "free page", "free page"],
    ["neither: nothing refused", null, null, null],
  ])("%s", (_, platform, free, shown) => {
    expect(lifecycleRefusal("Nearing expiry", platform, free)).toBe(shown);
  });

  it.each<[string, LifecycleAction[], LifecycleMessageConfig, LifecycleRules, unknown]>([
    ["refusal on: switching on cannot be saved", [{ type: "setEnabled", on: true }], cfg(), NOT_HERE, null],
    ["stored on: switched off it saves", [{ type: "setEnabled", on: false }], cfg({ enabled: true, text: "old" }), NOT_HERE,
      { enabled: false, messages: [{ variants: ["old"], follow_ups: [], discount: null }], hours: 24, ...EXTRAS }],
    ["off-recovery keeps the stored discount in the off save", [{ type: "setEnabled", on: false }], DISCOUNTED, NOT_HERE,
      { enabled: false, messages: [{ variants: ["hi"], follow_ups: [], discount: { percent: 10, months: 1 } }], hours: 24, ...EXTRAS }],
    ["OnlyFans control: no refusal, on saves", [{ type: "setEnabled", on: true }], cfg(), EXPIRY,
      { enabled: true, messages: [{ variants: [EXAMPLE], follow_ups: [], discount: null }], hours: 24, ...EXTRAS }],
  ])("%s", (_, actions, init, rules, body) => {
    const s = run(actions, init);
    expect(canSubmit(s, rules)).toBe(body !== null);
    expect(buildPayload(s, rules)).toEqual(body);
  });

  it("a stored-on Trigger with the refusal still reads as refused until switched off", () => {
    const s = run([], DISCOUNTED);
    expect(lifecycleIssues(s, NOT_HERE).refused).toBe(true);
    expect(buildPayload(s, NOT_HERE)).toBeNull();
  });
});
