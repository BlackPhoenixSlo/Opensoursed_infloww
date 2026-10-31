"use client";

/**
 * CreatorRail — Smart lists' creator layout for any page under Infloww's 48px header: the 260px creator column
 * (`CreatorColumn`: Search, refresh, "All creators", a row per creator with its photo, online dot and counts) left of
 * the page's content. Below md the column hides and a creator select tops the content instead.
 *
 * The page keeps its own pick (`?creator=`, state, a context): `value` and `onChange` only show and change it.
 * `onAll` makes "All creators" a pick (`value` null while it is on), for pages that work across creators;
 * `noAll` drops the "All creators" row entirely, for pages that always work on one creator.
 */

import type { ReactNode } from "react";

import { CreatorColumn } from "@/components/of-manager/CreatorColumn";
import { IfCreatorSelect } from "@/components/ui/infloww";
import type { AccountMeta } from "@/lib/relay";
import { cn } from "@/lib/utils";

export type CreatorPick = {
  accounts: AccountMeta[];
  value: string | null;
  onChange: (accountId: string) => void;
  onAll?: () => void;
  /** No "All creators" row: the page always works on one creator. */
  noAll?: boolean;
};

export function CreatorRail({ creators, top = "48px", className, children }: {
  creators: CreatorPick;
  /** What sits above the rail under the app chrome: the 48px header, plus any tab bar. */
  top?: string;
  /** The content box (padding and the like). */
  className?: string;
  children: ReactNode;
}) {
  const { accounts, value, onChange, onAll, noAll } = creators;
  return (
    // `.h-chat` on the column subtracts the header (`top`) too.
    <div className="flex min-h-0 min-w-0 flex-1" style={{ ["--shell-top" as string]: `calc(var(--chrome-top) + ${top})` }}>
      <CreatorColumn
        accounts={accounts}
        value={value}
        onChange={onChange}
        all={onAll && { on: value === null, pick: onAll }}
        noAll={noAll}
        className="md:flex w-[260px] border-r border-border"
      />
      <div className="flex min-h-0 min-w-0 flex-1 flex-col">
        {accounts.length > 0 && (
          <div className="border-b border-border px-4 py-2 md:hidden">
            <IfCreatorSelect accounts={accounts} value={value} onChange={onChange} onAll={onAll} />
          </div>
        )}
        <div className={cn("min-w-0 flex-1", className)}>{children}</div>
      </div>
    </div>
  );
}
