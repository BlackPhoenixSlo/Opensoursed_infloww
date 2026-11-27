import type { QueryFunctionContext } from "@tanstack/react-query";

import { cellMode } from "@/lib/cellFlag";
import { relay, type AccountMeta, type WatcherAccount } from "@/lib/relay";
import { askCells, cellScopeToken, loadCellMap, type CellResult } from "@/lib/cellMap";
import { cellToken, ROSTER_WAIT_MS } from "@/lib/cellInbox";

type RosterAccount = AccountMeta & { rosterPending?: true };

export interface AccountsResp {
  accounts: RosterAccount[];
  active_account_id: string | null;
  watchers?: WatcherAccount[];
}

type CellRoster = AccountsResp & { cellRoster: { scope: string; answers: Record<string, AccountsResp> } };

async function cellsRoster(ctx?: QueryFunctionContext): Promise<AccountsResp> {
  const m = await loadCellMap();
  const scope = cellToken(m);
  const state = ctx?.client.getQueryState<CellRoster>(ctx.queryKey);
  const cached = state?.data?.cellRoster;
  const nextUpdate = (state?.dataUpdateCount ?? 0) + 1;
  const prior = cached?.scope === scope ? cached.answers : {};
  const results = await askCells(m, m.accounts.map((a) => a.account_id), undefined, async ({ cell, signal }) => ({
    value: await relay.get<AccountsResp>("/admin/accounts", { cellId: cell }, signal),
    partial: [],
  }), {
    source: "roster", greyAfterMs: ROSTER_WAIT_MS,
    onLate: (late) => {
      if (!ctx || cellScopeToken() !== scope) return;
      const latest = ctx.client.getQueryState(ctx.queryKey);
      if (latest?.fetchStatus === "idle" && latest.dataUpdateCount === nextUpdate) {
        ctx.client.setQueryData(ctx.queryKey, normalize(merge(late)));
      }
    },
  });
  return merge(results);

  function merge(results: CellResult<AccountsResp>[]): CellRoster {
    const answers = { ...prior };
    for (const r of results) if (r.ok) answers[r.cell] = r.value;
    const granted = new Set(m.accounts.map((a) => a.account_id));
    const byId = new Map<string, RosterAccount>();
    const watchers = new Map<string, WatcherAccount>();
    let active: string | null = null;
    for (const cell of new Set([...m.cells, ...m.accounts.map((a) => a.cell)])) {
      const r = answers[cell];
      for (const a of r?.accounts ?? []) if (granted.has(a.id) && !byId.has(a.id)) byId.set(a.id, a);
      for (const w of r?.watchers ?? []) if (!watchers.has(w.id)) watchers.set(w.id, w);
      active ??= r?.active_account_id ?? null;
    }
    for (const a of m.accounts) if (!byId.has(a.account_id)) {
      byId.set(a.account_id, { id: a.account_id, platform: a.platform, is_active: true, proxy_down: true,
        ...(!answers[a.cell] ? { rosterPending: true } : {}),
      });
    }
    return { accounts: [...byId.values()], watchers: [...watchers.values()], active_account_id: active, cellRoster: { scope, answers } };
  }
}

export async function fetchAccounts(ctx?: QueryFunctionContext): Promise<AccountsResp> {
  return normalize(cellMode() ? await cellsRoster(ctx) : await relay.get<AccountsResp>("/admin/accounts"));
}

function normalize(r: AccountsResp): AccountsResp {
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
