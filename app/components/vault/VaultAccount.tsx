"use client";


import {
  createContext, useCallback, useContext, useEffect, useMemo, useState,
} from "react";

import { useAccounts, useActiveAccounts } from "@/hooks/useAccounts";
import type { AccountMeta } from "@/lib/relay";

const STORE_KEY = "vault.accountId";

type VaultAccountCtx = {
  accountId: string | null;
  account: AccountMeta | null;
  accounts: AccountMeta[];
  sessionLost: boolean;
  ready: boolean;
  setAccountId: (id: string) => void;
};

const Ctx = createContext<VaultAccountCtx | null>(null);

function remembered(): string | null {
  try {
    return window.localStorage.getItem(STORE_KEY);
  } catch {
    return null;
  }
}

export function VaultAccountProvider({ children }: { children: React.ReactNode }) {
  const accounts = useActiveAccounts();
  const all = useAccounts().data?.accounts;
  const [accountId, setId] = useState<string | null>(null);

  const known = accountId != null && (all ?? []).some((a) => a.id === accountId);
  const pickable = accountId != null && accounts.some((a) => a.id === accountId);
  const sessionLost = known && !pickable;

  useEffect(() => {
    if (all === undefined) return;
    // A dead session keeps the selection (sessionLost): re-adopting accounts[0] would silently remount the page under another creator.
    if (accountId !== null && known) return;
    if (accounts.length === 0) {
      if (accountId !== null && !known) setId(null);
      return;
    }
    const saved = remembered();
    setId(accounts.find((a) => a.id === saved)?.id ?? accounts[0].id);
  }, [accounts, all, accountId, known]);

  const setAccountId = useCallback((id: string) => {
    setId(id);
    try {
      window.localStorage.setItem(STORE_KEY, id);
    } catch {
    }
  }, []);

  const value = useMemo<VaultAccountCtx>(
    () => ({
      accountId,
      account: (all ?? []).find((a) => a.id === accountId) ?? null,
      accounts,
      sessionLost,
      ready: all !== undefined,
      setAccountId,
    }),
    [accountId, accounts, all, sessionLost, setAccountId],
  );

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useVaultAccount(): VaultAccountCtx {
  const v = useContext(Ctx);
  if (!v) {
    throw new Error("useVaultAccount must be used inside <VaultAccountProvider>");
  }
  return v;
}

export function useVaultAccountId(): string {
  const { accountId } = useVaultAccount();
  if (accountId === null) {
    throw new Error(
      "useVaultAccountId requires a selected model — mount this inside "
      + "VaultBody's accountId branch, not above it",
    );
  }
  return accountId;
}
