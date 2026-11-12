/** Smart Messages' status pills (Infloww #98-#102) in the theme palette, for the My Automations lists: Auto Post and
 *  Auto Mass rows (`ruleStatus`), their previous runs (`runStatus`); the form pages can adopt it. */

import type { AutomationRule } from "@/hooks/useAutomations";
import { cn } from "@/lib/utils";

export type PillTone = "idle" | "active" | "ok" | "warn" | "err";
export interface PillStatus { label: string; tone: PillTone; hint?: string }

const TONE: Record<PillTone, string> = {
  idle: "bg-fg-dim/15 text-fg-dim",
  active: "bg-accent/15 text-accent",
  ok: "bg-ok/15 text-ok",
  warn: "bg-warn/15 text-warn",
  err: "bg-err/15 text-err",
};

export function StatusPill({ status, className }: { status: PillStatus; className?: string }) {
  return (
    <span title={status.hint} data-tone={status.tone}
      className={cn("inline-block whitespace-nowrap rounded-2xl px-2 py-0.5 text-[12px] leading-[18px]", TONE[status.tone], className)}>
      {status.label}
    </span>
  );
}

/** A saved rule's pill: Paused while switched off; else its last run's Running / Failed, or Active. */
export function ruleStatus(r: Pick<AutomationRule, "is_enabled" | "last_run">): PillStatus {
  if (!r.is_enabled) return { label: "Paused", tone: "warn", hint: "Switched off: nothing runs until it is on." };
  const st = r.last_run?.status;
  if (st === "running") return { label: "Running", tone: "active", hint: "Running now." };
  if (st === "error") return { label: "Failed", tone: "err", hint: "The last run failed; the error is under the name." };
  return { label: "Active", tone: "ok", hint: "Runs on its schedule." };
}

/** One previous run's pill: Done / Failed / Running, any other status (skipped…) as itself, capitalised. */
export function runStatus(status: string): PillStatus {
  if (status === "ok") return { label: "Done", tone: "ok" };
  if (status === "error") return { label: "Failed", tone: "err" };
  if (status === "running") return { label: "Running", tone: "active" };
  return { label: status ? status[0].toUpperCase() + status.slice(1) : "Unknown", tone: "idle" };
}
