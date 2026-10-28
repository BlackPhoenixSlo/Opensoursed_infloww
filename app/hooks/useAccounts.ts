"use client";

/**
 * useAccounts — list of model accounts with sessions.
 *
 * Phase B drives the Unified Inbox fan-out. When ScopeContext is `all`,
 * we fan a chat-list query out across every account here and merge
 * client-side. Per-account scope just filters this list down to one.
 *
 * Source of truth depends on the active principal:
 *   - User (owner) session    → GET /admin/accounts
 *   - Chatter-only session    → GET /chatter/me/accounts (union across
 *                                 every linked owner, denormalised)
 *
 * The `{accounts, active_account_id}` envelope is preserved either way so
 * downstream consumers (chat fan-out, mass composer, sidebar) don't need
 * to know which principal is driving the request.
 */

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { relay, type AccountMeta } from "@/lib/relay";
import { useUser } from "@/contexts/UserContext";
import { useChatter } from "@/contexts/ChatterContext";
import { chatterAccountsQuery } from "@/lib/chatterAccounts";
import { accountPlatform, usePlatform } from "@/lib/platform";

export interface AccountsResp {
  accounts: AccountMeta[];
  active_account_id: string | null;
}

/** GET /admin/accounts, with `is_active` made total: a relay from before Creator deactivation (and a test fixture)
 *  omits it, and an omitted flag is an active Creator. The one place that default lives, so every reader can treat
 *  `is_active` as the plain boolean its type says. */
export async function fetchAccounts(): Promise<AccountsResp> {
  const r = await relay.get<AccountsResp>("/admin/accounts");
  return { ...r, accounts: (r.accounts ?? []).map((a) => ({ ...a, is_active: a.is_active ?? true })) };
}

export function useAccounts() {
  const { user } = useUser();
  const { chatter } = useChatter();
  // Chatter-only principal reads from /chatter/me/accounts; the
  // /admin/accounts endpoint is owner-only (403 under chatter session).
  const isChatterOnly = !user && !!chatter;

  const ownerQ = useQuery<AccountsResp>({
    // Scope the cache entry to the signed-in principal. /admin/accounts
    // returns the FULL multi-tenant registry when called UNauthenticated
    // (the dev-curl fallback). Under a principal-agnostic key, a list
    // fetched in an unauthed window (app boot before /auth/me resolves, a
    // brief session expiry) would persist for `staleTime` and bleed into
    // the next owner's session — surfacing another owner's models in this
    // owner's picker, then 403'ing on any write ("account X is not one of
    // yours"). Keying by user_id isolates it per principal.
    queryKey: ["accounts", user?.user_id ?? "anon"],
    queryFn: fetchAccounts,
    // Short staleTime on purpose: /admin/accounts is a relay-local
    // registry read (no OF call), and a long window meant a model
    // captured in another session stayed invisible until re-login —
    // the persisted cache survives page reloads, so staleTime was the
    // only expiry. 60s caps refetches at ~1/min per tab.
    staleTime: 60_000,
    refetchOnWindowFocus: false,
    // Never fetch the owner list until the principal is known — an
    // /admin/accounts call fired while `user` is still null hits the
    // unauthed full-list path and is exactly what poisons the cache above.
    enabled: !isChatterOnly && !!user,
  });

  const chatterQ = useQuery({
    // ChatterContext's query: one cache entry, no duplicate request.
    ...chatterAccountsQuery,
    staleTime: 5 * 60_000,
    refetchOnWindowFocus: false,
    enabled: isChatterOnly,
  });

  // Normalize chatter accounts into AccountMeta-shaped rows so every
  // downstream consumer keeps working unmodified. has_session=true is a
  // best-effort assumption — the relay grant is the source of truth that
  // the owner intended this chatter to use this account.
  const chatterAccounts: AccountMeta[] = useMemo(() => {
    const rows = chatterQ.data || [];
    return rows.map((r) => ({
      id: r.account_id,
      nickname: r.nickname,
      color: r.color,
      has_session: true,
      // Carry the pause through: has_session=true above is an assumption, so
      // without these two the chatter picker would render a model whose
      // automations are parked as indistinguishable from a working one.
      session_dead_at: r.session_dead_at,
      session_dead_reason: r.session_dead_reason,
      is_active: r.is_active,
    } as AccountMeta));
  }, [chatterQ.data]);

  // Synthesize an AccountsResp envelope so consumers see the same shape
  // either way. active_account_id is owner-only — no equivalent in
  // chatter mode (the picker selection lives in ScopeContext anyway).
  // Memoize the envelope on chatterAccounts alone so its reference stays
  // stable across renders (useQuery hands back a fresh object every render,
  // so depending on chatterQ would recompute this every time).
  const chatterData: AccountsResp = useMemo(
    () => ({ accounts: chatterAccounts, active_account_id: null }),
    [chatterAccounts],
  );
  return useMemo(() => {
    if (isChatterOnly) {
      return { ...chatterQ, data: chatterData };
    }
    return ownerQ;
  }, [isChatterOnly, chatterQ.status, chatterData, ownerQ]);
}

/** Human name for a model account — its nickname ("JadeFree") when the owner
 *  set one, else the raw account id as a fallback. Reads the FULL account list
 *  rather than useActiveAccounts() so a model whose session dropped still
 *  renders by name instead of silently reverting to a number. */
export function useAccountLabel(accountId?: string | null): string {
  const q = useAccounts();
  const all = q.data?.accounts;
  return useMemo(() => {
    if (!accountId) return "";
    return (all ?? []).find((a) => a.id === accountId)?.nickname || accountId;
  }, [all, accountId]);
}

/** Accounts that currently have a captured session and are not deactivated
 *  — the only ones the relay works for. Used by the chat-list fan-out (no
 *  point querying /chats for an account with no session — it'll 503). A
 *  deactivated Creator drops out of every surface reading this (switcher,
 *  inbox, composers); reports and the Creators page read useAccounts and keep
 *  its row.
 *
 *  Every platform's: the notification toaster, the bell, the money rail and
 *  the inbox realtime read this, so a Fansly-mode shell still hears OnlyFans.
 *  The surfaces that follow the platform selector read usePlatformAccounts.
 *
 *  Memoized on the underlying accounts array so the returned reference is
 *  stable when the data hasn't changed. Without this, consumers using the
 *  result in `useEffect` / `useMemo` deps see a new reference every render
 *  — e.g. the inbox warmer effect was cancelling and restarting on each
 *  parent render, and the spend/activity memos were never hitting. */
export function useActiveAccounts(): AccountMeta[] {
  const q = useAccounts();
  const all = q.data?.accounts;
  return useMemo(
    () => (all ?? []).filter((a) => a.has_session && a.is_active),
    [all],
  );
}

/** useActiveAccounts on the sidebar platform alone (lib/platform): Infloww's
 *  OnlyFans and Fansly shells each list their own creators. The creator
 *  switcher, Messages Pro's tabs and fan list, the chat-list fan-out, the
 *  composers and "pick all models" read it; global listeners must not (they
 *  read useActiveAccounts). A chatter's accounts carry no platform and count
 *  as OnlyFans. */
export function usePlatformAccounts(): AccountMeta[] {
  const accounts = useActiveAccounts();
  const platform = usePlatform();
  return useMemo(() => accounts.filter((a) => accountPlatform(a) === platform), [accounts, platform]);
}

/** The creators, and the picked one (shared by the rail and the selects). */
export interface GrowthCreator {
  accounts: AccountMeta[];
  accountId: string | null;
  setAccountId: (id: string) => void;
}

/** The creator a Growth page and its frame share: Tracking and Free trial links' Creator filter, Profile promotion's
 *  and Smart lists' rail (`growth/GrowthFrame`). */
export function useGrowthCreator(): GrowthCreator {
  const accounts = useActiveAccounts();
  const [picked, setAccountId] = useState<string | null>(null);
  // Default to the first account until the user picks one.
  const accountId = picked ?? accounts[0]?.id ?? null;
  return { accounts, accountId, setAccountId };
}
