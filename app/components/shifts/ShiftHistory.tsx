"use client";

/**
 * The Shift schedule's "Shift history" tab body: the viewed week's Timesheet
 * (`GET /admin/shifts/timesheet`), per Employee by default or per Creator,
 * with Scheduled Shifts, Shifts Worked, scheduled and worked hours, Recorded
 * earnings and a dot for anyone clocked in now
 * (docs/spec/phase-02-shifts-time-tracking.md, App and Timesheet). The page
 * owns the query, so the tab bar's "Export" writes the rows shown here.
 *
 * Infloww's tab lists one row per Shift with chatting statistics (Sales,
 * Messages sent, PPVs, Keystrokes...), an Employee select and "Show only
 * employees with Chatter role"; the Timesheet holds none of those, so this
 * weekly summary stands in (not built, not faked; page-parity ticket 18), and
 * the tab's "By shift" view (ShiftRecords; roadmap W6 6.6) lists one row per
 * worked shift with its Sales. ShiftSchedule owns the tab's view switch. The
 * look is Infloww's legacy table (`IF_TABLE`).
 *
 * "Recorded earnings" is Infloww's "Total Earnings", renamed and explained in
 * its header's tooltip so nobody reads it as payroll. There is no pay column.
 *
 * ASSUMPTION: hours read "20h 00m" and money uses the stats surface's
 * `fmtCents`. Rung 5. Overturned by Inventory evidence of Infloww's own formats.
 */

import type { UseQueryResult } from "@tanstack/react-query";

import { EmptyState, IF_TABLE } from "@/components/ui/infloww";
import { fmtCents } from "@/lib/format";
import { fmtHours, RECORDED_EARNINGS_TIP, type TimesheetGroup, type TimesheetRow } from "@/lib/shifts";
import { cn } from "@/lib/utils";

/** The table's head cells; the Export CSV writes the same columns. */
export const historyHeads = (group: TimesheetGroup) => [
  group === "employee" ? "Employee" : "Creator",
  "Scheduled Shifts", "Shifts Worked", "Scheduled hours", "Worked hours", "Recorded earnings",
];

/** One row as the table prints it (the dot aside). */
export const historyCells = (r: TimesheetRow) => [
  r.display_name, r.scheduled_shifts, r.shifts_worked, fmtHours(r.scheduled_minutes), fmtHours(r.worked_minutes),
  fmtCents(r.recorded_earnings_cents),
];

export default function ShiftHistory({ sheet, group }: {
  sheet: UseQueryResult<{ rows: TimesheetRow[] }>;
  group: TimesheetGroup;
}) {
  const rows = sheet.data?.rows ?? [];
  const heads = historyHeads(group);

  return (
    <>
      {sheet.isError && (
        <EmptyState kind="error" className="min-h-[200px]" onRetry={() => void sheet.refetch()}
          text={`Couldn't load the Shift history: ${sheet.error?.message ?? "unknown error"}`} />
      )}
      {sheet.isLoading && <p className="text-fg-dim">Loading…</p>}

      {!sheet.isError && !sheet.isLoading && (
        <div className="mb-[60px] overflow-x-auto">
          <table className={cn(IF_TABLE.table, "min-w-[720px]")}>
            <thead>
              <tr>
                {heads.map((h, i) => (
                  <th key={h} title={i === heads.length - 1 ? RECORDED_EARNINGS_TIP : undefined}
                    className={cn(IF_TABLE.th, IF_TABLE.thDivider, i === heads.length - 1 && "cursor-help")}>
                    {i === heads.length - 1 ? <span className="underline decoration-dotted">{h}</span> : h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.key} className={IF_TABLE.row}>
                  {historyCells(r).map((c, i) => (
                    <td key={i} className={cn(IF_TABLE.td, i > 0 && "tabular-nums")}>
                      {i === 0 ? (
                        <span className="inline-flex items-center gap-1.5">
                          {r.open_now && (
                            <span role="img" aria-label="Clocked in now" title="Clocked in now"
                              className="inline-block h-2 w-2 rounded-full bg-ok" />
                          )}
                          {c}
                        </span>
                      ) : c}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
          {rows.length === 0 && (
            <EmptyState size="sm" text="No shifts or clock time this week" className="border-b border-border" />
          )}
        </div>
      )}
    </>
  );
}
