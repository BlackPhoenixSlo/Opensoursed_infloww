"use client";

/**
 * ClockedHoursCard — Employee reports' "Clocked hours" (docs/spec/phase-05-remaining-parity-gaps.md, item 2,
 * stories 14-18): per Employee, the scheduled Shifts, Shifts worked, clocked hours and Recorded earnings over
 * the report's range, read from Phase 2's Timesheet rollup (`GET /admin/shifts/timesheet?group=employee`).
 * The card turns the rollup's minutes into hours and does no other arithmetic; range, timezone and open-clock
 * handling are the rollup's. Of Infloww's four views only "Total by employee" is built; the other three are
 * Not wired (ADR-0008), because the Timesheet groups by Employee or by Creator only. "Export" downloads the
 * visible rows as CSV on the client (the `CompetitorReports` precedent). No new Relay endpoint.
 *
 * ASSUMPTION: the time-tracking flag is read from `GET /admin/shifts/clocked-in` (the owner's "My shifts"
 * card's source, ShiftCards.tsx), because the Applied settings read carries no time-tracking key
 * (app/lib/appliedSettings.ts `AppliedSettings`). With time tracking off the card says so and requests no
 * Timesheet, even if clock time was recorded while it was on. Rung 3 for the source, rung 5 for the gate.
 * Overturned if the owner wants past clock time shown while time tracking is off.
 *
 * ASSUMPTION: the card renders only for a user session (an owner, or the Master, which is a `users` row with
 * `is_admin`; CONTEXT.md, Master), the same `user` gate as the Dashboard's ClockedInCard (ShiftCards.tsx),
 * because the Timesheet and the clocked-in read are owner and Master only (403 for a chatter); a chatter's
 * Employee reports simply lack it. Rung 3. Overturned when the Timesheet gains a Data scope for chatters (spec,
 * Implementation Decisions).
 *
 * ASSUMPTION: a range longer than the Timesheet allows (42 days, the Relay's limit) shows the Relay's own 422
 * refusal text as a neutral note, not an error; the client keeps no copy of the limit. Rung 5. Overturned if
 * the owner wants long ranges (the Relay's limit raised, or the range split on the client).
 *
 * ASSUMPTION: the table shows hours in Infloww's `calcMinutes` ("7h 30min", "0min") and money with `fmtCents`; the CSV
 * carries decimal hours to two places and dollars to two places (CompetitorReports' `dollars`), headed by the
 * table's column names. Rung 3. Overturned by Infloww's own export columns (its export is xlsx).
 *
 * The CSV helpers are lib/csv.ts, shared with ClockRecordsModal (its twins are listed there).
 *
 * A row's Clocked hours opens ClockRecordsModal, that Employee's Clock events (w4-a).
 */

import { useState, type ReactNode } from "react";

import { useActionAllowed } from "@/components/shell/useGrantedPages";
import ClockRecordsModal from "@/components/stats/ClockRecordsModal";
import { Card } from "@/components/ui/primitives";
import { useUser } from "@/contexts/UserContext";
import { downloadCsv } from "@/lib/csv";
import { fmtCents } from "@/lib/format";
import { RelayError } from "@/lib/relay";
import { calcMinutes, RECORDED_EARNINGS_TIP, useClockedIn, useTimesheet, type TimesheetRow } from "@/lib/shifts";

export const PLATFORM_NOTICE = "Clocked hours are not differentiated by platform.";
/** Infloww's report wording for the Clocked hours column. */
export const CLOCKED_HOURS_TIP = "Number of hours worked based on clocked time, rounded up to the nearest minute";

/** Infloww's view picker (H262078); only the first is built. */
const BUILT_VIEW = "Total by employee";
const NOT_WIRED_VIEWS = [
  "Total creators by day (daily) by employee",
  "Total by creator by employee",
  "By creator by day by employee",
];

const BUTTON = "text-xs px-3 py-1.5 border border-border first:rounded-l-lg last:rounded-r-lg";
const CELL = "px-2 md:px-4 py-2";

function downloadTimesheet(rows: TimesheetRow[]) {
  downloadCsv("clocked-hours.csv", [
    ["Employee", "Scheduled shifts", "Shifts worked", "Clocked hours", "Recorded earnings (USD)"],
    ...rows.map((r) => [
      r.display_name, r.scheduled_shifts, r.shifts_worked,
      (r.worked_minutes / 60).toFixed(2), (r.recorded_earnings_cents / 100).toFixed(2),
    ]),
  ]);
}

export default function ClockedHoursCard({ from, to }: { from: string | null; to: string | null }) {
  const { user } = useUser();
  if (!user) return null;
  return <OwnerClockedHours from={from} to={to} />;
}

function OwnerClockedHours({ from, to }: { from: string | null; to: string | null }) {
  const tracking = useClockedIn(true);
  const on = tracking.data?.time_tracking_enabled === true;
  const ranged = !!from && !!to;
  const sheet = useTimesheet(new Date(from ?? 0), new Date(to ?? 0), "employee", on && ranged);
  const rows = sheet.data?.rows ?? [];
  const failed = tracking.isError ? tracking.error : sheet.isError ? sheet.error : null;
  const [records, setRecords] = useState<TimesheetRow | null>(null);
  const exportAllowed = useActionAllowed("export");

  // The one place the card's state is decided: `table` is set only where the table renders, and Export follows it.
  let table: TimesheetRow[] | null = null;
  let body: ReactNode = null;
  if (failed instanceof RelayError && failed.status === 422) {
    body = <p className="p-6 text-sm text-fg-dim text-center">{failed.message}</p>;
  } else if (failed) {
    body = <p className="p-4 text-sm text-err">{`Couldn't load Clocked hours: ${failed.message}`}</p>;
  } else if (tracking.isPending || (on && ranged && sheet.isPending)) {
    body = <p className="p-4 text-sm text-fg-dim">Loading…</p>;
  } else if (!on) {
    body = <p className="p-6 text-sm text-fg-dim text-center">Time tracking is off</p>;
  } else if (!ranged) {
    body = <p className="p-6 text-sm text-fg-dim text-center">Choose a date range.</p>;
  } else if (rows.length === 0) {
    body = <p className="p-6 text-sm text-fg-dim text-center">No Shifts or clock time in this range.</p>;
  } else {
    table = rows;
    body = (
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-[11px] uppercase tracking-wide text-fg-dim border-b border-border">
              <th className={`${CELL} font-medium text-left`}>Employee</th>
              <th className={`${CELL} font-medium text-right`}>Scheduled shifts</th>
              <th className={`${CELL} font-medium text-right`}>Shifts worked</th>
              <th className={`${CELL} font-medium text-right cursor-help underline decoration-dotted`}
                title={CLOCKED_HOURS_TIP}>
                Clocked hours
              </th>
              <th className={`${CELL} font-medium text-right cursor-help underline decoration-dotted`}
                title={RECORDED_EARNINGS_TIP}>
                Recorded earnings
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.key} className="border-t border-border">
                <td className={CELL}>{r.display_name}</td>
                <td className={`${CELL} text-right tabular-nums`}>{r.scheduled_shifts}</td>
                <td className={`${CELL} text-right tabular-nums`}>{r.shifts_worked}</td>
                <td className={`${CELL} text-right tabular-nums`}>
                  {/* Infloww's cell: a #1890ff link, no underline, in `calcMinutes` ("0min"; live w5-a). */}
                  <button type="button" className="text-accent hover:opacity-80"
                    title={`${r.display_name}'s clock records`} onClick={() => setRecords(r)}>
                    {calcMinutes(r.worked_minutes)}
                  </button>
                </td>
                <td className={`${CELL} text-right tabular-nums`}>{fmtCents(r.recorded_earnings_cents)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }

  const exportRows = exportAllowed ? table : null;
  return (
    <Card className="p-0 overflow-hidden" aria-label="Clocked hours">
      <header className="flex flex-col md:flex-row md:items-center justify-between p-4 border-b border-border gap-3">
        <div>
          <h2 className="text-sm font-medium text-fg">Clocked hours</h2>
          <p className="text-xs text-fg-dim mt-0.5">{PLATFORM_NOTICE}</p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex flex-wrap">
            <button type="button" aria-pressed="true" className={`${BUTTON} bg-bg-elev-2 font-medium`}>
              {BUILT_VIEW}
            </button>
            {NOT_WIRED_VIEWS.map((label) => (
              <button key={label} type="button" disabled title="not wired"
                className={`${BUTTON} bg-bg text-fg-dim cursor-not-allowed`}>
                {label}
              </button>
            ))}
          </div>
          {exportRows && (
            <button type="button" onClick={() => downloadTimesheet(exportRows)}
              className="text-xs px-3 py-1.5 rounded-lg bg-bg-elev-1 hover:bg-bg-elev-2 border border-border">
              Export
            </button>
          )}
        </div>
      </header>
      {body}
      {records?.employee_id != null && from && to && (
        <ClockRecordsModal employeeId={records.employee_id} employeeName={records.display_name}
          groupName={records.group_name ?? ""} from={from} to={to} onClose={() => setRecords(null)} />
      )}
    </Card>
  );
}
