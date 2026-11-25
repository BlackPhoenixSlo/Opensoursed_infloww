"use client";


import { useState } from "react";
import { useQueryClient, type UseQueryResult } from "@tanstack/react-query";

import ReassignOptions, { attributeTo } from "@/components/analytics/ReassignOptions";
import { RecordEditor, clockStamp } from "@/components/stats/ClockRecordsModal";
import { EmptyState, IF_TABLE } from "@/components/ui/infloww";
import { useBatchAttribute } from "@/hooks/useStats";
import { fmtCents } from "@/lib/format";
import { RelayError } from "@/lib/relay";
import { deleteClockEvent, fmtHours, RECORDED_EARNINGS_TIP, type ShiftRecord } from "@/lib/shifts";
import { cn } from "@/lib/utils";
import { ifConfirm } from "@/components/ui/ifConfirm";

const LINK = "text-xs text-fg-dim hover:text-fg underline disabled:opacity-50";
const SELECT = "bg-bg border border-border rounded-lg px-2 py-1 text-xs text-fg";
const DELETE_CONFIRM = "Delete this shift record? Its time leaves the Shift history and Employee reports.";

export interface RecordNames {
  employee: (id: number | null) => string;
  creator: (id: string | null) => string;
}

export const recordHeads = (tz: string) => [
  "Employee", "Creator", `Clock in (${tz})`, `Clock out (${tz})`, "Worked hours", "Sales", "Recorded earnings",
];

export const recordCells = (r: ShiftRecord, tz: string, names: RecordNames, money: (cents: number) => string = fmtCents) => [
  names.employee(r.employee_id), names.creator(r.account_id), clockStamp(r.in_utc, tz),
  r.out_utc ? clockStamp(r.out_utc, tz) : "Clocked in", r.minutes == null ? "-" : fmtHours(r.minutes), r.sales,
  money(r.sales_cents),
];

export default function ShiftRecords({ records, tz, names, employees }: {
  records: UseQueryResult<{ records: ShiftRecord[] }>;
  tz: string;
  names: RecordNames;
  employees: { id: number; label: string }[];
}) {
  const rows = records.data?.records ?? [];
  const heads = [...recordHeads(tz), "Action"];
  if (records.isError) {
    return (
      <EmptyState kind="error" className="min-h-[200px]" onRetry={() => void records.refetch()}
        text={`Couldn't load the Shift records: ${records.error?.message ?? "unknown error"}`} />
    );
  }
  if (records.isLoading) return <p className="text-fg-dim">Loading…</p>;
  return (
    <div className="mb-[60px] overflow-x-auto">
      <table className={cn(IF_TABLE.table, "min-w-[960px]")} aria-label="Shift records">
        <thead>
          <tr>
            {heads.map((h) => (
              <th key={h} title={h === "Recorded earnings" ? RECORDED_EARNINGS_TIP : undefined}
                className={cn(IF_TABLE.th, IF_TABLE.thDivider)}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => <RecordRow key={r.clock_event_id} record={r} tz={tz} names={names} employees={employees} />)}
        </tbody>
      </table>
      {rows.length === 0 && <EmptyState size="sm" text="No shift records this week" className="border-b border-border" />}
    </div>
  );
}

function RecordRow({ record: r, tz, names, employees }: {
  record: ShiftRecord; tz: string; names: RecordNames; employees: { id: number; label: string }[];
}) {
  const queryClient = useQueryClient();
  const [mode, setMode] = useState<"edit" | "reassign" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const remove = async () => {
    if (!(await ifConfirm(DELETE_CONFIRM, { danger: true }))) return;
    setBusy(true);
    setError(null);
    try {
      await deleteClockEvent(r.clock_event_id);
      await queryClient.invalidateQueries({ queryKey: ["shifts"] });
    } catch (e) {
      setError(e instanceof RelayError || e instanceof Error ? e.message : "Couldn't delete the record.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <tr className={IF_TABLE.row}>
      {recordCells(r, tz, names).map((c, i) => (
        <td key={i} className={cn(IF_TABLE.td, i > 1 && "tabular-nums")}>{c}</td>
      ))}
      <td className={IF_TABLE.td}>
        {mode === "edit" ? (
          <RecordEditor record={r} tz={tz} closing={false} onDone={() => setMode(null)} />
        ) : mode === "reassign" ? (
          <ReassignSales clockEventId={r.clock_event_id} employees={employees} onDone={(skipped) => {
            setMode(null);
            setNote(skipped > 0 ? splitNote(skipped) : null);
          }} />
        ) : (
          <div className="flex flex-wrap gap-3">
            <button type="button" className={LINK} onClick={() => setMode("edit")} disabled={busy}>Edit</button>
            <button type="button" className={LINK} onClick={() => void remove()} disabled={busy}>Delete</button>
            <button type="button" className={LINK} onClick={() => setMode("reassign")} disabled={busy || r.sales === 0}>
              Reassign sales
            </button>
          </div>
        )}
        {error && <p className="text-xs text-err" role="alert">{error}</p>}
        {note && <p className="text-xs text-fg-dim" role="status">{note}</p>}
      </td>
    </tr>
  );
}

const splitNote = (n: number) =>
  `${n} split sale${n === 1 ? " was" : "s were"} left unchanged: shared with other employees on the shift.`;

function ReassignSales({ clockEventId, employees, onDone }: {
  clockEventId: number; employees: { id: number; label: string }[]; onDone: (skippedSplit: number) => void;
}) {
  const [choice, setChoice] = useState("");
  const batch = useBatchAttribute();
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <select aria-label="Reassign sales to" value={choice} onChange={(e) => setChoice(e.target.value)} className={SELECT}>
        <ReassignOptions employees={employees} />
      </select>
      <button type="button" className={LINK} disabled={!choice || batch.isPending}
        onClick={() => batch.mutate({ employeeId: attributeTo(choice), clockEventId }, { onSuccess: (r) => onDone(r.skipped_split) })}>
        Save
      </button>
      <button type="button" className={LINK} onClick={() => onDone(0)} disabled={batch.isPending}>Cancel</button>
      {batch.isError && <span className="text-xs text-err">{batch.error.message}</span>}
    </div>
  );
}
