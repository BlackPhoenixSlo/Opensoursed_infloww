/**
 * What the composers share with ofMirrorData's modules without those importing a composer: a vault dialog's pick
 * (ofMirrorData reads it), behind the sessionStorage loader (load, the composers read it too), and New message's route
 * (MASS_SEND, ofMirrorDataLists links to it). Cut from ofMirrorChatShared (which re-exports the loaders) and ofMirrorMass.
 * Imports nothing, so no ofMirrorData* leaf reaches ofMirrorChat through it.
 */

export function load<T>(storage: Storage, key: string, fresh: T): T {
  try {
    const raw = storage.getItem(key);
    return raw ? { ...fresh, ...(JSON.parse(raw) as Partial<T>) } : fresh;
  } catch {
    return fresh;
  }
}

/**
 * A composer's vault dialog's ticked tiles (OF's "N / 40 Selected"), kept over its tabs and folders (each its own page)
 * and attached only by its Add; Close, the backdrop or any other way back to the composer drops them (bindChat, bindMass).
 */
export interface VaultPick {
  ids: number[];
  thumbs: string[];
}
export const vaultPickKey = (accountId: string, page: string, chat?: string | null) => `oi:vault-pick:${accountId}:${page}:${chat ?? ""}`;
export const loadVaultPick = (storage: Storage, key: string): VaultPick => load<VaultPick>(storage, key, { ids: [], thumbs: [] });

/** New message's page, `?to=<list>` from a list page's Send message (OF's sendlist-<list>): opens with that list ticked. */
export const MASS_SEND = "/of-manager/messages/send";
