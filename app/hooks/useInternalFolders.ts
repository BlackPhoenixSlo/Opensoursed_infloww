"use client";


import { type QueryClient, queryOptions, useQuery } from "@tanstack/react-query";

import { folderPricesKey } from "@/hooks/useFolderPrices";
import { mirrorItemsKey } from "@/hooks/useVaultCache";
import { relay } from "@/lib/relay";

export interface InternalFolder {
  id: number;
  name: string;
  items: number;
  photos: number;
  videos: number;
  of_list_id: string | null;
  /** `ai`: generated, Build AI folders rewrites it · `pack`: a Feet pack rung · `own`: the operator's. */
  kind: "ai" | "pack" | "own";
}

export const internalFoldersKey = (accountId: string) => ["vault-internal-folders", accountId] as const;

const BASE = "/admin/vault-ai/internal-folders";

export const internalFoldersQuery = (accountId: string) =>
  queryOptions({
    queryKey: internalFoldersKey(accountId),
    queryFn: () => relay.get<{ list: InternalFolder[] }>(`${BASE}?account_id=${encodeURIComponent(accountId)}`, { accountId }),
    staleTime: 60_000,
  });

export function useInternalFolders(accountId: string) {
  return useQuery(internalFoldersQuery(accountId));
}

export function invalidateInternalFolders(qc: QueryClient, accountId: string): Promise<unknown> {
  return Promise.all([
    qc.invalidateQueries({ queryKey: internalFoldersKey(accountId) }),
    qc.invalidateQueries({ queryKey: mirrorItemsKey(accountId) }),
    qc.invalidateQueries({ queryKey: ["vault-pack-candidates", accountId] }),
    qc.invalidateQueries({ queryKey: ["vault-ai-folder-plan", accountId] }),
  ]);
}

interface Ids { account_id: string; media_ids: number[] }

export const internalFolders = {
  create: (accountId: string, name: string) =>
    relay.post<{ folder_id: number; name: string }>(BASE, { account_id: accountId, name }, { cellAccountId: accountId }),
  rename: (accountId: string, folderId: number, name: string) =>
    relay.post<{ name: string }>(`${BASE}/${folderId}/rename`, { account_id: accountId, name }, { cellAccountId: accountId }),
  remove: async (qc: QueryClient, accountId: string, folderId: number) => {
    await relay.delete(`${BASE}/${folderId}?account_id=${encodeURIComponent(accountId)}`);
    await qc.invalidateQueries({ queryKey: folderPricesKey(accountId) });
  },
  add: (folderId: number, body: Ids & { move_from?: number }) =>
    relay.post<{ added: number; already: number; moved: number }>(`${BASE}/${folderId}/add`, body, { cellAccountId: body.account_id }),
  take: (folderId: number, body: Ids) => relay.post<{ removed: number }>(`${BASE}/${folderId}/remove`, body, { cellAccountId: body.account_id }),
  reorder: (folderId: number, body: Ids & { before: number | null }) =>
    relay.post<{ items: number }>(`${BASE}/${folderId}/reorder`, body, { cellAccountId: body.account_id }),
};
