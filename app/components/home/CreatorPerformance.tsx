"use client";

/** Creator reports › Creator performance (#154 to #174): the creator list at the left and the picked Creator's
 *  Earnings, Earnings breakdown, Earnings heatmap and Chargebacks at the right. Its state lives in CompetitorReports. */

import { ArrowDownLeft, ArrowUpRight, Upload } from "lucide-react";

import { ChargebacksChart, EarningsHeatmap } from "@/components/home/CreatorPerfCharts";
import { fmtDollars } from "@/components/stats/chart";
import { EmptyState } from "@/components/ui/infloww";
import type { PerModelRow } from "@/hooks/useStats";
import { growthOf } from "@/lib/format";
import { EXTRA_LABEL } from "@/lib/openinflowwwwExtras";

import { Donut, PerfTitle, Sparkline, TrendBars } from "./ReportsCharts";
import { type Bucket, type Chan, type Point, type View, CHANNELS, NO_CREATORS, SUMMARY_TEXT, creatorName, dailyOf } from "./reportsMath";

/** #161: the Creator performance Earnings block's channel buttons, All first. */
const PERF_CHANNELS: readonly { key: Chan | "all"; label: string }[] = [
  { key: "all", label: "All" },
  { key: "subscriptions", label: "Subscriptions" },
  { key: "tips", label: "Tips" },
  { key: "posts", label: "Posts" },
  { key: "messages", label: "Messages" },
  { key: "referrals", label: "Referrals" },
  { key: "streams", label: "Streams" },
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

export default function CreatorPerformance({
  ids, perModel, hideZero, setHideZero, perfAll, perfList, picked, setPickedId, exportAllowed, exportPerf,
  perfChan, setPerfChan, perfView, perfRetry, perfPoints, perfBuckets, perfPrior, perfDaily, perfHeat, perfChargebacks,
}: {
  ids: { perfEarnings: string; perfBreakdown: string; perfHeatmap: string; perfChargebacks: string };
  perModel: { isPending: boolean; isError: boolean };
  hideZero: boolean; setHideZero: (v: boolean) => void;
  perfAll: PerModelRow[]; perfList: PerModelRow[]; picked: PerModelRow | null; setPickedId: (id: string) => void;
  exportAllowed: boolean; exportPerf: () => void;
  perfChan: Chan | "all"; setPerfChan: (c: Chan | "all") => void;
  perfView: View; perfRetry: () => void;
  perfPoints: Point[]; perfBuckets: Record<Bucket, number>; perfPrior: Record<Bucket, number> | null;
  perfDaily: ReturnType<typeof dailyOf>; perfHeat: { weekday: number; hour: number; value: number }[]; perfChargebacks: Point[];
}) {
  const perfReady = perfView === "ready";
  /* #172 to #174: a failed block's `AbnormalRequestError` in the block's place, centred in its height: the error art,
     "Request failed" and a primary Retry (the bundle's words are i18n keys loaded at run time). */
  const perfFailed = (minHeight: number) => (
    <div className="flex items-center justify-center" style={{ minHeight }}>
      <EmptyState kind="error" text="Request failed" onRetry={perfRetry} />
    </div>
  );
  const perfChanSum = CHANNELS.reduce((a, c) => a + perfBuckets[c.key], 0);
  return (
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
                  {creatorName(m)}
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
                <Donut perf slices={perfReady ? CHANNELS.map((c) => ({ color: PERF_COLORS[c.key], cents: perfBuckets[c.key] })) : null} />
                <ul aria-label="Earnings breakdown legend" className="flex flex-wrap">
                  {CHANNELS.map((c) => (
                    <li key={c.key} className="w-1/3 mb-2 flex flex-col">
                      <span className="flex items-center text-xs font-semibold leading-4 tracking-[0.15px] mb-2" style={{ color: "var(--color-fg-dim)" }}>
                        <span className="w-[7px] h-[7px] rounded-full mr-1.5 shrink-0" style={{ background: PERF_COLORS[c.key] }} aria-hidden />
                        {c.label}
                      </span>
                      <span className="text-lg font-bold leading-[22px] px-2" style={{ color: "var(--color-fg)" }}>
                        {perfReady ? fmtDollars(perfBuckets[c.key]) : "-"}
                      </span>
                      <span className="text-sm font-semibold leading-5 px-2" style={{ color: "var(--color-fg-dim)" }}>
                        {perfReady ? `${(perfChanSum > 0 ? (100 * perfBuckets[c.key]) / perfChanSum : 0).toFixed(2)}%` : "-"}
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
              <ul aria-label="Earnings growth" className="md:w-[314px] border-t md:border-t-0 md:border-l" style={{ borderColor: "var(--color-border)" }}>
                {CHANNELS.map((c) => {
                  const g = perfReady ? growthOf(perfBuckets[c.key], perfPrior?.[c.key]) : { text: "-", dir: null };
                  return (
                    <li
                      key={c.key}
                      className="h-[62px] flex items-center justify-between px-[15px] border-b last:border-b-0"
                      style={{ borderColor: "var(--color-border)" }}
                    >
                      <span className="flex flex-col min-w-0">
                        {/* #166: the count, 4px from the 12px arrow, then the change. */}
                        <span className="inline-flex items-center">
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
                        </span>
                        <span className="text-xs font-semibold leading-5 capitalize max-w-[150px] truncate" style={{ color: "var(--color-fg-dim)" }}>
                          {c.label}
                        </span>
                      </span>
                      {perfReady && (
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
  );
}
