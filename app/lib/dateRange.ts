/**
 * dateRange.ts — shared date-boundary helpers for the date-range pickers.
 *
 * These three primitives (daysAgoISO / todayISO / toLocalIso) were copied
 * verbatim between app/app/messages/page.tsx and app/app/stats/page.tsx.
 * Two copies of UTC/local day-boundary math drift: a fix in one page
 * silently leaves the other wrong, and the boundary logic is
 * correctness-sensitive (it keeps a Pacific user's "today" aligned with
 * their wall clock). Centralized here so both consumers share one copy.
 */

/** The wall-clock parts of instant `at` in `timeZone` (the browser's when
 *  null or absent). */
function wallParts(at: Date, timeZone?: string | null) {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: timeZone ?? undefined, hourCycle: "h23",
    year: "numeric", month: "numeric", day: "numeric", hour: "numeric", minute: "numeric", second: "numeric",
  }).formatToParts(at);
  const part = (type: string) => Number(parts.find((p) => p.type === type)?.value);
  return { y: part("year"), m: part("month"), d: part("day"), h: part("hour"), mi: part("minute"), s: part("second") };
}

/** YYYY-MM-DD for `n` days ago (picker output format), in `timeZone` (the
 *  Agency's report time zone), or the browser's when null or absent. */
export function daysAgoISO(n: number, timeZone?: string | null): string {
  const { y, m, d } = wallParts(new Date(), timeZone);
  return new Date(Date.UTC(y, m - 1, d - n)).toISOString().slice(0, 10);
}

/** YYYY-MM-DD for today (picker output format), in `timeZone` when given. */
export function todayISO(timeZone?: string | null): string {
  return daysAgoISO(0, timeZone);
}

/** The reports' fixed range presets: today alone, or the last 7, 30, 90 or 365 days. */
export type FixedRangePreset = "day" | "7d" | "30d" | "90d" | "365d";

/** Each preset's calendar days, today included. */
export const PRESET_DAYS: Record<FixedRangePreset, number> = { day: 1, "7d": 7, "30d": 30, "90d": 90, "365d": 365 };

/** A report preset's `[from, to]`: exactly its `PRESET_DAYS` calendar days
 *  ending today, so "Last 7 days" is today and the 6 days before (Infloww's
 *  stop at yesterday; ours keep today, so today's pending sales show), in
 *  `timeZone` when given (docs/spec/phase-04-apply-stored-settings.md, story
 *  18). Every report's "Last N days" is this window. */
export function presetRange(p: FixedRangePreset, timeZone?: string | null): [string, string] {
  return [daysAgoISO(PRESET_DAYS[p] - 1, timeZone), todayISO(timeZone)];
}

/** The day `n` days after YYYY-MM-DD `day`. */
function shiftDay(day: string, n: number): string {
  const [y, m, d] = day.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d + n)).toISOString().slice(0, 10);
}

/** The day `n` years after YYYY-MM-DD `day`; a Feb 29 with no Feb 29 that
 *  year lands on Mar 1. */
export function shiftYears(day: string, n: number): string {
  const [y, m, d] = day.split("-").map(Number);
  return new Date(Date.UTC(y + n, m - 1, d)).toISOString().slice(0, 10);
}

/** The pickable days of Infloww's range pickers, `[min, max]`: none before one
 *  year ago, none after two days ahead, counted from today in `timeZone` (the
 *  report time zone; the browser's when null or absent). */
export function dateBounds(timeZone?: string | null): [string, string] {
  const today = todayISO(timeZone);
  return [shiftYears(today, -1), shiftDay(today, 2)];
}

/** How far `timeZone`'s wall clock (the browser's when null or absent) is
 *  ahead of UTC at instant `at`, in ms. */
function zoneOffsetMs(at: number, timeZone?: string | null): number {
  const { y, m, d, h, mi, s } = wallParts(new Date(at), timeZone);
  return Date.UTC(y, m - 1, d, h, mi, s) - Math.floor(at / 1000) * 1000;
}

/** The first instant of the day whose midnight read as UTC is `wall`, in
 *  `timeZone` (the browser's when null or absent). Of the two offset guesses,
 *  the earliest instant already on that day: on a day whose midnight is
 *  skipped that is the change itself, on one whose midnight repeats the first. */
function dayStartMs(wall: number, timeZone?: string | null): number {
  const first = wall - zoneOffsetMs(wall, timeZone);
  const second = wall - zoneOffsetMs(first, timeZone);
  const onDay = (at: number) => {
    const { y, m, d } = wallParts(new Date(at), timeZone);
    return Date.UTC(y, m - 1, d) >= wall;
  };
  return [Math.min(first, second), Math.max(first, second)].find(onDay) ?? Math.max(first, second);
}

/** The current calendar month in `timeZone` (the browser's when null or
 *  absent), or the one `back` months before it: its first instant, up to the
 *  next month's first instant. */
export function monthRange(timeZone?: string | null, back = 0): [Date, Date] {
  const { y, m } = wallParts(new Date(), timeZone);
  return [
    new Date(dayStartMs(Date.UTC(y, m - 1 - back, 1), timeZone)),
    new Date(dayStartMs(Date.UTC(y, m - back, 1), timeZone)),
  ];
}

// Convert a bare YYYY-MM-DD (picker output) into a full UTC-instant ISO
// string with millisecond precision: the day's first instant, or with
// `end=true` 1 ms before the next day's, in `timeZone` when given (the
// Agency's report time zone, so every report consumer gets the same window:
// phase-04 spec, story 18) or else the browser's. Ending at the next day's
// start means a skipped or repeated hour never leaves a gap or overlap.
// Backend `_parse_date` (stats.py) converts the tzinfo back to UTC; this
// keeps a Pacific user's "today" boundary aligned with their wall clock.
// A YYYY-MM-DDTHH:00 (the picker's hour precision) is that wall-clock hour's
// first instant, or with `end=true` 1 ms before the next hour's. Anything
// else that already has a time component is passed through.
export function toLocalIso(date: string | null, end: boolean, timeZone?: string | null): string | null {
  if (!date) return null;
  const hour = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):00$/.exec(date);
  if (hour) {
    const [y, m, d, h] = hour.slice(1).map(Number);
    const wall = Date.UTC(y, m - 1, d, h + (end ? 1 : 0));
    const at = wall - zoneOffsetMs(wall - zoneOffsetMs(wall, timeZone), timeZone);
    return new Date(end ? at - 1 : at).toISOString();
  }
  if (date.includes("T")) return date;
  const parts = date.split("-").map(Number);
  if (parts.length !== 3 || parts.some((n) => !Number.isFinite(n))) return date;
  const [y, m, d] = parts;
  const at = end ? dayStartMs(Date.UTC(y, m - 1, d + 1), timeZone) - 1 : dayStartMs(Date.UTC(y, m - 1, d), timeZone);
  return new Date(at).toISOString();
}

const HOUR_MS = 3_600_000;

/** The range of equal length just before picker range `[from, to]` (YYYY-MM-DD, or YYYY-MM-DDTHH:00 at hour
 *  precision), for the reports' change against the previous period; null without both ends or with `to` before
 *  `from`. Counted on the wall clock, whole hours with each day running 12 AM to 11 PM, and given back in the same
 *  form, so `toLocalIso` places it in the report time zone: a range over a daylight-saving change keeps its
 *  wall-clock hours, and a whole-day range gives whole days. */
export function priorRange(from: string | null, to: string | null): [string, string] | null {
  const wall = (v: string, end: boolean) => Date.parse(`${v.length > 10 ? v : `${v}T${end ? "23" : "00"}:00`}:00Z`);
  const back = (at: number, end: boolean) => {
    const iso = new Date(at).toISOString();
    return iso.slice(11, 13) === (end ? "23" : "00") ? iso.slice(0, 10) : `${iso.slice(0, 13)}:00`;
  };
  if (!from || !to) return null;
  const f = wall(from, false);
  const t = wall(to, true);
  if (!Number.isFinite(f) || !Number.isFinite(t) || t < f) return null;
  return [back(f - (t - f + HOUR_MS), false), back(f - HOUR_MS, true)];
}

/** The Dashboard's period tabs, by id (docs/infloww-layouts/dashboard.md,
 *  #22-#25 and #96; `week` and `lastMonth` are the bundles' own ids, #3, #96). */
export type Period = "yesterday" | "today" | "week" | "month" | "lastMonth";

/** A Dashboard period's `[from, to]` instants: whole days cut at midnight in
 *  `timeZone` (the Agency's report time zone, the browser's when null), `to`
 *  1 ms before the next period's first instant. `week` is the seven days from
 *  the last `weekStart`, `month` the whole calendar month, as the bundle cuts
 *  them (docs/spec/infloww-parity-round-2/phase-01-dashboard.md, Interfaces;
 *  stories 7, 8 and 10); `lastMonth` the whole calendar month before it. */
export function periodWindow(
  period: Period, timeZone: string | null, weekStart: "monday" | "sunday",
): [string, string] {
  if (period === "month" || period === "lastMonth") {
    const [first, next] = monthRange(timeZone, period === "lastMonth" ? 1 : 0);
    return [first.toISOString(), new Date(next.getTime() - 1).toISOString()];
  }
  let back = period === "yesterday" ? 1 : 0;
  let days = 1;
  if (period === "week") {
    const weekday = new Date(`${todayISO(timeZone)}T00:00:00Z`).getUTCDay();
    back = weekStart === "sunday" ? weekday : (weekday + 6) % 7;
    days = 7;
  }
  return [
    toLocalIso(daysAgoISO(back, timeZone), false, timeZone)!,
    toLocalIso(daysAgoISO(back - days + 1, timeZone), true, timeZone)!,
  ];
}
