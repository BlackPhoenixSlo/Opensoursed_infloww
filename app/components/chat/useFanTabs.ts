"use client";

/**
 * useFanTabs — the Fan tabs store (docs/spec/phase-01-window-chrome-tabs.md,
 * Interfaces), shared by "Open in new tab" in the Chat header and the Fan
 * tabs strip:
 * - `stored`: every remembered Fan tab in open order. A tab is its Creator,
 *   the Fan id as a `FanId` (number on OnlyFans, the string snowflake on
 *   Fansly, which exceeds 2^53; never re-narrowed) and the Fan's name.
 * - `tabs`: the tabs the strip shows. The hidden rule, stated here once: once
 *   the Creators have loaded, a tab whose Creator is not among the loaded
 *   session-bearing Creators of the sidebar platform (`usePlatformAccounts`) is left out of `tabs`. It
 *   stays in `stored`, counts toward the cap, and is back in `tabs` when its
 *   Creator returns. Until the Creators have loaded, `tabs` is `stored`.
 *   Closing a Creator tab touches neither.
 * - `full`: `stored` holds `FAN_TABS_MAX` tabs, hidden ones included.
 * - `employeeKey`: whose tabs these are (`useEmployeeKey`), or null while the
 *   Employee is unresolved, when `tabs` is empty and nothing may be written:
 *   "Open in new tab" is disabled, and `open` or `close` called then throws,
 *   so every caller gates on it.
 * - `open(tab)`: adds the tab at the end (messages.js:2565-2572) and returns
 *   "opened", or adds nothing for a Fan who already has a tab and returns
 *   "exists", or, at the cap, adds nothing, evicts nothing and returns
 *   "full".
 * - `close(key)`: drops the tab with that key (`fanTabKey`); the others keep
 *   their order (messages.js:2574-2576). What opens next is the strip's
 *   business (`FanTabs`' `onClosed`).
 *
 * The tabs are remembered per Employee under the spec's Fan tabs key
 * (Contracts): an array of `{ accountId, fanId, name }` in open order, the
 * Fan id as text in its wire spelling. They are read through
 * `useSyncExternalStore` and re-read on this window's change event and on
 * `storage` from another window, so every window shows one tab set. The
 * malformed rule (ticket 68's): a value that is not JSON, or not an array of
 * that shape, reads as no tabs; an entry whose Fan id the Deep link's parser
 * (`fanIdFromParam`) rejects is dropped. Either way the next change
 * overwrites the stored value, so a tab this hook returns always carries a
 * usable id.
 */

import { useCallback, useLayoutEffect, useMemo, useRef, useSyncExternalStore } from "react";

import { useAccounts, usePlatformAccounts } from "@/hooks/useAccounts";
import { useEmployeeKey } from "@/hooks/useEmployeeKey";
import { fanIdFromParam, type FanId } from "@/lib/fanId";
import { readStorage, subscribeToStorage } from "@/lib/storageSync";

export type FanTab = { accountId: string; fanId: FanId; name: string };

/** The most Fan tabs an Employee keeps (the spec's Interfaces). */
export const FAN_TABS_MAX = 100;

/** What the Employee is told at the cap: "Open in new tab"'s tooltip and the
 *  notification panel's notice (story 49). */
export const FAN_TABS_FULL_LABEL = `Fan tab limit reached (${FAN_TABS_MAX})`;

/** The key a Fan tab is known by, and the strip's `activeKey`: its Creator
 *  and the Fan id as text, never re-parsed (the Clone's `tabKey`). */
export function fanTabKey(accountId: string, fanId: FanId): string {
  return `${accountId}:${String(fanId)}`;
}

/** A stored entry (Contracts): the Fan id as text. */
type StoredTab = { accountId: string; fanId: string; name: string };

const KEY_PREFIX = "chatterly:fan-tabs:v1:";
const EVENT = "chatterly-fan-tabs-change";
const NO_TABS: FanTab[] = [];
const subscribe = subscribeToStorage(EVENT);

function isStoredTab(v: unknown): v is StoredTab {
  if (typeof v !== "object" || v === null) return false;
  const { accountId, fanId, name } = v as Record<string, unknown>;
  return typeof accountId === "string" && typeof fanId === "string" && typeof name === "string";
}

/** The malformed rule: not JSON, or not an array of `StoredTab`, reads as no
 *  tabs; an entry whose Fan id `fanIdFromParam` rejects is dropped. */
function parseTabs(raw: string | null): FanTab[] {
  if (raw === null) return NO_TABS;
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return NO_TABS;
  }
  if (!Array.isArray(parsed) || !parsed.every(isStoredTab)) return NO_TABS;
  const tabs: FanTab[] = [];
  for (const t of parsed) {
    const fanId = fanIdFromParam(t.fanId);
    if (fanId !== null) tabs.push({ accountId: t.accountId, fanId, name: t.name });
  }
  return tabs;
}

export function useFanTabs(): {
  tabs: FanTab[];
  stored: FanTab[];
  full: boolean;
  employeeKey: string | null;
  open: (tab: FanTab) => "opened" | "exists" | "full";
  close: (key: string) => void;
} {
  const employeeKey = useEmployeeKey();
  const storageKey = employeeKey === null ? null : `${KEY_PREFIX}${employeeKey}`;
  const raw = useSyncExternalStore(subscribe, () => readStorage(storageKey), () => null);
  const stored = useMemo(() => parseTabs(raw), [raw]);

  // "Loaded" is a list the accounts read has answered with: a read that is
  // still pending, or failed before answering, hides nothing. A failed
  // refetch keeps the list it last answered with. Read from the query's
  // flags, not its data: a chatter session's `data` is defined while pending.
  const accounts = useAccounts();
  const creatorsLoaded = accounts.isSuccess || accounts.isRefetchError;
  const creators = usePlatformAccounts();
  const tabs = useMemo(() => {
    if (!creatorsLoaded) return stored;
    const live = new Set(creators.map((a) => a.id));
    return stored.filter((t) => live.has(t.accountId));
  }, [creatorsLoaded, creators, stored]);

  /** The one write path: `change` gets the stored tabs and returns the next
   *  ones, or why it changes nothing, which `update` hands back (null after
   *  a write). Reached only once the Employee resolves:
   *  "Open in new tab" is disabled and the strip has no ✕ while the key is
   *  null, and any other caller must gate on `employeeKey` too, so a write
   *  then throws instead of being dropped or filed under the wrong key. */
  const update = useCallback(<R extends string>(change: (prev: FanTab[]) => FanTab[] | R): R | null => {
    if (storageKey === null) throw new Error("useFanTabs: the Employee is unresolved; gate on employeeKey");
    const next = change(parseTabs(readStorage(storageKey)));
    if (typeof next === "string") return next;
    const stored: StoredTab[] = next.map((t) => ({ accountId: t.accountId, fanId: String(t.fanId), name: t.name }));
    window.localStorage.setItem(storageKey, JSON.stringify(stored));
    window.dispatchEvent(new Event(EVENT));
    return null;
  }, [storageKey]);

  const open = useCallback((tab: FanTab): "opened" | "exists" | "full" => {
    const key = fanTabKey(tab.accountId, tab.fanId);
    const refused = update((prev): FanTab[] | "exists" | "full" => {
      if (prev.some((t) => fanTabKey(t.accountId, t.fanId) === key)) return "exists";
      if (prev.length >= FAN_TABS_MAX) return "full";
      return [...prev, tab];
    });
    return refused ?? "opened";
  }, [update]);

  const close = useCallback((key: string) => {
    update((prev) => {
      const left = prev.filter((t) => fanTabKey(t.accountId, t.fanId) !== key);
      return left.length === prev.length ? "unknown" : left;
    });
  }, [update]);

  // While the key is null nothing is read, so `tabs` and `stored` are empty.
  return { tabs, stored, full: stored.length >= FAN_TABS_MAX, employeeKey, open, close };
}

/**
 * The close rule (tickets 72 and 74), one per window whatever its width: once
 * the store re-renders without a stored tab (a ✕ here, through the returned
 * `closeTab`, or a `storage` write from another window), it runs:
 * - none left: `onClosed(null)`, which empties the Thread;
 * - the active tab (`activeKey`) gone: `onClosed(last remaining tab)`;
 * - an inactive tab gone: nothing.
 * `onClosedHere` then gets the tab active once the close is done (the active
 * one if it remains, else the last remaining one, or null with none left),
 * only after a `closeTab` in this window: a remote close moves no focus.
 * Switching Employee (or the key going unresolved) swaps the tab set and
 * closes nothing. A tab hidden because its Creator left the relay is not
 * closed. With `enabled` false the rule only keeps count, so a window can
 * hand it from the page to the Fan tabs strip when the strip mounts.
 */
export function useFanTabsCloseRule({ activeKey, onClosed, onClosedHere, enabled = true }: {
  activeKey: string | null;
  onClosed: (next: FanTab | null) => void;
  onClosedHere?: (next: FanTab | null) => void;
  enabled?: boolean;
}): (key: string) => void {
  const { tabs, stored, employeeKey, close } = useFanTabs();
  const seen = useRef({ employeeKey, stored });
  const closedHere = useRef<string | null>(null);
  useLayoutEffect(() => {
    const prev = seen.current;
    seen.current = { employeeKey, stored };
    // Another Employee's tab set (or none while unresolved): nothing closed.
    if (prev.employeeKey !== employeeKey) return;
    const keys = new Set(stored.map((t) => fanTabKey(t.accountId, t.fanId)));
    const removed = prev.stored.filter((t) => !keys.has(fanTabKey(t.accountId, t.fanId)))
      .map((t) => fanTabKey(t.accountId, t.fanId));
    if (removed.length === 0) return;
    const local = closedHere.current !== null && removed.includes(closedHere.current);
    closedHere.current = null;
    if (!enabled) return;
    if (tabs.length === 0) {
      if (local) onClosedHere?.(null);
      onClosed(null);
      return;
    }
    const next = tabs.find((t) => fanTabKey(t.accountId, t.fanId) === activeKey) ?? tabs[tabs.length - 1];
    if (activeKey !== null && removed.includes(activeKey)) onClosed(next);
    if (local) onClosedHere?.(next);
  }, [employeeKey, stored, tabs, activeKey, onClosed, onClosedHere, enabled]);

  return useCallback((key: string) => {
    closedHere.current = key;
    close(key);
  }, [close]);
}
