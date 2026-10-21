"use client";

/**
 * The header gear's "Shift Settings" on the Shift schedule (Inventory §3.8;
 * docs/spec/phase-02-shifts-time-tracking.md, App): one switch, "Allow
 * multiple employees to work on the same shift for the assigned Creator".
 *
 * It stores nothing of its own. The value is the `sales` Settings blob's
 * `multi_employee_shift`, the same key the Sales Panel shows as "Multiple
 * employees per shift", read and written through `useSettingsBlob("sales")`.
 * "OK" sends the whole stored blob back with only that key changed (ADR-0007
 * whole-blob replace), behind the blob's Load gate. While it is not on, the
 * Relay refuses a Shift that double-staffs a Creator (service/shifts_api.py).
 *
 * ASSUMPTION: the hook's defaults are empty, so the PUT is the stored blob
 * plus this one key, never the Sales Panel's defaults for keys nobody saved.
 * Rung 5: the spec's "changing only `multi_employee_shift`". Overturned if
 * Phase 4's blob validation wants every Sales key present.
 *
 * ASSUMPTION: the box is ticked only for a stored literal `true`, the value
 * the Relay counts. Rung 5. Overturned if odd stored values should read as on.
 *
 * The label and the gear entry point are Inventory §3.8 (rung 1,
 * docs/infloww-screens.md:458). This is the antd modal look (`IfModal`, 520)
 * with one `IfSwitch` row (page-parity ticket 18). A toggle stages the change
 * and "OK" saves it, as the Sales Panel saves through its save bar rather than
 * on toggle.
 *
 * "Common periods" (Infloww's preset shift periods, roadmap W6 6.12) are the
 * `shifts` blob's `presets`, `[{start, end}]` "HH:MM", which the Shifts window
 * offers per row. Not `time-tracking`: its saves are payroll versions, and a
 * period credits nothing. "OK" saves that blob too, only when a period
 * changed, so its Load gate never blocks the switch alone.
 */

import { useState } from "react";

import { useSettingsBlob } from "@/lib/settingsBlob";
import { GateNoteText } from "@/components/settings/StickySaveBar";
import { IfButton, IfModal, IfSwitch } from "@/components/ui/infloww";
import type { CommonPeriod } from "@/lib/shifts";

const TIME = "h-8 rounded-md border border-border bg-bg px-2 text-[14px] text-fg tabular-nums";

const ALLOW = "Allow multiple employees to work on the same shift for the assigned Creator";

export default function ShiftSettingsDialog({ onClose }: { onClose: () => void }) {
  const blob = useSettingsBlob<{ multi_employee_shift?: unknown }>("sales", {});
  const allowed = blob.value.multi_employee_shift === true;
  const presets = useSettingsBlob<{ presets?: unknown }>("shifts", {});
  const stored = presets.value.presets;
  const periods = Array.isArray(stored) ? (stored as CommonPeriod[]) : [];
  const [periodsEdited, setPeriodsEdited] = useState(false);
  const setPeriods = (next: CommonPeriod[]) => {
    presets.set({ presets: next });
    setPeriodsEdited(true);
  };
  const save = () => blob.commit({}, () => (periodsEdited ? presets.commit({}, onClose) : onClose()));
  const saving = blob.save.saving || presets.save.saving;

  return (
    <IfModal
      title="Shift Settings"
      width={520}
      onClose={onClose}
      footer={(
        <>
          <IfButton onClick={onClose}>Cancel</IfButton>
          <IfButton variant="primary" disabled={!blob.save.canSave || (periodsEdited && !presets.save.canSave) || saving}
            onClick={save}>
            OK
          </IfButton>
        </>
      )}
    >
      <div className="space-y-4">
        <IfSwitch checked={allowed} aria-label={ALLOW} label={ALLOW}
          onChange={(on) => blob.set({ multi_employee_shift: on })} />
        <p className="text-[12px] text-muted">
          The same setting as &quot;Multiple employees per shift&quot; in Settings › Sales.
        </p>
        <fieldset aria-label="Common periods" className="space-y-2">
          <legend className="pb-1 text-[14px] text-fg">Common periods</legend>
          {periods.map((p, i) => (
            <div key={i} className="flex items-center gap-2">
              <input type="time" aria-label={`Period ${i + 1} start`} className={TIME} value={p.start}
                onChange={(e) => setPeriods(periods.map((q, j) => (j === i ? { ...q, start: e.target.value } : q)))} />
              <span className="text-muted">-</span>
              <input type="time" aria-label={`Period ${i + 1} end`} className={TIME} value={p.end}
                onChange={(e) => setPeriods(periods.map((q, j) => (j === i ? { ...q, end: e.target.value } : q)))} />
              <IfButton variant="link" onClick={() => setPeriods(periods.filter((_, j) => j !== i))}>Remove</IfButton>
            </div>
          ))}
          <IfButton onClick={() => setPeriods([...periods, { start: "09:00", end: "17:00" }])}>+ Add period</IfButton>
          <p className="text-[12px] text-muted">Offered in the Shifts window; an end before the start ends the next day.</p>
        </fieldset>
        {blob.save.gateNote && <p><GateNoteText note={blob.save.gateNote} /></p>}
        {periodsEdited && presets.save.gateNote && <p><GateNoteText note={presets.save.gateNote} /></p>}
        {blob.save.error && <p className="text-err">{`Couldn't save: ${blob.save.error}`}</p>}
        {presets.save.error && <p className="text-err">{`Couldn't save the common periods: ${presets.save.error}`}</p>}
      </div>
    </IfModal>
  );
}
