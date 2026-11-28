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
  notes?: Record<string, string>;
  chips?: Record<string, string>;
};

export function CreatorRail({ creators, top = "48px", className, children }: {
  creators: CreatorPick;
  top?: string;
  className?: string;
  children: ReactNode;
}) {
  const { accounts, value, onChange, all, watchers, notes, chips } = creators;
  return (
    <div className="flex min-h-0 min-w-0 flex-1 md:flex-initial md:h-[calc(var(--vvh)-var(--shell-top))]" style={{ ["--shell-top" as string]: `calc(var(--chrome-top) + ${top})` }}>
      <CreatorColumn
        accounts={accounts}
        value={value}
        onChange={onChange}
        all={all && { ...all, on: value === null }}
        watchers={watchers}
        notes={notes}
        chips={chips}
        className="md:flex w-[260px] border-r border-border"
      />
      <div className="flex min-h-0 min-w-0 flex-1 flex-col">
        {accounts.length > 0 && (
          <div className="border-b border-border px-4 py-2 md:hidden">
            <IfCreatorSelect accounts={accounts} value={value} onChange={onChange} onAll={all?.pick} allLabel={all?.label} watchers={watchers} chips={chips} />
          </div>
        )}
        <div className={cn("min-h-0 min-w-0 flex-1 md:overflow-y-auto", className)}>{children}</div>
      </div>
    </div>
  );
}
