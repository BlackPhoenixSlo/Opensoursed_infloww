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
 * appears by itself once its `cell` returns a value for some row (`TrackingLinksList`'s METRIC_COLS).
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
 *
 * Files: this tab shell; the Links list, its columns, `useLinks` and Export in `TrackingLinksList`; Details in
 * `TrackingLinkDetails`; the Dashboard in `TrackingDashboard`; `CreateLinkModal`; `CustomRedirects` with its
 * Analytics; the formulas and tooltips in `linkMetrics`.
 */

import { useState } from "react";

import { FrameTabs, GrowthHbFrame } from "@/components/growth/LinksListFrame";
import ShareLinksPanel from "@/components/growth/ShareLinksPanel";
import { LinksList } from "@/components/growth/TrackingLinksList";
import { Dashboard } from "@/components/growth/TrackingDashboard";
import { useOfTrackingLinks } from "@/hooks/useGrowth";
import { useGrowthCreator } from "@/hooks/useAccounts";
import { useUser } from "@/contexts/UserContext";

type TabKey = "list" | "dashboard" | "share";
const TABS: Array<{ key: TabKey; label: string }> = [
  { key: "list", label: "Links list" },
  { key: "dashboard", label: "Dashboard" },
  { key: "share", label: "Share links" },
];

export default function TrackingLinksTab({
  accountId, onAccountChange, accountsLoading = false,
}: {
  accountId: string | null;
  /** The Creators are still loading: the list is loading, not empty. */
  accountsLoading?: boolean;
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
          ? <LinksList accountId={accountId} onAccountChange={onAccountChange} net={net} onNet={setNet} accountsLoading={accountsLoading} />
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

/** /growth/tracking-links: this tab in the Growth HB frame. */
export function TrackingLinksPage() {
  const { accountId, setAccountId, loading } = useGrowthCreator();
  return (
    <GrowthHbFrame title="Tracking links">
      <TrackingLinksTab accountId={accountId} onAccountChange={setAccountId} accountsLoading={loading} />
    </GrowthHbFrame>
  );
}
