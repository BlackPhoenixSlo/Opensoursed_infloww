"use client";


import { useQueryClient } from "@tanstack/react-query";
import { useReducer, useState } from "react";

import { useActionAllowed } from "@/components/shell/useGrantedPages";
import { IfButton, IfLabel, IfModal } from "@/components/ui/infloww";
import { IF_DATE_FIELD, IfDateInput } from "@/components/ui/ifDateInput";
import { cn } from "@/lib/utils";
import { initialRecordForm, recordFormReducer, validateRecord } from "@/components/stats/recordEditor";
import { useAgencyTimeZone } from "@/lib/appliedSettings";
import { rangeOffsetLabel } from "@/lib/creatorClock";
import { downloadCsv } from "@/lib/csv";
import { RelayError } from "@/lib/relay";
import {
  MONTHS, calcMinutes, editClockEvent, fromZonedInput, pad, toZonedInput, useClockRecords, zonedParts,
  type ClockRecord,
} from "@/lib/shifts";

const LABEL = "mb-0 flex flex-col gap-2";
const HOUR_MS = 3_600_000;

export function clockStamp(iso: string, tz: string): string {
  const w = zonedParts(Date.parse(iso), tz);
  return `${MONTHS[w.mo - 1]} ${w.d}, ${w.y} ${w.h % 12 || 12}:${pad(w.mi)}:${pad(w.s)} ${w.h < 12 ? "AM" : "PM"}`;
}

function csvStamp(iso: string, tz: string): string {
  const w = zonedParts(Date.parse(iso), tz);
  return `${w.y}-${pad(w.mo)}-${pad(w.d)} ${pad(w.h)}:${pad(w.mi)}:${pad(w.s)}`;
}

const toHour = (value: string) => value.slice(0, 13) + ":00";

export default function ClockRecordsModal({ employeeId, employeeName, groupName, from, to, onClose }: {
  employeeId: number;
  employeeName: string;
  groupName: string;
  from: string;
  to: string;
  onClose: () => void;
}) {
  const tz = useAgencyTimeZone();
  const exportAllowed = useActionAllowed("export");
  const [fromInput, setFromInput] = useState<string | null>(null);
  const [toInput, setToInput] = useState<string | null>(null);
  const fromValue = fromInput ?? toHour(toZonedInput(from, tz));
  const toValue = toInput ?? toHour(toZonedInput(to, tz));
  const fromIso = fromInput === null ? from : fromZonedInput(fromValue, tz);
  const toStart = toInput === null ? null : fromZonedInput(toValue, tz);
  // toIso is exclusive: the picked end hour is inclusive, so the query sends the hour after it.
  const toIso = toInput === null ? to : toStart && new Date(new Date(toStart).getTime() + HOUR_MS).toISOString();
  const ranged = !!fromIso && !!toIso && new Date(fromIso) < new Date(toIso);
  const fromDate = new Date(fromIso ?? 0);
  const toDate = new Date(toIso ?? 0);
  const now = Date.now();
  const [labelFrom, labelTo] = ranged ? [fromDate.getTime(), toDate.getTime() - 1] : [now, now];
  const zoneLabel = rangeOffsetLabel(tz, labelFrom, labelTo);
  const records = useClockRecords(employeeId, fromDate, toDate, ranged);
  const list = records.data?.clock_events ?? [];
  const maxValue = `${toZonedInput(new Date().toISOString(), tz).slice(0, 10)}T23:00`;

  const exportCsv = () => {
    const name = employeeName.trim().replace(/[\s/\\]+/g, "_");
    downloadCsv(`Clocked_Hours_${name}_${fromValue.slice(0, 10)}_to_${toValue.slice(0, 10)}.csv`, [
      ["Group", "Employee", "Clocked hours", `Clock in date/time (${tz})`, `Clock out date/time (${tz})`],
      ...list.map((r) => [
        groupName, employeeName, r.minutes == null ? "-" : (r.minutes / 60).toFixed(2),
        csvStamp(r.in_utc, tz), r.out_utc ? csvStamp(r.out_utc, tz) : "-",
      ]),
    ]);
  };

  let body;
  if (!ranged) {
    body = <p className="text-sm text-fg-dim">Choose a range that ends after it starts.</p>;
  } else if (records.isPending) {
    body = <p className="text-sm text-fg-dim">Loading clock records…</p>;
  } else if (records.isError) {
    body = (
      <div className="flex items-center justify-between gap-3">
        <p className="text-sm text-err">{`Couldn't load clock records: ${records.error.message}`}</p>
        <IfButton onClick={() => void records.refetch()}>Retry</IfButton>
      </div>
    );
  } else if (list.length === 0) {
    body = <p className="text-sm text-fg-dim text-center py-6">No data</p>;
  } else {
    body = (
      <ol className="space-y-3 max-h-[50vh] overflow-y-auto pr-1">
        {list.map((r) => <RecordItem key={r.clock_event_id} record={r} tz={tz} />)}
      </ol>
    );
  }

  return (
    <IfModal
      title="Clocked hours"
      width={486}
      closable={false}
      keyboard
      onClose={onClose}
      footer={(
        <>
          <p className="mr-auto text-[12px] text-muted">{"Edit is ours: Infloww can't edit clock records."}</p>
          <IfButton onClick={onClose}>Close</IfButton>
        </>
      )}
    >
      <div className="space-y-4">
        <p className="mb-2 text-[12px] text-muted">{employeeName}</p>
        <div className="flex flex-wrap items-end gap-2">
          <IfLabel className={LABEL}>
            From
            <IfDateInput type="datetime-local" step={3600} max={maxValue} aria-label="From" className={cn(IF_DATE_FIELD, "tabular-nums")}
              value={fromValue} onChange={(e) => e.target.value && setFromInput(toHour(e.target.value))} />
          </IfLabel>
          <IfLabel className={LABEL}>
            To
            <IfDateInput type="datetime-local" step={3600} max={maxValue} aria-label="To" className={cn(IF_DATE_FIELD, "tabular-nums")}
              value={toValue} onChange={(e) => e.target.value && setToInput(toHour(e.target.value))} />
          </IfLabel>
          {exportAllowed && (
            <IfButton className="ml-auto" onClick={exportCsv}
              disabled={!ranged || !records.isSuccess || list.length === 0}>
              Export
            </IfButton>
          )}
        </div>
        <p className="text-[12px] text-muted">{`Times in ${zoneLabel}`}</p>
        {body}
      </div>
    </IfModal>
  );
}

function RecordItem({ record: r, tz }: { record: ClockRecord; tz: string }) {
  const [editing, setEditing] = useState<"edit" | "close" | null>(null);
  const tags = (
    <>
      {r.close_reason === "auto" && <span className="text-fg-dim"> (auto clock out)</span>}
      {r.edited && <span className="text-fg-dim"> (edited)</span>}
    </>
  );
  return (
    <li className="border-l-2 border-border pl-3 text-sm space-y-0.5">
      {r.out_utc && (
        <p>
          {`Clock out at ${clockStamp(r.out_utc, tz)} (${calcMinutes(r.minutes ?? 0)})`}
          {tags}
        </p>
      )}
      <p>
        {`Clock in at ${clockStamp(r.in_utc, tz)}`}
        {!r.out_utc && tags}
      </p>
      {editing ? (
        <RecordEditor record={r} tz={tz} closing={editing === "close"} onDone={() => setEditing(null)} />
      ) : (
        <div className="flex gap-3 pt-0.5">
          <IfButton variant="link" className="h-auto" onClick={() => setEditing("edit")}>Edit</IfButton>
          {!r.out_utc && (
            <IfButton variant="link" className="h-auto" onClick={() => setEditing("close")}>Clock out now…</IfButton>
          )}
        </div>
      )}
    </li>
  );
}

export function RecordEditor({ record: r, tz, closing, onDone }: {
  record: ClockRecord; tz: string; closing: boolean; onDone: () => void;
}) {
  const queryClient = useQueryClient();
  const [form, dispatch] = useReducer(recordFormReducer, null, () => initialRecordForm(r, tz, closing));

  const save = async () => {
    const check = validateRecord(r, form, tz, closing);
    switch (check.kind) {
      case "unchanged": return onDone();
      case "error": return dispatch({ type: "error", error: check.error });
    }
    dispatch({ type: "saving" });
    try {
      await editClockEvent(r.clock_event_id, check.body);
      await queryClient.invalidateQueries({ queryKey: ["shifts"] });
      onDone();
    } catch (e) {
      dispatch({
        type: "error",
        error: e instanceof RelayError || e instanceof Error ? e.message : "Couldn't save the record.",
      });
    }
  };

  return (
    <div className="space-y-2 pt-1">
      <div className="flex flex-wrap gap-2">
        {!closing && (
          <IfLabel className={LABEL}>
            Clock in
            <IfDateInput type="datetime-local" aria-label="Clock in" className={cn(IF_DATE_FIELD, "tabular-nums")}
              value={form.inV} onChange={(e) => dispatch({ type: "in", value: e.target.value })} />
          </IfLabel>
        )}
        {(closing || r.out_utc) && (
          <IfLabel className={LABEL}>
            Clock out
            <IfDateInput type="datetime-local" aria-label="Clock out" className={cn(IF_DATE_FIELD, "tabular-nums")}
              value={form.outV} onChange={(e) => dispatch({ type: "out", value: e.target.value })} />
          </IfLabel>
        )}
      </div>
      {form.error && <p className="text-[12px] text-err" role="alert">{form.error}</p>}
      <div className="flex gap-2">
        <IfButton onClick={onDone} disabled={form.busy}>Cancel</IfButton>
        <IfButton variant="primary" onClick={() => void save()} disabled={form.busy}>
          {form.busy ? "Saving…" : closing ? "Clock out" : "Save"}
        </IfButton>
      </div>
    </div>
  );
}
