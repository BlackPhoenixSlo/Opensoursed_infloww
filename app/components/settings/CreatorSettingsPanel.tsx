"use client";


import { useState, type ReactNode } from "react";

import { useScope } from "@/contexts/ScopeContext";
import { useAccounts, useActiveAccounts } from "@/hooks/useAccounts";
import { SettingsPanel } from "@/components/settings/SettingsPanel";
import { EmptyState, IfCreatorSelect } from "@/components/ui/infloww";
import { Skeleton } from "@/components/ui/Skeleton";

export function CreatorSettingsPanel({ title, emptyText, card, linked = null }: {
  title: string;
  emptyText: string;
  card: (accountId: string) => ReactNode;
  linked?: string | null;
}) {
  const { accountId: scoped } = useScope();
  const accounts = useActiveAccounts();
  const accountsLoading = useAccounts().isLoading;
  const [picked, setPicked] = useState<string | null>(null);
  const fromLink = linked && accounts.some((a) => a.id === linked) ? linked : null;
  const accountId = picked ?? fromLink ?? scoped ?? accounts[0]?.id ?? null;
  const picker = accounts.length > 0 && <IfCreatorSelect accounts={accounts} value={accountId} onChange={setPicked} />;
  return (
    <SettingsPanel title={title} actions={picker}>
      {accountId ? (
        <div key={accountId} className="max-w-xl">{card(accountId)}</div>
      ) : accountsLoading ? (
        <div className="max-w-xl space-y-3" aria-busy="true"><Skeleton className="h-4 w-40" /><Skeleton className="h-10 w-full" /></div>
      ) : (
        <EmptyState kind="data" text={emptyText} className="h-[260px]" />
      )}
    </SettingsPanel>
  );
}
