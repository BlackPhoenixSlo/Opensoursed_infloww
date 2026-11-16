"use client";

import { useEffect } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
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

export function useStandardFolders(accountId: string, enabled: boolean) {
  const qc = useQueryClient();
  const query = useQuery({
    queryKey: standardFoldersKey(accountId), enabled,
    queryFn: () => relay.get<StandardFolders>(
      `/admin/vault-ai/standard-folders?account_id=${encodeURIComponent(accountId)}`, { accountId }),
    staleTime: 30_000, retry: false,
  });
  const sync = useMutation({
    mutationFn: (id: string) => relay.post<StandardFolders>(
      "/admin/vault-ai/standard-folders/sync", { account_id: id }, { accountId: id }),
    onSuccess: async (data, id) => {
      await qc.cancelQueries({ queryKey: standardFoldersKey(id) });
      qc.setQueryData(standardFoldersKey(id), data);
      await qc.invalidateQueries({ queryKey: mirrorItemsKey(id) });
    },
  });
  const { mutate } = sync;
  useEffect(() => { if (enabled) mutate(accountId); }, [accountId, enabled, mutate]);
  return { ...query, syncing: sync.isPending, syncError: sync.isError,
    refresh: () => mutate(accountId) };
}
