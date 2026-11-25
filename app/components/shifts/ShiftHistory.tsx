"use client";


import type { UseQueryResult } from "@tanstack/react-query";

import { EmptyState, IF_TABLE } from "@/components/ui/infloww";
import { fmtCents } from "@/lib/format";
import { fmtHours, RECORDED_EARNINGS_TIP, type TimesheetGroup, type TimesheetRow } from "@/lib/shifts";
import { cn } from "@/lib/utils";

export const historyHeads = (group: TimesheetGroup) => [
  group === "employee" ? "Employee" : "Creator",
  "Scheduled Shifts", "Shifts Worked", "Scheduled hours", "Worked hours", "Recorded earnings",
];

export const historyCells = (r: TimesheetRow, money: (cents: number) => string = fmtCents) => [
  r.display_name, r.scheduled_shifts, r.shifts_worked, fmtHours(r.scheduled_minutes), fmtHours(r.worked_minutes),
  money(r.recorded_earnings_cents),
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
