"use client";

/**
 * The Dashboard (`/`): a 12-column card grid whose card set is the Layout capture `docs/infloww-layouts/dashboard.md`
 * of Infloww's old home (docs/spec/infloww-parity-round-2/phase-01-dashboard.md; capture items cited as `#<n>`), on
 * ticket 00's Infloww cards (page-parity ticket 01):
 *   • the KPI header (`DashboardHeader`): the "Creator earnings overview" card, the full width
 *   • "My shifts" on the left (#65, #67) across the three rows of the right column (#68): "Current clocked-in
 *     employees" (#75), "Employee sales" (#79; `EmployeeSalesCard`, ticket 26) and "Scheduled hours" (#86)
 *   • then one "Inflowwww extra" card, which the capture lacks (#5): the Per-model KPIs cards (`PerModelKpiGrid`).
 *     The rest of Creator reports lives in Analytics (owner, 2026-10-20).
 * The layout is static (lib/dashboardCards.ts). The period tabs sit over the grid, so a session whose role hides the
 * earnings card keeps them. A card the session's role hides, or an owner-only one for a chatter (`useCardAllowed`),
 * is not drawn.
 *
 * `DashboardPeriodProvider` holds the header's period (`?window=`), so every card reads the same days.
 */

import { Loader2 } from "lucide-react";
import type { ReactNode } from "react";

import DashboardHeader, {
  DashboardPeriodProvider, DashboardPeriodTabs, EmployeeSalesCard, useDashboardPeriod, WHITE,
} from "@/components/home/DashboardHeader";
import { ClockedInCard, MyShiftsCard } from "@/components/home/ShiftCards";
import PerModelKpiGrid from "@/components/stats/PerModelKpiGrid";
import { useIsChatterOnly } from "@/components/shell/useIsChatterOnly";
import { EmptyState, IfCard } from "@/components/ui/infloww";
import { useUser } from "@/contexts/UserContext";
import { useAppliedSettings } from "@/lib/appliedSettings";
import { cardKey, DASHBOARD_CARDS, type DashboardCardId } from "@/lib/dashboardCards";
import { EXTRA_LABEL } from "@/lib/openinflowwwwExtras";
import { useTimesheet } from "@/lib/shifts";
import { cn } from "@/lib/utils";

export default function HomePage() {
  return (
    // #6: the page frame's 16px padding, full width.
    <div className="min-h-dvh p-4">
      <DashboardPeriodProvider>
        <DashboardGrid />
      </DashboardPeriodProvider>
    </div>
  );
}

const CARDS: Record<DashboardCardId, () => ReactNode> = {
  earnings: () => <DashboardHeader />,
  "my-shifts": () => <MyShiftsCard />,
  "clocked-in": () => <ClockedInCard />,
  "employee-sales": () => <EmployeeSalesCard />,
  "scheduled-hours": () => <ScheduledHours />,
  "per-model": () => <PerModelExtra />,
};

const SPAN = Object.fromEntries(DASHBOARD_CARDS.map((c) => [c.id, c.span])) as Record<DashboardCardId, string>;

/** The owner-only cards: their reads refuse a chatter (Current clocked-in employees, Scheduled hours). */
const OWNER_ONLY: readonly DashboardCardId[] = ["clocked-in", "scheduled-hours"];

/** Whether this session may see each card: for a chatter, never an owner-only card, and no card with a permission
 *  until the Applied settings answer; false for a card its role hides (the Relay refuses a hidden card's read either
 *  way). */
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

/** The period tabs over the grid; the allowed cards in the Dashboard's order, 16px apart (#11), stacked on a phone.
 *  With dense placement a card fills the first cell it fits, so the right column's cards sit beside My shifts. */
function DashboardGrid() {
  const allowed = useCardAllowed();
  return (
    <>
      <div data-testid="dashboard-toolbar" className="mb-4 flex flex-wrap items-center justify-end gap-3">
        <DashboardPeriodTabs />
      </div>
      <div data-testid="dashboard-grid" className="grid grid-cols-1 gap-4 md:grid-cols-12 md:grid-flow-row-dense">
        {DASHBOARD_CARDS.map((c) => c.id).filter(allowed).map((id) => (
          // My shifts: from `md` the card is absolute at full height inside its stretched cell, so it takes the
          // right column's height (#67), as the bundle's `position:"absolute"`, `height:"100%"` card does.
          <div key={id} data-card={id}
            className={cn("min-w-0 empty:hidden", SPAN[id], id === "my-shifts" && "md:relative md:min-h-[320px]")}>
            {CARDS[id]()}
          </div>
        ))}
      </div>
    </>
  );
}

const SCHEDULED_TIP = "Number of hours worked based on shift schedule";

/**
 * "Scheduled hours" (#86-#92): one 12px #2AD4AC bar per Employee, its length the hours the Shift schedule gives
 * them in the header's period (`GET /admin/shifts/timesheet?group=employee`, `scheduled_minutes`), 24px under the
 * title; the empty art and "No data" when nobody has a scheduled minute. The read is owner and Master only (403 for
 * a chatter), so a chatter session has no card, as Infloww hides it without the permission.
 */
function ScheduledHours() {
  const { user } = useUser();
  const { from, to, ready } = useDashboardPeriod();
  const q = useTimesheet(new Date(from), new Date(to), "employee", !!user && ready);
  if (!user) return null;
  const rows = (Array.isArray(q.data?.rows) ? q.data.rows : []).filter((r) => r.scheduled_minutes > 0);
  const max = Math.max(...rows.map((r) => r.scheduled_minutes), 1);
  return (
    <IfCard aria-label="Scheduled hours" title="Scheduled hours" info={SCHEDULED_TIP} className="min-w-0">
      <div data-scheduled-hours className="mt-6">
        {!ready || q.isPending ? (
          <div role="status" aria-label="Loading Scheduled hours" className="h-[140px] flex items-center justify-center">
            <Loader2 size={20} className="animate-spin text-accent" aria-hidden />
          </div>
        ) : q.isError ? (
          <EmptyState kind="error" text={`Couldn't load Scheduled hours: ${q.error.message}`} onRetry={() => void q.refetch()} />
        ) : rows.length === 0 ? (
          <EmptyState />
        ) : (
          <ul className="flex flex-col gap-3">
            {rows.map((r) => {
              const hours = Math.round((r.scheduled_minutes / 60) * 10) / 10;
              return (
                <li key={r.key} data-employee className="flex items-center gap-3 text-[12px]">
                  <span data-name className="w-40 shrink-0 truncate text-fg-dim">{r.display_name}</span>
                  <span className="flex-1 min-w-0">
                    <span data-bar className="block h-3 rounded-r-[2px] bg-[#2ad4ac]"
                      style={{ width: `${(r.scheduled_minutes / max) * 100}%` }} />
                  </span>
                  <span data-hours className={cn("w-14 shrink-0 text-right tabular-nums", WHITE)}>{`${hours}h`}</span>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </IfCard>
  );
}

/** The Per-model KPIs cards over the header's period, once the Applied settings have answered (no read with the
 *  browser's days first). */
function PerModelKpis() {
  const { from, to, ready } = useDashboardPeriod();
  return ready ? <PerModelKpiGrid from={from} to={to} /> : null;
}

/** The "Inflowwww extra" card: its label over the Per-model KPIs cards. */
function PerModelExtra() {
  return (
    <section aria-labelledby="dash-extra-title" className="flex flex-col gap-4">
      <h2 id="dash-extra-title" title={EXTRA_LABEL} className="text-[16px] font-medium text-fg-dim">
        {EXTRA_LABEL}
      </h2>
      <PerModelKpis />
    </section>
  );
}
