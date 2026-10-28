"use client";

/**
 * TrackingLinksTab — Growth → Tracking links, laid out from its Layout capture
 * (`docs/infloww-layouts/growth-tracking-links.md`, ticket 38; `#n` below is
 * the capture's Item ID).
 *
 * The bundle's tabs (#10): "Links list" (the attribution tip, the filter
 * bar with the creator filter, "Create tracking link" and "Export", then the
 * metrics table) and "Dashboard" (its filters and seven KPI cards, ticket 40:
 * Total clicks, Total subs and the overall Subscription CVR are sums over the
 * same read for the picked Creator; Total earnings over the earnings read; Avg
 * CPC, Avg CPS and Avg ROI over the links with a Promo cost, `linkAverages`)
 * and "Share links" (#11, `ShareLinksPanel`, owner-only: public read-only
 * reports on picked links for 7 days; the bundle gates it behind an account
 * feature, ours shows it to every owner). The row checkboxes pick links for
 * Batch edit (`LinkBatchEditDialog`: Source, Promo cost, Tag), and Details has
 * Export fans (a CSV of the fan table).
 *
 * The data is OnlyFans' own tracking links (/campaigns, every page, deleted ones
 * included): OF mints a short profile link and reports real CLICKS and how many
 * of those clicks SUBSCRIBED. Name, date created, clicks and subs come from that
 * read, and Subscription CVR is subs divided by clicks. The table renders only
 * the metric columns that have data (Infloww keys its columns the same way,
 * `filterVisibleLinkListColumns`), so it fits without a sideways scroll; a column
 * appears by itself once its `cell` returns a value for some row (see METRIC_COLS).
 * The share URL (onlyfans.com/<user>/c<code>) is built exactly as OF's own
 * Copy-link builds it.
 *
 * Earnings, Fans who spent, Spending CVR, EPC and AEPS (and the Dashboard's Total
 * earnings) come from a second read, `/admin/of-tracking-links/earnings`: the
 * fans OnlyFans lists under each link (its claimers) times their spend in our
 * transactions ledger since the link was created. It lands after the list, and
 * a link it has no figure for shows "—".
 *
 * Filters: Creator, the name search, Date created (a client-side range on
 * `created_at` in the report time zone, with the bundle's six presets), "Show
 * deactivated links" and "Show net earnings" (on by default as the bundle's, one
 * state shared by both tabs, drawn while an earnings column has data), and Source
 * and Tag over the values the Edit dialog set. Export downloads a CSV of the
 * filtered rows and shown columns (the bundle emails one).
 *
 * "Create tracking link" opens the bundle's editor pop-up (#69 to #76, ticket
 * 39): its name creates the link through the existing OnlyFans write, and its
 * Source, Promo cost, Tag and List (`LinkMetaFields`, shared with Edit) ride in
 * the same request and are stored for the new link. Each row's Actions are the
 * bundle's Details (the per-fan overlay, `LinkDetails`), Edit (`LinkEditDialog`:
 * Source, Promo cost and Tag, kept by the relay and never written to OnlyFans;
 * they fill Promo cost, Profit, CPC, CPS, ROI, Source and Tag; and List, OnlyFans'
 * own add-to-list on the link's claimers, which fills the List column) and a dots
 * menu with Deactivate (#62).
 * Deactivate is the OnlyFans delete: Infloww's own is permanent ("This action is
 * permanent and cannot be undone"), and OF keeps the deleted link and its counts,
 * which the list shows as "Deactivated" behind "Show deactivated links".
 *
 * Ours, after every capture element and labelled "Inflowwww extra": custom
 * redirect links (internal /t/<slug>) for a NON-profile target (a Linktree, a
 * landing page). We count clicks; we can't see subscribers, because the
 * visitor never lands on OnlyFans.
 *
 * Ticket 59 (the regrade's follow-up): the title carries the Agency's report
 * time zone (#6 to #9) from the Applied settings, as the Dashboard reads it,
 * and the dates print in that zone; the tabs are the bundle's toggle buttons;
 * the filters lead with their icons; the bundle's tooltips sit on the metric
 * heads and four Dashboard cards; the table pages by 10 / 20 / 50 (#66). The
 * update row says when the relay last read OnlyFans, not the bundle's "every
 * 2 hours" (#30), and it and the house loading and reconnect lines (#68) are
 * labelled as ours.
 */

import { useState } from "react";
import { ArrowLeft, GitMerge, Info, Search, Tag, Upload } from "lucide-react";

import { Badge, Button, Card, ExtraTag, Input } from "@/components/ui/primitives";
import { HbButton, HbFilterLg, HbModal } from "@/components/ui/infloww";
import { ConfirmDeleteButton, CopyButton, Field, errMsg } from "@/components/growth/_bits";
import LinkEditDialog, { LinkBatchEditDialog } from "@/components/growth/LinkEditDialog";
import ShareLinksPanel from "@/components/growth/ShareLinksPanel";
import LinkMetaFields, { FieldLabel, META_LOST, useLinkMetaFields } from "@/components/growth/LinkMetaFields";
import LinksListFrame, {
  ACT, CreatorFilter, FilterSelect, FrameTabs, GrowthHbFrame, LEAD, Pager, RowActions, Switch, TD, TH, Tip, Unreachable,
  createdDay, dateOnly, downloadCsv, readTime, useFrameFilters, useMetaFilter, useReportTz, useSessionGone,
  DEFAULT_PAGE_SIZE, type PageSize,
} from "@/components/growth/LinksListFrame";
import { DASH, costPer, linkAverages, money, profitCents, roi } from "@/components/growth/linkMetrics";
import {
  useOfTrackingLinks, useOfTrackingEarnings, useOfTrackingFans, useCreateOfTrackingLink, useDeleteOfTrackingLink,
  useTrackingLinks, useCreateTrackingLink, useDeleteTrackingLink, useTrackingAnalytics,
  type OfTrackingFan, type OfTrackingLink,
} from "@/hooks/useGrowth";
import { useGrowthCreator } from "@/hooks/useAccounts";
import { useActionAllowed } from "@/components/shell/useGrantedPages";
import { useUser } from "@/contexts/UserContext";
import { EXTRA_LABEL } from "@/lib/openinflowwwwExtras";
import { fmtPrice } from "@/lib/format";
import { cn } from "@/lib/utils";

/** The internal link is same-origin (Next rewrites /t/* to the relay). */
function publicUrl(path: string): string {
  if (typeof window === "undefined") return path;
  return `${window.location.origin}${path}`;
}

/** The bundle's `tips` (its `useSelfCol` columns and `LINK_DASHBOARD_DATA`); the capture does not record them. */
const TIPS = {
  cvr: "Subscription conversion rate: Percentage of clicks that become subscribers. Includes those who signed up for free trial subscription through the tracking link",
  promoCost: "Amount spent on promotions or marketing campaigns for tracking link. Please set this for more accurate data calculations",
  earnings: "Total amount spent by fans on subscriptions and content via tracking link",
  spendingCvr: "Spending conversion rate: Percentage of fans who spent on content or gave tips",
  profit: "Profit: Earnings − Promo cost",
  cpc: "Cost per click: Promo cost divided by number of clicks",
  epc: "Earnings per click: Earnings divided by number of clicks",
  cps: "Cost per subscriber: Promo cost divided by number of subscribers, including those on free trial; average acquisition cost of a subscriber",
  aeps: "Average earnings per subscriber: Earnings divided by number of subscribers",
  roi: "Return of investment: Profit divided by Promo cost, multiplied by 100.",
};

type TabKey = "list" | "dashboard" | "share";
const TABS: Array<{ key: TabKey; label: string }> = [
  { key: "list", label: "Links list" },
  { key: "dashboard", label: "Dashboard" },
  { key: "share", label: "Share links" },
];

export default function TrackingLinksTab({
  accountId, onAccountChange,
}: {
  accountId: string | null;
  /** The creator filter (#17) picks the Creator every read and write below is for. */
  onAccountChange: (id: string) => void;
}) {
  const owner = !!useUser().user;
  const [chosen, setTab] = useState<TabKey>("list");
  // Share links is the owner's: a chatter sees the two other tabs.
  const tab = !owner && chosen === "share" ? "list" : chosen;
  // #25: "Show net earnings", on by default as the bundle's, and one state across both tabs (`getSharedValues`).
  const [net, setNet] = useState(true);
  return (
    <div>
      <FrameTabs tabs={owner ? TABS : TABS.slice(0, 2)} value={tab} onChange={setTab} label="Tracking links" idPrefix="tl" />
      <div role="tabpanel" id={`tl-panel-${tab}`} aria-labelledby={`tl-tab-${tab}`}>
        {tab === "list"
          ? <LinksList accountId={accountId} onAccountChange={onAccountChange} net={net} onNet={setNet} />
          : tab === "share"
            ? <TrackingShares accountId={accountId} onAccountChange={onAccountChange} />
            : <Dashboard accountId={accountId} onAccountChange={onAccountChange} net={net} onNet={setNet} />}
      </div>
    </div>
  );
}

/** Share links on the Creator's tracking links (every one OnlyFans returned with an id, deactivated ones too). */
function TrackingShares({ accountId, onAccountChange }: { accountId: string | null; onAccountChange: (id: string) => void }) {
  const q = useOfTrackingLinks(accountId);
  const links = (q.data?.links ?? []).filter((l) => l.id != null).map((l) => ({ ofId: l.id!, name: l.name }));
  return <ShareLinksPanel accountId={accountId} onAccountChange={onAccountChange} kind="campaign" links={links} />;
}

// ── Links list ────────────────────────────────────────────────────────

/**
 * A metric column after "Tracking link" (#38 to #55); `tip` is the bundle's tooltip on the head.
 *
 * `cell` fills a row's cell from the read (`tz` is the report time zone), `null` when that row has no value. A
 * column renders only when some row has a value for it (or it is `core`, the columns the OnlyFans read always
 * fills), so a column with no `cell` (Not wired) never draws, and one whose data arrives (earnings, promo cost)
 * appears by itself. `net` marks a column whose value has a net figure: while one of them shows, the "Show net
 * earnings" switch shows with it.
 */
type Col = {
  title: string;
  width: number;
  tip?: string;
  core?: boolean;
  net?: boolean;
  cell?: (l: OfTrackingLink, tz: string | null) => string | null;
  /** A tooltip on the row's cell, when it needs a caveat. */
  hint?: (l: OfTrackingLink) => string | undefined;
  /** The Export CSV's value when it differs from the cell's text (a raw number, an ISO day). */
  csv?: (l: OfTrackingLink, tz: string | null) => string;
};

/** Subscription CVR (#41, #77): subs over clicks, "—" with no clicks. */
function cvr({ subscribers, clicks }: { subscribers: number; clicks: number }): string {
  return clicks > 0 ? `${((subscribers / clicks) * 100).toFixed(2)}%` : "—";
}

/** A count with the bundle's thousands commas (its `numberFormat`, index.9f50f370.js @13927845). */
const count = (n: number) => n.toLocaleString("en-US");


/** `cents / n` as money: null when the link has no earnings figure, "—" when `n` is zero. */
function per(cents: number | null | undefined, n: number | null | undefined): string | null {
  return cents == null ? null : n ? fmtPrice(cents / n) : "—";
}

/** The marker on a net figure that leaves out transactions OnlyFans has no net for yet. */
const PARTIAL = " *";
const PARTIAL_HINT = "Partial: some transactions have no net figure from OnlyFans yet, so net is understated";

/** The OnlyFans read with the earnings read merged in, gross or net as "Show net earnings" picks. Both tabs read
 *  through this, so they always agree. */
function useLinks(accountId: string | null, net: boolean) {
  const q = useOfTrackingLinks(accountId);
  const e = useOfTrackingEarnings(accountId);
  const byId = new Map((e.data?.available ? e.data.links : []).map((x) => [x.id, x]));
  const links: OfTrackingLink[] = (q.data?.links ?? []).map((l) => {
    const x = l.id != null ? byId.get(l.id) : undefined;
    return x
      ? {
        ...l,
        earnings_cents: net ? x.earnings_net_cents : x.earnings_cents,
        fans_who_spent: x.fans_who_spent,
        fans_counted: x.fans_counted,
        earnings_partial: net && x.net_missing_count > 0,
      }
      : l;
  });
  return { q, links };
}

/** In the capture's order (#57). The earnings columns read the merged earnings (`useLinks`); a link without a figure
 *  is "—", and the columns draw once any link has one. The drawn columns' widths are tighter than the capture's (its
 *  1,718px for these nine scrolled at 1600px, hiding Spending CVR, EPC and AEPS under the sticky Actions); with
 *  `FIT_*` below they sum to 1,304px, inside a 1600px window's 1,316px panel. */
const METRIC_COLS: Col[] = [
  {
    title: "Date created", width: 104, core: true,
    cell: (l, tz) => dateOnly(l.created_at, tz), csv: (l, tz) => createdDay(l, tz) ?? "",
  },
  { title: "Clicks", width: 80, core: true, cell: (l) => count(l.clicks), csv: (l) => String(l.clicks) },
  { title: "Subs", width: 72, core: true, cell: (l) => count(l.subscribers), csv: (l) => String(l.subscribers) },
  { title: "Subscription CVR", width: 112, tip: TIPS.cvr, core: true, cell: cvr },
  {
    title: "Promo cost", width: 139, tip: TIPS.promoCost,
    cell: (l) => (l.promo_cost_cents ? fmtPrice(l.promo_cost_cents) : null),
    csv: (l) => (l.promo_cost_cents ? (l.promo_cost_cents / 100).toFixed(2) : ""),
  },
  {
    title: "Earnings", width: 128, tip: TIPS.earnings, net: true,
    cell: (l) => (l.earnings_cents == null ? null : money(l.earnings_cents) + (l.earnings_partial ? PARTIAL : "")),
    hint: (l) => (l.earnings_partial ? PARTIAL_HINT : undefined),
    csv: (l) => (l.earnings_cents == null ? "" : (l.earnings_cents / 100).toFixed(2)),
  },
  {
    title: "Fans who spent", width: 92,
    cell: (l) => (l.fans_who_spent == null ? null : count(l.fans_who_spent)),
    csv: (l) => (l.fans_who_spent == null ? "" : String(l.fans_who_spent)),
  },
  {
    title: "Spending CVR", width: 96, tip: TIPS.spendingCvr,
    // Over the link's claimers, the same fans the numerator is counted from.
    cell: (l) => (l.fans_who_spent == null ? null
      : l.fans_counted ? `${((l.fans_who_spent / l.fans_counted) * 100).toFixed(2)}%` : "—"),
  },
  // The cost-based columns read the Edit dialog's Promo cost: "—" while it is unset or 0 (linkMetrics).
  {
    title: "Profit", width: 139, tip: TIPS.profit, net: true,
    cell: (l) => { const p = profitCents(l.earnings_cents, l.promo_cost_cents); return p == null ? null : money(p); },
  },
  { title: "CPC", width: 123, tip: TIPS.cpc, cell: (l) => (l.promo_cost_cents ? costPer(l.promo_cost_cents, l.clicks) : null) },
  { title: "EPC", width: 100, tip: TIPS.epc, net: true, cell: (l) => per(l.earnings_cents, l.clicks) },
  { title: "CPS", width: 123, tip: TIPS.cps, cell: (l) => (l.promo_cost_cents ? costPer(l.promo_cost_cents, l.subscribers) : null) },
  { title: "AEPS", width: 112, tip: TIPS.aeps, net: true, cell: (l) => per(l.earnings_cents, l.fans_counted) },
  {
    title: "ROI", width: 139, tip: TIPS.roi, net: true,
    cell: (l) => (profitCents(l.earnings_cents, l.promo_cost_cents) == null ? null : roi(l.earnings_cents, l.promo_cost_cents)),
  },
  { title: "Source", width: 120, cell: (l) => l.link_source || null },
  { title: "Tag", width: 180, cell: (l) => (l.tags?.length ? l.tags.join(", ") : null) },
  { title: "List", width: 180, cell: (l) => l.list_name || (l.list_id ? `List ${l.list_id}` : null) },
  { title: "Last updated", width: 151 },
];

/** The metric columns that have data in `links` (see `Col`), in the capture's order. */
function visibleCols(links: OfTrackingLink[], tz: string | null): Col[] {
  return METRIC_COLS.filter((c) => c.cell && (c.core || links.some((l) => c.cell!(l, tz) !== null)));
}

/** The "Show net earnings" switch shows only while a net-aware column has data (`Col.net`); until then it would be
 *  a switch with nothing to switch. */
function hasNetCols(links: OfTrackingLink[], tz: string | null): boolean {
  return visibleCols(links, tz).some((c) => c.net);
}

/** The date and time the relay's read landed, in the report time zone. */
function readStamp(at: number, tz: string | null): string {
  return new Date(at).toLocaleString(undefined, {
    timeZone: tz ?? undefined, year: "numeric", month: "short", day: "numeric", hour: "numeric", minute: "2-digit",
  });
}

// ── Export (#28) ──

/** The bundle emails its export (#81); ours downloads the filtered rows (every page) with the columns shown. */
function exportCsv(rows: OfTrackingLink[], cols: Col[], tz: string | null) {
  const withStatus = rows.some((l) => l.is_deleted);
  const head = ["Tracking link", "Link", ...cols.map((c) => c.title), ...(withStatus ? ["Status"] : [])];
  downloadCsv("tracking-links", [head, ...rows.map((l) => [
    l.name,
    l.url ?? "",
    ...cols.map((c) => (c.csv ? c.csv(l, tz) : c.cell?.(l, tz) ?? "")),
    ...(withStatus ? [l.is_deleted ? "Deactivated" : "Active"] : []),
  ])], tz);
}

type TabProps = { accountId: string | null; onAccountChange: (id: string) => void; net: boolean; onNet: (on: boolean) => void };

function LinksList({ accountId, onAccountChange, net, onNet }: TabProps) {
  const { q, links } = useLinks(accountId, net);
  const deleteM = useDeleteOfTrackingLink(accountId);
  const filters = useFrameFilters();
  const { reportTz } = filters;

  const [creating, setCreating] = useState(false);
  // #24: off by default, as the bundle's.
  const [showDeactivated, setShowDeactivated] = useState(false);
  // Details (#82): the link whose fan list replaces the list, as the bundle's overlay does.
  const [details, setDetails] = useState<OfTrackingLink | null>(null);
  const [editing, setEditing] = useState<OfTrackingLink | null>(null);
  const [picked, setPicked] = useState<string[]>([]);
  const [batch, setBatch] = useState(false);
  const sessionGone = useSessionGone(accountId);

  const ofAvailable = q.data?.of_available ?? false;
  const matched = links.filter((l) => (!l.is_deleted || showDeactivated) && filters.keep(l));
  // Every link the read returned decides the columns, so they hold still across pages and filters.
  const cols = visibleCols(links, reportTz);
  const rowKey = (l: OfTrackingLink) => String(l.id ?? l.code);
  // The picks still in the list (a filter or another Creator leaves the rest out).
  const pickedRows = matched.filter((l) => l.id != null && picked.includes(rowKey(l)));

  if (details) {
    return <LinkDetails accountId={accountId} link={details} net={net} onBack={() => setDetails(null)} />;
  }

  return (
    <div>
      <LinksListFrame<OfTrackingLink>
        variant="TRACKING"
        accountId={accountId}
        onAccountChange={onAccountChange}
        filters={filters}
        sources={q.data?.sources ?? []}
        tags={q.data?.tags ?? []}
        switches={(
          <>
            {/* #24 to #26: labels 16px, 6px to the switch; deactivated off by default. "Show net earnings" (on by
                default, as the bundle's) is drawn only once a net-aware column has data (`hasNetCols`). */}
            <Switch
              label="Show deactivated links"
              on={showDeactivated}
              onChange={(on) => { setShowDeactivated(on); filters.setPage(1); }}
            />
            {hasNetCols(links, reportTz) && <Switch label="Show net earnings" on={net} onChange={onNet} />}
          </>
        )}
        onCreate={() => setCreating(true)}
        onExport={() => exportCsv(matched, cols, reportTz)}
        exportTitle={`${EXTRA_LABEL}: downloads a CSV of the filtered links and the columns shown; Infloww emails its export`}
        /* #30 to #32, #89: the update row; the tip 14px, 8px after its icon. The relay reads OnlyFans when asked, not
           every 2 hours, so the words are ours. */
        update={q.dataUpdatedAt > 0 ? (
          <span className="flex items-center gap-2 text-sm text-fg-dim">
            <Info size={16} aria-hidden className="shrink-0" />
            <span>Last read from OnlyFans at {readTime(q.dataUpdatedAt, reportTz)}</span>
            <ExtraTag />
          </span>
        ) : null}
        /* Ours when the read fails while the session looks alive; a dead session gets the bundle's reconnect state
           (#68) in the table body instead. */
        notice={!q.isLoading && !ofAvailable && !sessionGone ? <Unreachable /> : null}
        loading={q.isLoading}
        /* #34: only the columns with data draw (`visibleCols`), so the table fits. */
        columns={cols.map((c) => ({
          title: c.title, width: c.width, tip: c.tip, hint: c.hint, cell: (l: OfTrackingLink) => c.cell?.(l, reportTz) ?? "—",
        }))}
        rows={matched}
        rowKey={rowKey}
        selection={{
          selected: pickedRows.map(rowKey), onChange: setPicked, canSelect: (l) => l.id != null,
          onBatchEdit: () => setBatch(true),
        }}
        rowName={(l) => l.name}
        /* #58, #59, #90: the name on one line, then "Copy link", 2px apart. The address is ours. A deactivated link
           carries the bundle's red "Deactivated" chip in place of the copy: OF no longer serves it. */
        nameCell={(l) => (
          <div className="flex flex-col items-start gap-0.5 w-full">
            <span className="w-full truncate text-sm" title={l.name}>{l.name}</span>
            <span className="flex items-center gap-2 w-full min-w-0">
              {l.is_deleted ? (
                <Badge color="err">Deactivated</Badge>
              ) : (
                <>
                  {/* #61: "Link copied", the copy locked for 5 s. */}
                  {l.url && <CopyButton text={l.url} label="Copy link" doneLabel="Link copied" holdMs={5000} />}
                  {/* The path ("/<username>/c<code>"): the origin would fill the cell before the code. */}
                  <span className="truncate text-[11px] text-fg-dim" title={EXTRA_LABEL}>
                    {l.url ? l.url.replace(/^https:\/\/onlyfans\.com/, "") : "(url unavailable)"}
                  </span>
                </>
              )}
            </span>
          </div>
        )}
        /* #62 to #64: Details opens the link's fan list; Edit the editor on its Source, Promo cost and Tag; the dots
           menu's Deactivate is the OnlyFans delete, behind the bundle's confirm, disabled once deactivated. */
        actions={(l) => (
          <RowActions
            name={l.name}
            onDetails={l.id != null ? () => setDetails(l) : undefined}
            onEdit={l.id != null ? () => setEditing(l) : undefined}
            action={{
              label: "Deactivate",
              confirmTitle: `Deactivate link, ${l.name}?`,
              confirmBody: "Data from the tracking link is no longer tracked when the link is deactivated. This action is permanent and cannot be undone.",
              failText: "Unable to deactivate tracking link. Try again later",
              run: l.id != null && !l.is_deleted ? () => deleteM.mutateAsync(l.id!) : undefined,
            }}
          />
        )}
      />
      {editing?.id != null && (
        <LinkEditDialog
          accountId={accountId}
          link={{ kind: "campaign", ofId: editing.id, name: editing.name, promo_cost_cents: editing.promo_cost_cents,
            link_source: editing.link_source, tags: editing.tags, list_id: editing.list_id, list_name: editing.list_name }}
          sources={q.data?.sources ?? []}
          tags={q.data?.tags ?? []}
          onClose={() => setEditing(null)}
        />
      )}
      {batch && (
        <LinkBatchEditDialog
          accountId={accountId}
          kind="campaign"
          ofIds={pickedRows.map((l) => l.id!)}
          sources={q.data?.sources ?? []}
          tags={q.data?.tags ?? []}
          onClose={(saved) => { setBatch(false); if (saved) setPicked([]); }}
        />
      )}
      {creating && (
        <CreateLinkModal
          accountId={accountId}
          taken={links.filter((l) => !l.is_deleted).map((l) => l.name)}
          sources={q.data?.sources ?? []}
          tags={q.data?.tags ?? []}
          onClose={() => setCreating(false)}
        />
      )}

      <div className="px-4">
        <CustomRedirects accountId={accountId} />
      </div>
    </div>
  );
}

// ── The editor pop-up (#69 to #76) ────────────────────────────────────

/** #76: a field's label 16px; its "Optional" 14px, 4px after the label. */
/** "Create tracking link" (#69): name, Source, Promo cost, Tag, List (#74), then "Save" (#75). The name creates the
 *  link through the existing OnlyFans write for the Creator the filter picked; the other fields (`LinkMetaFields`,
 *  the Edit dialog's) ride in the same request and the relay stores them for the new link's id. OnlyFans' reply
 *  without an id: the link exists but the fields were not stored, and the pop-up says so instead of closing. */
function CreateLinkModal({ accountId, taken, sources, tags, onClose }: {
  accountId: string | null;
  /** The live links' names: the bundle refuses a repeat (`linkNameRepeat`), so we check before calling OnlyFans. */
  taken: string[];
  /** The account's Sources and Tags in use: the inputs' suggestions. */
  sources: string[];
  tags: string[];
  onClose: () => void;
}) {
  const createM = useCreateOfTrackingLink(accountId);
  const f = useLinkMetaFields();
  const [name, setName] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [lost, setLost] = useState(false);

  async function save() {
    setErr(null);
    // #70: the bundle's required-field words.
    if (!name.trim()) { setErr("This is a required field"); return; }
    if (taken.includes(name.trim())) { setErr("This link name already exists. Enter a different one"); return; }
    if (f.costBad) return;
    const body = f.filled() ? { name: name.trim(), ...f.payload() } : { name: name.trim() };
    try {
      const out = await createM.mutateAsync(body);
      if (out?.meta_saved === false) { setLost(true); return; }
      onClose();
    } catch (e) { setErr(errMsg(e, "Create failed")); }
  }

  return (
    <HbModal
      title="Create tracking link"
      width={480}
      onClose={onClose}
      footer={lost ? (
        <HbButton onClick={onClose}>Close</HbButton>
      ) : (
        <>
          {/* The bundle's two-button footer, both 36px: Cancel, then "Save" (#75). */}
          <HbButton variant="secondary" onClick={onClose}>Cancel</HbButton>
          <HbButton onClick={save} disabled={createM.isPending || f.costBad}>Save</HbButton>
        </>
      )}
    >
      {lost ? (
        <div role="alert" className="text-sm text-fg">
          {META_LOST}
        </div>
      ) : (
        /* #76: 24px between fields, 8px inside each. */
        <form className="flex flex-col gap-6 text-fg" onSubmit={(e) => { e.preventDefault(); void save(); }}>
          <div className="flex flex-col gap-2">
            <FieldLabel htmlFor="tl-ed-name" text="Tracking link name" />
            <Input
              id="tl-ed-name"
              className="h-9"
              maxLength={100}
              autoFocus
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
            {err && <div className="text-err text-xs">{err}</div>}
          </div>
          <LinkMetaFields f={f} id="tl-ed" accountId={accountId} sources={sources} tags={tags} />
        </form>
      )}
    </HbModal>
  );
}

// ── Details (#82 to #84): one link's fans and their spend ─────────────

/** The bundle's `LinkUserList` columns after Fan (`useLinkUserListTableConfig` @14152372): each reads its key, or the
 *  key with `Net` while "Show net earnings" is on. "Other" (a ledger kind outside the five) draws only when a fan has
 *  some, so Total always equals its row. */
const FAN_COLS: Array<{ title: string; key: "total" | "subs" | "posts" | "messages" | "streams" | "tips" | "other" }> = [
  { title: "Total", key: "total" },
  { title: "Subs", key: "subs" },
  { title: "Posts", key: "posts" },
  { title: "Messages", key: "messages" },
  { title: "Streams", key: "streams" },
  { title: "Tips", key: "tips" },
  { title: "Other", key: "other" },
];

function fanCents(f: OfTrackingFan, key: (typeof FAN_COLS)[number]["key"], net: boolean): number {
  return f[`${key}${net ? "_net" : ""}_cents` as keyof OfTrackingFan] as number;
}

function LinkDetails({ accountId, link, net, onBack }: {
  accountId: string | null; link: OfTrackingLink; net: boolean; onBack: () => void;
}) {
  const q = useOfTrackingFans(accountId, link.id);
  const { reportTz } = useReportTz();
  const exportAllowed = useActionAllowed("export");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState<PageSize>(DEFAULT_PAGE_SIZE);

  const fans = q.data?.fans ?? [];
  const cols = FAN_COLS.filter((c) => c.key !== "other" || fans.some((f) => f.other_cents !== 0));
  const needle = search.trim().toLowerCase();
  const matched = fans.filter((f) => !needle
    || f.name.toLowerCase().includes(needle) || f.username.toLowerCase().includes(needle));
  const pages = Math.max(1, Math.ceil(matched.length / pageSize));
  const current = Math.min(page, pages);
  const shown = matched.slice((current - 1) * pageSize, current * pageSize);
  const span = cols.length + 1;

  return (
    <section aria-label="Details" className="px-4 pt-4 mb-4 space-y-4">
      {/* The bundle's header: back to the list, "Details", then the link's name. */}
      <div className="flex flex-wrap items-center gap-4">
        <button type="button" onClick={onBack} className={cn(ACT, "gap-1 flex")}>
          <ArrowLeft size={14} aria-hidden /> Tracking links
        </button>
        <h2 className="text-base font-semibold">Details</h2>
        <span className="text-base text-fg-dim truncate">{link.name}</span>
      </div>
      <div className="flex flex-wrap items-center gap-4">
        <span className="relative inline-flex w-[280px] max-w-full">
          <Search size={20} aria-hidden className={LEAD} />
          <input
            className={cn(HbFilterLg, "w-full pl-10")}
            aria-label="Search fan name"
            placeholder="Search fan name"
            value={search}
            onChange={(e) => { setSearch(e.target.value); setPage(1); }}
          />
        </span>
        {/* Infloww's export-link-fans (it emails one); ours downloads the fans matched, as the table shows them. */}
        {exportAllowed && (
          <HbButton variant="secondary" icon={Upload} disabled={matched.length === 0} title={`${EXTRA_LABEL}: downloads a CSV`}
            onClick={() => downloadCsv(`tracking-link-fans-${link.id}`, [
              ["Fan", "Username", ...cols.map((c) => c.title)],
              ...matched.map((f) => [f.name, f.username, ...cols.map((c) => (fanCents(f, c.key, net) / 100).toFixed(2))]),
            ], reportTz)}>
            Export fans
          </HbButton>
        )}
        <span className="flex items-center gap-2 text-sm text-fg-dim">
          <Info size={16} aria-hidden className="shrink-0" />
          {q.data?.counted_from
            ? <>Spend from our ledger since {dateOnly(q.data.counted_from, reportTz)}</>
            : <>Spend from our ledger</>}
          ; a fan who came through several links is split between them by time.
          <ExtraTag />
        </span>
      </div>
      {q.isError && <div className="text-sm text-err">Unable to load page. Try again later</div>}
      <div className="overflow-x-auto">
        <table aria-label="Link fans" className="w-full border-collapse table-fixed">
          <thead>
            <tr>
              <th className={TH} style={{ width: 240 }}>Fan</th>
              {cols.map((c) => <th key={c.key} className={TH} style={{ width: 120 }}>{c.title}</th>)}
            </tr>
          </thead>
          <tbody>
            {q.isLoading ? (
              <tr>
                <td colSpan={span} className={cn(TD, "text-fg-dim")}>
                  <span className="inline-flex items-center gap-2">Loading… <ExtraTag /></span>
                </td>
              </tr>
            ) : shown.length === 0 ? (
              <tr><td colSpan={span} className={cn(TD, "text-center text-fg-dim")}>No data</td></tr>
            ) : (
              <>
                {shown.map((f) => (
                  <tr key={f.fan_id}>
                    <td className={TD}>
                      <div className="flex flex-col">
                        <span className="truncate text-sm">{f.name || f.username || f.fan_id}</span>
                        <span className="truncate text-[11px] text-fg-dim">
                          @{f.username || f.fan_id}
                          {f.also_claimed_by.length > 0 && " · also came through another link"}
                        </span>
                      </div>
                    </td>
                    {cols.map((c) => (
                      <td key={c.key} className={cn(TD, "tabular-nums")}>{money(fanCents(f, c.key, net))}</td>
                    ))}
                  </tr>
                ))}
                {/* The bundle's `LinkUserListSummaryRow`: each column summed. */}
                <tr className="font-medium">
                  <td className={TD}>Total:</td>
                  {cols.map((c) => (
                    <td key={c.key} className={cn(TD, "tabular-nums")}>
                      {money(shown.reduce((t, f) => t + fanCents(f, c.key, net), 0))}
                    </td>
                  ))}
                </tr>
              </>
            )}
          </tbody>
        </table>
      </div>
      {shown.length > 0 && (
        <Pager
          page={current}
          total={matched.length}
          size={pageSize}
          onPage={setPage}
          onSize={(s) => { setPageSize(s); setPage(1); }}
        />
      )}
    </section>
  );
}

// ── Dashboard ─────────────────────────────────────────────────────────

/** The read's totals for one Creator; null while there is no read to sum. `earnings` (every link, deactivated ones
 *  too: their money was earned) is null until some link has a figure; `partial` when some link has none, or net
 *  leaves transactions out. */
type Totals = { clicks: number; subscribers: number; earnings: number | null; partial: boolean } | null;

type Averages = ReturnType<typeof linkAverages>;
const orNull = (v: string): string | null => (v === DASH ? null : v);

/**
 * #77: the seven cards in the capture's order. Total clicks, Total subs and the overall Subscription CVR are sums
 * over the read; Total earnings over the earnings read. Avg CPC, Avg CPS and Avg ROI are ours (Infloww does not say
 * how it averages): pooled over the links with a Promo cost, deactivated ones too (their cost was spent), after the
 * Source and Tag filters: Σcost / Σclicks, Σcost / Σsubs, and (Σearnings − Σcost) / Σcost × 100 over the costed links
 * with an earnings figure, net or gross as the toggle says ("—" with no costed link or a divisor of 0).
 */
const KPIS: Array<{ title: string; tip?: string; value: (t: NonNullable<Totals>, a: Averages) => string | null }> = [
  { title: "Total clicks", value: (t) => count(t.clicks) },
  { title: "Avg CPC", tip: TIPS.cpc, value: (_t, a) => orNull(a.cpc) },
  { title: "Total subs", value: (t) => count(t.subscribers) },
  { title: "Avg CPS", tip: TIPS.cps, value: (_t, a) => orNull(a.cps) },
  { title: "Subscription CVR", tip: TIPS.cvr, value: cvr },
  { title: "Total earnings", value: (t) => (t.earnings == null ? null : money(t.earnings) + (t.partial ? PARTIAL : "")) },
  { title: "Avg ROI", tip: TIPS.roi, value: (_t, a) => (a.roi === DASH ? null : a.roi + (a.roiPartial ? PARTIAL : "")) },
];

const PARTIAL_TITLE: Record<string, string> = {
  "Total earnings": "Partial: some links have no earnings figure, or net leaves out transactions OnlyFans has no net for yet",
  "Avg ROI": "Partial: some links with a Promo cost have no earnings figure, or net leaves out transactions OnlyFans has no net for yet",
};

function Dashboard({ accountId, onAccountChange, net, onNet }: TabProps) {
  const { q, links: all } = useLinks(accountId, net);
  const mf = useMetaFilter();
  const links = all.filter(mf.keep);
  const { reportTz } = useReportTz();
  const ofAvailable = q.data?.of_available ?? false;
  // No read, or OnlyFans unreachable: "—", never a zero that reads as a real total. Clicks and subs are over the
  // live links, as they were before the read carried the deactivated ones; earnings are over every link.
  const totals: Totals = q.data && ofAvailable
    ? links.reduce<NonNullable<Totals>>(
      (t, l) => ({
        clicks: t.clicks + (l.is_deleted ? 0 : l.clicks),
        subscribers: t.subscribers + (l.is_deleted ? 0 : l.subscribers),
        earnings: l.earnings_cents == null ? t.earnings : (t.earnings ?? 0) + l.earnings_cents,
        partial: t.partial || l.earnings_cents == null || !!l.earnings_partial,
      }),
      { clicks: 0, subscribers: 0, earnings: null, partial: false },
    )
    : null;
  const averages = linkAverages(links);

  return (
    <div className="px-4 pt-4 mb-4">
      {/* #80: Creator, Source, Tag and Show net earnings (`LinkDashboardFilters`, index.9f50f370.js @13976167). */}
      <div className="flex flex-wrap items-center gap-x-4">
        <CreatorFilter accountId={accountId} onAccountChange={onAccountChange} />
        <FilterSelect label="Source" icon={GitMerge} options={q.data?.sources ?? []} value={mf.source} onChange={mf.setSource} />
        <FilterSelect label="Tag" icon={Tag} options={q.data?.tags ?? []} value={mf.tag} onChange={mf.setTag} />
        {/* Drawn once a net-aware column has data, as on Links list (`hasNetCols`). */}
        {hasNetCols(all, reportTz) && <Switch label="Show net earnings" on={net} onChange={onNet} />}
      </div>
      {!q.isLoading && !ofAvailable && <Unreachable className="mb-4" />}
      {/* #78, #79: 32% wide, 16px apart, 16px under the filters; a 20px title over a 48px mono value. */}
      <div className="flex flex-wrap gap-4">
        {KPIS.map((k) => {
          const v = totals ? k.value(totals, averages) : null;
          const partial = k.title === "Total earnings" ? !!totals?.partial : k.title === "Avg ROI" && averages.roiPartial;
          return (
            <div
              key={k.title}
              data-kpi
              className="w-full sm:w-[32%] p-4 rounded-xl bg-panel"
            >
              <div className="mb-4 h-5 leading-5 font-medium">{k.title}{k.tip && <Tip text={k.tip} />}</div>
              <div
                title={v != null && partial ? PARTIAL_TITLE[k.title] : undefined}
                className={cn(
                  "h-12 text-[48px] leading-[48px] font-mono font-normal truncate tabular-nums",
                  v != null ? "text-fg" : "text-fg-dim",
                )}
              >
                {v ?? "—"}
              </div>
            </div>
          );
        })}
      </div>
      {/* #80: "Last updated: " under the cards, right-aligned, 16px down (`LinkDashboardUpdateInfo`, @13977563): when
          the relay's read of OnlyFans landed, in the report time zone, as the Links list's update row says. */}
      <p className="mt-4 text-right text-sm text-fg-dim">
        <span>Last updated: {q.dataUpdatedAt > 0 ? readStamp(q.dataUpdatedAt, reportTz) : "—"}</span>
      </p>
    </div>
  );
}

// ── Internal redirect links: an Inflowwww extra, after the capture's elements ──

function CustomRedirects({ accountId }: { accountId: string | null }) {
  const linksQ = useTrackingLinks(accountId);
  const createM = useCreateTrackingLink(accountId);
  const deleteM = useDeleteTrackingLink(accountId);

  const [name, setName] = useState("");
  const [target, setTarget] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [openId, setOpenId] = useState<number | null>(null);
  const [open, setOpen] = useState(false);

  const links = linksQ.data ?? [];

  async function create() {
    setErr(null);
    if (!name.trim()) { setErr("Name is required."); return; }
    if (!/^https?:\/\//.test(target.trim())) { setErr("Target must be an http(s) URL."); return; }
    try {
      await createM.mutateAsync({ name: name.trim(), target_url: target.trim() });
      setName(""); setTarget("");
    } catch (e) { setErr(errMsg(e, "Create failed")); }
  }

  return (
    <section aria-label="Custom redirect links" className="space-y-4 border-t border-border pt-6">
      <header>
        <div className="flex flex-wrap items-center gap-2">
          <button type="button" onClick={() => setOpen((v) => !v)}
            className="flex items-center gap-2 text-left">
            <h2 className="text-lg font-semibold">Custom redirect links</h2>
            <Badge color="muted">/t/&lt;slug&gt;</Badge>
            <span className="text-fg-dim text-xs">{open ? "▲" : "▼"}</span>
            {links.length > 0 && <span className="text-fg-dim text-xs">· {links.length}</span>}
          </button>
          <ExtraTag />
        </div>
        <p className="text-sm text-fg-dim">
          For a target that <i>isn&rsquo;t</i> your OnlyFans profile — a Linktree, a
          landing page, a link you want to swap later. We count clicks; subscriber
          attribution isn&rsquo;t possible here, since the visitor never lands on OnlyFans.
        </p>
      </header>

      {open && (
        <>
          <Card className="p-4 space-y-3">
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="Name">
                <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Linktree" />
              </Field>
              <Field label="Target URL">
                <Input value={target} onChange={(e) => setTarget(e.target.value)}
                  placeholder="https://linktr.ee/creator" />
              </Field>
            </div>
            <div className="flex items-center gap-2">
              {err && <span className="text-err text-xs mr-auto">{err}</span>}
              <Button size="sm" onClick={create} disabled={createM.isPending || !accountId}
                className={err ? "" : "ml-auto"}>
                {createM.isPending ? "Creating…" : "Create link"}
              </Button>
            </div>
          </Card>

          {!linksQ.isLoading && links.length === 0 && (
            <div className="text-sm text-fg-dim">No custom redirect links yet.</div>
          )}

          <ul className="divide-y divide-border">
            {links.map((l) => (
              <li key={l.id} className="py-3 space-y-2">
                <div className="flex flex-wrap items-center gap-3">
                  <div className="min-w-0 flex-1">
                    <div className="text-sm font-medium text-fg truncate">{l.name}</div>
                    <div className="text-[11px] text-fg-dim truncate">
                      <span className="text-accent">{l.path}</span> → {l.target_url}
                    </div>
                  </div>
                  <div className="text-sm tabular-nums text-fg shrink-0">
                    {l.click_count} <span className="text-fg-dim text-[11px]">clicks</span>
                  </div>
                  <div className="flex items-center gap-1.5 shrink-0">
                    <CopyButton text={publicUrl(l.path)} label="Copy link" />
                    <Button size="sm" variant="ghost" onClick={() => setOpenId(openId === l.id ? null : l.id)}>
                      {openId === l.id ? "Hide" : "Analytics"}
                    </Button>
                    <ConfirmDeleteButton
                      confirm={`Delete redirect link "${l.name}"?`}
                      onConfirm={() => deleteM.mutate(l.id)}
                      pending={deleteM.isPending}
                    />
                  </div>
                </div>
                {openId === l.id && accountId && <Analytics accountId={accountId} linkId={l.id} />}
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}

function Analytics({ accountId, linkId }: { accountId: string; linkId: number }) {
  const q = useTrackingAnalytics(accountId, linkId);
  if (q.isLoading) return <div className="text-[11px] text-fg-dim ml-1">Loading analytics…</div>;
  if (q.isError || !q.data) return <div className="text-[11px] text-err ml-1">Failed to load analytics.</div>;
  const a = q.data;
  const max = Math.max(1, ...a.by_day.map((d) => d.clicks));
  return (
    <div className="ml-1 rounded-lg border border-border bg-bg/40 p-3 space-y-2">
      <div className="text-sm text-fg">
        <b>{a.total_clicks}</b> total clicks
        <span className="text-fg-dim text-[11px]"> · subscribers not tracked for off-profile links</span>
      </div>
      {a.by_day.length > 0 ? (
        <div className="flex items-end gap-1 h-16">
          {a.by_day.map((d) => (
            <div key={d.day} className="flex-1 min-w-2 flex flex-col items-center justify-end" title={`${d.day}: ${d.clicks}`}>
              <div className="w-full bg-accent/70 rounded-t" style={{ height: `${(d.clicks / max) * 100}%` }} />
              <span className="text-[8px] text-fg-dim mt-0.5 truncate w-full text-center">{d.day.slice(5)}</span>
            </div>
          ))}
        </div>
      ) : (
        <div className="text-[11px] text-fg-dim">No clicks yet.</div>
      )}
    </div>
  );
}

/** /growth/tracking-links: this tab in the Growth HB frame. */
export function TrackingLinksPage() {
  const { accountId, setAccountId } = useGrowthCreator();
  return (
    <GrowthHbFrame title="Tracking links">
      <TrackingLinksTab accountId={accountId} onAccountChange={setAccountId} />
    </GrowthHbFrame>
  );
}
