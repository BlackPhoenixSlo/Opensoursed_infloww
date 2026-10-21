"use client";

/**
 * ScopeSelect — the creator picker below lg, where a page's own picker hides (OF Manager's creator column, Messages
 * Pro's Creator tabs): "All creators", then each creator, read from and written to ScopeContext. The top bar has no
 * model filter, so this is the only switch there. `pickAll` replaces the plain "All creators" scope change (Messages
 * Pro's warms every creator); `onPicked` runs after any pick.
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
    { value: ALL, label: "All creators" },
    ...accounts.map((a) => ({ value: a.id, label: a.nickname || a.name || a.id })),
  ];
  return (
    <IfSelect
      aria-label="Creator"
      value={scope.kind === "model" ? scope.accountId : ALL}
      options={options}
      searchable={accounts.length > 8}
      onChange={(v) => {
        if (v !== ALL) setScope({ kind: "model", accountId: v });
        else if (pickAll) pickAll();
        else setScope({ kind: "all" });
        onPicked?.();
      }}
      className={cn("w-[180px]", className)}
    />
  );
}
