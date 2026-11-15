"use client";

/**
 * Settings › OnlyFans consent: one Creator's "Auto-accept OnlyFans consent" switch (OfConsentCard).
 * The Creator is picked in the panel header: `?account=<id>` (a consent notice's link) when it is one of
 * the session-backed Creators, else the one in scope, else the first.
 */

import { Suspense, useState } from "react";
import { useSearchParams } from "next/navigation";

import { useScope } from "@/contexts/ScopeContext";
import { useAccounts, useActiveAccounts } from "@/hooks/useAccounts";
import { OfConsentCard } from "@/components/settings/OfConsentCard";
import { SettingsPanel } from "@/components/settings/SettingsPanel";
import { EmptyState, IfCreatorSelect } from "@/components/ui/infloww";
import { Skeleton } from "@/components/ui/Skeleton";

export default function OfConsentTab() {
  // useSearchParams suspends while the page prerenders: its own boundary.
  return <Suspense fallback={null}><ConsentPanel /></Suspense>;
}

function ConsentPanel() {
  const linked = useSearchParams()?.get("account") ?? null;
  const { accountId: scoped } = useScope();
  const accounts = useActiveAccounts();
  const accountsLoading = useAccounts().isLoading;
  const [picked, setPicked] = useState<string | null>(null);
  const fromLink = linked && accounts.some((a) => a.id === linked) ? linked : null;
  const accountId = picked ?? fromLink ?? scoped ?? accounts[0]?.id ?? null;
  const picker = accounts.length > 0 && <IfCreatorSelect accounts={accounts} value={accountId} onChange={setPicked} />;
  return (
    <SettingsPanel title="OnlyFans consent" actions={picker}>
      {accountId ? (
        <div className="max-w-xl"><OfConsentCard key={accountId} accountId={accountId} /></div>
      ) : accountsLoading ? (
        <div className="max-w-xl space-y-3" aria-busy="true"><Skeleton className="h-4 w-40" /><Skeleton className="h-10 w-full" /></div>
      ) : (
        <EmptyState kind="data" text="Select a creator to set its OnlyFans consent" className="h-[260px]" />
      )}
    </SettingsPanel>
  );
}
