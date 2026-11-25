export const errText = (e: unknown, fallback = "failed"): string =>
  (e instanceof Error ? e.message : String(e ?? "")) || fallback;
