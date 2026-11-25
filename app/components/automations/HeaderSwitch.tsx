"use client";


import type { ReactNode } from "react";

import { IfSwitch } from "@/components/ui/infloww";
import { Badge } from "@/components/ui/primitives";

const OVERRIDE_PILL = "px-1.5 sm:px-2 max-sm:w-min max-sm:whitespace-normal max-sm:text-center max-sm:leading-3 max-sm:rounded-lg";

export function HeaderSwitch({ id, label, checked, onChange, disabled, loading, status }: {
  id?: string;
  label: string;
  checked: boolean;
  onChange: (on: boolean) => void;
  disabled?: boolean;
  loading?: boolean;
  status?: ReactNode | null;
}) {
  const pill = status === undefined ? (checked ? "On" : "Off") : status;
  return (
    <span className="inline-flex items-center gap-2 sm:gap-3">
      {pill !== null && <Badge className={status === undefined ? "hidden sm:inline-flex" : OVERRIDE_PILL} color={status === undefined && checked ? "ok" : "muted"}>{pill}</Badge>}
      <IfSwitch id={id} aria-label={label} checked={checked} onChange={onChange} disabled={disabled} loading={loading} />
    </span>
  );
}
