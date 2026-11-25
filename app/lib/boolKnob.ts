export function boolKnob(v: unknown, dflt: boolean): boolean {
  // Loose == null on purpose: stored null must mean absent (default), not false; rest follows python truthiness ([] / {} falsy).
  if (v == null) return dflt;
  if (Array.isArray(v)) return v.length > 0;
  if (typeof v === "object") return Object.keys(v).length > 0;
  return Boolean(v);
}
