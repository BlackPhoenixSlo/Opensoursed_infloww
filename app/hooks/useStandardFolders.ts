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

const inflight = new Map<string, Promise<StandardFolders>>();

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
  const { mutate, isIdle } = sync;
  const empty = query.data?.list.length === 0;
  useEffect(() => {
    if (enabled && isIdle && (empty || inflight.has(accountId))) mutate(accountId);
  }, [enabled, empty, isIdle, accountId, mutate]);
  return { ...query, syncing: sync.isPending, syncError: sync.isError,
    refresh: () => mutate(accountId) };
}
