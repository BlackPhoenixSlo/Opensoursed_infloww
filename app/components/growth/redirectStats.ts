/** Redirect links' stats (RedirectLinksPanel + RedirectLinkStats): which link's analytics is open and over how many
 *  days (one reducer: together they decide the request), plus the pure shapers the components draw from. */

import type { StatsDays, StatsKeyRow, TrackingLink, TrackingSummary } from "@/hooks/useGrowth";
import { count } from "@/components/growth/linkMetrics";
import { MONTHS } from "@/lib/shiftsTime";

export type { StatsDays } from "@/hooks/useGrowth";
export const RANGES: readonly StatsDays[] = [7, 30, 90];

export interface StatsView { openId: number | null; days: StatsDays }
export const INITIAL_VIEW: StatsView = { openId: null, days: 30 };

export type Action =
  | { type: "toggle"; id: number }
  | { type: "setDays"; days: StatsDays };

export function statsViewReducer(s: StatsView, a: Action): StatsView {
  switch (a.type) {
    case "toggle":
      return { ...s, openId: s.openId === a.id ? null : a.id };
    case "setDays":
      return s.days === a.days ? s : { ...s, days: a.days };
  }
}

/** The analytics read the view asks for; null when nothing is open. */
export function statsRequest(v: StatsView, accountId: string | null, ids: number[]): { linkId: number; days: StatsDays } | null {
  return v.openId != null && accountId && ids.includes(v.openId) ? { linkId: v.openId, days: v.days } : null;
}

// ── labels ──

export const OPENED_IN: Record<string, string> = {
  instagram: "Instagram app", tiktok: "TikTok app", facebook: "Facebook app", threads: "Threads app",
  "": "Browser", bot: "Bots & link previews",
};
export const CAME_FROM: Record<string, string> = {
  instagram: "Instagram", tiktok: "TikTok", facebook: "Facebook", x: "X", reddit: "Reddit", google: "Google",
  youtube: "YouTube", telegram: "Telegram", snapchat: "Snapchat", other: "Other", "": "Direct / unknown",
};

/** "🇩🇪 DE" from an ISO code (its regional-indicator flag); "XX" is "Unknown". */
export function countryLabel(code: string): string {
  if (!/^[A-Z]{2}$/.test(code) || code === "XX") return "Unknown";
  const flag = String.fromCodePoint(...[...code].map((c) => 0x1f1e6 + c.charCodeAt(0) - 65));
  return `${flag} ${code}`;
}

export interface BreakdownRow { key: string; label: string; clicks: number; pct: number }

/** The top `top` rows (as the API sorted them) with labels and whole percents of `total`; the rest folded into
 *  "Other" (into an existing "Other" row when one is shown). Unknown keys keep their key as the label. */
export function breakdownRows(rows: StatsKeyRow[], total: number,
  labels: Record<string, string> | ((key: string) => string), top = 5): BreakdownRow[] {
  const name = (k: string) => (typeof labels === "function" ? labels(k) : labels[k] ?? k);
  const pct = (n: number) => (total > 0 ? Math.round((n / total) * 100) : 0);
  const out: BreakdownRow[] = rows.slice(0, top).map((r) => ({ key: r.key, label: name(r.key), clicks: r.clicks, pct: 0 }));
  const rest = rows.slice(top).reduce((a, r) => a + r.clicks, 0);
  if (rest > 0) {
    const other = out.find((r) => r.label === "Other");
    if (other) other.clicks += rest;
    else out.push({ key: "__rest", label: "Other", clicks: rest, pct: 0 });
  }
  return out.map((r) => ({ ...r, pct: pct(r.clicks) }));
}

/** Whether any click carries a real country (CF-IPCountry only arrives through Cloudflare). */
export function hasCountries(rows: StatsKeyRow[]): boolean {
  return rows.some((r) => r.key !== "XX" && r.clicks > 0);
}

export interface SparkBar { x: number; y: number; w: number; h: number; zero: boolean }
export const SPARK_W = 56;

/** A 56 x `h` sparkline's bars: one slot per value, bars 6px; a zero day a 1px baseline, any click at least 2px. */
export function sparkBars(values: number[], h = 20): SparkBar[] {
  const max = Math.max(0, ...values);
  const slot = SPARK_W / Math.max(1, values.length);
  const w = Math.max(1, Math.min(6, slot - 2));
  return values.map((v, i) => {
    const bh = v > 0 && max > 0 ? Math.max(2, Math.round((v / max) * h)) : 1;
    return { x: i * slot + (slot - w) / 2, y: h - bh, w, h: bh, zero: v <= 0 };
  });
}

export type CardKey = "today" | "d7" | "d30" | "top" | "verified";
export interface SummaryCard {
  key: CardKey;
  title: string;
  /** null → "—" (loading, failed, or no data for this card). */
  value: string | null;
  /** The value's hover title (StatCard's `valueTitle`). */
  sub?: string;
}

/** The gate indicator is shown only when verification is available. */
export function verifiedSummary(s: TrackingSummary | undefined, links: TrackingLink[], available: boolean): number | null {
  return available && links.some((link) => link.bot_check) ? s?.verified_clicks ?? null : null;
}

/** Summary cards from the report range and the visible gate indicator. */
export function summaryCards(s: TrackingSummary | undefined, verifiedClicks: number | null): SummaryCard[] {
  const showGate = verifiedClicks != null;
  const cards: SummaryCard[] = [
    { key: "today", title: "Clicks today", value: s ? count(s.clicks.today) : null },
    { key: "d7", title: "Last 7 days", value: s ? count(s.clicks.d7) : null },
    { key: "d30", title: "Last 30 days", value: s ? count(s.clicks.d30) : null },
    { key: "top", title: "Top link · 30 days", value: s?.top ? s.top.name : null,
      sub: s?.top ? `${count(s.top.clicks)} clicks in the last 30 days` : s ? "No clicks yet" : undefined },
  ];
  if (showGate) cards.push({ key: "verified", title: "Bot check on · 30 days", value: count(verifiedClicks), sub: "clicks passed the bot check" });
  return cards;
}

/** "Nov 1" of a 'YYYY-MM-DD' day (no Date parse: the day is already the report zone's). */
export function dayLabel(day: string): string {
  const [, m, d] = day.split("-").map(Number);
  return `${MONTHS[(m || 1) - 1]} ${d}`;
}
