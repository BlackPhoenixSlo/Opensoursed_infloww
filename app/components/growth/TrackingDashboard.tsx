"use client";

import { GitMerge, Tag } from "lucide-react";

import { CreatorFilter, FilterSelect, Switch, Tip, Unreachable, useMetaFilter, useReportTz } from "@/components/growth/LinksListFrame";
import { DASH, PARTIAL, TIPS, count, cvr, linkAverages, money } from "@/components/growth/linkMetrics";
import { hasNetCols, useLinks, type TabProps } from "@/components/growth/TrackingLinksList";
import { cn } from "@/lib/utils";

/** The date and time the relay's read landed, in the report time zone. */
function readStamp(at: number, tz: string | null): string {
  return new Date(at).toLocaleString(undefined, {
    timeZone: tz ?? undefined, year: "numeric", month: "short", day: "numeric", hour: "numeric", minute: "2-digit",
  });
}

/** The read's totals for one Creator; null while there is no read to sum. `earnings` (every link, deactivated ones
 *  too: their money was earned) is null until some link has a figure; `partial` when some link has none, or net
 *  leaves transactions out. */
type Totals = { clicks: number; subscribers: number; earnings: number | null; partial: boolean } | null;

type Averages = ReturnType<typeof linkAverages>;
const orNull = (v: string): string | null => (v === DASH ? null : v);

/**
 * #77: the seven cards in the capture's order. Total clicks, Total subs and the overall Subscription CVR are sums
 * over the read; Total earnings over the earnings read. Avg CPC, Avg CPS and Avg ROI are ours (Infloww does not say
 * how it averages): pooled over the links with a Promo cost, deactivated ones too (their cost was spent), after the
 * Source and Tag filters: Σcost / Σclicks, Σcost / Σsubs, and (Σearnings − Σcost) / Σcost × 100 over the costed links
 * with an earnings figure, net or gross as the toggle says ("—" with no costed link or a divisor of 0).
 */
const KPIS: Array<{ title: string; tip?: string; value: (t: NonNullable<Totals>, a: Averages) => string | null }> = [
  { title: "Total clicks", value: (t) => count(t.clicks) },
  { title: "Avg CPC", tip: TIPS.cpc, value: (_t, a) => orNull(a.cpc) },
  { title: "Total subs", value: (t) => count(t.subscribers) },
  { title: "Avg CPS", tip: TIPS.cps, value: (_t, a) => orNull(a.cps) },
  { title: "Subscription CVR", tip: TIPS.cvr, value: cvr },
  { title: "Total earnings", value: (t) => (t.earnings == null ? null : money(t.earnings) + (t.partial ? PARTIAL : "")) },
  { title: "Avg ROI", tip: TIPS.roi, value: (_t, a) => (a.roi === DASH ? null : a.roi + (a.roiPartial ? PARTIAL : "")) },
];

const PARTIAL_TITLE: Record<string, string> = {
  "Total earnings": "Partial: some links have no earnings figure, or net leaves out transactions OnlyFans has no net for yet",
  "Avg ROI": "Partial: some links with a Promo cost have no earnings figure, or net leaves out transactions OnlyFans has no net for yet",
};

export function Dashboard({ accountId, onAccountChange, net, onNet }: TabProps) {
  const { q, links: all } = useLinks(accountId, net);
  const mf = useMetaFilter();
  const links = all.filter(mf.keep);
  const { reportTz } = useReportTz();
  const ofAvailable = q.data?.of_available ?? false;
  // No read, or OnlyFans unreachable: "—", never a zero that reads as a real total. Clicks and subs are over the
  // live links, as they were before the read carried the deactivated ones; earnings are over every link.
  const totals: Totals = q.data && ofAvailable
    ? links.reduce<NonNullable<Totals>>(
      (t, l) => ({
        clicks: t.clicks + (l.is_deleted ? 0 : l.clicks),
        subscribers: t.subscribers + (l.is_deleted ? 0 : l.subscribers),
        earnings: l.earnings_cents == null ? t.earnings : (t.earnings ?? 0) + l.earnings_cents,
        partial: t.partial || l.earnings_cents == null || !!l.earnings_partial,
      }),
      { clicks: 0, subscribers: 0, earnings: null, partial: false },
    )
    : null;
  const averages = linkAverages(links);

  return (
    <div className="px-4 pt-4 mb-4">
      {/* #80: Creator, Source, Tag and Show net earnings (`LinkDashboardFilters`, index.9f50f370.js @13976167). */}
      <div className="flex flex-wrap items-center gap-x-4">
        <CreatorFilter accountId={accountId} onAccountChange={onAccountChange} />
        <FilterSelect label="Source" icon={GitMerge} options={q.data?.sources ?? []} value={mf.source} onChange={mf.setSource} />
        <FilterSelect label="Tag" icon={Tag} options={q.data?.tags ?? []} value={mf.tag} onChange={mf.setTag} />
        {/* Drawn once a net-aware column has data, as on Links list (`hasNetCols`). */}
        {hasNetCols(all, reportTz) && <Switch label="Show net earnings" on={net} onChange={onNet} />}
      </div>
      {!q.isLoading && !ofAvailable && <Unreachable className="mb-4" />}
      {/* #78, #79: 32% wide, 16px apart, 16px under the filters; a 20px title over a 48px mono value. */}
      <div className="flex flex-wrap gap-4">
        {KPIS.map((k) => {
          const v = totals ? k.value(totals, averages) : null;
          const partial = k.title === "Total earnings" ? !!totals?.partial : k.title === "Avg ROI" && averages.roiPartial;
          return (
            <div
              key={k.title}
              data-kpi
              className="w-full sm:w-[32%] p-4 rounded-xl bg-panel"
            >
              <div className="mb-4 h-5 leading-5 font-medium">{k.title}{k.tip && <Tip text={k.tip} />}</div>
              <div
                title={v != null && partial ? PARTIAL_TITLE[k.title] : undefined}
                className={cn(
                  "h-12 text-[48px] leading-[48px] font-mono font-normal truncate tabular-nums",
                  v != null ? "text-fg" : "text-fg-dim",
                )}
              >
                {v ?? "—"}
              </div>
            </div>
          );
        })}
      </div>
      {/* #80: "Last updated: " under the cards, right-aligned, 16px down (`LinkDashboardUpdateInfo`, @13977563): when
          the relay's read of OnlyFans landed, in the report time zone, as the Links list's update row says. */}
      <p className="mt-4 text-right text-sm text-fg-dim">
        <span>Last updated: {q.dataUpdatedAt > 0 ? readStamp(q.dataUpdatedAt, reportTz) : "—"}</span>
      </p>
    </div>
  );
}
