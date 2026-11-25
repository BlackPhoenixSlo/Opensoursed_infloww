"use client";

// The fansly_manager flag is UI only; the Relay checks every data route anyway.

import Link from "next/link";
import { useMemo } from "react";

import { FanslyEarnings } from "@/components/fansly-manager/FanslyEarnings";
import { FanslyLists } from "@/components/fansly-manager/FanslyLists";
import { FanslyNotifications } from "@/components/fansly-manager/FanslyNotifications";
import { FanslyScheduled } from "@/components/fansly-manager/FanslyScheduled";
import { useFlags } from "@/components/shell/useFlags";
import { EmptyState, IfCreatorSelect, InflowwPageHeader, useCreatorParam } from "@/components/ui/infloww";
import { useAccounts, useActiveAccounts } from "@/hooks/useAccounts";
import type { NavLink } from "@/lib/nav";
import { accountPlatform } from "@/lib/platform";
import { TableSkeleton } from "@/components/ui/Skeleton";

export const BODIES: Record<string, (p: { accountId: string }) => React.ReactNode> = {
  "/fansly-manager/notifications": FanslyNotifications,
  "/fansly-manager/lists": FanslyLists,
  "/fansly-manager/scheduled": FanslyScheduled,
  "/fansly-manager/earning-statistics": FanslyEarnings,
};

export function FanslyManagerPage({ link }: { link: Pick<NavLink, "href" | "label" | "flag"> }) {
  const flags = useFlags();
  const loaded = useAccounts().isSuccess;
  const active = useActiveAccounts();
  const accounts = useMemo(() => active.filter((a) => accountPlatform(a) === "fansly"), [active]);
  const [accountId, setAccountId] = useCreatorParam(accounts);
  const Body = BODIES[link.href];

  if (link.flag && !flags) return <div className="p-4"><TableSkeleton rows={6} /></div>;
  if (link.flag && !flags?.[link.flag]) {
    return (
      <div className="flex h-full min-h-[calc(100dvh-var(--shell-top,56px))] items-center justify-center bg-bg px-6">
        <EmptyState kind="data" text={`${link.label} is not available.`} />
      </div>
    );
  }
  return (
    <div className="flex min-h-[calc(100dvh-var(--shell-top,56px))] flex-col bg-bg">
      <InflowwPageHeader
        title={link.label}
        extra={accounts.length > 0 && <IfCreatorSelect accounts={accounts} value={accountId} onChange={setAccountId} searchable />}
      />
      {accountId ? (
        <Body key={accountId} accountId={accountId} />
      ) : loaded && (
        <EmptyState
          kind="creator"
          className="mt-24"
          text="No Fansly creator is connected."
          action={<Link href="/creators" className="text-[14px] text-accent hover:text-accent-hover">Go to Manage creators</Link>}
        />
      )}
    </div>
  );
}
