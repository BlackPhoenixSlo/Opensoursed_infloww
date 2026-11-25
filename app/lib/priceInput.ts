export function parsePrice(raw: string): number | null {
  const cleaned = raw.replace(/\s/g, "").replace(",", ".");
  if (!cleaned) return null;
  const n = Number(cleaned);
  if (!Number.isFinite(n)) return null;
  return n;
}

// Bounces letters, "+5" and extra dots so a paid send never ships a malformed body.
export function sanitizePriceInput(raw: string): string {
  const cleaned = raw.replace(/[^\d.,]/g, "").replace(/,/g, ".");
  const dot = cleaned.indexOf(".");
  if (dot === -1) return cleaned;
  return cleaned.slice(0, dot + 1) + cleaned.slice(dot + 1).replace(/\./g, "");
}
