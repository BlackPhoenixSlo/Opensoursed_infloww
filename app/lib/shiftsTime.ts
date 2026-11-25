import type { ClockStatus } from "./shifts";

export type WeekStart = "monday" | "sunday";

export function weekStartOf(d: Date, start: WeekStart): Date {
  const m = new Date(d.getFullYear(), d.getMonth(), d.getDate());
  m.setDate(m.getDate() - (start === "sunday" ? m.getDay() : (m.getDay() + 6) % 7));
  return m;
}

export function addDays(d: Date, days: number): Date {
  const out = new Date(d);
  out.setDate(out.getDate() + days);
  return out;
}

export interface ShiftWeekFilter {
  weekStart: Date;
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

export const fmtHours = (minutes: number) =>
  `${Math.floor(minutes / 60)}h ${String(minutes % 60).padStart(2, "0")}m`;

export type TimesheetGroup = "employee" | "account";

export function timesheetPath(from: Date, to: Date, group: TimesheetGroup): string {
  const qs = new URLSearchParams({
    from: from.toISOString(),
    to: to.toISOString(),
    group,
  });
  return `/admin/shifts/timesheet?${qs}`;
}

export function browserTimeZone(): string {
  return Intl.DateTimeFormat().resolvedOptions().timeZone;
}

export const pad = (n: number) => String(n).padStart(2, "0");

export const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
export const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

export const hhmm = (d: Date) => `${pad(d.getHours())}:${pad(d.getMinutes())}`;
export const dayMonth = (d: Date) => `${d.getDate()} ${MONTHS[d.getMonth()]}`;
export const occurrenceLabel = (iso: string, tz?: string) => {
  if (tz) {
    const p = zonedParts(new Date(iso).getTime(), tz);
    const dow = new Date(Date.UTC(p.y, p.mo - 1, p.d)).getUTCDay();
    return `${WEEKDAYS[(dow + 6) % 7]} ${p.d} ${MONTHS[p.mo - 1]} ${pad(p.h)}:${pad(p.mi)}`;
  }
  const d = new Date(iso);
  return `${WEEKDAYS[(d.getDay() + 6) % 7]} ${dayMonth(d)} ${hhmm(d)}`;
};

export function zonedParts(ms: number, tz: string) {
  const parts = Object.fromEntries(
    new Intl.DateTimeFormat("en-US", {
      timeZone: tz, hourCycle: "h23",
      year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit",
    }).formatToParts(new Date(ms)).map((p) => [p.type, p.value]),
  );
  return { y: +parts.year, mo: +parts.month, d: +parts.day, h: +parts.hour % 24, mi: +parts.minute, s: +parts.second };
}

function wallClockMs(ms: number, tz: string): number {
  const w = zonedParts(ms, tz);
  return Date.UTC(w.y, w.mo - 1, w.d, w.h, w.mi, w.s);
}

export function toZonedInput(iso: string, tz: string): string {
  const d = new Date(wallClockMs(new Date(iso).getTime(), tz));
  return `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())}T${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}`;
}

export function fromZonedInput(value: string, tz: string): string | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})$/.exec(value);
  if (!m) return null;
  const wall = Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4], +m[5]);
  const offset = (x: number) => wallClockMs(x, tz) - x;
  const day = 86_400_000;
  // Relay _to_utc rule: a repeated fall-back time takes its first instant; a spring-forward gap time keeps the offset before the jump.
  const before = wall - offset(wall - day);
  const after = wall - offset(wall + day);
  const ms = wallClockMs(before, tz) === wall || wallClockMs(after, tz) !== wall ? before : after;
  return Number.isNaN(ms) ? null : new Date(ms).toISOString();
}

export interface ZonedDay { start: Date; end: Date; date: string; ddd: string; dd: string; today: boolean }

const DAY_MS = 86_400_000;
const SUN_FIRST = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

const isoDay = (base: number, i: number) => new Date(base + i * DAY_MS).toISOString().slice(0, 10);

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

export function weekRangeLabel(days: ZonedDay[]): string {
  const [first, last] = [days[0].date, days[6].date].map((d) => d.split("-").map(Number));
  return `${first[2]} ${MONTHS[first[1] - 1]} – ${last[2]} ${MONTHS[last[1] - 1]} ${last[0]}`;
}

export function fmtShiftTime(iso: string, tz: string): string {
  const { h, mi } = zonedParts(new Date(iso).getTime(), tz);
  return `${h % 12 || 12}:${pad(mi)} ${h < 12 ? "AM" : "PM"}`;
}

export function gmtOffset(iso: string, tz: string): string {
  const ms = new Date(iso).getTime();
  const minutes = Math.round((wallClockMs(ms, tz) - Math.floor(ms / 1000) * 1000) / 60_000);
  const abs = Math.abs(minutes);
  return `GMT${minutes < 0 ? "-" : "+"}${pad(Math.floor(abs / 60))}:${pad(abs % 60)}`;
}

export function clockAction(
  status: ClockStatus | undefined, only?: "in",
): { kind: "out"; clockEventId: number } | { kind: "pick" } | { kind: "in" } {
  if (status?.open && only !== "in") return { kind: "out", clockEventId: status.open.clock_event_id };
  if (status?.reason === "pick_creator") return { kind: "pick" };
  return { kind: "in" };
}

export function convertSeconds(seconds: number): string {
  const minutes = Math.max(0, Math.floor(seconds / 60));
  const h = Math.floor(minutes / 60);
  return h > 0 ? `${h} h ${minutes % 60} min` : `${minutes} min`;
}

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
