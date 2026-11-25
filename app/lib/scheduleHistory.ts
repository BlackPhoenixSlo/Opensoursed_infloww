const STORAGE_PREFIX = "chatterly:schedule:history:";
const HISTORY_CAP = 8;
const DELTA_SAMPLE = 3;
const DAY_MS = 24 * 60 * 60 * 1000;
const MIN_DELTA_MS = 5 * 60 * 1000;
const MAX_DELTA_MS = 30 * DAY_MS;

export interface HistoryEntry {
  value: string;
  savedAt: number;
}

export interface Prediction {
  value: string;
  intervalLabel: string;
  fromDelta: boolean;
}

function key(scope: string | null | undefined): string {
  return STORAGE_PREFIX + (scope || "default");
}

export function loadHistory(scope: string | null | undefined): HistoryEntry[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(key(scope));
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(
      (e): e is HistoryEntry =>
        e && typeof e.value === "string" && e.value.length >= 16 && typeof e.savedAt === "number",
    );
  } catch {
    return [];
  }
}

function saveHistory(scope: string | null | undefined, entries: HistoryEntry[]): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(key(scope), JSON.stringify(entries.slice(0, HISTORY_CAP)));
  } catch { }
}

export function recordSchedule(scope: string | null | undefined, value: string): void {
  if (typeof value !== "string" || value.length < 16) return;
  const existing = loadHistory(scope);
  if (existing[0]?.value === value) return;
  existing.unshift({ value, savedAt: Date.now() });
  saveHistory(scope, existing);
}

function parseLocal(value: string): Date | null {
  const m = value.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2}))?$/);
  if (!m) return null;
  const [, y, mo, d, h, mi, s] = m;
  // Not `new Date(s)`: some Node versions read it as UTC; we want local.
  const date = new Date(Number(y), Number(mo) - 1, Number(d), Number(h), Number(mi), Number(s || 0));
  return isNaN(date.getTime()) ? null : date;
}

export function toLocalDatetimeInput(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export function predictNext(history: HistoryEntry[], now: Date = new Date()): Prediction | null {
  if (history.length === 0) return null;
  const times = history
    .map((e) => parseLocal(e.value))
    .filter((d): d is Date => d !== null);
  if (times.length === 0) return null;
  const last = times[0];

  if (times.length === 1) {
    const inferred = Math.abs(last.getTime() - history[0].savedAt);
    if (inferred >= MIN_DELTA_MS && inferred <= MAX_DELTA_MS) {
      let next = new Date(last.getTime() + inferred);
      while (next.getTime() <= now.getTime()) next = new Date(next.getTime() + inferred);
      return { value: toLocalDatetimeInput(next), intervalLabel: formatInterval(inferred), fromDelta: true };
    }
    let next = new Date(last.getTime() + DAY_MS);
    while (next.getTime() <= now.getTime()) next = new Date(next.getTime() + DAY_MS);
    return { value: toLocalDatetimeInput(next), intervalLabel: "", fromDelta: false };
  }

  const deltas: number[] = [];
  for (let i = 0; i < times.length - 1 && deltas.length < DELTA_SAMPLE; i++) {
    const d = times[i].getTime() - times[i + 1].getTime();
    if (d >= MIN_DELTA_MS && d <= MAX_DELTA_MS) deltas.push(d);
  }
  if (deltas.length === 0) {
    let next = new Date(last.getTime() + DAY_MS);
    while (next.getTime() <= now.getTime()) next = new Date(next.getTime() + DAY_MS);
    return { value: toLocalDatetimeInput(next), intervalLabel: "", fromDelta: false };
  }
  const avg = Math.round(deltas.reduce((s, x) => s + x, 0) / deltas.length);
  let next = new Date(last.getTime() + avg);
  while (next.getTime() <= now.getTime()) next = new Date(next.getTime() + avg);
  return { value: toLocalDatetimeInput(next), intervalLabel: formatInterval(avg), fromDelta: true };
}

function formatInterval(ms: number): string {
  const totalMin = Math.max(1, Math.round(ms / 60000 / 5) * 5);
  const days = Math.floor(totalMin / (60 * 24));
  const hours = Math.floor((totalMin - days * 60 * 24) / 60);
  const mins = totalMin - days * 60 * 24 - hours * 60;
  const parts: string[] = [];
  if (days) parts.push(`${days}d`);
  if (hours) parts.push(`${hours}h`);
  if (!days && mins) parts.push(`${mins}m`);
  return parts.join(" ") || "0m";
}

export function describePrediction(value: string): string {
  const d = parseLocal(value);
  if (!d) return value;
  const date = d.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" });
  const time = d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
  return `${date} · ${time}`;
}

export function localDatetimeToIso(value: string): string | null {
  const d = parseLocal(value);
  return d ? d.toISOString() : null;
}
