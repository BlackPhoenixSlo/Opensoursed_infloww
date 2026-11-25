"use client";


import CompetitorReports from "@/components/home/CompetitorReports";
import EmployeeReport, { type EmployeeTab } from "@/components/stats/EmployeeReport";
import FanReport from "@/components/stats/FanReport";

export type StatsView = "creator" | "employee" | "fan";

export default function StatsReport({ view, tab }: { view: StatsView; tab?: EmployeeTab }) {
  if (view === "employee") return <EmployeeReport tab={tab} />;
  if (view === "fan") return <FanReport />;
  return (
    <div className="max-w-shell mx-auto">
      <CompetitorReports frame="page" />
    </div>
  );
}
