"use client";


import type { ReactNode } from "react";

import type { GrowthCreator } from "@/hooks/useAccounts";
import { CreatorColumn } from "@/components/of-manager/CreatorColumn";
import { IfCreatorSelect, InflowwPageHeader } from "@/components/ui/infloww";

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
