import { sentState, withSent, type Saved, type SentState } from "@/components/automations/sentDraft";
import type { AutomationKind, AutomationRule, RuleDraft, RulePatch } from "@/hooks/useAutomations";
import type { VaultMedia } from "@/lib/relay";

export interface GtkfDraft {
  cutoff: string;
  media: VaultMedia[];
  caption: string;
  price: string;
}

export type GtkfState = SentState<GtkfDraft>;

export type GtkfEdit = { [K in keyof GtkfDraft]: { type: "field"; k: K; v: GtkfDraft[K] } }[keyof GtkfDraft];

export type GtkfAction = GtkfEdit | Saved;

export interface RuleLimits { cutMin: number; cutMax: number; priceMin: number; priceMax: number }

const toCents = (dollars: number) => Math.round(dollars * 100);
const toDollars = (cents: number) => Math.round(cents) / 100;

const knobOf = (meta: AutomationKind, key: string) => meta.knobs.find((k) => k.key === key);

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

export function invalidReason(d: GtkfDraft, l: RuleLimits): string | null {
  const cutoffN = Number(d.cutoff);
  const priceN = Number(d.price);
  if (!Number.isInteger(cutoffN) || cutoffN < l.cutMin || cutoffN > l.cutMax) return `Message cutoff: ${l.cutMin} to ${l.cutMax}.`;
  if (d.price.trim() === "" || !Number.isFinite(priceN) || priceN < l.priceMin || priceN > l.priceMax) {
    return `Price: $${l.priceMin} to $${l.priceMax}.`;
  }
  return null;
}

// The PATCH replaces the payload, so send the stored one back with only this page's fields changed.
export function buildPayload(d: GtkfDraft, payload: Record<string, unknown>): Record<string, unknown> {
  return {
    ...payload,
    max_fan_messages: Number(d.cutoff),
    closing_ppv_media_ids: d.media.map((m) => m.id),
    closing_ppv_text: d.caption,
    closing_ppv_price_cents: toCents(Number(d.price)),
  };
}

export type RuleSave = { id: number; patch: RulePatch } | { create: RuleDraft };

// A Save with no rule yet creates it parked, so Save never turns the automation on.
export function ruleSave(d: GtkfDraft, rule: AutomationRule | null, meta: AutomationKind, accountId: string): RuleSave {
  if (rule) return { id: rule.id, patch: { payload: buildPayload(d, rule.payload ?? {}) } };
  return { create: {
    account_id: accountId, kind: meta.kind, name: meta.label || meta.kind,
    every_seconds: meta.cadence_default_s ?? 300, payload: buildPayload(d, {}), is_enabled: false,
  } };
}

export const gtkfReducer = withSent((d: GtkfDraft, a: GtkfEdit): GtkfDraft => ({ ...d, [a.k]: a.v }));
