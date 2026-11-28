import { cleanup, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createElement } from "react";
import { afterEach, describe, expect, it, vi, type Mock } from "vitest";

const platform = vi.hoisted(() => ({ current: "onlyfans" as "onlyfans" | "fansly" }));
vi.mock("@/hooks/useCan", () => ({ useAccountPlatform: (id: string | null | undefined) => (id ? platform.current : null) }));
vi.mock("@/lib/relay", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/lib/relay")>();
  return { ...mod, relay: { ...mod.relay, get: vi.fn() } };
});
vi.mock("./SmartMessageFields", async (importOriginal) => ({
  ...await importOriginal<typeof import("./SmartMessageFields")>(), SmartMessageFields: () => null,
}));

import type { AutomationRule } from "@/hooks/useAutomations";
import type { AccountPlatform } from "@/lib/platform";
import { relay } from "@/lib/relay";

import { unsaved } from "@/components/automations/sentDraft";

import { DelayedWelcomeEditor } from "./DelayedWelcomeEditor";
import {
  afterOfDisabled, buildSave, canSubmit, initWelcome, initWelcomeState, mergeTarget, nativeWelcomeRefusal, welcomeIssues,
  welcomePlatformCopy, welcomeReducer, type WelcomeAction, type WelcomeEdit,
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
    expect(canSubmit(s, null)).toBe(true);
    expect(buildSave(s, rule, "a", null)).toEqual(req);
  });
});

describe("one gate: welcomeIssues / canSubmit / buildSave agree", () => {
  it.each<[string, WelcomeEdit[], Partial<ReturnType<typeof welcomeIssues>>]>([
    ["a follow-up delay out of range", [{ type: "patch", patch: { followUps: [{ text: "f", delay: "0" }] } }], { invalid: true }],
    ["a price without media", [{ type: "patchExtras", patch: { price: "5" } }], { problem: "Add media to set a price" }],
  ])("%s", (_, actions, flagged) => {
    const s = run(null, actions);
    expect(welcomeIssues(s, null)).toMatchObject(flagged);
    expect(canSubmit(s, null)).toBe(false);
    expect(buildSave(s, null, "a", null)).toBeNull();
  });
});

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
    ["untouched since mount, a newer rule: reseeded, reads saved", [{ type: "live", rule: ANSWER }],
      { minutes: 17, variants: ["As saved"], unsaved: false }],
    ["typed, a newer rule: the edit stays", [typed, { type: "live", rule: ANSWER }],
      { minutes: 10, variants: ["Typed while saving"], unsaved: true }],
  ])("%s", (_, actions, want) => {
    const s = runState(RULE(), actions);
    expect({ minutes: s.draft.minutes, variants: s.draft.variants, unsaved: unsaved(s) }).toEqual(want);
  });
});

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

const WARNING = "Fansly's own welcome message can't be checked — turn it off in Fansly, or both will send.";

describe("a Platform without a native welcome check: after-native-welcome refused on, always switchable off", () => {
  it.each<[string, "onlyfans" | "fansly", string | null]>([
    ["Fansly refuses with the warning", "fansly", WARNING],
    ["OnlyFans control: no refusal", "onlyfans", null],
  ])("%s", (_, p, want) => {
    expect(nativeWelcomeRefusal(p)).toBe(want);
  });

  it.each<[string, AccountPlatform, { refusal: string | null; afterLabel: string }]>([
    ["Fansly names Fansly", "fansly", {
      refusal: WARNING, afterLabel: "Fansly's welcome message is message 1: while it is on, send only the follow-ups",
    }],
    ["OnlyFans names OnlyFans, no refusal", "onlyfans", {
      refusal: null, afterLabel: "OnlyFans' welcome message is message 1: while it is on, send only the follow-ups",
    }],
    ["an unregistered key refuses without naming Unknown platform", "unknown", {
      refusal: "This Creator's platform isn't recognised, so its own welcome message can't be checked.",
      afterLabel: "The platform's welcome message is message 1: while it is on, send only the follow-ups",
    }],
  ])("welcome copy: %s", (_, p, want) => {
    expect(welcomePlatformCopy(p)).toEqual(want);
  });

  const ON = RULE({}, { message: "m", after_of_welcome: true });
  const OFF = RULE({}, { message: "m" });
  type Row = [string, AutomationRule | null, WelcomeEdit[], string | null, { disabled: boolean; body: unknown }];
  it.each<Row>([
    ["refusal set + off: the switch is disabled, the save goes through", OFF, [], WARNING, {
      disabled: true,
      body: { id: 7, patch: { is_enabled: true, every_seconds: 600, payload: { message: "m", ...EXTRAS, delay_range: null } } },
    }],
    ["refusal set + stored on: switchable, refused until switched off", ON, [], WARNING, { disabled: false, body: null }],
    ["refusal set + stored on, switched off: saves off, then the switch is disabled", ON,
      [{ type: "patch", patch: { afterOf: false } }], WARNING, {
        disabled: true,
        body: {
          id: 7, patch: {
            is_enabled: true, every_seconds: 600,
            payload: { message: "m", after_of_welcome: false, ...EXTRAS, delay_range: null },
          },
        },
      }],
    ["refusal set: switching on is refused", OFF, [{ type: "patch", patch: { afterOf: true } }], WARNING,
      { disabled: false, body: null }],
    ["OnlyFans control: switched on, it saves on", OFF, [{ type: "patch", patch: { afterOf: true } }], null, {
      disabled: false,
      body: {
        id: 7, patch: {
          is_enabled: true, every_seconds: 600,
          payload: { message: "m", after_of_welcome: true, ...EXTRAS, delay_range: null },
        },
      },
    }],
  ])("%s", (_, rule, actions, refusal, want) => {
    const s = run(rule, actions);
    expect(afterOfDisabled(s, refusal)).toBe(want.disabled);
    expect(welcomeIssues(s, refusal).refused).toBe(want.body === null);
    expect(canSubmit(s, refusal)).toBe(want.body !== null);
    expect(buildSave(s, rule, "a", refusal)).toEqual(want.body);
  });
});

describe("DelayedWelcomeEditor names the Platform and warns about its native welcome", () => {
  const get = relay.get as unknown as Mock;
  const mount = (p: "onlyfans" | "fansly", payload: Record<string, unknown>) => {
    platform.current = p;
    get.mockResolvedValue({ rules: [RULE({ account_id: "acc" }, payload)] });
    return render(createElement(QueryClientProvider,
      { client: new QueryClient({ defaultOptions: { queries: { retry: false } } }) },
      createElement(DelayedWelcomeEditor, { accountId: "acc", onTouched: () => {} })));
  };
  afterEach(() => { cleanup(); vi.clearAllMocks(); });

  it("Fansly, off: the warning, Fansly named, the switch disabled", async () => {
    mount("fansly", { message: "m" });
    expect(await screen.findByText(WARNING)).toBeTruthy();
    const sw = screen.getByRole("switch", { name: /welcome message is message 1/ }) as HTMLButtonElement;
    expect(sw.textContent).toContain("Fansly's welcome message is message 1");
    expect(sw.disabled).toBe(true);
    expect(screen.queryByText(/OnlyFans/)).toBeNull();
  });

  it("Fansly, stored on: switchable off, no claim of a check", async () => {
    mount("fansly", { message: "m", after_of_welcome: true });
    expect(await screen.findByText(WARNING)).toBeTruthy();
    const sw = screen.getByRole("switch", { name: /welcome message is message 1/ }) as HTMLButtonElement;
    expect(sw.disabled).toBe(false);
    expect(screen.queryByText(/Checked once per run/)).toBeNull();
  });

  it("OnlyFans control: today's copy, no warning", async () => {
    mount("onlyfans", { message: "m", after_of_welcome: true });
    const sw = await screen.findByRole("switch", {
      name: "OnlyFans' welcome message is message 1: while it is on, send only the follow-ups",
    }) as HTMLButtonElement;
    expect(sw.disabled).toBe(false);
    expect(screen.getByText(/Checked once per run on OnlyFans/)).toBeTruthy();
    expect(screen.queryByText(/can't be checked/)).toBeNull();
  });
});
