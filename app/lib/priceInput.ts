/**
 * A typed price box: what the field accepts (`sanitizePriceInput`) and the
 * number it holds (`parsePrice`). Shared by every composer that takes a price
 * (the chat Composer, mass message, post, premade, Priority mass, Edit post).
 */

/** Accept "5", "5.00", "5,50". Returns null on garbage so submit stays
 *  free of guard-clauses on every read. */
export function parsePrice(raw: string): number | null {
  const cleaned = raw.replace(/\s/g, "").replace(",", ".");
  if (!cleaned) return null;
  const n = Number(cleaned);
  if (!Number.isFinite(n)) return null;
  return n;
}

/** Strip everything except digits and a single decimal separator from
 *  PPV input. Lets the user type "12.56" but bounces letters / "+5" /
 *  multiple dots so a paid send can never ship a malformed body. Empty
 *  string passes through so backspace clears the field cleanly. */
export function sanitizePriceInput(raw: string): string {
  // Allow commas as a decimal alias — `parsePrice` normalises to dot.
  const cleaned = raw.replace(/[^\d.,]/g, "").replace(/,/g, ".");
  const dot = cleaned.indexOf(".");
  if (dot === -1) return cleaned;
  // Keep only the FIRST decimal point; strip subsequent dots.
  return cleaned.slice(0, dot + 1) + cleaned.slice(dot + 1).replace(/\./g, "");
}
