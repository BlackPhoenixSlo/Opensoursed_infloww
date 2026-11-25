import { unsaved, withSent, type Saved, type SentState } from "@/components/automations/sentDraft";
import type { AutomationRule, RuleDraft, RulePatch } from "@/hooks/useAutomations";

import { badDelay, cleanFollowUps, type FollowUpDraft } from "./lifecycleForm";
import { collectExtras, extrasDraft, extrasOfPayload, type ExtrasDraft } from "./SmartMessageFields";

const WELCOME_DEFAULT_EVERY_S = 300;

const WELCOME_QUESTION_DEFAULT = "what's yours?";

const WELCOME_CREATE_DEFAULTS = {
  // Creation default only: the sender reads an absent time_only as off on purpose.
  time_only: true,
  skip_time_bubble: false,
  human_pace: true,
  stop_on_reply: true,
  follow_back: true,
  follow_back_gate: true,
};

const WELCOME_DELAY: [number, number] = [2, 5];

export interface WelcomeDraft {
  enabled: boolean;
  minutes: number;
  variants: string[];
  followUps: FollowUpDraft[];
  afterOf: boolean;
  extras: ExtrasDraft;
}

export type WelcomeEdit =
  | { type: "patch"; patch: Partial<Omit<WelcomeDraft, "extras">> }
  | { type: "patchExtras"; patch: Partial<ExtrasDraft> };

export type Landed = { type: "landed"; rule: AutomationRule };
export type Failed = { type: "failed" };
export type Live = { type: "live"; rule: AutomationRule | null };

export type WelcomeAction = WelcomeEdit | Saved | Failed | Landed | Live;

export interface WelcomeState extends SentState<WelcomeDraft> {
  prior: WelcomeDraft | null;
  live: AutomationRule | null;
  written: AutomationRule | null;
}

export const mergeTarget = (s: WelcomeState): AutomationRule | null => s.live ?? s.written;

export function initWelcome(rule: AutomationRule | null): WelcomeDraft {
  const stored = rule?.payload ?? {};
  const saved = stored.message;
  const savedVariants = (Array.isArray(saved) ? saved : [saved]).filter((v): v is string => typeof v === "string");
  const savedSteps = Array.isArray(stored.follow_ups) ? stored.follow_ups as { text?: unknown; delay_minutes?: unknown }[] : [];
  return {
    enabled: rule?.is_enabled ?? false,
    minutes: Math.max(1, Math.round((rule?.every_seconds ?? WELCOME_DEFAULT_EVERY_S) / 60)),
    variants: savedVariants.length ? savedVariants : [""],
    followUps: savedSteps.map((f) => ({ text: String(f.text ?? ""), delay: String(f.delay_minutes ?? "") })),
    afterOf: stored.after_of_welcome === true,
    extras: extrasDraft(rule ? extrasOfPayload(rule.payload) : { delay_range: WELCOME_DELAY }, WELCOME_DELAY),
  };
}

export function initWelcomeState(live: AutomationRule | null): WelcomeState {
  const draft = initWelcome(live);
  return { draft, sent: draft, prior: null, live, written: null };
}

function editWelcome(s: WelcomeDraft, a: WelcomeEdit): WelcomeDraft {
  switch (a.type) {
    case "patch": return { ...s, ...a.patch };
    case "patchExtras": return { ...s, extras: { ...s.extras, ...a.patch } };
  }
}

const withSentWelcome = withSent(editWelcome);

function reseed(s: WelcomeState, rule: AutomationRule | null): WelcomeState {
  if (unsaved(s)) return s;
  const draft = initWelcome(rule);
  return { ...s, draft, sent: draft };
}

export function welcomeReducer(s: WelcomeState, a: WelcomeAction): WelcomeState {
  switch (a.type) {
    case "saved": return { ...s, ...withSentWelcome(s, a), prior: s.sent };
    case "failed": return { ...s, sent: s.prior };
    case "landed": return { ...reseed(s, a.rule), written: a.rule };
    case "live": return { ...reseed(s, a.rule), live: a.rule, written: null };
    default: return { ...s, ...withSentWelcome(s, a) };
  }
}

const collect = (s: WelcomeDraft) => collectExtras(s.extras, { delay: true });

export function welcomeIssues(s: WelcomeDraft) {
  const collected = collect(s);
  return { problem: typeof collected === "string" ? collected : null, invalid: s.followUps.some(badDelay) };
}

export function canSubmit(s: WelcomeDraft): boolean {
  const i = welcomeIssues(s);
  return !i.problem && !i.invalid;
}

export function buildSave(
  s: WelcomeDraft, rule: AutomationRule | null, accountId: string,
): { id: number; patch: RulePatch } | { create: RuleDraft } | null {
  const collected = collect(s);
  if (!canSubmit(s) || typeof collected === "string") return null;
  const stored = rule?.payload ?? {};
  const every_seconds = Math.max(60, Math.round(s.minutes * 60));
  const variants = s.variants.map((v) => v.trim()).filter(Boolean);
  const followUps = cleanFollowUps(s.followUps);
  const smart = {
    message: variants.length > 1 ? variants : (variants[0] ?? ""),
    ...(followUps.length || "follow_ups" in stored ? { follow_ups: followUps } : {}),
    ...(s.afterOf || "after_of_welcome" in stored ? { after_of_welcome: s.afterOf } : {}),
  };
  if (rule) {
    return {
      id: rule.id,
      // A PATCH replaces the whole payload, so merge into the rule's other knobs.
      patch: { is_enabled: s.enabled, every_seconds, payload: { ...(rule.payload ?? {}), ...smart, ...collected } },
    };
  }
  return {
    create: {
      account_id: accountId, kind: "send_welcome", name: "Welcome new subscribers",
      every_seconds, is_enabled: s.enabled,
      payload: {
        ...WELCOME_CREATE_DEFAULTS, question: WELCOME_QUESTION_DEFAULT, gif_id: "", ...smart,
        ...collected,
      },
    },
  };
}
