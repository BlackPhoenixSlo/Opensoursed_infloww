"use client";

/**
 * CreatorRail — Smart lists' creator layout for any page under Infloww's 48px header: the 260px creator column
 * (`CreatorColumn`: Search, refresh, a row per creator with its photo, online dot and counts) left of
 * the page's content. Below md the column hides and a creator select tops the content instead.
 *
 * The page keeps its own pick (`?creator=`, state, a context): `value` and `onChange` only show and change it.
 * `all` makes "All creators" a pick (`value` null while it is on), for pages that work across creators; without it
 * there is no "All creators" row (owner 2026-11-20: only pages where it means something offer it).
 * `watchers` lists the owner's watcher accounts after the creators as dimmed rows that cannot be picked (a watcher is no Creator, but the owner must still see it exists); only a page that passes it shows them.
 */

import type { ReactNode } from "react";

import { CreatorColumn, type AllPick } from "@/components/of-manager/CreatorColumn";
import { IfCreatorSelect } from "@/components/ui/infloww";
import type { AccountMeta, WatcherAccount } from "@/lib/relay";
import { cn } from "@/lib/utils";

export type CreatorPick = {
  accounts: AccountMeta[];
  value: string | null;
  onChange: (accountId: string) => void;
  /** The "All creators" pick: `label` relabels it (Scripts' "All models"), default "All creators"; `row` shows it as a
   *  creator row with a rainbow tile, one click, else in the menu. */
  all?: Omit<AllPick, "on">;
  /** Watcher accounts, shown after the creators as non-selectable rows. */
  watchers?: WatcherAccount[];
};

export function CreatorRail({ creators, top = "48px", className, children }: {
  creators: CreatorPick;
  /** What sits above the rail under the app chrome: the 48px header, plus any tab bar. */
  top?: string;
  /** The content box (padding and the like). */
  className?: string;
  children: ReactNode;
}) {
  const { accounts, value, onChange, all, watchers } = creators;
  return (
    // `.h-chat` on the column subtracts the header (`top`) too.
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
