"use client";


import { IfButton, IfHelp, IfLabel, IfTextArea } from "@/components/ui/infloww";
import { mergeCaptions } from "@/lib/parseCaptions";

import { ImportCaptionsButton } from "./ImportCaptionsButton";

export function VariantsField({
  id, label, variants, placeholder, max, maxLength, help = "Each fan gets one of these at random.", onChange,
}: {
  id: string;
  label: string;
  variants: string[];
  placeholder?: string;
  max?: number;
  maxLength?: number;
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
