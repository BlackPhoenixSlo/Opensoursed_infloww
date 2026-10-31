"use client";

/**
 * The Shift schedule's client: the wire types of `/admin/shifts`
 * (service/shifts_api.py), the week query, and the create, edit and cancel
 * calls the "Shifts" window sends.
 *
 * Weeks start on the Agency's week start day (Monday when never saved;
 * docs/spec/phase-04-apply-stored-settings.md, story 20). The Shift schedule
 * cuts them in the Agency's time zone (`zonedWeek`, page-parity ticket 18);
 * the Dashboard's "My shifts" still cuts them in the browser's (`weekStartOf`,
 * `addDays`). A week is seven calendar days, so across a daylight-saving
 * change it is 167 or 169 hours; `from` and `to` are its first-day midnights
 * converted to UTC.
 */

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useState } from "react";

import { pushNotice } from "@/lib/notices";
import { relay, RelayError } from "@/lib/relay";

export interface ShiftEmployee { id: number; display_name: string }
export interface ShiftCreator { id: string; display_name: string }

/** One Shift occurrence that intersects the asked range. `start_utc` and
 *  `end_utc` are its series' first occurrence; an edit starts from the
 *  occurrence itself (`occurrence_start`), and "All shifts" reaches back to
 *  `start_utc`. */
export interface ShiftOccurrence {
  shift_id: number;
  occurrence_start: string;
  occurrence_end: string;
  start_utc: string;
  end_utc: string;
  tz: string;
  repeat_days: number[] | null;
  repeat_until: string | null;
  employees: ShiftEmployee[];
  accounts: ShiftCreator[];
}

export interface ShiftWeek { occurrences: ShiftOccurrence[] }

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

/** The Agency's Shift occurrences in one week. Owner sessions only. */
export function useShiftWeek(filter: ShiftWeekFilter, enabled: boolean) {
  const path = shiftWeekPath(filter);
  return useQuery<ShiftWeek>({
    queryKey: ["shifts", "week", path],
    queryFn: () => relay.get<ShiftWeek>(path),
    enabled,
    staleTime: 30_000,
    refetchOnWindowFocus: false,
  });
}

/** One Employee's or one Creator's week in `GET /admin/shifts/timesheet`.
 *  `key` is the Employee id as text, or the Creator id. Money is gross cents
 *  as stored; there is no payroll field. */
export interface TimesheetRow {
  key: string;
  display_name: string;
  scheduled_shifts: number;
  shifts_worked: number;
  scheduled_minutes: number;
  worked_minutes: number;
  recorded_earnings_cents: number;
  open_now: boolean;
  /** The Employee and its group's name, on `group=employee` rows; null on a Creator's. */
  employee_id: number | null;
  group_name: string | null;
}

/** The one explanation of `recorded_earnings_cents` wherever an earnings
 *  column shows it (docs/spec/phase-02-shifts-time-tracking.md, App). */
export const RECORDED_EARNINGS_TIP =
  "Infloww calls this Total Earnings. Earnings already credited during worked time; not payroll.";

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

/** The Agency's Timesheet over [from, to), per Employee or per Creator. Owner
 *  sessions only. Shares the `["shifts"]` key prefix, so a Shift write
 *  refreshes it with the week. */
export function useTimesheet(from: Date, to: Date, group: TimesheetGroup, enabled: boolean) {
  const path = timesheetPath(from, to, group);
  return useQuery<{ rows: TimesheetRow[] }>({
    queryKey: ["shifts", "timesheet", path],
    queryFn: () => relay.get<{ rows: TimesheetRow[] }>(path),
    enabled,
    staleTime: 30_000,
    refetchOnWindowFocus: false,
  });
}

/** The body of a create (POST) or a whole-series edit (PATCH). */
export interface ShiftInput {
  start_utc: string;
  end_utc: string;
  tz: string;
  /** ISO weekdays, 1 = Monday … 7 = Sunday; null = no repeat. */
  repeat_days: number[] | null;
  /** Last local date (YYYY-MM-DD), inclusive; null = "Never". */
  repeat_until: string | null;
  employee_ids: number[];
  account_ids: string[];
  /** Write over the other Shifts it clashes with (roadmap W6 6.12): their clashing occurrences leave them (a series
   *  loses those dates, a one-off is cancelled) instead of a 409. The Shift's own double-staffing is still 409. */
  replace?: boolean;
  /** Grant the `grantable` pairs of an earlier 422 Creator access in the same write. */
  grant_access?: boolean;
}

/** One pair of a 422 the Relay clears on a `grant_access` resend: an Employee whose login lacks the Creator. */
export interface ShiftGrantable {
  employee_id: number;
  employee_name: string;
  account_id: string;
  account_name: string;
}

/** The grantable pairs of a 422 (`{detail, grantable}`), or null for any other error. */
export function shiftGrantable(e: unknown): ShiftGrantable[] | null {
  if (!(e instanceof RelayError) || e.status !== 422) return null;
  const g = e.body && typeof e.body === "object" && "grantable" in e.body ? e.body.grantable : null;
  return Array.isArray(g) && g.length > 0 ? (g as ShiftGrantable[]) : null;
}

/** A saved "common period" (the `shifts` blob's `presets`, roadmap W6 6.12): wall-clock "HH:MM" in the Shift's
 *  zone, an `end` before `start` ending the next day. */
export interface CommonPeriod { start: string; end: string }

/** A Shift as create, edit and cancel return it. */
export interface Shift {
  shift_id: number;
  start_utc: string;
  end_utc: string;
  tz: string;
  repeat_days: number[] | null;
  repeat_until: string | null;
  status: "scheduled" | "cancelled";
  employees: ShiftEmployee[];
  accounts: ShiftCreator[];
}

/** One clash in a 409 from the overlap rule (`{detail, clashes}`): another
 *  Shift's first clashing occurrence on a shared Creator, or `shift_id: null`
 *  for the Shift itself putting more than one Employee on that Creator. */
export interface ShiftClash {
  shift_id: number | null;
  occurrence_start: string;
  account_id: string;
}

/** The clashes of a 409 from the overlap rule, or null for any other error. */
export function shiftClashes(e: unknown): ShiftClash[] | null {
  if (!(e instanceof RelayError) || e.status !== 409) return null;
  const clashes = e.body && typeof e.body === "object" && "clashes" in e.body ? e.body.clashes : null;
  if (!Array.isArray(clashes) || clashes.length === 0) return null;
  return clashes.every((c) =>
    c && typeof c === "object" && typeof c.occurrence_start === "string" && typeof c.account_id === "string"
    && (c.shift_id === null || typeof c.shift_id === "number"),
  ) ? clashes : null;
}

export const createShift = (body: ShiftInput) => relay.post<Shift>("/admin/shifts", body);
/** How much of a weekly series an edit or a delete reaches, from one occurrence (roadmap W6 6.3,
 *  service/shifts_api.py): "this" is that occurrence alone, "following" it and every later one (the series ends
 *  the day before), "all" the whole series. Left out, the Relay reads "all". */
export type ShiftScope = "this" | "following" | "all";
export interface ShiftScopeAt { scope: ShiftScope; occurrence_start: string }

export const editShift = (id: number, body: ShiftInput, at?: ShiftScopeAt) =>
  relay.patch<Shift>(`/admin/shifts/${id}`, { ...body, ...at });
export const cancelShift = (id: number, at?: ShiftScopeAt) => relay.post<Shift>(`/admin/shifts/${id}/cancel`, at);

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

/** Infloww's Employee colours (`colors$2`, the first 12), handed out in first-seen order. */
export const EMPLOYEE_COLOURS = [
  "#FF7875", "#FFC069", "#D3F261", "#69B1FF", "#FF9C6E", "#5CDBD3",
  "#95DE64", "#85A5FF", "#FFF566", "#B37FEB", "#FFD666", "#FF85C0",
];

/** Each Employee's colour, by first appearance in `occurrences` (per render; nothing is stored). */
export function employeeColours(occurrences: ShiftOccurrence[]): (employeeId: number) => string {
  const seen = new Map<number, string>();
  for (const o of occurrences) {
    for (const e of o.employees) {
      if (!seen.has(e.id)) seen.set(e.id, EMPLOYEE_COLOURS[seen.size % EMPLOYEE_COLOURS.length]);
    }
  }
  return (id) => seen.get(id) ?? EMPLOYEE_COLOURS[0];
}

/* ── Clock in and out ─────────────────────────────────────────────────── */

/** One Employee's clock-in and its clock-out; `out_utc` null = open.
 *  `account_id` null is the agency-wide clock (the top bar's Clock in);
 *  older events, and a chatter in two Agencies, name a Creator. */
export interface ClockEvent {
  clock_event_id: number;
  employee_id: number | null;
  account_id: string | null;
  shift_id: number | null;
  in_utc: string;
  out_utc: string | null;
  close_reason: "manual" | "auto" | "owner_edit" | null;
}

/** A Creator the chatter can access, with its own Agency's time-tracking flags. */
export interface MyShiftsAccount {
  account_id: string;
  display_name: string;
  time_tracking_enabled: boolean;
  clock_in_reminder: boolean;
}

/** One of the chatter's own Shift occurrences on one Creator. */
export interface MyShiftOccurrence {
  shift_id: number;
  occurrence_start: string;
  occurrence_end: string;
  tz: string;
  account_id: string;
}

/** `GET /admin/shifts/me`: the chatter's own rows across every Agency it is
 *  linked to. `reminder` is a started, assigned occurrence with no clock-in
 *  while its Agency has time tracking and the reminder on, or null. */
export interface MyShifts {
  accounts: MyShiftsAccount[];
  occurrences: MyShiftOccurrence[];
  open_clocks: ClockEvent[];
  reminder: MyShiftOccurrence | null;
}

export const MY_SHIFTS_KEY = ["shifts", "me"] as const;
/** The Dashboard cards and the clock-in reminder re-read every minute. */
export const SHIFTS_POLL_MS = 60_000;

/** The chatter's Creators, Shifts and open Clock events, re-read every
 *  minute. Chatter sessions only: pass `enabled` false for anyone else. */
export function useMyShifts(enabled = true) {
  return useQuery<MyShifts>({
    queryKey: MY_SHIFTS_KEY,
    queryFn: () => relay.get<MyShifts>("/admin/shifts/me"),
    enabled,
    refetchInterval: SHIFTS_POLL_MS,
    refetchOnWindowFocus: false,
  });
}

/** One open Clock event in `GET /admin/shifts/clocked-in`; `shift` is the
 *  occurrence that holds the clock-in, or null for none, with the Creators
 *  the Employee holds in it (what an agency-wide event, `account` null,
 *  is named by). */
export interface ClockedInRow {
  clock_event_id: number;
  employee: ShiftEmployee | null;
  account: ShiftCreator | null;
  in_utc: string;
  shift_id: number | null;
  shift: { shift_id: number; occurrence_start: string; occurrence_end: string; accounts: ShiftCreator[] } | null;
}

export interface ClockedIn {
  time_tracking_enabled: boolean;
  clocked_in: ClockedInRow[];
}

/** The Agency's open Clock events and its time-tracking flag, re-read every
 *  minute. Owner and Master sessions only (403 for a chatter). */
export function useClockedIn(enabled: boolean) {
  return useQuery<ClockedIn>({
    queryKey: ["shifts", "clocked-in"],
    queryFn: () => relay.get<ClockedIn>("/admin/shifts/clocked-in"),
    enabled,
    refetchInterval: SHIFTS_POLL_MS,
    refetchOnWindowFocus: false,
  });
}

/** Clock in on `account_id`, or with none on the agency-wide clock. */
export const clockIn = (account_id?: string) =>
  relay.post<ClockEvent>("/admin/shifts/clock-in", account_id ? { account_id } : {});
export const clockOut = (clock_event_id: number) =>
  relay.post<ClockEvent>("/admin/shifts/clock-out", { clock_event_id });

/** `GET /admin/shifts/clock-status`, and what `POST /clock-heartbeat`
 *  returns: whether the caller may clock in (`reason` says why not, or
 *  `pick_creator` for a chatter in two Agencies, who names a Creator in
 *  `ClockDialog`), its open event, its latest event closed in the last 24 h,
 *  and the minutes of inactivity before Auto clock out. Any signed-in session. */
export interface ClockStatus {
  can_clock: boolean;
  reason: null | "time_tracking_off" | "role_not_enabled" | "inactive" | "pick_creator";
  open: ClockEvent | null;
  last_closed: { clock_event_id: number; out_utc: string; close_reason: ClockEvent["close_reason"] } | null;
  auto_clock_out_minutes: number;
  server_now: string;
}

export const CLOCK_STATUS_KEY = ["shifts", "clock-status"] as const;

/** The caller's ClockStatus, re-read every minute (the read sweeps overdue
 *  events, so an idle tab learns of its Auto clock out). */
export function useClockStatus(enabled: boolean) {
  return useQuery<ClockStatus>({
    queryKey: CLOCK_STATUS_KEY,
    queryFn: () => relay.get<ClockStatus>("/admin/shifts/clock-status"),
    enabled,
    refetchInterval: SHIFTS_POLL_MS,
    refetchOnWindowFocus: false,
  });
}

export const clockHeartbeat = () => relay.post<ClockStatus>("/admin/shifts/clock-heartbeat");

/** Infloww's clock copy (bundle @10614322). */
export const CLOCK_TEXT = {
  confirmIn: "Confirm clock in?",
  confirmOut: "Confirm clock out?",
  inOk: "Clock in successful",
  outOk: "Clock out successful",
  alreadyIn: "You are already clocked in",
  alreadyOut: "You are already clocked out",
  inactivity: "You have been clocked out due to inactivity",
  connectionLost: "You have been clocked out as your internet connection was lost.",
} as const;

/** A failed clock write as its toast: a 409 as Infloww's "already" line,
 *  unless the Relay refused it with a typed reason (`{error, message}`, such
 *  as `time_tracking_off`), whose message it shows. */
function clockError(e: unknown, already: string): string {
  if (e instanceof RelayError && e.status === 409 && !refusalReason(e)) return already;
  return e instanceof Error ? e.message : String(e);
}

/** The typed reason of a refused clock write (ClockStatus' `reason` words), or null. */
function refusalReason(e: RelayError): string | null {
  const detail = (e.body as { detail?: unknown } | null)?.detail;
  const error = detail && typeof detail === "object" ? (detail as { error?: unknown }).error : null;
  return typeof error === "string" ? error : null;
}

/** Numbers each successful clock write's toast, across every `useClock`, so
 *  "Clock in successful" twice (in, out, in) is two toasts. */
let clockWrites = 0;

/** Whether clocking in means naming a Creator first (a chatter in two Agencies). */
const picksCreator = (s: ClockStatus | undefined) => s?.reason === "pick_creator";

/**
 * The one clock action of the top bar's Clock button, the "My shifts" card,
 * the clock-in reminder and `ClockDialog`: the caller's ClockStatus; whether
 * a Clock button shows (`visible`: it may clock in or has an open event) and
 * its `label`; and `act()`, Clock out of the open event, else Clock in on
 * the agency-wide clock, else for a chatter in two Agencies (`reason:
 * "pick_creator"`) `picking`, which the caller answers with `ClockDialog`
 * (`clockInNow(account_id)`). `act` reads the status cached when it runs, so
 * a toast's action that runs later acts on the clock as it is then;
 * `act("in")` never clocks out (the reminder's "Clock in": an event opened
 * meanwhile gets the Relay's "You are already clocked in"). Each
 * write toasts Infloww's line and re-reads every `["shifts"]` query.
 *
 * ASSUMPTION: only the top bar asks "Confirm clock in?" / "Confirm clock
 * out?" first (Infloww's `ClockInOrOut`); the card's and the reminder's
 * buttons act at once, each already a labelled click on the clock. Rung 5.
 * Overturned if the owner wants every clock button to confirm.
 */
export function useClock(enabled = true) {
  const queryClient = useQueryClient();
  const status = useClockStatus(enabled);
  const [busy, setBusy] = useState(false);
  const [picking, setPicking] = useState(false);

  // A refusal's id is its text, so the same refusal twice while the first still shows is one toast.
  const run = useCallback(async (write: () => Promise<unknown>, ok: string, already: string) => {
    setBusy(true);
    try {
      await write();
      pushNotice({ id: `clock:${ok}:${++clockWrites}`, text: ok, label: "Time tracking" });
    } catch (e) {
      const text = clockError(e, already);
      pushNotice({ id: `clock:error:${text}`, text, label: "Time tracking" });
    } finally {
      setBusy(false);
      await queryClient.invalidateQueries({ queryKey: ["shifts"] });
    }
  }, [queryClient]);
  const clockInNow = useCallback(
    (account_id?: string) => run(() => clockIn(account_id), CLOCK_TEXT.inOk, CLOCK_TEXT.alreadyIn), [run]);
  const clockOutNow = useCallback(
    (id: number) => run(() => clockOut(id), CLOCK_TEXT.outOk, CLOCK_TEXT.alreadyOut), [run]);
  // Stable, so a toast's action may hold it.
  const act = useCallback((only?: "in") => {
    const now = queryClient.getQueryData<ClockStatus>(CLOCK_STATUS_KEY);
    if (now?.open && only !== "in") return clockOutNow(now.open.clock_event_id);
    if (picksCreator(now)) return setPicking(true);
    return clockInNow();
  }, [queryClient, clockInNow, clockOutNow]);
  const data = status.data;

  return {
    status,
    busy,
    visible: !!data && (data.can_clock || !!data.open),
    label: data?.open ? "Clock out" : "Clock in",
    /** `act()` would open the Creator picker rather than write. */
    picks: !data?.open && picksCreator(data),
    act,
    picking,
    closePicker: () => setPicking(false),
    clockInNow,
    clockOutNow,
  };
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

/* ── Clock records (Employee reports' "Clocked hours" modal) ──────────── */

/** One record of `GET /admin/shifts/clock-events`: `minutes` rounded up,
 *  null while open; `edited` once an Owner edit touched it. */
export interface ClockRecord extends ClockEvent {
  minutes: number | null;
  edited: boolean;
}

export function clockRecordsPath(employeeId: number, from: Date, to: Date): string {
  const qs = new URLSearchParams({ employee_id: String(employeeId), from: from.toISOString(), to: to.toISOString() });
  return `/admin/shifts/clock-events?${qs}`;
}

/** One Employee's Clock events intersecting [from, to), newest first. Owner
 *  and Master sessions only. */
export function useClockRecords(employeeId: number, from: Date, to: Date, enabled: boolean) {
  const path = clockRecordsPath(employeeId, from, to);
  return useQuery<{ clock_events: ClockRecord[] }>({
    queryKey: ["shifts", "clock-events", path],
    queryFn: () => relay.get<{ clock_events: ClockRecord[] }>(path),
    enabled,
    refetchOnWindowFocus: false,
  });
}

/** An Owner edit: either time or both; `out_utc` alone closes an open event. */
export interface ClockEdit { in_utc?: string; out_utc?: string }

export const editClockEvent = (id: number, body: ClockEdit) =>
  relay.patch<ClockEvent>(`/admin/shifts/clock-events/${id}`, body);

/** An Owner delete of a Clock event (roadmap W6 6.6): its time leaves the Timesheet and Employee reports. */
export const deleteClockEvent = (id: number) => relay.delete<{ deleted: number }>(`/admin/shifts/clock-events/${id}`);

/* ── Shift records (Shift history "By shift", roadmap W6 6.6) ─────────── */

/** One worked shift, a Clock event of `GET /admin/shifts/records`, with the sales credited to its Employee inside
 *  its time on its Creator (the Timesheet's Recorded earnings rule): `sales` how many, `sales_cents` their sum. */
export interface ShiftRecord extends ClockRecord {
  sales: number;
  sales_cents: number;
}

/** The Agency's Shift records intersecting [from, to), newest clock-in first. Owner and Master sessions only. */
export function useShiftRecords(from: Date, to: Date, enabled: boolean) {
  const path = `/admin/shifts/records?${new URLSearchParams({ from: from.toISOString(), to: to.toISOString() })}`;
  return useQuery<{ records: ShiftRecord[] }>({
    queryKey: ["shifts", "records", path],
    queryFn: () => relay.get<{ records: ShiftRecord[] }>(path),
    enabled,
    staleTime: 30_000,
    refetchOnWindowFocus: false,
  });
}
