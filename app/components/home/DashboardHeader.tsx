"use client";

/**
 * The Dashboard's KPI header (docs/spec/infloww-parity-round-2/phase-01-dashboard.md;
 * ticket 24): Infloww's "Creator earnings overview" card as the Layout capture
 * `docs/infloww-layouts/dashboard.md` records it, and its "Employee sales"
 * card (`EmployeeSalesCard`, which the page places in the bottom box's right
 * column). Labels, order and spacing come from the capture through the control
 * catalogue (`dashboardControls.ts`); the card, the select, the period strip
 * and the colours are page-parity ticket 01's, on ticket 00's Infloww
 * primitives (`components/ui/infloww.tsx`), sampled from the live capture
 * `.scratch/infloww-live/16-dashboard.png`.
 *
 * The period is the capture's tabs (`DashboardPeriodTabs`, which the page
 * places over its grid; `DashboardPeriodProvider`, which the page wraps
 * around every card), seeded once from `?window=` and written
 * back on a click with `history.replaceState` (no history entry). Its days are
 * cut at midnight in the Agency's report time zone from the Applied settings
 * (the browser's when none is saved, as the reports do), and no read fires
 * before those settings answer.
 *
 * Total earnings and the channel tiles read one
 * `GET /admin/stats/revenue?from&to&group_by=kind`. Total sums every kind,
 * `unknown` included; each channel sums the kinds `CHANNEL_KINDS` maps to it
 * (ticket 25), so the channels can sum to less than Total and nothing here
 * says they add up. The header is Agency-wide: it sends no `account_id` (and
 * no `X-Account-Id`), whatever the top bar's scope, so the Relay bounds it to
 * the session's own Creators.
 *
 * The Net earnings / Gross earnings select opens on the capture's Net (#4) and
 * toggles every money tile (#32). Net adds `include_net=true` to the read and
 * shows OnlyFans's own `net_cents`; when some of the window's sales have no
 * net figure yet (`net_missing_count`), a note under the tiles says how many,
 * so gross is never read as net. Gross sends ticket 24's read unchanged. The
 * select does not drive the Creator Reports card (Phase 3's). Referrals has
 * no sales kind: its tile reads `GET /admin/stats/referrals` (`useReferrals`,
 * OnlyFans' own figure per Creator, the same under Net and Gross), and Total
 * earnings adds it, as the bundle's Total counts referrals and Creator reports'
 * does. OnlyFans buckets referral days in its own time zone, so the window's
 * edges can sit a few hours off. A Creator whose referrals read failed counts
 * $0.00, and the tile is titled so.
 *
 * Employee sales (ticket 26) reads `GET /admin/stats/per-employee?from&to`,
 * the read Employee reports makes, so each sale is credited by Sales Settings
 * and the "Unattributed" bucket is a row of its own. It sends no `account_id`
 * either, and the Relay's account clamp and Data scope bound what it shows.
 * The bundle draws one daily "Earnings" line (capture #81), which needs a
 * per-day read the Relay does not make; the card ranks the Employees in the
 * Relay's order instead, labelled as an Inflowwww extra, and draws the
 * bundle's bare axes when there is no row. The select does not drive it: the
 * bundle's read takes no basis.
 */

import { createContext, useContext, useState, type ReactNode } from "react";
import { useQuery, type UseQueryResult } from "@tanstack/react-query";
import {
  AlignCenter, BookmarkPlus, FileText, Info as InfoIcon, Lightbulb, Loader2, MessageCircleMore, UserStar,
  type LucideIcon,
} from "lucide-react";

import { dayIn, referralsTotal, useReferrals, type ReferralsResp } from "@/hooks/useReferrals";
import type { PerEmployeeResp } from "@/hooks/useStats";
import { useAppliedSettings } from "@/lib/appliedSettings";
import { periodWindow, type Period } from "@/lib/dateRange";
import { fmtCents } from "@/lib/format";
import { EXTRA_LABEL } from "@/lib/openinflowwwwExtras";
import { relay } from "@/lib/relay";
import { utcOffsetLabel } from "@/lib/utcOffset";
import { cn } from "@/lib/utils";
import { useTabParam } from "@/hooks/useTabParam";
import { OnlyfansLine } from "@/components/shell/inflowwIcons";
import { EmptyState, IfCard, IfSegmented, IfSelect } from "@/components/ui/infloww";
import {
  control, DEFAULT_BASIS, DEFAULT_PERIOD, isPeriod, PERIOD_TABS, type Basis, type DashboardControlKey,
} from "@/components/home/dashboardControls";

/** Referrals' tile title when OnlyFans' referrals read failed for some Creators, or all. */
export const REFERRALS_UNAVAILABLE = "OnlyFans referrals are unavailable for some creators, counted as $0.00";

/** White on the dark card (16-dashboard.png), the theme's text in light. */
export const WHITE = "text-white [html[data-theme=light]_&]:text-fg";

/** A by-kind row; `net_cents` and `net_missing_count` come only with `include_net=true`. */
interface RevenueRow {
  kind: string | null; total_cents: number; count: number;
  net_cents?: number; net_missing_count?: number;
}
interface RevenueResp { rows: RevenueRow[] }

type Channel = "subscriptions" | "tips" | "posts" | "referrals" | "messages" | "streams";

/**
 * The capture's channels and the Relay's sales kinds (`transaction_ingest.KIND_CATALOG`)
 * each sums, as the spec's Channel mapping writes them. A channel absent here
 * (Referrals) has no sales kind and reads its own (`useReferrals`); a kind absent here (`unknown`
 * among them) counts in Total earnings only.
 */
const CHANNEL_KINDS: Partial<Record<Channel, readonly string[]>> = {
  subscriptions: ["subscription", "rebill"],
  messages: ["ppv_message", "custom"],
  posts: ["ppv_post"],
  tips: ["tip", "tip_post"],
  streams: ["ppv_stream", "tip_stream"],
};

/**
 * Each channel's icon (capture #58-#63): the glyph 22px in the channel colour on a 45px circle of that colour at 10%
 * over the card (16-dashboard.png samples: Subscriptions #2d3734, Tips #292d3b, Referrals #3a302e, Messages #362d3b,
 * Streams #262a36). `rgb` is "r, g, b".
 */
export const TILE_ICON: Record<Channel, { Icon: LucideIcon; rgb: string }> = {
  subscriptions: { Icon: BookmarkPlus, rgb: "42, 212, 172" },
  tips: { Icon: Lightbulb, rgb: "52, 103, 255" },
  posts: { Icon: FileText, rgb: "42, 212, 172" },
  referrals: { Icon: UserStar, rgb: "255, 124, 113" },
  messages: { Icon: MessageCircleMore, rgb: "206, 99, 255" },
  streams: { Icon: AlignCenter, rgb: "20, 78, 204" },
};

/** The answer's rows; an answer without a `rows` array (a mock's `[]` or `{}`) reads as a window with no sales,
 *  never a crash. */
const rowsOf = (d: RevenueResp | undefined): RevenueRow[] => (Array.isArray(d?.rows) ? d.rows : []);

/** A header figure as the bundle's `getHomePageMoneyFormat` prints it (index.9f50f370.js @11227188): two decimals
 *  and a thousands separator at every size, "$12,848.00", where the house `fmtCents` drops the cents from $1,000. */
const money = (c: number): string =>
  `${c < 0 ? "-" : ""}$${(Math.abs(c) / 100).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

/** A row's money in the chosen basis: OnlyFans's `net_cents` in Net, `total_cents` in Gross. */
const cents = (r: RevenueRow, basis: Basis) => (basis === "Net" ? r.net_cents ?? 0 : r.total_cents);

/** "1 sale … has … it" / "3 sales … have … them": the missing-net note under the tiles. */
function netMissingNote(n: number): string {
  return n === 1
    ? "1 sale in this period has no net figure from OnlyFans yet, so Net leaves it out."
    : `${n} sales in this period have no net figure from OnlyFans yet, so Net leaves them out.`;
}

const label = (key: DashboardControlKey) => control(key).labels[0];

/** The ⓘ beside a title: its tooltip is the catalogue label. */
function Info({ k }: { k: DashboardControlKey }) {
  return (
    <span data-control={k} role="img" title={label(k)} aria-label={label(k)} className="text-fg-dim cursor-help">
      <InfoIcon className="h-3.5 w-3.5" aria-hidden />
    </span>
  );
}

/** A figure's slot while its read loads: a shimmer bar, no text (the bundle prints "$0.00"). */
function Shimmer({ what, className }: { what: string; className: string }) {
  return (
    <span role="status" aria-label={`Loading ${what}`} data-loading className="flex items-center">
      <span className={cn("block rounded bg-bg-elev-2 animate-pulse", className)} />
    </span>
  );
}

/** A channel's 45px icon circle (capture #58-#63). */
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

/** The Total earnings figure: the currency sign at 25px beside a 34px number (capture #42). */
function Figure({ text }: { text: string }) {
  const sign = text.startsWith("$") ? "$" : "";
  return (
    <span data-figure className="font-bold text-accent tabular-nums">
      <span className="text-[25px] leading-[15px]">{sign}</span>
      <span className="text-[34px] leading-[45px]">{text.slice(sign.length)}</span>
    </span>
  );
}

/** What a channel tile needs from the header: the by-kind read, whether the
 *  Applied settings have answered, and the basis. */
interface Tiles {
  revenue: UseQueryResult<RevenueResp>; referrals: UseQueryResult<ReferralsResp>; ready: boolean; basis: Basis;
}

/**
 * A channel tile (capture #50-#57): the figure over the label, the icon circle
 * at the right. While the read loads the figure's slot shimmers (the bundle
 * prints "$0.00", capture #50); a window with no sales of the channel's kinds
 * shows $0.00, as the bundle does. A failed read shows on the whole tiles row
 * (`DashboardHeader`). Referrals, with no sales kind, reads its own
 * (`useReferrals`): a failed read, or a Creator it failed for, counts $0.00
 * under a title saying so.
 */
function ChannelTile({ k, tiles }: { k: Channel; tiles: Tiles }) {
  const kinds = CHANNEL_KINDS[k];
  const { revenue, referrals, ready, basis } = tiles;
  const sum = kinds ? rowsOf(revenue.data)
    .filter((r) => r.kind !== null && kinds.includes(r.kind))
    .reduce((s, r) => s + cents(r, basis), 0) : referralsTotal(referrals.data);
  const partial = !kinds && (referrals.isError || !!referrals.data?.unavailable?.length);
  return (
    <div
      data-control={k}
      title={partial ? REFERRALS_UNAVAILABLE : undefined}
      className="flex items-center justify-between gap-2 ml-[35.5px] mr-[38.5px]"
    >
      <div className="flex flex-col shrink-0">
        {!ready || (kinds ? revenue : referrals).isPending ? (
          <span className="h-[28px] flex items-center"><Shimmer what={label(k)} className="h-[21px] w-16" /></span>
        ) : (
          <span data-figure className={cn("text-[21px] leading-[28px] font-bold tabular-nums", WHITE)}>{money(sum)}</span>
        )}
        <span className="text-[12px] leading-[17px] text-[#808080]">{label(k)}</span>
      </div>
      <TileIcon k={k} />
    </div>
  );
}

/** One of the three channel columns, two channels stacked (capture #34, #52). Below `xl` the three sit on their
 *  own row under Total earnings, so the first has no left divider there. */
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

/** The bundle's empty chart (16-dashboard.png): dashed #444 rules at 0, 0.2 … 1 with 12px #999 labels at the left. */
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

/**
 * The Employee sales card's body (capture #81-#85): the bundle's `Spin` and
 * 300px `CommonRetryBox` around a 350px chart. The chart is a ranking of the
 * per-employee read's rows in the Relay's order (revenue, highest first, as
 * Employee reports ranks them), Unattributed included; each row's tooltip is
 * the capture's first point line, led by "Inflowwww extra" since it is a
 * ranking row without the bundle's "Growth:" and "From …:" lines (#84). A
 * period not read yet spins, never showing the last period's ranking; a period
 * with no row draws the bundle's bare axes.
 */
function EmployeeSales({ sales, ready }: { sales: UseQueryResult<PerEmployeeResp>; ready: boolean }) {
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
  const rows = Array.isArray(sales.data?.employees) ? sales.data.employees : [];
  if (rows.length === 0) return <EmptyAxes />;
  const max = Math.max(...rows.map((r) => r.revenue_cents), 1);
  return (
    <ol data-chart title={EXTRA_LABEL} className="h-[350px] overflow-y-auto flex flex-col gap-3 py-2">
      {rows.map((r) => (
        <li
          key={r.employee_id ?? "unattributed"}
          data-employee
          title={`${EXTRA_LABEL} · Earnings: ${fmtCents(r.revenue_cents)}`}
          className="flex items-center gap-3 text-[12px]"
        >
          <span data-name className="w-40 shrink-0 truncate text-fg">
            {r.display_name ?? `Employee #${r.employee_id}`}
          </span>
          <span className="flex-1 min-w-0 h-[5px] rounded-full bg-bg-elev-2">
            <span className="block h-full rounded-full bg-accent" style={{ width: `${(r.revenue_cents / max) * 100}%` }} />
          </span>
          <span data-figure className={cn("w-20 shrink-0 text-right font-bold tabular-nums", WHITE)}>{fmtCents(r.revenue_cents)}</span>
        </li>
      ))}
    </ol>
  );
}

/** The selected period, its `[from, to]` in the report time zone, and whether the Applied settings have answered. */
interface DashboardPeriod {
  period: Period; pick: (p: Period) => void; from: string; to: string; ready: boolean; reportTz: string | null;
}

const PeriodContext = createContext<DashboardPeriod | null>(null);

/** The header's period, for every card inside `DashboardPeriodProvider`. */
export function useDashboardPeriod(): DashboardPeriod {
  const value = useContext(PeriodContext);
  if (!value) throw new Error("DashboardHeader and EmployeeSalesCard need a DashboardPeriodProvider");
  return value;
}

/**
 * The header's period, shared with the Employee sales card, which the page
 * places in the bottom box's right column (capture #79): seeded once from
 * `?window=`, written back on a tab click with `history.replaceState`.
 */
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

/**
 * The period tabs (capture #22-#25, and #96 from the later bundle), over the Dashboard's grid, not in the earnings card: every card
 * reads their period, and a role may hide the earnings card. Below `md` the strip takes its own full-width line with
 * the five tabs sharing it (4px side padding, no gap), so every tab shows and the page never scrolls sideways.
 */
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

/** "Employee sales" (capture #79-#85), for the bottom box's right column. */
export function EmployeeSalesCard() {
  const { from, to, ready } = useDashboardPeriod();
  const sales = useQuery<PerEmployeeResp>({
    queryKey: ["dashboard", "per-employee", from, to],
    queryFn: () => relay.get<PerEmployeeResp>(`/admin/stats/per-employee?${new URLSearchParams({ from, to }).toString()}`),
    enabled: ready,
    staleTime: 30_000,
  });
  return (
    <IfCard data-control="employeeSales" aria-labelledby="dash-employee-sales-title" className="min-w-0">
      <div className="flex items-center mb-4">
        <h2 id="dash-employee-sales-title" className={cn("text-[16px] font-medium mr-[9px]", WHITE)}>
          {label("employeeSales")}
        </h2>
        <Info k="employeeSalesTip" />
      </div>
      <EmployeeSales sales={sales} ready={ready} />
    </IfCard>
  );
}

const BASIS_OPTIONS = control("basis").labels.map((l) => ({ value: l.split(" ")[0] as Basis, label: l }));

export default function DashboardHeader() {
  const { from, to, ready, reportTz } = useDashboardPeriod();
  const [basis, setBasis] = useState<Basis>(DEFAULT_BASIS);

  const revenue = useQuery<RevenueResp>({
    queryKey: ["dashboard", "revenue-by-kind", from, to, basis],
    queryFn: () => {
      const qs = new URLSearchParams({ from, to, group_by: "kind" });
      if (basis === "Net") qs.set("include_net", "true");
      return relay.get<RevenueResp>(`/admin/stats/revenue?${qs.toString()}`);
    },
    enabled: ready,
    staleTime: 30_000,
  });

  // OnlyFans' referrals, the same figure under Net and Gross; Total earnings adds them as the bundle's does. The
  // ledger's Total shows without waiting on them (an OF read per Creator) and takes them in when they land.
  const referrals = useReferrals(dayIn(from, reportTz), dayIn(to, reportTz), null, ready);
  const totalCents = rowsOf(revenue.data).reduce((sum, r) => sum + cents(r, basis), 0) + referralsTotal(referrals.data);
  const netMissing = basis === "Net" && revenue.isSuccess
    ? rowsOf(revenue.data).reduce((n, r) => n + (r.net_missing_count ?? 0), 0)
    : 0;
  const tiles: Tiles = { revenue, referrals, ready, basis };

  return (
    // #11: 16px from this card to the bottom box, the Dashboard grid's gap.
    <IfCard aria-labelledby="dash-earnings-title">
      {/* Title row: title, ⓘ, time zone, ⓘ on the left; the select on the right (the period tabs sit over the grid,
       *  `DashboardPeriodTabs`). Below `md` the groups wrap in the capture's order. */}
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
        <span data-control="basis">
          <IfSelect size="lg" aria-label="Earnings" value={basis} options={BASIS_OPTIONS} onChange={setBasis}
            className="w-[140px]" />
        </span>
      </div>

      {/* Tiles row: Total earnings, then three columns of two channels (capture #33-#35). The bundle has no
       *  narrower layout; below `xl` the four columns are too narrow for a figure and its icon circle, so Total
       *  earnings takes its own row over the three channel columns (from `md`), and on a phone all four stack. A
       *  figure wider than its tile pushes the circle into the tile's right margin, never over the figure. A failed
       *  read swaps the row for the bundle's `CommonRetryBox` at the row's height. */}
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
            <span className="text-[12px] leading-[15px] font-medium mt-[18px] mb-3 text-[#1890ff]">{label("total")}</span>
            {!ready || revenue.isPending ? (
              <span className="h-[45px] flex items-center"><Shimmer what={label("total")} className="h-[34px] w-32" /></span>
            ) : (
              <Figure text={money(totalCents)} />
            )}
          </div>
          <div className="flex flex-col md:flex-row xl:flex-[3] min-w-0">
            <ChannelColumn top="subscriptions" bottom="tips" tiles={tiles} first />
            <ChannelColumn top="posts" bottom="referrals" tiles={tiles} />
            <ChannelColumn top="messages" bottom="streams" tiles={tiles} />
          </div>
        </div>
      )}
      {netMissing > 0 && (
        <p data-net-missing title={EXTRA_LABEL} className="mt-3 pl-6 text-[12px] leading-[17px] text-muted">
          {netMissingNote(netMissing)}
        </p>
      )}
    </IfCard>
  );
}
