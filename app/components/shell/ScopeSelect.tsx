"use client";

/**
 * ScopeSelect — the creator picker below lg, where a page's own picker hides (OF Manager's creator column, Messages
 * Pro's Creator tabs): each creator, read from and written to ScopeContext. The top bar has no model filter, so this is
 * the only switch there. `pickAll` adds "All creators" first and runs on it (Messages Pro's unified inbox warms every
 * creator); without it there is none (OF Manager: always one creator, owner 2026-11-20). `onPicked` runs after any pick.
 */

import { useScope } from "@/contexts/ScopeContext";
import { IfSelect, type IfOption } from "@/components/ui/infloww";
import type { AccountMeta } from "@/lib/relay";
import { cn } from "@/lib/utils";

const ALL = "__all__";

export function ScopeSelect({ accounts, pickAll, onPicked, className }: {
  accounts: AccountMeta[];
  pickAll?: () => void;
  onPicked?: () => void;
  className?: string;
}) {
  const { scope, setScope } = useScope();
  const options: IfOption[] = [
    ...(pickAll ? [{ value: ALL, label: "All creators" }] : []),
    // OF Manager's list carries its watchers (useOfManagerAccounts), named so they are not taken for Creators.
    ...accounts.map((a) => ({ value: a.id, label: `${a.nickname || a.name || a.id}${a.role === "watcher" ? " (watcher)" : ""}` })),
  ];
  return (
    <IfSelect
      aria-label="Creator"
      value={scope.kind === "model" ? scope.accountId : ALL}
      options={options}
      searchable={accounts.length > 8}
      onChange={(v) => {
        if (v !== ALL) setScope({ kind: "model", accountId: v });
        else pickAll?.();
        onPicked?.();
      }}
      className={cn("w-[180px]", className)}
    />
  );
}
