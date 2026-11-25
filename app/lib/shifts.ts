"use client";


import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useState } from "react";

import { pushNotice } from "@/lib/notices";
import { relay, RelayError } from "@/lib/relay";
import { errText } from "@/lib/errText";
import {
  clockAction, clockRecordsPath, shiftWeekPath, timesheetPath,
  type ShiftWeekFilter, type TimesheetGroup,
} from "./shiftsTime";

export {
  addDays, browserTimeZone, calcMinutes, clockAction, clockRecordsPath, convertSeconds, dayMonth, fmtHours,
  fmtShiftTime, fromZonedInput, gmtOffset, hhmm, MONTHS, occurrenceLabel, pad, shiftWeekPath, timesheetPath,
  toZonedInput, weekRangeLabel, weekStartOf, WEEKDAYS, zonedParts, zonedWeek,
} from "./shiftsTime";
export type { ShiftWeekFilter, TimesheetGroup, WeekStart, ZonedDay } from "./shiftsTime";

export interface ShiftEmployee { id: number; display_name: string }
export interface ShiftCreator { id: string; display_name: string }

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

export interface TimesheetRow {
  key: string;
  display_name: string;
  scheduled_shifts: number;
  shifts_worked: number;
  scheduled_minutes: number;
  worked_minutes: number;
  recorded_earnings_cents: number;
  open_now: boolean;
  employee_id: number | null;
  group_name: string | null;
}

export const RECORDED_EARNINGS_TIP =
  "Infloww calls this Total Earnings. Earnings already credited during worked time; not payroll.";

export function timesheetRefetchMs(from: Date, to: Date, now: number): number | false {
  return from.getTime() <= now && now < to.getTime() ? SHIFTS_POLL_MS : false;
}

export function useTimesheet(from: Date, to: Date, group: TimesheetGroup, enabled: boolean) {
  const path = timesheetPath(from, to, group);
  return useQuery<{ rows: TimesheetRow[] }>({
    queryKey: ["shifts", "timesheet", path],
    queryFn: () => relay.get<{ rows: TimesheetRow[] }>(path),
    enabled,
    staleTime: 30_000,
    // eslint-disable-next-line local/no-fixed-polling -- open-shift worked minutes grow with time, not on an event
    refetchInterval: () => timesheetRefetchMs(from, to, Date.now()),
    refetchOnWindowFocus: false,
  });
}

export interface ShiftInput {
  start_utc: string;
  end_utc: string;
  tz: string;
  repeat_days: number[] | null;
  repeat_until: string | null;
  employee_ids: number[];
  account_ids: string[];
  replace?: boolean;
  grant_access?: boolean;
}

export interface ShiftGrantable {
  employee_id: number;
  employee_name: string;
  account_id: string;
  account_name: string;
}

export function shiftGrantable(e: unknown): ShiftGrantable[] | null {
  if (!(e instanceof RelayError) || e.status !== 422) return null;
  const g = e.body && typeof e.body === "object" && "grantable" in e.body ? e.body.grantable : null;
  return Array.isArray(g) && g.length > 0 ? (g as ShiftGrantable[]) : null;
}

export interface CommonPeriod { start: string; end: string }

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

export interface ShiftClash {
  shift_id: number | null;
  occurrence_start: string;
  account_id: string;
}

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
export type ShiftScope = "this" | "following" | "all";
export interface ShiftScopeAt { scope: ShiftScope; occurrence_start: string }

export const editShift = (id: number, body: ShiftInput, at?: ShiftScopeAt) =>
  relay.patch<Shift>(`/admin/shifts/${id}`, { ...body, ...at });
export const cancelShift = (id: number, at?: ShiftScopeAt) => relay.post<Shift>(`/admin/shifts/${id}/cancel`, at);

export const EMPLOYEE_COLOURS = [
  "#FF7875", "#FFC069", "#D3F261", "#69B1FF", "#FF9C6E", "#5CDBD3",
  "#95DE64", "#85A5FF", "#FFF566", "#B37FEB", "#FFD666", "#FF85C0",
];

export function employeeColours(occurrences: ShiftOccurrence[]): (employeeId: number) => string {
  const seen = new Map<number, string>();
  for (const o of occurrences) {
    for (const e of o.employees) {
      if (!seen.has(e.id)) seen.set(e.id, EMPLOYEE_COLOURS[seen.size % EMPLOYEE_COLOURS.length]);
    }
  }
  return (id) => seen.get(id) ?? EMPLOYEE_COLOURS[0];
}


export interface ClockEvent {
  clock_event_id: number;
  employee_id: number | null;
  account_id: string | null;
  shift_id: number | null;
  in_utc: string;
  out_utc: string | null;
  close_reason: "manual" | "auto" | "owner_edit" | null;
}

export interface MyShiftsAccount {
  account_id: string;
  display_name: string;
  time_tracking_enabled: boolean;
  clock_in_reminder: boolean;
}

export interface MyShiftOccurrence {
  shift_id: number;
  occurrence_start: string;
  occurrence_end: string;
  tz: string;
  account_id: string;
}

export interface MyShifts {
  accounts: MyShiftsAccount[];
  occurrences: MyShiftOccurrence[];
  open_clocks: ClockEvent[];
  reminder: MyShiftOccurrence | null;
}

export const MY_SHIFTS_KEY = ["shifts", "me"] as const;
export const SHIFTS_POLL_MS = 60_000;

export function useMyShifts(enabled = true) {
  return useQuery<MyShifts>({
    queryKey: MY_SHIFTS_KEY,
    queryFn: () => relay.get<MyShifts>("/admin/shifts/me"),
    enabled,
    // eslint-disable-next-line local/no-fixed-polling -- reminder is time-driven, not change-driven
    refetchInterval: SHIFTS_POLL_MS,
    refetchOnWindowFocus: false,
  });
}

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

export function useClockedIn(enabled: boolean) {
  return useQuery<ClockedIn>({
    queryKey: ["shifts", "clocked-in"],
    queryFn: () => relay.get<ClockedIn>("/admin/shifts/clocked-in"),
    enabled,
    // eslint-disable-next-line local/no-fixed-polling -- other chatters' clock events have no SSE event (TODO verify)
    refetchInterval: SHIFTS_POLL_MS,
    refetchOnWindowFocus: false,
  });
}

export const clockIn = (account_id?: string) =>
  relay.post<ClockEvent>("/admin/shifts/clock-in", account_id ? { account_id } : {});
export const clockOut = (clock_event_id: number) =>
  relay.post<ClockEvent>("/admin/shifts/clock-out", { clock_event_id });

export interface ClockStatus {
  can_clock: boolean;
  reason: null | "time_tracking_off" | "role_not_enabled" | "inactive" | "pick_creator";
  open: ClockEvent | null;
  last_closed: { clock_event_id: number; out_utc: string; close_reason: ClockEvent["close_reason"] } | null;
  auto_clock_out_minutes: number;
  server_now: string;
}

export const CLOCK_STATUS_KEY = ["shifts", "clock-status"] as const;

export function useClockStatus(enabled: boolean) {
  return useQuery<ClockStatus>({
    queryKey: CLOCK_STATUS_KEY,
    queryFn: () => relay.get<ClockStatus>("/admin/shifts/clock-status"),
    enabled,
    // eslint-disable-next-line local/no-fixed-polling -- the read sweeps overdue events; auto clock out is time-driven
    refetchInterval: SHIFTS_POLL_MS,
    refetchOnWindowFocus: false,
  });
}

export const clockHeartbeat = () => relay.post<ClockStatus>("/admin/shifts/clock-heartbeat");

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

function clockError(e: unknown, already: string): string {
  if (e instanceof RelayError && e.status === 409 && !refusalReason(e)) return already;
  return errText(e);
}

function refusalReason(e: RelayError): string | null {
  const detail = (e.body as { detail?: unknown } | null)?.detail;
  const error = detail && typeof detail === "object" ? (detail as { error?: unknown }).error : null;
  return typeof error === "string" ? error : null;
}

let clockWrites = 0;

export function useClock(enabled = true) {
  const queryClient = useQueryClient();
  const status = useClockStatus(enabled);
  const [busy, setBusy] = useState(false);
  const [picking, setPicking] = useState(false);

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
  const act = useCallback((only?: "in") => {
    const now = queryClient.getQueryData<ClockStatus>(CLOCK_STATUS_KEY);
    const a = clockAction(now, only);
    switch (a.kind) {
      case "out": return clockOutNow(a.clockEventId);
      case "pick": return setPicking(true);
      case "in": return clockInNow();
    }
  }, [queryClient, clockInNow, clockOutNow]);
  const data = status.data;

  return {
    status,
    busy,
    visible: !!data && (data.can_clock || !!data.open),
    label: data?.open ? "Clock out" : "Clock in",
    picks: clockAction(data).kind === "pick",
    act,
    picking,
    closePicker: () => setPicking(false),
    clockInNow,
    clockOutNow,
  };
}


export interface ClockRecord extends ClockEvent {
  minutes: number | null;
  edited: boolean;
}

export function useClockRecords(employeeId: number, from: Date, to: Date, enabled: boolean) {
  const path = clockRecordsPath(employeeId, from, to);
  return useQuery<{ clock_events: ClockRecord[] }>({
    queryKey: ["shifts", "clock-events", path],
    queryFn: () => relay.get<{ clock_events: ClockRecord[] }>(path),
    enabled,
    refetchOnWindowFocus: false,
  });
}

export interface ClockEdit { in_utc?: string; out_utc?: string }

export const editClockEvent = (id: number, body: ClockEdit) =>
  relay.patch<ClockEvent>(`/admin/shifts/clock-events/${id}`, body);

export const deleteClockEvent = (id: number) => relay.delete<{ deleted: number }>(`/admin/shifts/clock-events/${id}`);


export interface ShiftRecord extends ClockRecord {
  sales: number;
  sales_cents: number;
}

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
