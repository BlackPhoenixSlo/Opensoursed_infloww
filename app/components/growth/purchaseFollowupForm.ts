/**
 * purchaseFollowupForm — PurchaseFollowupEditor's one state (on/off, the text,
 * the Smart Message settings and the settings it opened on), its reducer and
 * the one save gate.
 *
 *   • `opened` never changes: an "after delay" row left as it opened is not
 *     sent (collectExtras' `initial`), so the Relay keeps what it stored.
 *   • `purchaseIssues` feeds the warnings and Save's disabled state;
 *     `buildPayload` is the PUT config, null while an issue stands.
 */

import type { PurchaseFollowupConfig } from "@/hooks/usePurchaseFollowupConfig";

import { collectExtras, extrasDraft, type ExtrasDraft } from "./SmartMessageFields";

export interface PurchaseDraft {
  enabled: boolean;
  text: string;
  extras: ExtrasDraft;
  /** The settings the form opened on. */
  opened: ExtrasDraft;
}

export type PurchaseAction =
  | { type: "setEnabled"; on: boolean }
  | { type: "setText"; text: string }
  | { type: "patchExtras"; patch: Partial<ExtrasDraft> };

/** The saved config; with no text saved, `template` (Infloww's default script). */
export function initPurchase(initial: PurchaseFollowupConfig, template: string): PurchaseDraft {
  const opened = extrasDraft(initial);
  return { enabled: initial.enabled, text: initial.text || template, extras: opened, opened };
}

export function purchaseReducer(s: PurchaseDraft, a: PurchaseAction): PurchaseDraft {
  switch (a.type) {
    case "setEnabled": return { ...s, enabled: a.on };
    case "setText": return { ...s, text: a.text };
    case "patchExtras": return { ...s, extras: { ...s.extras, ...a.patch } };
  }
}

const collect = (s: PurchaseDraft) => collectExtras(s.extras, { delay: true, frequency: true, initial: s.opened });

/** What stops a save: the Smart Message settings' line, or switched on with no text. */
export function purchaseIssues(s: PurchaseDraft) {
  const collected = collect(s);
  return { problem: typeof collected === "string" ? collected : null, missingText: s.enabled && !s.text.trim() };
}

export function canSubmit(s: PurchaseDraft): boolean {
  const i = purchaseIssues(s);
  return !i.problem && !i.missingText;
}

/** The PUT config, or null while it can't save. */
export function buildPayload(s: PurchaseDraft): Partial<PurchaseFollowupConfig> | null {
  const collected = collect(s);
  if (!canSubmit(s) || typeof collected === "string") return null;
  return { enabled: s.enabled, text: s.text.trim(), ...collected };
}
