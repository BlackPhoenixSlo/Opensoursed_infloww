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

const SLOT = "\u0000";

const CURRENCY_RE = /(?:[$€£]\s?\d[\d,]*(?:\.\d+)?(?:\s?[kKmM]\b)?|\b\d[\d,]*(?:\.\d+)?\s?(?:USD|EUR|dollars?)\b)/g;
const NUMBER_RE = /(?<![@\w.,])\d[\d,]*(?:\.\d+)?(?:%|\s?[kK]\b)?(?!\s?(?:days?|hours?|weeks?|months?|years?)\b)(?![\w])/g;

function stripFigures(sentence: string): string {
  return sentence.replace(CURRENCY_RE, "").replace(NUMBER_RE, "");
}

function tidy(s: string): string {
  return s
    .replace(/(?<=\S)[ \t]{2,}/g, " ")
    .replace(/(?<=\S) +([.,!?;:])/g, "$1")
    .replace(/\(\s*\)/g, "")
    .replace(/[ \t]+$/gm, "")
    .replace(/^ (?=\S)/gm, "");
}

export function parseMarkers(text: string): { text: string; markers: Marker[] } {
  const markers: Marker[] = [];
  let hasData = false;
  const marked = text.replace(MARKER_RE, (_all, kind: string, body: string) => {
    const m = readMarker(kind, body);
    if (m && markers.length < MAX_MARKERS) markers.push(m);
    if (m?.kind === "chat") return `@${m.handle}`;
    if (kind !== "data") return "";
    hasData = true;
    return SLOT;
  });
  if (!hasData) return { text: markers.length || marked !== text ? tidy(marked) : text, markers };
  const out = marked
    .split("\n")
    // A sentence with a data marker loses every model-written figure, so a hallucinated "$1,234" never sits beside (or replaces) the real card.
    .map((line) => line.split(/(?<=[.!?])(?=\s)/).map((s) => (s.includes(SLOT) ? stripFigures(s) : s)).join(""))
    .join("\n")
    .split(SLOT)
    .join("");
  return { text: tidy(out), markers };
}

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
