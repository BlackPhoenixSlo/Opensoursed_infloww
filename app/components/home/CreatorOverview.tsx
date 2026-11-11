"use client";

/** Creator reports › Overview (#42 to #153): Earnings summary, Earnings trends, Earnings by channel and Earnings
 *  breakdown, Creator statistics, and our Earnings ledger. Its state lives in CompetitorReports. */

import type { LucideIcon } from "lucide-react";

import { OnlyfansLine } from "@/components/shell/inflowwIcons";
import { LineChart, fmtDollars, fmtUsd } from "@/components/stats/chart";
import ExportMenu, { type ExportChoice } from "@/components/stats/ExportMenu";
import type { ReferralsGap } from "@/hooks/useReferrals";
import type { PerModelRow } from "@/hooks/useStats";
import { growthOf, isLoss } from "@/lib/format";
import { EXTRA_LABEL } from "@/lib/openinflowwwwExtras";
import type { Section } from "@/lib/reportExport";

import styles from "./CreatorReports.module.css";

import { CreatorTable } from "./CreatorTable";
import { CardTitle, NotWired, ReportCard, SectionTitle, StatCard, SummaryTile, TrendBars } from "./ReportsCharts";
import { CHARGEBACKS_UNAVAILABLE, REFERRALS_FAILED, TOTAL_GROWTH_EXCL, TOTAL_PARTIAL } from "./netMissingNote";
import { TILE_ICON } from "./tileIcons";
import { ChannelsPill, CustomMetricsPill, UtcChip } from "./ReportsControls";
import {
  type Bucket, type Chan, type ColCtx, type GrowthSums, type Point, type StatCol, type TotalGrowth, type View, CHANNEL_TEXT, CHANNELS, CHARGEBACKS_COLOR,
  LEDGER_ROWS,
  SUMMARY_TEXT,
  TREND_TEXT, isWait, viewOf,
} from "./reportsMath";

/** The summary's sum tiles in grid order, each channel's icon and colour from the Dashboard's one map (#5), Total on
 *  the accent; Chargebacks (its own read, no growth) follows them. */
const TILES: readonly { key: Chan | "total"; label: string; Icon: LucideIcon; rgb?: string }[] = [
  { key: "total", label: "Total earnings", Icon: OnlyfansLine },
  ...([
    ["subscriptions", "Subscriptions"], ["posts", "Posts"], ["messages", "Messages"], ["tips", "Tips"],
    ["referrals", "Referrals"],
  ] as const).map(([key, label]) => ({ key, label, ...TILE_ICON[key] })),
];
/** #101: the Creator statistics cards' tooltips, verbatim but for Total earnings: the per-model read it sums carries
 *  no OnlyFans referrals, so its tip says so. */
const STAT_TIPS = {
  creators: "Total number of creators managed by your team",
  message: "Earnings from creators’ messages during the selected time frame",
  total: "Earnings from all creators’ subscriptions, tips, posts, messages and streams during the selected time frame, OnlyFans referrals not included",
  refunded: "Amount of refunds during the selected time frame",
} as const;

export default function CreatorOverview({
  ids, view, totalCents, buckets, prior, growthNow, totalGrowth, trendPoints, chanPick, setChanPick,
  channelLines, from, to, net, buildExport, perModel, visibleCreators, visibleCols,
  setVisibleCols, orderedCols, colCtx, grossCents, netLedger, chargebacksCents, chargebacksView, referralsGap,
  referralsShown,
}: {
  ids: { summary: string; trends: string; channel: string; breakdown: string; stats: string; ledger: string };
  view: View; totalCents: number; buckets: Record<Bucket, number>;
  /** Both windows' sums as growth reads them (`forGrowth`, per `totalGrowth`): unless whole, no Referrals, and
   *  Total without referrals (`exclReferrals`) or none yet (`pending`). */
  prior: GrowthSums | null; growthNow: GrowthSums; totalGrowth: TotalGrowth;
  trendPoints: Point[];
  chanPick: Set<Chan>; setChanPick: (next: Set<Chan>) => void;
  channelLines: ((typeof CHANNELS)[number] & { points: Point[] })[];
  from: string | null; to: string | null; net: boolean; buildExport: (c: ExportChoice) => Promise<Section[]>;
  perModel: { isPending: boolean; isError: boolean }; visibleCreators: PerModelRow[];
  visibleCols: Set<string>; setVisibleCols: (next: Set<string>) => void;
  orderedCols: readonly StatCol[]; colCtx: ColCtx; grossCents: number;
  netLedger: Partial<Record<(typeof LEDGER_ROWS)[number], number>>;
  /** Chargebacks' figure, below zero, and its reversed read's state, outside `view`: pending or failed, only
   *  Chargebacks' figures show "-". */
  chargebacksCents: number; chargebacksView: View;
  /** How much of OnlyFans' referrals read is missing: all, Referrals shows "-"; any, Total is marked partial. */
  referralsGap: ReferralsGap;
  /** Whether Referrals has a figure (`referralsShown`): not, its tile, legend row and line wait ("-"), Total shows the
   *  sales without it; `referralsGap` says why (the failure title, Total's partial mark). */
  referralsShown: boolean;
}) {
  const ready = view === "ready";
  const cbShown = ready && !isWait(chargebacksView);
  /* #101: the Creator statistics cards; "-" until the per-model read answers with a Creator in the selection. */
  const statsView = viewOf([perModel], visibleCreators.length > 0);
  const messageEarnings = visibleCreators.reduce((a, m) => a + (m.revenue_by_kind?.ppv ?? 0), 0);
  // With net on, a Creator's total is the per-model read's net total; it has no net by kind.
  const totalEarningsAcrossCreators =
    visibleCreators.reduce((a, m) => a + (net ? m.total_net_revenue_cents : m.total_revenue_cents), 0);
  const refundedGross = visibleCreators.reduce((a, m) => a + (m.refunded_cents ?? 0), 0);
  const refundedAcrossCreators = net
    ? visibleCreators.reduce((a, m) => a + (m.refunded_net_cents ?? 0), 0) : refundedGross;
  /* Each channel’s share of total channel earnings. */
  const chanSum = CHANNELS.reduce((a, c) => a + buckets[c.key], 0);
  /* The summary tiles' rows: Chargebacks has its own read (its own wait and error) and no growth. */
  const refsFailed = referralsGap === "all";
  const NO_GROWTH = { text: "-", dir: null };
  const tiles = [
    ...TILES.map((t) => {
      const total = t.key === "total";
      const failed = t.key === "referrals" && refsFailed;
      const blank = isWait(view) || (t.key === "referrals" && !referralsShown);
      const now = growthNow[t.key];
      const growth = !ready || blank || now === undefined ? NO_GROWTH : growthOf(now, prior?.[t.key]);
      return {
        ...t,
        cents: t.key === "total" ? totalCents : buckets[t.key],
        blank,
        growth,
        title: !isWait(view) && failed ? REFERRALS_FAILED : undefined,
        partial: total && !isWait(view) && referralsGap !== "none" ? TOTAL_PARTIAL : undefined,
        growthTitle: total && totalGrowth === "exclReferrals" && growth.text !== "-" ? TOTAL_GROWTH_EXCL : undefined,
      };
    }),
    {
      key: "chargebacks", label: "Chargebacks", ...TILE_ICON.chargebacks,
      cents: chargebacksCents,
      blank: isWait(view) || isWait(chargebacksView),
      growth: NO_GROWTH,
      title: !isWait(view) && chargebacksView === "error" ? CHARGEBACKS_UNAVAILABLE : undefined,
      partial: undefined,
      growthTitle: undefined,
    },
  ];
  /* The legend's rows: the channels with their share, then Chargebacks (no share, its own read). */
  const legend = [
    ...CHANNELS.map((c) => ({ ...c, cents: buckets[c.key], share: true, shown: ready && (c.key !== "referrals" || referralsShown) })),
    { key: "chargebacks", label: "Chargebacks", color: CHARGEBACKS_COLOR, cents: chargebacksCents, share: false, shown: cbShown },
  ];
  return (
    <div className={styles.overview}>
    {/* #46 to #60: Earnings summary, a card of seven tiles in four columns. */}
    <section aria-labelledby={ids.summary}>
      <SectionTitle
        id={ids.summary}
        label="Earnings summary"
        tip="An overview of total earnings based on your managed creators during this period"
      />
      <ReportCard className={styles.summary}>
        <dl className={styles.summaryGrid}>
          {/* The summary grid positions Tips beneath Subscriptions. */}
          {tiles.map((t) => (
            <SummaryTile
              key={t.key}
              label={t.label}
              Icon={t.Icon}
              rgb={t.rgb}
              total={t.key === "total"}
              negative={!t.blank && isLoss(t.cents)}
              title={t.title}
              partial={t.partial}
              // With no Creator the reads' zeros, "$0".
              value={t.blank ? "-" : fmtDollars(t.cents)}
              growth={t.growth}
              growthTitle={t.growthTitle}
            />
          ))}
        </dl>
        {isWait(view) && (
          <p title={EXTRA_LABEL} className="mt-4 text-sm" style={{ color: "var(--color-fg-dim)" }}>{SUMMARY_TEXT[view]}</p>
        )}
      </ReportCard>
    </section>

    {/* #61 to #67: Earnings trends, a 220px bar chart in the toolbar's "Shown by" bucket (#4). */}
    <section aria-labelledby={ids.trends}>
      <ReportCard className={styles.trends}>
        <CardTitle
          id={ids.trends}
          label="Earnings trends"
          tip="Sales growth and trends of all earnings from your managed creators"
        />
        <div className="mt-2">
          <TrendBars points={ready ? trendPoints : null} message={isWait(view) ? TREND_TEXT[view] : ""} />
        </div>
      </ReportCard>
    </section>

    {/* #68: the channel row, 32px below, Earnings by channel and Earnings breakdown at either end. */}
    <div className={styles.channels}>
      {/* #69 to #75: Earnings by channel (Inventory §3.4, C[H276166]), one of Infloww's sections. */}
      <section aria-labelledby={ids.channel} className="min-w-0">
        <ReportCard className={styles.channelCard}>
          <div className="min-w-0">
            <CardTitle
              id={ids.channel}
              className="mb-2"
              label="Earnings by channel"
              tip="Track trends and growth of your managed creators’ earning channels"
            />
            <div className="flex flex-wrap items-center justify-between gap-2">
              <ChannelsPill picked={chanPick} onChange={setChanPick} />
            </div>
            <div className="mt-2">
              {/* #74, #81, #83: a 250px chart of 2px lines, one per channel given; the breakdown's legend names them. */}
              <LineChart
                height={190}
                labels={trendPoints.map((p) => p.label)}
                lines={ready && channelLines.length > 0
                  ? channelLines.map((c) => ({ name: c.label, color: c.color, values: c.points.map((p) => p.value) })) : null}
                // Only Referrals picked and it has no figure: why, not empty axes (as Creator performance's chart).
                message={isWait(view) ? CHANNEL_TEXT[view]
                  : channelLines.length > 0 ? "" : refsFailed ? REFERRALS_FAILED : SUMMARY_TEXT.loading}
                messageTitle={EXTRA_LABEL}
                valueFmt={fmtUsd}
                legend={false}
              />
            </div>
          </div>
        </ReportCard>
      </section>
      {/* Channel shares and totals sit beside the line chart. */}
      <section aria-labelledby={ids.breakdown} className={styles.legend}>
        <ReportCard className={styles.channelCard}>
          <div className="min-w-0">
            <h3 id={ids.breakdown} className="sr-only">Earnings breakdown</h3>

            <ul
              aria-label="Earnings breakdown legend"
              className="grid grid-cols-[1fr_max-content_max-content] gap-x-6 gap-y-1 text-sm leading-[1.1429]"
            >
              {legend.map((c) => (
                <li key={c.key} className="contents">
                  <span className="flex items-center font-medium" style={{ color: "var(--color-fg-dim)" }}>
                    <span className="w-2 h-2 rounded-full mr-2 shrink-0" style={{ background: c.color }} aria-hidden />
                    {c.label}
                  </span>
                  {/* Chargebacks has no share of the earnings: "-". */}
                  <span className="text-right" style={{ color: "var(--color-fg)" }}>
                    {ready && c.share ? `${(chanSum > 0 ? (100 * c.cents) / chanSum : 0).toFixed(2)}%` : "-"}
                  </span>
                  <span className="text-right" style={{ color: c.shown && isLoss(c.cents) ? "var(--color-err)" : "var(--color-fg)" }}>
                    {c.shown ? fmtDollars(c.cents) : "-"}
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
      <div className={styles.statisticsHeader}>
        <h2 id={ids.stats} className="text-xl font-medium leading-[1.2]" style={{ color: "var(--color-fg)" }}>
          Creator statistics
        </h2>
        <CustomMetricsPill visible={visibleCols} onChange={setVisibleCols} />
        {/* #88, #89: the bundle's Export pop-up; ours downloads at once (W5 5.9). */}
        <ExportMenu fileName={`creator-reports_${from ?? ""}_${to ?? ""}`} sheet="Creator reports"
          displays={["total", "day"]} fields net={net} build={buildExport} className="self-start" />
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

      <CreatorTable creators={visibleCreators} cols={orderedCols} ctx={colCtx} view={statsView} />

      {/* #94 to #100: the notice, two lines with 6px dots, the second carrying the UTC chip. */}
      <div className="mt-3 rounded-lg border px-3 py-2" style={{ borderColor: "var(--color-border)" }}>
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
  );
}
