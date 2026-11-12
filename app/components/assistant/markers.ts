/**
 * markers — the help bot's live-figure and chat markers (spec D12).
 *
 * The bot never writes a figure itself: it writes `[[data:<metric>|<window>|<scope>]]`
 * and the panel renders a card that reads the figure live, with the asker's own
 * session (a role without stats access gets a 403, shown as such, never $0).
 * `[[chat:@handle]]` opens that fan's chat.
 *
 * Pure: parse, validate, strip. A marker that does not validate is dropped
 * silently; past the first MAX_MARKERS valid ones the rest are dropped too. In
 * a sentence that carries a data marker — kept or dropped — every figure the
 * model wrote anyway (digits, currency) is stripped, so a hallucinated "$1,234"
 * never sits beside the real card nor stands in for a dropped one (the client
 * strip, Fable round 4).
 */

import { addDayStr, periodWindow, presetRange, todayISO, toLocalIso } from "@/lib/dateRange";

export const METRICS = ["revenue", "per_model", "top_spenders", "top_tippers", "unread"] as const;
export const WINDOWS = ["today", "yesterday", "7d", "30d", "this_month", "last_month", "now"] as const;
export const SCOPES = ["this", "all"] as const;
export type Metric = (typeof METRICS)[number];
export type Window = (typeof WINDOWS)[number];
export type MarkerScope = (typeof SCOPES)[number];

export type DataMarker = { kind: "data"; metric: Metric; window: Window; scope: MarkerScope };
export type ChatMarker = { kind: "chat"; handle: string };
export type Marker = DataMarker | ChatMarker;

export const MAX_MARKERS = 2;

const MARKER_RE = /\[\[(data|chat):([^\][\n]*)\]\]/g;
const HANDLE_RE = /^@([A-Za-z0-9_.-]{1,64})$/;

const isOf = <T extends string>(list: readonly T[], v: string): v is T => (list as readonly string[]).includes(v);

/** One marker's body → a marker, or null when it does not validate. `unread`
 *  is a live count (window `now` only); every other metric needs a range. */
export function readMarker(kind: string, body: string): Marker | null {
  if (kind === "chat") {
    const m = HANDLE_RE.exec(body.trim());
    return m ? { kind: "chat", handle: m[1] } : null;
  }
  const parts = body.split("|").map((p) => p.trim());
  if (parts.length !== 3) return null;
  const [metric, window, scope] = parts;
  if (!isOf(METRICS, metric) || !isOf(WINDOWS, window) || !isOf(SCOPES, scope)) return null;
  if ((metric === "unread") !== (window === "now")) return null;
  return { kind: "data", metric, window, scope };
}

/** A placeholder no answer contains, marking where a data marker sat. */
const SLOT = "\u0000";

/** Money and counts: `$1,234.50`, `1.2k`, `40%`, `12`. Not part of a word or
 *  a handle (`@fan99`), and a number of days/hours/weeks/months stays: "the
 *  last 7 days" is the window, not a figure. */
const CURRENCY_RE = /(?:[$€£]\s?\d[\d,]*(?:\.\d+)?(?:\s?[kKmM]\b)?|\b\d[\d,]*(?:\.\d+)?\s?(?:USD|EUR|dollars?)\b)/g;
const NUMBER_RE = /(?<![@\w.,])\d[\d,]*(?:\.\d+)?(?:%|\s?[kK]\b)?(?!\s?(?:days?|hours?|weeks?|months?|years?)\b)(?![\w])/g;

function stripFigures(sentence: string): string {
  return sentence.replace(CURRENCY_RE, "").replace(NUMBER_RE, "");
}

/** Leftover gaps after a strip: double spaces, a space before punctuation,
 *  trailing blanks. A line's leading indent stays (a list item's wrap). */
function tidy(s: string): string {
  return s
    .replace(/(?<=\S)[ \t]{2,}/g, " ")
    .replace(/(?<=\S) +([.,!?;:])/g, "$1")
    .replace(/\(\s*\)/g, "")
    .replace(/[ \t]+$/gm, "")
    .replace(/^ (?=\S)/gm, "");
}

/** The answer with its markers out (figures stripped where a data marker sat)
 *  and the markers to render, in order, at most MAX_MARKERS. */
export function parseMarkers(text: string): { text: string; markers: Marker[] } {
  const markers: Marker[] = [];
  let hasData = false;
  const marked = text.replace(MARKER_RE, (_all, kind: string, body: string) => {
    const m = readMarker(kind, body);
    if (m && markers.length < MAX_MARKERS) markers.push(m);
    if (m?.kind === "chat") return `@${m.handle}`;
    if (kind !== "data") return "";
    // Any data marker, invalid or past the cap too: its sentence loses its figures.
    hasData = true;
    return SLOT;
  });
  if (!hasData) return { text: markers.length || marked !== text ? tidy(marked) : text, markers };
  // Sentences end at . ! ? before a space or the end of a line (so "$1.50"
  // stays whole), and at line ends.
  const out = marked
    .split("\n")
    .map((line) => line.split(/(?<=[.!?])(?=\s)/).map((s) => (s.includes(SLOT) ? stripFigures(s) : s)).join(""))
    .join("\n")
    .split(SLOT)
    .join("");
  return { text: tidy(out), markers };
}

/** A window's `[from, to]` instants in the report zone `tz` (the browser's
 *  when null), the Dashboard's and reports' own cuts. `now` has none. */
export function windowRange(w: Window, tz: string | null): [string, string] | null {
  switch (w) {
    case "today": return periodWindow("today", tz, "monday");
    case "yesterday": return periodWindow("yesterday", tz, "monday");
    case "30d": return periodWindow("last30Days", tz, "monday");
    case "this_month": return periodWindow("month", tz, "monday");
    case "7d": {
      const [from, to] = presetRange("7d", tz);
      return [toLocalIso(from, false, tz)!, toLocalIso(to, true, tz)!];
    }
    case "last_month": {
      const [y, m] = todayISO(tz).split("-").map(Number);
      const first = `${y}-${String(m).padStart(2, "0")}-01`;
      const prev = m === 1 ? `${y - 1}-12-01` : `${y}-${String(m - 1).padStart(2, "0")}-01`;
      return [toLocalIso(prev, false, tz)!, toLocalIso(addDayStr(first, -1), true, tz)!];
    }
    case "now": return null;
  }
}

export const METRIC_LABEL: Record<Metric, string> = {
  revenue: "Revenue",
  per_model: "Revenue by model",
  top_spenders: "Top spenders",
  top_tippers: "Top tippers",
  unread: "Unread chats",
};

export const WINDOW_LABEL: Record<Window, string> = {
  today: "Today",
  yesterday: "Yesterday",
  "7d": "Last 7 days",
  "30d": "Last 30 days",
  this_month: "This month",
  last_month: "Last month",
  now: "Now",
};

/** The stats read a range metric makes: the existing report endpoints, no new
 *  ones. `account` null = every account the session may see (the relay
 *  clamps to them). */
export function metricPath(metric: Exclude<Metric, "unread">, range: [string, string], account: string | null): string {
  const qs = new URLSearchParams({ from: range[0], to: range[1] });
  if (account) qs.set("account_id", account);
  switch (metric) {
    case "revenue": qs.set("group_by", "kind"); return `/admin/stats/revenue?${qs}`;
    case "per_model": return `/admin/stats/per-model?${qs}`;
    case "top_spenders": qs.set("sort", "total"); qs.set("limit", "5"); return `/admin/stats/fan-report?${qs}`;
    case "top_tippers": qs.set("limit", "5"); return `/admin/top-tippers?${qs}`;
  }
}
