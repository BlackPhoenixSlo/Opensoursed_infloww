"use client";


import { Loader2 } from "lucide-react";
import { type ReactNode } from "react";

import DashboardHeader, {
  DashboardPeriodProvider, DashboardPeriodTabs, EmployeeSalesCard, useDashboardPeriod, WHITE,
} from "@/components/home/DashboardHeader";
import { MyShiftsCard } from "@/components/home/ShiftCards";
import PerModelKpiGrid from "@/components/stats/PerModelKpiGrid";
import { useIsChatterOnly } from "@/components/shell/useIsChatterOnly";
import { EmptyState, IfCard } from "@/components/ui/infloww";
import { useUser } from "@/contexts/UserContext";
import { useAppliedSettings } from "@/lib/appliedSettings";
import { cardKey, cardSpan, DASHBOARD_CARDS, type DashboardCardId } from "@/lib/dashboardCards";
import { EXTRA_LABEL } from "@/lib/openinflowwwwExtras";
import { useTimesheet } from "@/lib/shifts";
import { cn } from "@/lib/utils";

export default function HomePage() {
  return (
    <div className="min-h-dvh p-4">
      <DashboardPeriodProvider>
        <DashboardGrid />
      </DashboardPeriodProvider>
    </div>
  );
}

// ids are stored permission keys (`/#card-<id>`): keep old names
const CARDS: Record<DashboardCardId, () => ReactNode> = {
  earnings: () => <DashboardHeader />,
  "my-shifts": () => <DashboardShifts />,
  "employee-sales": () => <EmployeeSalesCard />,
  "scheduled-hours": () => <WorkedHours />,
  "per-model": () => <PerModelExtra />,
};

// Timesheet read refuses a chatter
const OWNER_ONLY: readonly DashboardCardId[] = ["scheduled-hours"];

function useCardAllowed(): (id: DashboardCardId) => boolean {
  const chatterOnly = useIsChatterOnly();
  const q = useAppliedSettings();
  const denied = q.data?.permissions?.denied_cards ?? [];
  return (id) => {
    if (chatterOnly && OWNER_ONLY.includes(id)) return false;
    const key = cardKey(id);
    if (key === null) return true;
    if (chatterOnly && !q.data) return false;
    return !denied.includes(key);
  };
}

function DashboardGrid() {
  const allowed = useCardAllowed();
  const shown = DASHBOARD_CARDS.map((c) => c.id).filter(allowed);
  return (
    <>
      <div data-testid="dashboard-toolbar" className="mb-4 flex flex-wrap items-center justify-end gap-3">
        <DashboardPeriodTabs />
      </div>
      <div data-testid="dashboard-grid" className="grid grid-cols-1 gap-4 md:grid-cols-[240px_minmax(0,1fr)] md:grid-flow-row-dense">
        {shown.map((id) => (
          <div key={id} data-card={id}
            className={cn("min-w-0 empty:hidden", cardSpan(id, shown), id === "my-shifts" && "md:relative md:min-h-[320px]")}>
            {CARDS[id]()}
          </div>
        ))}
      </div>
    </>
  );
}

function DashboardShifts() {
  const { from, to, ready } = useDashboardPeriod();
  return <MyShiftsCard from={from} to={to} ready={ready} />;
}

const WORKED_HOURS_TIP = "Recorded hours worked during this period";

function WorkedHours() {
  const { user } = useUser();
  const { from, to, ready } = useDashboardPeriod();
  const q = useTimesheet(new Date(from), new Date(to), "employee", !!user && ready);
  if (!user) return null;
  const rows = (Array.isArray(q.data?.rows) ? q.data.rows : []).filter((r) => r.worked_minutes > 0).sort((a, b) => b.worked_minutes - a.worked_minutes);
  const max = Math.max(...rows.map((r) => r.worked_minutes), 1);
  return (
    <IfCard aria-label="Worked hours" title="Worked hours" info={WORKED_HOURS_TIP} className="min-w-0 flex flex-col md:h-[278px]">
      <div data-worked-hours role="group" aria-label="Worked hours list" tabIndex={0}
        className="mt-6 min-h-0 max-h-[280px] overflow-y-auto overscroll-contain pr-2 md:flex-1 md:max-h-none">
        {!ready || q.isPending ? (
          <div role="status" aria-label="Loading Worked hours" className="h-[140px] flex items-center justify-center">
            <Loader2 size={20} className="animate-spin text-accent" aria-hidden />
          </div>
        ) : q.isError ? (
          <EmptyState kind="error" text={`Couldn't load Worked hours: ${q.error.message}`} onRetry={() => void q.refetch()} />
        ) : rows.length === 0 ? (
          <EmptyState />
        ) : (
          <ul className="flex flex-col gap-6 pb-1">
            {rows.map((r) => {
              const hours = r.worked_minutes < 6 ? "<0.1h" : `${Math.round((r.worked_minutes / 60) * 10) / 10}h`;
              return (
                <li key={r.key} data-employee className="flex items-center gap-3 text-[14px]">
                  <span data-name className="w-28 md:w-32 shrink-0 truncate text-fg">{r.display_name}</span>
                  <span className="flex-1 min-w-0 pr-12">
                    <span data-bar className="relative block h-3.5 rounded-full bg-[#20cba6]"
                      style={{ width: `${(r.worked_minutes / max) * 100}%` }}>
                      <span data-hours className={cn("absolute left-full top-1/2 -translate-y-1/2 ml-3 whitespace-nowrap tabular-nums", WHITE)}>{hours}</span>
                    </span>
                  </span>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </IfCard>
  );
}

function PerModelExtra() {
  const { from, to, ready } = useDashboardPeriod();
  return (
    <section aria-labelledby="dash-extra-title" className="flex flex-col gap-4">
      <h2 id="dash-extra-title" title={EXTRA_LABEL} className="text-[16px] font-medium text-fg-dim">
        {EXTRA_LABEL}
      </h2>
      {ready ? <PerModelKpiGrid from={from} to={to} /> : null}
    </section>
  );
}
