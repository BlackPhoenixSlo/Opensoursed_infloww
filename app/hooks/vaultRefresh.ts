/**
 * The vault's refreshes, one home. Every "skip the relay's vault cache" in the app goes through here or through
 * `dropRelayVaultCache` (hooks/useVaultMedia, the leaf module: POST /admin/vault/cache/invalidate, the relay forgets
 * every cached vault/lists and vault/media answer of one Creator, so the next read of each goes to OnlyFans):
 *
 *   • refreshVaultFromOf   Vault Pro's Refresh (↻): POST /admin/vault-ai/sync (drops that cache and, for a collected
 *     Creator, pulls OF's newest into the mirror), then reloads the grid. false when OnlyFans could not be reached
 *     (the relay's 502/504, or no answer at all): the grid still reloaded what the relay has, and the caller says
 *     so. Any other failure (401/403/422, ...) is thrown, after the same reload. `useOfRefresh` is it as both grids'
 *     mutation (pending, note, the thumbs redrawn).
 *   • reloadBrokenThumbs   a grid's broken thumbnails (useThumbAutoRefresh): the mirror's items again (its thumb
 *     route re-signs by id; no OF listing read), or every loaded page of the live listing read through the relay's
 *     age gate (`revalidate=1`, useVaultMedia `revalidateLoadedVaultPages`): a copy older than the gate comes back
 *     freshly signed from OF, a young one (signed minutes ago) is served, and page 1 joins the picker open's own
 *     revalidate instead of costing OF a second read. Put back in place: no flash, no scroll jump.
 *
 * The one-shot `refresh=1` of useVaultLists().refresh stays where it is: it bypasses the cache for that one read
 * only, where the drop above makes every other cached page of the Creator go to OF again too.
 */

import { useIsMutating, useMutation, useQueryClient, type QueryClient } from "@tanstack/react-query";

import { type ThumbRetry } from "@/hooks/useThumbAutoRefresh";
import { invalidateVaultGrid, mirrorItemsKey, type VaultCacheSummary } from "@/hooks/useVaultCache";
import { revalidateLoadedVaultPages } from "@/hooks/useVaultMedia";
import { type FanId } from "@/lib/fanId";
import { relay, RelayError } from "@/lib/relay";

/** The sync never reached OnlyFans: the relay said so (502 / 504), or there was no answer at all. */
export function ofUnreachable(e: unknown): boolean {
  return !(e instanceof RelayError) || e.status === 502 || e.status === 504;
}

/** Vault Pro's Refresh: what OnlyFans holds now (the open folder's media, if one is open), then the grid reloads.
 *  Resolves once the reload settled, so a spinner bound to it stops with the new grid on screen: true when the
 *  sync reached OnlyFans, false when it could not (the grid shows what the relay already had). */
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

/** Where a grid's tiles come from: the local mirror, or OF's live listing (through the relay's cache). */
export type VaultSource = "mirror" | "live";

type SourceSummary = Pick<VaultCacheSummary, "count" | "complete"> | null | undefined;

/** Whole-set rule: the mirror once a whole-vault walk finished (`complete`) and it holds media. For what must be
 *  the whole vault/folder: the picker's grid (what can be sent), the manager's vault/folder downloads, the focus
 *  prefetch that warms the picker. A partial mirror (first pages only) would serve, and download, part of it. A
 *  restricted chatter's summary carries `complete` and its own folders' count (#329), so the rule holds for its
 *  folders; "All" is soft-denied to it on both sources, so the manager keeps its whole-vault download off. */
export function vaultWholeSource(summary: SourceSummary): VaultSource {
  return summary?.complete === true && summary.count > 0 ? "mirror" : "live";
}

/** How long the picker waits for its summary's first answer before listing live anyway (`vaultPickerSource`). */
export const SUMMARY_WAIT_MS = 8000;

/** The picker's grid source while its summary may be in flight: "pending" until the summary's first answer (no
 *  grid query runs; the grid shows loading), then `vaultWholeSource`; a failed summary (a chatter's 403) is "live".
 *  A live listing fired alongside painted OF CDN tiles over a collected vault whenever the summary lost the race
 *  (U4: a slow phone network), and spent an OF listing call the mirror answers. `waitedOut`: the summary has been
 *  pending `SUMMARY_WAIT_MS`; the relay read has no timeout, so a stalled one would hold the grid on Loading for
 *  good. Then "live"; a late answer still switches to the mirror. */
export function vaultPickerSource(summary: { data?: SourceSummary; isLoading: boolean },
                                  waitedOut = false): VaultSource | "pending" {
  return summary.data === undefined && summary.isLoading && !waitedOut ? "pending" : vaultWholeSource(summary.data);
}

/** Browse rule: the mirror once it holds anything. For the manager's grid (and its thumb reload, selection
 *  download): AI-tag search, describe results and custom folder order live only in the mirror, and the collector's
 *  page cap means a big vault may never read `complete`. */
export function vaultBrowseSource(summary: SourceSummary): VaultSource {
  return (summary?.count ?? 0) > 0 ? "mirror" : "live";
}

/** A grid's broken thumbnails: refetch the listing that hands out their urls, never a full OF sync. */
export async function reloadBrokenThumbs(qc: QueryClient, accountId: string, source: VaultSource): Promise<void> {
  if (source === "live") return revalidateLoadedVaultPages(qc, accountId);
  await qc.invalidateQueries({ queryKey: mirrorItemsKey(accountId) });
}

export interface OfRefresh {
  /** Sync the scope's Creator (the open folder's media, if one); a no-op while the scope is null. */
  mutate: (folder: FanId | null) => void;
  isPending: boolean;
  /** Settled: "Refresh failed", or the saved-vault note when OF could not be reached; else null. */
  note: string | null;
}

/** Refresh (↻) as a mutation, for both grids: disabled + spinning while pending, the note once settled. Settled,
 *  the broken thumbs of the Creator it ran for (the mutation's own `accountId`, not the one on screen now) are
 *  drawn again. Pending is per Creator across mounts (`["of-refresh", scope]`): a close/reopen or a Creator
 *  switch back mid-sync still sees it, so no second sync. The note is shown only to the grid that started the
 *  sync while it still shows that Creator: a change of `scope` (the Creator, or null while the grid is closed)
 *  drops it (the observer resets when its mutationKey changes). */
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
