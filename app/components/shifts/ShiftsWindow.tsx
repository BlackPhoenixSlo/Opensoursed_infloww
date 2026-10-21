"use client";

/**
 * The Shifts window (docs/spec/phase-02-shifts-time-tracking.md, App;
 * Inventory §3.8), in Infloww's antd modal look at 700px (page-parity ticket
 * 18): "Create shift(s)" opens it with one row (a click on an empty day cell
 * seeds that row with the cell's Creator and 09:00-17:00 that day), "+ Add
 * Shift" adds more, and "OK" sends one `POST /admin/shifts` per row. Rows the
 * server saves leave the window; a refused row stays with the server's
 * reason under it; a 409 from the overlap rule is spelled out clash by
 * clash, each with its Creator and its start in the Agency's time. A 422
 * for an Employee whose login lacks a Creator asks "Grant <Employee> access
 * to <Creator>?" and, confirmed, resends the row with `grant_access` so the
 * Relay grants the access with the Shift. Opened
 * from a Shift in the calendar, it holds that one occurrence as "Edit
 * shift", its row at the occurrence's times: "OK" saves it (`PATCH`), and
 * "Delete" cancels it after a confirmation (a soft cancel: the Shift stays in
 * the history). An occurrence of a weekly series first asks Infloww's scope
 * (ShiftScopeDialog, roadmap W6 6.3): an edit "Only this shift" or "This and
 * all future shifts", a delete "This shift", "This shift and following" or
 * "All shifts".
 *
 * Roadmap W6 6.12: a row's "Common period" picks one of the Agency's saved
 * periods (Shift Settings, the `shifts` blob's `presets`) and sets Start and
 * End to it on the row's day (today when unset; an end before the start
 * ends the next day). When a 409 clashes only with other Shifts, the row
 * offers "Replace the clashing shifts": ticked, OK sends `replace: true`, and
 * the Relay takes the clashing occurrences out of those Shifts.
 *
 * A row is in one timezone, its `tz`, shown in the row: Start, End, the
 * repeat weekdays and "Repeat until" are all wall clock there, and Start and
 * End are sent as UTC. A new row's `tz` is the Agency's (`defaultTz`); an
 * edited Shift keeps its own, and its repeats follow that zone's wall clock
 * on the Relay.
 *
 * ASSUMPTION: the row shows its timezone but offers no picker; a new Shift
 * always takes the Agency's. Rung 5: the spec asks only for the default and
 * the display. Overturned by Inventory evidence of a timezone picker.
 *
 * ASSUMPTION: a one-off Shift's delete confirms with the browser's
 * `window.confirm`. Rung 3: components/settings/TemplatesTab.tsx (useSavedReplyEditor) confirms
 * deletes the same way. Overturned by a house confirm dialog.
 */

import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { IfButton, IfModal } from "@/components/ui/infloww";
import { useSettingsBlob } from "@/lib/settingsBlob";
import ShiftScopeDialog, { isRecurring, useShiftDelete } from "@/components/shifts/ShiftScopeDialog";
import {
  WEEKDAYS, createShift, editShift, fromZonedInput, occurrenceLabel, shiftClashes, shiftGrantable, toZonedInput,
  type CommonPeriod, type ShiftGrantable, type ShiftInput, type ShiftOccurrence, type ShiftScopeAt,
} from "@/lib/shifts";

/** The antd field box (`IF_FIELD` in ui/infloww.tsx) on a native input. */
const FIELD =
  "h-8 rounded-md border border-border bg-bg px-[11px] text-[14px] text-fg outline-none hover:border-accent focus:border-accent";
const LABEL = "flex flex-col gap-1 text-[14px] text-fg";

/** A Creator and a day (YYYY-MM-DD in `defaultTz`) to seed the first row with: an empty day cell's click. */
export interface ShiftPreset { accountId: string; date: string }

export interface Choice<Id> { id: Id; label: string }

interface Row {
  key: number;
  start: string;
  end: string;
  tz: string;
  employeeIds: number[];
  accountIds: string[];
  repeat: boolean;
  repeatDays: number[];
  repeatEnds: "never" | "date";
  repeatUntil: string;
  error: string | null;
  /** The last refusal clashed with other Shifts only, so "Replace the clashing shifts" is offered. */
  replaceable: boolean;
  replace: boolean;
}

let nextKey = 1;

function blankRow(tz: string, preset?: ShiftPreset): Row {
  return {
    key: nextKey++,
    start: preset ? `${preset.date}T09:00` : "",
    end: preset ? `${preset.date}T17:00` : "",
    tz, employeeIds: [], accountIds: preset ? [preset.accountId] : [],
    repeat: false, repeatDays: [], repeatEnds: "never", repeatUntil: "", error: null, replaceable: false,
    replace: false,
  };
}

/** The occurrence opened, at its own times. */
function rowOf(o: ShiftOccurrence): Row {
  return {
    key: nextKey++,
    start: toZonedInput(o.occurrence_start, o.tz),
    end: toZonedInput(o.occurrence_end, o.tz),
    tz: o.tz,
    employeeIds: o.employees.map((e) => e.id),
    accountIds: o.accounts.map((a) => a.id),
    repeat: !!o.repeat_days,
    repeatDays: o.repeat_days ?? [],
    repeatEnds: o.repeat_until ? "date" : "never",
    repeatUntil: o.repeat_until ?? "",
    error: null,
    replaceable: false,
    replace: false,
  };
}

/** The row as the Relay's body, or the reason it cannot be sent yet. */
function toInput(row: Row): ShiftInput | string {
  const start = fromZonedInput(row.start, row.tz);
  const end = fromZonedInput(row.end, row.tz);
  if (!start || !end) return "Set a start and an end.";
  if (row.repeat && row.repeatDays.length === 0) return "Pick at least one weekday to repeat on.";
  if (row.repeat && row.repeatEnds === "date" && !row.repeatUntil) return "Set the date the repeat ends.";
  return {
    start_utc: start,
    end_utc: end,
    tz: row.tz,
    repeat_days: row.repeat ? [...row.repeatDays].sort((a, b) => a - b) : null,
    repeat_until: row.repeat && row.repeatEnds === "date" ? row.repeatUntil : null,
    employee_ids: row.employeeIds,
    account_ids: row.accountIds,
    ...(row.replace ? { replace: true } : {}),
  };
}

/** `row` with Start and End set to `period` on its day (today in its zone when unset). */
function withPeriod(row: Row, period: CommonPeriod): Partial<Row> {
  const day = (row.start || toZonedInput(new Date().toISOString(), row.tz)).slice(0, 10);
  const next = new Date(Date.parse(`${day}T00:00:00Z`) + 86_400_000).toISOString().slice(0, 10);
  return { start: `${day}T${period.start}`, end: `${period.end <= period.start ? next : day}T${period.end}` };
}

const periodLabel = (p: CommonPeriod) => `${p.start} - ${p.end}`;

/** A refused write's reason. A 409 carrying the overlap rule's `clashes` is
 *  spelled out one clash at a time; anything else is the Relay's `detail`.
 *  ASSUMPTION: a clash names the Creator and the other Shift's start, not
 *  its id or Employees, which the window does not hold. Rung 5. Overturned
 *  if owners need the other Shift's Employees named. */
function errorText(e: unknown, creatorName: (id: string) => string, tz: string): string {
  const clashes = shiftClashes(e);
  if (clashes) {
    const named = clashes.map((c) => `${creatorName(c.account_id)}: ${
      c.shift_id === null ? "more than one Employee on this Shift" : `another Shift on ${occurrenceLabel(c.occurrence_start, tz)}`
    }`);
    return `Not saved: "Multiple employees per shift" is off (Shift Settings). ${named.join("; ")}.`;
  }
  return e instanceof Error ? e.message : String(e);
}

function toggle<T>(list: T[], value: T): T[] {
  return list.includes(value) ? list.filter((v) => v !== value) : [...list, value];
}

export default function ShiftsWindow({
  editing, preset, defaultTz, employees, creators, onClose,
}: {
  /** The Shift opened from the calendar, or null for "Create shift(s)". */
  editing: ShiftOccurrence | null;
  preset?: ShiftPreset;
  /** A new row's time zone: the Agency's. */
  defaultTz: string;
  employees: Choice<number>[];
  creators: Choice<string>[];
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const [rows, setRows] = useState<Row[]>(() => [editing ? rowOf(editing) : blankRow(defaultTz, preset)]);
  const [busy, setBusy] = useState(false);
  /** "Edit recurring shift" open over the window, for an occurrence of a weekly series. */
  const [askingEdit, setAskingEdit] = useState(false);

  const update = (key: number, patch: Partial<Row>) =>
    setRows((rs) => rs.map((r) => (r.key === key ? { ...r, ...patch } : r)));
  const refreshWeek = () => queryClient.invalidateQueries({ queryKey: ["shifts"] });
  const creatorName = (id: string) => creators.find((c) => c.id === id)?.label ?? id;
  const stored = useSettingsBlob<{ presets?: unknown }>("shifts", {}).value.presets;
  const periods = Array.isArray(stored) ? (stored as CommonPeriod[]) : [];

  const save = async (at?: ShiftScopeAt) => {
    if (editing && isRecurring(editing) && !at) {
      setAskingEdit(true);
      return;
    }
    setBusy(true);
    // One answer per (Employee, Creator) pair for the whole OK, however many rows need it.
    const answers = new Map<string, boolean>();
    const approve = (pairs: ShiftGrantable[]) => pairs.every((p) => {
      const key = `${p.employee_id}:${p.account_id}`;
      if (!answers.has(key)) answers.set(key, window.confirm(`Grant ${p.employee_name} access to ${p.account_name}?`));
      return answers.get(key);
    });
    const failed = (e: unknown): Partial<Row> => {
      const clashes = shiftClashes(e);
      return { error: errorText(e, creatorName, defaultTz), replace: false,
        replaceable: !!clashes && clashes.every((c) => c.shift_id !== null) };
    };
    const results = await Promise.all(rows.map(async (row): Promise<Partial<Row> | null> => {
      const input = toInput(row);
      if (typeof input === "string") return { error: input, replaceable: false, replace: false };
      const send = (body: ShiftInput) => (editing ? editShift(editing.shift_id, body, at) : createShift(body));
      try {
        await send(input);
        return null;
      } catch (e) {
        // An Employee whose login lacks a Creator: ask, then resend granting the access with the Shift. The
        // Relay asks before it checks clashes, so the resend may still come back 409 (and offer Replace).
        const grantable = shiftGrantable(e);
        if (!grantable || !approve(grantable)) return failed(e);
        try {
          await send({ ...input, grant_access: true });
          return null;
        } catch (e2) {
          return failed(e2);
        }
      }
    }));
    setBusy(false);
    const left = rows.flatMap((row, i) => (results[i] === null ? [] : [{ ...row, ...results[i] }]));
    if (left.length < rows.length) void refreshWeek();
    if (left.length === 0) onClose();
    else setRows(left);
  };

  const del = useShiftDelete({
    onDone: () => {
      void refreshWeek();
      onClose();
    },
    onError: (e) => setRows((rs) => rs.map((r) => ({ ...r, error: errorText(e, creatorName, defaultTz) }))),
  });

  return (
    <IfModal
      title={editing ? "Edit shift" : "Create shift(s)"}
      width={700}
      onClose={onClose}
      footer={(
        <>
          {editing ? (
            <IfButton variant="link" className="mr-auto text-err hover:text-err/80" disabled={busy || del.busy}
              onClick={() => del.request(editing)}>
              Delete
            </IfButton>
          ) : (
            <IfButton className="mr-auto" onClick={() => setRows((rs) => [...rs, blankRow(defaultTz)])}>
              + Add Shift
            </IfButton>
          )}
          <IfButton onClick={onClose}>Cancel</IfButton>
          <IfButton variant="primary" disabled={busy || del.busy} onClick={() => void save()}>OK</IfButton>
        </>
      )}
    >
      <div className="space-y-4">
        {rows.map((row, i) => (
          <fieldset key={row.key} aria-label={`Shift ${i + 1}`}
            className="space-y-3 rounded-md border border-border p-4">
            <div className="flex flex-wrap items-end gap-3">
              <label className={LABEL}>
                Start
                <input type="datetime-local" className={FIELD} value={row.start}
                  onChange={(e) => update(row.key, { start: e.target.value })} />
              </label>
              <label className={LABEL}>
                End
                <input type="datetime-local" className={FIELD} value={row.end}
                  onChange={(e) => update(row.key, { end: e.target.value })} />
              </label>
              {periods.length > 0 && (
                <label className={LABEL}>
                  Common period
                  <select className={FIELD} value="" aria-label="Common period"
                    onChange={(e) => e.target.value && update(row.key, withPeriod(row, periods[Number(e.target.value)]))}>
                    <option value="">Choose…</option>
                    {periods.map((p, n) => <option key={n} value={String(n)}>{periodLabel(p)}</option>)}
                  </select>
                </label>
              )}
              <p className="pb-1.5 text-muted">Time zone: <span className="text-accent">{row.tz}</span></p>
              {!editing && rows.length > 1 && (
                <IfButton variant="link" className="ml-auto"
                  onClick={() => setRows((rs) => rs.filter((r) => r.key !== row.key))}>
                  Remove
                </IfButton>
              )}
            </div>

            <div className="grid gap-3 sm:grid-cols-2">
              <fieldset aria-label="Creators" className="space-y-1">
                <legend className="pb-1 text-muted">Creators</legend>
                {creators.map((c) => (
                  <label key={c.id} className="flex items-center gap-2">
                    <input type="checkbox" className="accent-accent" checked={row.accountIds.includes(c.id)}
                      onChange={() => update(row.key, { accountIds: toggle(row.accountIds, c.id) })} />
                    {c.label}
                  </label>
                ))}
              </fieldset>
              <fieldset aria-label="Employees" className="space-y-1">
                <legend className="pb-1 text-muted">Employees</legend>
                {employees.map((e) => (
                  <label key={e.id} className="flex items-center gap-2">
                    <input type="checkbox" className="accent-accent" checked={row.employeeIds.includes(e.id)}
                      onChange={() => update(row.key, { employeeIds: toggle(row.employeeIds, e.id) })} />
                    {e.label}
                  </label>
                ))}
              </fieldset>
            </div>

            <div className="space-y-2">
              <label className="flex items-center gap-2">
                <input type="checkbox" className="accent-accent" checked={row.repeat}
                  onChange={(e) => update(row.key, { repeat: e.target.checked })} />
                Repeat weekly
              </label>
              {row.repeat && (
                <div className="flex flex-wrap items-center gap-3">
                  <fieldset aria-label="Repeat on" className="flex flex-wrap gap-2">
                    {WEEKDAYS.map((label, d) => (
                      <label key={label} className="flex items-center gap-1">
                        <input type="checkbox" className="accent-accent" checked={row.repeatDays.includes(d + 1)}
                          onChange={() => update(row.key, { repeatDays: toggle(row.repeatDays, d + 1) })} />
                        {label}
                      </label>
                    ))}
                  </fieldset>
                  <label className="flex items-center gap-2">
                    Repeat Ends
                    <select className={FIELD} value={row.repeatEnds}
                      onChange={(e) => update(row.key, { repeatEnds: e.target.value as Row["repeatEnds"] })}>
                      <option value="never">Never</option>
                      <option value="date">On date</option>
                    </select>
                  </label>
                  {row.repeatEnds === "date" && (
                    <label className="flex items-center gap-2">
                      Repeat until
                      <input type="date" className={FIELD} value={row.repeatUntil}
                        onChange={(e) => update(row.key, { repeatUntil: e.target.value })} />
                    </label>
                  )}
                </div>
              )}
            </div>

            {row.error && <p className="text-err">{row.error}</p>}
            {row.replaceable && (
              <label className="flex items-center gap-2 text-[14px]">
                <input type="checkbox" className="accent-accent" checked={row.replace}
                  onChange={(e) => update(row.key, { replace: e.target.checked })} />
                Replace the clashing shifts (their clashing occurrences are removed when you press OK)
              </label>
            )}
          </fieldset>
        ))}
      </div>
      {editing && askingEdit && (
        <ShiftScopeDialog action="edit" occurrence={editing} onClose={() => setAskingEdit(false)}
          onPick={(at) => {
            setAskingEdit(false);
            void save(at);
          }} />
      )}
      {del.dialog}
    </IfModal>
  );
}
