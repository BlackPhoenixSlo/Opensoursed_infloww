"use client";

/** Redirect links' stats: each row's 7-day sparkline and a link's expanded analytics (daily click bars, Opened in /
 *  Came from / Country). Days are the report zone's (the API's `tz`). The shapes come from redirectStats.ts; the reads
 *  from useGrowth. The summary cards are RedirectLinksPanel's StatCards. */

import { BlankChart, ChartAxes, ChartMessage, niceMax, plotFrame, useChartWidth } from "@/components/stats/chart";
import { EmptyState, IfSegmented } from "@/components/ui/infloww";
import { count } from "@/components/growth/linkMetrics";
import {
  CAME_FROM, OPENED_IN, RANGES, SPARK_W, breakdownRows, countryLabel, dayLabel, hasCountries, sparkBars,
  type BreakdownRow, type StatsDays,
} from "@/components/growth/redirectStats";
import { useTrackingAnalytics, type TrackingAnalytics, type TrackingLink } from "@/hooks/useGrowth";

/** A row's last 7 days: 7 bars in 56 x 20, a zero day a 1px baseline. */
export function ClickSparkline({ values, message = "Loading…" }: { values: number[] | undefined; message?: string }) {
  if (!values) return <span className="w-14 text-center text-[10px] text-fg-dim" aria-label={message}>{message}</span>;
  return (
    <svg width={SPARK_W} height={20} viewBox={`0 0 ${SPARK_W} 20`} role="img" className="shrink-0"
      aria-label={`Last 7 days: ${values.join(", ")}`}>
      {sparkBars(values).map((b, i) => (
        <rect key={i} x={b.x} y={b.y} width={b.w} height={b.h} rx={b.zero ? 0 : 1}
          className={b.zero ? "fill-border" : "fill-accent"} />
      ))}
    </svg>
  );
}

/** A link's daily clicks: chart.tsx's axes, bars drawn as the reports' TrendBars (80% of the slot). */
function ClickBars({ series, message }: { series: TrackingAnalytics["series"] | null; message?: string }) {
  const [ref, W] = useChartWidth();
  const H = W < 640 ? 160 : 200;
  const f = plotFrame(W, H);
  const n = series?.length ?? 0;
  const max = niceMax(Math.max(4, ...(series ?? []).map((d) => d.clicks)), 4);
  const slot = (f.R - f.L) / Math.max(1, n);
  const raw = slot * 0.8;
  const bw = Math.min(48, raw > 1 ? Math.floor(raw) : raw);
  const xAt = (i: number) => f.L + slot * (i + 0.5);
  return (
    <div ref={ref} className="relative">
      {message && <ChartMessage message={message} />}
      <svg width="100%" height={H} viewBox={`0 0 ${W} ${H}`} className="block">
        {series ? <ChartAxes W={W} H={H} max={max} labels={series.map((d) => dayLabel(d.day))} xAt={xAt} fmt={count} /> : <BlankChart W={W} H={H} />}
        {(series ?? []).map((d, i) => {
          const h = (d.clicks / max) * (f.B - f.T);
          return (
            <rect key={d.day} data-testid="click-bar" role="img" aria-label={`${dayLabel(d.day)}: ${d.clicks} clicks`}
              x={xAt(i) - bw / 2} y={f.B - h} width={bw} height={h} className="fill-accent">
              <title>{`${dayLabel(d.day)}: ${count(d.clicks)} clicks`}</title>
            </rect>
          );
        })}
      </svg>
    </div>
  );
}

/** One breakdown: label, a bar as wide as its share, clicks and percent. */
function Breakdown({ title, rows }: { title: string; rows: BreakdownRow[] }) {
  return (
    <section aria-label={title} className="min-w-0 rounded-lg bg-panel p-3">
      <h4 className="mb-2 text-xs font-medium text-fg-dim">{title}</h4>
      <ul className="space-y-1.5">
        {rows.map((r) => (
          <li key={r.key} data-breakdown-row className="text-[12px]">
            <div className="flex items-baseline gap-2">
              <span className="min-w-0 flex-1 truncate text-fg">{r.label}</span>
              <span className="tabular-nums text-fg">{count(r.clicks)}</span>
              <span className="w-9 text-right tabular-nums text-fg-dim">{r.pct}%</span>
            </div>
            <div className="mt-0.5 h-1 rounded bg-bg-elev-2">
              <div className="h-1 rounded bg-accent" style={{ width: `${r.pct}%` }} />
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}

/** A link's expanded analytics ("Analytics" toggle): the range picker, the daily bars and the breakdowns. */
export function LinkStats({ accountId, link, days, onDays, shareUrl, botAvailable }: {
  accountId: string; link: TrackingLink; days: StatsDays; onDays: (d: StatsDays) => void; shareUrl: string;
  botAvailable: boolean;
}) {
  const q = useTrackingAnalytics(accountId, link.id, days);
  const a = q.data;
  const gated = link.bot_check && botAvailable;
  const total = a?.totals.clicks ?? 0;
  return (
    <div className="space-y-3 rounded-lg border border-border bg-bg/40 p-3" data-link-stats={link.id}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0 text-sm">
          <div className="text-fg" data-stats-header>
            {a ? <><b className="tabular-nums">{count(total)}</b> clicks · last {days} days</> : <span className="text-fg-dim">— clicks · last {days} days</span>}
          </div>
          {a && gated && <div className="text-[11px] text-fg-dim">Bot check on · {count(a.totals.verified_clicks)} clicks passed the bot check</div>}
        </div>
        <IfSegmented aria-label="Range" value={String(days) as `${StatsDays}`} onChange={(v) => onDays(Number(v) as StatsDays)}
          options={RANGES.map((d) => ({ value: String(d) as `${StatsDays}`, label: `${d} d` }))} className="shrink-0" />
      </div>
      {q.isError ? (
        <EmptyState kind="error" size="sm" text="Couldn't load the analytics" onRetry={() => void q.refetch()} />
      ) : !a ? (
        <ClickBars series={null} message="Loading…" />
      ) : total === 0 ? (
        link.click_count === 0
          ? <p className="py-6 text-center text-sm text-fg-dim">No clicks yet: share <span className="break-all text-accent">{shareUrl}</span></p>
          : <ClickBars series={null} message={`No clicks in the last ${days} days`} />
      ) : (
        <>
          <ClickBars series={a.series} />
          <div className="grid gap-3 sm:grid-cols-3">
            <Breakdown title="Opened in" rows={breakdownRows(a.opened_in, total, OPENED_IN)} />
            <Breakdown title="Came from" rows={breakdownRows(a.came_from, total, CAME_FROM)} />
            {hasCountries(a.country)
              ? <Breakdown title="Country" rows={breakdownRows(a.country, total, countryLabel)} />
              : <p className="self-center text-[11px] text-fg-dim">Countries need Cloudflare in front of this site</p>}
          </div>
        </>
      )}
    </div>
  );
}
