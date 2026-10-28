"use client";

/**
 * GrowthFrame — the frames of the Growth sub-pages that were /growth's tab strip (Smart lists, Auto-follow, Profile
 * promotion, Free trial links, Tracking links). Each tab is now its own sidebar route, and /growth?tab=… redirects to
 * it (next.config.ts). The frame is Infloww's per page: the HB frame (`GrowthHbFrame`, in LinksListFrame) for Tracking
 * and Free trial links, the legacy header with the creator rail (`GrowthRailFrame`, here) for Profile promotion and
 * Smart lists, the legacy header alone for Auto-follow (AutoFollowPage). `useGrowthCreator` (hooks/useAccounts) is the
 * picked creator the frame and the page share. Each route's page (AutoFollowPage, SmartListsPage, PromotionPage,
 * TrialLinksPage, TrackingLinksPage, beside its tab) renders its frame, so a route's first load carries its own tab
 * and frame alone and not the other four (Free trial links' OF mirror among them, the rail's CreatorColumn only where
 * a rail is drawn).
 */

import type { ReactNode } from "react";

import type { GrowthCreator } from "@/hooks/useAccounts";
import { CreatorColumn } from "@/components/of-manager/CreatorColumn";
import { IfCreatorSelect, InflowwPageHeader } from "@/components/ui/infloww";

/** Profile promotion and Smart lists are legacy antd pages with a creator rail (`PromotionLayout`,
 *  `ErrorModalListLayout`): the 48px header, then the 260px rail (OF Manager's column, controlled by the page's
 *  `creator`) beside the content 24px in. Below md the rail gives way to the creator select. With no Creator the frame
 *  still draws. */
export function GrowthRailFrame({ title, creator: { accounts, accountId, setAccountId }, children }: {
  title: ReactNode;
  creator: GrowthCreator;
  children: ReactNode;
}) {
  return (
    <div className="flex min-h-full flex-col">
      <InflowwPageHeader title={title} />
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
          {children}
        </div>
      </div>
    </div>
  );
}
