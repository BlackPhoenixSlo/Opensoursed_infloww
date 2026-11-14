"use client";

/**
 * useFolderPrices — an agency's price per vault folder (GET /admin/vault-ai/folder-prices): `{ref: cents}`, refs
 * `vf:<id>` / `of:<id>`. Full AI Chat's sell executor lists a priced folder's items at it. `setFolderPrice` writes
 * one (null clears) and refreshes the map. Owner scope: a folder-limited chatter's read 403s, so `data` stays
 * undefined and the rail offers no "Set price".
 */

import { useQuery, type QueryClient } from "@tanstack/react-query";

import { relay } from "@/lib/relay";

export const folderPricesKey = (accountId: string) => ["vault-folder-prices", accountId] as const;

export function useFolderPrices(accountId: string) {
  return useQuery<Record<string, number>>({
    queryKey: folderPricesKey(accountId),
    queryFn: async () => {
      const r = await relay.get<{ list: { ref: string; price_cents: number }[] }>(
        `/admin/vault-ai/folder-prices?account_id=${encodeURIComponent(accountId)}`, { accountId });
      return Object.fromEntries((r.list ?? []).map((p) => [p.ref, p.price_cents]));
    },
    staleTime: 60_000,
    retry: false,
  });
}

export async function setFolderPrice(
  qc: QueryClient, body: { account_id: string; ref: string; price_cents: number | null },
): Promise<void> {
  await relay.post(`/admin/vault-ai/folder-prices`, body, { accountId: body.account_id });
  await qc.invalidateQueries({ queryKey: folderPricesKey(body.account_id) });
}
