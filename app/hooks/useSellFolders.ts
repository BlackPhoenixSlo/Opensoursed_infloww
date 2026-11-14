"use client";

/**
 * useSellFolders — what Full AI Chat's Content folders picker lists (ticket 49): the Creator's internal vault folders
 * (GET /admin/vault-ai/internal-folders, `vf:<id>`) and OF lists from the mirror (`useOfFoldersMirror`, `of:<id>`).
 * The folder dialog mounts only while open, so that is the gate.
 */

import { useQuery } from "@tanstack/react-query";

import { useOfFoldersMirror } from "@/hooks/useVaultCache";
import { relay } from "@/lib/relay";

export interface InternalFolder { id: number; name: string; items: number }
export interface SellFolder { ref: string; name: string; count: number }

/** The key the vault page's folder writes already invalidate (`VaultAiFoldersModal`, `VaultPackPickerModal`). */
export const internalFoldersKey = (accountId: string) => ["vault-internal-folders", accountId] as const;

export function useSellFolders(accountId: string) {
  const internalQ = useQuery<{ list: InternalFolder[] }>({
    queryKey: internalFoldersKey(accountId),
    queryFn: () => relay.get(`/admin/vault-ai/internal-folders?account_id=${encodeURIComponent(accountId)}`, { accountId }),
    staleTime: 60_000,
  });
  const ofQ = useOfFoldersMirror(accountId, true);
  const vault: SellFolder[] = (internalQ.data?.list ?? []).map((f) => ({ ref: `vf:${f.id}`, name: f.name, count: f.items }));
  const of: SellFolder[] = (ofQ.data?.list ?? []).map((f) => ({ ref: `of:${f.id}`, name: f.name, count: f.mediaCount ?? 0 }));
  return {
    vault, of,
    loading: internalQ.isPending || ofQ.isPending,
    error: internalQ.isError || ofQ.isError,
  };
}
