/** A caught error as one UI line: an Error's message, else the value as text; `fallback` when that is empty. */
export const errText = (e: unknown, fallback = "failed"): string =>
  (e instanceof Error ? e.message : String(e ?? "")) || fallback;
