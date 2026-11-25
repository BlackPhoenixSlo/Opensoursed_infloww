"use client";


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
