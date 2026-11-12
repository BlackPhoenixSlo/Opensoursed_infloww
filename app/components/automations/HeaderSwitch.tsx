"use client";

/**
 * The automation form pages' header on/off (Auto Story, Auto-reply, Get to know fans, Gen-Info): a status pill, then
 * the switch, saving the moment it flips (each page wires its own write). The switch is named by `label` (no visible
 * text: the page title beside it already says what it turns on). A plain On / Off pill hides on phones (the title needs the
 * room and the switch shows it); a `status` override ("Not saved") stays visible there.
 */

import type { ReactNode } from "react";

import { IfSwitch } from "@/components/ui/infloww";
import { Badge } from "@/components/ui/primitives";

export function HeaderSwitch({ label, checked, onChange, disabled, loading, status }: {
  label: string;
  checked: boolean;
  onChange: (on: boolean) => void;
  disabled?: boolean;
  loading?: boolean;
  /** Overrides the pill's On / Off (Auto Story's "Not saved" before its rule exists); null hides it. */
  status?: ReactNode | null;
}) {
  const pill = status === undefined ? (checked ? "On" : "Off") : status;
  return (
    <span className="inline-flex items-center gap-2 sm:gap-3">
      {pill !== null && <Badge className={status === undefined ? "hidden sm:inline-flex" : "px-1.5 sm:px-2"} color={status === undefined && checked ? "ok" : "muted"}>{pill}</Badge>}
      <IfSwitch aria-label={label} checked={checked} onChange={onChange} disabled={disabled} loading={loading} />
    </span>
  );
}
