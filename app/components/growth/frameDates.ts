import { parseUtc } from "@/lib/format";

export function dayKey(at: Date, tz: string | null): string {
  return at.toLocaleDateString("en-CA", { timeZone: tz ?? undefined, year: "numeric", month: "2-digit", day: "2-digit" });
}

// Link stamps are zone-less naive UTC: read as UTC.
export function createdDay(l: { created_at: string | null }, tz: string | null): string | null {
  const d = parseUtc(l.created_at);
  return d ? dayKey(d, tz) : null;
}

export { addDayStr as addDays } from "@/lib/dateRange";

export function monthStartBefore(day: string, m: number): string {
  const d = new Date(`${day}T00:00:00Z`);
  d.setUTCDate(1);
  d.setUTCMonth(d.getUTCMonth() - m);
  return d.toISOString().slice(0, 10);
}
