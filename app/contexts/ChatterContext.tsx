"use client";


import {
  createContext,
  useCallback,
  useContext,
  useMemo,
} from "react";
import {
  keepPreviousData,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

import { clearIdentityMemory, wipeIdentityStorage } from "@/contexts/UserContext";
import { chatterAccountsQuery } from "@/lib/chatterAccounts";
import type { Freshness } from "@/lib/creatorFreshness";
import { takeInline } from "@/lib/inlineBoot";
import { forgetPush } from "@/lib/webPush";
import { isTwoFactorChallenge, postAuthJSON, TwoFactorRequired, type TwoFactorChallenge } from "@/lib/twoFactor";

export interface ChatterOwnerAccountDTO {
  account_id: string;
  nickname: string | null;
  color: string | null;
}

export interface ChatterOwnerDTO {
  user_id: string;
  username: string;
  accounts: ChatterOwnerAccountDTO[];
}

export interface ChatterMeDTO {
  chatter_id: string;
  username: string;
  display_name: string | null;
  color: string | null;
  owners: ChatterOwnerDTO[];
  created_at?: string | null;
}

export interface ChatterFlatAccountDTO {
  account_id: string;
  nickname: string | null;
  color: string | null;
  owner_id: string;
  owner_username: string;
  /** Session dead: automations paused; the picker must not show a parked model as normal. */
  session_dead_at?: string | null;
  session_dead_reason?: string | null;
  is_active: boolean;
  role?: "watcher" | null;
  platform?: string | null;
  freshness?: Freshness;
}

interface ChatterContextValue {
  chatter: ChatterMeDTO | null;
  accounts: ChatterFlatAccountDTO[];
  groupedAccounts: ChatterOwnerDTO[];
  loading: boolean;
  reprobe: () => void;
  login: (username: string, password: string) => Promise<ChatterMeDTO>;
  register: (
    username: string,
    password: string,
    token: string,
    displayName?: string,
  ) => Promise<ChatterMeDTO>;
  logout: () => Promise<void>;
}

const ChatterContext = createContext<ChatterContextValue | null>(null);

function wipeNonChatterCaches(queryClient: ReturnType<typeof useQueryClient>) {
  // Cancel in-flight queries so stale payloads don't re-seed after the clear; the sync setQueryData seed survives.
  try {
    queryClient.cancelQueries({
      predicate: (q) => {
        const head = q.queryKey[0];
        return !(typeof head === "string" && head === "chatter");
      },
    });
  } catch { }
  // Keep the chatter family: login() seeds it first and removing it would null it, flashing Landing before the next notification.
  try {
    queryClient.removeQueries({
      predicate: (q) => {
        const head = q.queryKey[0];
        return !(typeof head === "string" && head === "chatter");
      },
    });
  } catch { }
  clearIdentityMemory();
  void wipeIdentityStorage();
}

export function ChatterProvider({ children }: { children: React.ReactNode }) {
  const queryClient = useQueryClient();

  const meQ = useQuery<ChatterMeDTO | null>({
    queryKey: ["chatter", "self"],
    queryFn: async () => {
      const inline = takeInline("/chatter/me");
      const r = (inline && await inline) ?? await fetch("/chatter/me", {
        credentials: "same-origin",
        headers: { Accept: "application/json" },
      });
      if (!r.ok) return null;
      const body = (await r.json()) as ChatterMeDTO | null;
      return body && body.chatter_id ? body : null;
    },
    staleTime: 5 * 60_000,
    placeholderData: keepPreviousData,
    refetchOnMount: true,
  });

  const accountsQ = useQuery({
    ...chatterAccountsQuery,
    staleTime: 5 * 60_000,
    placeholderData: keepPreviousData,
    enabled: !!meQ.data,
  });

  const accounts = accountsQ.data ?? [];
  const chatter = meQ.data ?? null;
  const groupedAccounts = chatter?.owners ?? [];

  const reprobe = useCallback(() => {
    void queryClient.resetQueries({ queryKey: ["chatter", "self"], exact: true });
  }, [queryClient]);

  const login = useCallback(async (username: string, password: string) => {
    const dto = await postAuthJSON<ChatterMeDTO | TwoFactorChallenge>("/chatter/login", { username, password });
    if (isTwoFactorChallenge(dto)) throw new TwoFactorRequired(dto);
    // Seed BEFORE wiping the rest; the reverse order needed a manual refresh.
    queryClient.setQueryData(["chatter", "self"], dto);
    wipeNonChatterCaches(queryClient);
    return dto;
  }, [queryClient]);

  const register = useCallback(
    async (username: string, password: string, token: string, displayName?: string) => {
      const url = `/chatter/register?token=${encodeURIComponent(token)}`;
      const dto = await postAuthJSON<ChatterMeDTO | TwoFactorChallenge>(url, {
        username, password, display_name: displayName,
      });
      if (isTwoFactorChallenge(dto)) throw new TwoFactorRequired(dto);
      queryClient.setQueryData(["chatter", "self"], dto);
      wipeNonChatterCaches(queryClient);
      return dto;
    },
    [queryClient],
  );

  const logout = useCallback(async () => {
    forgetPush();
    try { await postAuthJSON<unknown>("/chatter/logout", {}); } catch { }
    try { queryClient.cancelQueries(); } catch { }
    try { queryClient.clear(); } catch { }
    queryClient.setQueryData(["chatter", "self"], null);
    queryClient.setQueryData(chatterAccountsQuery.queryKey, []);
    // The snapshot delete must commit before the navigation tears the page down.
    await wipeIdentityStorage();
    // Hard navigate via replace(): a setState-only path lost a race with meQ's refetch, which resurfaced the previous chatter.
    if (typeof window !== "undefined") {
      window.location.replace("/");
    }
  }, [queryClient]);

  const value = useMemo<ChatterContextValue>(() => ({
    chatter,
    accounts,
    groupedAccounts,
    loading: meQ.isLoading,
    reprobe,
    login,
    register,
    logout,
  }), [chatter, accounts, groupedAccounts, meQ.isLoading, reprobe, login, register, logout]);

  return <ChatterContext.Provider value={value}>{children}</ChatterContext.Provider>;
}

export function useChatter(): ChatterContextValue {
  const ctx = useContext(ChatterContext);
  if (!ctx) throw new Error("useChatter called outside <ChatterProvider>");
  return ctx;
}

export function useOptionalChatter(): ChatterContextValue | null {
  return useContext(ChatterContext);
}
