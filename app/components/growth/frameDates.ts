/**
 * frameDates — day arithmetic for LinksListFrame's Date created filter (#21, #22) and automatedRows' `dayOf`:
 * YYYY-MM-DD days in the report time zone (a link's `createdDay` among them), and the bundle's preset ranges'
 * steps. Pure, so the presets' month ends, leap days and year rollovers are tested on their own (frameDates.test.ts).
 */

import { parseUtc } from "@/lib/format";

/** `at` as YYYY-MM-DD in the report time zone (`en-CA` prints the ISO order). */
export function dayKey(at: Date, tz: string | null): string {
  return at.toLocaleDateString("en-CA", { timeZone: tz ?? undefined, year: "numeric", month: "2-digit", day: "2-digit" });
}

/** The day a link was created, in the report time zone; null with no (or a bad) date. Our links' stamps come
 *  zone-less (naive UTC), so they are read as UTC. */
export function createdDay(l: { created_at: string | null }, tz: string | null): string | null {
  const d = parseUtc(l.created_at);
  return d ? dayKey(d, tz) : null;
}

/** A YYYY-MM-DD day moved by `n` days. */
export function addDays(day: string, n: number): string {
  const d = new Date(`${day}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
}

/** The first of the month `m` months before a YYYY-MM-DD day (dayjs `subtract(m,"month").startOf("month")`). */
export function monthStartBefore(day: string, m: number): string {
  const d = new Date(`${day}T00:00:00Z`);
  d.setUTCDate(1);
  d.setUTCMonth(d.getUTCMonth() - m);
  return d.toISOString().slice(0, 10);
}
