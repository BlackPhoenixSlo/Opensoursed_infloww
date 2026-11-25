"use client";

import { useState } from "react";
import { IfInput } from "@/components/ui/infloww";
import { cn } from "@/lib/utils";

export function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="mb-2 block text-[14px] text-fg">{label}</span>
      {children}
    </label>
  );
}

export function NumInput({
  value, onChange, min = 0, className, ...props
}: Omit<React.ComponentProps<typeof IfInput>, "value" | "onChange" | "min"> & {
  value: number; onChange: (v: number) => void; min?: number;
}) {
  // Raw keystrokes live in a draft (a number-bound box shows "040" after typing 40 and cannot be cleared); an external value change wins.
  const [draft, setDraft] = useState<{ text: string; base: number } | null>(null);
  const showDraft = draft !== null && value === draft.base;
  return (
    <IfInput
      {...props} type="number" min={min} className={cn("w-full", className)}
      value={showDraft ? draft.text : String(value)}
      onChange={(e) => {
        const raw = e.target.value;
        const n = Number(raw);
        setDraft({ text: raw, base: raw === "" ? value : n });
        if (raw !== "" && Number.isFinite(n)) onChange(n);
      }}
      onBlur={(e) => { setDraft(null); props.onBlur?.(e); }}
    />
  );
}
