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
import { useId, useMemo, useState } from "react";
import { keepPreviousData, useIsFetching, useQueries, useQueryClient } from "@tanstack/react-query";
import { Info as InfoCircle, RefreshCw, Tag } from "lucide-react";

import { useActionAllowed } from "@/components/shell/useGrantedPages";
import { type Gran, granShown } from "@/components/stats/chart";
import { type ExportChoice } from "@/components/stats/ExportMenu";
import { Skeleton, TableSkeleton } from "@/components/ui/Skeleton";
import { useReferralRevenue } from "@/hooks/useReferrals";
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

import CreatorOverview from "./CreatorOverview";
import CreatorPerformance from "./CreatorPerformance";
import { DateRangePill, FILTER_FIELD, FiltersPill, ShownBySelect } from "./ReportsControls";
import {
  type Chan, type ColCtx, type Money, type RangeKey, type RevResp, type Tab, CHANNELS, DEFAULT_COLS, DEFAULT_RANGE,
  LEDGER_ROWS, STAT_COLS, TABS, creatorDayRows, creatorName, creatorRows, dailyOf, datePresets, daysFrom, grossOf, hoursOf,
  isTab, netMissingNote, netOf, readOf, referralsUnavailableNote, rollUp, sumKinds, totalOf, viewOf, wholeHistory,
} from "./reportsMath";

// The kind bucketing's home moved to reportsMath.ts; CompetitorReports.bucket.test.ts still reads it here.
export { bucketOf } from "./reportsMath";

const BG_CTX: RelayContext = { priority: "background" };

/** A revenue query's key slot holding its `include_net` flag, which `placeholderData` compares across a switch. */
const NET_SLOT = 5;
/* A revenue query for the selection (none when it is empty); "__all__" sends no account_id. `reversed` reads the
   chargebacks and refunds in place of the earnings (#170). */
function revenueQuery(
  kind: "day" | "hour" | "kind" | "hour_of_week", id: string, f: string | null, t: string | null, n: boolean,
  reversed = false,
) {
  return {
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
      prevQuery?.queryKey[NET_SLOT] === n ? keepPreviousData(prev) : undefined,
  };
}

/** Write `?tab=` back, keeping every other parameter and the hash. The state argument is `null`, as
 *  `stripSearchParam` in MessagesPro.tsx explains: Next's patched replaceState then syncs its router. */
function writeTabParam(tab: Tab) {
  const url = new URL(window.location.href);
  url.searchParams.set("tab", tab);
  window.history.replaceState(null, "", url.pathname + url.search + url.hash);
}

/* ── main component ── */

/** Creator reports' own range, in the report time zone: the last 7 days through today to start with (#21), kept here
 *  so the other reports' shared `useReportRange` keeps its 30-day default. A preset's days are derived each render,
 *  so they follow the report time zone; `ready` is false until the Applied settings answer. */
function useCreatorRange() {
  // The preset and the custom days change together, in one set; the custom days stay while a preset is picked.
  const [{ preset, custom }, setRange] = useState<{ preset: RangeKey; custom: { from: string | null; to: string | null } }>(
    { preset: DEFAULT_RANGE, custom: { from: null, to: null } },
  );
  const applied = useAppliedSettings();
  const reportTz = applied.data?.preferences?.report_tz ?? null;
  const [from, to]: [string | null, string | null] =
    preset === "custom" ? [custom.from, custom.to]
    : datePresets(reportTz).find((p) => p.key === preset)?.days ?? [null, null];
  const handleRange = (f: string | null, t: string | null, p: RangeKey) =>
    setRange((r) => ({ preset: p, custom: p === "custom" ? { from: f, to: t } : r.custom }));
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
    // The Applied settings (the report's time zone) are still in flight: the report's rows as placeholder bars, so
    // the page is not blank (the page frame has no surface of its own to show a bare pulse on).
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
  const totalCents = useMemo(() => totalOf(buckets), [buckets]);
  // The ledger's Gross earnings stays gross with net on: a net read still carries each row's `total_cents`.
  const grossCents = useMemo(
    () => totalOf(sumKinds([...revByKindQueries, { data: refRev.kind }], grossOf)),
    [revByKindQueries, refRev],
  );
  // Its rows off the net read: OnlyFans' own per-sale fee and VAT, and the net total.
  const netLedger: Partial<Record<(typeof LEDGER_ROWS)[number], number>> = useMemo(() => {
    const sum = (money: Money) => totalOf(sumKinds(revByKindQueries, money));
    return { "Platform fee": sum((r) => r.fee_cents ?? 0), "VAT collected": sum((r) => r.vat_cents ?? 0), "Net earnings": totalCents };
  }, [revByKindQueries, totalCents]);
  const prior = useMemo(() => {
    if (!wholeHistory(revPriorQueries)) return null;
    const b = sumKinds([...revPriorQueries, { data: refPriorRev.kind }], money);
    return { ...b, total: totalOf(b) };
  }, [revPriorQueries, refPriorRev, money]);

  /* creator table — filtered to selection */
  const visibleCreators = useMemo(() => {
    if (isAll) return allModels;
    return allModels.filter((m) => selectedIds!.has(m.account_id));
  }, [isAll, allModels, selectedIds]);

  /* The Overview's state: an error first, then a read still pending, then no Creator in the selection. */
  // The referrals read never holds the Overview; failed, it counts $0.00 under a note, never an error.
  const view = viewOf([perModel, ...revByDayQueries, ...revByKindQueries, ...revByHourQueries], visibleCreators.length > 0);

  const trendPoints = useMemo(() => rollUp(trendSrc.slots, trendSrc.d.total, trendPeriod), [trendSrc, trendPeriod]);
  // #74: a line per picked channel, every one when none is picked.
  const channelLines = useMemo(
    () => CHANNELS
      .filter((c) => chanPick.size === 0 || chanPick.has(c.key))
      .map((c) => ({ ...c, points: rollUp(chanSrc.slots, chanSrc.d.byChan(c.key), chanPeriod) })),
    [chanSrc, chanPeriod, chanPick],
  );

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
              models={allModels.map((m) => ({ id: m.account_id, name: creatorName(m) }))}
              selected={selectedIds}
              onChange={setSelectedIds}
            />
          </>
        ) : (
          /* #27 to #29: on Creator performance the "Shown by" select takes their place. */
          <ShownBySelect value={perfPeriod} days={dayDates.length} onPick={setPerfGran} />
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
          {netMissingNote(netMissing, "net earnings")}
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
        <CreatorPerformance
          ids={ids} perModel={perModel} hideZero={hideZero} setHideZero={setHideZero} perfAll={perfAll} perfList={perfList}
          picked={picked} setPickedId={setPickedId} exportAllowed={exportAllowed} exportPerf={exportPerf}
          perfChan={perfChan} setPerfChan={setPerfChan} perfView={perfView} perfRetry={perfRetry} perfPoints={perfPoints}
          perfBuckets={perfBuckets} perfPrior={perfPrior} perfDaily={perfDaily} perfHeat={perfHeat}
          perfChargebacks={perfChargebacks}
        />
      )}

      {/* #42, #43: the Overview, 16px sides: Earnings summary, Earnings trends, the channel row, Creator statistics. */}
      {tab === "overview" && (
        <CreatorOverview
          ids={ids} view={view} totalCents={totalCents} buckets={buckets} prior={prior} trendGran={trendGran}
          setTrendGran={setTrendGran} dayDates={dayDates} trendPoints={trendPoints} chanPick={chanPick}
          setChanPick={setChanPick} chanGran={chanGran} setChanGran={setChanGran} channelLines={channelLines}
          from={from} to={to} net={net} buildExport={buildExport} perModel={perModel} visibleCreators={visibleCreators}
          visibleCols={visibleCols} setVisibleCols={setVisibleCols} orderedCols={orderedCols} colCtx={colCtx}
          grossCents={grossCents} netLedger={netLedger}
        />
      )}
    </div>
  );
}
