import { LABELS } from "@/components/setup/providerFields";

export const MAX_CAP_CENTS = 10_000;
const MILLICENTS_PER_CENT = 100;

const DOLLARS = /^\d+(\.\d{0,2})?$|^\.\d{1,2}$/;

export function dollarsToCents(raw: string): number | null {
  const s = raw.trim().replace(/^\$/, "");
  if (!DOLLARS.test(s)) return null;
  return Math.round(Number(s) * 100);
}

export const centsToDollars = (cents: number): string => (cents / 100).toFixed(2);

export function capError(raw: string, storedCents: number): string | null {
  const cents = dollarsToCents(raw);
  if (cents === null) return "Enter a dollar amount, e.g. 5 or 2.50";
  // The server refuses an edit above the cap but takes a stored legacy cap back unchanged.
  if (cents > MAX_CAP_CENTS && cents !== storedCents) return `At most $${centsToDollars(MAX_CAP_CENTS)} a day`;
  return null;
}

export const canSaveCap = (raw: string, storedCents: number): boolean =>
  capError(raw, storedCents) === null && dollarsToCents(raw) !== storedCents;

export function spentText(millicents: number): string {
  if (millicents > 0 && millicents < MILLICENTS_PER_CENT) return "<$0.01";
  return `$${(millicents / (MILLICENTS_PER_CENT * 100)).toFixed(2)}`;
}

export const providerName = (id: string): string =>
  id === "describe" ? "Vault describe" : id === "chat" ? "Chats and other AI" : (LABELS[id] ?? id).replace(/ API key$/, "");
