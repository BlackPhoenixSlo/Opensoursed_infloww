"use client";

/**
 * MessageDashboardFilters — the All tab's filters the shared MessagesFilters
 * strip does not carry (roadmap 5.7): Search message text, Price min/max,
 * Type = Employee / Automation and Status = unsent, applied as they change.
 * All-Messages tab only; the PPV and Tips tabs keep MessagesFilters as it is.
 * The All tab shows both kinds: Direct messages and OnlyFans mass messages are
 * the page's own tabs now (page-parity 30, MessageDashboardForm).
 *
 * Price is typed in dollars and handed up as cents (the relay's unit). Text
 * search debounces 250ms, as the fan search does, and is sent from 2 chars.
 *
 * No Script filter: no message row records the script it came from, so there
 * is nothing honest to filter on.
 */

import { useEffect, useState } from "react";

import { Input } from "@/components/ui/primitives";

import type { SenderType } from "@/hooks/usePaidMessages";

export interface DashboardFilterValue {
  q: string;
  minPriceCents: number | null;
  maxPriceCents: number | null;
  senderType: SenderType;
  unsentOnly: boolean;
}

export const EMPTY_DASHBOARD_FILTERS: DashboardFilterValue = {
  q: "",
  minPriceCents: null,
  maxPriceCents: null,
  senderType: "any",
  unsentOnly: false,
};

function toCents(raw: string): number | null {
  const n = Number(raw);
  return raw.trim() === "" || !Number.isFinite(n) || n < 0 ? null : Math.round(n * 100);
}

export default function MessageDashboardFilters({
  value,
  onChange,
}: {
  value: DashboardFilterValue;
  onChange: (next: DashboardFilterValue) => void;
}) {
  const set = (patch: Partial<DashboardFilterValue>) => onChange({ ...value, ...patch });

  // Local mirror so typing feels instant; nothing resets the parent's string
  // from outside, so no sync back.
  const [localQ, setLocalQ] = useState(value.q);
  useEffect(() => {
    const h = window.setTimeout(() => {
      if (localQ !== value.q) set({ q: localQ });
    }, 250);
    return () => window.clearTimeout(h);
    // keyed on the typed string only, as MessagesFilters' fan search
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [localQ]);

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-end gap-3 p-3 bg-panel border border-border rounded-xl">
        <Field label="Message text">
          <Input
            value={localQ}
            onChange={(e) => setLocalQ(e.target.value)}
            maxLength={200}
            placeholder="Search message text"
            className="text-xs py-1.5 w-52"
            aria-label="Search message text"
          />
        </Field>

        <Field label="Price ($)">
          <div className="flex items-center gap-1">
            <PriceInput label="Minimum price" cents={value.minPriceCents} onChange={(c) => set({ minPriceCents: c })} />
            <span className="text-fg-dim text-xs">–</span>
            <PriceInput label="Maximum price" cents={value.maxPriceCents} onChange={(c) => set({ maxPriceCents: c })} />
          </div>
        </Field>

        <Field label="Sent by">
          <select
            value={value.senderType}
            onChange={(e) => set({ senderType: e.target.value as SenderType })}
            className="bg-bg border border-border rounded-lg px-2 py-1.5 text-xs text-fg focus:outline-none focus:border-accent"
          >
            <option value="any">Anyone</option>
            <option value="employee">Employee</option>
            <option value="automation">Automation (AI)</option>
          </select>
        </Field>

        <label className="flex items-center gap-1.5 text-xs text-fg pb-1.5">
          <input
            type="checkbox"
            checked={value.unsentOnly}
            onChange={(e) => set({ unsentOnly: e.target.checked })}
          />
          Unsent only
        </label>
      </div>
    </div>
  );
}

function PriceInput({ label, cents, onChange }: { label: string; cents: number | null; onChange: (c: number | null) => void }) {
  const [raw, setRaw] = useState(cents == null ? "" : String(cents / 100));
  return (
    <Input
      type="number"
      min={0}
      step="0.01"
      inputMode="decimal"
      value={raw}
      onChange={(e) => setRaw(e.target.value)}
      onBlur={() => onChange(toCents(raw))}
      onKeyDown={(e) => { if (e.key === "Enter") onChange(toCents(raw)); }}
      aria-label={label}
      className="text-xs py-1.5 w-20"
    />
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-[10px] uppercase tracking-wide text-fg-dim">{label}</span>
      {children}
    </label>
  );
}
