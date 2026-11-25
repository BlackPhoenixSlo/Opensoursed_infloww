"use client";


import { useState } from "react";

import { useSettingsBlob } from "@/lib/settingsBlob";
import { GateNoteText } from "@/components/settings/StickySaveBar";
import { IfButton, IfModal, IfSwitch } from "@/components/ui/infloww";
import { IfDateInput } from "@/components/ui/ifDateInput";
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
  // Whole-blob replace: the PUT is the stored blob plus this one key, never the Sales Panel's defaults.
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
              <IfDateInput type="time" aria-label={`Period ${i + 1} start`} className={TIME} value={p.start}
                onChange={(e) => setPeriods(periods.map((q, j) => (j === i ? { ...q, start: e.target.value } : q)))} />
              <span className="text-muted">-</span>
              <IfDateInput type="time" aria-label={`Period ${i + 1} end`} className={TIME} value={p.end}
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
