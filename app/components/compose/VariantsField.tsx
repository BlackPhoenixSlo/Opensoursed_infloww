"use client";

/**
 * VariantsField — one pool of message texts: a box per text, Remove (never
 * the last), "Add variant" and "Import captions", both capped at `max`. The
 * caller owns the pool (`onChange` gets the whole new list) and how it sends:
 * one picked per send on the Smart Messages Trigger editors and the ready-made
 * rule composer (PremadeForm); on a funnel step card the first 2 non-blank go
 * out, in order.
 */

import { IfButton, IfHelp, IfLabel, IfTextArea } from "@/components/ui/infloww";
import { mergeCaptions } from "@/lib/parseCaptions";

import { ImportCaptionsButton } from "./ImportCaptionsButton";

export function VariantsField({
  id, label, variants, placeholder, max, maxLength, help = "Each fan gets one of these at random.", onChange,
}: {
  /** Box i gets `${id}-${i}`; the label points at box 0. */
  id: string;
  label: string;
  variants: string[];
  /** The first box's placeholder. */
  placeholder?: string;
  /** The pool's cap (Add and Import stop there); none = no cap. */
  max?: number;
  /** Per-variant character cap. */
  maxLength?: number;
  /** Shown once there is more than one variant. */
  help?: string;
  onChange: (v: string[]) => void;
}) {
  return (
    <div className="space-y-2">
      <IfLabel htmlFor={`${id}-0`} className="mb-0">{label}</IfLabel>
      {variants.map((v, i) => (
        <div key={i} className="flex items-start gap-3">
          <IfTextArea
            id={`${id}-${i}`}
            aria-label={i ? `${label}, variant ${i + 1}` : undefined}
            value={v}
            maxLength={maxLength}
            placeholder={i === 0 ? placeholder : "Another way to say it"}
            rows={3}
            onChange={(e) => onChange(variants.map((x, j) => (j === i ? e.target.value : x)))}
          />
          {variants.length > 1 && (
            <IfButton variant="link" aria-label={`Remove variant ${i + 1}`} onClick={() => onChange(variants.filter((_, j) => j !== i))}>
              Remove
            </IfButton>
          )}
        </div>
      ))}
      <div className="flex flex-wrap items-center gap-4">
        {(max === undefined || variants.length < max) && (
          <IfButton variant="link" onClick={() => onChange([...variants, ""])}>
            Add variant
          </IfButton>
        )}
        <ImportCaptionsButton current={variants} max={max}
          onImport={(items) => onChange(mergeCaptions(variants, items).pool)} />
      </div>
      {variants.length > 1 && <IfHelp>{help}</IfHelp>}
    </div>
  );
}
