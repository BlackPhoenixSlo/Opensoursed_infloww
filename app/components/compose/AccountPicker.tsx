"use client";


import { useEffect, useId, useMemo } from "react";

import { usePlatformAccounts } from "@/hooks/useAccounts";
import { useAllModelsInclude } from "@/hooks/useAllModelsInclude";
import { useScope } from "@/contexts/ScopeContext";
import { IfLabel, IfNativeSelect } from "@/components/ui/infloww";
import { useCreatorPlatformName } from "@/components/shell/PlatformSwitcher";
import type { AccountMeta } from "@/lib/relay";

export function AccountPicker({
  value, onChange, accounts: senders,
}: {
  value: string | null;
  onChange: (id: string) => void;
  accounts?: readonly AccountMeta[];
}) {
  const platformAccounts = usePlatformAccounts();
  const accounts = senders ?? platformAccounts;
  const { isIncluded } = useAllModelsInclude();
  const { scope } = useScope();
  const platformName = useCreatorPlatformName();

  const visibleAccounts = useMemo(
    () => accounts.filter((a) => isIncluded(a.id) || a.id === value),
    [accounts, isIncluded, value],
  );

  useEffect(() => {
    if (value) return;
    const seed = scope.kind === "model" ? scope.accountId : visibleAccounts[0]?.id;
    if (seed) onChange(seed);
  }, [value, scope, visibleAccounts, onChange]);

  const id = useId();
  return (
    <div>
      <IfLabel htmlFor={id}>Post as</IfLabel>
      <IfNativeSelect
        id={id}
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value)}
        className="w-full"
      >
        {visibleAccounts.length === 0 && <option value="">(no active sessions)</option>}
        {visibleAccounts.map((a) => {
          const badge = platformName(a);
          return (
            <option key={a.id} value={a.id}>
              {badge ? `${a.nickname || a.id} · ${badge}` : a.nickname || a.id}
            </option>
          );
        })}
      </IfNativeSelect>
    </div>
  );
}
