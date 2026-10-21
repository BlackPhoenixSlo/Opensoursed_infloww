"use client";

/**
 * GrowthTabPage — one Growth sub-page (Smart lists, Auto-follow, Profile
 * promotion, Free trial links, Tracking links). Was the tab strip on /growth;
 * each tab is now its own sidebar route, and /growth?tab=… redirects to it
 * (next.config.ts). The picked creator is shared; the frame is Infloww's per page: the HB frame for Tracking and
 * Free trial links, the legacy header with the creator rail for Profile promotion and Smart lists, the legacy
 * header alone for Auto-follow.
 */

import { useState } from "react";

import { useActiveAccounts } from "@/hooks/useAccounts";
import SmartListsTab, { SMART_LISTS_ABOUT } from "@/components/growth/SmartListsTab";
import TrialLinksTab from "@/components/growth/TrialLinksTab";
import TrackingLinksTab from "@/components/growth/TrackingLinksTab";
import { ReportTimeZone } from "@/components/growth/LinksListFrame";
import PromotionTab from "@/components/growth/PromotionTab";
import AutoFollowList from "@/components/growth/AutoFollowList";
import { CreatorColumn } from "@/components/of-manager/OfManagerChrome";
import { IfCreatorSelect, InflowwPageHeader } from "@/components/ui/infloww";

/** The Growth sub-pages, by their old `/growth?tab=` key. */
type GrowthTab = "smart" | "trial" | "tracking" | "promotion" | "auto_follow";

/** Tab key → page title. The keys are the old `/growth?tab=` values; the
 *  assistant's link table (components/assistant/answerLinks.ts) is checked
 *  against them. */
const TABS: Array<{ key: GrowthTab; label: string }> = [
  { key: "smart", label: "Smart lists" },
  { key: "trial", label: "Free trial links" },
  { key: "tracking", label: "Tracking links" },
  { key: "promotion", label: "Profile promotion" },
  { key: "auto_follow", label: "Auto-follow" },
];

export default function GrowthTabPage({ tab }: { tab: GrowthTab }) {
  const accounts = useActiveAccounts();
  const [picked, setAccountId] = useState<string | null>(null);
  // Default to the first account until the user picks one.
  const accountId = picked ?? accounts[0]?.id ?? null;
  const title = TABS.find((t) => t.key === tab)?.label ?? "Growth";

  // Tracking links and Free trial links are one HB frame (its Layout capture, #4 to #9): the HB body, a 16px-padded
  // header with a 24px weight-500 title and the report time zone; its own panels carry the 16px sides. With no
  // Creator it still draws the whole frame (the Creator filter empty, Create disabled, the table's "No data").
  if (tab === "tracking" || tab === "trial") {
    return (
      <div className="min-h-full bg-hb-bg">
        <header className="flex flex-wrap items-start justify-between gap-3 p-4">
          <div className="flex flex-wrap items-center min-w-0">
            <h1 className="text-2xl font-medium leading-[1.1667]">{title}</h1>
            <ReportTimeZone />
          </div>
        </header>
        {tab === "tracking"
          ? <TrackingLinksTab accountId={accountId} onAccountChange={setAccountId} />
          : <TrialLinksTab accountId={accountId} onAccountChange={setAccountId} />}
      </div>
    );
  }

  // Auto-follow is a legacy page with no rail: the 48px header, then the list 16px in. It lists every creator with
  // its own Creator filter, so it draws (an empty table) with none.
  if (tab === "auto_follow") {
    return (
      <div className="flex min-h-full flex-col">
        <InflowwPageHeader title={title} />
        <AutoFollowList accounts={accounts} />
      </div>
    );
  }

  // Profile promotion and Smart lists are legacy antd pages with a creator rail (`PromotionLayout`,
  // `ErrorModalListLayout`): the 48px header, then the 260px rail (OF Manager's column, controlled here) beside the
  // content 24px in. Below md the rail gives way to the creator select. With no Creator the frame still draws.
  return (
    <div className="flex min-h-full flex-col">
      <InflowwPageHeader title={tab === "smart" ? <span title={SMART_LISTS_ABOUT}>{title}</span> : title} />
      {/* `.h-chat` on the rail subtracts the 48px header too. */}
      <div className="flex flex-1" style={{ ["--shell-top" as string]: "calc(var(--chrome-top) + 48px)" }}>
        <CreatorColumn
          accounts={accounts}
          value={accountId}
          onChange={setAccountId}
          className="md:flex w-[260px] border-r border-border"
        />
        <div className="min-w-0 flex-1 px-6 py-4">
          {accounts.length > 0 && (
            <IfCreatorSelect accounts={accounts} value={accountId} onChange={setAccountId} className="mb-4 md:hidden" />
          )}
          {tab === "smart" ? <SmartListsTab accountId={accountId} /> : <PromotionTab accountId={accountId} />}
        </div>
      </div>
    </div>
  );
}
