/** A ready-made rule's interval as the editor's value + unit pair. */

export type Unit = "minutes" | "hours";
export const UNIT_S: Record<Unit, number> = { minutes: 60, hours: 3600 };

/** Largest tidy unit (≥ minutes) that divides `secs` cleanly. */
export function splitInterval(secs: number): { value: number; unit: Unit } {
  if (secs > 0 && secs % 3600 === 0) return { value: secs / 3600, unit: "hours" };
  return { value: Math.max(1, Math.round(secs / 60)), unit: "minutes" };
}
