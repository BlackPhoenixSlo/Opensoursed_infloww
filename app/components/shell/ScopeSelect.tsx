"use client";


import { CreatorPlatformBadge, useCreatorPlatformName } from "@/components/shell/PlatformSwitcher";
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
  const platformName = useCreatorPlatformName();
  const options: IfOption[] = [
    ...(pickAll ? [{ value: ALL, label: "All creators" }] : []),
    ...accounts.map((a) => {
      const text = `${a.nickname || a.name || a.id}${a.role === "watcher" ? " (watcher)" : ""}`;
      if (!platformName(a)) return { value: a.id, label: text };
      return { value: a.id, text, label: <span className="inline-flex items-center gap-1">{text}<CreatorPlatformBadge account={a} /></span> };
    }),
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
