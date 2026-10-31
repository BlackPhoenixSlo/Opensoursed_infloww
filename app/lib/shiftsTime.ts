/**
 * The Shift screens' pure time helpers: weeks, Agency time zones, labels,
 * durations, the `/admin/shifts` query paths, and the clock button's choice.
 * No React, no fetch; shifts.ts re-exports every name here.
 *
 * Weeks start on the Agency's week start day (Monday when never saved;
 * docs/spec/phase-04-apply-stored-settings.md, story 20). The Shift schedule
 * cuts them in the Agency's time zone (`zonedWeek`, page-parity ticket 18);
 * the Dashboard's "My shifts" still cuts them in the browser's (`weekStartOf`,
 * `addDays`). A week is seven calendar days, so across a daylight-saving
 * change it is 167 or 169 hours; `from` and `to` are its first-day midnights
 * converted to UTC.
 */

import type { ClockStatus } from "./shifts";

export type WeekStart = "monday" | "sunday";

/** Local midnight of the `start` day (Monday or Sunday) on or before `d`. */
export function weekStartOf(d: Date, start: WeekStart): Date {
  const m = new Date(d.getFullYear(), d.getMonth(), d.getDate());
  m.setDate(m.getDate() - (start === "sunday" ? m.getDay() : (m.getDay() + 6) % 7));
  return m;
}

/** `d` moved by whole local days (calendar days, not 24-hour steps). */
export function addDays(d: Date, days: number): Date {
  const out = new Date(d);
  out.setDate(out.getDate() + days);
  return out;
}

export interface ShiftWeekFilter {
  /** The week's first-day midnight. */
  weekStart: Date;
  /** The next week's first-day midnight; seven local days after `weekStart` when left out. */
  weekEnd?: Date;
  employeeId?: string;
  accountId?: string;
}

export function shiftWeekPath({ weekStart, weekEnd, employeeId, accountId }: ShiftWeekFilter): string {
  const qs = new URLSearchParams({
    from: weekStart.toISOString(),
    to: (weekEnd ?? addDays(weekStart, 7)).toISOString(),
  });
  if (employeeId) qs.set("employee_id", employeeId);
  if (accountId) qs.set("account_id", accountId);
  return `/admin/shifts?${qs}`;
}

/** Minutes as "7h 30m", the Shift history's hours format (Employee reports' Clocked hours use `calcMinutes`). */
export const fmtHours = (minutes: number) =>
  `${Math.floor(minutes / 60)}h ${String(minutes % 60).padStart(2, "0")}m`;

export type TimesheetGroup = "employee" | "account";

/** The Timesheet over [from, to): a week for the Shift history, a month for Manage employees. */
export function timesheetPath(from: Date, to: Date, group: TimesheetGroup): string {
  const qs = new URLSearchParams({
    from: from.toISOString(),
    to: to.toISOString(),
    group,
  });
  return `/admin/shifts/timesheet?${qs}`;
}

/** The browser's IANA timezone, which a new Shift row defaults to. */
export function browserTimeZone(): string {
  return Intl.DateTimeFormat().resolvedOptions().timeZone;
}

export const pad = (n: number) => String(n).padStart(2, "0");

/** Monday-first weekday labels, as the repeat picker shows them. */
export const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
export const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "09:00" in the viewer's timezone. */
export const hhmm = (d: Date) => `${pad(d.getHours())}:${pad(d.getMinutes())}`;
/** "13 Oct" in the viewer's timezone. */
export const dayMonth = (d: Date) => `${d.getDate()} ${MONTHS[d.getMonth()]}`;
/** "Tue 13 Oct 09:00" in `tz`, or in the viewer's timezone when it is left out. */
export const occurrenceLabel = (iso: string, tz?: string) => {
  if (tz) {
    const p = zonedParts(new Date(iso).getTime(), tz);
    const dow = new Date(Date.UTC(p.y, p.mo - 1, p.d)).getUTCDay();
    return `${WEEKDAYS[(dow + 6) % 7]} ${p.d} ${MONTHS[p.mo - 1]} ${pad(p.h)}:${pad(p.mi)}`;
  }
  const d = new Date(iso);
  return `${WEEKDAYS[(d.getDay() + 6) % 7]} ${dayMonth(d)} ${hhmm(d)}`;
};

/** An instant's wall clock in `tz`, as numbers (`mo` 1-12, `h` 0-23). */
export function zonedParts(ms: number, tz: string) {
  const parts = Object.fromEntries(
    new Intl.DateTimeFormat("en-US", {
      timeZone: tz, hourCycle: "h23",
      year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit",
    }).formatToParts(new Date(ms)).map((p) => [p.type, p.value]),
  );
  return { y: +parts.year, mo: +parts.month, d: +parts.day, h: +parts.hour % 24, mi: +parts.minute, s: +parts.second };
}

/** The wall-clock fields of an instant in `tz`, as if they were UTC (ms). */
function wallClockMs(ms: number, tz: string): number {
  const w = zonedParts(ms, tz);
  return Date.UTC(w.y, w.mo - 1, w.d, w.h, w.mi, w.s);
}

/** An ISO instant → the `YYYY-MM-DDTHH:mm` wall clock in `tz` that a
 *  `<input type="datetime-local">` holds. */
export function toZonedInput(iso: string, tz: string): string {
  const d = new Date(wallClockMs(new Date(iso).getTime(), tz));
  return `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())}T${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}`;
}

/** A `datetime-local` value, read as wall clock in `tz` → an ISO UTC
 *  string, or null when it is empty or not a time. */
export function fromZonedInput(value: string, tz: string): string | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})$/.exec(value);
  if (!m) return null;
  const wall = Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4], +m[5]);
  // The Relay's `_to_utc` rule: try the offset from a day before, then a day
  // after; the first that reads back as `wall` wins, so a repeated fall-back
  // time takes its first instant. A spring-forward gap time matches neither
  // and keeps the offset before the jump, landing after the gap (02:30 → 03:30).
  const offset = (x: number) => wallClockMs(x, tz) - x;
  const day = 86_400_000;
  const before = wall - offset(wall - day);
  const after = wall - offset(wall + day);
  const ms = wallClockMs(before, tz) === wall || wallClockMs(after, tz) !== wall ? before : after;
  return Number.isNaN(ms) ? null : new Date(ms).toISOString();
}

/** One day of a `zonedWeek`: [start, end) as instants, `date` its YYYY-MM-DD there, `ddd` "Mon", `dd` "05". */
export interface ZonedDay { start: Date; end: Date; date: string; ddd: string; dd: string; today: boolean }

const DAY_MS = 86_400_000;
const SUN_FIRST = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

/** The calendar day `i` days after `base` (a UTC midnight, in ms), as YYYY-MM-DD. */
const isoDay = (base: number, i: number) => new Date(base + i * DAY_MS).toISOString().slice(0, 10);

/**
 * The week `weeksAway` weeks from the one holding `now`, cut in `tz`: today's date there, back to the week's
 * `start` day, then each day's midnight in `tz` via `fromZonedInput` (the Relay's `_to_utc` rule, so a midnight
 * in a daylight-saving gap lands just after it). A fall-back week holds one 25-hour day.
 */
export function zonedWeek(now: Date, start: WeekStart, tz: string, weeksAway: number): { days: ZonedDay[] } {
  const p = zonedParts(now.getTime(), tz);
  const todayMs = Date.UTC(p.y, p.mo - 1, p.d);
  const dow = new Date(todayMs).getUTCDay();
  const base = todayMs - (start === "sunday" ? dow : (dow + 6) % 7) * DAY_MS + weeksAway * 7 * DAY_MS;
  const today = isoDay(todayMs, 0);
  const midnight = (i: number) => new Date(fromZonedInput(`${isoDay(base, i)}T00:00`, tz)!);
  const days = Array.from({ length: 7 }, (_, i) => {
    const date = isoDay(base, i);
    const d = new Date(base + i * DAY_MS);
    return {
      start: midnight(i), end: midnight(i + 1), date,
      ddd: SUN_FIRST[d.getUTCDay()], dd: pad(d.getUTCDate()), today: date === today,
    };
  });
  return { days };
}

/** "19 Oct – 25 Oct 2026": a `zonedWeek`'s first and last dates. */
export function weekRangeLabel(days: ZonedDay[]): string {
  const [first, last] = [days[0].date, days[6].date].map((d) => d.split("-").map(Number));
  return `${first[2]} ${MONTHS[first[1] - 1]} – ${last[2]} ${MONTHS[last[1] - 1]} ${last[0]}`;
}

/** "9:00 AM": an instant's wall clock in `tz` (Infloww's tile `hh:mm A`, unpadded). */
export function fmtShiftTime(iso: string, tz: string): string {
  const { h, mi } = zonedParts(new Date(iso).getTime(), tz);
  return `${h % 12 || 12}:${pad(mi)} ${h < 12 ? "AM" : "PM"}`;
}

/** "GMT+02:00": `tz`'s offset at the instant `iso`. */
export function gmtOffset(iso: string, tz: string): string {
  const ms = new Date(iso).getTime();
  const minutes = Math.round((wallClockMs(ms, tz) - Math.floor(ms / 1000) * 1000) / 60_000);
  const abs = Math.abs(minutes);
  return `GMT${minutes < 0 ? "-" : "+"}${pad(Math.floor(abs / 60))}:${pad(abs % 60)}`;
}

/** What `useClock`'s `act(only)` does with the cached ClockStatus: Clock out of the open event (unless `only` is
 *  "in"), else open the Creator picker for a chatter in two Agencies, else Clock in on the agency-wide clock.
 *  A union, not a bare word, so "out" carries the event to close and `act` need not re-check `open`. */
export function clockAction(
  status: ClockStatus | undefined, only?: "in",
): { kind: "out"; clockEventId: number } | { kind: "pick" } | { kind: "in" } {
  if (status?.open && only !== "in") return { kind: "out", clockEventId: status.open.clock_event_id };
  if (status?.reason === "pick_creator") return { kind: "pick" };
  return { kind: "in" };
}

/** Infloww's `convertSeconds`: "1 h 23 min", or "12 min" under an hour. */
export function convertSeconds(seconds: number): string {
  const minutes = Math.max(0, Math.floor(seconds / 60));
  const h = Math.floor(minutes / 60);
  return h > 0 ? `${h} h ${minutes % 60} min` : `${minutes} min`;
}

/** Infloww's `calcMinutes$1` (bundle @11228512), its Clocked hours format: "0min", "45min", "2h", "2h 5min",
 *  thousands grouped ("1,234h"). The report cell and the clock record lines use it. */
export function calcMinutes(minutes: number): string {
  const m = Math.max(0, Math.floor(minutes));
  const h = Math.floor(m / 60).toLocaleString("en-US");
  if (m === 0) return "0min";
  if (m % 60 === 0) return `${h}h`;
  if (m < 60) return `${m}min`;
  return `${h}h ${m % 60}min`;
}

export function clockRecordsPath(employeeId: number, from: Date, to: Date): string {
  const qs = new URLSearchParams({ employee_id: String(employeeId), from: from.toISOString(), to: to.toISOString() });
  return `/admin/shifts/clock-events?${qs}`;
}
