"use client";


import { useId, useMemo, useState, useEffect } from "react";
import { Clock } from "lucide-react";

import { IfButton, IfHelp, IfLabel } from "@/components/ui/infloww";
import { IF_FIELD } from "@/components/ui/ifSelect";
import { IfDateInput } from "@/components/ui/ifDateInput";
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
  const [history, setHistory] = useState<HistoryEntry[]>(() => loadHistory(scope));
  // A same-tab storage event is not guaranteed after the parent's recordSchedule, so re-read on mount and scope change.
  useEffect(() => { setHistory(loadHistory(scope)); }, [scope]);

  const prediction = useMemo(() => predictNext(history), [history]);

  const id = useId();
  return (
    <div>
      <IfLabel htmlFor={id}>{label}</IfLabel>
      <div className="flex items-center gap-3">
        <IfDateInput
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
