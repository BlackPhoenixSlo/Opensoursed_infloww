/**
 * The vault's refreshes, one home. Every "skip the relay's vault cache" in the app goes through here or through
 * `dropRelayVaultCache` (hooks/useVaultMedia, the leaf module: POST /admin/vault/cache/invalidate, the relay forgets
 * every cached vault/lists and vault/media answer of one Creator, so the next read of each goes to OnlyFans):
 *
 *   • refreshVaultFromOf   Vault Pro's Refresh (↻): POST /admin/vault-ai/sync (drops that cache and, for a collected
 *     Creator, pulls OF's newest into the mirror), then reloads the grid. false when OnlyFans could not be reached
 *     (the relay's 502/504, or no answer at all): the grid still reloaded what the relay has, and the caller says
 *     so. Any other failure (401/403/422, ...) is thrown, after the same reload.
 *   • reloadBrokenThumbs   a grid's broken thumbnails (useThumbAutoRefresh): the mirror's items again (its thumb
 *     route re-signs by id; no OF listing read), or the live listing with the relay's cache dropped first so every
 *     loaded page comes back freshly signed. Refetched in place: no flash, no scroll jump.
 *
 * The one-shot `refresh=1` of useVaultLists().refresh stays where it is: it bypasses the cache for that one read
 * only, where the drop above makes every other cached page of the Creator go to OF again too.
 */

import { type QueryClient } from "@tanstack/react-query";

import { invalidateVaultGrid, mirrorItemsKey } from "@/hooks/useVaultCache";
import { dropRelayVaultCache, vaultMediaKey } from "@/hooks/useVaultMedia";
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
export type ThumbSource = "mirror" | "live";

/** A grid's broken thumbnails: refetch the listing that hands out their urls, never a full OF sync. */
export async function reloadBrokenThumbs(qc: QueryClient, accountId: string, source: ThumbSource): Promise<void> {
  if (source === "live") await dropRelayVaultCache(accountId);
  await qc.invalidateQueries({ queryKey: source === "mirror" ? mirrorItemsKey(accountId) : vaultMediaKey(accountId) });
}
