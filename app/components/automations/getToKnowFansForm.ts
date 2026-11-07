/**
 * Get to know fans' rule settings as a pure reducer: the draft of the rule payload the page edits (its Human style
 * boxes: HumanStyleBlock.tsx) and the draft the last Save sent.
 *
 *   • The draft is seeded once per creator from the rule's payload, else (no rule yet) the catalog defaults
 *     (`initState`); a refetch, or the switch creating the rule, never re-seeds it.
 *   • Numbers stay as typed (a min of 3 would fight every keystroke); `invalidReason` checks them before Save.
 *   • The state is the draft plus the draft the last Save sent (sentDraft.ts: `unsaved` holds "Saved" off over an
 *     edit made while that save was in flight).
 *   • `buildPayload` sends the rule's payload back with only this page's fields changed (the PATCH replaces it).
 *   • `ruleSave`: a PATCH of the rule, or with none yet a create PARKED (`is_enabled: false`), so a Save never turns
 *     the automation on; only the switch does.
 */

import { sentState, withSent, type Saved, type SentState } from "@/components/automations/sentDraft";
import type { AutomationKind, AutomationRule, RuleDraft, RulePatch } from "@/hooks/useAutomations";
import type { VaultMedia } from "@/lib/relay";

export interface GtkfDraft {
  /** `max_fan_messages`, as typed. */
  cutoff: string;
  /** `closing_ppv_media_ids`: saved ids render as plain tiles; tiles picked this session keep their thumbnails. */
  media: VaultMedia[];
  /** `closing_ppv_text`. */
  caption: string;
  /** `closing_ppv_price_cents`, in dollars as typed. */
  price: string;
}

export type GtkfState = SentState<GtkfDraft>;

/** An edit of one field. */
export type GtkfEdit = { [K in keyof GtkfDraft]: { type: "field"; k: K; v: GtkfDraft[K] } }[keyof GtkfDraft];

export type GtkfAction = GtkfEdit | Saved;

export interface RuleLimits { cutMin: number; cutMax: number; priceMin: number; priceMax: number }

const toCents = (dollars: number) => Math.round(dollars * 100);
const toDollars = (cents: number) => Math.round(cents) / 100;

/** A knob's catalog default (automation_rules_api._CATALOG, the value the engine reads when the key is absent). */
const knobOf = (meta: AutomationKind, key: string) => meta.knobs.find((k) => k.key === key);

/** The bounds of the cutoff and the price (dollars), from the catalog. */
export function limitsOf(meta: AutomationKind): RuleLimits {
  const cut = knobOf(meta, "max_fan_messages");
  const price = knobOf(meta, "closing_ppv_price_cents");
  return {
    cutMin: cut?.min ?? 3, cutMax: cut?.max ?? 100,
    priceMin: toDollars(price?.min ?? 300), priceMax: toDollars(price?.max ?? 20_000),
  };
}

export function initState(stored: Record<string, unknown> | undefined, meta: AutomationKind): GtkfState {
  const p = stored ?? {};
  return sentState({
    cutoff: String(p.max_fan_messages ?? knobOf(meta, "max_fan_messages")?.default ?? 10),
    media: (Array.isArray(p.closing_ppv_media_ids) ? p.closing_ppv_media_ids : [])
      .map((id) => ({ id: Number(id), type: "photo" }) as VaultMedia),
    caption: String(p.closing_ppv_text ?? knobOf(meta, "closing_ppv_text")?.default ?? ""),
    price: String(toDollars(Number(p.closing_ppv_price_cents ?? knobOf(meta, "closing_ppv_price_cents")?.default ?? 1000))),
  });
}

/** Why Save is refused, or null. */
export function invalidReason(d: GtkfDraft, l: RuleLimits): string | null {
  const cutoffN = Number(d.cutoff);
  const priceN = Number(d.price);
  if (!Number.isInteger(cutoffN) || cutoffN < l.cutMin || cutoffN > l.cutMax) return `Message cutoff: ${l.cutMin} to ${l.cutMax}.`;
  if (d.price.trim() === "" || !Number.isFinite(priceN) || priceN < l.priceMin || priceN > l.priceMax) {
    return `Price: $${l.priceMin} to $${l.priceMax}.`;
  }
  return null;
}

/** The PATCH payload: the rule's payload with this page's fields set from the draft. */
export function buildPayload(d: GtkfDraft, payload: Record<string, unknown>): Record<string, unknown> {
  return {
    ...payload,
    max_fan_messages: Number(d.cutoff),
    closing_ppv_media_ids: d.media.map((m) => m.id),
    closing_ppv_text: d.caption,
    closing_ppv_price_cents: toCents(Number(d.price)),
  };
}

/** What Save sends: the rule's PATCH, or (no rule yet) a parked create with the name and cadence the switch's create
 *  would give it (automation_rules_api.ensure_kind_rule `_new_row`), so switching it on later just wakes it. */
export type RuleSave = { id: number; patch: RulePatch } | { create: RuleDraft };

export function ruleSave(d: GtkfDraft, rule: AutomationRule | null, meta: AutomationKind, accountId: string): RuleSave {
  if (rule) return { id: rule.id, patch: { payload: buildPayload(d, rule.payload ?? {}) } };
  return { create: {
    account_id: accountId, kind: meta.kind, name: meta.label || meta.kind,
    every_seconds: meta.cadence_default_s ?? 300, payload: buildPayload(d, {}), is_enabled: false,
  } };
}

export const gtkfReducer = withSent((d: GtkfDraft, a: GtkfEdit): GtkfDraft => ({ ...d, [a.k]: a.v }));
