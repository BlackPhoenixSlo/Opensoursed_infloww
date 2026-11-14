"use client";

/**
 * Our own vault folders (`vault_folders`: the `AI-…` script/lane folders, the Feet pack's rungs, the operator's):
 * the list (GET /admin/vault-ai/internal-folders) and the Inflowwww folders editor's writes
 * (`service/vault_internal_folders.py`). Every write changes our DB only, never OnlyFans.
 *
 * `useSellFolders` (Full AI Chat's folder picker) reads the same list under the same key.
 */

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
  /** Set once the folder was published to OnlyFans (its list id there). */
  of_list_id: string | null;
  /** `ai`: generated, Build AI folders rewrites it · `pack`: a Feet pack rung · `own`: the operator's. */
  kind: "ai" | "pack" | "own";
}

/** The key the vault page's folder writes already invalidate (`VaultAiFoldersModal`, `VaultPackPickerModal`). */
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

/** After a write: the list (counts, kinds), the grids, and the two tools that read folder membership (the Feet
 *  pack's triage, the AI folders plan). Resolves once the mounted ones refetched. */
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
    relay.post<{ folder_id: number; name: string }>(BASE, { account_id: accountId, name }),
  rename: (accountId: string, folderId: number, name: string) =>
    relay.post<{ name: string }>(`${BASE}/${folderId}/rename`, { account_id: accountId, name }),
  /** Soft: the folder leaves the list, its media stay in the vault. Its price goes with it. */
  remove: async (qc: QueryClient, accountId: string, folderId: number) => {
    await relay.delete(`${BASE}/${folderId}?account_id=${encodeURIComponent(accountId)}`);
    await qc.invalidateQueries({ queryKey: folderPricesKey(accountId) });
  },
  /** A copy into the folder; with `move_from`, a move out of that one. */
  add: (folderId: number, body: Ids & { move_from?: number }) =>
    relay.post<{ added: number; already: number; moved: number }>(`${BASE}/${folderId}/add`, body),
  take: (folderId: number, body: Ids) => relay.post<{ removed: number }>(`${BASE}/${folderId}/remove`, body),
  /** Put `media_ids` in front of `before` (null: at the end). */
  reorder: (folderId: number, body: Ids & { before: number | null }) =>
    relay.post<{ items: number }>(`${BASE}/${folderId}/reorder`, body),
};
