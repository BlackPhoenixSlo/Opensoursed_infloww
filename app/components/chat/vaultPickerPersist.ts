/**
 * VaultPicker's localStorage: the per-fan picker state, the per-fan folder
 * MRU and the account-wide folder usage counters. Loaders tolerate corrupt
 * or foreign JSON; writers swallow quota / private-mode errors.
 */

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

/** Full picker state for one fan — folder, sort order, media type. We
 *  persist all three so reopening the picker is byte-identical to where
 *  the chatter left it (no forced "pop to last folder" surprises). */
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
    // EVICT-BY: created-at — see plan/17_cache_strategy.md §7
    window.localStorage.setItem(k, JSON.stringify(state));
  } catch { /* quota / private mode — ignore */ }
}

/** Per-fan folder MRU. Drives the quick-chip row when this specific fan
 *  has history. Most-recent first, capped at MRU_CAP. */
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
  } catch { /* ignore */ }
}

/** `id` moved (or added) to the head of the MRU, deduped, capped. */
export function nextMru(mru: FanId[], id: FanId, cap = MRU_CAP): FanId[] {
  return [id, ...mru.filter((x) => x !== id)].slice(0, cap);
}

/** Account-wide folder usage counters — sum of picks across every fan.
 *  Used as the fallback ranking when the current fan has no per-fan
 *  history yet, so the chip row still shows folders the chatter
 *  actually uses (not just the first three OF returns). */
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
  } catch { /* ignore */ }
}
