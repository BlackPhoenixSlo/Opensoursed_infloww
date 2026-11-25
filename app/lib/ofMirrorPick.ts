// Imports nothing, so no ofMirrorData* leaf reaches ofMirrorChat through it.
export function load<T>(storage: Storage, key: string, fresh: T): T {
  try {
    const raw = storage.getItem(key);
    return raw ? { ...fresh, ...(JSON.parse(raw) as Partial<T>) } : fresh;
  } catch {
    return fresh;
  }
}

export interface VaultPick {
  ids: number[];
  thumbs: string[];
}
export const vaultPickKey = (accountId: string, page: string, chat?: string | null) => `oi:vault-pick:${accountId}:${page}:${chat ?? ""}`;
export const loadVaultPick = (storage: Storage, key: string): VaultPick => load<VaultPick>(storage, key, { ids: [], thumbs: [] });

export const MASS_SEND = "/of-manager/messages/send";
