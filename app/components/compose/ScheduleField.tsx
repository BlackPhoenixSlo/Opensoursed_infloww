"use client";

/**
 * ScheduleField — datetime-local input with a smart-suggestion chip.
 *
 * Behavior mirrors the desktop app's chip: once the scope (account id)
 * has ≥1 prior pick in localStorage, we show a chip that fills the
 * field with the predicted next slot ("Tue, May 25 · 9:00 PM · +1d").
 * Click to apply; Clear next to a populated field empties it.
 *
 * Empty value === "send immediately" — the parent decides what to do
 * with that. Callers should also call `recordSchedule(scope, value)`
 * after a successful submit so the cadence keeps learning.
 */

import { useId, useMemo, useState, useEffect } from "react";
import { Clock } from "lucide-react";

import { IfButton, IfHelp, IfLabel } from "@/components/ui/infloww";
import { IF_FIELD } from "@/components/ui/ifSelect";
import { cn } from "@/lib/utils";

import {
  describePrediction,
  loadHistory,
  predictNext,
  type HistoryEntry,
} from "@/lib/scheduleHistory";

export function ScheduleField({
  scope, value, onChange, label = "Schedule",
}: {
  scope: string | null;
  value: string;
  onChange: (next: string) => void;
  label?: string;
}) {
  // Local copy so chip predictions refresh when the user clicks Submit
  // and we call recordSchedule from the parent (storage write fires our
  // own re-read via the "storage" event in the same tab is not guaranteed,
  // so we re-read on mount + when the scope changes).
  const [history, setHistory] = useState<HistoryEntry[]>(() => loadHistory(scope));
  useEffect(() => { setHistory(loadHistory(scope)); }, [scope]);

  const prediction = useMemo(() => predictNext(history), [history]);

  const id = useId();
  return (
    <div>
      <IfLabel htmlFor={id}>{label}</IfLabel>
      <div className="flex items-center gap-3">
        <input
          id={id}
          type="datetime-local"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className={cn(IF_FIELD, "h-8 min-w-0 flex-1 px-[11px] outline-none focus:border-accent max-md:text-base")}
        />
        {value && (
          <IfButton variant="link" onClick={() => onChange("")} title="Clear schedule (send immediately)">
            Clear
          </IfButton>
        )}
      </div>
      <IfHelp>Optional: leave empty to send now.</IfHelp>
      {prediction && (
        <IfButton
          icon={Clock}
          onClick={() => onChange(prediction.value)}
          className="mt-2"
          title={
            prediction.fromDelta
              ? `Based on a ${prediction.intervalLabel} cadence learned from your recent picks`
              : "Suggested as next day at the same time"
          }
        >
          <span>{describePrediction(prediction.value)}</span>
          {prediction.fromDelta && (
            <span className="text-muted">+{prediction.intervalLabel}</span>
          )}
        </IfButton>
      )}
    </div>
  );
}
