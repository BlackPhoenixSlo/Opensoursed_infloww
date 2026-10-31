"use client";

/**
 * The single-model picker of the per-account post tabs (Posts, My feed, Top posts): one option per active model,
 * "No models" while there are none, and "" chosen reads as no model.
 */

import { useEffect, useState } from "react";

import { useActiveAccounts } from "@/hooks/useAccounts";
import type { AccountMeta } from "@/lib/relay";

/**
 * The active models plus the picked one: null until the list loads, then the first model, then whatever the user
 * picks. A pick (default included) is a latched state, not derived, so it stays when that model leaves the list.
 */
export function usePickedModel() {
  const accounts = useActiveAccounts();
  const [accountId, setAccountId] = useState<string | null>(null);

  useEffect(() => {
    if (accountId == null && accounts.length > 0) setAccountId(accounts[0].id);
  }, [accounts, accountId]);

  return { accounts, accountId, setAccountId };
}

interface Props {
  accounts: AccountMeta[];
  value: string | null;
  onChange: (accountId: string | null) => void;
}

export default function ModelSelect({ accounts, value, onChange }: Props) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-[10px] uppercase tracking-wide text-fg-dim">Model</span>
      <select
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value || null)}
        className="bg-bg border border-border rounded-lg px-3 py-2 text-base md:px-2 md:py-1.5 md:text-xs text-fg focus:outline-none focus:border-accent"
      >
        {accounts.length === 0 && <option value="">No models</option>}
        {accounts.map((a) => (
          <option key={a.id} value={a.id}>
            {a.nickname || a.id}
          </option>
        ))}
      </select>
    </label>
  );
}
