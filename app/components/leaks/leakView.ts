import { parseUtc } from "@/lib/format";

import type { IdentityStart } from "./IdentityForm";
import type { LeakLane, LeakWeek } from "./leakCoverage";
import type { Removal, RemovalOffer } from "./removalOffer";

export const NOT_TRACKED = "Not tracked";
export const NOT_CHECKED = "Not checked yet";
export const NOT_REACHABLE = "Not reachable";
export const TRACKING_ON = "Tracking on";
export const PAUSED = "Paused";

export type LeakCounts = {
  live: number;
  cached: number;
  gone: number;
  listed: number;
  not_checked: number;
  new_today?: number;
  found_on_first_scan: number;
  came_back_30d: number;
};

export type LeakRosterRow = {
  account_id: string;
  name: string;
  platform: string;
  username: string;
  display_name: string;
  on: boolean;
  synced: boolean;
  reachable: boolean;
  seeded: boolean;
  paused: boolean;
  paused_since: string | null;
  last_checked_at: string | null;
  next_check_at: string | null;
  counts: LeakCounts | null;
  this_week: LeakWeek | null;
};

export type LeakPill = "live" | "cached" | "gone" | "listed" | "not_checked";

export type LeakEvent = { at: string; type: string; data: Record<string, unknown> };

export type Leak = {
  leak_id: string;
  url: string;
  leak_site: string;
  kind: string;
  sources: string[];
  title: string;
  pill: LeakPill;
  came_back: boolean;
  found_on_first_scan: boolean;
  first_seen_at: string;
  last_up_at: string | null;
  last_probe_at: string | null;
  origin_status: string | null;
  account_id?: string;
  events?: LeakEvent[];
  preview: LeakPreview | null;
};

export type LeakPreview = { vertical: "images" | "videos"; seen_at: string };

export type LeakPage = { leaks: Leak[] | null; next_cursor: string | null; stale: boolean };

export type LeakRemovalPage = LeakPage & { removal: Removal | null; offer: RemovalOffer | null };

export type LeakWatchRead = LeakRemovalPage & {
  tracked: boolean;
  identity: (IdentityStart & { platform: string; on: boolean }) | null;
  suggested: IdentityStart | null;
  synced: boolean;
  lanes: LeakLane[] | null;
  this_week: LeakWeek | null;
  next_refresh_at: string | null;
  last_checked_at: string | null;
};

export type LeakRoster = {
  rows: LeakRosterRow[];
  untracked: { account_id: string; name: string }[];
  stale: boolean;
  fetched_at: string | null;
};

type Local = { day: number; year: number; date: string; hour: number; time: string };

function local(d: Date, tz: string): Local {
  const parts = Object.fromEntries(new Intl.DateTimeFormat("en-GB", {
    timeZone: tz, year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", hourCycle: "h23",
  }).formatToParts(d).map((p) => [p.type, p.value]));
  const ymd = new Intl.DateTimeFormat("en-CA", { timeZone: tz, year: "numeric", month: "2-digit", day: "2-digit" }).format(d);
  const [y, m, dd] = ymd.split("-").map(Number);
  return {
    day: Date.UTC(y, m - 1, dd) / 86_400_000,
    year: y,
    date: `${parts.day} ${parts.month}`,
    hour: Number(parts.hour),
    time: `${parts.hour}:${parts.minute}`,
  };
}

function at(iso: string, now: Date, tz: string): { t: Local; n: Local; diff: number } | null {
  const d = parseUtc(iso);
  if (!d) return null;
  const t = local(d, tz);
  const n = local(now, tz);
  return { t, n, diff: t.day - n.day };
}

const dated = (t: Local, n: Local) => (t.year === n.year ? t.date : `${t.date} ${t.year}`);

export function dayLabel(iso: string, now: Date, tz: string): string | null {
  const a = at(iso, now, tz);
  return a && dated(a.t, a.n);
}

export function when(iso: string, now: Date, tz: string): string | null {
  const a = at(iso, now, tz);
  if (!a) return null;
  const { t, n, diff } = a;
  if (diff === 0) return `Today ${t.time}`;
  if (diff === -1) return `Yesterday ${t.time}`;
  return `${dated(t, n)} ${t.time}`;
}

export function nextCheck(iso: string, now: Date, tz: string): string | null {
  const a = at(iso, now, tz);
  if (!a) return null;
  const { t, n, diff } = a;
  if ((diff === 0 && t.hour >= 18) || (diff === 1 && t.hour < 12)) return "Next check tonight";
  if (diff === 0) return `Next check today ${t.time}`;
  if (diff === 1) return `Next check tomorrow ${t.time}`;
  return `Next check ${dated(t, n)} ${t.time}`;
}

export function pausedLabel(row: Pick<LeakRosterRow, "on" | "paused" | "paused_since">, now: Date, tz: string): string | null {
  if (row.on && !row.paused) return null;
  const since = row.paused_since && dayLabel(row.paused_since, now, tz);
  return since ? `Paused since ${since}` : PAUSED;
}

export function entryNote(row: LeakRosterRow, now: Date, tz: string): string {
  if (!row.reachable) return NOT_REACHABLE;
  const paused = pausedLabel(row, now, tz);
  if (paused) return paused;
  const c = row.counts;
  if (!row.seeded || !c) return NOT_CHECKED;
  const total = c.live + c.cached + c.gone + c.listed + c.not_checked;
  const fresh = row.this_week?.new ?? 0;
  if (fresh === 0 && c.found_on_first_scan === total) return `Found on first scan · ${c.found_on_first_scan}`;
  return fresh ? `${c.live} up now · ${fresh} new this week` : `${c.live} up now`;
}

export function rosterNotes(roster: LeakRoster, now: Date, tz: string): Record<string, string> {
  const notes: Record<string, string> = {};
  for (const r of roster.rows) {
    const note = entryNote(r, now, tz);
    const checked = roster.stale && r.reachable && r.last_checked_at ? when(r.last_checked_at, now, tz) : null;
    notes[r.account_id] = checked ? `${note} · last checked ${checked}` : note;
  }
  for (const u of roster.untracked) notes[u.account_id] = NOT_TRACKED;
  return notes;
}

export function untrack(roster: LeakRoster, accountId: string): LeakRoster {
  const gone = roster.rows.find((r) => r.account_id === accountId);
  if (!gone) return roster;
  return {
    ...roster,
    rows: roster.rows.filter((r) => r !== gone),
    untracked: [...roster.untracked, { account_id: accountId, name: gone.name }],
  };
}

export const withoutCreator = (page: LeakPage, accountId: string): LeakPage =>
  page.leaks ? { ...page, leaks: page.leaks.filter((l) => l.account_id !== accountId) } : page;

export const withSnooze = (page: LeakRemovalPage, snoozedUntil: string): LeakRemovalPage =>
  page.removal && page.offer
    ? { ...page, removal: { ...page.removal, offer_snoozed_until: snoozedUntil }, offer: null }
    : page;

export const viewerZone = () => Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";

export const PILL_LABEL: Record<LeakPill, string> = {
  live: "Live", cached: "Cached", gone: "Gone", listed: "Listed", not_checked: NOT_CHECKED,
};

export const LEGEND: [LeakPill, string][] = [
  ["live", "The page loads and the Leak is up."],
  ["cached", "Gone from the site, but Google still shows it."],
  ["gone", "Gone from the site and not seen in Google."],
  ["listed", "A Mega, Telegram or file-host link: listed, never opened."],
  ["not_checked", "Found, but the daily check has not opened it yet."],
];

export const KIND_LABEL: Record<string, string> = {
  page: "Page", mega: "Mega", telegram: "Telegram", file_host: "File host", media: "Image or video",
};

const SOURCE_LABEL: Record<string, string> = {
  google_web: "Google", google_images: "Google Images", google_videos: "Google Videos", site_search: "a site search",
  mega_index: "the Mega index",
};

export function seenNote(leak: Leak, now: Date, tz: string): string {
  const day = dayLabel(leak.first_seen_at, now, tz) ?? leak.first_seen_at;
  if (leak.found_on_first_scan) return `Found on first scan · ${day}`;
  const seen = parseUtc(leak.first_seen_at);
  if (seen && seen.toISOString().slice(0, 10) === now.toISOString().slice(0, 10)) return "New today";
  return `First seen ${day}`;
}

function eventText(e: LeakEvent, foundAt: Set<string>): string | null {
  if (e.type === "seen") {
    if (e.data.first_scan === true) return "Found on first scan";
    const source = typeof e.data.source === "string" ? SOURCE_LABEL[e.data.source] : undefined;
    return source ? `Found via ${source}` : "Found";
  }
  if (e.type === "google_seen") {
    const visible = "visible" in e.data ? e.data.visible : true;
    if (visible === false) return "Not seen in Google";
    return visible === true && !foundAt.has(e.at) ? "Seen in Google" : null;
  }
  if (e.type === "status" && e.data.to === "live") return e.data.from === "gone" ? "Came back" : "Up";
  if (e.type === "status" && e.data.to === "gone") return "Gone";
  return null;
}

export function timeline(events: LeakEvent[], now: Date, tz: string, max = 4): string[] {
  const foundAt = new Set(events.filter((e) => e.type === "seen").map((e) => e.at));
  const out: string[] = [];
  for (const e of events) {
    const text = eventText(e, foundAt);
    const day = text && dayLabel(e.at, now, tz);
    if (day) out.push(`${day} ${text}`);
  }
  return out.slice(-max);
}

export type HeaderFacts = {
  counts: [string, string, string | null][] | null;
  tracking: string;
  checked: string;
};

export function headerFacts(row: LeakRosterRow, now: Date, tz: string): HeaderFacts {
  const c = row.seeded ? row.counts : null;
  const tracking = pausedLabel(row, now, tz) ?? TRACKING_ON;
  const last = row.last_checked_at && when(row.last_checked_at, now, tz);
  const next = row.next_check_at && nextCheck(row.next_check_at, now, tz);
  const checked = !row.reachable ? NOT_REACHABLE : last ? `Last checked ${last}` : next || NOT_CHECKED;
  const counts: HeaderFacts["counts"] = c && [
    ["Up now", String(c.live), c.cached ? `${c.cached} cached` : null],
    ["Gone", String(c.gone), null],
    ["Listed", String(c.listed), null],
  ];
  if (counts && row.this_week) counts.push(["New this week", String(row.this_week.new), null]);
  return { counts, tracking, checked };
}
