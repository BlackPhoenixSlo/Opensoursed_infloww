import { parseUtc } from "@/lib/format";

export type LaneName = "origin_probe" | "mega_lookup" | "listing_recheck" | "google_fresh" | "google_full" | "registry_crawl";
export type LaneState = "ok" | "waiting" | "reduced" | "failed" | "never" | "paused";
export type LeakTrimmed = { field: string; value: string };

export type LeakLane = {
  lane: LaneName;
  cadence: "daily" | "weekly";
  state: LaneState;
  reason: string | null;
  last_success_at: string | null;
  last_attempt_at: string | null;
  next_attempt_on: string | null;
  trimmed: LeakTrimmed[];
};

export type LaneRow = {
  lane: LaneName;
  label: string;
  chip: string;
  tone: LaneState;
  note: string | null;
  lastOk: string | null;
  next: string | null;
  skipped: string[];
};

export const LANE_ORDER: readonly LaneName[] = [
  "origin_probe", "mega_lookup", "listing_recheck", "google_fresh", "google_full", "registry_crawl",
];

export const LANE_LABEL: Record<LaneName, string> = {
  origin_probe: "Link check",
  mega_lookup: "Mega",
  listing_recheck: "Leak-site pages",
  google_fresh: "Google (past day)",
  google_full: "Google full search",
  registry_crawl: "Leak-site search",
};

const BUDGET = new Set(["cap_global", "cap_tenant_month", "judge_cap", "creator_cap"]);

const CHIP: Record<LaneState, string> = {
  ok: "OK", waiting: "Waiting", reduced: "Reduced", failed: "Failed", never: "Not run yet", paused: "Paused",
};

const REASON: Record<string, string> = {
  cap_global: "The removal service's daily search limit is used up",
  cap_tenant_month: "Your agency's monthly search allowance is used up",
  judge_cap: "The daily limit for checking results is used up",
  creator_cap: "Your agency's Creator limit is reached",
  google_failed: "Google didn't load; no other search engine is used",
  listing_rotated: "Too many pages to re-read in one day, so each is re-read every few days",
};

export const FRESHNESS = "Known links are checked daily. New Google results show within a day, or within a week on a reduced day. "
  + "Images, videos and new sites show within a week.";

function ago(iso: string, now: Date): string | null {
  const d = parseUtc(iso);
  if (!d) return null;
  const mins = Math.max(0, Math.round((now.getTime() - d.getTime()) / 60_000));
  if (mins < 60) return mins < 1 ? "just now" : `${mins} min ago`;
  const hrs = Math.round(mins / 60);
  return hrs < 24 ? `${hrs} h ago` : `${Math.round(hrs / 24)} d ago`;
}

function onDay(day: string, now: Date): string | null {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(day)) return null;
  const d = new Date(`${day}T00:00:00Z`);
  if (Number.isNaN(d.getTime())) return null;
  const text = new Intl.DateTimeFormat("en-GB", { timeZone: "UTC", weekday: "short", day: "numeric", month: "short" }).format(d);
  return d.getUTCFullYear() === now.getUTCFullYear() ? text.replace(",", "") : `${text.replace(",", "")} ${d.getUTCFullYear()}`;
}

const FIELD_NAME: Record<string, string> = { instagram: "Instagram", x: "X" };

export const skippedNames = (trimmed: LeakTrimmed[]): string[] =>
  trimmed.map((t) => FIELD_NAME[t.field] ?? t.value);

function chip(lane: LeakLane): string {
  if (lane.state === "waiting" && lane.reason && BUDGET.has(lane.reason)) return "Waiting on budget";
  return CHIP[lane.state];
}

function note(lane: LeakLane): string | null {
  if (lane.state === "never" || lane.state === "paused" || lane.state === "ok" || !lane.reason) return null;
  if (lane.reason === "lane_failed") return lane.state === "waiting" ? "Not finished; it carries on the next day" : null;
  return REASON[lane.reason] ?? null;
}

export function laneRows(lanes: LeakLane[], now: Date): LaneRow[] {
  const by = new Map(lanes.map((l) => [l.lane, l]));
  return LANE_ORDER.map((name) => {
    const l = by.get(name);
    if (!l) {
      return { lane: name, label: LANE_LABEL[name], chip: CHIP.never, tone: "never", note: null, lastOk: null, next: null,
        skipped: [] };
    }
    const last = l.state !== "never" && l.last_success_at ? ago(l.last_success_at, now) : null;
    const next = l.state !== "paused" && l.next_attempt_on ? onDay(l.next_attempt_on, now) : null;
    return {
      lane: name,
      label: LANE_LABEL[name],
      chip: chip(l),
      tone: l.state,
      note: note(l),
      lastOk: last && `last OK ${last}`,
      next: next && `next attempt ${next}`,
      skipped: l.state === "never" ? [] : skippedNames(l.trimmed),
    };
  });
}

export type DayState = "pending" | "complete" | "partial" | "coverage_reduced" | "paused";

export type LeakToday = {
  day: string;
  state: DayState;
  new: number;
  first_scan: number;
  came_back: number;
  gone: number;
};

export type TodayStrip = { new: number; cameBack: number; gone: number; firstRun: number; checked: number; partial: number; total: number };

export function todayStrip(watches: { today: LeakToday | null; paused: boolean; on: boolean }[]): TodayStrip | null {
  if (!watches.some((w) => w.today)) return null;
  const s: TodayStrip = { new: 0, cameBack: 0, gone: 0, firstRun: 0, checked: 0, partial: 0, total: 0 };
  for (const { today: t, paused, on } of watches) {
    if (t) {
      s.new += t.new;
      s.cameBack += t.came_back;
      s.gone += t.gone;
      s.firstRun += t.first_scan;
    }
    if (paused || !on || t?.state === "paused") continue;
    s.total += 1;
    if (t?.state === "complete") s.checked += 1;
    if (t?.state === "partial" || t?.state === "coverage_reduced") s.partial += 1;
  }
  return s;
}

export function todayLine(s: TodayStrip): string {
  const bits = [`${s.new} new today`, `${s.cameBack} came back`, `${s.gone} gone`, `checked ${s.checked} of ${s.total}`];
  if (s.partial) bits.push(`${s.partial} partial`);
  if (s.firstRun) bits.push(`${s.firstRun} found on first scans`);
  return bits.join(" · ");
}

export type DayMarker = "partial" | "reduced" | "pending" | "paused";

const MARKER: Record<DayState, DayMarker | null> = {
  pending: "pending", complete: null, partial: "partial", coverage_reduced: "reduced", paused: "paused",
};

export const DAY_MARKER_LABEL: Record<DayMarker, string> = {
  partial: "Partial check", reduced: "Reduced", pending: "Checking…", paused: "Paused",
};

export const dayMarker = (today: LeakToday | null): DayMarker | null => (today ? MARKER[today.state] ?? null : null);

export function rosterChips(rows: { account_id: string; today: LeakToday | null }[]): Record<string, string> {
  const chips: Record<string, string> = {};
  for (const r of rows) {
    const m = dayMarker(r.today);
    if (m) chips[r.account_id] = DAY_MARKER_LABEL[m];
  }
  return chips;
}
