/** `IfDateInput`'s pure value maths: the native input's own strings (`YYYY-MM-DD`, `HH:mm`, `YYYY-MM-DDTHH:mm`) in
 *  and out, so a call site keeps its state as it was with `<input type="date">`. */

export type DateMode = "date" | "time" | "datetime-local";

const pad = (n: number) => String(n).padStart(2, "0");
const DAY = /^\d{4}-\d{2}-\d{2}$/;
const TIME = /^\d{2}:\d{2}/;

/** A value's day (`YYYY-MM-DD`) and time (`HH:mm`), "" where it has none or the part is malformed. */
export function splitValue(mode: DateMode, value: string): { day: string; time: string } {
  if (mode === "time") return { day: "", time: TIME.test(value) ? value.slice(0, 5) : "" };
  const [d = "", t = ""] = value.split("T");
  return { day: DAY.test(d) ? d : "", time: mode === "datetime-local" && TIME.test(t) ? t.slice(0, 5) : "" };
}

/** The input's value from a day and a time. A date-time with a day but no time takes midnight; with no day, "". */
export function joinValue(mode: DateMode, day: string, time: string): string {
  if (mode === "date") return day;
  if (mode === "time") return time;
  return day ? `${day}T${time || "00:00"}` : "";
}

export const dayKey = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
export const timeKey = (d: Date) => `${pad(d.getHours())}:${pad(d.getMinutes())}`;

/** `YYYY-MM` moved `by` months. */
export function shiftMonth(month: string, by: number): string {
  const d = new Date(Number(month.slice(0, 4)), Number(month.slice(5, 7)) - 1 + by, 1);
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}`;
}

/** The 42 days (6 weeks, Sunday first, as antd's en-US calendar) that show `YYYY-MM`, with the edge weeks' days of the
 *  months either side. */
export function monthGrid(month: string): string[] {
  const first = new Date(Number(month.slice(0, 4)), Number(month.slice(5, 7)) - 1, 1);
  const start = new Date(first.getFullYear(), first.getMonth(), 1 - first.getDay());
  return Array.from({ length: 42 }, (_, i) => dayKey(new Date(start.getFullYear(), start.getMonth(), start.getDate() + i)));
}

/** Whether `day` lies within the input's `min`/`max` (a date-time bound is compared by its day). */
export function dayAllowed(day: string, min?: string, max?: string): boolean {
  return (!min || day >= min.slice(0, 10)) && (!max || day <= max.slice(0, 10));
}

/** The minute column for the input's `step` (seconds): every minute by default, the step's minutes when it is a whole
 *  number of them, only ":00" from an hour up. */
export function minuteOptions(step?: number | string): number[] {
  const s = Number(step);
  const every = Number.isFinite(s) && s >= 60 ? Math.min(60, Math.round(s / 60)) : 1;
  return Array.from({ length: Math.ceil(60 / every) }, (_, i) => i * every);
}

/** `HH:mm` with the hour or the minute replaced (the other kept, else 00). */
export function setTimePart(time: string, part: "h" | "m", n: number): string {
  const [h = "00", m = "00"] = (time || "00:00").split(":");
  return part === "h" ? `${pad(n)}:${m}` : `${h}:${pad(n)}`;
}

/** `value` held inside the input's `min`/`max` (same-format strings compare in order), so a picked day on the bound's
 *  day can't land before a date-time `min` (a past schedule would send at once). A bound of another shape is ignored. */
export function clampValue(value: string, min?: string, max?: string): string {
  if (!value) return value;
  if (min && min.length === value.length && value < min) return min;
  if (max && max.length === value.length && value > max) return max;
  return value;
}
