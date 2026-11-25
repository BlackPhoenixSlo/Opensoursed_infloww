"use client";


import { useState, type ReactNode } from "react";

import { IfButton, IfModal } from "@/components/ui/infloww";
import { cancelShift, type ShiftOccurrence, type ShiftScope, type ShiftScopeAt } from "@/lib/shifts";
import { ifConfirm } from "@/components/ui/ifConfirm";

export const CANCEL_CONFIRM = "Cancel this Shift? It leaves the calendar and stays in the history.";

export type ScopeAction = "edit" | "delete";

const CHOICES: Record<ScopeAction, { title: string; options: { scope: ShiftScope; label: string }[]; past: string }> = {
  edit: {
    title: "Edit recurring shift",
    options: [{ scope: "this", label: "Only this shift" }, { scope: "following", label: "This and all future shifts" }],
    past: "Past shifts will also be modified",
  },
  delete: {
    title: "Delete recurring shift",
    options: [
      { scope: "this", label: "This shift" },
      { scope: "following", label: "This shift and following" },
      { scope: "all", label: "All shifts" },
    ],
    past: "All records of past shifts will be permanently deleted",
  },
};

export const isRecurring = (o: ShiftOccurrence) => !!o.repeat_days?.length;

export default function ShiftScopeDialog({ action, occurrence, onPick, onClose }: {
  action: ScopeAction;
  occurrence: ShiftOccurrence;
  onPick: (at: ShiftScopeAt) => void;
  onClose: () => void;
}) {
  const { title, options, past } = CHOICES[action];
  const [scope, setScope] = useState<ShiftScope>("this");
  const from = scope === "all" ? occurrence.start_utc : occurrence.occurrence_start;
  const reachesPast = new Date(from).getTime() < Date.now();

  return (
    <IfModal
      title={title}
      width={420}
      onClose={onClose}
      footer={(
        <>
          <IfButton onClick={onClose}>Cancel</IfButton>
          <IfButton variant="primary" onClick={() => onPick({ scope, occurrence_start: occurrence.occurrence_start })}>
            OK
          </IfButton>
        </>
      )}
    >
      <div role="radiogroup" aria-label={title} className="flex flex-col gap-3">
        {options.map((o) => (
          <label key={o.scope} className="inline-flex cursor-pointer items-center gap-2">
            <input type="radio" name="shift-scope" className="h-4 w-4 cursor-pointer accent-[var(--if-accent)]"
              checked={scope === o.scope} onChange={() => setScope(o.scope)} />
            {o.label}
          </label>
        ))}
      </div>
      {reachesPast && <p role="alert" className="mt-4 text-[13px] text-warn">{past}</p>}
    </IfModal>
  );
}

export function useShiftDelete({ onDone, onError }: {
  onDone: () => void;
  onError: (e: unknown, o: ShiftOccurrence) => void;
}): {
  request: (o: ShiftOccurrence) => void;
  dialog: ReactNode;
  busy: boolean;
} {
  const [asking, setAsking] = useState<ShiftOccurrence | null>(null);
  const [busy, setBusy] = useState(false);
  const send = async (o: ShiftOccurrence, at?: ShiftScopeAt) => {
    setBusy(true);
    try {
      await cancelShift(o.shift_id, at);
      onDone();
    } catch (e) {
      onError(e, o);
    } finally {
      setBusy(false);
    }
  };
  return {
    request: async (o) => {
      if (isRecurring(o)) setAsking(o);
      else if (await ifConfirm(CANCEL_CONFIRM, { danger: true })) void send(o);
    },
    dialog: asking && (
      <ShiftScopeDialog action="delete" occurrence={asking} onClose={() => setAsking(null)}
        onPick={(at) => {
          setAsking(null);
          void send(asking, at);
        }} />
    ),
    busy,
  };
}
