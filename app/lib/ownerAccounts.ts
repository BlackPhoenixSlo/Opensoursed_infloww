/**
 * GET /admin/accounts: one key and fetch for useAccounts and the readers that peek at its cache entry
 * (useOfRichAllowed, useRosterCounts). Its own module rather than an export of useAccounts, which many tests mock.
 */

import { relay, type AccountMeta, type WatcherAccount } from "@/lib/relay";

export interface AccountsResp {
  accounts: AccountMeta[];
  active_account_id: string | null;
  /** The caller's watcher accounts (`role` "watcher": fan accounts the Library's Suggestions read), never in
   *  `accounts`: Manage creators and OF Manager (useOfManagerAccounts) list them, nothing else picks them. Always set
   *  after fetchAccounts. */
  watchers?: WatcherAccount[];
}

/** GET /admin/accounts, with `is_active` made total: a relay from before Creator deactivation (and a test fixture)
 *  omits it, and an omitted flag is an active Creator. The one place that default lives, so every reader can treat
 *  `is_active` as the plain boolean its type says. `watchers` likewise: an older relay omits it, read as none. */
export async function fetchAccounts(): Promise<AccountsResp> {
  const r = await relay.get<AccountsResp>("/admin/accounts");
  return {
    ...r,
    accounts: (r.accounts ?? []).map((a) => ({ ...a, is_active: a.is_active ?? true })),
    watchers: (r.watchers ?? []).map((w) => ({ ...w, is_active: w.is_active ?? true, proxy_down: !!w.proxy_down, role: "watcher" })),
  };
}

/** The owner's account list query (key + fetcher + freshness): `useAccounts` reads it, `useOfRichAllowed` peeks at
 *  its cache under the same entry. */
export const ownerAccountsQuery = (userId: string | undefined) => ({
  // Scope the cache entry to the signed-in principal. /admin/accounts
  // returns the FULL multi-tenant registry when called UNauthenticated
  // (the dev-curl fallback). Under a principal-agnostic key, a list
  // fetched in an unauthed window (app boot before /auth/me resolves, a
  // brief session expiry) would persist for `staleTime` and bleed into
  // the next owner's session — surfacing another owner's models in this
  // owner's picker, then 403'ing on any write ("account X is not one of
  // yours"). Keying by user_id isolates it per principal.
  queryKey: ["accounts", userId ?? "anon"],
  queryFn: fetchAccounts,
  // Short staleTime on purpose: /admin/accounts is a relay-local
  // registry read (no OF call), and a long window meant a model
  // captured in another session stayed invisible until re-login —
  // the persisted cache survives page reloads, so staleTime was the
  // only expiry. 60s caps refetches at ~1/min per tab.
  staleTime: 60_000,
});
