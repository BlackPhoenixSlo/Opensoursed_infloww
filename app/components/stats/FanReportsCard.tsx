"use client";

/**
 * FanReportsCard — Analytics > Fan reports' filter row and cards for one Creator (roadmap W5 5.6), in
 * Infloww's order (`FansReport`, bundle @13648850, page-parity 29):
 *
 *   filters      the page's range box (`range`), "Shown by" (Day / Week / Month; Hour is ruled out, the read is
 *                daily) and Gross / Net earnings.
 *   New fans     a line chart per "Shown by" bucket: All (new + renewed), Renews, New subscribers; the daily
 *                `growth` rows summed client-side, in the report time zone the relay buckets them in.
 *   Total fans   Not wired: nothing stores the subscriber count per day (the route's docstring).
 *   Traffic      the window's spend by the free trial link or promotion each spender claimed; gross only.
 *   Top fans     each fan's spend in the window ranked by the picked metric; "Download report" is the same
 *                ranking as CSV. Subscriptions is our extra column. Net
 *                earnings switches Total spend to the read's net (`net_or_80_cents`); the read has no net per
 *                kind, so Tips, PPV sales and Subscriptions stay gross and say so in their heads.
 *
 * Source: GET /admin/stats/fan-report (useFanReport). Every spend counts cleared and pending sales.
 */

import { useState, type ReactNode } from "react";

import CsvExportButton from "@/components/messages/CsvExportButton";
import { type ChartLine, type Gran, LineChart, granAllowed, granShown, rangeDays } from "@/components/stats/chart";
import { EmptyState, IF_TABLE, IfCard, IfSelect, type IfOption } from "@/components/ui/infloww";
import { fanReportQuery, useFanReport, type FanGrowthRow, type FanReportSort } from "@/hooks/useStats";
import { useWeekStart } from "@/lib/appliedSettings";
import { fmtCentsBlankZero, fmtInt } from "@/lib/format";
import { EXTRA_LABEL } from "@/lib/openinflowwwwExtras";
import { utcOffsetLabel } from "@/lib/utcOffset";
import { cn } from "@/lib/utils";

export type EarningsBasis = "gross" | "net";

const SORTS: IfOption<FanReportSort>[] = [
  { value: "total", label: "Rank by total spend" },
  { value: "tips", label: "Rank by tips" },
  { value: "ppv", label: "Rank by PPV sales" },
  // The relay ranks by subscription spend, not by Subscription length (Infloww's fourth ranking).
  { value: "subs", label: "Rank by subscriptions" },
];
const GRANS: { value: Gran; label: string }[] = [
  { value: "hour", label: "Shown by hour" }, { value: "day", label: "Shown by day" },
  { value: "week", label: "Shown by week" }, { value: "month", label: "Shown by month" },
];
const BASES: IfOption<EarningsBasis>[] = [
  { value: "gross", label: "Gross earnings" },
  { value: "net", label: "Net earnings" },
];
// Infloww's comparison colours (Employee reports' charts).
const ALL_COLOR = "#3467FF";
const RENEW_COLOR = "#2AD4AC";
const NEW_COLOR = "#FFA15F";
const NO_NET = "No net figure: the traffic read gives gross spend only";
const GROSS_ONLY = "Gross: the fan report has a net figure for Total spend only, none per kind";
const TOTAL_FANS_TIP = "Not wired: no daily subscriber count is stored, so there is no history of active fans or auto-renew changes to draw.";

/** Whole days since a naive-UTC ISO instant, or "—". */
function subDays(iso: string | null): string {
  if (!iso) return "—";
  const at = Date.parse(/[zZ]|[+-]\d\d:?\d\d$/.test(iso) ? iso : `${iso}Z`);
  if (Number.isNaN(at)) return "—";
  const days = Math.max(0, Math.floor((Date.now() - at) / 86_400_000));
  return `${days} ${days === 1 ? "day" : "days"}`;
}

/** The day `n` days after YYYY-MM-DD `day`. */
function addDays(day: string, n: number): string {
  const [y, m, d] = day.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d + n)).toISOString().slice(0, 10);
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** A bucket's x label from its first day: "Oct 12", or "Oct 2026" by month (Employee reports' wording). */
function bucketLabel(day: string, gran: Gran): string {
  const month = MONTHS[Number(day.slice(5, 7)) - 1];
  return gran === "month" ? `${month} ${day.slice(0, 4)}` : `${month} ${Number(day.slice(8, 10))}`;
}

/** The first day of `day`'s bucket: itself, its week's first day, or the 1st of its month. */
function bucketStart(day: string, gran: Gran, weekStart: "monday" | "sunday"): string {
  if (gran === "month") return `${day.slice(0, 8)}01`;
  if (gran !== "week") return day;
  const [y, m, d] = day.split("-").map(Number);
  const weekday = new Date(Date.UTC(y, m - 1, d)).getUTCDay();
  return addDays(day, -(weekStart === "sunday" ? weekday : (weekday + 6) % 7));
}

/** The New fans chart over every day from `first` to `last` (the window's days, else the rows' own span): the
 *  daily rows summed per bucket, zero where a day has none. */
export function growthSeries(
  rows: FanGrowthRow[], gran: Gran, weekStart: "monday" | "sunday", first?: string | null, last?: string | null,
): { labels: string[]; lines: ChartLine[] } {
  const days = rows.map((r) => r.day).sort();
  const from = first ?? days[0];
  const to = last ?? days[days.length - 1];
  const byDay = new Map(rows.map((r) => [r.day, r]));
  const buckets = new Map<string, { n: number; r: number }>();
  for (let day = from; from && to && day <= to; day = addDays(day, 1)) {
    const key = bucketStart(day, gran, weekStart);
    const b = buckets.get(key) ?? { n: 0, r: 0 };
    b.n += byDay.get(day)?.new_fans ?? 0;
    b.r += byDay.get(day)?.renewed_fans ?? 0;
    buckets.set(key, b);
  }
  const sums = [...buckets.values()];
  return {
    labels: [...buckets.keys()].map((k) => bucketLabel(k, gran)),
    lines: [
      { name: "All", color: ALL_COLOR, values: sums.map((b) => b.n + b.r) },
      { name: "Renews", color: RENEW_COLOR, values: sums.map((b) => b.r) },
      { name: "New subscribers", color: NEW_COLOR, values: sums.map((b) => b.n) },
    ],
  };
}

/** A table body's one full-width row: the loading line or antd's simple empty. */
function TableNote({ span, loading }: { span: number; loading: boolean }) {
  return (
    <tr>
      <td colSpan={span}>
        {loading
          ? <p className="py-8 text-center text-[14px] text-muted">Loading…</p>
          : <EmptyState size="sm" />}
      </td>
    </tr>
  );
}

export default function FanReportsCard({ from, to, fromDay, toDay, accountId, timeZone = null, range }: {
  /** The window's instants (useReportRange). */
  from: string | null;
  to: string | null;
  /** The window's first and last calendar days, the chart's x axis; the rows' own span when absent. */
  fromDay?: string | null;
  toDay?: string | null;
  /** The picked Creator. */
  accountId: string;
  /** The report time zone the relay buckets `growth` in. */
  timeZone?: string | null;
  /** The page's range box, first in the filter row. */
  range?: ReactNode;
}) {
  const weekStart = useWeekStart();
  const [sort, setSort] = useState<FanReportSort>("total");
  const [picked, setPicked] = useState<Gran>("day");
  const [basis, setBasis] = useState<EarningsBasis>("gross");
  const q = useFanReport(from, to, accountId, sort);

  const csv = fanReportQuery(from, to, accountId, sort);
  csv.set("format", "csv");

  const days = from && to ? rangeDays(from, to) : 30;
  const gran = granShown(picked, days);
  const top = q.data?.top_fans ?? [];
  const traffic = q.data?.traffic ?? [];
  const series = growthSeries(q.data?.growth ?? [], gran, weekStart, fromDay, toDay);
  const loading = q.isPending;
  const net = basis === "net";

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        {range}
        <IfSelect<Gran> aria-label="Shown by" className="w-[160px]" value={gran} onChange={setPicked}
          options={GRANS.map((g) => ({
            ...g,
            disabled: g.value === "hour" || !granAllowed(g.value, days),
            title: g.value === "hour" ? "The fan report is read by day" : undefined,
          }))} />
        <IfSelect<EarningsBasis> aria-label="Earnings" className="w-[160px]" value={basis} onChange={setBasis} options={BASES} />
      </div>

      {q.isError ? (
        <EmptyState kind="error" text="Failed to load" onRetry={() => void q.refetch()} className="py-24" />
      ) : (
        <>
          <IfCard
            aria-label="New fans (growth & trends)"
            title={
              <>
                New fans (growth &amp; trends)
                <span title="The report time zone the days are counted in" suppressHydrationWarning
                  className="ml-3 rounded px-2 text-[14px] font-normal leading-6 text-[#2ad4ac] bg-[#2ad4ac]/15">
                  {utcOffsetLabel(timeZone)}
                </span>
              </>
            }
            info="Fans whose subscription began (New subscribers) and fans who renewed (Renews), per bucket."
          >
            <div className="mt-4">
              <LineChart labels={series.labels} lines={loading ? null : series.lines} message={loading ? "Loading…" : ""}
                fmt={fmtInt} valueFmt={fmtInt} />
            </div>
          </IfCard>

          <IfCard aria-label="Total fans (growth & trends)" title="Total fans (growth & trends)" info={TOTAL_FANS_TIP}>
            <div title="not wired" aria-disabled="true" data-testid="total-fans-not-wired" className="mt-4">
              <ul className="flex flex-wrap gap-4 text-xs text-fg-dim opacity-50">
                {["Active fans", "Turned auto-renew on", "Turned auto-renew off"].map((l) => <li key={l}>{l}</li>)}
              </ul>
              <EmptyState className="py-10" />
            </div>
          </IfCard>

          <IfCard aria-label="Traffic earnings" title="Traffic earnings"
            info="The window's spend by the free trial link or promotion each fan claimed, cleared and pending.">
            <div className="mt-4 overflow-x-auto">
              <table className={IF_TABLE.table}>
                <thead>
                  <tr>
                    <th className={cn(IF_TABLE.th, IF_TABLE.thDivider)}>Source</th>
                    <th className={cn(IF_TABLE.th, IF_TABLE.thDivider, "text-right")}>Fans</th>
                    <th className={cn(IF_TABLE.th, IF_TABLE.thDivider, "text-right")}>Earnings</th>
                  </tr>
                </thead>
                <tbody>
                  {traffic.map((t) => (
                    <tr key={`${t.account_id}:${t.kind}:${t.of_id}`} className={IF_TABLE.row}>
                      <td className={IF_TABLE.td}>
                        <div>
                          {t.kind == null
                            ? "No link"
                            : t.name || `${t.kind === "trial" ? "Free trial link" : "Promotion"} #${t.of_id}`}
                        </div>
                        <div className="text-xs text-fg-dim">
                          {[t.kind === "trial" ? "Free trial link" : t.kind === "promo" ? "Promotion" : null,
                            t.source].filter(Boolean).join(" · ")}
                        </div>
                      </td>
                      <td className={cn(IF_TABLE.td, "text-right tabular-nums")}>{fmtInt(t.fans)}</td>
                      <td className={cn(IF_TABLE.td, "text-right tabular-nums")} title={net ? NO_NET : undefined}>
                        {net ? "-" : fmtCentsBlankZero(t.total_cents)}
                      </td>
                    </tr>
                  ))}
                  {(loading || traffic.length === 0) && <TableNote span={3} loading={loading} />}
                </tbody>
              </table>
            </div>
          </IfCard>

          <IfCard
            aria-label="Top fans"
            title="Top fans"
            info="Spend in the window, cleared and pending. Top 100."
            extra={
              <div className="flex items-center gap-3">
                <IfSelect<FanReportSort> aria-label="Rank by" className="w-[200px]" value={sort} onChange={setSort} options={SORTS} />
                <CsvExportButton path="/admin/stats/fan-report" query={csv.toString()} look="infloww"
                  label="Download report" title="Download the Top fans ranking as CSV (the whole ranking, up to 50,000 rows)" />
              </div>
            }
          >
            <div className="mt-4 overflow-x-auto">
              <table className={IF_TABLE.table}>
                <thead>
                  <tr>
                    <th className={cn(IF_TABLE.th, IF_TABLE.thDivider)}>Fan name</th>
                    <th className={cn(IF_TABLE.th, IF_TABLE.thDivider, "text-right")}>Total spend</th>
                    <th className={cn(IF_TABLE.th, IF_TABLE.thDivider, "text-right")} title={net ? GROSS_ONLY : undefined}>
                      {net ? "Tips (gross)" : "Tips"}
                    </th>
                    <th className={cn(IF_TABLE.th, IF_TABLE.thDivider, "text-right")} title={net ? GROSS_ONLY : undefined}>
                      {net ? "PPV sales (gross)" : "PPV sales"}
                    </th>
                    <th className={cn(IF_TABLE.th, IF_TABLE.thDivider, "text-right")}>Subscription length</th>
                    <th className={cn(IF_TABLE.th, IF_TABLE.thDivider, "text-right")}
                      title={net ? `${EXTRA_LABEL}. ${GROSS_ONLY}` : EXTRA_LABEL}>
                      {net ? "Subscriptions (gross)" : "Subscriptions"}
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {top.map((f) => (
                    <tr key={`${f.account_id}:${f.fan_id}`} className={IF_TABLE.row}>
                      <td className={IF_TABLE.td}>
                        <div>{f.fan_name || f.username || f.fan_id}</div>
                        {f.username && <div className="text-xs text-fg-dim">@{f.username}</div>}
                      </td>
                      <td className={cn(IF_TABLE.td, "text-right tabular-nums font-medium")} data-testid="total-spend">
                        {fmtCentsBlankZero(net ? f.net_or_80_cents : f.total_cents)}
                      </td>
                      <td className={cn(IF_TABLE.td, "text-right tabular-nums")}>{fmtCentsBlankZero(f.tips_cents)}</td>
                      <td className={cn(IF_TABLE.td, "text-right tabular-nums")}>{fmtCentsBlankZero(f.ppv_cents)}</td>
                      <td className={cn(IF_TABLE.td, "text-right tabular-nums text-fg-dim")}>{subDays(f.subscribed_at)}</td>
                      <td className={cn(IF_TABLE.td, "text-right tabular-nums")}>{fmtCentsBlankZero(f.subs_cents)}</td>
                    </tr>
                  ))}
                  {(loading || top.length === 0) && <TableNote span={6} loading={loading} />}
                </tbody>
              </table>
            </div>
          </IfCard>
        </>
      )}
    </div>
  );
}
