import type { LifecycleMessage, LifecycleMessageConfig } from "@/hooks/useLifecycleMessageConfig";

import { collectExtras, extrasDraft, type ExtrasDraft } from "./SmartMessageFields";

export const FOLLOW_UP_DELAY_MAX = 7 * 24 * 60;
export const MAX_VARIANTS = 10;
export const TEXT_MAX = 1000;

export interface FollowUpDraft {
  text: string;
  delay: string;
}

export function badDelay(f: FollowUpDraft): boolean {
  const n = Number(f.delay);
  return !!f.text.trim() && !(Number.isInteger(n) && n >= 1 && n <= FOLLOW_UP_DELAY_MAX);
}

export function cleanFollowUps(steps: FollowUpDraft[]) {
  return steps.filter((f) => f.text.trim()).map((f) => ({ text: f.text.trim(), delay_minutes: Number(f.delay) }));
}

export interface MessageDraft {
  variants: string[];
  followUps: FollowUpDraft[];
  discount: { percent: number; months: string } | null;
}

const toDraft = (m: LifecycleMessage): MessageDraft => ({
  variants: m.variants.length ? m.variants : [""],
  followUps: m.follow_ups.map((f) => ({ text: f.text, delay: String(f.delay_minutes) })),
  discount: m.discount && { percent: m.discount.percent, months: String(m.discount.months) },
});

export const EMPTY_MESSAGE: MessageDraft = { variants: [""], followUps: [], discount: null };

export function badMonths(d: MessageDraft): boolean {
  const n = Number(d.discount?.months);
  return !!d.discount && !(Number.isInteger(n) && n >= 1 && n <= 12);
}

export interface LifecycleDraft {
  enabled: boolean;
  messages: MessageDraft[];
  hours: string;
  extras: ExtrasDraft;
}

export type LifecycleAction =
  | { type: "setEnabled"; on: boolean }
  | { type: "setHours"; hours: string }
  | { type: "patchMessage"; i: number; patch: Partial<MessageDraft> }
  | { type: "addMessage" }
  | { type: "removeMessage"; i: number }
  | { type: "patchExtras"; patch: Partial<ExtrasDraft> };

export function initLifecycle(initial: LifecycleMessageConfig, example: string): LifecycleDraft {
  return {
    enabled: initial.enabled,
    messages: initial.messages?.length
      ? initial.messages.map(toDraft) : [{ ...EMPTY_MESSAGE, variants: [initial.text || example] }],
    hours: String(initial.hours ?? 24),
    extras: extrasDraft(initial),
  };
}

export function lifecycleReducer(s: LifecycleDraft, a: LifecycleAction): LifecycleDraft {
  switch (a.type) {
    case "setEnabled": return { ...s, enabled: a.on };
    case "setHours": return { ...s, hours: a.hours };
    case "patchMessage":
      return { ...s, messages: s.messages.map((m, j) => (j === a.i ? { ...m, ...a.patch } : m)) };
    case "addMessage": return { ...s, messages: [...s.messages, EMPTY_MESSAGE] };
    case "removeMessage": return { ...s, messages: s.messages.filter((_, j) => j !== a.i) };
    case "patchExtras": return { ...s, extras: { ...s.extras, ...a.patch } };
  }
}

export interface LifecycleRules {
  hours?: { min: number; max: number };
  refusal: string | null;
}

const collect = (s: LifecycleDraft) => collectExtras(s.extras, { frequency: true });

function cleanMessages(s: LifecycleDraft): LifecycleMessage[] {
  return s.messages
    .map((m) => ({
      variants: m.variants.map((v) => v.trim()).filter(Boolean),
      follow_ups: cleanFollowUps(m.followUps),
      discount: m.discount && { percent: m.discount.percent, months: Number(m.discount.months) },
    }))
    .filter((m) => m.variants.length);
}

export function lifecycleIssues(s: LifecycleDraft, rules: LifecycleRules) {
  const collected = collect(s);
  const n = Number(s.hours);
  return {
    problem: typeof collected === "string" ? collected : null,
    badHours: !!rules.hours && !(Number.isInteger(n) && n >= rules.hours.min && n <= rules.hours.max),
    missingText: s.enabled && !cleanMessages(s).length,
    invalid: s.messages.some((m) => m.followUps.some(badDelay) || badMonths(m)),
    refused: !!rules.refusal && s.enabled,
  };
}

export function canSubmit(s: LifecycleDraft, rules: LifecycleRules): boolean {
  const i = lifecycleIssues(s, rules);
  return !i.problem && !i.badHours && !i.missingText && !i.invalid && !i.refused;
}

export function buildPayload(s: LifecycleDraft, rules: LifecycleRules): Partial<LifecycleMessageConfig> | null {
  const collected = collect(s);
  if (!canSubmit(s, rules) || typeof collected === "string") return null;
  return { enabled: s.enabled, messages: cleanMessages(s), ...(rules.hours ? { hours: Number(s.hours) } : {}), ...collected };
}
