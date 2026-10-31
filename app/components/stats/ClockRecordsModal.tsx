"use client";

/**
 * ClockRecordsModal — Employee reports' "Clocked hours" modal for one Employee, Infloww's `ClockInModal`
 * (bundle @13123590), opened from a row's Clocked hours in ClockedHoursCard. It lists the Employee's Clock
 * events (`GET /admin/shifts/clock-events`) over an hour-precision range that defaults to the report's, newest
 * first, as Infloww's timeline lines ("Clock out at Oct 18, 2026 5:00:00 PM (2h 5min)", then "Clock in at
 * …"; an empty range reads Infloww's "No data", live w5-a), in the Agency's time zone (`useAgencyTimeZone`). Until the user picks, the query reads the report's exact
 * range, whatever the zones; the pickers show it cut to the hour. "Export" downloads the records as CSV with
 * Infloww's file name and five columns (the house's CSV over Infloww's xlsx), the group named by the card.
 *
 * Our improvement, not Infloww's: each record has "Edit" (`PATCH /admin/shifts/clock-events/{id}`, the Owner
 * edit), and an open one "Clock out now…", which sends only `out_utc`. The Relay's 409 or 422 text shows inline.
 *
 * ASSUMPTION: the range's end hour is inclusive, so "to 23:00" reads up to midnight, as an hour picker's last
 * hour reads to Infloww's user; the query sends the hour after it. Rung 5. Overturned by Infloww's own request.
 *
 * ASSUMPTION: the export names the file `Clocked_Hours_<Employee>_<from>_to_<to>.csv` with the range's
 * days (YYYY-MM-DD) and spaces in the name as "_", gives Clocked hours as decimal hours (the card's CSV) and
 * times as "YYYY-MM-DD HH:mm:ss" in the zone the header names. Rung 3 for the name and columns (bundle), rung 5
 * for the formats. Overturned by an Infloww export file.
 */

import * as Dialog from "@radix-ui/react-dialog";
import { useQueryClient } from "@tanstack/react-query";
import { useReducer, useState } from "react";

import { useActionAllowed } from "@/components/shell/useGrantedPages";
import { initialRecordForm, recordFormReducer, validateRecord } from "@/components/stats/recordEditor";
import { useAgencyTimeZone } from "@/lib/appliedSettings";
import { zoneOffsetNow } from "@/lib/creatorClock";
import { downloadCsv } from "@/lib/csv";
import { RelayError } from "@/lib/relay";
import {
  MONTHS, calcMinutes, editClockEvent, fromZonedInput, pad, toZonedInput, useClockRecords, zonedParts,
  type ClockRecord,
} from "@/lib/shifts";

const BUTTON =
  "text-xs px-3 py-1.5 rounded-lg bg-bg-elev-1 hover:bg-bg-elev-2 border border-border disabled:opacity-50";
const PRIMARY = "text-xs px-3 py-1.5 rounded-lg bg-accent text-white hover:opacity-90 disabled:opacity-50";
const INPUT = "px-2 py-1 rounded-lg border border-border bg-bg text-xs tabular-nums";
const LINK = "text-xs text-fg-dim hover:text-fg underline";
const HOUR_MS = 3_600_000;

/** Infloww's "MMM D, YYYY h:mm:ss A" in `tz`. */
export function clockStamp(iso: string, tz: string): string {
  const w = zonedParts(Date.parse(iso), tz);
  return `${MONTHS[w.mo - 1]} ${w.d}, ${w.y} ${w.h % 12 || 12}:${pad(w.mi)}:${pad(w.s)} ${w.h < 12 ? "AM" : "PM"}`;
}

/** "YYYY-MM-DD HH:mm:ss" in `tz`, the export's cells. */
function csvStamp(iso: string, tz: string): string {
  const w = zonedParts(Date.parse(iso), tz);
  return `${w.y}-${pad(w.mo)}-${pad(w.d)} ${pad(w.h)}:${pad(w.mi)}:${pad(w.s)}`;
}

/** A `datetime-local` value cut to its hour, the range picker's precision. */
const toHour = (value: string) => value.slice(0, 13) + ":00";

/** The zone as "Europe/Paris (UTC+2)". */
const zoneLabel = (tz: string) => {
  const off = zoneOffsetNow(tz);
  return off ? `${tz} (${off.label})` : tz;
};

export default function ClockRecordsModal({ employeeId, employeeName, groupName, from, to, onClose }: {
  employeeId: number;
  employeeName: string;
  /** The Employee's group, the export's Group column ("" for none). */
  groupName: string;
  /** The report's range, the picker's default. */
  from: string;
  to: string;
  onClose: () => void;
}) {
  const tz = useAgencyTimeZone();
  const exportAllowed = useActionAllowed("export");
  // null until the user picks: the pickers show the report's range in the zone once the Applied settings load.
  const [fromInput, setFromInput] = useState<string | null>(null);
  const [toInput, setToInput] = useState<string | null>(null);
  const fromValue = fromInput ?? toHour(toZonedInput(from, tz));
  const toValue = toInput ?? toHour(toZonedInput(to, tz));
  // An end the user has not picked reads the report's exact instant, so a zone whose offset is not whole
  // hours from the report's does not move the default range.
  const fromIso = fromInput === null ? from : fromZonedInput(fromValue, tz);
  const toStart = toInput === null ? null : fromZonedInput(toValue, tz);
  const toIso = toInput === null ? to : toStart && new Date(new Date(toStart).getTime() + HOUR_MS).toISOString();
  const ranged = !!fromIso && !!toIso && new Date(fromIso) < new Date(toIso);
  const fromDate = new Date(fromIso ?? 0);
  const toDate = new Date(toIso ?? 0);
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
        <button type="button" className={BUTTON} onClick={() => void records.refetch()}>Retry</button>
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
    <Dialog.Root open onOpenChange={(open) => { if (!open) onClose(); }}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-black/50" />
        <Dialog.Content
          aria-describedby={undefined}
          className="fixed left-1/2 top-1/2 z-50 -translate-x-1/2 -translate-y-1/2 w-[486px] max-w-[calc(100vw-32px)] p-5 rounded-lg border border-border bg-bg space-y-4 outline-none"
        >
          <div>
            <Dialog.Title className="text-base font-semibold">Clocked hours</Dialog.Title>
            <p className="text-xs text-fg-dim mt-0.5">{employeeName}</p>
          </div>
          <div className="flex flex-wrap items-end gap-2">
            <label className="text-xs text-fg-dim flex flex-col gap-1">
              From
              <input type="datetime-local" step={3600} max={maxValue} aria-label="From" className={INPUT}
                value={fromValue} onChange={(e) => e.target.value && setFromInput(toHour(e.target.value))} />
            </label>
            <label className="text-xs text-fg-dim flex flex-col gap-1">
              To
              <input type="datetime-local" step={3600} max={maxValue} aria-label="To" className={INPUT}
                value={toValue} onChange={(e) => e.target.value && setToInput(toHour(e.target.value))} />
            </label>
            {exportAllowed && (
              <button type="button" className={`${BUTTON} ml-auto`} onClick={exportCsv}
                disabled={!ranged || !records.isSuccess || list.length === 0}>
                Export
              </button>
            )}
          </div>
          <p className="text-xs text-fg-dim">{`Times in ${zoneLabel(tz)}`}</p>
          {body}
          <div className="flex items-center justify-between gap-3">
            <p className="text-[11px] text-fg-dim">{"Edit is ours: Infloww can't edit clock records."}</p>
            <Dialog.Close asChild>
              <button type="button" className={BUTTON}>Close</button>
            </Dialog.Close>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

/** One record: Infloww's clock out line (when closed) over its clock in line, and our Edit. */
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
          <button type="button" className={LINK} onClick={() => setEditing("edit")}>Edit</button>
          {!r.out_utc && (
            <button type="button" className={LINK} onClick={() => setEditing("close")}>Clock out now…</button>
          )}
        </div>
      )}
    </li>
  );
}

/** The inline Owner edit: changed fields only; `closing` sends just `out_utc`, defaulting to this minute. */
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
          <label className="text-xs text-fg-dim flex flex-col gap-1">
            Clock in
            <input type="datetime-local" aria-label="Clock in" className={INPUT}
              value={form.inV} onChange={(e) => dispatch({ type: "in", value: e.target.value })} />
          </label>
        )}
        {(closing || r.out_utc) && (
          <label className="text-xs text-fg-dim flex flex-col gap-1">
            Clock out
            <input type="datetime-local" aria-label="Clock out" className={INPUT}
              value={form.outV} onChange={(e) => dispatch({ type: "out", value: e.target.value })} />
          </label>
        )}
      </div>
      {form.error && <p className="text-xs text-err" role="alert">{form.error}</p>}
      <div className="flex gap-2">
        <button type="button" className={BUTTON} onClick={onDone} disabled={form.busy}>Cancel</button>
        <button type="button" className={PRIMARY} onClick={() => void save()} disabled={form.busy}>
          {form.busy ? "Saving…" : closing ? "Clock out" : "Save"}
        </button>
      </div>
    </div>
  );
}
