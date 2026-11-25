"use client";


import { createContext, useContext, useState, type ReactNode } from "react";
import { useQuery, type UseQueryResult } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";

import { dayIn, referralsGap, referralsTotal, useReferrals, type ReferralsQuery } from "@/hooks/useReferrals";
import type { EmployeeSalesResp } from "@/hooks/useStats";
import { useAppliedSettings } from "@/lib/appliedSettings";
import { usePrincipalId } from "@/hooks/useEmployeeKey";
import { periodWindow, todayISO, type Period } from "@/lib/dateRange";
import { fmtCents, isLoss } from "@/lib/format";
import { EXTRA_LABEL } from "@/lib/openinflowwwwExtras";
import { EmployeeSalesChart } from "./EmployeeSalesChart";
import { PartialMark } from "./ReportsCharts";
import { type Channel, TILE_ICON } from "./tileIcons";
import { relay } from "@/lib/relay";
import { utcOffsetLabel } from "@/lib/utcOffset";
import { cn } from "@/lib/utils";
import { useTabParam } from "@/hooks/useTabParam";
import { OnlyfansLine } from "@/components/shell/inflowwIcons";
import { EmptyState, IfCard, IfSegmented, IfSelect } from "@/components/ui/infloww";
import { Skeleton } from "@/components/ui/Skeleton";
import {
  control, DEFAULT_BASIS, DEFAULT_PERIOD, isPeriod, PERIOD_TABS, type Basis, type DashboardControlKey,
} from "@/components/home/dashboardControls";
import {
  CHARGEBACKS_UNAVAILABLE, netMissingNote, REFERRALS_FAILED, REFERRALS_UNAVAILABLE, TOTAL_PARTIAL,
} from "@/components/home/netMissingNote";
import { InfoTip } from "@/components/ui/InfoTip";


export const WHITE = "text-white [html[data-theme=light]_&]:text-fg";

interface RevenueRow {
  kind: string | null; total_cents: number; count: number;
  net_cents?: number; net_missing_count?: number;
}
interface RevenueResp { rows: RevenueRow[] }

const TILE_TIP: Record<Channel | "total", string> = {
  total: "Everything your managed Creators earned in this period: all sales plus referrals, gross or net as picked on "
    + "the right. Counts sales OnlyFans hasn't cleared yet; charged-back sales are left out.",
  subscriptions: "New subscriptions and renewals in this period.",
  tips: "Tips fans sent in chat and on posts in this period.",
  posts: "Paid post unlocks in this period.",
  referrals: "Earnings from OnlyFans creator referrals in this period.",
  messages: "Paid message unlocks and paid customs sold in chat in this period.",
  chargebacks: "Sales in this period that fans later charged back or refunded, shown below zero. Already left out of Total earnings.",
};
const BASIS_TIP = "Gross: what fans paid. Net: what the Creators keep after OnlyFans' fee.";

// Keep in sync with service/stats_employees.py SERIES_MESSAGE_KINDS / SERIES_TIP_KINDS (messages, tips).
const CHANNEL_KINDS: Partial<Record<Channel, readonly string[]>> = {
  subscriptions: ["subscription", "rebill"],
  messages: ["ppv_message", "custom"],
  posts: ["ppv_post"],
  tips: ["tip", "tip_post"],
};

const rowsOf = (d: RevenueResp | undefined): RevenueRow[] => (Array.isArray(d?.rows) ? d.rows : []);

const cents = (r: RevenueRow, basis: Basis) => (basis === "Net" ? r.net_cents ?? 0 : r.total_cents);

const label = (key: DashboardControlKey) => control(key).labels[0];

function Info({ k }: { k: DashboardControlKey }) {
  return (
    <InfoTip data-control={k} text={label(k)} className="text-fg-dim" />
  );
}

function Shimmer({ what, className }: { what: string; className: string }) {
  return (
    <span role="status" aria-label={`Loading ${what}`} data-loading className="flex items-center">
      <Skeleton className={className} />
    </span>
  );
}

function TileIcon({ k }: { k: Channel }) {
  const { Icon, rgb } = TILE_ICON[k];
  return (
    <span
      aria-hidden
      data-icon={k}
      className="w-[45px] h-[45px] rounded-full shrink-0 flex items-center justify-center"
      style={{ background: `rgba(${rgb}, 0.1)` }}
    >
      <Icon size={22} strokeWidth={1.75} style={{ color: `rgb(${rgb})` }} />
    </span>
  );
}

function Figure({ text, refreshing = false, partial }: { text: string; refreshing?: boolean; partial?: string }) {
  const sign = text.startsWith("$") ? "$" : "";
  return (
    <span className="flex items-start gap-1">
      <span data-figure aria-busy={refreshing || undefined} title={refreshing ? "Refreshing…" : partial}
        className={cn("font-bold text-accent tabular-nums transition-opacity", refreshing && "opacity-60")}>
        <span className="text-[25px] leading-[15px]">{sign}</span>
        <span className="text-[34px] leading-[45px]">{text.slice(sign.length)}</span>
      </span>
      {partial && <PartialMark reason={partial} className="text-[20px] leading-[28px] font-bold" />}
    </span>
  );
}

interface Tiles {
  revenue: UseQueryResult<RevenueResp>; referrals: ReferralsQuery; reversed: UseQueryResult<RevenueResp>;
  ready: boolean; basis: Basis;
}

// Whole-dollar figures are the house choice, deliberately unlike the bundle's two decimals.
function ChannelTile({ k, tiles }: { k: Channel; tiles: Tiles }) {
  const kinds = CHANNEL_KINDS[k];
  const { revenue, referrals, reversed, ready, basis } = tiles;
  const chargebacks = k === "chargebacks";
  // Chargebacks: reversals below zero; Total already leaves them out.
  const sum = chargebacks ? -rowsOf(reversed.data).reduce((s, r) => s + cents(r, basis), 0)
    : kinds ? rowsOf(revenue.data)
      .filter((r) => r.kind !== null && kinds.includes(r.kind))
      .reduce((s, r) => s + cents(r, basis), 0) : referralsTotal(referrals.data);
  const gap = k === "referrals" ? referralsGap(referrals) : "none";
  const read = chargebacks ? reversed : kinds ? revenue : referrals;
  const dash = (chargebacks && reversed.isError) || gap === "all";
  return (
    <div
      data-control={k}
      title={gap === "all" ? REFERRALS_FAILED : gap === "some" ? REFERRALS_UNAVAILABLE
        : chargebacks && reversed.isError ? CHARGEBACKS_UNAVAILABLE : undefined}
      className="flex items-center justify-between gap-2 ml-[35.5px] mr-[38.5px]"
    >
      <div className="flex flex-col shrink-0">
        {!ready || read.isPending ? (
          <span className="h-[28px] flex items-center"><Shimmer what={label(k)} className="h-[21px] w-16" /></span>
        ) : dash ? (
          <span data-figure className={cn("text-[21px] leading-[28px] font-bold", WHITE)}>-</span>
        ) : (
          <span data-figure className={cn("text-[21px] leading-[28px] font-bold tabular-nums", isLoss(sum) ? "text-err" : WHITE)}>
            {fmtCents(sum)}
          </span>
        )}
        <span className="flex items-center gap-1 text-[12px] leading-[17px] text-[#808080]">
          {label(k)}<InfoTip text={TILE_TIP[k]} iconClassName="h-3 w-3" />
        </span>
      </div>
      <TileIcon k={k} />
    </div>
  );
}

function ChannelColumn({ top, bottom, tiles, first = false }: {
  top: Channel; bottom: Channel; tiles: Tiles; first?: boolean;
}) {
  return (
    <div
      className={cn(
        "flex-1 min-w-0 md:h-[177px] flex flex-col justify-center gap-4 md:gap-[56px] py-4 md:py-0",
        "border-t xl:border-t-0 md:border-l border-border",
        first && "md:border-l-0 xl:border-l",
      )}
    >
      <ChannelTile k={top} tiles={tiles} />
      <ChannelTile k={bottom} tiles={tiles} />
    </div>
  );
}

function EmptyAxes() {
  const ticks = [1, 0.8, 0.6, 0.4, 0.2, 0];
  return (
    <svg data-empty-axes role="img" aria-label="No employee sales in this period" className="block h-[350px] w-full">
      {ticks.map((t, i) => {
        const y = `${4 + (i * 92) / (ticks.length - 1)}%`;
        return (
          <g key={t}>
            <text x="0" y={y} dy="4" className="fill-muted text-[12px]">{String(t)}</text>
            <line x1="32" x2="100%" y1={y} y2={y} className="stroke-border" strokeDasharray="4 4" />
          </g>
        );
      })}
    </svg>
  );
}

function EmployeeSales({ sales, ready, tz }: { sales: UseQueryResult<EmployeeSalesResp>; ready: boolean; tz: string }) {
  if (!ready || sales.isPending) {
    return (
      <div role="status" aria-label={`Loading ${label("employeeSales")}`} className="h-[350px] flex items-center justify-center">
        <Loader2 size={20} className="animate-spin text-accent" aria-hidden />
      </div>
    );
  }
  if (sales.isError) {
    return (
      <div data-retry className="min-h-[300px] flex items-center justify-center">
        <EmptyState
          kind="error"
          text={`Couldn't load ${label("employeeSales")}: ${sales.error.message}`}
          onRetry={() => void sales.refetch()}
        />
      </div>
    );
  }
  const points = sales.data.series;
  if (points.length === 0) return <EmptyAxes />;
  return <EmployeeSalesChart points={points} today={todayISO(tz)} />;
}

interface DashboardPeriod {
  period: Period; pick: (p: Period) => void; from: string; to: string; ready: boolean; reportTz: string | null;
}

const PeriodContext = createContext<DashboardPeriod | null>(null);

export function useDashboardPeriod(): DashboardPeriod {
  const value = useContext(PeriodContext);
  if (!value) throw new Error("DashboardHeader and EmployeeSalesCard need a DashboardPeriodProvider");
  return value;
}

export function DashboardPeriodProvider({ children }: { children: ReactNode }) {
  const [period, setPeriod] = useState<Period>(DEFAULT_PERIOD);
  useTabParam("window", isPeriod, setPeriod);
  const applied = useAppliedSettings();
  const reportTz = applied.data?.preferences?.report_tz ?? null;
  const weekStart = applied.data?.preferences?.week_start ?? "monday";
  const ready = !applied.isPending;
  const [from, to] = periodWindow(period, reportTz, weekStart);
  const pick = (p: Period) => {
    setPeriod(p);
    const url = new URL(window.location.href);
    url.searchParams.set("window", p);
    window.history.replaceState(window.history.state, "", url.pathname + url.search + url.hash);
  };
  return (
    <PeriodContext.Provider value={{ period, pick, from, to, ready, reportTz }}>{children}</PeriodContext.Provider>
  );
}

export function DashboardPeriodTabs() {
  const { period, pick } = useDashboardPeriod();
  return (
    <IfSegmented
      aria-label="Period"
      value={period}
      onChange={pick}
      options={PERIOD_TABS.map((t) => ({ value: t.period, label: <span data-control={t.key}>{t.labels[0]}</span> }))}
      className={cn(
        "w-full md:w-auto max-md:*:flex-1 max-md:*:px-1 md:*:mr-[5px] md:*:last:mr-0",
        "[&>button:hover]:text-accent [&>button[aria-checked=false]:hover]:bg-bg-elev-2/60",
      )}
    />
  );
}

export function EmployeeSalesCard() {
  const { from, to, ready, reportTz } = useDashboardPeriod();
  const tz = reportTz ?? Intl.DateTimeFormat().resolvedOptions().timeZone;
  const sales = useQuery<EmployeeSalesResp>({
    queryKey: ["dashboard", "per-employee", "daily", from, to, tz],
    queryFn: async () => {
      const qs = new URLSearchParams({ from, to, include_series: "true", tz });
      const res = await relay.get<EmployeeSalesResp>(`/admin/stats/per-employee?${qs.toString()}`);
      if (!Array.isArray(res?.series)) throw new Error("the answer has no daily series");
      return res;
    },
    enabled: ready,
    staleTime: 30_000,
  });
  return (
    <IfCard data-control="employeeSales" aria-labelledby="dash-employee-sales-title" className="min-w-0 md:h-[426px]">
      <div className="flex items-center mb-4">
        <h2 id="dash-employee-sales-title" className={cn("text-[16px] font-medium mr-[9px]", WHITE)}>
          {label("employeeSales")}
        </h2>
        <Info k="employeeSalesTip" />
      </div>
      <EmployeeSales sales={sales} ready={ready} tz={tz} />
    </IfCard>
  );
}

const BASIS_OPTIONS = control("basis").labels.map((l) => ({ value: l.split(" ")[0] as Basis, label: l }));

export default function DashboardHeader() {
  const { from, to, ready, reportTz } = useDashboardPeriod();
  const [basis, setBasis] = useState<Basis>(DEFAULT_BASIS);
  const principalId = usePrincipalId();

  // principalId keeps one login's saved figure from another's; include_net only adds keys (total_cents is Gross), so the basis is not in the key.
  const byKind = (reversedOnly: boolean) => ({
    queryKey: ["dashboard", reversedOnly ? "revenue-reversed-by-kind" : "revenue-by-kind", principalId, from, to],
    queryFn: () => {
      const qs = new URLSearchParams({ from, to, group_by: "kind", include_net: "true" });
      if (reversedOnly) qs.set("status", "reversed");
      return relay.get<RevenueResp>(`/admin/stats/revenue?${qs.toString()}`);
    },
    enabled: ready,
    staleTime: 30_000,
  });
  const revenue = useQuery<RevenueResp>(byKind(false));
  const reversed = useQuery<RevenueResp>(byKind(true));

  const referrals = useReferrals(dayIn(from, reportTz), dayIn(to, reportTz), null, ready);
  // Total shows without waiting on referrals (an OF read per Creator) and takes them in when they land.
  const totalCents = rowsOf(revenue.data).reduce((sum, r) => sum + cents(r, basis), 0) + referralsTotal(referrals.data);
  const netMissing = basis === "Net" && revenue.isSuccess
    ? [...rowsOf(revenue.data), ...(reversed.isSuccess ? rowsOf(reversed.data) : [])]
      .reduce((n, r) => n + (r.net_missing_count ?? 0), 0)
    : 0;
  const tiles: Tiles = { revenue, referrals, reversed, ready, basis };

  return (
    <IfCard aria-labelledby="dash-earnings-title">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center min-w-0">
          <h2 id="dash-earnings-title" data-control="title" className={cn("text-[16px] font-medium mr-[9px]", WHITE)}>
            {label("title")}
          </h2>
          <Info k="titleTip" />
          <span
            data-control="timeZone"
            className="ml-2 text-[14px] p-[5px] rounded-[5px] translate-y-px text-fg-dim tabular-nums"
          >
            {ready ? utcOffsetLabel(reportTz) : label("timeZone")}
          </span>
          <span className="ml-1"><Info k="timeZoneTip" /></span>
        </div>
        <span data-control="basis" className="flex items-center gap-2">
          <IfSelect size="lg" aria-label="Earnings" value={basis} options={BASIS_OPTIONS} onChange={setBasis}
            className="w-[160px]" />
          <InfoTip text={BASIS_TIP} className="text-fg-dim" />
        </span>
      </div>

      {revenue.isError ? (
        <div data-control="total" className="mt-4 md:min-h-[177px] flex items-center justify-center">
          <EmptyState
            kind="error"
            text={`Couldn't load ${label("total")}: ${revenue.error.message}`}
            onRetry={() => void revenue.refetch()}
          />
        </div>
      ) : (
        <div className="mt-4 flex flex-col xl:flex-row">
          <div data-control="total" className="xl:flex-1 min-w-0 md:h-[177px] flex flex-col justify-center pl-6 py-4 md:py-0">
            <span aria-hidden data-icon="total" className="w-[45px] h-[45px] rounded-full bg-accent flex items-center justify-center">
              <OnlyfansLine size={26} className="text-white" />
            </span>
            <span className="flex items-center gap-1 text-[12px] leading-[15px] font-medium mt-[18px] mb-3 text-[#1890ff]">
              {label("total")}<InfoTip text={TILE_TIP.total} iconClassName="h-3 w-3" />
            </span>
            {!ready || revenue.isPending ? (
              <span className="h-[45px] flex items-center"><Shimmer what={label("total")} className="h-[34px] w-32" /></span>
            ) : (
              <Figure text={fmtCents(totalCents)} refreshing={revenue.isFetching}
                partial={referralsGap(referrals) === "none" ? undefined : TOTAL_PARTIAL} />
            )}
          </div>
          <div className="flex flex-col md:flex-row xl:flex-[3] min-w-0">
            <ChannelColumn top="subscriptions" bottom="tips" tiles={tiles} first />
            <ChannelColumn top="posts" bottom="referrals" tiles={tiles} />
            <ChannelColumn top="messages" bottom="chargebacks" tiles={tiles} />
          </div>
        </div>
      )}
      {netMissing > 0 && (
        <p data-net-missing title={EXTRA_LABEL} className="mt-3 pl-6 text-[12px] leading-[17px] text-muted">
          {netMissingNote(netMissing, "Net")}
        </p>
      )}
    </IfCard>
  );
}
