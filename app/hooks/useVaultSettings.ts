"use client";

/**
 * useVaultSettings — a Creator's three vault switches (GET / PUT /admin/vault-ai/settings):
 * `folder_price_final` (Full AI Chat sells folder-priced media at exactly the saved price) and `standard_folders`
 * (the fixed category list, with its Needs Review folder), both off by default, and `solo_sequences` (Script Fill
 * puts only solo media into Sequences), on by default. Owner scope: a folder-limited chatter's read 403s, so
 * `data` stays undefined.
 */

import { useQuery, type QueryClient } from "@tanstack/react-query";

import { relay } from "@/lib/relay";
import { syncStandardFolders } from "@/hooks/useStandardFolders";

export interface VaultSettings { folder_price_final: boolean; standard_folders: boolean; solo_sequences: boolean }
export const vaultSettingsKey = (accountId: string) => ["vault-settings", accountId] as const;

export function useVaultSettings(accountId: string, enabled = true) {
  return useQuery<VaultSettings>({
    queryKey: vaultSettingsKey(accountId),
    queryFn: () => relay.get<VaultSettings>(
      `/admin/vault-ai/settings?account_id=${encodeURIComponent(accountId)}`, { accountId }),
    enabled,
    staleTime: 60_000,
    retry: false,
  });
}

export async function setVaultSetting(qc: QueryClient, accountId: string, patch: Partial<VaultSettings>): Promise<void> {
  const saved = await relay.put<VaultSettings>(`/admin/vault-ai/settings`, { account_id: accountId, ...patch }, { accountId });
  qc.setQueryData(vaultSettingsKey(accountId), {
    folder_price_final: saved.folder_price_final, standard_folders: saved.standard_folders,
    solo_sequences: saved.solo_sequences,
  });
  // Turning "Standard folders" on creates and fills the categories once; the vault rail only reads them. Not awaited:
  // the switch is saved either way. A mounted rail joins this sort and shows its error; else a failed sort leaves an
  // empty rail that syncs on its next mount.
  if (patch.standard_folders && saved.standard_folders) {
    syncStandardFolders(qc, accountId).catch((e) => console.warn("standard folders sort failed", e));
  }
}
