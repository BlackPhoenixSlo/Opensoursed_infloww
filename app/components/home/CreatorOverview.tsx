"use client";

/** Creator reports › Overview (#42 to #153): Earnings summary, Earnings trends, Earnings by channel and Earnings
 *  breakdown, Creator statistics, and our Earnings ledger. Its state lives in CompetitorReports. */

import { CircleDollarSign, MessageCircle, RefreshCw, StickyNote, UserRoundPlus, Video, type LucideIcon } from "lucide-react";

import { OnlyfansLine } from "@/components/shell/inflowwIcons";
import { type Gran, LineChart, fmtDollars, fmtUsd } from "@/components/stats/chart";
import ExportMenu, { type ExportChoice } from "@/components/stats/ExportMenu";
import type { PerModelRow } from "@/hooks/useStats";
import { growthOf } from "@/lib/format";
import { EXTRA_LABEL } from "@/lib/openinflowwwwExtras";
import type { Section } from "@/lib/reportExport";

import { CreatorTable } from "./CreatorTable";
import { CardTitle, Donut, NotWired, ReportCard, SectionTitle, StatCard, SummaryTile, TrendBars } from "./ReportsCharts";
import { ChannelsPill, CustomMetricsPill, GranularityTabs, UtcChip } from "./ReportsControls";
import {
  type Bucket, type Chan, type ColCtx, type Point, type StatCol, type View, CHANNEL_TEXT, CHANNELS, LEDGER_ROWS, SUMMARY_TEXT,
  TREND_TEXT, isWait, viewOf,
} from "./reportsMath";

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
/** #101: the Creator statistics cards' tooltips, verbatim. */
const STAT_TIPS = {
  creators: "Total number of creators managed by your team",
  message: "Earnings from creators’ messages during the selected time frame",
  total: "Earnings from all creators’ subscriptions, tips, posts, messages, streams and referrals during the selected time frame",
  refunded: "Amount of refunds during the selected time frame",
} as const;

export default function CreatorOverview({
  ids, view, totalCents, buckets, prior, trendGran, setTrendGran, dayDates, trendPoints, chanPick, setChanPick,
  chanGran, setChanGran, channelLines, from, to, net, buildExport, perModel, visibleCreators, visibleCols,
  setVisibleCols, orderedCols, colCtx, grossCents, netLedger,
}: {
  ids: { summary: string; trends: string; channel: string; breakdown: string; stats: string; ledger: string };
  view: View; totalCents: number; buckets: Record<Bucket, number>; prior: (Record<Bucket, number> & { total: number }) | null;
  trendGran: Gran; setTrendGran: (g: Gran) => void; dayDates: string[]; trendPoints: Point[];
  chanPick: Set<Chan>; setChanPick: (next: Set<Chan>) => void; chanGran: Gran; setChanGran: (g: Gran) => void;
  channelLines: ((typeof CHANNELS)[number] & { points: Point[] })[];
  from: string | null; to: string | null; net: boolean; buildExport: (c: ExportChoice) => Promise<Section[]>;
  perModel: { isPending: boolean; isError: boolean }; visibleCreators: PerModelRow[];
  visibleCols: Set<string>; setVisibleCols: (next: Set<string>) => void;
  orderedCols: readonly StatCol[]; colCtx: ColCtx; grossCents: number;
  netLedger: Partial<Record<(typeof LEDGER_ROWS)[number], number>>;
}) {
  const ready = view === "ready";
  /* #101: the Creator statistics cards; "-" until the per-model read answers with a Creator in the selection. */
  const statsView = viewOf([perModel], visibleCreators.length > 0);
  const messageEarnings = visibleCreators.reduce((a, m) => a + (m.revenue_by_kind?.ppv ?? 0), 0);
  // With net on, a Creator's total is the per-model read's net total; it has no net by kind.
  const totalEarningsAcrossCreators =
    visibleCreators.reduce((a, m) => a + (net ? m.total_net_revenue_cents : m.total_revenue_cents), 0);
  const refundedGross = visibleCreators.reduce((a, m) => a + (m.refunded_cents ?? 0), 0);
  const refundedAcrossCreators = net
    ? visibleCreators.reduce((a, m) => a + (m.refunded_net_cents ?? 0), 0) : refundedGross;
  /* #75, #85: the donut's channels, their share of the channels' sum */
  const chanSum = CHANNELS.reduce((a, c) => a + buckets[c.key], 0);
  return (
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
            const tile = (
              <SummaryTile
                key={t.key}
                label={t.label}
                Icon={t.Icon}
                total={t.key === "total"}
                // With no Creator the reads' zeros, "$0".
                value={isWait(view) ? "-" : fmtDollars(cents)}
                growth={ready ? growthOf(cents, prior?.[t.key]) : { text: "-", dir: null }}
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
            <Donut slices={ready ? CHANNELS.map((c) => ({ color: c.color, cents: buckets[c.key] })) : null} />
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
                    {ready ? `${(chanSum > 0 ? (100 * buckets[c.key]) / chanSum : 0).toFixed(2)}%` : "-"}
                  </span>
                  <span className="text-right" style={{ color: "var(--color-fg)" }}>
                    {ready ? fmtDollars(buckets[c.key]) : "-"}
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
  );
}
