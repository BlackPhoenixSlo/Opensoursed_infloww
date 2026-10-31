/**
 * Creator reports' pure parts: the revenue reads' shapes and sums, the range presets, the day axis and its buckets,
 * the sections' state, the Creator statistics columns, their cells and export rows, and the notes' wording. No React;
 * CompetitorReports.tsx and its parts read them, and DashboardHeader.tsx reads `netMissingNote` for its Net switch.
 */

import { type Gran, fmtDollars } from "@/components/stats/chart";
import type { PerModelRow } from "@/hooks/useStats";
import { presetRange, todayISO } from "@/lib/dateRange";
import { fmtPrice, fmtReplyTime } from "@/lib/format";
import { type Cell, mapLimit, usd } from "@/lib/reportExport";

/** `net_cents` (OnlyFans' own post-fee figure, VAT not deducted), `net_missing_count` (the rows with no net yet,
 *  which `net_cents` leaves out) and OnlyFans' own `fee_cents` and `vat_cents` are there when the read asks for them
 *  (`include_net=true`). */
export interface RevKindRow {
  kind: string | null; total_cents: number; count: number; net_cents?: number; net_missing_count?: number;
  fee_cents?: number; vat_cents?: number;
}
/** `by_kind` is there when the day read asks for it (`by_kind=true`): that day's kinds. */
interface RevRow extends RevKindRow {
  day: string | null; by_kind?: RevKindRow[];
  /** `group_by=hour_of_week`'s slot: ISO weekday (1 = Monday) and hour in the report zone. */
  weekday?: number; hour?: number;
}
/** `history_missing_days`: Creator-days before a Creator was added with no OnlyFans figure (service/stats.py revenue),
 *  so the window's sum is not its earnings and a growth against it is "-". */
export interface RevResp { rows: RevRow[]; history_missing_days?: number }
/** Whether a window's reads answered and each one's history is whole: else a growth against it is "-". */
export const wholeHistory = (qs: readonly { isSuccess: boolean; data?: RevResp }[]) =>
  qs.length > 0 && qs.every((q) => q.isSuccess && !(q.data?.history_missing_days ?? 0));
/** A revenue row's money: gross, or with "Show net earnings" on OnlyFans' own net. Never a ratio of gross. */
export type Money = (r: RevKindRow) => number;
export const grossOf: Money = (r) => r.total_cents;
export const netOf: Money = (r) => r.net_cents ?? 0;

/** #65: the granularity tabs. Hour reads the relay's local hours (`group_by=hour`). */
export const GRANS: readonly { key: Gran; label: string }[] = [
  { key: "hour", label: "Hour" }, { key: "day", label: "Day" }, { key: "week", label: "Week" }, { key: "month", label: "Month" },
];
/** #28: a disabled choice's tooltip. */
export const GRAN_LIMIT: Record<Gran, string> = {
  hour: "Date range must be 2 days or less for this option",
  day: "Date range must be 31 days or less for this option",
  week: "Date range must be between 14 to 365 days for this option",
  month: "Date range must be more than 62 days for this option",
};
/** The range's local hours, `YYYY-MM-DDTHH:00` as the relay's `group_by=hour` keys them; none past Hour's 2 days. */
export function hoursOf(days: string[]): string[] {
  if (days.length > 2) return [];
  return days.flatMap((d) => Array.from({ length: 24 }, (_, h) => `${d}T${String(h).padStart(2, "0")}:00`));
}

/** The sections' state: the reads answered with at least one Creator in the selection, or not. */
export type View = "ready" | "loading" | "error" | "empty";
/** A section's state from its reads: any failed first, then any pending, then whether it has a row to show. */
export function viewOf(reads: readonly { isError: boolean; isPending: boolean }[], hasRows: boolean): View {
  return reads.some((q) => q.isError) ? "error" : reads.some((q) => q.isPending) ? "loading" : hasRows ? "ready" : "empty";
}
/* The wording of a section still loading or failed. The capture shows a pulser there, so these are ours, labelled
 * (ticket 60). With no Creator the bundle prints its zeros and blank charts, and so do we, with no wording. */
export type Wait = "loading" | "error";
export const isWait = (v: View): v is Wait => v === "loading" || v === "error";
export const SUMMARY_TEXT: Record<Wait, string> = { loading: "Loading…", error: "Earnings data unavailable" };
export const TREND_TEXT: Record<Wait, string> = { loading: "Loading earnings trend…", error: "Earnings trend unavailable" };
export const CHANNEL_TEXT: Record<Wait, string> = { loading: "", error: "Earnings by channel unavailable" };
/** Ours: the Creator performance list's wording with no Creator in the Creator filter's pick. */
export const NO_CREATORS = "No creators in this selection";
/** The bundle's own tab keys (index.9f50f370.js @13634517, `E==="performance"`), which `?tab=` carries. */
export type Tab = "overview" | "performance";
export const TABS: readonly { key: Tab; label: string }[] = [
  { key: "overview", label: "Overview" },
  { key: "performance", label: "Creator performance" },
];
export const isTab = (v: string): v is Tab => TABS.some((t) => t.key === v);

/** OnlyFans' referrals read failed for `n` Creators (no session, OnlyFans down), or the whole read did (`null`). */
export function referralsUnavailableNote(n: number | null): string {
  const who = n === null ? "these creators" : n === 1 ? "1 creator" : `${n} creators`;
  return `Referrals from OnlyFans are unavailable for ${who}, counted as $0.00.`;
}

/** "1 sale … has … it" / "3 sales … have … them": the sales with no net figure from OnlyFans yet. `noun` is what
 *  leaves them out: the Dashboard's "Net" switch (one, "leaves") or Creator reports' "net earnings" (many, "leave"). */
export function netMissingNote(n: number, noun: "Net" | "net earnings"): string {
  const verb = noun === "Net" ? "leaves" : "leave";
  return n === 1
    ? `1 sale in this period has no net figure from OnlyFans yet, so ${noun} ${verb} it out.`
    : `${n} sales in this period have no net figure from OnlyFans yet, so ${noun} ${verb} them out.`;
}

/** A Creator's name as the reports show it: its display name, else its account id. */
export const creatorName = (m: PerModelRow): string => m.display_name || m.account_id;

/* ── Creator statistics columns ── */

/** What a cell reads besides its row: the window's hours (#121), the Agency's total earnings (#123), and whether
 *  "Show net earnings" is on. */
export interface ColCtx { hours: number; agencyCents: number; net: boolean }
export interface StatCol {
  key: string;
  title: string;
  /** The capture's column width, kept as the header's minimum. */
  width: number;
  /** Shown by default (`ColumnFieldsDefault`). */
  show: boolean;
  /** The header carries the "UTC+00:00" chip (#98). */
  utc?: boolean;
  /** A "usd" average (per hour, per spender, LTV, ARPU): it keeps its cents, as Infloww prints it. */
  avg?: true;
  /** Ours, not the capture's: a column the old table had, kept behind Custom metrics (ADR-0003). */
  extra?: boolean;
  /** `dur`: seconds, shown as "3m 05s". */
  fmt?: "usd" | "int" | "pct" | "dur";
  /** The figure, `null` for "-" (#147). A column with no `v` has no relay field: Not wired. */
  v?: (m: PerModelRow, c: ColCtx) => number | null;
  /** The figure while "Show net earnings" is on. A money column without one has no net read (the per-model read
   *  gives net only as a per-Creator total), so it is Not wired then; any other column keeps `v`. */
  netV?: (m: PerModelRow, c: ColCtx) => number | null;
}
const subsOf = (m: PerModelRow) => (m.revenue_by_kind?.subscription ?? 0) + (m.revenue_by_kind?.rebill ?? 0);
/** Messages and tips, the numerator of #117 and #133 (the bundle's column descriptions, index.9f50f370.js near
 *  @13245838). The per-model read files stream tips and PPVs under tips and messages. */
const engagedOf = (m: PerModelRow) => (m.revenue_by_kind?.ppv ?? 0) + (m.revenue_by_kind?.tip ?? 0);
/** #112 to #146: every column after "Creator" (#111, always shown), in the capture's order, then ours. Streams has
 *  no read of its own (the per-model read files stream sales under tips and messages); the rest without `v` need OF
 *  statistics (ranking, following, guest / user visitors, total and expired fans, subscription length) or
 *  earnings per fan no relay read carries. */
export const STAT_COLS: readonly StatCol[] = [
  { key: "totalSubscriptionsEarnings", title: "Total subscription earnings", width: 270, show: true, fmt: "usd", v: subsOf },
  { key: "subscriptionsEarnings", title: "Subscription earnings", width: 240, show: false, fmt: "usd", v: (m) => m.revenue_by_kind?.subscription ?? 0 },
  { key: "recurringSubscriptionEarnings", title: "Recurring subscription earnings", width: 305, show: false, fmt: "usd", v: (m) => m.revenue_by_kind?.rebill ?? 0 },
  { key: "tips", title: "Tips", width: 112, show: true, fmt: "usd", v: (m) => m.revenue_by_kind?.tip ?? 0 },
  { key: "message", title: "Message", width: 145, show: true, fmt: "usd", v: (m) => m.revenue_by_kind?.ppv ?? 0 },
  { key: "engagementEarningsRatio", title: "Engagement earnings ratio", width: 280, show: true, fmt: "pct", v: (m) => (subsOf(m) > 0 ? (100 * engagedOf(m)) / subsOf(m) : null) },
  { key: "streams", title: "Streams", width: 140, show: false },
  { key: "posts", title: "Posts", width: 120, show: false, fmt: "usd", v: (m) => m.revenue_by_kind?.post ?? 0 },
  { key: "totalEarnings", title: "Total earnings", width: 240, show: true, fmt: "usd", v: (m) => m.total_revenue_cents, netV: (m) => m.total_net_revenue_cents },
  { key: "avgHourlyEarnings", title: "Avg hourly earnings", width: 220, show: false, fmt: "usd", avg: true, v: (m, c) => (c.hours > 0 ? m.total_revenue_cents / c.hours : null),
    netV: (m, c) => (c.hours > 0 ? m.total_net_revenue_cents / c.hours : null) },
  // The window's chargebacks and refunds, dated by their sale (the bundle dates a refund by its credit date).
  { key: "refunds", title: "Refunds", width: 132, show: false, fmt: "usd", v: (m) => m.refunded_cents ?? 0,
    netV: (m) => m.refunded_net_cents ?? 0 },
  { key: "contributionPercent", title: "Contribution %", width: 190, show: true, fmt: "pct", v: (m, c) => (c.agencyCents > 0 ? (100 * m.total_revenue_cents) / c.agencyCents : null),
    netV: (m, c) => (c.agencyCents > 0 ? (100 * m.total_net_revenue_cents) / c.agencyCents : null) },
  { key: "ofRanking", title: "OF ranking", width: 230, show: true, utc: true },
  { key: "following", title: "Following", width: 210, show: false, utc: true },
  { key: "fansWithRenewOn", title: "Fans with renew on", width: 285, show: true, utc: true, fmt: "int", v: (m) => m.of_renew_on },
  { key: "renewPercent", title: "Renew on %", width: 240, show: false, utc: true, fmt: "pct", v: (m) => m.of_renew_on_pct },
  { key: "profileVisitors", title: "Profile visitors", width: 250, show: true, utc: true, fmt: "int", v: (m) => m.of_visitors },
  { key: "guestProfileVisitors", title: "Guest profile visitors", width: 295, show: false, utc: true },
  { key: "userProfileVisitors", title: "User profile visitors", width: 285, show: false, utc: true },
  { key: "newSubscribers", title: "New subscribers", width: 270, show: true, utc: true, fmt: "int", v: (m) => m.new_subs_count },
  { key: "subscriberRenewals", title: "Subscriber renewals", width: 300, show: true, utc: true, fmt: "int", v: (m) => m.of_renewals },
  { key: "newSubscribersLtv", title: "New subscriber LTV", width: 300, show: true, fmt: "usd", avg: true, v: (m) => (m.new_subs_count > 0 ? engagedOf(m) / m.new_subs_count : null) },
  { key: "newSubscriberConversion", title: "New subscriber conversion", width: 340, show: true, utc: true, fmt: "pct", v: (m) => m.of_new_sub_conversion_pct },
  { key: "activeFans", title: "Active fans", width: 230, show: true, utc: true, fmt: "int", v: (m) => m.active_subs_count },
  { key: "changeInExpiredFanCount", title: "Change in expired fan count", width: 345, show: false, utc: true },
  { key: "numberOfSpender", title: "Number of spenders", width: 260, show: true, fmt: "int", v: (m) => m.spenders_count },
  { key: "avgSpendPerSpender", title: "Avg spend per spender", width: 263, show: true, fmt: "usd", avg: true, v: (m) => m.avg_spend_per_spender_cents },
  { key: "avgSpendPerTransaction", title: "Avg spend per transaction", width: 280, show: false, fmt: "usd", avg: true, v: (m) => m.avg_spend_per_transaction_cents },
  { key: "totalNumberOfFans", title: "Total number of fans", width: 300, show: false, utc: true },
  { key: "avgEarningsPerFan", title: "Avg earnings per fan", width: 225, show: true },
  { key: "avgSubscriptionLength", title: "Avg subscription length", width: 315, show: false, utc: true },
  // #143 to #146: the Employees' own sends, no mass or automated message (service/msg_stats.py).
  { key: "replyTime", title: "Reply time", width: 190, show: true, fmt: "dur", v: (m) => m.avg_reply_seconds ?? null },
  { key: "fansChatted", title: "Fans chatted", width: 185, show: true, fmt: "int", v: (m) => m.fans_chatted ?? 0 },
  { key: "messagesSent", title: "Messages sent", width: 190, show: true, fmt: "int", v: (m) => m.messages_sent },
  { key: "ppvsSent", title: "PPVs sent", width: 170, show: true, fmt: "int", v: (m) => m.ppvs_sent ?? 0 },
  // Ours: the old table's columns the capture lacks.
  { key: "pending", title: "Pending revenue", width: 200, show: false, extra: true, fmt: "usd", v: (m) => m.pending_revenue_cents ?? 0 },
  { key: "ppvConversions", title: "PPV conversions", width: 200, show: false, extra: true, fmt: "int", v: (m) => m.ppv_conversions },
  { key: "ltv", title: "LTV", width: 140, show: false, extra: true, fmt: "usd", avg: true, v: (m) => m.ltv_cents },
  { key: "arpu", title: "ARPU", width: 140, show: false, extra: true, fmt: "usd", avg: true, v: (m) => m.arpu_cents },
];
export const DEFAULT_COLS = (): Set<string> => new Set(STAT_COLS.filter((c) => c.show).map((c) => c.key));
/** The column's read in the current basis; none when it has no relay field, or no net read while net is on. */
export function readOf(col: StatCol, ctx: ColCtx): StatCol["v"] {
  if (!ctx.net) return col.v;
  return col.netV ?? (col.fmt === "usd" ? undefined : col.v);
}
/** A cell as shown: "-" when the read has nothing (#147). */
export function cellText(col: StatCol, m: PerModelRow, ctx: ColCtx): string {
  const n = readOf(col, ctx)?.(m, ctx) ?? null;
  if (n === null) return "-";
  // A total in whole dollars, as on the dashboard; an average keeps its cents, as Infloww prints it.
  if (col.fmt === "usd") return col.avg ? fmtPrice(n) : fmtDollars(n);
  if (col.fmt === "pct") return `${n.toFixed(2)}%`;
  if (col.fmt === "dur") return fmtReplyTime(n);
  return n.toLocaleString("en-US");
}
/** A cell as exported: dollars and percentages to two decimals, as numbers; empty when the read has nothing. */
export function cellCsv(col: StatCol, m: PerModelRow, ctx: ColCtx): Cell {
  const n = readOf(col, ctx)?.(m, ctx) ?? null;
  if (n === null) return "";
  if (col.fmt === "usd") return usd(n);
  if (col.fmt === "pct") return Math.round(n * 100) / 100;
  if (col.fmt === "dur") return fmtReplyTime(n);
  return n;
}

/* Days are the report range's YYYY-MM-DD strings, already in the report time zone, which is also the zone the
 * relay's `group_by=day` buckets in; they are handled as UTC calendar dates so no browser zone shifts them. */
function utcDate(day: string): Date { return new Date(`${day}T00:00:00Z`); }
/** Every day from `from` through `to`; none while either side is unset. */
export function daysFrom(from: string | null, to: string | null): string[] {
  if (!from || !to) return [];
  const out: string[] = [];
  const end = utcDate(to).getTime();
  // Ten years of days at most, so a malformed range can never spin.
  for (let t = utcDate(from).getTime(); t <= end && out.length < 3660; t += 86_400_000) {
    out.push(new Date(t).toISOString().slice(0, 10));
  }
  return out;
}

/** A range preset: one of `datePresets`' keys, "custom" for days typed in. */
export type RangeKey = string;
/** #21: the default range, the bundle's `defaultSelectDate`. */
export const DEFAULT_RANGE: RangeKey = "last7";
/** #23, #24: the bundle's presets in its order, their days in `tz`. "Custom" carries the default range as its value
 *  (the bundle's `defineSelectDateArr`). Where the bundle's Last ones and its year end yesterday, ours run through
 *  today on the shared `presetRange` (the other reports' "Last N days", so one label is one window everywhere, and
 *  today's pending sales show); this month runs from its first day to today, and the five months before are whole. */
export function datePresets(tz: string | null): { key: RangeKey; label: string; days: [string, string] }[] {
  const today = todayISO(tz);
  const [y, m] = today.split("-").map(Number);
  const iso = (d: Date) => d.toISOString().slice(0, 10);
  const monthLabel = (back: number) =>
    new Date(Date.UTC(y, m - 1 - back, 1)).toLocaleString("en-US", { timeZone: "UTC", month: "long" });
  return [
    { key: "custom", label: "Custom", days: presetRange("7d", tz) },
    { key: "last7", label: "Last 7 days", days: presetRange("7d", tz) },
    { key: "last30", label: "Last 30 days", days: presetRange("30d", tz) },
    { key: "last90", label: "Last 90 days", days: presetRange("90d", tz) },
    { key: "last365", label: "Last 365 days", days: presetRange("365d", tz) },
    { key: "year", label: String(y), days: [`${y}-01-01`, today] },
    { key: "month", label: monthLabel(0), days: [`${today.slice(0, 7)}-01`, today] },
    ...[1, 2, 3, 4, 5].map((b) => ({
      key: `month-${b}`,
      label: monthLabel(b),
      days: [iso(new Date(Date.UTC(y, m - 1 - b, 1))), iso(new Date(Date.UTC(y, m - b, 0)))] as [string, string],
    })),
  ];
}

/** #21: the range picker's `MMM D, YYYY`. */
export function fmtRangeLabel(day: string | null): string {
  if (!day) return "…";
  return utcDate(day).toLocaleDateString("en-US", { timeZone: "UTC", month: "short", day: "numeric", year: "numeric" });
}
export function fmtBucketLabel(day: string, p: Gran): string {
  if (p === "hour") {
    // "Oct 14 3 PM": the slot's local wall clock, read as UTC so no browser zone shifts it.
    const t = new Date(`${day}:00Z`);
    const h = t.getUTCHours();
    return `${t.toLocaleString("en-US", { timeZone: "UTC", month: "short" })} ${t.getUTCDate()} ${h % 12 || 12} ${h < 12 ? "AM" : "PM"}`;
  }
  const d = utcDate(day);
  if (p === "month") return d.toLocaleString("en-US", { timeZone: "UTC", month: "short", year: "2-digit" });
  if (p === "week")  return `${d.toLocaleString("en-US", { timeZone: "UTC", month: "short" })} ${d.getUTCDate()}`;
  return d.toLocaleString("en-US", { timeZone: "UTC", month: "short", day: "numeric" });
}

export interface Point { label: string; value: number }
/** The days' values rolled into `p`: each day; seven days at a time from the range's first day; calendar months. With
 *  `hour` the slots are hours (`hoursOf`), each its own bucket. */
export function rollUp(days: string[], values: number[], p: Gran): Point[] {
  if (p === "day" || p === "hour") return days.map((d, i) => ({ label: fmtBucketLabel(d, p), value: values[i] ?? 0 }));
  const out: Point[] = [];
  days.forEach((d, i) => {
    const starts = p === "week" ? i % 7 === 0 : i === 0 || d.slice(0, 7) !== days[i - 1].slice(0, 7);
    if (starts) out.push({ label: fmtBucketLabel(d, p), value: 0 });
    out[out.length - 1].value += values[i] ?? 0;
  });
  return out;
}

/* ── kind bucketing ── */

export type Bucket = "subscriptions" | "tips" | "posts" | "messages" | "streams" | "referrals" | "other";
export type Chan = Exclude<Bucket, "other">;
const noBuckets = (): Record<Bucket, number> =>
  ({ subscriptions: 0, tips: 0, posts: 0, messages: 0, streams: 0, referrals: 0, other: 0 });
/** Every channel's money, summed. */
export const totalOf = (b: Record<Bucket, number>): number => Object.values(b).reduce((a, c) => a + c, 0);
/** The kind reads' rows' money summed by channel. */
export function sumKinds(qs: readonly { data?: RevResp }[], money: Money): Record<Bucket, number> {
  const out = noBuckets();
  for (const q of qs) for (const r of q.data?.rows ?? []) out[bucketOf(r.kind)] += money(r);
  return out;
}
/** The day reads' rows (`by_kind=true`) as each day's money and each channel's, over `days`. */
export function dailyOf(qs: readonly { data?: RevResp }[], days: string[], money: Money) {
  const total = new Map<string, number>();
  const byChan = new Map<string, Record<Bucket, number>>();
  for (const q of qs) {
    for (const r of q.data?.rows ?? []) {
      if (!r.day) continue;
      total.set(r.day, (total.get(r.day) ?? 0) + money(r));
      const c = byChan.get(r.day) ?? noBuckets();
      for (const k of r.by_kind ?? []) c[bucketOf(k.kind)] += money(k);
      byChan.set(r.day, c);
    }
  }
  return {
    total: days.map((d) => total.get(d) ?? 0),
    byChan: (key: Chan) => days.map((d) => byChan.get(d)?.[key] ?? 0),
  };
}
/** #75: the channels, in the capture's order, and #81: their colours on the lines, slices and legend dots. No
 *  transaction kind carries referral earnings: Referrals is OnlyFans' own read, as `referralsAsRevenue`'s rows. */
export const CHANNELS: readonly { key: Chan; label: string; color: string }[] = [
  { key: "subscriptions", label: "Subscription", color: "#1b9bd2" },
  { key: "tips",          label: "Tips",         color: "#58a547" },
  { key: "posts",         label: "Posts",        color: "#d96a42" },
  { key: "messages",      label: "Messages",     color: "#ac72d2" },
  { key: "referrals",     label: "Referrals",    color: "#d5638d" },
  { key: "streams",       label: "Streams",      color: "#ac8d00" },
];
/** The Inventory's breakdown rows, which the capture lacks (its Notes): ours, in the "Earnings ledger". Gross
 *  earnings has a read, and Platform fee, VAT collected and Net earnings too while "Show net earnings" is on (the net
 *  read carries OnlyFans' own fee and VAT). */
export const LEDGER_ROWS = ["Gross earnings", "Platform fee", "VAT collected", "Chargeback ratio", "Refunds", "Net earnings"] as const;

export function bucketOf(kind: string | null): Bucket {
  if (!kind) return "other";
  if (kind === "subscription" || kind === "rebill") return "subscriptions";
  // Paid feed-post sales land as `ppv_post` (and post-tips as `tip_post`);
  // both are "Posts" in OF's vocab. Must precede the generic ppv→messages
  // catch-all below, or `ppv_post` gets swallowed into Messages.
  if (kind === "tip_post" || kind === "ppv_post") return "posts";
  if (kind === "tip_stream" || kind === "ppv_stream") return "streams";
  if (kind === "tip") return "tips";
  if (kind === "referral") return "referrals"; // `referralsAsRevenue`'s rows
  if (kind.startsWith("ppv")) return "messages"; // ppv (WS pump) + ppv_message
  return "other";
}

/** Creator statistics columns as rows: a header of their titles, then a row per Creator. */
export function creatorRows(cols: readonly StatCol[], creators: PerModelRow[], ctx: ColCtx): Cell[][] {
  return [
    ["Creator", ...cols.map((c) => c.title)],
    ...creators.map((m) => [creatorName(m), ...cols.map((c) => cellCsv(c, m, ctx))]),
  ];
}

/** The export's "Display by day" (Infloww's, 05-analytics M22): a row per Creator per day of the range, its
 *  earnings and each channel's, from one revenue read per Creator (four at a time). Pending sales count, as
 *  every earnings figure here. */
export async function creatorDayRows(creators: PerModelRow[], days: string[], net: boolean,
  read: (accountId: string) => Promise<RevResp>): Promise<Cell[][]> {
  // Referrals are OnlyFans' own read, not on the revenue read: left out rather than written as $0.
  const chans = CHANNELS.filter((c) => c.key !== "referrals");
  const reads = await mapLimit(creators, 4, (m) => read(m.account_id));
  const rows: Cell[][] = [["Creator", "Day", "Total earnings", ...chans.map((c) => c.label)]];
  creators.forEach((m, i) => {
    const d = dailyOf([{ data: reads[i] }], days, net ? netOf : grossOf);
    const byChan = chans.map((c) => d.byChan(c.key));
    days.forEach((day, j) => rows.push([creatorName(m), day, usd(d.total[j]), ...byChan.map((v) => usd(v[j]))]));
  });
  return rows;
}
