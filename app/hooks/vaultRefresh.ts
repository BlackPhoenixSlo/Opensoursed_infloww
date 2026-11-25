import { useIsMutating, useMutation, useQueryClient, type QueryClient } from "@tanstack/react-query";

import { type ThumbRetry } from "@/hooks/useThumbAutoRefresh";
import { invalidateVaultGrid, mirrorItemsKey, type VaultCacheSummary } from "@/hooks/useVaultCache";
import { revalidateLoadedVaultPages } from "@/hooks/useVaultMedia";
import { type FanId } from "@/lib/fanId";
import { relay, RelayError } from "@/lib/relay";

export function ofUnreachable(e: unknown): boolean {
  return !(e instanceof RelayError) || e.status === 502 || e.status === 504;
}

// Syncs from OF, not just a mirror re-read: stored URLs carry the signature and proxy IP of the Collect that wrote them.
export async function refreshVaultFromOf(
  qc: QueryClient, accountId: string, ofFolderId: FanId | null,
): Promise<boolean> {
  const q = new URLSearchParams({ account_id: accountId });
  if (ofFolderId != null) q.set("of_folder_id", String(ofFolderId));
  try {
    await relay.post(`/admin/vault-ai/sync?${q}`, undefined, { accountId });
    return true;
  } catch (e) {
    if (ofUnreachable(e)) return false;
    throw e;
  } finally {
    await invalidateVaultGrid(qc, accountId);
  }
}

export type VaultSource = "mirror" | "live";

type SourceSummary = Pick<VaultCacheSummary, "count" | "complete"> | null | undefined;

// A partial mirror (first pages only) would serve and download only part of the vault.
export function vaultWholeSource(summary: SourceSummary): VaultSource {
  return summary?.complete === true && summary.count > 0 ? "mirror" : "live";
}

export const SUMMARY_WAIT_MS = 8000;

// A live listing racing the summary painted OF CDN tiles over a collected vault; the relay read has no timeout, hence waitedOut.
export function vaultPickerSource(summary: { data?: SourceSummary; isLoading: boolean },
                                  waitedOut = false): VaultSource | "pending" {
  return summary.data === undefined && summary.isLoading && !waitedOut ? "pending" : vaultWholeSource(summary.data);
}

// Mirror once it holds anything: AI tags, describe results and folder order live only there.
export function vaultBrowseSource(summary: SourceSummary): VaultSource {
  return (summary?.count ?? 0) > 0 ? "mirror" : "live";
}

export async function reloadBrokenThumbs(qc: QueryClient, accountId: string, source: VaultSource): Promise<void> {
  if (source === "live") return revalidateLoadedVaultPages(qc, accountId);
  await qc.invalidateQueries({ queryKey: mirrorItemsKey(accountId) });
}

export interface OfRefresh {
  mutate: (folder: FanId | null) => void;
  isPending: boolean;
  note: string | null;
}

export function useOfRefresh(scope: string | null, thumbs: Pick<ThumbRetry, "refreshed">): OfRefresh {
  const qc = useQueryClient();
  const key = ["of-refresh", scope] as const;
  const m = useMutation({
    mutationKey: key,
    mutationFn: (v: { accountId: string; folder: FanId | null }) => refreshVaultFromOf(qc, v.accountId, v.folder),
    onSettled: (_d, _e, v) => thumbs.refreshed(v.accountId),
  });
  const pending = useIsMutating({ mutationKey: key }) > 0;
  const note = m.isPending ? null
    : m.isError ? "Refresh failed"
    : m.data === false ? "Couldn't reach OnlyFans, showing saved vault" : null;
  const mutate = (folder: FanId | null) => { if (scope) m.mutate({ accountId: scope, folder }); };
  return { mutate, isPending: pending, note };
}
