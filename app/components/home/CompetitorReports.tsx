"use client";


import Link from "next/link";
import { useId, useMemo, useReducer, useState } from "react";
import { keepPreviousData, useIsFetching, useQueries, useQueryClient } from "@tanstack/react-query";
import { RefreshCw } from "lucide-react";

import { useActionAllowed } from "@/components/shell/useGrantedPages";
import { granShown } from "@/components/stats/chart";
import { type ExportChoice } from "@/components/stats/ExportMenu";
import { Skeleton, TableSkeleton } from "@/components/ui/Skeleton";
import { referralsGap, referralsShown, useReferralRevenue } from "@/hooks/useReferrals";
import IngestHealthBanner from "@/components/stats/IngestHealthBanner";
import PerModelKpiGrid from "@/components/stats/PerModelKpiGrid";
import { usePerModel } from "@/hooks/useStats";
import { useTabParam } from "@/hooks/useTabParam";
import { useAppliedSettings } from "@/lib/appliedSettings";
import { priorRange, toLocalIso } from "@/lib/dateRange";
import { EXTRA_LABEL, EXTRAS_OVERFLOW_LABEL } from "@/lib/openinflowwwwExtras";
import { relay, type RelayContext } from "@/lib/relay";
import { type Section, exportSections } from "@/lib/reportExport";
import { utcOffsetLabel } from "@/lib/utcOffset";
import { cn } from "@/lib/utils";

import styles from "./CreatorReports.module.css";

import CreatorOverview from "./CreatorOverview";
import CreatorPerformance from "./CreatorPerformance";
import { INITIAL_FILTERS, creatorReportsFiltersReducer } from "./creatorReportsFilters";
import { colsOf } from "./creatorCols";
import { netMissingNote } from "./netMissingNote";
import { useCreatorCols } from "./useCreatorCols";
import { DateRangePill, ReportFilters, ShownBySelect } from "./ReportsControls";
import {
  type Chan, type ColCtx, type Money, type RevResp, type Tab, CHANNELS,
  LEDGER_ROWS, STAT_COLS, TABS, creatorDayRows, creatorName, creatorRows, dailyOf, datePresets, daysFrom, grossOf, hoursOf,
  chargebacksCents, forGrowth, isTab, netOf, readOf, referralsUnavailableNote, rollUp, sumKinds, totalGrowthOf, totalOf,
  viewOf, wholeHistory,
} from "./reportsMath";
import { InfoTip } from "@/components/ui/InfoTip";

export { bucketOf } from "./reportsMath";

const BG_CTX: RelayContext = { priority: "background" };

const NET_SLOT = 5;
function revenueQuery(
  kind: "day" | "hour" | "kind" | "hour_of_week", id: string, f: string | null, t: string | null, n: boolean,
  reversed = false,
) {
  return {
    queryKey: ["competitor", `revenue-${kind}`, id, f, t, n, reversed] as const,
    queryFn: () => {
      const qs = new URLSearchParams(kind === "day" || kind === "hour" ? { group_by: kind, by_kind: "true" } : { group_by: kind });
      if (n) qs.set("include_net", "true");
      if (reversed) qs.set("status", "reversed");
      if (f) qs.set("from", f);
      if (t) qs.set("to", t);
      if (id !== "__all__") qs.set("account_id", id);
      return relay.get<RevResp>(`/admin/stats/revenue?${qs.toString()}`, BG_CTX);
    },
    staleTime: 60_000,
    // Never across the net switch: a gross answer has no net_cents and would read as $0 net.
    placeholderData: (prev: RevResp | undefined, prevQuery?: { queryKey: readonly unknown[] }) =>
      prevQuery?.queryKey[NET_SLOT] === n ? keepPreviousData(prev) : undefined,
  };
}

// State arg is null (see stripSearchParam in MessagesPro.tsx): Next's patched replaceState then syncs its router.
function writeTabParam(tab: Tab) {
  const url = new URL(window.location.href);
  url.searchParams.set("tab", tab);
  window.history.replaceState(null, "", url.pathname + url.search + url.hash);
}


function useCreatorRange() {
  const [filters, dispatch] = useReducer(creatorReportsFiltersReducer, INITIAL_FILTERS);
  const { preset, custom } = filters;
  const applied = useAppliedSettings();
  const reportTz = applied.data?.preferences?.report_tz ?? null;
  const [from, to]: [string | null, string | null] =
    preset === "custom" ? [custom.from, custom.to]
    : datePresets(reportTz).find((p) => p.key === preset)?.days ?? [null, null];
  return {
    preset, from, to, selectedIds: filters.selectedIds, gran: filters.gran, dispatch,
    fromIso: toLocalIso(from, false, reportTz),
    toIso: toLocalIso(to, true, reportTz),
    reportTz,
    ready: !applied.isPending,
  };
}

type Frame = "card" | "page";

export default function CompetitorReports({ frame = "card" }: { frame?: Frame } = {}) {
  const range = useCreatorRange();
  if (!range.ready) {
    return (
      <div className={cn("p-4", frame === "card" && "rounded-md border")} aria-busy="true"
        style={frame === "card" ? { background: "var(--color-panel)", borderColor: "var(--color-border)" } : undefined}>
        <div className="mb-4 flex flex-wrap items-center gap-2">
          <Skeleton className="h-8 w-48" />
          <Skeleton className="ml-auto h-8 w-24" />
        </div>
        <TableSkeleton rows={6} />
      </div>
    );
  }
  return <CreatorReportsCard range={range} frame={frame} />;
}

type CreatorRange = ReturnType<typeof useCreatorRange>;

function CreatorReportsCard({ range, frame }: { range: CreatorRange; frame: Frame }) {
  const { preset, from, to, fromIso, toIso, reportTz, selectedIds, gran, dispatch } = range;
  const [chanPick, setChanPick] = useState<Set<Chan>>(() => new Set());
  const [tab, setTab] = useState<Tab>("overview");
  useTabParam("tab", isTab, setTab);
  const [extrasOpen, setExtrasOpen] = useState(false);
  const [colKeys, setColKeys, retryCols] = useCreatorCols();
  const [perfChan, setPerfChan] = useState<Chan | "all">("all");
  const [pickedId, setPickedId] = useState<string | null>(null);
  const [hideZero, setHideZero] = useState(true);
  const [net, setNet] = useState(true);
  const money = net ? netOf : grossOf;
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
  const reset = () => dispatch({ type: "reset" });

  const qc = useQueryClient();
  const fetchingStats = useIsFetching({ queryKey: ["stats"] });
  const fetchingReports = useIsFetching({ queryKey: ["competitor"] });
  const fetching = fetchingStats + fetchingReports > 0;
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["stats"] });
    qc.invalidateQueries({ queryKey: ["competitor"] });
  };
  const zone = reportTz ?? Intl.DateTimeFormat().resolvedOptions().timeZone;

  const dayDates = useMemo(() => daysFrom(from, to), [from, to]);

  const perModel = usePerModel(fromIso, toIso, { engagement: true });
  const allModels = perModel.data?.per_model ?? [];

  const isAll = selectedIds === null;
  const effectiveIds: string[] = useMemo(() => {
    if (isAll) return ["__all__"];
    return selectedIds!.size ? [Array.from(selectedIds!).sort().join(",")] : [];
  }, [isAll, selectedIds]);

  const priorDays = priorRange(from, to);
  const priorFromIso = toLocalIso(priorDays?.[0] ?? null, false, reportTz);
  const priorToIso = toLocalIso(priorDays?.[1] ?? null, true, reportTz);

  const revByDayQueries = useQueries({ queries: effectiveIds.map((id) => revenueQuery("day", id, fromIso, toIso, net)) });
  const revByKindQueries = useQueries({ queries: effectiveIds.map((id) => revenueQuery("kind", id, fromIso, toIso, net)) });
  const revPriorQueries = useQueries({
    queries: effectiveIds.map((id) => revenueQuery("kind", id, priorFromIso, priorToIso, net)),
  });
  const revReversedQueries = useQueries({
    queries: effectiveIds.map((id) => revenueQuery("kind", id, fromIso, toIso, net, true)),
  });
  // Referrals come from OF's own read (no transaction carries them); the ledger's figures never wait on them.
  const { now: refs, before: refsPrior, rev: refRev, priorRev: refPriorRev } =
    useReferralRevenue([from, to], priorDays ?? [null, null], effectiveIds[0], effectiveIds.length > 0);
  const refGap = referralsGap(refs);
  const refsShown = referralsShown(refs);

  const daily = useMemo(
    () => dailyOf([...revByDayQueries, { data: refRev.day }], dayDates, money),
    [revByDayQueries, refRev, dayDates, money],
  );

  const period = granShown(gran, dayDates.length);
  const hourSlots = useMemo(() => hoursOf(dayDates), [dayDates]);
  const revByHourQueries = useQueries({
    queries: period === "hour"
      ? effectiveIds.map((id) => revenueQuery("hour", id, fromIso, toIso, net)) : [],
  });
  const hourly = useMemo(() => dailyOf(revByHourQueries, hourSlots, money), [revByHourQueries, hourSlots, money]);
  const trendSrc = useMemo(() => (period === "hour" ? { slots: hourSlots, d: hourly } : { slots: dayDates, d: daily }),
    [period, hourSlots, hourly, dayDates, daily]);

  const buckets = useMemo(
    () => sumKinds([...revByKindQueries, { data: refRev.kind }], money),
    [revByKindQueries, refRev, money],
  );
  const cbCents = useMemo(() => chargebacksCents(revReversedQueries, money), [revReversedQueries, money]);
  const totalCents = useMemo(() => totalOf(buckets), [buckets]);
  // The ledger's Gross earnings stays gross with net on: a net read still carries each row's total_cents.
  const grossCents = useMemo(
    () => totalOf(sumKinds([...revByKindQueries, { data: refRev.kind }], grossOf)),
    [revByKindQueries, refRev],
  );
  const netLedger: Partial<Record<(typeof LEDGER_ROWS)[number], number>> = useMemo(() => {
    const sum = (money: Money) => totalOf(sumKinds(revByKindQueries, money));
    return { "Platform fee": sum((r) => r.fee_cents ?? 0), "VAT collected": sum((r) => r.vat_cents ?? 0), "Net earnings": totalCents };
  }, [revByKindQueries, totalCents]);
  const totalGrowth = totalGrowthOf(refs, refsPrior);
  const growthNow = useMemo(() => forGrowth({ ...buckets, total: totalCents }, totalGrowth), [buckets, totalCents, totalGrowth]);
  const prior = useMemo(() => {
    if (!wholeHistory(revPriorQueries)) return null;
    const b = sumKinds([...revPriorQueries, { data: refPriorRev.kind }], money);
    return forGrowth({ ...b, total: totalOf(b) }, totalGrowth);
  }, [revPriorQueries, refPriorRev, money, totalGrowth]);

  const visibleCreators = useMemo(() => {
    if (isAll) return allModels;
    return allModels.filter((m) => selectedIds!.has(m.account_id));
  }, [isAll, allModels, selectedIds]);

  const view = viewOf([perModel, ...revByDayQueries, ...revByKindQueries, ...revByHourQueries],
    visibleCreators.length > 0);
  const chargebacksView = viewOf(revReversedQueries, visibleCreators.length > 0);

  const trendPoints = useMemo(() => rollUp(trendSrc.slots, trendSrc.d.total, period), [trendSrc, period]);
  const channelLines = useMemo(
    () => CHANNELS
      .filter((c) => (chanPick.size === 0 || chanPick.has(c.key)) && (c.key !== "referrals" || refsShown))
      .map((c) => ({ ...c, points: rollUp(trendSrc.slots, trendSrc.d.byChan(c.key), period) })),
    [trendSrc, period, chanPick, refsShown],
  );

  const ctxFor = (n: boolean): ColCtx => ({
    hours: dayDates.length * 24,
    agencyCents: allModels.reduce((a, m) => a + (n ? m.total_net_revenue_cents : m.total_revenue_cents), 0),
    net: n,
  });
  const colCtx = ctxFor(net);
  const netMissing = net && revByKindQueries.every((q) => q.isSuccess)
    ? [...revByKindQueries, ...revReversedQueries.filter((q) => q.isSuccess)]
      .reduce((n, q) => n + (q.data?.rows ?? []).reduce((a, r) => a + (r.net_missing_count ?? 0), 0), 0)
    : 0;
  const orderedCols = useMemo(() => colsOf(colKeys), [colKeys]);

  const perfAll = visibleCreators;
  const perfList = hideZero ? perfAll.filter((m) => m.total_revenue_cents > 0) : perfAll;
  const picked = perfList.find((m) => m.account_id === pickedId) ?? perfList[0] ?? null;
  const perfIds = tab === "performance" && picked ? [picked.account_id] : [];
  const perfHour = period === "hour";
  const perfTimeQueries = useQueries({
    queries: perfIds.map((id) => revenueQuery(perfHour ? "hour" : "day", id, fromIso, toIso, net)),
  });
  const perfKindQueries = useQueries({ queries: perfIds.map((id) => revenueQuery("kind", id, fromIso, toIso, net)) });
  const perfPriorQueries = useQueries({
    queries: perfIds.map((id) => revenueQuery("kind", id, priorFromIso, priorToIso, net)),
  });
  const perfReversedQueries = useQueries({
    queries: perfIds.map((id) => revenueQuery(perfHour ? "hour" : "day", id, fromIso, toIso, net, true)),
  });
  const perfHeatQueries = useQueries({ queries: perfIds.map((id) => revenueQuery("hour_of_week", id, fromIso, toIso, net)) });
  const { now: perfRefs, before: perfRefsPrior, rev: perfRefRev, priorRev: perfRefPriorRev } =
    useReferralRevenue([from, to], priorDays ?? [null, null], perfIds[0], perfIds.length > 0);
  const perfReads = [...perfTimeQueries, ...perfKindQueries, ...perfReversedQueries, ...perfHeatQueries];
  const perfView = viewOf([perModel, ...perfReads], !!picked);
  const perfRetry = () => {
    if (perModel.isError) perModel.refetch();
    for (const q of [...perfReads, ...perfPriorQueries, perfRefs, perfRefsPrior]) q.refetch();
  };
  const perfSlots = perfHour ? hourSlots : dayDates;
  const perfDaily = useMemo(
    () => dailyOf([...perfTimeQueries, { data: perfRefRev.day }], perfSlots, money),
    [perfTimeQueries, perfRefRev, perfSlots, money],
  );
  const perfPoints = useMemo(
    () => rollUp(perfSlots, perfChan === "all" ? perfDaily.total : perfDaily.byChan(perfChan), period),
    [perfSlots, perfDaily, perfChan, period],
  );
  const perfHeat = useMemo(
    () => perfHeatQueries.flatMap((q) => q.data?.rows ?? [])
      .map((r) => ({ weekday: r.weekday ?? 0, hour: r.hour ?? 0, value: money(r) })),
    [perfHeatQueries, money],
  );
  const perfChargebacks = useMemo(
    () => rollUp(perfSlots, dailyOf(perfReversedQueries, perfSlots, money).total, period),
    [perfReversedQueries, perfSlots, money, period],
  );
  const perfBuckets = useMemo(
    () => sumKinds([...perfKindQueries, { data: perfRefRev.kind }], money),
    [perfKindQueries, perfRefRev, money],
  );
  const perfChargebacksCents = useMemo(() => chargebacksCents(perfReversedQueries, money), [perfReversedQueries, money]);
  const perfGrowth = totalGrowthOf(perfRefs, perfRefsPrior);
  const perfPrior = useMemo(
    () => (wholeHistory(perfPriorQueries)
      ? forGrowth(sumKinds([...perfPriorQueries, { data: perfRefPriorRev.kind }], money), perfGrowth) : null),
    [perfPriorQueries, perfRefPriorRev, money, perfGrowth],
  );
  const exportPerf = () => void exportSections(`creator-performance_${from ?? ""}_${to ?? ""}`, "Creator performance",
    [{ title: "Total", rows: creatorRows(orderedCols, perfList, colCtx) }], "csv");
  const exportAllowed = useActionAllowed("export");
  const buildExport = async (c: ExportChoice): Promise<Section[]> => {
    const ctx = ctxFor(c.net);
    const sections: Section[] = [];
    if (c.displays.includes("total")) {
      const cols = c.allFields ? STAT_COLS.filter((col) => readOf(col, ctx)) : orderedCols;
      sections.push({ title: "Total", rows: creatorRows(cols, visibleCreators, ctx) });
    }
    if (c.displays.includes("day")) {
      const read = async (id: string): Promise<{ earned: RevResp; reversed: RevResp }> => {
        const [earned, reversed] = await Promise.all([
          qc.fetchQuery(revenueQuery("day", id, fromIso, toIso, c.net)),
          qc.fetchQuery(revenueQuery("day", id, fromIso, toIso, c.net, true)),
        ]);
        return { earned, reversed };
      };
      sections.push({ title: "By day", rows: await creatorDayRows(visibleCreators, dayDates, c.net, read) });
    }
    return sections;
  };

  return (
    <div
      // overflow-clip, not overflow-hidden: hidden would trap the statistics header's sticky top.
      className={cn(styles.report, frame === "card" && "rounded-md overflow-clip border")}
      style={{
        ...(frame === "card" ? { background: "var(--color-panel)", borderColor: "var(--color-border)" } : {}),
        color: "var(--color-fg)",
      }}
    >
      <header className="flex flex-wrap items-center justify-between gap-2 p-4">
        <div className="flex flex-wrap items-center min-w-0">
          <h1 className="text-2xl font-medium leading-[1.1667]" style={{ color: "var(--color-fg)" }}>
            Creator reports
          </h1>
          <span className="mx-2 flex items-center text-sm" style={{ color: "var(--color-fg-dim)" }}>
            <span className="mr-2" title={zone} suppressHydrationWarning>{utcOffsetLabel(zone)}</span>
            <InfoTip text="Set by your organization" iconClassName="h-4 w-4" />
          </span>
        </div>
        <div className="flex items-center gap-2">
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

      <div className={styles.toolbar}>
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

      <div role="group" aria-label="Report controls" className={styles.toolbarControls}>
        <DateRangePill
          from={from}
          to={to}
          preset={preset}
          reportTz={reportTz}
          onChange={(f, t) => dispatch({ type: "custom", from: f, to: t })}
          onPreset={(key) => dispatch(key === "custom" ? { type: "custom", from, to } : { type: "preset", preset: key })}
        />
        <ShownBySelect
          value={period}
          days={dayDates.length}
          onPick={(g) => dispatch({ type: "gran", gran: g })}
        />
        <select aria-label="Earnings basis" value={net ? "net" : "gross"}
          onChange={(e) => setNet(e.target.value === "net")}>
          <option value="net">Net earnings</option>
          <option value="gross">Gross earnings</option>
        </select>
        <ReportFilters
          models={allModels.map((m) => ({ id: m.account_id, name: creatorName(m) }))}
          selected={selectedIds} onChange={(ids) => dispatch({ type: "select", ids })} onReset={reset}
        />
      </div>
      </div>
      {netMissing > 0 && (
        <p title={EXTRA_LABEL} className="px-4 pb-2 text-[12px] leading-[17px]" style={{ color: "var(--color-fg-dim)" }}>
          {netMissingNote(netMissing, "net earnings")}
        </p>
      )}
      {refGap !== "none" && (
        <p title={EXTRA_LABEL} className="px-4 pb-2 text-[12px] leading-[17px]" style={{ color: "var(--color-fg-dim)" }}>
          {referralsUnavailableNote(refs.data?.unavailable?.length ?? null)}
        </p>
      )}

      {tab === "performance" && (
        <CreatorPerformance
          ids={ids} perModel={perModel} hideZero={hideZero} setHideZero={setHideZero} perfAll={perfAll} perfList={perfList}
          picked={picked} setPickedId={setPickedId} exportAllowed={exportAllowed} exportPerf={exportPerf}
          perfChan={perfChan} setPerfChan={setPerfChan} perfView={perfView} perfRetry={perfRetry} perfPoints={perfPoints}
          perfBuckets={perfBuckets} perfPrior={perfPrior} perfDaily={perfDaily} perfHeat={perfHeat}
          perfChargebacks={perfChargebacks} perfChargebacksCents={perfChargebacksCents}
          perfRefsShown={referralsShown(perfRefs)} perfRefsGap={referralsGap(perfRefs)}
        />
      )}

      {tab === "overview" && (
        <CreatorOverview
          ids={ids} view={view} totalCents={totalCents} buckets={buckets} prior={prior} growthNow={growthNow}
          totalGrowth={totalGrowth}
          trendPoints={trendPoints} chanPick={chanPick} setChanPick={setChanPick} channelLines={channelLines}
          from={from} to={to} net={net} buildExport={buildExport} perModel={perModel} visibleCreators={visibleCreators}
          colKeys={colKeys} setColKeys={setColKeys} retryCols={retryCols} orderedCols={orderedCols} colCtx={colCtx}
          grossCents={grossCents} netLedger={netLedger} chargebacksCents={cbCents}
          chargebacksView={chargebacksView} referralsGap={refGap}
          referralsShown={refsShown}
        />
      )}
    </div>
  );
}
