"use client";

/**
 * useCreatorTabs — the Creator tabs store (docs/spec/phase-01-window-chrome-tabs.md,
 * Interfaces). It joins the store's ids to the session-bearing Creators, so
 * callers get Creators, not ids:
 * - `open`: the open tabs' Creators in strip order.
 * - `closed`: the closed tabs' Creators, in the same order.
 * - `ready`: the accounts read has settled (answered or failed) and the
 *   Employee key has resolved, so an empty `open` and `closed` means the
 *   relay has no Creators rather than "still loading". Read from the query's
 *   status, not its data: a chatter session's `data` is defined even while
 *   its read is pending.
 * - `close(id)` / `reopen(id)`.
 * - `reorder(ids)`: `ids` are the open tabs' ids in their new order. They
 *   take the open tabs' slots in the full stored order, so a closed tab (and
 *   a saved Creator that has left the relay) keeps its slot. A reorder is a
 *   custom order, so it also sets `sort` back to "custom".
 * - `sort` / `setSort(sort)`: how the strip orders the open tabs (MP2's chat
 *   sorting, 04-messages-pro P9): "custom" (the saved order, the default),
 *   "unread" (most unread first), "az" or "za" (by name). The strip applies
 *   it (`sortTabs`), since "unread" reads the roster counts.
 *
 * Strip order is the saved order filtered to live Creators, then every live
 * Creator the saved order lacks, in the relay's account order (the Clone's
 * `tabOrder`, messages.js:242-255). With nothing saved that is the relay's
 * order, with no reshuffling by activity. A closed tab keeps its place, so a
 * reopened tab returns to it.
 *
 * The order and the closed ids are remembered per Employee under the spec's
 * Creator tabs key (Contracts), `{ order, closed }`, and re-read on this
 * window's change event and on `storage` from another window. Until the
 * Employee key resolves (`useEmployeeKey`) the store is still loading: no
 * tabs, and nothing read or written. A stored value that is not JSON, or not that shape, reads as the
 * default and is overwritten on the next change. Call it once and hand the
 * result down, so the strip and the picker share it.
 */

import { useCallback, useMemo, useSyncExternalStore } from "react";

import { useAccounts, usePlatformAccounts } from "@/hooks/useAccounts";
import { useEmployeeKey } from "@/hooks/useEmployeeKey";
import type { AccountMeta } from "@/lib/relay";
import { readStorage, subscribeToStorage } from "@/lib/storageSync";

export type CreatorTabsStore = {
  open: AccountMeta[];
  closed: AccountMeta[];
  ready: boolean;
  close: (id: string) => void;
  reopen: (id: string) => void;
  reorder: (ids: string[]) => void;
  sort: CreatorSort;
  setSort: (sort: CreatorSort) => void;
};

export type CreatorSort = "custom" | "unread" | "az" | "za";

const SORTS: readonly CreatorSort[] = ["custom", "unread", "az", "za"];

/** `open` in `sort`'s order; ties (and "custom") keep the store's order. */
export function sortTabs(open: AccountMeta[], sort: CreatorSort, unreadOf: (id: string) => number): AccountMeta[] {
  if (sort === "custom") return open;
  const name = (a: AccountMeta) => a.nickname || a.id;
  const out = open.slice();
  if (sort === "unread") out.sort((a, b) => unreadOf(b.id) - unreadOf(a.id));
  else out.sort((a, b) => (sort === "az" ? 1 : -1) * name(a).localeCompare(name(b), undefined, { sensitivity: "base" }));
  return out;
}

/** The stored value (Contracts). An empty `order` means the relay's order;
 *  no `sort` means "custom". */
type SavedTabs = { order: string[]; closed: string[]; sort?: CreatorSort };

const KEY_PREFIX = "chatterly:creator-tabs:v1:";
const EVENT = "chatterly-creator-tabs-change";
const DEFAULT_TABS: SavedTabs = { order: [], closed: [] };
const subscribe = subscribeToStorage(EVENT);

function isIdList(v: unknown): v is string[] {
  return Array.isArray(v) && v.every((id) => typeof id === "string");
}

function isSavedTabs(v: unknown): v is SavedTabs {
  if (typeof v !== "object" || v === null) return false;
  const { order, closed, sort } = v as Record<string, unknown>;
  return isIdList(order) && isIdList(closed) && (sort === undefined || SORTS.includes(sort as CreatorSort));
}

/** The malformed rule: a value that is not JSON, or not `SavedTabs`, reads
 *  as the default. */
function parseSavedTabs(raw: string | null): SavedTabs {
  if (raw === null) return DEFAULT_TABS;
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return DEFAULT_TABS;
  }
  return isSavedTabs(parsed) ? parsed : DEFAULT_TABS;
}

/** `creators` in the saved order: saved ids filtered to live Creators, then
 *  the live Creators the saved order lacks, in the relay's order. */
function inSavedOrder(creators: AccountMeta[], order: string[]): AccountMeta[] {
  const live = new Map(creators.map((a) => [a.id, a]));
  const placed = new Set<string>();
  const out: AccountMeta[] = [];
  for (const id of [...order, ...creators.map((a) => a.id)]) {
    const account = live.get(id);
    if (account === undefined || placed.has(id)) continue;
    placed.add(id);
    out.push(account);
  }
  return out;
}

export function useCreatorTabs(): CreatorTabsStore {
  const accountsSettled = !useAccounts().isPending;
  const creators = usePlatformAccounts();
  const employeeKey = useEmployeeKey();
  const storageKey = employeeKey === null ? null : `${KEY_PREFIX}${employeeKey}`;

  const ready = accountsSettled && storageKey !== null;

  const raw = useSyncExternalStore(subscribe, () => readStorage(storageKey), () => null);
  const saved = useMemo(() => parseSavedTabs(raw), [raw]);

  const update = useCallback((change: (prev: SavedTabs) => SavedTabs) => {
    // Unreachable: while the key is null the store hands out no tabs, so
    // nothing renders a ✕ or a picker row to click. The guard only narrows
    // `storageKey` for setItem; the invariant is stated here, not asserted away.
    if (storageKey === null) return;
    const next = change(parseSavedTabs(readStorage(storageKey)));
    window.localStorage.setItem(storageKey, JSON.stringify(next));
    window.dispatchEvent(new Event(EVENT));
  }, [storageKey]);

  const close = useCallback((id: string) => {
    update((prev) => ({ ...prev, closed: [...prev.closed.filter((c) => c !== id), id] }));
  }, [update]);
  const reopen = useCallback((id: string) => {
    update((prev) => ({ ...prev, closed: prev.closed.filter((c) => c !== id) }));
  }, [update]);

  const reorder = useCallback((ids: string[]) => {
    const moved = new Set(ids);
    update((prev) => {
      // The full order: the saved ids, then the live Creators it lacks.
      const full = [...new Set([...prev.order, ...creators.map((a) => a.id)])];
      let next = 0;
      // No `sort`: a hand-made order is the custom one.
      return { order: full.map((id) => (moved.has(id) ? ids[next++] : id)), closed: prev.closed };
    });
  }, [update, creators]);

  const setSort = useCallback((sort: CreatorSort) => {
    update(({ order, closed }) => (sort === "custom" ? { order, closed } : { order, closed, sort }));
  }, [update]);

  const { open, closed } = useMemo(() => {
    if (storageKey === null) return { open: [], closed: [] };
    const ordered = inSavedOrder(creators, saved.order);
    const closedIds = new Set(saved.closed);
    return {
      open: ordered.filter((a) => !closedIds.has(a.id)),
      closed: ordered.filter((a) => closedIds.has(a.id)),
    };
  }, [storageKey, creators, saved]);
  return { open, closed, ready, close, reopen, reorder, sort: saved.sort ?? "custom", setSort };
}
