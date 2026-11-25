"use client";


import { useState, type ReactNode } from "react";
import { useSearchParams } from "next/navigation";

import { FrameTabs, GrowthHbFrame, type FrameTab } from "@/components/growth/LinksListFrame";
import ShareLinksPanel from "@/components/growth/ShareLinksPanel";
import { LinksList } from "@/components/growth/TrackingLinksList";
import { Dashboard } from "@/components/growth/TrackingDashboard";
import { useOfTrackingLinks } from "@/hooks/useGrowth";
import { useGrowthCreator } from "@/hooks/useAccounts";
import { useUser } from "@/contexts/UserContext";

type TabKey = "list" | "dashboard" | "share";
const TABS: Array<FrameTab<TabKey> & { ownerOnly?: true }> = [
  { key: "list", label: "Links list" },
  { key: "dashboard", label: "Dashboard" },
  { key: "share", label: "Share links", ownerOnly: true },
];
const isTabKey = (v: string): v is TabKey => TABS.some((t) => t.key === v);

export default function TrackingLinksTab({
  accountId, onAccountChange, accountsLoading = false,
}: {
  accountId: string | null;
  accountsLoading?: boolean;
  onAccountChange: (id: string) => void;
}) {
  const owner = !!useUser().user;
  const search = useSearchParams();
  const searchKey = search.toString();
  const [chosen, setChosen] = useState<{ searchKey: string; tab: TabKey } | null>(null);
  const setTab = (tab: TabKey) => setChosen({ searchKey, tab });
  const tabs = TABS.filter((t) => owner || !t.ownerOnly);
  const requested = search.get("tab");
  const selected = chosen?.searchKey === searchKey ? chosen.tab : requested && isTabKey(requested) ? requested : "list";
  const tab = tabs.some((t) => t.key === selected) ? selected : "list";
  const [net, setNet] = useState(true);
  const panels: Record<TabKey, ReactNode> = {
    list: <LinksList accountId={accountId} onAccountChange={onAccountChange} net={net} onNet={setNet} accountsLoading={accountsLoading} />,
    dashboard: <Dashboard accountId={accountId} onAccountChange={onAccountChange} net={net} onNet={setNet} />,
    share: <TrackingShares accountId={accountId} onAccountChange={onAccountChange} />,
  };
  return (
    <div>
      <FrameTabs tabs={tabs} value={tab} onChange={setTab} label="Tracking links" idPrefix="tl" />
      <div role="tabpanel" id={`tl-panel-${tab}`} aria-labelledby={`tl-tab-${tab}`}>
        {panels[tab]}
      </div>
    </div>
  );
}

function TrackingShares({ accountId, onAccountChange }: { accountId: string | null; onAccountChange: (id: string) => void }) {
  const q = useOfTrackingLinks(accountId);
  const links = (q.data?.links ?? []).filter((l) => l.id != null).map((l) => ({ ofId: l.id!, name: l.name }));
  return <ShareLinksPanel accountId={accountId} onAccountChange={onAccountChange} kind="campaign" links={links} />;
}

export function TrackingLinksPage() {
  const { accountId, setAccountId, loading } = useGrowthCreator();
  return (
    <GrowthHbFrame title="Tracking links">
      <TrackingLinksTab accountId={accountId} onAccountChange={setAccountId} accountsLoading={loading} />
    </GrowthHbFrame>
  );
}
