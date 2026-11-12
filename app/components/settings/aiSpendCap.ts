/**
 * The daily AI spend limit's pure rules (AiSpendCapCard): dollars in the box,
 * cents on the wire (`account_ai_config.daily_cost_cap_cents`), spend served in
 * millicents (`ai_spend_today`, the `grok_daily_cost` rows llm_client reserves
 * against).
 *
 *   • Up to 2 decimals, 0 to MAX_CAP_DOLLARS; 0 = every AI call refused.
 *   • The server refuses an EDIT above $100/day (account_config_rules
 *     MAX_DAILY_COST_CAP_CENTS) but takes a stored cap above it back unchanged,
 *     so a legacy cap is never a field the owner cannot save past.
 */

import { LABELS } from "@/components/setup/providerFields";

/** account_config_rules.MAX_DAILY_COST_CAP_CENTS. */
export const MAX_CAP_CENTS = 10_000;
const MILLICENTS_PER_CENT = 100;

const DOLLARS = /^\d+(\.\d{0,2})?$|^\.\d{1,2}$/;

/** The box's text as cents, or null when it is not a dollar amount of at most 2 decimals. */
export function dollarsToCents(raw: string): number | null {
  const s = raw.trim().replace(/^\$/, "");
  if (!DOLLARS.test(s)) return null;
  return Math.round(Number(s) * 100);
}

/** Cents as the box's text: "1.00", "12.50", "0.00". */
export const centsToDollars = (cents: number): string => (cents / 100).toFixed(2);

/** Why the box's text cannot be saved, or null. A stored cap above the bound may be saved back as is. */
export function capError(raw: string, storedCents: number): string | null {
  const cents = dollarsToCents(raw);
  if (cents === null) return "Enter a dollar amount, e.g. 5 or 2.50";
  if (cents > MAX_CAP_CENTS && cents !== storedCents) return `At most $${centsToDollars(MAX_CAP_CENTS)} a day`;
  return null;
}

/** Save only a valid amount that differs from the stored one. */
export const canSaveCap = (raw: string, storedCents: number): boolean =>
  capError(raw, storedCents) === null && dollarsToCents(raw) !== storedCents;

/** Millicents as dollars; a spend under a cent but above zero reads "<$0.01", never "$0.00". */
export function spentText(millicents: number): string {
  if (millicents > 0 && millicents < MILLICENTS_PER_CENT) return "<$0.01";
  return `$${(millicents / (MILLICENTS_PER_CENT * 100)).toFixed(2)}`;
}

/** A provider id as it reads ("DeepSeek"); one the UI does not know reads as itself. */
export const providerName = (id: string): string => (LABELS[id] ?? id).replace(/ API key$/, "");
