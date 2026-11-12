"use client";

import { useId } from "react";
import { GitMerge, Tag } from "lucide-react";

import { SectionTitle, StatCard } from "@/components/home/ReportsCharts";
import { CreatorFilter, FilterSelect, Switch, Unreachable, useMetaFilter, useReportTz } from "@/components/growth/LinksListFrame";
import { DASH, PARTIAL, TIPS, count, cvr, linkAverages, money } from "@/components/growth/linkMetrics";
import { hasNetCols, useLinks, type TabProps } from "@/components/growth/TrackingLinksList";
import { EXTRA_LABEL } from "@/lib/openinflowwwwExtras";

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

type Kpi = { title: string; tip?: string; value: (t: NonNullable<Totals>, a: Averages, cost: number) => string | null };

/**
 * #77's seven cards, laid out as the Analytics pages' Creator statistics cards (owner: the Dashboard reads like the
 * rest of Analytics): "Performance" (Total clicks, Total subs, Subscription CVR, Total earnings), then "Promo cost"
 * (ours: Total promo cost, then Avg CPC, Avg CPS and Avg ROI). Total clicks, Total subs and the overall Subscription
 * CVR are sums over the read; Total earnings over the earnings read. Avg CPC, Avg CPS and Avg ROI are ours (Infloww
 * does not say how it averages): pooled over the links with a Promo cost, deactivated ones too (their cost was
 * spent), after the Source and Tag filters: Σcost / Σclicks, Σcost / Σsubs, and (Σearnings − Σcost) / Σcost × 100
 * over the costed links with an earnings figure, net or gross as the toggle says ("—" with no costed link or a
 * divisor of 0).
 */
const PERFORMANCE: Kpi[] = [
  { title: "Total clicks", value: (t) => count(t.clicks) },
  { title: "Total subs", value: (t) => count(t.subscribers) },
  { title: "Subscription CVR", tip: TIPS.cvr, value: cvr },
  { title: "Total earnings", value: (t) => (t.earnings == null ? null : money(t.earnings) + (t.partial ? PARTIAL : "")) },
];
const COST: Kpi[] = [
  { title: "Total promo cost", tip: `${EXTRA_LABEL}: the Promo cost set on the links, added up`, value: (_t, _a, c) => (c ? money(c) : null) },
  { title: "Avg CPC", tip: TIPS.cpc, value: (_t, a) => orNull(a.cpc) },
  { title: "Avg CPS", tip: TIPS.cps, value: (_t, a) => orNull(a.cps) },
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
  const ids = { perf: useId(), cost: useId() };
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
  // Every costed link, deactivated ones too, as the averages pool them.
  const cost = links.reduce((c, l) => c + (l.promo_cost_cents && l.promo_cost_cents > 0 ? l.promo_cost_cents : 0), 0);

  const cards = (kpis: Kpi[], label: string) => (
    <ul aria-label={label} className="flex flex-col md:flex-row gap-4 md:gap-0">
      {kpis.map((k) => {
        const v = totals ? k.value(totals, averages, cost) : null;
        const partial = k.title === "Total earnings" ? !!totals?.partial : k.title === "Avg ROI" && averages.roiPartial;
        return (
          <StatCard key={k.title} label={k.title} tip={k.tip} value={v ?? DASH}
            valueTitle={v != null && partial ? PARTIAL_TITLE[k.title] : undefined} />
        );
      })}
    </ul>
  );

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
      <div className="flex flex-col gap-8">
        <section aria-labelledby={ids.perf}>
          <SectionTitle id={ids.perf} label="Performance"
            tip="Clicks, subscribers and earnings of the Creator's tracking links, after the Source and Tag filters" />
          {cards(PERFORMANCE, "Performance cards")}
        </section>
        <section aria-labelledby={ids.cost}>
          <SectionTitle id={ids.cost} label="Promo cost"
            tip="What the links cost and returned, over the links with a Promo cost (set it with Edit on Links list)" />
          {cards(COST, "Promo cost cards")}
          {!cost && totals && (
            <p className="mt-3 text-sm text-fg-dim">Add a promo cost to links (Edit on Links list) to see these.</p>
          )}
        </section>
      </div>
      {/* #80: "Last updated: " under the cards, right-aligned, 16px down (`LinkDashboardUpdateInfo`, @13977563): when
          the relay's read of OnlyFans landed, in the report time zone, as the Links list's update row says. */}
      <p className="mt-4 text-right text-sm text-fg-dim">
        <span>Last updated: {q.dataUpdatedAt > 0 ? readStamp(q.dataUpdatedAt, reportTz) : "—"}</span>
      </p>
    </div>
  );
}
