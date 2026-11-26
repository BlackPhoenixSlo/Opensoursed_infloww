import { cellMode } from "@/lib/cellFlag";
import { relay, type AccountMeta, type WatcherAccount } from "@/lib/relay";
import { askCells, loadCellMap } from "@/lib/cellMap";
import { ROSTER_WAIT_MS } from "@/lib/cellInbox";

export interface AccountsResp {
  accounts: AccountMeta[];
  active_account_id: string | null;
  watchers?: WatcherAccount[];
}

async function cellsRoster(): Promise<AccountsResp> {
  const m = await loadCellMap();
  const answered = new Map<string, AccountsResp>();
  const all = askCells<AccountsResp>(m, m.accounts.map((a) => a.account_id), undefined, async ({ cell, signal }) => {
    const value = await relay.get<AccountsResp>("/admin/accounts", { cellId: cell }, signal);
    answered.set(cell, value);
    return { value, partial: [] };
  });
  await Promise.race([all, new Promise((r) => setTimeout(r, ROSTER_WAIT_MS))]);
  const byId = new Map<string, AccountMeta>();
  const watchers = new Map<string, WatcherAccount>();
  let active: string | null = null;
  for (const r of m.cells.map((c) => answered.get(c))) {
    for (const a of r?.accounts ?? []) if (!byId.has(a.id)) byId.set(a.id, a);
    for (const w of r?.watchers ?? []) if (!watchers.has(w.id)) watchers.set(w.id, w);
    active ??= r?.active_account_id ?? null;
  }
  for (const a of m.accounts) if (!byId.has(a.account_id) && m.cells.includes(a.cell)) {
    byId.set(a.account_id, { id: a.account_id, platform: a.platform, has_session: true, is_active: true, proxy_down: false });
  }
  return { accounts: [...byId.values()], watchers: [...watchers.values()], active_account_id: active };
}

export async function fetchAccounts(): Promise<AccountsResp> {
  const r = cellMode() ? await cellsRoster() : await relay.get<AccountsResp>("/admin/accounts");
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
