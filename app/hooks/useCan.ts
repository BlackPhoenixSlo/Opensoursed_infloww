"use client";

import { useQuery } from "@tanstack/react-query";

import type { ChatterFlatAccountDTO } from "@/contexts/ChatterContext";
import { useOptionalUser } from "@/contexts/UserContext";
import { chatterAccountsQuery } from "@/lib/chatterAccounts";
import { ownerAccountsQuery, type AccountsResp } from "@/lib/ownerAccounts";
import { accountPlatform, can, useFallbackPlatform, type Capability, type AccountPlatform } from "@/lib/platform";

export function useAccountPlatform(accountId: string | null | undefined): AccountPlatform | null {
  const user = useOptionalUser()?.user;
  const owner = useQuery<AccountsResp>({ ...ownerAccountsQuery(user?.user_id), enabled: false }).data;
  const chatter = useQuery<ChatterFlatAccountDTO[]>({ ...chatterAccountsQuery, enabled: false }).data;
  if (!accountId) return null;
  if (user) {
    const a = owner?.accounts?.find((x) => x.id === accountId) ?? owner?.watchers?.find((x) => x.id === accountId);
    return a ? accountPlatform(a) : null;
  }
  const r = chatter?.find((x) => x.account_id === accountId);
  return r?.platform === undefined ? null : accountPlatform(r);
}

export function useCan(accountId: string | null | undefined, cap: Capability): boolean {
  return can(useAccountPlatform(accountId), cap);
}

// D7 keeps OnlyFans toolbar and mass controls visible while the Creator roster loads.
export function useCanOrFallback(accountId: string | null | undefined, cap: Capability): boolean {
  const fallback = useFallbackPlatform();
  return can(useAccountPlatform(accountId) ?? fallback, cap);
}
