"use client";


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
export const CLOCKED_HOURS_TIP = "Number of hours worked based on clocked time, rounded up to the nearest minute";

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
  // Timesheet and clocked-in reads are owner/Master only (403 for a chatter)
  if (!user) return null;
  return <OwnerClockedHours from={from} to={to} />;
}

function OwnerClockedHours({ from, to }: { from: string | null; to: string | null }) {
  const tracking = useClockedIn(true);
  // time-tracking flag comes from clocked-in: Applied settings carries no such key; off = no Timesheet request
  const on = tracking.data?.time_tracking_enabled === true;
  const ranged = !!from && !!to;
  const sheet = useTimesheet(new Date(from ?? 0), new Date(to ?? 0), "employee", on && ranged);
  const rows = sheet.data?.rows ?? [];
  const failed = tracking.isError ? tracking.error : sheet.isError ? sheet.error : null;
  const [records, setRecords] = useState<TimesheetRow | null>(null);
  const exportAllowed = useActionAllowed("export");

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
