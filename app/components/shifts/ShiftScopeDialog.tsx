"use client";

/**
 * Infloww's "Edit recurring shift" / "Delete recurring shift" choice (roadmap W6 6.3): an edit or a delete opened
 * from one occurrence of a weekly series asks how far it reaches. Edit: "Only this shift" or "This and all future
 * shifts"; Delete: "This shift", "This shift and following" or "All shifts". The pick is sent as `scope` with the
 * occurrence's start (lib/shifts.ts `ShiftScopeAt`). A pick that reaches a shift already started says so in
 * Infloww's words: "Past shifts will also be modified" for an edit, "All records of past shifts will be
 * permanently deleted" for a delete.
 *
 * A one-off Shift has no choice to make: its edit saves at once and its delete keeps the `window.confirm` it had.
 * `useShiftDelete` is the one delete step, from the Shifts window and from a calendar tile alike.
 */

import { useState, type ReactNode } from "react";

import { IfButton, IfModal } from "@/components/ui/infloww";
import { cancelShift, type ShiftOccurrence, type ShiftScope, type ShiftScopeAt } from "@/lib/shifts";

/** A one-off Shift's delete confirmation (a soft cancel). */
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

/** Whether `o` repeats, so an edit or a delete asks its scope. */
export const isRecurring = (o: ShiftOccurrence) => !!o.repeat_days?.length;

export default function ShiftScopeDialog({ action, occurrence, onPick, onClose }: {
  action: ScopeAction;
  occurrence: ShiftOccurrence;
  onPick: (at: ShiftScopeAt) => void;
  onClose: () => void;
}) {
  const { title, options, past } = CHOICES[action];
  const [scope, setScope] = useState<ShiftScope>("this");
  // "all" starts at the series' first occurrence; "this" and "following" at the one opened.
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

/** Delete an occurrence: a weekly series' asks its scope (render `dialog`), a one-off's confirms; then
 *  `cancelShift`, and `onDone` or `onError`. */
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
    request: (o) => {
      if (isRecurring(o)) setAsking(o);
      else if (window.confirm(CANCEL_CONFIRM)) void send(o);
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
