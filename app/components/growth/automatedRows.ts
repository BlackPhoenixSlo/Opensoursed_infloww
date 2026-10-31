/**
 * automatedRows — the Automated Messages tab's pure row helpers (AutomatedMessagesTab): a rule's Status, the nudge's
 * message lines, the Smart Message settings' cells and the date cells, in the report time zone. Tested on their own
 * (automatedRows.test.ts).
 */

import { type NudgeSlots } from "@/hooks/useNudgeConfig";
import { fmtPrice } from "@/lib/format";

import { dayKey } from "./frameDates";
import { extrasOfPayload } from "./SmartMessageFields";
import { SM, SM_AUTOMATED_COLUMNS } from "./smartMessagesControls";

export type ColumnLabel = (typeof SM_AUTOMATED_COLUMNS)[number]["label"];

/** A rule or switch that is on reads "Active", off "Canceled"; on, before its
 *  Effective date "Scheduled", from its Expiry "Completed". */
export function statusOf(on: boolean, payload?: Record<string, unknown>, now: number = Date.now()): string {
  if (!on) return SM.statusCanceled.label;
  const { starts_at, ends_at } = extrasOfPayload(payload);
  if (starts_at && Date.parse(starts_at) > now) return SM.statusScheduled.label;
  if (ends_at && Date.parse(ends_at) <= now) return SM.statusCompleted.label;
  return SM.statusActive.label;
}

/** Every message line of the nudge's tease pools, in stored order. */
export function slotLines(slots: NudgeSlots | undefined): string[] {
  return Object.values(slots ?? {})
    .flatMap((bucket) => Object.values(bucket ?? {}).flatMap((entry) => entry?.text ?? []))
    .map((t) => t.trim())
    .filter(Boolean);
}

/** The cells a rule's Smart Message settings fill: the bundle's " --" / "--"
 *  where one is unset (index.9f50f370.js @16299052, @16300051, @16301218). */
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

/** "MMM D, YYYY" in the report time zone, as the bundle's date columns render
 *  (`dayjs(...).tz(sn).format("MMM D, YYYY")`, index.9f50f370.js @16301606);
 *  the browser's zone when none is saved. */
export function shortDate(iso: string | null, timeZone: string | null): string | null {
  if (!iso) return null;
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? null
    : d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric", timeZone: timeZone ?? undefined });
}

/** The day of `iso` as YYYY-MM-DD in the report time zone (`frameDates.dayKey`), for the Date
 *  created filter's comparison. */
export function dayOf(iso: string | null, timeZone: string | null): string | null {
  if (!iso) return null;
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? null : dayKey(d, timeZone);
}
