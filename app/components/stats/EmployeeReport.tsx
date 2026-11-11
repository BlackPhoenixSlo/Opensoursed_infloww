"use client";

/** Compact Employee reports frame. URL tabs and report-zone ranges remain shared with Sales records. */

import { Filter } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";


import styles from "./EmployeeReport.module.css";
import { useOutsideClose } from "@/components/ui/Menu";
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
import { TableSkeleton } from "@/components/ui/Skeleton";
import { useReportRange } from "@/hooks/useReportRange";
import { useChattingStats, useIngestHealth } from "@/hooks/useStats";
import { fmtTimeOnly } from "@/lib/format";
import { deniedPage } from "@/lib/nav";
import { cn } from "@/lib/utils";
import { BRAND_NAME } from "@/lib/brand";
import { InfoTip } from "@/components/ui/InfoTip";

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
    <div className={styles.report}>
      <InflowwPageHeader title="Employee Reports" utc={reportTz} />
      <IfBody className={styles.body}>
        <SalesSettingsNotice fallback={stats.data?.attribution_fallback ?? null} />
        <IfTabs<EmployeeTab> aria-label="Employee reports" className={cn(styles.toolbar, "px-0", BRIGHT_BAR)} value={tab}
          onChange={go} tabs={tabs}
          extra={tab === "sales" ? <StatsRefreshButton /> : (
            <>
              <DateRangePicker from={from} to={to} preset={preset} onChange={handleRange} timeZone={reportTz} hours />
              <span className="flex items-center gap-2">
                <ShownBySelect days={days} value={bucket} onChange={setPicked} />
                <InfoTip text={GRAN_TIP} className="text-fg-dim" />
              </span>
              <ReportFilters checked={chatterOnly} onChange={setChatterOnly} />
              <StatsRefreshButton />
            </>
          )} />
        {tab === "sales" ? (
          <SalesRecords />
        ) : !ready ? (
          // The Applied settings (the report's time zone) are still in flight: the table's rows as placeholder bars.
          <TableSkeleton rows={6} className="mt-6" />
        ) : (
          <div className={styles.content}>
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

function SalesSettingsNotice({ fallback }: { fallback: string | null }) {
  return (
    <div role="note" className={styles.notice} title={fallback ?? undefined}>
      The sales data is based on the sales settings. View your settings at {" "}
      <Link href="/settings/sales" aria-label="View sales settings">Settings &gt; Sales Settings.</Link>
      {fallback && <InfoTip text={fallback} iconClassName="h-3 w-3" />}
    </div>
  );
}

function ReportFilters({ checked, onChange }: { checked: boolean; onChange: (value: boolean) => void }) {
  const { open, setOpen, ref } = useOutsideClose();
  return <div ref={ref} className="relative" onKeyDown={(event) => {
    if (event.key === "Escape") { setOpen(false); ref.current?.querySelector("button")?.focus(); }
  }}>
    <button type="button" className={styles.filter} aria-expanded={open} aria-controls="employee-report-filters"
      onClick={() => setOpen(!open)}><Filter size={12} />Filters{checked ? " (1)" : ""}</button>
    {open && <div id="employee-report-filters" className={styles.filters}>
      <label className="flex items-center gap-2"><input type="checkbox" checked={checked}
        onChange={(event) => onChange(event.target.checked)} />Chatter role only</label>
    </div>}
  </div>;
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
    <section aria-label={`${BRAND_NAME} extras`} className="space-y-5">
      <header className="flex flex-wrap items-center gap-3 border-t border-border pt-6 text-[14px]">
        <h2 className="text-[16px] font-medium text-fg">{BRAND_NAME} extras</h2>
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
