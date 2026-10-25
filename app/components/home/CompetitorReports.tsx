"use client";

/**
 * The "Creator Reports" card: the body of Analytics › Creator reports (`StatsReport`, view "creator") and the
 * Dashboard's embed, one module for both (docs/spec/infloww-parity-round-2/phase-03-creator-reports.md).
 *
 * It opens on the Layout capture's frame (docs/infloww-layouts/analytics-creator-reports.md, ticket 20): the page
 * header (title, report time zone, Refresh), the "Overview" / "Creator performance" tabs, then the filter bar
 * (date range, Creator tag, Creator, Show net earnings, Reset). Item IDs are cited as `#<n>`.
 *   • the window is the page's own range (`useCreatorRange`, ticket 60), the last 7 days through today to start with,
 *     with the bundle's presets and bounds (#21 to #24), in the Agency's report time zone; each "Last N days" is the
 *     other reports' `presetRange` window (N calendar days through today, so today's pending sales show); nothing is read until
 *     the Applied settings answer, so no request goes out with the browser's days. The other reports' shared
 *     `useReportRange` keeps its own 30-day default
 *   • `frame="page"` (Analytics › Creator reports) lies flush on the page background (#41); the Dashboard's embed
 *     keeps its bordered card
 *   • the tab is seeded once from `?tab=` (`overview` | `performance`) and a click writes it back
 *   • the Creator filter lists the per-model read's Creators (the relay clamps it to the caller's Agency) and
 *     narrows every section; Reset puts the range, the Creators and the bucket back
 *   • Creator tag is Not wired. "Show net earnings" (ticket 23, on at load as the bundle's is, #33) switches every money figure with a net
 *     read to OnlyFans' own post-fee net: the revenue reads gain `include_net=true` (`net_cents`), and Creator
 *     statistics' Total reads the per-model read's `total_net_revenue_cents`. A figure with no net read (each
 *     per-kind money column and card, Pending revenue, LTV, ARPU) shows the Not wired marker while it is on, and the
 *     export leaves it empty; the sales with no net figure yet are counted under the filter bar
 *   • the Overview (ticket 21, #42 to #86): Earnings summary from the revenue-by-kind read, each tile's growth
 *     against the window of equal length just before ("-" when that window holds days the relay has no figure for,
 *     `history_missing_days`: before a Creator was added and not read from OnlyFans yet); Earnings trends and Earnings by channel from the daily read
 *     (split by kind), bucketed by Hour, Day, Week or Month under the capture's limits; Earnings
 *     breakdown from the kind read; Referrals from OnlyFans' own read (`useReferralRevenue`), taken as one more kind
 *   • Creator statistics (ticket 22, #87 to #153): the four stat cards and the capture's columns from the per-model
 *     read, Custom metrics picking them; Refunded and Refunds sum the reversed sales (chargebacks, refunds, refunds
 *     pending) dated by sale; every column no read carries is Not wired; Export
 *     is the bundle's pop-up (W5 5.9, ExportMenu): All data fields or Selected fields, Gross or Net, total and by
 *     day, as CSV or Excel, downloaded at once
 *   • Creator performance (ticket 22, #154 to #174): the filter bar's "Shown by" select, a creator list and, for the
 *     one picked, Earnings and Earnings breakdown from its revenue reads; Earnings heatmap (the window's
 *     sales by weekday and hour, `group_by=hour_of_week`); Chargebacks charts its reversed sales (`status=reversed`) by sale date
 *   • Ingest health, "All messages…" and the per-model KPI cards are ours, behind the
 *     header's one "Inflowwww extras" overflow (ADR-0003); the Inventory's breakdown rows are ours too, in the
 *     "Earnings ledger" after Creator statistics (the capture's Notes); and so are "Hide $0 creators" and "Export
 *     CSV" over Creator performance's creator list, where the Clone puts them
 *
 * Colours come from the app's theme tokens (var(--color-*) / fill-*,
 * stroke-* utilities) so the card follows the shell's dark/light mode.
 */

import Link from "next/link";
import { useEffect, useId, useMemo, useRef, useState } from "react";
import { keepPreviousData, useIsFetching, useQueries, useQueryClient } from "@tanstack/react-query";
import {
  ArrowDownLeft, ArrowUpRight, CircleDollarSign, Filter as FilterFunnel, Info as InfoCircle,
  MessageCircle, RefreshCw, SlidersHorizontal, StickyNote, Tag, Upload, UserRoundPlus, Video, X, type LucideIcon,
} from "lucide-react";

import { ChargebacksChart, EarningsHeatmap } from "@/components/home/CreatorPerfCharts";
import { OnlyfansLine } from "@/components/shell/inflowwIcons";
import { useActionAllowed } from "@/components/shell/useGrantedPages";
import {
  type Gran, BlankChart, ChartAxes, ChartMessage, LineChart, fmtDollars, fmtUsd, granAllowed, granShown, niceMax, plotFrame,
  useChartWidth,
} from "@/components/stats/chart";
import ExportMenu, { type ExportChoice } from "@/components/stats/ExportMenu";
import { EmptyState } from "@/components/ui/infloww";
import { useReferralRevenue } from "@/hooks/useReferrals";
import IngestHealthBanner from "@/components/stats/IngestHealthBanner";
import PerModelKpiGrid from "@/components/stats/PerModelKpiGrid";
import { usePerModel, type PerModelRow } from "@/hooks/useStats";
import { useTabParam } from "@/hooks/useTabParam";
import { useAppliedSettings } from "@/lib/appliedSettings";
import { dateBounds, presetRange, priorRange, todayISO, toLocalIso } from "@/lib/dateRange";
import { fmtPrice, fmtReplyTime, growthOf, type Growth } from "@/lib/format";
import { EXTRA_LABEL, EXTRAS_OVERFLOW_LABEL } from "@/lib/openinflowwwwExtras";
import { relay, type RelayContext } from "@/lib/relay";
import { type Cell, type Section, exportSections, mapLimit, usd } from "@/lib/reportExport";
import { utcOffsetLabel } from "@/lib/utcOffset";
import { cn } from "@/lib/utils";

const BG_CTX: RelayContext = { priority: "background" };

/** `net_cents` (OnlyFans' own post-fee figure, VAT not deducted), `net_missing_count` (the rows with no net yet,
 *  which `net_cents` leaves out) and OnlyFans' own `fee_cents` and `vat_cents` are there when the read asks for them
 *  (`include_net=true`). */
interface RevKindRow {
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
interface RevResp { rows: RevRow[]; history_missing_days?: number }
/** Whether a window's reads answered and each one's history is whole: else a growth against it is "-". */
const wholeHistory = (qs: readonly { isSuccess: boolean; data?: RevResp }[]) =>
  qs.length > 0 && qs.every((q) => q.isSuccess && !(q.data?.history_missing_days ?? 0));
/** A revenue row's money: gross, or with "Show net earnings" on OnlyFans' own net. Never a ratio of gross. */
type Money = (r: RevKindRow) => number;
const grossOf: Money = (r) => r.total_cents;
const netOf: Money = (r) => r.net_cents ?? 0;

/** #65: the granularity tabs. Hour reads the relay's local hours (`group_by=hour`). */
const GRANS: readonly { key: Gran; label: string }[] = [
  { key: "hour", label: "Hour" }, { key: "day", label: "Day" }, { key: "week", label: "Week" }, { key: "month", label: "Month" },
];
/** #28: a disabled choice's tooltip. */
const GRAN_LIMIT: Record<Gran, string> = {
  hour: "Date range must be 2 days or less for this option",
  day: "Date range must be 31 days or less for this option",
  week: "Date range must be between 14 to 365 days for this option",
  month: "Date range must be more than 62 days for this option",
};
/** The range's local hours, `YYYY-MM-DDTHH:00` as the relay's `group_by=hour` keys them; none past Hour's 2 days. */
function hoursOf(days: string[]): string[] {
  if (days.length > 2) return [];
  return days.flatMap((d) => Array.from({ length: 24 }, (_, h) => `${d}T${String(h).padStart(2, "0")}:00`));
}

/** The sections' state: the reads answered with at least one Creator in the selection, or not. */
type View = "ready" | "loading" | "error" | "empty";
/* The wording of a section still loading or failed. The capture shows a pulser there, so these are ours, labelled
 * (ticket 60). With no Creator the bundle prints its zeros and blank charts, and so do we, with no wording. */
type Wait = "loading" | "error";
const isWait = (v: View): v is Wait => v === "loading" || v === "error";
const SUMMARY_TEXT: Record<Wait, string> = { loading: "Loading…", error: "Earnings data unavailable" };
const TREND_TEXT: Record<Wait, string> = { loading: "Loading earnings trend…", error: "Earnings trend unavailable" };
const CHANNEL_TEXT: Record<Wait, string> = { loading: "", error: "Earnings by channel unavailable" };
/** Ours: the Creator performance list's wording with no Creator in the Creator filter's pick. */
const NO_CREATORS = "No creators in this selection";
/** The bundle's own tab keys (index.9f50f370.js @13634517, `E==="performance"`), which `?tab=` carries. */
type Tab = "overview" | "performance";
const TABS: readonly { key: Tab; label: string }[] = [
  { key: "overview", label: "Overview" },
  { key: "performance", label: "Creator performance" },
];
const isTab = (v: string): v is Tab => TABS.some((t) => t.key === v);

/** Write `?tab=` back, keeping every other parameter and the hash. The state argument is `null`, as
 *  `stripSearchParam` in MessagesPro.tsx explains: Next's patched replaceState then syncs its router. */
function writeTabParam(tab: Tab) {
  const url = new URL(window.location.href);
  url.searchParams.set("tab", tab);
  window.history.replaceState(null, "", url.pathname + url.search + url.hash);
}

/** "1 sale … has … it" / "3 sales … have … them": the sales with no net figure from OnlyFans yet. */
/** OnlyFans' referrals read failed for `n` Creators (no session, OnlyFans down), or the whole read did (`null`). */
function referralsUnavailableNote(n: number | null): string {
  const who = n === null ? "these creators" : n === 1 ? "1 creator" : `${n} creators`;
  return `Referrals from OnlyFans are unavailable for ${who}, counted as $0.00.`;
}

function netMissingNote(n: number): string {
  return n === 1
    ? "1 sale in this period has no net figure from OnlyFans yet, so net earnings leave it out."
    : `${n} sales in this period have no net figure from OnlyFans yet, so net earnings leave them out.`;
}

/* ── Creator statistics columns ── */

/** What a cell reads besides its row: the window's hours (#121), the Agency's total earnings (#123), and whether
 *  "Show net earnings" is on. */
interface ColCtx { hours: number; agencyCents: number; net: boolean }
interface StatCol {
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
const STAT_COLS: readonly StatCol[] = [
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
const DEFAULT_COLS = (): Set<string> => new Set(STAT_COLS.filter((c) => c.show).map((c) => c.key));
/** The column's read in the current basis; none when it has no relay field, or no net read while net is on. */
function readOf(col: StatCol, ctx: ColCtx): StatCol["v"] {
  if (!ctx.net) return col.v;
  return col.netV ?? (col.fmt === "usd" ? undefined : col.v);
}
/** A cell as shown: "-" when the read has nothing (#147). */
function cellText(col: StatCol, m: PerModelRow, ctx: ColCtx): string {
  const n = readOf(col, ctx)?.(m, ctx) ?? null;
  if (n === null) return "-";
  // A total in whole dollars, as on the dashboard; an average keeps its cents, as Infloww prints it.
  if (col.fmt === "usd") return col.avg ? fmtPrice(n) : fmtDollars(n);
  if (col.fmt === "pct") return `${n.toFixed(2)}%`;
  if (col.fmt === "dur") return fmtReplyTime(n);
  return n.toLocaleString("en-US");
}
/** A cell as exported: dollars and percentages to two decimals, as numbers; empty when the read has nothing. */
function cellCsv(col: StatCol, m: PerModelRow, ctx: ColCtx): Cell {
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
function daysFrom(from: string | null, to: string | null): string[] {
  if (!from || !to) return [];
  const out: string[] = [];
  const end = utcDate(to).getTime();
  // Ten years of days at most, so a malformed range can never spin.
  for (let t = utcDate(from).getTime(); t <= end && out.length < 3660; t += 86_400_000) {
    out.push(new Date(t).toISOString().slice(0, 10));
  }
  return out;
}

/** #21: the range picker's `MMM D, YYYY`. */
function fmtRangeLabel(day: string | null): string {
  if (!day) return "…";
  return utcDate(day).toLocaleDateString("en-US", { timeZone: "UTC", month: "short", day: "numeric", year: "numeric" });
}
function fmtBucketLabel(day: string, p: Gran): string {
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

interface Point { label: string; value: number }
/** The days' values rolled into `p`: each day; seven days at a time from the range's first day; calendar months. With
 *  `hour` the slots are hours (`hoursOf`), each its own bucket. */
function rollUp(days: string[], values: number[], p: Gran): Point[] {
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

type Bucket = "subscriptions" | "tips" | "posts" | "messages" | "streams" | "referrals" | "other";
type Chan = Exclude<Bucket, "other">;
const noBuckets = (): Record<Bucket, number> =>
  ({ subscriptions: 0, tips: 0, posts: 0, messages: 0, streams: 0, referrals: 0, other: 0 });
/** The kind reads' rows' money summed by channel. */
function sumKinds(qs: readonly { data?: RevResp }[], money: Money): Record<Bucket, number> {
  const out = noBuckets();
  for (const q of qs) for (const r of q.data?.rows ?? []) out[bucketOf(r.kind)] += money(r);
  return out;
}
/** The day reads' rows (`by_kind=true`) as each day's money and each channel's, over `days`. */
function dailyOf(qs: readonly { data?: RevResp }[], days: string[], money: Money) {
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
const CHANNELS: readonly { key: Chan; label: string; color: string; wired: boolean }[] = [
  { key: "subscriptions", label: "Subscription", color: "#1b9bd2", wired: true },
  { key: "tips",          label: "Tips",         color: "#58a547", wired: true },
  { key: "posts",         label: "Posts",        color: "#d96a42", wired: true },
  { key: "messages",      label: "Messages",     color: "#ac72d2", wired: true },
  { key: "referrals",     label: "Referrals",    color: "#d5638d", wired: true },
  { key: "streams",       label: "Streams",      color: "#ac8d00", wired: true },
];
/** #50: the summary tiles in order; the hidden cell sits after Messages. The icons are the nearest of ours to the
 *  bundle's (`RefreshCw02`, `StickerSquare`, `MessageCircle01`, `CurrencyDollarCircle`, `UserShare`, `VideoRecorder`,
 *  index.9f50f370.js near @13286185); the Total tile's is OnlyFans' mark (`Onlyfans`), the shell's `OnlyfansLine`. */
const TILES: readonly { key: Chan | "total"; label: string; Icon: LucideIcon }[] = [
  { key: "total",         label: "Total earnings", Icon: OnlyfansLine },
  { key: "subscriptions", label: "Subscriptions",  Icon: RefreshCw },
  { key: "posts",         label: "Posts",          Icon: StickyNote },
  { key: "messages",      label: "Messages",       Icon: MessageCircle },
  { key: "tips",          label: "Tips",           Icon: CircleDollarSign },
  { key: "referrals",     label: "Referrals",      Icon: UserRoundPlus },
  { key: "streams",       label: "Streams",        Icon: Video },
];
/** The Inventory's breakdown rows, which the capture lacks (its Notes): ours, in the "Earnings ledger". Gross
 *  earnings has a read, and Platform fee, VAT collected and Net earnings too while "Show net earnings" is on (the net
 *  read carries OnlyFans' own fee and VAT). */
const LEDGER_ROWS = ["Gross earnings", "Platform fee", "VAT collected", "Chargeback ratio", "Refunds", "Net earnings"] as const;
/** #101: the Creator statistics cards' tooltips, verbatim. */
const STAT_TIPS = {
  creators: "Total number of creators managed by your team",
  message: "Earnings from creators’ messages during the selected time frame",
  total: "Earnings from all creators’ subscriptions, tips, posts, messages, streams and referrals during the selected time frame",
  refunded: "Amount of refunds during the selected time frame",
} as const;
/** #161: the Creator performance Earnings block's channel buttons, All first. */
const PERF_CHANNELS: readonly { key: Chan | "all"; label: string; wired: boolean }[] = [
  { key: "all", label: "All", wired: true },
  { key: "subscriptions", label: "Subscriptions", wired: true },
  { key: "tips", label: "Tips", wired: true },
  { key: "posts", label: "Posts", wired: true },
  { key: "messages", label: "Messages", wired: true },
  { key: "referrals", label: "Referrals", wired: true },
  { key: "streams", label: "Streams", wired: true },
];
/** #167: Creator performance's own slice and legend-dot colours, in CHANNELS' order (the bundle's literal hex, as the
 *  Overview's channel colours are); its sparklines rise and fall in the bundle's two. */
const PERF_COLORS: Record<Chan, string> = {
  subscriptions: "#3467ff", tips: "#2ad4ac", posts: "#ff6868", messages: "#ffa553", referrals: "#34c2ff", streams: "#ca34ff",
};
const PERF_SPARK = { up: "#2ad4ac", down: "#ff7c71" } as const;
/** #155, #164, #168: the Creator performance blocks' tooltips, verbatim. */
const PERF_TIPS = {
  earnings: "Sales growth and trends of all Creator earnings",
  breakdown: "A detailed view of Creator earnings broken down by channel",
  heatmap: "Heat intensity shows the number of PPVs bought per time slot, identifying top performing days and hours within a week",
  chargebacks: "Growth and trends of earnings refunded from the Creator",
} as const;

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

/* ── outside-click hook ── */

function useClickOutside<T extends HTMLElement>(onClose: () => void) {
  const ref = useRef<T | null>(null);
  useEffect(() => {
    function onDown(e: MouseEvent) {
      if (!ref.current) return;
      if (!ref.current.contains(e.target as Node)) onClose();
    }
    function onKey(e: KeyboardEvent) { if (e.key === "Escape") onClose(); }
    // pointerdown, not mousedown: iOS only synthesises mousedown for taps on
    // clickable nodes, so tapping the backdrop never dismissed these popovers.
    // pointerdown precedes mousedown for a mouse, so desktop is unchanged.
    document.addEventListener("pointerdown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [onClose]);
  return ref;
}

/* ── main component ── */

/* ── the page's own range (#21 to #24) ── */

/** A range preset: one of `datePresets`' keys, "custom" for days typed in. */
type RangeKey = string;
/** #21: the default range, the bundle's `defaultSelectDate`. */
const DEFAULT_RANGE: RangeKey = "last7";
/** #23, #24: the bundle's presets in its order, their days in `tz`. "Custom" carries the default range as its value
 *  (the bundle's `defineSelectDateArr`). Where the bundle's Last ones and its year end yesterday, ours run through
 *  today on the shared `presetRange` (the other reports' "Last N days", so one label is one window everywhere, and
 *  today's pending sales show); this month runs from its first day to today, and the five months before are whole. */
function datePresets(tz: string | null): { key: RangeKey; label: string; days: [string, string] }[] {
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

/** Creator reports' own range, in the report time zone: the last 7 days through today to start with (#21), kept here
 *  so the other reports' shared `useReportRange` keeps its 30-day default. A preset's days are derived each render,
 *  so they follow the report time zone; `ready` is false until the Applied settings answer. */
function useCreatorRange() {
  const [custom, setCustom] = useState<{ from: string | null; to: string | null }>({ from: null, to: null });
  const [preset, setPreset] = useState<RangeKey>(DEFAULT_RANGE);
  const applied = useAppliedSettings();
  const reportTz = applied.data?.preferences?.report_tz ?? null;
  const [from, to]: [string | null, string | null] =
    preset === "custom" ? [custom.from, custom.to]
    : datePresets(reportTz).find((p) => p.key === preset)?.days ?? [null, null];
  const handleRange = (f: string | null, t: string | null, p: RangeKey) => {
    if (p === "custom") setCustom({ from: f, to: t });
    setPreset(p);
  };
  return {
    preset, from, to,
    fromIso: toLocalIso(from, false, reportTz),
    toIso: toLocalIso(to, true, reportTz),
    reportTz,
    ready: !applied.isPending,
    handleRange,
  };
}

/** `card` (the default, the Dashboard's embed) sits in a bordered panel; `page` (Analytics › Creator reports) lies
 *  flush on the page background, as the bundle's page does (#41). */
type Frame = "card" | "page";

export default function CompetitorReports({ frame = "card" }: { frame?: Frame } = {}) {
  const range = useCreatorRange();
  // Nothing mounts, so nothing is read, until the Applied settings answer: no request goes out with the
  // browser's days first (StatsReport waits the same way).
  if (!range.ready) {
    return (
      <div
        className={cn("h-[400px] animate-pulse", frame === "card" && "rounded-md border")}
        style={frame === "card" ? { background: "var(--color-panel)", borderColor: "var(--color-border)" } : undefined}
        aria-busy="true"
      />
    );
  }
  return <CreatorReportsCard range={range} frame={frame} />;
}

type CreatorRange = ReturnType<typeof useCreatorRange>;

function CreatorReportsCard({ range, frame }: { range: CreatorRange; frame: Frame }) {
  const { preset, from, to, fromIso, toIso, reportTz, handleRange } = range;
  /* state */
  // #65, #73: each chart's own granularity tabs, Day by default.
  const [trendGran, setTrendGran] = useState<Gran>("day");
  const [chanGran, setChanGran] = useState<Gran>("day");
  // #71: the channels picked; none picked draws every one.
  const [chanPick, setChanPick] = useState<Set<Chan>>(() => new Set());
  // null  ≡ "all models". Set ≡ explicit subset.
  const [selectedIds, setSelectedIds] = useState<Set<string> | null>(null);
  const [tab, setTab] = useState<Tab>("overview");
  // Seeded once from `?tab=`; a bogus value leaves Overview (#14).
  useTabParam("tab", isTab, setTab);
  const [extrasOpen, setExtrasOpen] = useState(false);
  // #105: the Creator statistics columns shown, the capture's defaults first.
  const [visibleCols, setVisibleCols] = useState<Set<string>>(DEFAULT_COLS);
  // Creator performance: the "Shown by" bucket (#27), the Earnings channel (#161), the picked Creator (#156), and
  // ours, "Hide $0 creators" (on, as the Clone has it).
  const [perfGran, setPerfGran] = useState<Gran>("day");
  const [perfChan, setPerfChan] = useState<Chan | "all">("all");
  const [pickedId, setPickedId] = useState<string | null>(null);
  const [hideZero, setHideZero] = useState(true);
  // #33: "Show net earnings", on at load as the bundle's is; Reset leaves it alone, as the bundle's does (#37).
  const [net, setNet] = useState(true);
  const money = net ? netOf : grossOf;
  const netLabelId = useId();
  const sectionId = useId();
  const ids = {
    summary: `${sectionId}-summary`, trends: `${sectionId}-trends`, channel: `${sectionId}-channel`,
    breakdown: `${sectionId}-breakdown`, stats: `${sectionId}-stats`, ledger: `${sectionId}-ledger`,
    perfEarnings: `${sectionId}-perf-earnings`, perfBreakdown: `${sectionId}-perf-breakdown`,
    perfHeatmap: `${sectionId}-perf-heatmap`, perfChargebacks: `${sectionId}-perf-chargebacks`,
  };

  const pickTab = (t: Tab) => {
    setTab(t);
    writeTabParam(t);
  };
  /* #37: the default range, no Creator tag, every Creator, Day. */
  const reset = () => {
    handleRange(null, null, DEFAULT_RANGE);
    setSelectedIds(null);
    setTrendGran("day");
    setChanGran("day");
    setPerfGran("day");
  };

  const qc = useQueryClient();
  const fetchingStats = useIsFetching({ queryKey: ["stats"] });
  const fetchingReports = useIsFetching({ queryKey: ["competitor"] });
  const fetching = fetchingStats + fetchingReports > 0;
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["stats"] });
    qc.invalidateQueries({ queryKey: ["competitor"] });
  };
  // #7: the report time zone the window runs in; the browser's when the Agency saved none.
  const zone = reportTz ?? Intl.DateTimeFormat().resolvedOptions().timeZone;

  /* day-axis */
  const dayDates = useMemo(() => daysFrom(from, to), [from, to]);

  /* queries — per_model is always all-models so we have the full picker */
  const perModel = usePerModel(fromIso, toIso, { engagement: true });
  const allModels = perModel.data?.per_model ?? [];

  /* effective model id list — when null, fall through with no account_id */
  const isAll = selectedIds === null;
  const effectiveIds: string[] = useMemo(() => {
    if (isAll) return ["__all__"];
    // One read for every selected Creator: the revenue route sums a comma-separated account_id.
    return selectedIds!.size ? [Array.from(selectedIds!).sort().join(",")] : [];
  }, [isAll, selectedIds]);

  /* #58: the window of equal length just before the selected one, for each tile's growth. */
  const priorDays = priorRange(from, to);
  const priorFromIso = toLocalIso(priorDays?.[0] ?? null, false, reportTz);
  const priorToIso = toLocalIso(priorDays?.[1] ?? null, true, reportTz);

  /* a revenue query for the selection (none when it is empty); "__all__" sends no account_id. `reversed` reads the
     chargebacks and refunds in place of the earnings (#170). */
  const revenueQuery = (
    kind: "day" | "hour" | "kind" | "hour_of_week", id: string, f: string | null, t: string | null, n: boolean,
    reversed = false,
  ) => ({
    queryKey: ["competitor", `revenue-${kind}`, id, f, t, n, reversed] as const,
    queryFn: () => {
      // #74: the day (and hour) read splits each bucket by kind for Earnings by channel.
      const qs = new URLSearchParams(kind === "day" || kind === "hour" ? { group_by: kind, by_kind: "true" } : { group_by: kind });
      // #33: OnlyFans' own net rides on the same read (the Dashboard's Net switch asks it the same way).
      if (n) qs.set("include_net", "true");
      if (reversed) qs.set("status", "reversed");
      if (f) qs.set("from", f);
      if (t) qs.set("to", t);
      if (id !== "__all__") qs.set("account_id", id);
      return relay.get<RevResp>(`/admin/stats/revenue?${qs.toString()}`, BG_CTX);
    },
    staleTime: 60_000,
    // The last answer stays up while the next loads, but never across the switch: a gross answer has no
    // `net_cents`, so it would read as $0 net.
    placeholderData: (prev: RevResp | undefined, prevQuery?: { queryKey: readonly unknown[] }) =>
      prevQuery?.queryKey[5] === n ? keepPreviousData(prev) : undefined,
  });
  const revByDayQueries = useQueries({ queries: effectiveIds.map((id) => revenueQuery("day", id, fromIso, toIso, net)) });
  const revByKindQueries = useQueries({ queries: effectiveIds.map((id) => revenueQuery("kind", id, fromIso, toIso, net)) });
  const revPriorQueries = useQueries({
    queries: effectiveIds.map((id) => revenueQuery("kind", id, priorFromIso, priorToIso, net)),
  });
  // Referrals: OnlyFans' own read per Creator (no transaction carries them), as one more kind on the rows above,
  // folded in when they land: the ledger's figures never wait on them.
  const { now: refs, rev: refRev, priorRev: refPriorRev } =
    useReferralRevenue([from, to], priorDays ?? [null, null], effectiveIds[0], effectiveIds.length > 0);

  /* aggregate day rows → each day's money (gross, or net with the switch on), and each channel's */
  const daily = useMemo(
    () => dailyOf([...revByDayQueries, { data: refRev.day }], dayDates, money),
    [revByDayQueries, refRev, dayDates, money],
  );

  /* #65, #73: each chart's buckets, under the range's limits. Hour (2 days at most, #29) reads the hour buckets, only
     while a chart shows it. */
  const trendPeriod = granShown(trendGran, dayDates.length);
  const chanPeriod = granShown(chanGran, dayDates.length);
  const hourSlots = useMemo(() => hoursOf(dayDates), [dayDates]);
  const revByHourQueries = useQueries({
    queries: trendPeriod === "hour" || chanPeriod === "hour"
      ? effectiveIds.map((id) => revenueQuery("hour", id, fromIso, toIso, net)) : [],
  });
  const hourly = useMemo(() => dailyOf(revByHourQueries, hourSlots, money), [revByHourQueries, hourSlots, money]);
  const trendSrc = useMemo(() => (trendPeriod === "hour" ? { slots: hourSlots, d: hourly } : { slots: dayDates, d: daily }),
    [trendPeriod, hourSlots, hourly, dayDates, daily]);
  const chanSrc = useMemo(() => (chanPeriod === "hour" ? { slots: hourSlots, d: hourly } : { slots: dayDates, d: daily }),
    [chanPeriod, hourSlots, hourly, dayDates, daily]);

  /* aggregate kind rows → buckets, for the window and the one before */
  const buckets = useMemo(
    () => sumKinds([...revByKindQueries, { data: refRev.kind }], money),
    [revByKindQueries, refRev, money],
  );
  const totalCents = useMemo(
    () => Object.values(buckets).reduce((a, b) => a + b, 0),
    [buckets],
  );
  // The ledger's Gross earnings stays gross with net on: a net read still carries each row's `total_cents`.
  const grossCents = useMemo(
    () => Object.values(sumKinds([...revByKindQueries, { data: refRev.kind }], grossOf)).reduce((a, b) => a + b, 0),
    [revByKindQueries, refRev],
  );
  // Its rows off the net read: OnlyFans' own per-sale fee and VAT, and the net total.
  const netLedger: Partial<Record<(typeof LEDGER_ROWS)[number], number>> = useMemo(() => {
    const sum = (money: Money) => Object.values(sumKinds(revByKindQueries, money)).reduce((a, b) => a + b, 0);
    return { "Platform fee": sum((r) => r.fee_cents ?? 0), "VAT collected": sum((r) => r.vat_cents ?? 0), "Net earnings": totalCents };
  }, [revByKindQueries, totalCents]);
  const prior = useMemo(() => {
    if (!wholeHistory(revPriorQueries)) return null;
    const b = sumKinds([...revPriorQueries, { data: refPriorRev.kind }], money);
    return { ...b, total: Object.values(b).reduce((a, c) => a + c, 0) };
  }, [revPriorQueries, refPriorRev, money]);

  /* creator table — filtered to selection */
  const visibleCreators = useMemo(() => {
    if (isAll) return allModels;
    return allModels.filter((m) => selectedIds!.has(m.account_id));
  }, [isAll, allModels, selectedIds]);

  /* The Overview's state: an error first, then a read still pending, then no Creator in the selection. */
  const current = [...revByDayQueries, ...revByKindQueries, ...revByHourQueries];
  // The referrals read never holds the Overview; failed, it counts $0.00 under a note, never an error.
  const view: View =
    perModel.isError || current.some((q) => q.isError) ? "error" :
    perModel.isPending || current.some((q) => q.isPending) ? "loading" :
    visibleCreators.length === 0 ? "empty" : "ready";
  const ready = view === "ready";

  const trendPoints = useMemo(() => rollUp(trendSrc.slots, trendSrc.d.total, trendPeriod), [trendSrc, trendPeriod]);
  // #74: a line per picked channel, every wired one when none is picked.
  const channelLines = useMemo(
    () => CHANNELS
      .filter((c) => c.wired && (chanPick.size === 0 || chanPick.has(c.key)))
      .map((c) => ({ ...c, points: rollUp(chanSrc.slots, chanSrc.d.byChan(c.key), chanPeriod) })),
    [chanSrc, chanPeriod, chanPick],
  );
  /* #75, #85: the donut's channels, their share of the wired channels' sum */
  const wiredSum = CHANNELS.reduce((a, c) => a + (c.wired ? buckets[c.key] : 0), 0);

  /* #101: the Creator statistics cards; "-" until the per-model read answers with a Creator in the selection. */
  const statsView: View =
    perModel.isError ? "error" : perModel.isPending ? "loading" : visibleCreators.length === 0 ? "empty" : "ready";
  const messageEarnings = visibleCreators.reduce((a, m) => a + (m.revenue_by_kind?.ppv ?? 0), 0);
  // With net on, a Creator's total is the per-model read's net total; it has no net by kind.
  const creatorTotal = (m: PerModelRow) => (net ? m.total_net_revenue_cents : m.total_revenue_cents);
  const totalEarningsAcrossCreators = visibleCreators.reduce((a, m) => a + creatorTotal(m), 0);
  const refundedGross = visibleCreators.reduce((a, m) => a + (m.refunded_cents ?? 0), 0);
  const refundedAcrossCreators = net
    ? visibleCreators.reduce((a, m) => a + (m.refunded_net_cents ?? 0), 0) : refundedGross;
  // #121, #123: the window's hours, and the Agency's total over every Creator it has, not only the ones picked.
  const ctxFor = (n: boolean): ColCtx => ({
    hours: dayDates.length * 24,
    agencyCents: allModels.reduce((a, m) => a + (n ? m.total_net_revenue_cents : m.total_revenue_cents), 0),
    net: n,
  });
  const colCtx = ctxFor(net);
  // The sales in the selection's window with no net figure from OnlyFans yet, which net leaves out.
  const netMissing = net && revByKindQueries.every((q) => q.isSuccess)
    ? revByKindQueries.reduce((n, q) => n + (q.data?.rows ?? []).reduce((a, r) => a + (r.net_missing_count ?? 0), 0), 0)
    : 0;
  // The capture's column order, filtered to the Custom metrics pick.
  const orderedCols = useMemo(() => STAT_COLS.filter((c) => visibleCols.has(c.key)), [visibleCols]);

  /* Creator performance (#154 to #174): the creator list (the Creator filter's pick, less the $0 ones while "Hide $0
     creators" is on), and the one picked's reads, made only while the tab is open. */
  const perfAll = visibleCreators;
  const perfList = hideZero ? perfAll.filter((m) => m.total_revenue_cents > 0) : perfAll;
  const picked = perfList.find((m) => m.account_id === pickedId) ?? perfList[0] ?? null;
  const perfIds = tab === "performance" && picked ? [picked.account_id] : [];
  const perfPeriod = granShown(perfGran, dayDates.length);
  const perfHour = perfPeriod === "hour";
  const perfTimeQueries = useQueries({
    queries: perfIds.map((id) => revenueQuery(perfHour ? "hour" : "day", id, fromIso, toIso, net)),
  });
  const perfKindQueries = useQueries({ queries: perfIds.map((id) => revenueQuery("kind", id, fromIso, toIso, net)) });
  const perfPriorQueries = useQueries({
    queries: perfIds.map((id) => revenueQuery("kind", id, priorFromIso, priorToIso, net)),
  });
  // #170: Chargebacks, the picked Creator's reversals by day (or hour, as Earnings).
  const perfReversedQueries = useQueries({
    queries: perfIds.map((id) => revenueQuery(perfHour ? "hour" : "day", id, fromIso, toIso, net, true)),
  });
  // #168: Earnings heatmap, the picked Creator's sales by weekday and hour in the report zone.
  const perfHeatQueries = useQueries({ queries: perfIds.map((id) => revenueQuery("hour_of_week", id, fromIso, toIso, net)) });
  const { now: perfRefs, before: perfRefsPrior, rev: perfRefRev, priorRev: perfRefPriorRev } =
    useReferralRevenue([from, to], priorDays ?? [null, null], perfIds[0], perfIds.length > 0);
  const perfReads = [...perfTimeQueries, ...perfKindQueries, ...perfReversedQueries, ...perfHeatQueries];
  const perfView: View =
    perModel.isError || perfReads.some((q) => q.isError) ? "error" :
    perModel.isPending || perfReads.some((q) => q.isPending) ? "loading" :
    picked ? "ready" : "empty";
  const perfReady = perfView === "ready";
  const perfRetry = () => {
    if (perModel.isError) perModel.refetch();
    for (const q of [...perfReads, ...perfPriorQueries, perfRefs, perfRefsPrior]) q.refetch();
  };
  /* #172 to #174: a failed block's `AbnormalRequestError` in the block's place, centred in its height: the error art,
     "Request failed" and a primary Retry (the bundle's words are i18n keys loaded at run time). */
  const perfFailed = (minHeight: number) => (
    <div className="flex items-center justify-center" style={{ minHeight }}>
      <EmptyState kind="error" text="Request failed" onRetry={perfRetry} />
    </div>
  );
  const perfSlots = perfHour ? hourSlots : dayDates;
  const perfDaily = useMemo(
    () => dailyOf([...perfTimeQueries, { data: perfRefRev.day }], perfSlots, money),
    [perfTimeQueries, perfRefRev, perfSlots, money],
  );
  const perfPoints = useMemo(
    () => rollUp(perfSlots, perfChan === "all" ? perfDaily.total : perfDaily.byChan(perfChan), perfPeriod),
    [perfSlots, perfDaily, perfChan, perfPeriod],
  );
  const perfHeat = useMemo(
    () => perfHeatQueries.flatMap((q) => q.data?.rows ?? [])
      .map((r) => ({ weekday: r.weekday ?? 0, hour: r.hour ?? 0, value: money(r) })),
    [perfHeatQueries, money],
  );
  const perfChargebacks = useMemo(
    () => rollUp(perfSlots, dailyOf(perfReversedQueries, perfSlots, money).total, perfPeriod),
    [perfReversedQueries, perfSlots, money, perfPeriod],
  );
  const perfBuckets = useMemo(
    () => sumKinds([...perfKindQueries, { data: perfRefRev.kind }], money),
    [perfKindQueries, perfRefRev, money],
  );
  const perfPrior = useMemo(
    () => (wholeHistory(perfPriorQueries)
      ? sumKinds([...perfPriorQueries, { data: perfRefPriorRev.kind }], money) : null),
    [perfPriorQueries, perfRefPriorRev, money],
  );
  const perfWiredSum = CHANNELS.reduce((a, c) => a + (c.wired ? perfBuckets[c.key] : 0), 0);
  // Ours: the creator list's rows, with the columns Creator statistics shows.
  // The same rows and cells as the export pop-up's total (a cell with no net read is left empty).
  const exportPerf = () => void exportSections(`creator-performance_${from ?? ""}_${to ?? ""}`, "Creator performance",
    [{ title: "Total", rows: creatorRows(orderedCols, perfList, colCtx) }], "csv");
  const exportAllowed = useActionAllowed("export");
  // #88, #89: Infloww's Creator export pop-up (W5 5.9): All data fields (every column with a read in the basis) or
  // the Custom metrics pick, Gross or Net, the range's total per Creator and by day.
  const buildExport = async (c: ExportChoice): Promise<Section[]> => {
    const ctx = ctxFor(c.net);
    const sections: Section[] = [];
    if (c.displays.includes("total")) {
      const cols = c.allFields ? STAT_COLS.filter((col) => readOf(col, ctx)) : orderedCols;
      sections.push({ title: "Total", rows: creatorRows(cols, visibleCreators, ctx) });
    }
    if (c.displays.includes("day")) {
      // The day read Earnings by channel makes, so a Creator already on screen comes from the cache.
      const read = (id: string) => qc.fetchQuery(revenueQuery("day", id, fromIso, toIso, c.net));
      sections.push({ title: "By day", rows: await creatorDayRows(visibleCreators, dayDates, c.net, read) });
    }
    return sections;
  };

  /* render */
  return (
    <div
      // overflow-clip, not overflow-hidden: a hidden overflow would trap the statistics header's sticky top (#108).
      className={cn(frame === "card" && "rounded-md overflow-clip border")}
      style={{
        ...(frame === "card" ? { background: "var(--color-panel)", borderColor: "var(--color-border)" } : {}),
        color: "var(--color-fg)",
      }}
    >
      {/* #4: the page header, 16px all round, the title block left and the controls right. */}
      <header className="flex flex-wrap items-center justify-between gap-2 p-4">
        <div className="flex flex-wrap items-center min-w-0">
          {/* #3, #5: the menu title, 24px weight 500. */}
          <h1 className="text-2xl font-medium leading-[1.1667]" style={{ color: "var(--color-fg)" }}>
            Creator reports
          </h1>
          {/* #7 to #9: the report time zone and a 16px info icon, 8px either side, 14px. */}
          <span className="mx-2 flex items-center text-sm" style={{ color: "var(--color-fg-dim)" }}>
            {/* The zone's offset, as the bundle prints a `reportTimezoneId`; its name on hover. */}
            <span className="mr-2" title={zone} suppressHydrationWarning>{utcOffsetLabel(zone)}</span>
            <span title="Set by your organization" className="inline-flex">
              <InfoCircle size={16} aria-hidden />
            </span>
          </span>
        </div>
        <div className="flex items-center gap-2">
          {/* Ours: every Inflowwww extra on this page sits behind this one overflow (ADR-0003). */}
          <button
            type="button"
            title={EXTRAS_OVERFLOW_LABEL}
            aria-expanded={extrasOpen}
            aria-controls="creator-reports-extras"
            onClick={() => setExtrasOpen((v) => !v)}
            className="px-2 py-1.5 rounded-md min-h-7 text-sm"
            style={{ color: "var(--color-fg-dim)", background: "var(--color-bg-elev-1)" }}
          >
            {EXTRAS_OVERFLOW_LABEL}
          </button>
          {/* #10 to #13: an icon-only button, "Refresh page", 6px padding and radius, 28px high, no border. */}
          <button
            type="button"
            aria-label="Refresh page"
            title="Refresh page"
            onClick={refresh}
            disabled={fetching}
            className="p-1.5 rounded-md min-h-7 disabled:opacity-60"
            style={{ color: "var(--color-fg)", background: "var(--color-bg-elev-1)" }}
          >
            <RefreshCw size={16} className={fetching ? "animate-spin" : undefined} aria-hidden />
          </button>
        </div>
      </header>

      {extrasOpen && (
        <section
          id="creator-reports-extras"
          aria-label={EXTRAS_OVERFLOW_LABEL}
          className="mx-4 mb-4 p-3 space-y-3 rounded-md border text-[13px]"
          style={{ borderColor: "var(--color-border)" }}
        >
          <div className="flex flex-wrap items-center gap-3">
            <span title={EXTRA_LABEL}>
              <Link
                href="/analytics/message-dashboard?tab=all"
                className="text-sm text-accent hover:underline whitespace-nowrap"
                title="Drill into individual messages — filter by fan, direction, type. Export CSV."
              >
                All messages…
              </Link>
            </span>
          </div>
          <div title={EXTRA_LABEL}><IngestHealthBanner /></div>
          <div title={EXTRA_LABEL}><PerModelKpiGrid from={fromIso} to={toIso} /></div>
        </section>
      )}

      {/* #14 to #17: two toggle buttons side by side, Overview first, 16px sides and 16px below. */}
      <div role="tablist" aria-label="Creator reports" className="flex px-4 mb-4">
        {TABS.map((t) => {
          const on = tab === t.key;
          return (
            <button
              key={t.key}
              type="button"
              role="tab"
              aria-selected={on}
              onClick={() => pickTab(t.key)}
              className="px-3 py-2 rounded-lg min-h-9 text-base font-medium leading-5"
              style={{
                color: on ? "var(--color-fg)" : "var(--color-fg-dim)",
                background: on ? "color-mix(in srgb, var(--color-fg) 5.5%, transparent)" : "transparent",
              }}
            >
              {t.label}
            </button>
          );
        })}
      </div>

      {/* #18, #19: the inline filter bar, 16px between controls, 16px left and 8px bottom padding. */}
      <div role="group" aria-label="Filters" className="flex flex-wrap items-center gap-x-4 gap-y-2 pl-4 pr-4 pb-2 text-[14px]">
        {/* #21: the date range. */}
        <DateRangePill
          from={from}
          to={to}
          preset={preset}
          reportTz={reportTz}
          onChange={(f, t) => handleRange(f, t, "custom")}
          onPreset={(key, [f, t]) => handleRange(f, t, key)}
        />
        {tab === "overview" ? (
          <>
            {/* #25: Inflowwww has no Creator tags. */}
            <button
              type="button"
              disabled
              title="not wired"
              className={cn("inline-flex items-center rounded-md min-w-[140px] disabled:opacity-50 disabled:cursor-not-allowed", FILTER_FIELD)}
              style={{ border: "1px solid var(--color-border)", background: "var(--color-bg-elev-1)", color: "var(--color-fg-dim)" }}
            >
              <Tag size={14} aria-hidden />
              Creator tag
            </button>
            {/* #26: the Agency's Creators. */}
            <FiltersPill
              models={allModels.map((m) => ({ id: m.account_id, name: m.display_name || m.account_id }))}
              selected={selectedIds}
              onChange={setSelectedIds}
            />
          </>
        ) : (
          /* #27 to #29: on Creator performance the "Shown by" select takes their place; a
             bucket the range rules out is disabled with the capture's tooltip. */
          <select
            aria-label="Shown by"
            value={perfPeriod}
            onChange={(e) => setPerfGran(e.target.value as Gran)}
            className={cn("rounded-md min-w-[140px]", FILTER_FIELD)}
            style={{ border: "1px solid var(--color-border)", background: "var(--color-bg-elev-1)", color: "var(--color-fg)" }}
          >
            {GRANS.map(({ key, label }) => {
              const ok = granAllowed(key, dayDates.length);
              return (
                <option key={key} value={key} disabled={!ok} title={ok ? undefined : GRAN_LIMIT[key]}>
                  {`Shown by ${label.toLowerCase()}`}
                </option>
              );
            })}
          </select>
        )}
        {/* #30 to #39: the label, the switch and Reset in one centred row. */}
        <span className="flex items-center">
          <span id={netLabelId} className="mr-2 text-base" style={{ color: "var(--color-fg)" }}>Show net earnings</span>
          {/* #33, #34, #36: OnlyFans' own net on every figure that has a net read; the knob 6px in off, 22px on. */}
          <button
            type="button"
            role="switch"
            aria-checked={net}
            aria-labelledby={netLabelId}
            onClick={() => setNet((v) => !v)}
            className="relative w-11 h-7 rounded-full"
            style={{ background: net ? "var(--color-accent)" : "var(--color-bg-elev-2)" }}
          >
            <span className={cn("absolute top-1.5 w-4 h-4 rounded-full bg-white", net ? "left-[22px]" : "left-1.5")} aria-hidden />
          </button>
          <button
            type="button"
            onClick={reset}
            className="ml-6 text-sm font-medium"
            style={{ color: "var(--color-accent)" }}
          >
            Reset
          </button>
        </span>
      </div>
      {/* Ours, as the Dashboard's Net switch has it: the sales net leaves out, so gross is never read as net. */}
      {netMissing > 0 && (
        <p title={EXTRA_LABEL} className="px-4 pb-2 text-[12px] leading-[17px]" style={{ color: "var(--color-fg-dim)" }}>
          {netMissingNote(netMissing)}
        </p>
      )}
      {/* Ours: the Creators OnlyFans' referrals read failed for (all of them when the read did), counted $0.00. */}
      {(refs.isError || !!refs.data?.unavailable?.length) && (
        <p title={EXTRA_LABEL} className="px-4 pb-2 text-[12px] leading-[17px]" style={{ color: "var(--color-fg-dim)" }}>
          {referralsUnavailableNote(refs.data?.unavailable?.length ?? null)}
        </p>
      )}

      {/* #154 to #157: Creator performance, a creator list at the left and the picked one's report at the right. */}
      {tab === "performance" && (
        <div className="flex flex-col md:flex-row text-[13px]">
          <aside className="md:w-[240px] shrink-0 px-4 md:pr-0 pt-2 md:pt-6 pb-4">
            {/* Ours (the capture has neither, its Notes): Hide $0 creators and Export CSV, where the Clone puts them. */}
            <div role="group" aria-label="Creator list tools" title={EXTRA_LABEL} className="flex flex-col items-start gap-2 mb-3">
              <label className="flex items-center gap-2 text-sm cursor-pointer" style={{ color: "var(--color-fg)" }}>
                <input
                  type="checkbox"
                  checked={hideZero}
                  onChange={(e) => setHideZero(e.target.checked)}
                  style={{ accentColor: "var(--color-accent)" }}
                />
                Hide $0 creators
              </label>
              {perfAll.length > perfList.length && (
                <span className="text-xs" style={{ color: "var(--color-fg-dim)" }}>
                  {`${perfAll.length - perfList.length} zero-revenue creator${perfAll.length - perfList.length === 1 ? "" : "s"} hidden`}
                </span>
              )}
              {exportAllowed && <button
                type="button"
                onClick={exportPerf}
                disabled={perfList.length === 0}
                className="inline-flex items-center gap-1 p-1.5 rounded-md min-h-7 text-sm font-medium disabled:opacity-50"
                style={{ color: "var(--color-fg)", background: "var(--color-bg-elev-1)" }}
              >
                <Upload size={16} aria-hidden />
                Export CSV
              </button>}
            </div>
            <ul aria-label="Creators" className="flex flex-col gap-1">
              {perfList.length === 0 ? (
                <li title={EXTRA_LABEL} className="text-sm py-2" style={{ color: "var(--color-fg-dim)" }}>
                  {perModel.isPending ? "Loading…" : perModel.isError ? "Creators unavailable"
                    : perfAll.length === 0 ? NO_CREATORS
                    : `No creator earned in this window. Untick “Hide $0 creators” to see all ${perfAll.length}.`}
                </li>
              ) : perfList.map((m) => {
                const on = m.account_id === picked?.account_id;
                return (
                  <li key={m.account_id}>
                    <button
                      type="button"
                      aria-pressed={on}
                      onClick={() => setPickedId(m.account_id)}
                      className="w-full text-left px-3 py-2 rounded-md text-sm truncate"
                      style={{
                        color: on ? "var(--color-fg)" : "var(--color-fg-dim)",
                        background: on ? "color-mix(in srgb, var(--color-fg) 5.5%, transparent)" : "transparent",
                      }}
                    >
                      {m.display_name || m.account_id}
                    </button>
                  </li>
                );
              })}
            </ul>
          </aside>

          {/* #157: 24px report padding, none below; blocks 32px apart. */}
          <div className="flex-1 min-w-0 px-4 md:px-6 md:pt-6">
            {/* #155, #161 to #163: Earnings, the channel buttons at the right, a 336px bar chart. */}
            <section aria-labelledby={ids.perfEarnings} className="mb-8">
              <div className="flex flex-wrap items-center justify-between gap-2 mb-4">
                <PerfTitle id={ids.perfEarnings} label="Earnings" tip={PERF_TIPS.earnings} />
                <div role="group" aria-label="Earnings channel" className="flex flex-wrap items-center gap-y-1">
                  {PERF_CHANNELS.map((c) => (
                    <button
                      key={c.key}
                      type="button"
                      aria-pressed={perfChan === c.key}
                      disabled={!c.wired}
                      title={c.wired ? undefined : "not wired"}
                      onClick={() => setPerfChan(c.key)}
                      className="h-6 px-2 mr-[15px] last:mr-0 rounded-md text-xs disabled:opacity-50 disabled:cursor-not-allowed"
                      style={{
                        color: perfChan === c.key ? "#fff" : "var(--color-fg)",
                        background: perfChan === c.key ? "var(--color-accent)" : "var(--color-bg-elev-1)",
                      }}
                    >
                      {c.label}
                    </button>
                  ))}
                </div>
              </div>
              {perfView === "error" ? perfFailed(336) : (
                <TrendBars
                  height={336}
                  perf
                  points={perfReady ? perfPoints : null}
                  message={perfView === "loading" ? SUMMARY_TEXT.loading : ""}
                />
              )}
            </section>

            {/* #164 to #167: Earnings breakdown, a donut over its legend beside a growth column. */}
            <section aria-labelledby={ids.perfBreakdown} className="mb-8">
              <div className="flex items-center justify-between mb-4">
                <PerfTitle id={ids.perfBreakdown} label="Earnings breakdown" tip={PERF_TIPS.breakdown} />
              </div>
              {perfView === "error" ? perfFailed(250) : (
                <div className="flex flex-col md:flex-row border rounded-lg" style={{ borderColor: "var(--color-border)" }}>
                  <div className="flex-1 min-w-0 p-4">
                    <Donut perf slices={perfReady ? CHANNELS.filter((c) => c.wired).map((c) => ({ color: PERF_COLORS[c.key], cents: perfBuckets[c.key] })) : null} />
                    <ul aria-label="Earnings breakdown legend" className="flex flex-wrap">
                      {CHANNELS.map((c) => (
                        <li key={c.key} className="w-1/3 mb-2 flex flex-col">
                          <span className="flex items-center text-xs font-semibold leading-4 tracking-[0.15px] mb-2" style={{ color: "var(--color-fg-dim)" }}>
                            <span className="w-[7px] h-[7px] rounded-full mr-1.5 shrink-0" style={{ background: PERF_COLORS[c.key] }} aria-hidden />
                            {c.label}
                          </span>
                          <span className="text-lg font-bold leading-[22px] px-2" style={{ color: "var(--color-fg)" }}>
                            {!c.wired ? <NotWired label={`${c.label} amount`} /> : perfReady ? fmtDollars(perfBuckets[c.key]) : "-"}
                          </span>
                          <span className="text-sm font-semibold leading-5 px-2" style={{ color: "var(--color-fg-dim)" }}>
                            {!c.wired ? <NotWired label={`${c.label} share`} />
                              : perfReady ? `${(perfWiredSum > 0 ? (100 * perfBuckets[c.key]) / perfWiredSum : 0).toFixed(2)}%` : "-"}
                          </span>
                        </li>
                      ))}
                    </ul>
                  </div>
                  <ul aria-label="Earnings growth" className="md:w-[314px] border-t md:border-t-0 md:border-l" style={{ borderColor: "var(--color-border)" }}>
                    {CHANNELS.map((c) => {
                      const g = c.wired && perfReady ? growthOf(perfBuckets[c.key], perfPrior?.[c.key]) : { text: "-", dir: null };
                      return (
                        <li
                          key={c.key}
                          className="h-[62px] flex items-center justify-between px-[15px] border-b last:border-b-0"
                          style={{ borderColor: "var(--color-border)" }}
                        >
                          <span className="flex flex-col min-w-0">
                            {/* #166: the count, 4px from the 12px arrow, then the change. */}
                            <span className="inline-flex items-center">
                              {!c.wired ? <NotWired label={`${c.label} growth`} /> : (
                                <>
                                  <span className="text-base font-semibold leading-5 mr-1 tabular-nums" style={{ color: "var(--color-fg)" }}>
                                    {perfReady ? fmtDollars(perfBuckets[c.key]) : "-"}
                                  </span>
                                  <span
                                    className="inline-flex items-center text-xs font-bold leading-4"
                                    style={{ color: g.dir === "up" ? "var(--color-ok)" : g.dir === "down" ? "var(--color-pink)" : "var(--color-fg)" }}
                                  >
                                    {g.dir && (g.dir === "up"
                                      ? <ArrowUpRight size={12} className="mr-1" role="img" aria-label="rising" />
                                      : <ArrowDownLeft size={12} className="mr-1" role="img" aria-label="falling" />)}
                                    {g.text}
                                  </span>
                                </>
                              )}
                            </span>
                            <span className="text-xs font-semibold leading-5 capitalize max-w-[150px] truncate" style={{ color: "var(--color-fg-dim)" }}>
                              {c.label}
                            </span>
                          </span>
                          {c.wired && perfReady && (
                            <Sparkline values={perfDaily.byChan(c.key)} color={g.dir === "down" ? PERF_SPARK.down : PERF_SPARK.up} />
                          )}
                        </li>
                      );
                    })}
                  </ul>
                </div>
              )}
            </section>

            {/* #168, #169: Earnings heatmap, the window's sales folded into one week in the report zone. */}
            <section aria-labelledby={ids.perfHeatmap} className="mb-8">
              <div className="flex items-center justify-between mb-4">
                <PerfTitle id={ids.perfHeatmap} label="Earnings heatmap" tip={PERF_TIPS.heatmap} />
              </div>
              {perfView === "error" ? perfFailed(300) : (
                <EarningsHeatmap cells={perfReady ? perfHeat : null} message={perfView === "loading" ? SUMMARY_TEXT.loading : ""} />
              )}
            </section>

            {/* #170, #171: Chargebacks, the picked Creator's reversals at the "Shown by" bucket. */}
            <section aria-labelledby={ids.perfChargebacks} className="mb-8">
              <div className="flex items-center justify-between mb-4">
                <PerfTitle id={ids.perfChargebacks} label="Chargebacks" tip={PERF_TIPS.chargebacks} />
              </div>
              {perfView === "error" ? perfFailed(250) : (
                <ChargebacksChart
                  points={perfReady ? perfChargebacks : null}
                  message={perfView === "loading" ? SUMMARY_TEXT.loading : ""}
                />
              )}
            </section>
          </div>
        </div>
      )}

      {/* #42, #43: the Overview, 16px sides: Earnings summary, Earnings trends, the channel row, Creator statistics. */}
      {tab === "overview" && (
        <div className="px-4 pb-6 text-[13px]">
        {/* #46 to #60: Earnings summary, a card of seven tiles in four columns. */}
        <section aria-labelledby={ids.summary}>
          <SectionTitle
            id={ids.summary}
            label="Earnings summary"
            tip="An overview of total earnings based on your managed creators during this period"
          />
          <ReportCard className="px-7 py-6 mb-4">
            <dl className="grid grid-cols-2 md:grid-cols-4 gap-2">
              {TILES.map((t, i) => {
                const cents = t.key === "total" ? totalCents : buckets[t.key];
                const wired = t.key === "total" || CHANNELS.some((c) => c.key === t.key && c.wired);
                const tile = (
                  <SummaryTile
                    key={t.key}
                    label={t.label}
                    Icon={t.Icon}
                    total={t.key === "total"}
                    // With no Creator the reads' zeros, "$0".
                    value={wired ? (isWait(view) ? "-" : fmtDollars(cents)) : null}
                    growth={wired && ready ? growthOf(cents, prior?.[t.key]) : { text: "-", dir: null }}
                  />
                );
                // #50: the hidden cell after Messages keeps Tips under Subscriptions.
                return i === 4 ? [<div key="hidden" aria-hidden className="hidden md:block invisible" />, tile] : tile;
              })}
            </dl>
            {isWait(view) && (
              <p title={EXTRA_LABEL} className="mt-4 text-sm" style={{ color: "var(--color-fg-dim)" }}>{SUMMARY_TEXT[view]}</p>
            )}
          </ReportCard>
        </section>

        {/* #61 to #67: Earnings trends, the granularity tabs right-aligned over a 220px bar chart. */}
        <section aria-labelledby={ids.trends}>
          <ReportCard className="p-4 mb-4">
            <CardTitle
              id={ids.trends}
              label="Earnings trends"
              tip="Sales growth and trends of all earnings from your managed creators"
            />
            <div className="flex flex-row-reverse">
              <GranularityTabs name="Earnings trends granularity" pick={trendGran} days={dayDates.length} onPick={setTrendGran} />
            </div>
            <div className="mt-5">
              <TrendBars points={ready ? trendPoints : null} message={isWait(view) ? TREND_TEXT[view] : ""} />
            </div>
          </ReportCard>
        </section>

        {/* #68: the channel row, 32px below, Earnings by channel and Earnings breakdown at either end. */}
        <div className="flex flex-col md:flex-row md:justify-between gap-4 md:gap-0 mb-8">
          {/* #69 to #75: Earnings by channel (Inventory §3.4, C[H276166]), one of Infloww's sections. */}
          <section aria-labelledby={ids.channel} className="flex-1 min-w-0 md:mr-4">
            <ReportCard className="p-4 md:h-[375px]">
              <div className="md:pr-4">
                <CardTitle
                  id={ids.channel}
                  className="mb-4"
                  label="Earnings by channel"
                  tip="Track trends and growth of your managed creators’ earning channels"
                />
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <ChannelsPill picked={chanPick} onChange={setChanPick} />
                  <GranularityTabs name="Earnings by channel granularity" pick={chanGran} days={dayDates.length} onPick={setChanGran} />
                </div>
                <div className="mt-5">
                  {/* #74, #81, #83: a 250px chart of 2px lines, one per channel given; the breakdown's legend names them. */}
                  <LineChart
                    labels={channelLines[0]?.points.map((p) => p.label) ?? []}
                    lines={ready ? channelLines.map((c) => ({ name: c.label, color: c.color, values: c.points.map((p) => p.value) })) : null}
                    message={isWait(view) ? CHANNEL_TEXT[view] : ""}
                    messageTitle={EXTRA_LABEL}
                    valueFmt={fmtUsd}
                    legend={false}
                  />
                </div>
              </div>
            </ReportCard>
          </section>
          {/* #76 to #86: Earnings breakdown, a 200px donut over the channels' legend. */}
          <section aria-labelledby={ids.breakdown} className="md:w-[376px] shrink-0">
            <ReportCard className="p-4 md:h-[375px]">
              <div className="md:w-[344px]">
                <CardTitle id={ids.breakdown} label="Earnings breakdown" />
                <Donut slices={ready ? CHANNELS.filter((c) => c.wired).map((c) => ({ color: c.color, cents: buckets[c.key] })) : null} />
                <ul
                  aria-label="Earnings breakdown legend"
                  className="grid grid-cols-[1fr_max-content_max-content] gap-x-6 gap-y-1 text-sm leading-[1.1429]"
                >
                  {CHANNELS.map((c) => (
                    <li key={c.key} className="contents">
                      <span className="flex items-center font-medium" style={{ color: "var(--color-fg-dim)" }}>
                        <span className="w-2 h-2 rounded-full mr-2 shrink-0" style={{ background: c.color }} aria-hidden />
                        {c.label}
                      </span>
                      <span className="text-right" style={{ color: "var(--color-fg)" }}>
                        {!c.wired ? <NotWired label={`${c.label} share`} />
                          : ready ? `${(wiredSum > 0 ? (100 * buckets[c.key]) / wiredSum : 0).toFixed(2)}%` : "-"}
                      </span>
                      <span className="text-right" style={{ color: "var(--color-fg)" }}>
                        {!c.wired ? <NotWired label={`${c.label} amount`} /> : ready ? fmtDollars(buckets[c.key]) : "-"}
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            </ReportCard>
          </section>
        </div>

        {/* #87 to #153: Creator statistics, its title with Export at the right, the notice, the four stat cards,
            Custom metrics and the table. */}
        <section aria-labelledby={ids.stats}>
          <div className="flex items-start justify-between gap-2 mb-4">
            <h2 id={ids.stats} className="text-xl font-medium leading-[1.2]" style={{ color: "var(--color-fg)" }}>
              Creator statistics
            </h2>
            {/* #88, #89: the bundle's Export pop-up; ours downloads at once (W5 5.9). */}
            <ExportMenu fileName={`creator-reports_${from ?? ""}_${to ?? ""}`} sheet="Creator reports"
              displays={["total", "day"]} fields net={net} build={buildExport} className="self-start" />
          </div>

          {/* #94 to #100: the notice, two lines with 6px dots, the second carrying the UTC chip. */}
          <div className="mb-4 rounded-lg border px-[11px] py-[7px]" style={{ borderColor: "var(--color-border)" }}>
            <ul className="text-sm" style={{ color: "var(--color-fg)" }}>
              <li className="flex items-baseline my-1 mb-1">
                <span className="w-1.5 h-1.5 rounded-full mr-2 shrink-0 -translate-y-0.5" style={{ background: "var(--color-fg)" }} aria-hidden />
                <span>Percentage change is calculated based on the change in value in the selected time frame against the same time frame immediately before it.</span>
              </li>
              <li className="flex items-baseline my-1">
                <span className="w-1.5 h-1.5 rounded-full mr-2 shrink-0 -translate-y-0.5" style={{ background: "var(--color-fg)" }} aria-hidden />
                <span>Data marked with <UtcChip /> is available in UTC+00:00 only, due to OnlyFans limitations</span>
              </li>
            </ul>
          </div>

          {/* #101 to #104: four cards side by side, 16px apart; Refunded sums the Refunds column. */}
          <ul aria-label="Creator statistics cards" className="flex flex-col md:flex-row gap-4 md:gap-0 mb-4">
            <StatCard label="Creators" tip={STAT_TIPS.creators}
              value={statsView === "ready" ? visibleCreators.length.toLocaleString("en-US") : "-"} />
            <StatCard label="Message earnings" tip={STAT_TIPS.message}
              value={net ? null : statsView === "ready" ? fmtDollars(messageEarnings) : "-"} />
            <StatCard label="Total earnings" tip={STAT_TIPS.total}
              value={statsView === "ready" ? fmtDollars(totalEarningsAcrossCreators) : "-"} />
            <StatCard label="Refunded" tip={STAT_TIPS.refunded}
              value={statsView === "ready" ? fmtDollars(refundedAcrossCreators) : "-"} />
          </ul>

          {/* #105 to #107: Custom metrics, right-aligned, 8px above the table. */}
          <div className="flex justify-end mb-2">
            <CustomMetricsPill visible={visibleCols} onChange={setVisibleCols} />
          </div>

          <CreatorTable creators={visibleCreators} cols={orderedCols} ctx={colCtx} view={statsView} />
        </section>

        {/* Ours: the Inventory's breakdown rows, which the capture lacks (its Notes), after Creator statistics as the
            Clone places them. Gross earnings and Refunds have a read, and Platform fee, VAT collected and Net earnings
            too while "Show net earnings" is on. */}
        <section aria-labelledby={ids.ledger} title={EXTRA_LABEL} className="mt-6">
          <ReportCard className="p-4">
            <h2 id={ids.ledger} className="text-xl font-medium leading-[1.2] mb-4" style={{ color: "var(--color-fg)" }}>
              Earnings ledger
            </h2>
            {LEDGER_ROWS.map((name) => (
              <div
                key={name}
                role="group"
                aria-label={name}
                className="flex flex-wrap items-center justify-between py-2 text-sm border-b last:border-b-0"
                style={{ borderColor: "var(--color-border)" }}
              >
                <span style={{ color: "var(--color-fg-dim)" }}>{name}</span>
                <span style={{ color: "var(--color-fg)" }}>
                  {name === "Gross earnings" ? (ready ? fmtDollars(grossCents) : "-")
                    : name === "Refunds" ? (statsView === "ready" ? fmtDollars(refundedGross) : "-")
                    : !(name in netLedger) ? <NotWired label={name} />
                    : net ? (ready ? fmtDollars(netLedger[name] ?? 0) : "-")
                    // Off, no net read is made: a dash, not the Not wired marker, since the row has a read.
                    : (
                      <button type="button" disabled title="Turn on Show net earnings" aria-label={name} className="cursor-not-allowed opacity-50">
                        -
                      </button>
                    )}
                </span>
                {/* The relay's net is gross less OnlyFans' fee (service/stats.py, `include_net`); VAT collected above
                    is OnlyFans' own figure beside it, not deducted, so the rows do not sum. */}
                {name === "Net earnings" && (
                  <p className="basis-full mt-1 text-[12px]" style={{ color: "var(--color-fg-dim)" }}>
                    OnlyFans&apos; net is gross less its fee; VAT is not deducted.
                  </p>
                )}
              </div>
            ))}
          </ReportCard>
        </section>
        </div>
      )}
    </div>
  );
}

/* ───────── interactive pills ───────── */

/** #40: a filter bar control's geometry, 28px high, 6px by 9px padding, 6px radius, 4px from icon to text, 14px. */
const FILTER_FIELD = "min-h-7 px-[9px] py-1.5 gap-1 text-[14px]";

function PillTrigger({ open, accent, ariaLabel, className, children, onClick }: {
  open?: boolean; accent?: boolean; ariaLabel?: string; className?: string; children: React.ReactNode;
  onClick?: () => void;
}) {
  return (
    <button
      type="button"
      aria-label={ariaLabel}
      aria-expanded={open}
      onClick={onClick}
      className={cn("inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[12px] outline-none", className)}
      style={{
        border: `1px solid ${open ? "var(--color-accent)" : accent ? "color-mix(in srgb, var(--color-accent) 50%, transparent)" : "var(--color-border)"}`,
        background: "var(--color-bg-elev-1)",
        color: accent ? "var(--color-accent)" : "var(--color-fg)",
        boxShadow: open ? "0 0 0 3px color-mix(in srgb, var(--color-accent) 25%, transparent)" : "none",
        cursor: "pointer",
      }}
    >
      {children}
    </button>
  );
}

function PopoverBox({ children, anchor }: { children: React.ReactNode; anchor: "left" | "right" }) {
  return (
    <div
      style={{
        position: "absolute",
        top: "calc(100% + 6px)",
        [anchor]: 0,
        background: "var(--color-bg-elev-1)",
        border: "1px solid var(--color-border)",
        borderRadius: 8,
        boxShadow: "0 12px 32px rgba(0,0,0,0.35), 0 2px 6px rgba(0,0,0,0.2)",
        padding: 8,
        zIndex: 20,
        minWidth: 200,
      } as React.CSSProperties}
    >
      {children}
    </div>
  );
}

/** #21 to #24: the date range, the range's days (YYYY-MM-DD in the report time zone), the bundle's presets beside
 *  the two days, a year back to two days ahead. A cleared input or a day out of bounds changes nothing, so both
 *  sides always hold a day. */
function DateRangePill({ from, to, preset, reportTz, onChange, onPreset }: {
  from: string | null; to: string | null; preset: RangeKey; reportTz: string | null;
  onChange: (f: string | null, t: string | null) => void;
  onPreset: (key: RangeKey, days: [string, string]) => void;
}) {
  const [open, setOpen] = useState(false);
  const ref = useClickOutside<HTMLDivElement>(() => setOpen(false));
  const [minDay, maxDay] = dateBounds(reportTz);
  const isDay = (v: string) => /^\d{4}-\d{2}-\d{2}$/.test(v) && v >= minDay && v <= maxDay;
  return (
    <div ref={ref} style={{ position: "relative" }}>
      <PillTrigger open={open} ariaLabel="Date range" className={FILTER_FIELD} onClick={() => setOpen((v) => !v)}>
        <span style={{ color: "var(--color-fg)" }}>{fmtRangeLabel(from)}</span>
        <span style={{ color: "var(--color-fg-dim)" }}>{"  →  "}</span>
        <span style={{ color: "var(--color-fg)" }}>{fmtRangeLabel(to)}</span>
        <CalIcon />
      </PillTrigger>
      {open && (
        <PopoverBox anchor="left">
          <div className="flex gap-3">
          <div role="group" aria-label="Date presets" className="flex flex-col pr-3 border-r" style={{ borderColor: "var(--color-border)" }}>
            {datePresets(reportTz).map((p) => (
              <button
                key={p.key}
                type="button"
                aria-pressed={preset === p.key}
                onClick={() => onPreset(p.key, p.days)}
                className="text-left whitespace-nowrap px-2 py-1 rounded text-[12px]"
                style={{
                  color: preset === p.key ? "var(--color-accent)" : "var(--color-fg)",
                  background: preset === p.key ? "color-mix(in srgb, var(--color-fg) 5.5%, transparent)" : "transparent",
                }}
              >
                {p.label}
              </button>
            ))}
          </div>
          <div className="flex flex-col gap-2 p-1" style={{ minWidth: 240 }}>
            <label className="flex items-center justify-between gap-3 text-[12px]" style={{ color: "var(--color-fg)" }}>
              <span>From</span>
              <input
                type="date"
                aria-label="From date"
                value={from ?? ""}
                min={minDay}
                max={to ?? maxDay}
                onChange={(e) => { if (isDay(e.target.value)) onChange(e.target.value, to); }}
                style={dateInputStyle}
              />
            </label>
            <label className="flex items-center justify-between gap-3 text-[12px]" style={{ color: "var(--color-fg)" }}>
              <span>To</span>
              <input
                type="date"
                aria-label="To date"
                value={to ?? ""}
                min={from ?? minDay}
                max={maxDay}
                onChange={(e) => { if (isDay(e.target.value)) onChange(from, e.target.value); }}
                style={dateInputStyle}
              />
            </label>
          </div>
          </div>
        </PopoverBox>
      )}
    </div>
  );
}

/** #65, #66, #73: the Hour / Day / Week / Month toggle buttons, 28px, 6px by 8px, no gap and no strip. A choice the
 *  range rules out is disabled with the capture's tooltip (#28, #29). */
function GranularityTabs({ name, pick, days, onPick }: {
  name: string; pick: Gran; days: number; onPick: (g: Gran) => void;
}) {
  const shown = granShown(pick, days);
  return (
    <div role="group" aria-label={name} className="flex">
      {GRANS.map(({ key, label }) => {
        const ok = granAllowed(key, days);
        const on = key === shown;
        return (
          <button
            key={key}
            type="button"
            aria-pressed={on}
            disabled={!ok}
            title={ok ? undefined : GRAN_LIMIT[key]}
            onClick={() => onPick(key)}
            className="px-2 py-1.5 rounded-md min-h-7 text-sm font-medium leading-[1.1429] disabled:cursor-not-allowed"
            style={{
              // #16: toggle colours; a disabled one at the capture's 23.5% alpha on our token.
              color: !ok ? "color-mix(in srgb, var(--color-fg) 23.5%, transparent)" : on ? "var(--color-fg)" : "var(--color-fg-dim)",
              background: on ? "color-mix(in srgb, var(--color-fg) 5.5%, transparent)" : "transparent",
            }}
          >
            {label}
          </button>
        );
      })}
    </div>
  );
}

/** #71, #72: the Channels multi select, a funnel 5px from its text, clearable. */
function ChannelsPill({ picked, onChange }: { picked: Set<Chan>; onChange: (next: Set<Chan>) => void }) {
  const [open, setOpen] = useState(false);
  const ref = useClickOutside<HTMLDivElement>(() => setOpen(false));
  const names = CHANNELS.filter((c) => picked.has(c.key)).map((c) => c.label);
  const toggle = (key: Chan) => {
    const next = new Set(picked);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    onChange(next);
  };
  return (
    <div ref={ref} className="relative flex items-center gap-1">
      <PillTrigger open={open} ariaLabel="Channels" className={FILTER_FIELD} onClick={() => setOpen((v) => !v)}>
        <FilterFunnel size={16} className="mr-[5px]" aria-hidden />
        <span style={{ color: names.length ? "var(--color-fg)" : "var(--color-fg-dim)" }}>
          {names.length ? names.join(", ") : "Channels"}
        </span>
        <Chev />
      </PillTrigger>
      {names.length > 0 && (
        <button
          type="button"
          aria-label="Clear channels"
          onClick={() => onChange(new Set())}
          className="p-1 rounded-md"
          style={{ color: "var(--color-fg-dim)" }}
        >
          <X size={14} aria-hidden />
        </button>
      )}
      {open && (
        <PopoverBox anchor="left">
          <div className="flex flex-col">
            {CHANNELS.map((c) => (
              <label
                key={c.key}
                title={c.wired ? undefined : "not wired"}
                className={cn("flex items-center gap-2 text-[12px] px-2 py-1.5 rounded", c.wired ? "cursor-pointer" : "opacity-50 cursor-not-allowed")}
                style={{ color: "var(--color-fg)" }}
              >
                <input
                  type="checkbox"
                  checked={c.wired && picked.has(c.key)}
                  disabled={!c.wired}
                  onChange={() => toggle(c.key)}
                  style={{ accentColor: "var(--color-accent)" }}
                />
                <span className="w-2 h-2 rounded-full" style={{ background: c.color }} aria-hidden />
                <span>{c.label}</span>
              </label>
            ))}
          </div>
        </PopoverBox>
      )}
    </div>
  );
}

function FiltersPill({ models, selected, onChange }: {
  models: { id: string; name: string }[];
  selected: Set<string> | null;
  onChange: (next: Set<string> | null) => void;
}) {
  const [open, setOpen] = useState(false);
  const ref = useClickOutside<HTMLDivElement>(() => setOpen(false));
  const isAll = selected === null;
  const count = isAll ? models.length : selected!.size;
  // #26: "Creator" until a pick; several picked read "creators selected".
  const label =
    isAll              ? "Creator" :
    count === 0        ? "No creators" :
    count === 1        ? models.find((m) => selected!.has(m.id))?.name ?? "1 creator selected" :
                         `${count} creators selected`;

  function toggle(id: string) {
    const next = new Set(isAll ? models.map((m) => m.id) : Array.from(selected!));
    if (next.has(id)) next.delete(id);
    else next.add(id);
    if (next.size === models.length) onChange(null);
    else onChange(next);
  }

  return (
    <div ref={ref} style={{ position: "relative" }}>
      <PillTrigger open={open} className={cn(FILTER_FIELD, "min-w-[140px] justify-between")} onClick={() => setOpen((v) => !v)}>
        <span>{label}</span>
        <Chev />
      </PillTrigger>
      {open && (
        <PopoverBox anchor="left">
          <div style={{ minWidth: 240, maxHeight: 320, overflowY: "auto" }} className="flex flex-col">
            <div className="flex items-center justify-between px-2 py-1.5">
              <span className="text-[12px]" style={{ color: "var(--color-fg-dim)" }}>
                {isAll ? `All ${models.length} creators` : `${count}/${models.length} selected`}
              </span>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  className="text-[11px]"
                  style={{ color: "var(--color-accent)", background: "none", border: "none", cursor: "pointer", padding: 0 }}
                  onClick={() => onChange(null)}
                >
                  All
                </button>
                <button
                  type="button"
                  className="text-[11px]"
                  style={{ color: "var(--color-fg-dim)", background: "none", border: "none", cursor: "pointer", padding: 0 }}
                  onClick={() => onChange(new Set())}
                >
                  None
                </button>
              </div>
            </div>
            <div style={{ borderTop: "1px solid var(--color-border)", marginBottom: 2 }} />
            {models.length === 0 ? (
              <div className="text-[12px] px-2 py-2" style={{ color: "var(--color-muted)" }}>No creators yet.</div>
            ) : models.map((m) => {
              const checked = isAll || selected!.has(m.id);
              return (
                <label
                  key={m.id}
                  className="flex items-center gap-2 text-[12px] px-2 py-1.5 rounded cursor-pointer"
                  style={{ color: "var(--color-fg)" }}
                >
                  <input
                    type="checkbox"
                    checked={checked}
                    onChange={() => toggle(m.id)}
                    style={{ accentColor: "var(--color-accent)" }}
                  />
                  <span style={{ flex: 1 }}>{m.name}</span>
                </label>
              );
            })}
          </div>
        </PopoverBox>
      )}
    </div>
  );
}

/** #105 to #107: "Custom metrics", opening "Creator report metrics": a checkbox per column in the capture's order,
 *  then ours, each labelled. */
function CustomMetricsPill({ visible, onChange }: {
  visible: Set<string>; onChange: (next: Set<string>) => void;
}) {
  const [open, setOpen] = useState(false);
  const ref = useClickOutside<HTMLDivElement>(() => setOpen(false));
  const headingId = useId();

  function toggle(key: string) {
    const next = new Set(visible);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    onChange(next);
  }
  const linkBtn = "text-[11px] bg-transparent border-none p-0 cursor-pointer";

  return (
    <div ref={ref} style={{ position: "relative" }}>
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="inline-flex items-center gap-1 p-1.5 rounded-md text-sm"
        style={{ color: "var(--color-fg)" }}
      >
        Custom metrics
        <SlidersHorizontal size={16} aria-hidden />
      </button>
      {open && (
        <PopoverBox anchor="right">
          <div role="group" aria-labelledby={headingId} style={{ minWidth: 260, maxHeight: 360, overflowY: "auto" }} className="flex flex-col">
            <div className="flex items-center justify-between px-2 py-1.5">
              <span id={headingId} className="text-[12px] font-medium" style={{ color: "var(--color-fg)" }}>
                Creator report metrics
              </span>
              {/* Ours: the old picker's shortcuts. */}
              <div className="flex items-center gap-2" title={EXTRA_LABEL}>
                <button type="button" className={linkBtn} style={{ color: "var(--color-accent)" }} onClick={() => onChange(DEFAULT_COLS())}>
                  Default
                </button>
                <button type="button" className={linkBtn} style={{ color: "var(--color-accent)" }}
                  onClick={() => onChange(new Set(STAT_COLS.map((c) => c.key)))}>
                  All
                </button>
                <button type="button" className={linkBtn} style={{ color: "var(--color-fg-dim)" }} onClick={() => onChange(new Set())}>
                  None
                </button>
              </div>
            </div>
            <div style={{ borderTop: "1px solid var(--color-border)", marginBottom: 2 }} />
            {STAT_COLS.map((c) => (
              <label
                key={c.key}
                title={c.extra ? EXTRA_LABEL : c.v ? undefined : "not wired"}
                className="flex items-center gap-2 text-[12px] px-2 py-1.5 rounded cursor-pointer"
                style={{ color: c.v ? "var(--color-fg)" : "var(--color-fg-dim)" }}
              >
                <input
                  type="checkbox"
                  checked={visible.has(c.key)}
                  onChange={() => toggle(c.key)}
                  style={{ accentColor: "var(--color-accent)" }}
                />
                <span style={{ flex: 1 }}>{c.title}</span>
              </label>
            ))}
          </div>
        </PopoverBox>
      )}
    </div>
  );
}

/** #98 to #100: the "UTC+00:00" chip, 2px by 4px, 16px high, a pill, 10px weight 500. */
function UtcChip() {
  return (
    <span
      className="inline-flex items-center ml-1 px-1 py-0.5 min-h-4 rounded-full text-[10px] font-medium leading-[1.2] align-middle"
      style={{ color: "var(--color-fg-dim)", background: "var(--color-bg-elev-2)" }}
    >
      UTC+00:00
    </span>
  );
}

/** #108 to #153: the Creator statistics table. "Creator" is fixed left at 180px; the headers start-aligned, 48px rows
 *  with 18px sides; a column with no read has the Not wired marker in its header and "-" cells; "No data" with no
 *  rows; the end line under more than 20. The header stays in view under the top bar (`sticky:true`, #108): it is a
 *  table of its own, sticky to the window's top and scrolled sideways with the body, both laid out by one colgroup. */
function CreatorTable({ creators, cols, ctx, view }: {
  creators: PerModelRow[]; cols: readonly StatCol[]; ctx: ColCtx; view: View;
}) {
  const cell = "px-[18px] h-12 whitespace-nowrap text-start";
  const line = { borderBottom: "1px solid var(--color-border)" };
  const headRef = useRef<HTMLDivElement | null>(null);
  const tableStyle: React.CSSProperties = {
    color: "var(--color-fg)", width: "100%", tableLayout: "fixed",
    minWidth: 180 + cols.reduce((a, c) => a + c.width, 0),
  };
  const colgroup = (
    <colgroup>
      <col style={{ width: 180 }} />
      {cols.map((c) => <col key={c.key} style={{ width: c.width }} />)}
    </colgroup>
  );
  return (
    <>
      <div role="table" aria-label="Creator statistics" className="rounded-xl" style={{ background: "var(--color-bg-elev-1)" }}>
        <div
          ref={headRef}
          role="rowgroup"
          className="overflow-hidden rounded-t-xl z-[2]"
          style={{ position: "sticky", top: "var(--shell-top, 3.5rem)", background: "var(--color-bg-elev-1)" }}
        >
        <table role="presentation" className="text-sm leading-[1.1429] border-collapse" style={tableStyle}>
          {colgroup}
          <thead role="presentation">
            <tr role="row" style={line}>
              <th role="columnheader" scope="col" className={cn(cell, "sticky left-0 z-[1] font-medium")} style={{ background: "var(--color-bg-elev-1)" }}>
                Creator
              </th>
              {cols.map((c) => (
                <th
                  key={c.key}
                  role="columnheader"
                  scope="col"
                  title={c.extra ? EXTRA_LABEL : undefined}
                  className={cn(cell, "font-medium")}
                >
                  {c.v ? c.title : (
                    <button type="button" disabled title="not wired" className="font-medium cursor-not-allowed opacity-60">
                      {c.title}
                    </button>
                  )}
                  {c.utc && <UtcChip />}
                </th>
              ))}
            </tr>
          </thead>
        </table>
        </div>
        <div
          role="rowgroup"
          className="overflow-x-auto"
          onScroll={(e) => { if (headRef.current) headRef.current.scrollLeft = e.currentTarget.scrollLeft; }}
        >
        <table role="presentation" className="text-sm leading-[1.1429] border-collapse" style={tableStyle}>
          {colgroup}
          <tbody role="presentation">
            {view !== "ready" ? (
              <tr role="row">
                <td role="cell" colSpan={cols.length + 1}>
                  {/* #148 to #150: 96px above and below, centred, 16px; "No data" is the bundle's, 8px under the
                      illustration; the loading and failed wording ours (the bundle shows a spinner). */}
                  {view === "empty" ? (
                    <EmptyState className="py-24" textClassName="text-base text-fg-dim" />
                  ) : (
                    <div
                      title={EXTRA_LABEL}
                      className="flex flex-col items-center justify-center py-24 text-base"
                      style={{ color: "var(--color-fg-dim)" }}
                    >
                      {view === "loading" ? "Loading…" : "Creator statistics unavailable"}
                    </div>
                  )}
                </td>
              </tr>
            ) : creators.map((m) => (
              <tr key={m.account_id} role="row" style={line}>
                <td role="cell" className={cn(cell, "sticky left-0 z-[1]")} style={{ background: "var(--color-bg-elev-1)" }}>
                  {m.display_name || m.account_id}
                </td>
                {cols.map((c) => (
                  <td key={c.key} role="cell" className={cell}>
                    {/* A column with a gross read but no net read carries the marker in each cell while net is on. */}
                    {c.v && !readOf(c, ctx)
                      ? <NotWired label={`${m.display_name || m.account_id} ${c.title}`} />
                      : cellText(c, m, ctx)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
        </div>
      </div>
      {/* #151 to #153: the end line, 32px above and below, centred. */}
      {view === "ready" && creators.length > 20 && (
        <p className="py-8 text-center text-base" style={{ color: "color-mix(in srgb, var(--color-fg) 38%, transparent)" }}>
          You have reached the end of the page
        </p>
      )}
    </>
  );
}

/* ───────── export ───────── */

/** Creator statistics columns as rows: a header of their titles, then a row per Creator. */
function creatorRows(cols: readonly StatCol[], creators: PerModelRow[], ctx: ColCtx): Cell[][] {
  return [
    ["Creator", ...cols.map((c) => c.title)],
    ...creators.map((m) => [m.display_name || m.account_id, ...cols.map((c) => cellCsv(c, m, ctx))]),
  ];
}

/** The export's "Display by day" (Infloww's, 05-analytics M22): a row per Creator per day of the range, its
 *  earnings and each wired channel's, from one revenue read per Creator (four at a time). Pending sales count, as
 *  every earnings figure here. */
async function creatorDayRows(creators: PerModelRow[], days: string[], net: boolean,
  read: (accountId: string) => Promise<RevResp>): Promise<Cell[][]> {
  // Referrals are OnlyFans' own read, not on the revenue read: left out rather than written as $0.
  const chans = CHANNELS.filter((c) => c.wired && c.key !== "referrals");
  const reads = await mapLimit(creators, 4, (m) => read(m.account_id));
  const rows: Cell[][] = [["Creator", "Day", "Total earnings", ...chans.map((c) => c.label)]];
  creators.forEach((m, i) => {
    const d = dailyOf([{ data: reads[i] }], days, net ? netOf : grossOf);
    const byChan = chans.map((c) => d.byChan(c.key));
    days.forEach((day, j) => rows.push([m.display_name || m.account_id, day, usd(d.total[j]), ...byChan.map((v) => usd(v[j]))]));
  });
  return rows;
}

const dateInputStyle: React.CSSProperties = {
  border: "1px solid var(--color-border)",
  borderRadius: 6,
  padding: "4px 6px",
  fontSize: 12,
  color: "var(--color-fg)",
  background: "var(--color-bg-elev-1)",
  outline: "none",
};

/* ───────── primitives ───────── */

/** The house Not wired marker, read as "-" (#58, #147). */
function NotWired({ label }: { label: string }) {
  return (
    <button type="button" disabled title="not wired" aria-label={label} className="cursor-not-allowed opacity-50">
      -
    </button>
  );
}

/** #44: a report card, 16px padding and 12px radius by default, on our raised surface (ADR-0001 colours). */
function ReportCard({ className, children }: { className?: string; children: React.ReactNode }) {
  return (
    <div className={cn("rounded-xl p-4", className)} style={{ background: "var(--color-bg-elev-1)" }}>
      {children}
    </div>
  );
}

/** #46 to #48: a section title, 20px weight 500, 16px below, a 24px info icon 8px to its right. */
function SectionTitle({ id, label, tip }: { id: string; label: string; tip: string }) {
  return (
    <div className="flex items-center mb-4">
      <h2 id={id} className="text-xl font-medium leading-[1.2]" style={{ color: "var(--color-fg)" }}>{label}</h2>
      <span title={tip} className="ml-2 inline-flex" style={{ color: "var(--color-fg-dim)" }}>
        <InfoCircle size={24} aria-hidden />
      </span>
    </div>
  );
}

/** #63, #64: a card title, 16px weight 500, a 16px info icon 8px to its right when it has a tooltip. */
function CardTitle({ id, label, tip, className }: { id: string; label: string; tip?: string; className?: string }) {
  return (
    <div className={cn("flex items-center", className)}>
      <h3 id={id} className="text-base font-medium leading-5" style={{ color: "var(--color-fg)" }}>{label}</h3>
      {tip && (
        <span title={tip} className="ml-2 inline-flex" style={{ color: "var(--color-fg-dim)" }}>
          <InfoCircle size={16} aria-hidden />
        </span>
      )}
    </div>
  );
}

/** #55 to #60: a summary tile, its title (with a 20px icon 4px away), value and growth. The total tile is larger.
 *  A `null` value is Not wired. */
function SummaryTile({ label, Icon, total, value, growth }: {
  label: string; Icon: LucideIcon; total: boolean; value: string | null; growth: Growth;
}) {
  // #59: rising and falling on our ok and pink tokens (ADR-0001 colours).
  const color = growth.dir === "up" ? "var(--color-ok)" : growth.dir === "down" ? "var(--color-pink)" : "var(--color-fg)";
  const Arrow = growth.dir === "up" ? ArrowUpRight : ArrowDownLeft;
  return (
    // The capture has no phone layout: below md the total tile spans both columns and long values wrap.
    <div role="group" aria-label={label} className={cn("flex flex-col min-w-0 [overflow-wrap:anywhere]", total && "gap-0.5 col-span-2 md:col-span-1")}>
      <dt
        // #51, #53: Text$5's tracking, heading4's 0.034px or body1's 0.032px on the title and growth, heading1's
        // 0.128px or heading2's 0.098px on the value.
        className={cn("flex items-center gap-1 font-medium", total ? "text-xl leading-6 tracking-[0.034px]" : "text-base leading-5 tracking-[0.032px] mb-2")}
        style={{ color: "var(--color-fg-dim)" }}
      >
        <Icon size={20} aria-hidden />
        {label}
      </dt>
      <dd
        className={cn("font-medium tabular-nums", total ? "text-[32px] leading-9 tracking-[0.128px]" : "text-[28px] leading-8 tracking-[0.098px]")}
        style={{ color: "var(--color-fg)" }}
      >
        {value === null ? <NotWired label={label} /> : value}
      </dd>
      <dd
        className={cn("inline-flex items-center font-medium", total ? "text-xl leading-6 tracking-[0.034px] -translate-y-1" : "text-base leading-5 tracking-[0.032px]")}
        style={{ color }}
      >
        {growth.dir && (
          <Arrow size={total ? 24 : 20} role="img" aria-label={growth.dir === "up" ? "rising" : "falling"} />
        )}
        {growth.text}
      </dd>
    </div>
  );
}

/** #102 to #104: a Creator statistics card, 104px high, its label (16px weight 500, a 16px info icon 4px away) 12px
 *  over its value (32px weight 500). A `null` value is Not wired. */
function StatCard({ label, tip, value }: { label: string; tip: string; value: string | null }) {
  return (
    <li className="flex-1 min-w-0 md:mr-4 md:last:mr-0">
      <div
        role="group"
        aria-label={label}
        className="h-[104px] rounded-xl p-4 flex flex-col gap-3"
        style={{ background: "var(--color-bg-elev-1)", color: "var(--color-fg)" }}
      >
        {/* #53, #103: body1's 0.032px tracking on the label, heading1's 0.128px on the value. */}
        <span className="flex items-center gap-1 text-base leading-5 tracking-[0.032px] font-medium">
          {label}
          <span title={tip} className="inline-flex" style={{ color: "var(--color-fg-dim)" }}>
            <InfoCircle size={16} aria-hidden />
          </span>
        </span>
        <span className="text-[32px] leading-9 tracking-[0.128px] font-medium tabular-nums truncate">
          {value === null ? <NotWired label={label} /> : value}
        </span>
      </div>
    </li>
  );
}

/** #159, #160: a Creator performance block title, 16px weight 500 on 16px, its info icon 9px away and 1px down. */
function PerfTitle({ id, label, tip }: { id: string; label: string; tip: string }) {
  return (
    <div className="flex items-center">
      <h3 id={id} className="text-base font-medium leading-4 mr-[9px]" style={{ color: "var(--color-fg)" }}>{label}</h3>
      <span title={tip} className="inline-flex translate-y-px" style={{ color: "var(--color-fg-dim)" }}>
        <InfoCircle size={16} aria-hidden />
      </span>
    </div>
  );
}

/** #164, #166: a growth row's 140px by 25px sparkline of the channel's days. */
function Sparkline({ values, color }: { values: number[]; color: string }) {
  const W = 140, H = 25;
  const max = Math.max(1, ...values);
  const x = (i: number) => (values.length <= 1 ? W / 2 : (i / (values.length - 1)) * W);
  return (
    <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} className="shrink-0" aria-hidden>
      <path
        d={values.map((v, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(2)},${(H - 1 - (v / max) * (H - 2)).toFixed(2)}`).join(" ")}
        fill="none"
        stroke={color}
        strokeWidth={1.5}
      />
    </svg>
  );
}


/* ───────── charts ───────── */

/** #83: a bar with only its top corners rounded, 2px below 24px wide, 4px below 60px, else 8px, never more than half
 *  its width or its height. */
function barPath(x: number, y: number, w: number, h: number): string {
  const r = Math.min(w < 24 ? 2 : w < 60 ? 4 : 8, w / 2, h);
  return `M${x},${y + h}V${y + r}Q${x},${y} ${x + r},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + h}Z`;
}

/** #67, #82, #83: Earnings trends, a 220px bar chart, each bar's tooltip its Earnings and its Growth over the bucket
 *  before. `perf` is Creator performance's Earnings (#161, #162): 336px high, 25px bars (never wider than their slot),
 *  the x labels 16px off the axis. `null` points draw the blank chart with `message`. */
function TrendBars({ points, message, height = 220, perf = false }: {
  points: Point[] | null; message: string; height?: number; perf?: boolean;
}) {
  const [ref, W] = useChartWidth();
  const H = height;
  const f = plotFrame(W, H);
  const n = points?.length ?? 0;
  const max = niceMax(Math.max(1, ...(points ?? []).map((p) => p.value)), 4);
  const slot = (f.R - f.L) / Math.max(1, n);
  // Each bar 80% of its slot, whole pixels above 1px, at most 96px; Creator performance's 25px (`barWidth:25`).
  const raw = slot * 0.8;
  const bw = perf ? Math.min(25, slot) : Math.min(96, raw > 1 ? Math.floor(raw) : raw);
  const xAt = (i: number) => f.L + slot * (i + 0.5);
  return (
    <div ref={ref} className="relative">
      <ChartMessage message={points ? "" : message} title={EXTRA_LABEL} />
      <svg width="100%" height={H} viewBox={`0 0 ${W} ${H}`} className="block">
        {!points ? <BlankChart W={W} H={H} /> : (
          <>
            <ChartAxes W={W} H={H} max={max} labels={points.map((p) => p.label)} xAt={xAt} labelGap={perf ? 16 : undefined} />
            {points.map((p, i) => {
              const h = (p.value / max) * (f.B - f.T);
              const growth = growthOf(p.value, i > 0 ? points[i - 1].value : null);
              const g = (growth.dir === "down" ? "-" : "") + growth.text;
              return (
                <path
                  key={i}
                  role="img"
                  aria-label={`${p.label}: ${fmtUsd(p.value)}`}
                  d={barPath(xAt(i) - bw / 2, f.B - h, bw, h)}
                  className="fill-accent"
                >
                  <title>{`${p.label}\nEarnings ${fmtUsd(p.value)}\nGrowth ${g}`}</title>
                </path>
              );
            })}
          </>
        )}
      </svg>
    </div>
  );
}

/** #78, #84: Earnings breakdown, a 200px donut (inner radius 55, outer 85); an empty ring with nothing to show.
 *  `perf` is Creator performance's (#164): 180px high and 35px down, its ring 69% to 80% of the half height
 *  (`radius:["80%","69%"]`), 62.1px to 72px. */
function Donut({ slices, perf = false }: { slices: { color: string; cents: number }[] | null; perf?: boolean }) {
  const H = perf ? 180 : 200;
  const [inner, outer] = perf ? [0.69 * 90, 0.8 * 90] : [55, 85];
  const cx = 172, cy = H / 2, r = (inner + outer) / 2, sw = outer - inner, C = 2 * Math.PI * r;
  const sum = (slices ?? []).reduce((a, s) => a + s.cents, 0);
  let at = 0;
  return (
    <svg
      viewBox={`0 0 344 ${H}`}
      className={cn("block w-full", perf ? "h-[180px] mt-[35px]" : "h-[200px] my-2")}
      role="img"
      aria-label={sum > 0 ? "Earnings breakdown chart" : "No earnings"}
    >
      <circle cx={cx} cy={cy} r={r} fill="none" strokeWidth={sw} style={{ stroke: "color-mix(in srgb, var(--color-fg) 24%, transparent)" }} />
      {sum > 0 && slices!.map((s, i) => {
        const len = (C * s.cents) / sum;
        const offset = -at;
        at += len;
        return len > 0 ? (
          <circle
            key={i}
            cx={cx} cy={cy} r={r} fill="none" stroke={s.color} strokeWidth={sw}
            strokeDasharray={`${len.toFixed(2)} ${(C - len).toFixed(2)}`}
            strokeDashoffset={offset.toFixed(2)}
            transform={`rotate(-90 ${cx} ${cy})`}
          />
        ) : null;
      })}
    </svg>
  );
}

/* ───────── icons ───────── */

function Chev() {
  return (
    <svg width="10" height="10" viewBox="0 0 24 24" fill="none">
      <path d="M6 9l6 6 6-6" className="stroke-fg-dim" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
    </svg>
  );
}
function CalIcon() {
  return (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" style={{ marginLeft: 6 }}>
      <rect x="3" y="5" width="18" height="16" rx="2" className="stroke-fg-dim" strokeWidth="1.6"/>
      <path d="M3 9h18M8 3v4M16 3v4" className="stroke-fg-dim" strokeWidth="1.6" strokeLinecap="round"/>
    </svg>
  );
}
