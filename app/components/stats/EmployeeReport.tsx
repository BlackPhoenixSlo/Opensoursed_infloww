"use client";

/**
 * EmployeeReport — Analytics > Employee reports, in Infloww's legacy frame (page-parity tickets 25 and 27; live
 * `.scratch/infloww-live/08-employee-reports.png`, `09-employee-performance.png`, `10-…overview-table.png`):
 *
 *   header       the title, the report time zone's UTC offset, the icon Refresh;
 *   notice       the black sales-settings bar with "View sales settings", once above the tabs on every tab, and the
 *                Relay's attribution fallback line under it (spec phase-04, stories 46 and 54);
 *   tabs         Overview / Sales records / Employee performance, page-level, with the range box (hours, W5 5.2) and
 *                "Shown by" at the bar's right on Overview and Employee performance; Sales records brings its own
 *                toolbar (SalesRecords, ticket 28);
 *   Overview     the charts, Chatting statistics (its chatter-role checkbox in its own title row, as Infloww's), Clocked
 *                hours, then one "Inflowwww extra" heading over our own cards.
 *
 * Routes: Overview `/analytics/employee-reports`, Employee performance `?tab=performance`, Sales records keeps
 * `/analytics/sales-records` (its Permission page, role actions, the Relay's PAGE_MAP and bookmarks key on it); a tab
 * click is `router.push`, and the tab is read from the URL on every render (`useSearchParams`), so Back and Forward
 * move it too. A tab shows only when the role grants its page, so a role with Sales records alone gets the
 * frame with that one tab. Infloww's "Filters" popover is not drawn (the chart reads take no employee or creator
 * filter); "Learn more" is not built (README No work).
 *
 * The date range is owned here and threaded into every hook so the sections stay in sync: the last 30 days to
 * start with, in the Agency's report time zone, and nothing fires until the Applied settings answer
 * (useReportRange). Earnings totals include pending (uncleared) sales.
 */

import { Info, MessageSquareWarning } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";


import SalesRecords from "@/components/analytics/SalesRecords";
import { useGrantedPages } from "@/components/shell/useGrantedPages";
import ChattingStatsTable from "@/components/stats/ChattingStatsTable";
import ClockedHoursCard from "@/components/stats/ClockedHoursCard";
import CoverageHeader from "@/components/stats/CoverageHeader";
import DateRangePicker from "@/components/stats/DateRangePicker";
import {
  EmployeeOverviewCharts, EmployeePerformance, ShownBySelect, useEmployeeCharts,
} from "@/components/stats/EmployeeReportCharts";
import IngestHealthBanner from "@/components/stats/IngestHealthBanner";
import PerEmployeeTable from "@/components/stats/PerEmployeeTable";
import SalesNeedingAttributionCard from "@/components/stats/SalesNeedingAttributionCard";
import StatsRefreshButton from "@/components/stats/StatsRefreshButton";
import UnattributedDrawer from "@/components/stats/UnattributedDrawer";
import { type Gran, granShown, rangeDays } from "@/components/stats/chart";
import { IfBody, IfTabs, InflowwPageHeader } from "@/components/ui/infloww";
import { ExtraTag } from "@/components/ui/primitives";
import { useReportRange } from "@/hooks/useReportRange";
import { useChattingStats, useIngestHealth } from "@/hooks/useStats";
import { fmtTimeOnly } from "@/lib/format";
import { deniedPage } from "@/lib/nav";
import { cn } from "@/lib/utils";

export type EmployeeTab = "overview" | "sales" | "performance";

const PAGE = "/analytics/employee-reports";
const SALES = "/analytics/sales-records";
const HREF: Record<EmployeeTab, string> = { overview: PAGE, sales: SALES, performance: `${PAGE}?tab=performance` };
const GRAN_TIP = "The granularities offered depend on the length of the selected time frame";
/** The live v5.7.20 capture draws this bar's idle tabs and the range box's dates in element-emphasis-00 (#ffffff dark),
 *  brighter than the shared IfTabs' and DateRangePicker's T1, so here only they take it; hover stays M1. */
const BRIGHT_BAR = cn(
  "[&_[role=tab][aria-selected=false]:not(:disabled)]:text-nav-fg-active",
  "[&_[role=tab][aria-selected=false]:not(:disabled):hover]:text-accent",
  "[&_[aria-haspopup=dialog]]:text-nav-fg-active",
);

export default function EmployeeReport({ tab }: {
  /** The tab the route opens on: Sales records' route passes "sales"; Employee reports' reads `?tab=`. */
  tab?: EmployeeTab;
}) {
  // useSearchParams suspends while the page prerenders: the boundary keeps that to this report.
  return <Suspense fallback={null}><EmployeeReportBody routeTab={tab ?? "overview"} /></Suspense>;
}

function EmployeeReportBody({ routeTab }: { routeTab: EmployeeTab }) {
  const router = useRouter();
  const search = useSearchParams();
  const granted = useGrantedPages();
  const { preset, from, to, fromIso, toIso, priorFromIso, priorToIso, reportTz, ready, handleRange } = useReportRange();
  const tab: EmployeeTab = routeTab !== "overview" ? routeTab : search?.get("tab") === "performance" ? "performance" : "overview";
  // Only the Employees holding the built-in Chatter role (`chatter_only` on the relay).
  const [chatterOnly, setChatterOnly] = useState(false);
  const days = fromIso && toIso ? rangeDays(fromIso, toIso) : 30;
  const [picked, setPicked] = useState<Gran>("day");
  const bucket = granShown(picked, days);
  const employeePage = deniedPage(PAGE, granted) == null;
  // The fallback line rides on the Chatting statistics read the table and charts already make (one request), so it
  // is read only on their tabs and for a role with their page: Sales records never sends it.
  const stats = useChattingStats(fromIso, toIso, chatterOnly, ready && employeePage && tab !== "sales");

  const tabs = [
    ...(employeePage ? [{ value: "overview" as const, label: "Overview" }] : []),
    ...(deniedPage(SALES, granted) == null ? [{ value: "sales" as const, label: "Sales records" }] : []),
    ...(employeePage ? [{ value: "performance" as const, label: "Employee performance" }] : []),
  ];
  const go = (t: EmployeeTab) => {
    if (t !== tab) router.push(HREF[t]);
  };

  return (
    <div className="min-w-0">
      <InflowwPageHeader title="Employee reports" utc={reportTz} actions={<StatsRefreshButton />} />
      <IfBody>
        <SalesSettingsNotice fallback={stats.data?.attribution_fallback ?? null} />
        <IfTabs<EmployeeTab> aria-label="Employee reports" className={cn("mt-2 px-0", BRIGHT_BAR)} value={tab}
          onChange={go} tabs={tabs}
          extra={tab === "sales" ? undefined : (
            <>
              <DateRangePicker from={from} to={to} preset={preset} onChange={handleRange} timeZone={reportTz} hours />
              <span className="flex items-center gap-2">
                <ShownBySelect days={days} value={bucket} onChange={setPicked} />
                <span role="img" aria-label={GRAN_TIP} title={GRAN_TIP} className="cursor-help text-fg-dim">
                  <Info className="h-3.5 w-3.5" aria-hidden />
                </span>
              </span>
            </>
          )} />
        {tab === "sales" ? (
          <SalesRecords />
        ) : ready && (
          <div className="space-y-8 pt-6">
            {tab === "performance" ? (
              <Charts tab="performance" from={fromIso} to={toIso} bucket={bucket} chatterOnly={chatterOnly} />
            ) : (
              <>
                <Charts tab="overview" from={fromIso} to={toIso} bucket={bucket} chatterOnly={chatterOnly} />
                <ChattingStatsTable from={fromIso} to={toIso} priorFrom={priorFromIso} priorTo={priorToIso}
                  chatterOnly={chatterOnly} onChatterOnly={setChatterOnly} />
                <ClockedHoursCard from={fromIso} to={toIso} />
                <Extras from={fromIso} to={toIso} chatterOnly={chatterOnly} />
              </>
            )}
          </div>
        )}
      </IfBody>
    </div>
  );
}

/** A chart tab's body, mounted once the range is ready so its reads never go out without one. */
function Charts({ tab, from, to, bucket, chatterOnly }: {
  tab: "overview" | "performance"; from: string | null; to: string | null; bucket: Gran; chatterOnly: boolean;
}) {
  const charts = useEmployeeCharts(from, to, bucket, chatterOnly);
  return tab === "performance" ? <EmployeePerformance {...charts} /> : <EmployeeOverviewCharts {...charts} />;
}

/** Infloww's sales-settings bar: black, radius 4, a 14px notice glyph and line, the orange "View sales settings" at
 *  the right. "Learn more" is not built (README No work: Sales "Learn more").
 *
 *  ASSUMPTION: the link shows for every viewer, chatters included; a chatter whose Permission role denies Settings
 *  lands on the denied page, which explains itself (ticket 24). Rung 5: no per-role branch here. Overturned if the
 *  owner wants the link hidden from chatters. */
function SalesSettingsNotice({ fallback }: { fallback: string | null }) {
  return (
    <div className="space-y-1">
      <div role="note" className="flex min-h-[38px] items-center gap-3 rounded-[4px] bg-black px-3 py-1.5 text-[14px] text-white [html[data-theme=light]_&]:bg-bg-elev-1 [html[data-theme=light]_&]:text-fg">
        <MessageSquareWarning className="h-3.5 w-3.5 shrink-0" aria-hidden />
        <p className="flex-1">The sales data is based on your organization&apos;s sales settings.</p>
        <Link href="/settings/sales"
          className="shrink-0 whitespace-nowrap rounded-[4px] bg-cta px-2 py-0.5 text-[12px] font-medium text-black hover:opacity-90">
          View sales settings
        </Link>
      </div>
      {fallback && <p className="text-xs text-fg-dim">{fallback}</p>}
    </div>
  );
}

/** Ours, not Infloww's, under one heading: the ingest note and "All messages…" on its line, then the per-Creator
 *  table, the attribution cards, coverage and ingest health. */
function Extras({ from, to, chatterOnly }: {
  from: string | null; to: string | null; chatterOnly: boolean;
}) {
  const health = useIngestHealth();
  const lastIngest = (health.data?.accounts ?? [])
    .map((a) => a.last_scan_at)
    .filter((s): s is string => !!s)
    .sort()
    .pop() ?? null;
  return (
    <section aria-label="Inflowwww extras" className="space-y-5">
      <header className="flex flex-wrap items-center gap-3 border-t border-border pt-6 text-[14px]">
        <h2 className="text-[16px] font-medium text-fg">Inflowwww extras</h2>
        <ExtraTag />
        <span className="flex items-center gap-3 md:ml-auto whitespace-nowrap">
          {lastIngest && <span className="text-fg-dim">Data through {fmtTimeOnly(lastIngest)}</span>}
          <Link
            href="/analytics/message-dashboard?tab=all"
            className="text-accent hover:underline"
            title="Drill into individual messages — filter by fan, direction, type. Export CSV."
          >
            All messages…
          </Link>
        </span>
      </header>
      <PerEmployeeTable from={from} to={to} chatterOnly={chatterOnly} />
      <SalesNeedingAttributionCard from={from} to={to} />
      <UnattributedDrawer />
      <CoverageHeader from={from} to={to} />
      <IngestHealthBanner />
    </section>
  );
}
