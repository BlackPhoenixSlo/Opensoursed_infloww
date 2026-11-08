/**
 * delayedWelcomeForm — DelayedWelcomeEditor's one state (on/off, cadence,
 * message variants, follow-ups, "OnlyFans' welcome is message 1", the Smart
 * Message settings), its reducer and the one save gate.
 *
 *   • `initWelcome` seeds from the `send_welcome` rule, or with none from the
 *     Brain's defaults.
 *   • The state is the draft plus the draft the last Save sent (sentDraft.ts),
 *     seeded as if just saved, and the rules a save merges into (`mergeTarget`):
 *     the rule as the cache last read it, else the one the last save answered.
 *     `live` (a newer read: a refetch, another tab, the rule deleted) and
 *     `landed` (a save's answer) reseed from that rule (none: the defaults)
 *     unless the draft holds an edit (then the edit stays, `unsaved`).
 *     `failed` puts back what was sent before that Save, so an untouched form
 *     follows the rule again and an edit stays unsaved.
 *   • `buildSave` is `useSaveRule`'s request: PATCH an existing rule with its
 *     payload MERGED (a PATCH replaces the whole payload, so the Brain's other
 *     knobs stay), or create the rule the old Brain welcome lane created
 *     (`WELCOME_CREATE_DEFAULTS`). Null while an issue stands.
 */

import { unsaved, withSent, type Saved, type SentState } from "@/components/automations/sentDraft";
import type { AutomationRule, RuleDraft, RulePatch } from "@/hooks/useAutomations";

import { badDelay, cleanFollowUps, type FollowUpDraft } from "./lifecycleForm";
import { collectExtras, extrasDraft, extrasOfPayload, type ExtrasDraft } from "./SmartMessageFields";

/** The welcome rule's default cadence: poll OF's new-subscriber feed every
 *  5 min (the send_welcome spec's {every_seconds: 300}). */
const WELCOME_DEFAULT_EVERY_S = 300;

/** Default 3rd-bubble question, stamped at rule creation (the sender treats an
 *  absent key as off, so older rules don't change; "" is explicitly off). */
const WELCOME_QUESTION_DEFAULT = "what's yours?";

/** The six welcome booleans a brand-new rule is born with. They mirror the
 *  relay catalog's `default` for each key (`automation_rules_api`'s
 *  send_welcome entry; `case_every_catalogued_bool_honours_its_default` holds
 *  the two sides together). `time_only: true` is a creation default only: the
 *  sender reads an absent `time_only` as off on purpose (C-N7). `follow_back`
 *  and `follow_back_gate` drive a money-spending lane, not a bubble. */
const WELCOME_CREATE_DEFAULTS = {
  time_only: true,
  skip_time_bubble: false,
  human_pace: true,
  stop_on_reply: true,
  follow_back: true,
  follow_back_gate: true,
};

/** Infloww's delay for a new welcome: 2～5 minutes. */
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

/** A save's answer: the rule as written. */
export type Landed = { type: "landed"; rule: AutomationRule };
/** A save failed. */
export type Failed = { type: "failed" };
/** The rule as the cache now reads it (null: none, e.g. deleted elsewhere). */
export type Live = { type: "live"; rule: AutomationRule | null };

export type WelcomeAction = WelcomeEdit | Saved | Failed | Landed | Live;

export interface WelcomeState extends SentState<WelcomeDraft> {
  /** `sent` before the Save in flight: `failed` puts it back. */
  prior: WelcomeDraft | null;
  /** The rule as the cache last read it (null: none, or its read failed). */
  live: AutomationRule | null;
  /** The rule the last save answered with, until a newer read: a create whose refetch failed still PATCHes it. */
  written: AutomationRule | null;
}

/** The rule a save merges into (null = create it). */
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

/** The state at mount: the cache's rule, its draft untouched (reads as just saved, so a newer rule reseeds it). */
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

/** Untouched (since the seed or the Save): reseed from `rule` as just saved. An edit stays. */
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
    // A newer read supersedes the save's answer; null (deleted elsewhere) → the next Save creates it.
    case "live": return { ...reseed(s, a.rule), live: a.rule, written: null };
    default: return { ...s, ...withSentWelcome(s, a) };
  }
}

const collect = (s: WelcomeDraft) => collectExtras(s.extras, { delay: true });

/** What stops a save: the Smart Message settings' line, or a follow-up delay out of range (flagged at the field). */
export function welcomeIssues(s: WelcomeDraft) {
  const collected = collect(s);
  return { problem: typeof collected === "string" ? collected : null, invalid: s.followUps.some(badDelay) };
}

export function canSubmit(s: WelcomeDraft): boolean {
  const i = welcomeIssues(s);
  return !i.problem && !i.invalid;
}

/** The save request for `accountId`'s rule (null = create it), or null while it can't save. */
export function buildSave(
  s: WelcomeDraft, rule: AutomationRule | null, accountId: string,
): { id: number; patch: RulePatch } | { create: RuleDraft } | null {
  const collected = collect(s);
  if (!canSubmit(s) || typeof collected === "string") return null;
  const stored = rule?.payload ?? {};
  const every_seconds = Math.max(60, Math.round(s.minutes * 60));
  const variants = s.variants.map((v) => v.trim()).filter(Boolean);
  const followUps = cleanFollowUps(s.followUps);
  // One text stays a string; several are the variants' list. The follow-up
  // knobs are written once used, so a rule that never had them keeps its shape.
  const smart = {
    message: variants.length > 1 ? variants : (variants[0] ?? ""),
    ...(followUps.length || "follow_ups" in stored ? { follow_ups: followUps } : {}),
    ...(s.afterOf || "after_of_welcome" in stored ? { after_of_welcome: s.afterOf } : {}),
  };
  if (rule) {
    return {
      id: rule.id,
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
