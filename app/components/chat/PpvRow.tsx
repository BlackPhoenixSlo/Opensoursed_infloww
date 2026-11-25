"use client";


import type { ReactNode } from "react";

import { EXECUTOR_MAX_MINUTES } from "@/hooks/useSendMessage";
import { MP } from "@/lib/messagesPro";
import { cn } from "@/lib/utils";
import { fmtPrice } from "@/lib/format";
import { IfDateInput } from "@/components/ui/ifDateInput";

const FIELD_BOX = cn(
  MP.ppvRow.input,
  "bg-bg border-border focus-within:border-accent has-disabled:opacity-40",
);

export const FIELD = cn(FIELD_BOX, "focus:outline-none placeholder:text-muted disabled:opacity-40");

export interface PpvRowProps {
  price: string;
  onPrice: (raw: string) => void;
  lockText: boolean;
  onLockText: (on: boolean) => void;
  scheduleOn: boolean;
  at: string;
  onAt: (value: string) => void;
  onClear: () => void;
  disabled?: boolean;
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
          <IfDateInput
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

export function FreePreviews({
  count, total, enabled, onStep,
}: {
  count: number;
  total: number;
  enabled: boolean;
  onStep: (by: 1 | -1) => void;
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
        onClick={() => onStep(-1)}
        disabled={!enabled || count === 0}
        className={step}
        aria-label="Fewer free previews"
        title="Fewer free previews"
      >−</button>
      <span className="tabular-nums text-fg">{count}/{total}</span>
      <button
        type="button"
        onClick={() => onStep(1)}
        disabled={!enabled || count >= total}
        className={step}
        aria-label="More free previews"
        title="More free previews"
      >+</button>
    </div>
  );
}

export function toLocalInput(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function describeSchedule(value: string): string {
  const d = new Date(value);
  const deltaMs = d.getTime() - Date.now();
  // Short delays ride our executor queue, longer ones OF's native queue.
  if (deltaMs <= EXECUTOR_MAX_MINUTES * 60_000) {
    const mins = Math.max(1, Math.round(deltaMs / 60_000));
    return `Sending in ${mins} min (scheduled)`;
  }
  return `Queued for ${d.toLocaleString()}`;
}
