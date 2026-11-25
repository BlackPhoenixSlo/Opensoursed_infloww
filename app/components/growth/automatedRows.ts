import { type NudgeSlots } from "@/hooks/useNudgeConfig";
import { fmtPrice } from "@/lib/format";

import { dayKey } from "./frameDates";
import { extrasOfPayload } from "./SmartMessageFields";
import { SM, SM_AUTOMATED_COLUMNS } from "./smartMessagesControls";

export type ColumnLabel = (typeof SM_AUTOMATED_COLUMNS)[number]["label"];

export function statusOf(on: boolean, payload?: Record<string, unknown>, now: number = Date.now()): string {
  if (!on) return SM.statusCanceled.label;
  const { starts_at, ends_at } = extrasOfPayload(payload);
  if (starts_at && Date.parse(starts_at) > now) return SM.statusScheduled.label;
  if (ends_at && Date.parse(ends_at) <= now) return SM.statusCompleted.label;
  return SM.statusActive.label;
}

export function slotLines(slots: NudgeSlots | undefined): string[] {
  return Object.values(slots ?? {})
    .flatMap((bucket) => Object.values(bucket ?? {}).flatMap((entry) => entry?.text ?? []))
    .map((t) => t.trim())
    .filter(Boolean);
}

export function extrasCells(payload: Record<string, unknown>, timeZone: string | null): Partial<Record<ColumnLabel, string>> {
  const x = extrasOfPayload(payload);
  const n = x.media_ids?.length ?? 0;
  return {
    "Attachment(s)": n ? `${n} media` : "--",
    Price: x.price_cents ? fmtPrice(x.price_cents) : "--",
    "Start date": shortDate(x.starts_at ?? null, timeZone) ?? "--",
    "End date": shortDate(x.ends_at ?? null, timeZone) ?? "--",
  };
}

export function shortDate(iso: string | null, timeZone: string | null): string | null {
  if (!iso) return null;
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? null
    : d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric", timeZone: timeZone ?? undefined });
}

export function dayOf(iso: string | null, timeZone: string | null): string | null {
  if (!iso) return null;
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? null : dayKey(d, timeZone);
}
