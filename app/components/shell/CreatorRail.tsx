"use client";


import type { ReactNode } from "react";

import { CreatorColumn, type AllPick } from "@/components/of-manager/CreatorColumn";
import { IfCreatorSelect } from "@/components/ui/infloww";
import type { AccountMeta, WatcherAccount } from "@/lib/relay";
import { cn } from "@/lib/utils";

export type CreatorPick = {
  accounts: AccountMeta[];
  value: string | null;
  onChange: (accountId: string) => void;
  all?: Omit<AllPick, "on">;
  watchers?: WatcherAccount[];
};

export function CreatorRail({ creators, top = "48px", className, children }: {
  creators: CreatorPick;
  top?: string;
  className?: string;
  children: ReactNode;
}) {
  const { accounts, value, onChange, all, watchers } = creators;
  return (
    <div className="flex min-h-0 min-w-0 flex-1" style={{ ["--shell-top" as string]: `calc(var(--chrome-top) + ${top})` }}>
      <CreatorColumn
        accounts={accounts}
        value={value}
        onChange={onChange}
        all={all && { ...all, on: value === null }}
        watchers={watchers}
        className="md:flex w-[260px] border-r border-border"
      />
      <div className="flex min-h-0 min-w-0 flex-1 flex-col">
        {accounts.length > 0 && (
          <div className="border-b border-border px-4 py-2 md:hidden">
            <IfCreatorSelect accounts={accounts} value={value} onChange={onChange} onAll={all?.pick} allLabel={all?.label} watchers={watchers} />
          </div>
        )}
        <div className={cn("min-w-0 flex-1", className)}>{children}</div>
      </div>
    </div>
  );
}
