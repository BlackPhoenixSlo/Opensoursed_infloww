"use client";


import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { IfButton, IfModal } from "@/components/ui/infloww";
import { useSettingsBlob } from "@/lib/settingsBlob";
import ShiftScopeDialog, { isRecurring, useShiftDelete } from "@/components/shifts/ShiftScopeDialog";
import {
  WEEKDAYS, createShift, editShift, fromZonedInput, occurrenceLabel, shiftClashes, shiftGrantable, toZonedInput,
  type CommonPeriod, type ShiftGrantable, type ShiftInput, type ShiftOccurrence, type ShiftScopeAt,
} from "@/lib/shifts";
import { errText } from "@/lib/errText";
import { ifConfirm } from "@/components/ui/ifConfirm";
import { IfDateInput } from "@/components/ui/ifDateInput";

const FIELD =
  "h-8 rounded-md border border-border bg-bg px-[11px] text-[14px] text-fg outline-none hover:border-accent focus:border-accent";
const LABEL = "flex flex-col gap-1 text-[14px] text-fg";

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

function withPeriod(row: Row, period: CommonPeriod): Partial<Row> {
  const day = (row.start || toZonedInput(new Date().toISOString(), row.tz)).slice(0, 10);
  const next = new Date(Date.parse(`${day}T00:00:00Z`) + 86_400_000).toISOString().slice(0, 10);
  return { start: `${day}T${period.start}`, end: `${period.end <= period.start ? next : day}T${period.end}` };
}

const periodLabel = (p: CommonPeriod) => `${p.start} - ${p.end}`;

function errorText(e: unknown, creatorName: (id: string) => string, tz: string): string {
  const clashes = shiftClashes(e);
  if (clashes) {
    const named = clashes.map((c) => `${creatorName(c.account_id)}: ${
      c.shift_id === null ? "more than one Employee on this Shift" : `another Shift on ${occurrenceLabel(c.occurrence_start, tz)}`
    }`);
    return `Not saved: "Multiple employees per shift" is off (Shift Settings). ${named.join("; ")}.`;
  }
  return errText(e);
}

function toggle<T>(list: T[], value: T): T[] {
  return list.includes(value) ? list.filter((v) => v !== value) : [...list, value];
}

export default function ShiftsWindow({
  editing, preset, defaultTz, employees, creators, onClose,
}: {
  editing: ShiftOccurrence | null;
  preset?: ShiftPreset;
  defaultTz: string;
  employees: Choice<number>[];
  creators: Choice<string>[];
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const [rows, setRows] = useState<Row[]>(() => [editing ? rowOf(editing) : blankRow(defaultTz, preset)]);
  const [busy, setBusy] = useState(false);
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
    // One answer per (Employee, Creator) pair for the whole OK; a row failing while it is open waits on it.
    const answers = new Map<string, Promise<boolean>>();
    const approve = async (pairs: ShiftGrantable[]) => {
      for (const p of pairs) {
        const key = `${p.employee_id}:${p.account_id}`;
        let answer = answers.get(key);
        if (!answer) {
          answer = ifConfirm(`Grant ${p.employee_name} access to ${p.account_name}?`);
          answers.set(key, answer);
        }
        if (!(await answer)) return false;
      }
      return true;
    };
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
        // The Relay asks before it checks clashes, so the resend may still come back 409.
        const grantable = shiftGrantable(e);
        if (!grantable || !(await approve(grantable))) return failed(e);
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
                <IfDateInput type="datetime-local" className={FIELD} value={row.start}
                  onChange={(e) => update(row.key, { start: e.target.value })} />
              </label>
              <label className={LABEL}>
                End
                <IfDateInput type="datetime-local" className={FIELD} value={row.end}
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
                      <IfDateInput type="date" className={FIELD} value={row.repeatUntil}
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
