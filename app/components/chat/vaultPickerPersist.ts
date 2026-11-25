import type { FanId } from "@/lib/fanId";
import { isStatsSort } from "./vaultPickerStats";
import type { PickerFanState } from "./vaultPickerFilters";

export const MRU_CAP = 3;

export function fanStateKey(accountId: string | null, fanId: FanId | null): string | null {
  if (!accountId || fanId == null) return null;
  return `chatterly:vault-state:${accountId}:${fanId}`;
}

export function fanMruKey(accountId: string | null, fanId: FanId | null): string | null {
  if (!accountId || fanId == null) return null;
  return `chatterly:vault-mru:${accountId}:${fanId}`;
}

export function accountCountsKey(accountId: string | null): string | null {
  if (!accountId) return null;
  return `chatterly:vault-folder-counts:${accountId}`;
}

export function loadFanState(accountId: string | null, fanId: FanId | null): PickerFanState | null {
  const k = fanStateKey(accountId, fanId);
  if (!k || typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(k);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<PickerFanState>;
    return {
      listId: (typeof parsed.listId === "number" || typeof parsed.listId === "string")
        ? parsed.listId : null,
      sort: parsed.sort === "oldest" || isStatsSort(parsed.sort) ? parsed.sort : "newest",
      type:
        parsed.type === "photo" || parsed.type === "video" || parsed.type === "gif"
          ? parsed.type
          : "all",
    };
  } catch {
    return null;
  }
}

export function saveFanState(accountId: string | null, fanId: FanId | null, state: PickerFanState): void {
  const k = fanStateKey(accountId, fanId);
  if (!k || typeof window === "undefined") return;
  try {
    window.localStorage.setItem(k, JSON.stringify(state));
  } catch { }
}

export function loadFanMru(accountId: string | null, fanId: FanId | null): FanId[] {
  const k = fanMruKey(accountId, fanId);
  if (!k || typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(k);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter((n): n is number => typeof n === "number").slice(0, MRU_CAP);
  } catch { return []; }
}

export function saveFanMru(accountId: string | null, fanId: FanId | null, mru: FanId[]): void {
  const k = fanMruKey(accountId, fanId);
  if (!k || typeof window === "undefined") return;
  try {
    window.localStorage.setItem(k, JSON.stringify(mru.slice(0, MRU_CAP)));
  } catch { }
}

export function nextMru(mru: FanId[], id: FanId, cap = MRU_CAP): FanId[] {
  return [id, ...mru.filter((x) => x !== id)].slice(0, cap);
}

export function loadAccountCounts(accountId: string | null): Record<string, number> {
  const k = accountCountsKey(accountId);
  if (!k || typeof window === "undefined") return {};
  try {
    const raw = window.localStorage.getItem(k);
    if (!raw) return {};
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === "object" ? parsed as Record<string, number> : {};
  } catch { return {}; }
}

export function bumpAccountCount(accountId: string | null, folderId: FanId): void {
  const k = accountCountsKey(accountId);
  if (!k || typeof window === "undefined") return;
  try {
    const cur = loadAccountCounts(accountId);
    cur[String(folderId)] = (cur[String(folderId)] || 0) + 1;
    window.localStorage.setItem(k, JSON.stringify(cur));
  } catch { }
}
