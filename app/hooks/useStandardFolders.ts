"use client";

import { useEffect } from "react";
import { useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { relay } from "@/lib/relay";
import { mirrorItemsKey } from "@/hooks/useVaultCache";

export interface StandardFolder {
  id: number;
  kind: "photo" | "video";
  slug: string;
  name: string;
  items: number;
  priceable: boolean;
}
export interface StandardFolders { list: StandardFolder[]; pending: number }
export const standardFoldersKey = (id: string) => ["vault-standard-folders", id] as const;

// The sort in flight per Creator: a second caller (the rail mounting during the switch's turn-on sort) joins it.
const inflight = new Map<string, Promise<StandardFolders>>();

/** POST sync: creates the categories and places saved analysis (O(vault) write batches), then seeds the list. Only on
 *  the switch's turn-on (`setVaultSetting`), an empty list, and the rail's Retry; never on every mount. One POST per
 *  Creator at a time: a call while one runs gets that one's result. */
export function syncStandardFolders(qc: QueryClient, accountId: string): Promise<StandardFolders> {
  const running = inflight.get(accountId);
  if (running) return running;
  const run = (async () => {
    const data = await relay.post<StandardFolders>(
      "/admin/vault-ai/standard-folders/sync", { account_id: accountId }, { accountId });
    await qc.cancelQueries({ queryKey: standardFoldersKey(accountId) });
    qc.setQueryData(standardFoldersKey(accountId), data);
    await qc.invalidateQueries({ queryKey: mirrorItemsKey(accountId) });
    return data;
  })().finally(() => inflight.delete(accountId));
  inflight.set(accountId, run);
  return run;
}

export function useStandardFolders(accountId: string, enabled: boolean) {
  const qc = useQueryClient();
  const query = useQuery({
    queryKey: standardFoldersKey(accountId), enabled,
    queryFn: () => relay.get<StandardFolders>(
      `/admin/vault-ai/standard-folders?account_id=${encodeURIComponent(accountId)}`, { accountId }),
    staleTime: 30_000, retry: false,
  });
  const sync = useMutation({ mutationFn: (id: string) => syncStandardFolders(qc, id) });
  // Mount only GETs. Join the switch's turn-on sort while it runs, else sync once when the switch is on but no
  // category exists yet (its turn-on sync failed): the rail shows "Sorting…" / the error with Retry, not an empty list.
  const { mutate, isIdle } = sync;
  const empty = query.data?.list.length === 0;
  useEffect(() => {
    if (enabled && isIdle && (empty || inflight.has(accountId))) mutate(accountId);
  }, [enabled, empty, isIdle, accountId, mutate]);
  return { ...query, syncing: sync.isPending, syncError: sync.isError,
    refresh: () => mutate(accountId) };
}
