import { type Gran, fmtDollars } from "@/components/stats/chart";
import { referralsGap, type ReferralsResp } from "@/hooks/useReferrals";
import type { PerModelRow } from "@/hooks/useStats";
import { presetRange, todayISO } from "@/lib/dateRange";
import { fmtPrice, fmtReplyTime } from "@/lib/format";
import { type Cell, mapLimit, usd } from "@/lib/reportExport";

export interface RevKindRow {
  kind: string | null; total_cents: number; count: number; net_cents?: number; net_missing_count?: number;
  fee_cents?: number; vat_cents?: number;
}
interface RevRow extends RevKindRow {
  day: string | null; by_kind?: RevKindRow[];
  weekday?: number; hour?: number;
}
// Creator-days before a Creator was added have no OnlyFans figure: the window sum is not its earnings.
export interface RevResp { rows: RevRow[]; history_missing_days?: number }
export const wholeHistory = (qs: readonly { isSuccess: boolean; data?: RevResp }[]) =>
  qs.length > 0 && qs.every((q) => q.isSuccess && !(q.data?.history_missing_days ?? 0));
export type Money = (r: RevKindRow) => number;
export const grossOf: Money = (r) => r.total_cents;
export const netOf: Money = (r) => r.net_cents ?? 0;

export const GRANS: readonly { key: Gran; label: string }[] = [
  { key: "hour", label: "Hour" }, { key: "day", label: "Day" }, { key: "week", label: "Week" }, { key: "month", label: "Month" },
];
export const GRAN_LIMIT: Record<Gran, string> = {
  hour: "Date range must be 2 days or less for this option",
  day: "Date range must be 31 days or less for this option",
  week: "Date range must be between 14 to 365 days for this option",
  month: "Date range must be more than 62 days for this option",
};
export function hoursOf(days: string[]): string[] {
  if (days.length > 2) return [];
  return days.flatMap((d) => Array.from({ length: 24 }, (_, h) => `${d}T${String(h).padStart(2, "0")}:00`));
}

export type View = "ready" | "loading" | "error" | "empty";
export function viewOf(reads: readonly { isError: boolean; isPending: boolean }[], hasRows: boolean): View {
  return reads.some((q) => q.isError) ? "error" : reads.some((q) => q.isPending) ? "loading" : hasRows ? "ready" : "empty";
}
export type Wait = "loading" | "error";
export const isWait = (v: View): v is Wait => v === "loading" || v === "error";
export const SUMMARY_TEXT: Record<Wait, string> = { loading: "Loading…", error: "Earnings data unavailable" };
export const TREND_TEXT: Record<Wait, string> = { loading: "Loading earnings trend…", error: "Earnings trend unavailable" };
export const CHANNEL_TEXT: Record<Wait, string> = { loading: "", error: "Earnings by channel unavailable" };
export const NO_CREATORS = "No creators in this selection";
export type Tab = "overview" | "performance";
export const TABS: readonly { key: Tab; label: string }[] = [
  { key: "overview", label: "Overview" },
  { key: "performance", label: "Creator performance" },
];
export const isTab = (v: string): v is Tab => TABS.some((t) => t.key === v);

export function referralsUnavailableNote(n: number | null): string {
  const who = n === null ? "these creators" : n === 1 ? "1 creator" : `${n} creators`;
  return `Referrals from OnlyFans are unavailable for ${who}, left out of Total earnings.`;
}

export type GrowthSums = Partial<Record<Bucket | "total", number>>;

export type TotalGrowth = "whole" | "pending" | "exclReferrals";
type ReferralsRead = { isSuccess: boolean; isError: boolean; data?: ReferralsResp };
export function totalGrowthOf(refs: ReferralsRead, refsPrior: ReferralsRead): TotalGrowth {
  if (referralsGap(refs) !== "none" || referralsGap(refsPrior) !== "none") return "exclReferrals";
  return refs.isSuccess && refsPrior.isSuccess ? "whole" : "pending";
}

export function forGrowth(sums: GrowthSums, mode: TotalGrowth): GrowthSums {
  if (mode === "whole") return sums;
  const { referrals = 0, total, ...rest } = sums;
  return total === undefined || mode === "pending" ? rest : { ...rest, total: total - referrals };
}

export const creatorName = (m: PerModelRow): string => m.display_name || m.account_id;


export interface ColCtx { hours: number; agencyCents: number; net: boolean }
export interface StatCol {
  key: string;
  title: string;
  width: number;
  show: boolean;
  utc?: boolean;
  avg?: true;
  extra?: boolean;
  fmt?: "usd" | "int" | "pct" | "dur";
  v?: (m: PerModelRow, c: ColCtx) => number | null;
  netV?: (m: PerModelRow, c: ColCtx) => number | null;
}
type Kind = keyof PerModelRow["revenue_by_kind"];
const kindOf = (k: Kind) => (m: PerModelRow) => m.revenue_by_kind?.[k] ?? 0;
const netKindOf = (k: Kind) => (m: PerModelRow) => (m.net_revenue_by_kind ? m.net_revenue_by_kind[k] ?? 0 : null);
const chanOf = (k: Kind) => (m: PerModelRow) => kindOf(k)(m) - (m.other_by_kind?.[k] ?? 0);
const netChanOf = (k: Kind) => (m: PerModelRow) => {
  const n = netKindOf(k)(m);
  return n === null ? null : n - (m.net_other_by_kind?.[k] ?? 0);
};
const subsOf = (m: PerModelRow) => (m.revenue_by_kind?.subscription ?? 0) + (m.revenue_by_kind?.rebill ?? 0);
const netSubsOf = (m: PerModelRow) => {
  const n = m.net_revenue_by_kind;
  return n ? (n.subscription ?? 0) + (n.rebill ?? 0) : null;
};
export const msgOf = (m: PerModelRow) => chanOf("ppv")(m) + chanOf("custom")(m);
export const netMsgOf = (m: PerModelRow) => {
  const p = netChanOf("ppv")(m);
  return p === null ? null : p + (netChanOf("custom")(m) ?? 0);
};
const engagedOf = (m: PerModelRow) => msgOf(m) + chanOf("tip")(m);
const netEngagedOf = (m: PerModelRow) => {
  const n = netMsgOf(m);
  return n == null ? null : n + (netChanOf("tip")(m) ?? 0);
};
export const STAT_COLS: readonly StatCol[] = [
  { key: "totalSubscriptionsEarnings", title: "Total subscription earnings", width: 270, show: true, fmt: "usd", v: subsOf, netV: netSubsOf },
  { key: "subscriptionsEarnings", title: "Subscription earnings", width: 240, show: false, fmt: "usd", v: kindOf("subscription"), netV: netKindOf("subscription") },
  { key: "recurringSubscriptionEarnings", title: "Recurring subscription earnings", width: 305, show: false, fmt: "usd", v: kindOf("rebill"), netV: netKindOf("rebill") },
  { key: "tips", title: "Tips", width: 112, show: true, fmt: "usd", v: chanOf("tip"), netV: netChanOf("tip") },
  { key: "message", title: "Message", width: 145, show: true, fmt: "usd", v: msgOf, netV: netMsgOf },
  { key: "engagementEarningsRatio", title: "Engagement earnings ratio", width: 280, show: true, fmt: "pct", v: (m) => (subsOf(m) > 0 ? (100 * engagedOf(m)) / subsOf(m) : null),
    netV: (m) => { const s = netSubsOf(m), e = netEngagedOf(m); return s !== null && e !== null && s > 0 ? (100 * e) / s : null; } },
  { key: "posts", title: "Posts", width: 120, show: false, fmt: "usd", v: kindOf("post"), netV: netKindOf("post") },
  { key: "totalEarnings", title: "Total earnings", width: 240, show: true, fmt: "usd", v: (m) => m.total_revenue_cents, netV: (m) => m.total_net_revenue_cents },
  { key: "avgHourlyEarnings", title: "Avg hourly earnings", width: 220, show: false, fmt: "usd", avg: true, v: (m, c) => (c.hours > 0 ? m.total_revenue_cents / c.hours : null),
    netV: (m, c) => (c.hours > 0 ? m.total_net_revenue_cents / c.hours : null) },
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
  { key: "newSubscribersLtv", title: "New subscriber LTV", width: 300, show: true, fmt: "usd", avg: true, v: (m) => (m.new_subs_count > 0 ? engagedOf(m) / m.new_subs_count : null),
    netV: (m) => { const n = netEngagedOf(m); return n !== null && m.new_subs_count > 0 ? n / m.new_subs_count : null; } },
  { key: "newSubscriberConversion", title: "New subscriber conversion", width: 340, show: true, utc: true, fmt: "pct", v: (m) => m.of_new_sub_conversion_pct },
  { key: "activeFans", title: "Active fans", width: 230, show: true, utc: true, fmt: "int", v: (m) => m.active_subs_count },
  { key: "changeInExpiredFanCount", title: "Change in expired fan count", width: 345, show: false, utc: true },
  { key: "numberOfSpender", title: "Number of spenders", width: 260, show: true, fmt: "int", v: (m) => m.spenders_count },
  { key: "avgSpendPerSpender", title: "Avg spend per spender", width: 263, show: true, fmt: "usd", avg: true, v: (m) => m.avg_spend_per_spender_cents },
  { key: "avgSpendPerTransaction", title: "Avg spend per transaction", width: 280, show: false, fmt: "usd", avg: true, v: (m) => m.avg_spend_per_transaction_cents },
  { key: "totalNumberOfFans", title: "Total number of fans", width: 300, show: false, utc: true },
  { key: "avgEarningsPerFan", title: "Avg earnings per fan", width: 225, show: true },
  { key: "avgSubscriptionLength", title: "Avg subscription length", width: 315, show: false, utc: true },
  { key: "replyTime", title: "Reply time", width: 190, show: true, fmt: "dur", v: (m) => m.avg_reply_seconds ?? null },
  { key: "fansChatted", title: "Fans chatted", width: 185, show: true, fmt: "int", v: (m) => m.fans_chatted ?? 0 },
  { key: "messagesSent", title: "Messages sent", width: 190, show: true, fmt: "int", v: (m) => m.messages_sent },
  { key: "ppvsSent", title: "PPVs sent", width: 170, show: true, fmt: "int", v: (m) => m.ppvs_sent ?? 0 },
  { key: "pending", title: "Pending revenue", width: 200, show: false, extra: true, fmt: "usd", v: (m) => m.pending_revenue_cents ?? 0 },
  { key: "ppvConversions", title: "PPV conversions", width: 200, show: false, extra: true, fmt: "int", v: (m) => m.ppv_conversions },
  { key: "ltv", title: "LTV", width: 140, show: false, extra: true, fmt: "usd", avg: true, v: (m) => m.ltv_cents },
  { key: "arpu", title: "ARPU", width: 140, show: false, extra: true, fmt: "usd", avg: true, v: (m) => m.arpu_cents },
];
export function readOf(col: StatCol, ctx: ColCtx): StatCol["v"] {
  if (!ctx.net) return col.v;
  return col.netV ?? (col.fmt === "usd" ? undefined : col.v);
}
export function statCol(key: string): StatCol {
  const c = STAT_COLS.find((x) => x.key === key);
  if (!c) throw new Error(`no stat column ${key}`);
  return c;
}
export function colTotal(col: StatCol, rows: readonly PerModelRow[], ctx: ColCtx): number {
  const read = readOf(col, ctx);
  return rows.reduce((a, m) => a + (read?.(m, ctx) ?? 0), 0);
}
export function cellText(col: StatCol, m: PerModelRow, ctx: ColCtx): string {
  const n = readOf(col, ctx)?.(m, ctx) ?? null;
  if (n === null) return "-";
  if (col.fmt === "usd") return col.avg ? fmtPrice(n) : fmtDollars(n);
  if (col.fmt === "pct") return `${n.toFixed(2)}%`;
  if (col.fmt === "dur") return fmtReplyTime(n);
  return n.toLocaleString("en-US");
}
export function cellCsv(col: StatCol, m: PerModelRow, ctx: ColCtx): Cell {
  const n = readOf(col, ctx)?.(m, ctx) ?? null;
  if (n === null) return "";
  if (col.fmt === "usd") return usd(n);
  if (col.fmt === "pct") return Math.round(n * 100) / 100;
  if (col.fmt === "dur") return fmtReplyTime(n);
  return n;
}

function utcDate(day: string): Date { return new Date(`${day}T00:00:00Z`); }
export function daysFrom(from: string | null, to: string | null): string[] {
  if (!from || !to) return [];
  const out: string[] = [];
  const end = utcDate(to).getTime();
  for (let t = utcDate(from).getTime(); t <= end && out.length < 3660; t += 86_400_000) {
    out.push(new Date(t).toISOString().slice(0, 10));
  }
  return out;
}

export type RangeKey = string;
export const DEFAULT_RANGE: RangeKey = "last30";
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

export function fmtRangeLabel(day: string | null): string {
  if (!day) return "…";
  return utcDate(day).toLocaleDateString("en-US", { timeZone: "UTC", month: "short", day: "numeric", year: "numeric" });
}
export function fmtBucketLabel(day: string, p: Gran): string {
  if (p === "hour") {
    const t = new Date(`${day}:00Z`);
    const h = t.getUTCHours();
    return `${t.toLocaleString("en-US", { timeZone: "UTC", month: "short" })} ${t.getUTCDate()} ${h % 12 || 12} ${h < 12 ? "AM" : "PM"}`;
  }
  const d = utcDate(day);
  if (p === "month") return d.toLocaleString("en-US", { timeZone: "UTC", month: "short", year: "2-digit" });
  if (p === "week")  return `${d.toLocaleString("en-US", { timeZone: "UTC", month: "short" })} ${d.getUTCDate()}`;
  return d.toLocaleString("en-US", { timeZone: "UTC", month: "short", day: "numeric" });
}

export interface Point { label: string; value: number; partial?: string }
export function rollUp(days: string[], values: number[], p: Gran): Point[] {
  if (p === "day" || p === "hour") return days.map((d, i) => ({ label: fmtBucketLabel(d, p), value: values[i] ?? 0 }));
  const out: (Point & { days: number; full: number })[] = [];
  days.forEach((d, i) => {
    const starts = p === "week" ? i % 7 === 0 : i === 0 || d.slice(0, 7) !== days[i - 1].slice(0, 7);
    const full = p === "week" ? 7 : new Date(Date.UTC(+d.slice(0, 4), +d.slice(5, 7), 0)).getUTCDate();
    if (starts) out.push({ label: fmtBucketLabel(d, p), value: 0, days: 0, full });
    const b = out[out.length - 1];
    b.value += values[i] ?? 0;
    b.days += 1;
  });
  return out.map(({ label, value, days: n, full }) => (n < full ? { label, value, partial: `${n} of ${full} days` } : { label, value }));
}


export type Bucket = "subscriptions" | "tips" | "posts" | "messages" | "referrals" | "other";
export type Chan = Exclude<Bucket, "other">;
const noBuckets = (): Record<Bucket, number> =>
  ({ subscriptions: 0, tips: 0, posts: 0, messages: 0, referrals: 0, other: 0 });
export const totalOf = (b: Record<Bucket, number>): number => Object.values(b).reduce((a, c) => a + c, 0);
// Earnings already leave reversals out, so no total counts chargebacks.
export const chargebacksCents = (qs: readonly { data?: RevResp }[], money: Money): number =>
  qs.reduce((a, q) => (q.data?.rows ?? []).reduce((b, r) => b - money(r), a), 0);
export function sumKinds(qs: readonly { data?: RevResp }[], money: Money): Record<Bucket, number> {
  const out = noBuckets();
  for (const q of qs) for (const r of q.data?.rows ?? []) out[bucketOf(r.kind)] += money(r);
  return out;
}
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
    byChan: (key: Bucket) => days.map((d) => byChan.get(d)?.[key] ?? 0),
  };
}
export const CHANNELS: readonly { key: Chan; label: string; color: string }[] = [
  { key: "subscriptions", label: "Subscription", color: "#1b9bd2" },
  { key: "tips",          label: "Tips",         color: "#58a547" },
  { key: "posts",         label: "Posts",        color: "#d96a42" },
  { key: "messages",      label: "Messages",     color: "#ac72d2" },
  { key: "referrals",     label: "Referrals",    color: "#d5638d" },
];
export const CHARGEBACKS_COLOR = "#ff7c71";
export const LEDGER_ROWS = ["Gross earnings", "Platform fee", "VAT collected", "Chargeback ratio", "Refunds", "Net earnings"] as const;

export function bucketOf(kind: string | null): Bucket {
  if (!kind) return "other";
  if (kind === "subscription" || kind === "rebill") return "subscriptions";
  // Must precede the generic ppv catch-all below, or ppv_post lands in Messages.
  if (kind === "tip_post" || kind === "ppv_post") return "posts";
  if (kind === "tip_stream" || kind === "ppv_stream") return "other";
  if (kind === "tip") return "tips";
  if (kind === "referral") return "referrals";
  if (kind.startsWith("ppv")) return "messages";
  // Paid customs are sold in chat: Messages.
  if (kind === "custom") return "messages";
  return "other";
}

export function creatorRows(cols: readonly StatCol[], creators: PerModelRow[], ctx: ColCtx): Cell[][] {
  return [
    ["Creator", ...cols.map((c) => c.title)],
    ...creators.map((m) => [creatorName(m), ...cols.map((c) => cellCsv(c, m, ctx))]),
  ];
}

export async function creatorDayRows(creators: PerModelRow[], days: string[], net: boolean,
  read: (accountId: string) => Promise<{ earned: RevResp; reversed: RevResp }>): Promise<Cell[][]> {
  // Referrals are OnlyFans' own read, not on the revenue read: left out (not $0), so Total earnings == the columns before Chargebacks.
  const chans: { key: Bucket; label: string }[] = [
    ...CHANNELS.filter((c) => c.key !== "referrals"), { key: "other", label: "Other" }];
  const reads = await mapLimit(creators, 4, (m) => read(m.account_id));
  const rows: Cell[][] = [["Creator", "Day", "Total earnings (excl. referrals)", ...chans.map((c) => c.label), "Chargebacks"]];
  creators.forEach((m, i) => {
    const money = net ? netOf : grossOf;
    const d = dailyOf([{ data: reads[i].earned }], days, money);
    const byChan = chans.map((c) => d.byChan(c.key));
    const cb = dailyOf([{ data: reads[i].reversed }], days, money).total.map((v) => 0 - v);
    days.forEach((day, j) => rows.push([creatorName(m), day, usd(d.total[j]), ...byChan.map((v) => usd(v[j])), usd(cb[j])]));
  });
  return rows;
}
