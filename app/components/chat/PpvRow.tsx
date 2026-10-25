"use client";

/**
 * PpvRow — the Composer's PPV row (docs/spec/phase-04-composer-ppv-vault.md,
 * Gap rows 10–14, Interfaces): a controlled `role="group"` named "PPV row" in
 * the deleted Clone's order (messages.html:739–753, tag legacy-ui-final):
 *
 *   "PPV" · "$" + price · lock text · attachments (children) · "at" · "Clear"
 *
 * With media attached the Composer puts `FreePreviews` first among the
 * children, as the earlier in-OF overlay composer showed its stepper (TODO.md A2).
 *
 * No box; it wraps. The Composer decides when it shows and owns every value;
 * this module only lays the row out. Its Geometry is the Clone's (`.comp-x`,
 * messages.html:514–518; `.btn-sm`, :499), from `MP.ppvRow` (PV1–PV9), in
 * Infloww's input typography since look-and-feel ticket 148 (Gap row C11:
 * 14px at 140%, radius 4px, the 85px price field with its `$` inside).
 */

import type { ReactNode } from "react";

import { EXECUTOR_MAX_MINUTES } from "@/hooks/useSendMessage";
import { MP } from "@/lib/messagesPro";
import { cn } from "@/lib/utils";
import { fmtPrice } from "@/lib/format";

/** A field's box (`MP.ppvRow.input`, PV4) in our colours: the price field's
 *  box around its `$` and input, and through `FIELD` every bare field.
 *  `:focus-within` also matches a focused bare input. */
const FIELD_BOX = cn(
  MP.ppvRow.input,
  "bg-bg border-border focus-within:border-accent has-disabled:opacity-40",
);

/** A bare field (Clone `.comp-x input`) in the field box's style. Exported
 *  for the ⏱ Timed message's minutes field. */
export const FIELD = cn(FIELD_BOX, "focus:outline-none placeholder:text-muted disabled:opacity-40");

export interface PpvRowProps {
  /** The sanitized price string; a value above 0 makes the send paid. */
  price: string;
  onPrice: (raw: string) => void;
  lockText: boolean;
  onLockText: (on: boolean) => void;
  /** Schedule mode shows "at" and its date field. */
  scheduleOn: boolean;
  at: string;
  onAt: (value: string) => void;
  onClear: () => void;
  disabled?: boolean;
  /** The attachment tiles and GIF chips, between "lock text" and "at". */
  children?: ReactNode;
}

export function PpvRow({
  price, onPrice, lockText, onLockText, scheduleOn, at, onAt, onClear, disabled, children,
}: PpvRowProps) {
  const paid = Number(price);
  return (
    <div
      role="group"
      aria-label="PPV row"
      className={cn(MP.ppvRow.row, "flex flex-wrap items-center text-fg-dim")}
    >
      <span className={cn(MP.ppvRow.label, "text-fg")}>PPV</span>
      {/* The box is the field (look-and-feel C11): "$" drawn inside it,
       *  then the input, which draws no box of its own. */}
      <label
        className={cn(FIELD_BOX, MP.ppvRow.price, "flex items-center")}
      >
        <span aria-hidden>$</span>
        <input
          type="text"
          inputMode="decimal"
          value={price}
          onChange={(e) => onPrice(e.target.value)}
          disabled={disabled}
          placeholder="0.00"
          aria-label="PPV price"
          title={paid > 0 ? `Fan pays ${fmtPrice(Math.round(paid * 100))} to read` : "Price 0 sends for free; set a price > 0 to send as paid"}
          className="min-w-0 flex-1 focus:outline-none placeholder:text-muted"
        />
      </label>
      <label className={cn(MP.ppvRow.group, "flex items-center cursor-pointer select-none")}>
        <input
          type="checkbox"
          checked={lockText}
          onChange={(e) => onLockText(e.target.checked)}
          disabled={disabled}
          className="accent-accent"
        />
        lock text
      </label>
      {children}
      {scheduleOn && (
        <span className="flex items-center gap-1.5">
          <span>at</span>
          <input
            type="datetime-local"
            value={at}
            onChange={(e) => onAt(e.target.value)}
            min={toLocalInput(new Date())}
            disabled={disabled}
            aria-label="Send at"
            title={at
              ? new Date(at) > new Date() ? describeSchedule(at) : "Pick a future time"
              : "Pick a date/time or a preset under ⏱"}
            className={FIELD}
          />
        </span>
      )}
      <button
        type="button"
        onClick={onClear}
        disabled={disabled}
        className={cn(MP.ppvRow.clear, "ml-auto bg-bg-elev-2 text-fg hover:brightness-125 disabled:opacity-40")}
      >
        Clear
      </button>
    </div>
  );
}

/** The free previews stepper: how many leading tiles go out unlocked. Its
 *  buttons work only on a paid message (`enabled`); a free one has no split. */
export function FreePreviews({
  count, total, enabled, onChange,
}: {
  count: number;
  total: number;
  enabled: boolean;
  onChange: (updater: (c: number) => number) => void;
}) {
  const step = "w-6 h-6 grid place-items-center rounded border border-border hover:bg-bg-elev-1 disabled:opacity-30";
  return (
    <div
      role="group"
      aria-label="Free previews"
      title={enabled
        ? "How many tiles are free previews. Drag a tile across the divider to flip its side."
        : "Set a price > 0 to choose free previews"}
      className="flex items-center gap-1.5"
    >
      <span>free</span>
      <button
        type="button"
        onClick={() => onChange((c) => Math.max(0, c - 1))}
        disabled={!enabled || count === 0}
        className={step}
        aria-label="Fewer free previews"
      >−</button>
      <span className="tabular-nums text-fg">{count}/{total}</span>
      <button
        type="button"
        onClick={() => onChange((c) => Math.min(total, c + 1))}
        disabled={!enabled || count >= total}
        className={step}
        aria-label="More free previews"
      >+</button>
    </div>
  );
}

/** datetime-local needs `YYYY-MM-DDTHH:MM` in local time (no Z). */
export function toLocalInput(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/** Describe the schedule in plain English. Both ranges are server-side now and
 *  survive reload; short delays (≤ 15 min) ride our executor queue, longer ones
 *  OF's native queue. */
function describeSchedule(value: string): string {
  const d = new Date(value);
  const deltaMs = d.getTime() - Date.now();
  if (deltaMs <= EXECUTOR_MAX_MINUTES * 60_000) {
    const mins = Math.max(1, Math.round(deltaMs / 60_000));
    return `Sending in ${mins} min (scheduled)`;
  }
  return `Queued for ${d.toLocaleString()}`;
}
