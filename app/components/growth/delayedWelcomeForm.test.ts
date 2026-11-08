import { describe, expect, it } from "vitest";

import type { AutomationRule } from "@/hooks/useAutomations";

import { unsaved } from "@/components/automations/sentDraft";

import {
  buildSave, canSubmit, initWelcome, initWelcomeState, mergeTarget, welcomeIssues, welcomeReducer, type WelcomeAction,
  type WelcomeEdit,
} from "./delayedWelcomeForm";

const RULE = (over: Partial<AutomationRule> = {}, payload: Record<string, unknown> = {}): AutomationRule => ({
  id: 7, account_id: "a", name: "Welcome", kind: "send_welcome", is_enabled: true, every_seconds: 600,
  trigger: null as unknown as AutomationRule["trigger"], payload, quiet_hours: null, created_at: null, last_run: null,
  next_due_at: null, has_pending_job: false, ...over,
});
const runState = (rule: AutomationRule | null, actions: WelcomeAction[] = []) =>
  actions.reduce(welcomeReducer, initWelcomeState(rule));
const run = (rule: AutomationRule | null, actions: WelcomeEdit[] = []) => runState(rule, actions).draft;
const EXTRAS = { media_ids: [], price_cents: 0, starts_at: null, ends_at: null, unsend_minutes: 0 };

describe("initWelcome", () => {
  it("no rule: the Brain's defaults, off, 5 minutes, Infloww's 2～5 delay", () => {
    const s = initWelcome(null);
    expect(s).toMatchObject({ enabled: false, minutes: 5, variants: [""], followUps: [], afterOf: false });
    expect(s.extras).toMatchObject({ delayOn: true, delayA: "2", delayB: "5" });
  });
  it("a rule: its on/off, cadence, variants, follow-ups and after-OF switch", () => {
    const s = initWelcome(RULE({}, {
      message: ["a", "b"], follow_ups: [{ text: "f", delay_minutes: 30 }], after_of_welcome: true,
    }));
    expect(s).toMatchObject({
      enabled: true, minutes: 10, variants: ["a", "b"], followUps: [{ text: "f", delay: "30" }], afterOf: true,
    });
    expect(s.extras.delayOn).toBe(false);
  });
});

// Same input → the request the old inline save() built (HEAD DelayedWelcomeEditor.tsx).
describe("buildSave pins the old inline requests", () => {
  it.each<[string, AutomationRule | null, WelcomeEdit[], unknown]>([
    ["no rule, untouched: create off with the Brain lane's defaults", null, [], {
      create: {
        account_id: "a", kind: "send_welcome", name: "Welcome new subscribers", every_seconds: 300, is_enabled: false,
        payload: {
          time_only: true, skip_time_bubble: false, human_pace: true, stop_on_reply: true, follow_back: true,
          follow_back_gate: true, question: "what's yours?", gif_id: "", message: "", ...EXTRAS, delay_range: [2, 5],
        },
      },
    }],
    ["create with variants and a follow-up", null, [
      { type: "patch", patch: { enabled: true, minutes: 0.4, variants: [" hi ", "yo", " "] } },
      { type: "patch", patch: { followUps: [{ text: " f ", delay: "15" }] } },
    ], {
      create: {
        account_id: "a", kind: "send_welcome", name: "Welcome new subscribers", every_seconds: 60, is_enabled: true,
        payload: {
          time_only: true, skip_time_bubble: false, human_pace: true, stop_on_reply: true, follow_back: true,
          follow_back_gate: true, question: "what's yours?", gif_id: "", message: ["hi", "yo"],
          follow_ups: [{ text: "f", delay_minutes: 15 }], ...EXTRAS, delay_range: [2, 5],
        },
      },
    }],
    ["update merges into the stored payload; untouched follow-up knobs keep their shape",
      RULE({}, { question: "q?", gif_id: "g", message: "old" }),
      [{ type: "patch", patch: { variants: ["new"] } }], {
        id: 7, patch: {
          is_enabled: true, every_seconds: 600,
          payload: { question: "q?", gif_id: "g", message: "new", ...EXTRAS, delay_range: null },
        },
      }],
    ["a rule that had the follow-up knobs gets them written back, emptied",
      RULE({}, { message: "m", follow_ups: [{ text: "x", delay_minutes: 5 }], after_of_welcome: true }),
      [{ type: "patch", patch: { followUps: [], afterOf: false } }], {
        id: 7, patch: {
          is_enabled: true, every_seconds: 600,
          payload: { message: "m", follow_ups: [], after_of_welcome: false, ...EXTRAS, delay_range: null },
        },
      }],
  ])("%s", (_, rule, actions, req) => {
    const s = run(rule, actions);
    expect(canSubmit(s)).toBe(true);
    expect(buildSave(s, rule, "a")).toEqual(req);
  });
});

describe("one gate: welcomeIssues / canSubmit / buildSave agree", () => {
  it.each<[string, WelcomeEdit[], Partial<ReturnType<typeof welcomeIssues>>]>([
    ["a follow-up delay out of range", [{ type: "patch", patch: { followUps: [{ text: "f", delay: "0" }] } }], { invalid: true }],
    ["a price without media", [{ type: "patchExtras", patch: { price: "5" } }], { problem: "Add media to set a price" }],
  ])("%s", (_, actions, flagged) => {
    const s = run(null, actions);
    expect(welcomeIssues(s)).toMatchObject(flagged);
    expect(canSubmit(s)).toBe(false);
    expect(buildSave(s, null, "a")).toBeNull();
  });
});

// The rule as written (a save's answer, or a newer read): reseed from it, unless the draft holds an edit.
describe("welcomeReducer: saved, then landed", () => {
  const ANSWER = RULE({ every_seconds: 17 * 60 }, { message: "As saved" });
  const typed: WelcomeEdit = { type: "patch", patch: { variants: ["Typed while saving"] } };
  it.each<[string, WelcomeAction[], { minutes: number; variants: string[]; unsaved: boolean }]>([
    ["landed clean: reseeded from the answer, reads saved", [{ type: "saved" }, { type: "landed", rule: ANSWER }],
      { minutes: 17, variants: ["As saved"], unsaved: false }],
    ["landed edited: the edit stays, unsaved", [{ type: "saved" }, typed, { type: "landed", rule: ANSWER }],
      { minutes: 10, variants: ["Typed while saving"], unsaved: true }],
    ["edited back to the sent value while in flight: still unsaved, not reseeded",
      [{ type: "saved" }, typed, { type: "patch", patch: { variants: [""] } }, { type: "landed", rule: ANSWER }],
      { minutes: 10, variants: [""], unsaved: true }],
    ["an edit after a clean land: unsaved", [{ type: "saved" }, { type: "landed", rule: ANSWER }, typed],
      { minutes: 17, variants: ["Typed while saving"], unsaved: true }],
    // The rule as the cache reads it now (a refetch, another tab, the first read after a failed one).
    ["untouched since mount, a newer rule: reseeded, reads saved", [{ type: "live", rule: ANSWER }],
      { minutes: 17, variants: ["As saved"], unsaved: false }],
    ["typed, a newer rule: the edit stays", [typed, { type: "live", rule: ANSWER }],
      { minutes: 10, variants: ["Typed while saving"], unsaved: true }],
  ])("%s", (_, actions, want) => {
    const s = runState(RULE(), actions);
    expect({ minutes: s.draft.minutes, variants: s.draft.variants, unsaved: unsaved(s) }).toEqual(want);
  });
});

// What a save merges into, a newer read (incl. the rule deleted elsewhere), and a failed save.
describe("welcomeReducer: merge target, live, failed", () => {
  const ON = RULE({ id: 7, every_seconds: 600 }, { message: "On the server" });
  const OTHER = RULE({ id: 9, is_enabled: false, every_seconds: 1200 }, { message: "From another tab" });
  const CREATED = RULE({ id: 8, is_enabled: false, every_seconds: 7 * 60 }, { message: "As created" });
  const typed: WelcomeEdit = { type: "patch", patch: { variants: ["Typed"] } };
  type Want = { enabled: boolean; minutes: number; variants: string[]; unsaved: boolean; target: number | null };
  it.each<[string, AutomationRule | null, WelcomeAction[], Want]>([
    ["mount on the rule: its values, merge into it", ON, [],
      { enabled: true, minutes: 10, variants: ["On the server"], unsaved: false, target: 7 }],
    ["untouched, the rule appears: follows it", null, [{ type: "live", rule: OTHER }],
      { enabled: false, minutes: 20, variants: ["From another tab"], unsaved: false, target: 9 }],
    ["untouched, the rule changes: follows it", ON, [{ type: "live", rule: OTHER }],
      { enabled: false, minutes: 20, variants: ["From another tab"], unsaved: false, target: 9 }],
    ["untouched, the rule deleted elsewhere: the defaults, create", ON, [{ type: "live", rule: null }],
      { enabled: false, minutes: 5, variants: [""], unsaved: false, target: null }],
    ["typed, the rule deleted elsewhere: the edit stays, create", ON, [typed, { type: "live", rule: null }],
      { enabled: true, minutes: 10, variants: ["Typed"], unsaved: true, target: null }],
    ["typed, the rule changes: the edit stays, merge into the new read", ON, [typed, { type: "live", rule: OTHER }],
      { enabled: true, minutes: 10, variants: ["Typed"], unsaved: true, target: 9 }],
    ["create lands clean: reseeded from the answer, merge into it", null, [{ type: "saved" }, { type: "landed", rule: CREATED }],
      { enabled: false, minutes: 7, variants: ["As created"], unsaved: false, target: 8 }],
    ["create lands, then a newer read: merge into the read", null,
      [{ type: "saved" }, { type: "landed", rule: CREATED }, { type: "live", rule: OTHER }],
      { enabled: false, minutes: 20, variants: ["From another tab"], unsaved: false, target: 9 }],
    ["create lands, then the rule deleted elsewhere: the defaults, create", null,
      [{ type: "saved" }, { type: "landed", rule: CREATED }, { type: "live", rule: OTHER }, { type: "live", rule: null }],
      { enabled: false, minutes: 5, variants: [""], unsaved: false, target: null }],
    ["a save lands while the cache still reads the old rule: merge into the cache's", ON,
      [typed, { type: "saved" }, { type: "landed", rule: CREATED }],
      { enabled: false, minutes: 7, variants: ["As created"], unsaved: false, target: 7 }],
    ["untouched save fails: still untouched, a newer read is followed", null,
      [{ type: "saved" }, { type: "failed" }, { type: "live", rule: OTHER }],
      { enabled: false, minutes: 20, variants: ["From another tab"], unsaved: false, target: 9 }],
    ["typed save fails: the edit stays unsaved over a newer read", ON,
      [typed, { type: "saved" }, { type: "failed" }, { type: "live", rule: OTHER }],
      { enabled: true, minutes: 10, variants: ["Typed"], unsaved: true, target: 9 }],
    ["untouched save, an edit while it runs, it fails: the edit stays unsaved", ON,
      [{ type: "saved" }, typed, { type: "failed" }, { type: "live", rule: OTHER }],
      { enabled: true, minutes: 10, variants: ["Typed"], unsaved: true, target: 9 }],
    ["a save fails after an earlier one landed: still untouched, follows a newer read", null,
      [typed, { type: "saved" }, { type: "landed", rule: CREATED }, { type: "saved" }, { type: "failed" },
        { type: "live", rule: OTHER }],
      { enabled: false, minutes: 20, variants: ["From another tab"], unsaved: false, target: 9 }],
  ])("%s", (_, rule, actions, want) => {
    const s = runState(rule, actions);
    expect({
      enabled: s.draft.enabled, minutes: s.draft.minutes, variants: s.draft.variants, unsaved: unsaved(s),
      target: mergeTarget(s)?.id ?? null,
    }).toEqual(want);
  });
});
