function wallParts(at: Date, timeZone?: string | null) {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: timeZone ?? undefined, hourCycle: "h23",
    year: "numeric", month: "numeric", day: "numeric", hour: "numeric", minute: "numeric", second: "numeric",
  }).formatToParts(at);
  const part = (type: string) => Number(parts.find((p) => p.type === type)?.value);
  return { y: part("year"), m: part("month"), d: part("day"), h: part("hour"), mi: part("minute"), s: part("second") };
}

export function daysAgoISO(n: number, timeZone?: string | null): string {
  const { y, m, d } = wallParts(new Date(), timeZone);
  return new Date(Date.UTC(y, m - 1, d - n)).toISOString().slice(0, 10);
}

export function todayISO(timeZone?: string | null): string {
  return daysAgoISO(0, timeZone);
}

export type FixedRangePreset = "day" | "7d" | "30d" | "90d" | "365d";

export const PRESET_DAYS: Record<FixedRangePreset, number> = { day: 1, "7d": 7, "30d": 30, "90d": 90, "365d": 365 };

// Keeps today (unlike Infloww's, which stops at yesterday) so today's pending sales show.
export function presetRange(p: FixedRangePreset, timeZone?: string | null): [string, string] {
  return [daysAgoISO(PRESET_DAYS[p] - 1, timeZone), todayISO(timeZone)];
}

export function addDayStr(day: string, n: number): string {
  const [y, m, d] = day.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d + n)).toISOString().slice(0, 10);
}

export function shiftYears(day: string, n: number): string {
  const [y, m, d] = day.split("-").map(Number);
  return new Date(Date.UTC(y + n, m - 1, d)).toISOString().slice(0, 10);
}

export function dateBounds(timeZone?: string | null): [string, string] {
  const today = todayISO(timeZone);
  return [shiftYears(today, -1), addDayStr(today, 2)];
}

function zoneOffsetMs(at: number, timeZone?: string | null): number {
  const { y, m, d, h, mi, s } = wallParts(new Date(at), timeZone);
  return Date.UTC(y, m - 1, d, h, mi, s) - Math.floor(at / 1000) * 1000;
}

function dayStartMs(wall: number, timeZone?: string | null): number {
  const first = wall - zoneOffsetMs(wall, timeZone);
  const second = wall - zoneOffsetMs(first, timeZone);
  const onDay = (at: number) => {
    const { y, m, d } = wallParts(new Date(at), timeZone);
    return Date.UTC(y, m - 1, d) >= wall;
  };
  return [Math.min(first, second), Math.max(first, second)].find(onDay) ?? Math.max(first, second);
}

export function monthRange(timeZone?: string | null): [Date, Date] {
  const { y, m } = wallParts(new Date(), timeZone);
  return [
    new Date(dayStartMs(Date.UTC(y, m - 1, 1), timeZone)),
    new Date(dayStartMs(Date.UTC(y, m, 1), timeZone)),
  ];
}

export function toLocalIso(date: string | null, end: boolean, timeZone?: string | null): string | null {
  if (!date) return null;
  const hour = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):00$/.exec(date);
  if (hour) {
    const [y, m, d, h] = hour.slice(1).map(Number);
    const wall = Date.UTC(y, m - 1, d, h + (end ? 1 : 0));
    const at = wall - zoneOffsetMs(wall - zoneOffsetMs(wall, timeZone), timeZone);
    return new Date(end ? at - 1 : at).toISOString();
  }
  if (date.includes("T")) return date;
  const parts = date.split("-").map(Number);
  if (parts.length !== 3 || parts.some((n) => !Number.isFinite(n))) return date;
  const [y, m, d] = parts;
  const at = end ? dayStartMs(Date.UTC(y, m - 1, d + 1), timeZone) - 1 : dayStartMs(Date.UTC(y, m - 1, d), timeZone);
  return new Date(at).toISOString();
}

const HOUR_MS = 3_600_000;

export function priorRange(from: string | null, to: string | null): [string, string] | null {
  const wall = (v: string, end: boolean) => Date.parse(`${v.length > 10 ? v : `${v}T${end ? "23" : "00"}:00`}:00Z`);
  const back = (at: number, end: boolean) => {
    const iso = new Date(at).toISOString();
    return iso.slice(11, 13) === (end ? "23" : "00") ? iso.slice(0, 10) : `${iso.slice(0, 13)}:00`;
  };
  if (!from || !to) return null;
  const f = wall(from, false);
  const t = wall(to, true);
  if (!Number.isFinite(f) || !Number.isFinite(t) || t < f) return null;
  return [back(f - (t - f + HOUR_MS), false), back(f - HOUR_MS, true)];
}

export type Period = "yesterday" | "today" | "week" | "month" | "last30Days";

export function periodWindow(
  period: Period, timeZone: string | null, weekStart: "monday" | "sunday",
): [string, string] {
  if (period === "month") {
    const [first, next] = monthRange(timeZone);
    return [first.toISOString(), new Date(next.getTime() - 1).toISOString()];
  }
  if (period === "last30Days") {
    const [from, to] = presetRange("30d", timeZone);
    return [toLocalIso(from, false, timeZone)!, toLocalIso(to, true, timeZone)!];
  }
  let back = period === "yesterday" ? 1 : 0;
  let days = 1;
  if (period === "week") {
    const weekday = new Date(`${todayISO(timeZone)}T00:00:00Z`).getUTCDay();
    back = weekStart === "sunday" ? weekday : (weekday + 6) % 7;
    days = 7;
  }
  return [
    toLocalIso(daysAgoISO(back, timeZone), false, timeZone)!,
    toLocalIso(daysAgoISO(back - days + 1, timeZone), true, timeZone)!,
  ];
}
