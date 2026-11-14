"use client";

/**
 * useSellFolders — what Full AI Chat's Content folders picker lists (ticket 49): the Creator's internal vault folders
 * (GET /admin/vault-ai/internal-folders, `vf:<id>`) and OF lists from the mirror (`useOfFoldersMirror`, `of:<id>`).
 * The folder dialog mounts only while open, so that is the gate.
 */

import { useQuery } from "@tanstack/react-query";

import { internalFoldersQuery } from "@/hooks/useInternalFolders";
import { useOfFoldersMirror } from "@/hooks/useVaultCache";

export interface SellFolder { ref: string; name: string; count: number }

export function useSellFolders(accountId: string) {
  const internalQ = useQuery(internalFoldersQuery(accountId));
  const ofQ = useOfFoldersMirror(accountId, true);
  const vault: SellFolder[] = (internalQ.data?.list ?? []).map((f) => ({ ref: `vf:${f.id}`, name: f.name, count: f.items }));
  const of: SellFolder[] = (ofQ.data?.list ?? []).map((f) => ({ ref: `of:${f.id}`, name: f.name, count: f.mediaCount ?? 0 }));
  return {
    vault, of,
    loading: internalQ.isPending || ofQ.isPending,
    error: internalQ.isError || ofQ.isError,
  };
}
