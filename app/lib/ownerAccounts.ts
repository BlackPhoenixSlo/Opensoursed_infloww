import { relay, type AccountMeta, type WatcherAccount } from "@/lib/relay";

export interface AccountsResp {
  accounts: AccountMeta[];
  active_account_id: string | null;
  watchers?: WatcherAccount[];
}

export async function fetchAccounts(): Promise<AccountsResp> {
  const r = await relay.get<AccountsResp>("/admin/accounts");
  return {
    ...r,
    accounts: (r.accounts ?? []).map((a) => ({ ...a, is_active: a.is_active ?? true })),
    watchers: (r.watchers ?? []).map((w) => ({ ...w, is_active: w.is_active ?? true, proxy_down: !!w.proxy_down, role: "watcher" })),
  };
}

export const ownerAccountsQuery = (userId: string | undefined) => ({
  // Keyed by principal: unauthenticated /admin/accounts returns the full multi-tenant registry and would bleed into the next owner's session.
  queryKey: ["accounts", userId ?? "anon"],
  queryFn: fetchAccounts,
  // A short staleTime is cheap because this read stays on the relay.
  staleTime: 60_000,
});
