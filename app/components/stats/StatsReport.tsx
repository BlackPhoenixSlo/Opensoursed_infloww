"use client";

/**
 * StatsReport — the Analytics report pages (was the single /stats page, which now redirects to Employee reports):
 *   creator  — Creator reports: the Creator Reports card (home/CompetitorReports), which carries its own header,
 *              tabs and filter bar (ticket 20) and reads the shared range (useReportRange) itself.
 *   employee — Employee reports (EmployeeReport).
 *   fan      — Fan reports (FanReport).
 */

import CompetitorReports from "@/components/home/CompetitorReports";
import EmployeeReport, { type EmployeeTab } from "@/components/stats/EmployeeReport";
import FanReport from "@/components/stats/FanReport";

export type StatsView = "creator" | "employee" | "fan";

export default function StatsReport({ view, tab }: { view: StatsView; tab?: EmployeeTab }) {
  if (view === "employee") return <EmployeeReport tab={tab} />;
  if (view === "fan") return <FanReport />;
  // #41: flush on the page; the header's own 16px is the bundle's inset.
  return (
    <div className="max-w-shell mx-auto">
      <CompetitorReports frame="page" />
    </div>
  );
}
