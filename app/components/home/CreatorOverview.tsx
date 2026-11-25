"use client";


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
  TREND_TEXT, colTotal, isWait, statCol, viewOf,
} from "./reportsMath";

const TILES: readonly { key: Chan | "total"; label: string; Icon: LucideIcon; rgb?: string }[] = [
  { key: "total", label: "Total earnings", Icon: OnlyfansLine },
  ...([
    ["subscriptions", "Subscriptions"], ["posts", "Posts"], ["messages", "Messages"], ["tips", "Tips"],
    ["referrals", "Referrals"],
  ] as const).map(([key, label]) => ({ key, label, ...TILE_ICON[key] })),
];
const STAT_TIPS = {
  creators: "Total number of creators managed by your team",
  message: "Earnings from creators’ messages during the selected time frame",
  total: "Earnings from all creators’ subscriptions, tips, posts, messages and streams during the selected time frame, OnlyFans referrals not included",
  refunded: "Amount of refunds during the selected time frame",
} as const;

const MESSAGE_COL = statCol("message");
const TOTAL_EARNINGS_COL = statCol("totalEarnings");
const REFUNDS_COL = statCol("refunds");

export default function CreatorOverview({
  ids, view, totalCents, buckets, prior, growthNow, totalGrowth, trendPoints, chanPick, setChanPick,
  channelLines, from, to, net, buildExport, perModel, visibleCreators, colKeys,
  setColKeys, retryCols, orderedCols, colCtx, grossCents, netLedger, chargebacksCents, chargebacksView, referralsGap,
  referralsShown,
}: {
  ids: { summary: string; trends: string; channel: string; breakdown: string; stats: string; ledger: string };
  view: View; totalCents: number; buckets: Record<Bucket, number>;
  prior: GrowthSums | null; growthNow: GrowthSums; totalGrowth: TotalGrowth;
  trendPoints: Point[];
  chanPick: Set<Chan>; setChanPick: (next: Set<Chan>) => void;
  channelLines: ((typeof CHANNELS)[number] & { points: Point[] })[];
  from: string | null; to: string | null; net: boolean; buildExport: (c: ExportChoice) => Promise<Section[]>;
  perModel: { isPending: boolean; isError: boolean }; visibleCreators: PerModelRow[];
  colKeys: string[]; setColKeys: ((next: string[]) => void) | null;
  retryCols?: (() => void) | null;
  orderedCols: readonly StatCol[]; colCtx: ColCtx; grossCents: number;
  netLedger: Partial<Record<(typeof LEDGER_ROWS)[number], number>>;
  chargebacksCents: number; chargebacksView: View;
  referralsGap: ReferralsGap;
  referralsShown: boolean;
}) {
  const ready = view === "ready";
  const cbShown = ready && !isWait(chargebacksView);
  const statsView = viewOf([perModel], visibleCreators.length > 0);
  const netByKind = visibleCreators.every((m) => m.net_revenue_by_kind);
  const messageEarnings = colTotal(MESSAGE_COL, visibleCreators, colCtx);
  const totalEarningsAcrossCreators = colTotal(TOTAL_EARNINGS_COL, visibleCreators, colCtx);
  const refundedGross = colTotal(REFUNDS_COL, visibleCreators, { ...colCtx, net: false });
  const refundedAcrossCreators = colTotal(REFUNDS_COL, visibleCreators, colCtx);
  const chanSum = CHANNELS.reduce((a, c) => a + buckets[c.key], 0);
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
  const legend = [
    ...CHANNELS.map((c) => ({ ...c, cents: buckets[c.key], share: true, shown: ready && (c.key !== "referrals" || referralsShown) })),
    { key: "chargebacks", label: "Chargebacks", color: CHARGEBACKS_COLOR, cents: chargebacksCents, share: false, shown: cbShown },
  ];
  return (
    <div className={styles.overview}>
    <section aria-labelledby={ids.summary}>
      <SectionTitle
        id={ids.summary}
        label="Earnings summary"
        tip="An overview of total earnings based on your managed creators during this period"
      />
      <ReportCard className={styles.summary}>
        <dl className={styles.summaryGrid}>
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

    <div className={styles.channels}>
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
              <LineChart
                height={190}
                labels={trendPoints.map((p) => p.label)}
                partial={trendPoints.map((p) => p.partial)}
                lines={ready && channelLines.length > 0
                  ? channelLines.map((c) => ({ name: c.label, color: c.color, values: c.points.map((p) => p.value) })) : null}
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

    <section aria-labelledby={ids.stats}>
      <div className={styles.statisticsHeader}>
        <h2 id={ids.stats} className="text-xl font-medium leading-[1.2]" style={{ color: "var(--color-fg)" }}>
          Creator statistics
        </h2>
        <CustomMetricsPill keys={colKeys} onChange={setColKeys} onRetry={retryCols} />
        <ExportMenu fileName={`creator-reports_${from ?? ""}_${to ?? ""}`} sheet="Creator reports"
          displays={["total", "day"]} fields net={net} build={buildExport} className="self-start" />
      </div>

      <ul aria-label="Creator statistics cards" className="grid grid-cols-2 gap-2 md:flex md:flex-row md:gap-0 mb-4">
        <StatCard label="Creators" tip={STAT_TIPS.creators}
          value={statsView === "ready" ? visibleCreators.length.toLocaleString("en-US") : "-"} />
        <StatCard label="Message earnings" tip={STAT_TIPS.message}
          value={net && !netByKind ? null : statsView === "ready" ? fmtDollars(messageEarnings) : "-"} />
        <StatCard label="Total earnings" tip={STAT_TIPS.total}
          value={statsView === "ready" ? fmtDollars(totalEarningsAcrossCreators) : "-"} />
        <StatCard label="Refunded" tip={STAT_TIPS.refunded}
          value={statsView === "ready" ? fmtDollars(refundedAcrossCreators) : "-"} />
      </ul>

      <CreatorTable creators={visibleCreators} cols={orderedCols} ctx={colCtx} view={statsView} />

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
                : (
                  <button type="button" disabled title="Turn on Show net earnings" aria-label={name} className="cursor-not-allowed opacity-50">
                    -
                  </button>
                )}
            </span>
            {name === "Net earnings" && (
              /* The relay's net is gross less OnlyFans' fee; VAT is OnlyFans' own figure, not deducted, so the rows do not sum. */
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
