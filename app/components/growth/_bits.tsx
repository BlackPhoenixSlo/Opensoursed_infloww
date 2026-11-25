"use client";


import { Button } from "@/components/ui/primitives";
import { IfSelect } from "@/components/ui/infloww";
import { errText } from "@/lib/errText";
import { ifConfirm } from "@/components/ui/ifConfirm";

export { useIfConfirm } from "@/hooks/useIfConfirm";
export { Field, NumInput } from "@/components/ui/fields";

export function fmtUsd(cents: number): string {
  return `$${(Math.max(0, cents) / 100).toFixed(2)}`;
}


export const errMsg = (e: unknown, fallback: string) => errText(e, fallback);

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

