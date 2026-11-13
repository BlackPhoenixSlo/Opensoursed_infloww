"use client";

/** Small shared bits for the Growth tabs (Trial / Tracking / Promotion).
 *
 *  The last-run line every automation surface renders is NOT here any more — it
 *  is `@/lib/runStats`, because the Brain's welcome card renders it too and this
 *  module's leading underscore says "internal to this folder". Nothing forwards
 *  it any more — import `RunStats` / `runStatsChunks` / `isDryRun` from
 *  `@/lib/runStats` directly; the compatibility re-export that stood here while
 *  the importers were repointed is gone. */

import { useState } from "react";
import { Button } from "@/components/ui/primitives";
import { IfSelect } from "@/components/ui/infloww";
import { errText } from "@/lib/errText";
import { ifConfirm } from "@/components/ui/ifConfirm";

export { useIfConfirm } from "@/hooks/useIfConfirm";
export { Field, NumInput } from "@/components/ui/fields";

export function fmtUsd(cents: number): string {
  return `$${(Math.max(0, cents) / 100).toFixed(2)}`;
}


/** Message off a thrown value, with a fallback — `errText` under the name the Growth catches import. */
export const errMsg = (e: unknown, fallback: string) => errText(e, fallback);

/** The house select (`IfSelect`, pop-up field size) over `{value, label}` options (OF's / Infloww's dropdown
 *  lists), numbers in and out. */
export function SelectInput({
  value, options, onChange, ariaLabel, disabled,
}: {
  value: number;
  options: { value: string; label: string }[];
  onChange: (v: number) => void;
  ariaLabel?: string;
  disabled?: boolean;
}) {
  return (
    <IfSelect
      aria-label={ariaLabel}
      disabled={disabled}
      size="field"
      className="w-full"
      value={String(value)}
      options={options.map((o) => ({ value: o.value, label: o.label }))}
      onChange={(v) => onChange(Number(v))}
    />
  );
}

// ── Automation last-run stats live in `@/lib/runStats` ────────────────
//
// `isDryRun`, `runStatsChunks`, `welcomeStatsChunks`, `RunStats` and `StatChunk`
// were here. `RunStats` is not growth-only — the Brain's welcome card renders it
// too, and reaching across the folder boundary for an underscore-prefixed module
// is the seam a welcome bag came through into the auto_follow formatter. A
// compatibility re-export stood here while the importers were repointed; it is
// gone, so `_bits`'s underscore means what it says again: growth-local only.

/** Danger button that guards a delete behind a confirm (`ifConfirm`). Every Growth
 *  list row (trial / tracking / redirect / promo / segment) deleted through the
 *  same confirm→mutate→disabled-while-pending shape; this is that shape, once. */
export function ConfirmDeleteButton({
  confirm, onConfirm, pending, label = "Delete",
}: {
  confirm: string;
  onConfirm: () => void;
  pending?: boolean;
  label?: string;
}) {
  return (
    <Button
      size="sm" variant="danger" disabled={pending}
      onClick={async () => { if (await ifConfirm(confirm, { danger: true })) onConfirm(); }}
    >
      {label}
    </Button>
  );
}

/** Copy-to-clipboard button that flashes "Copied". Tracking links passes the
 *  bundle's "Link copied" held 5 s; a click during the flash copies nothing. */
export function CopyButton({
  text, label = "Copy", doneLabel = "✓ Copied", holdMs = 1200,
}: { text: string; label?: string; doneLabel?: string; holdMs?: number }) {
  const [done, setDone] = useState(false);
  return (
    <Button
      size="sm" variant="ghost"
      onClick={async () => {
        if (done) return;
        try {
          if (!navigator.clipboard?.writeText) return;   // insecure origin: no fake "Copied"
          await navigator.clipboard.writeText(text);
          setDone(true);
          setTimeout(() => setDone(false), holdMs);
        } catch { /* clipboard blocked */ }
      }}
      title={text}
    >
      {done ? doneLabel : label}
    </Button>
  );
}
