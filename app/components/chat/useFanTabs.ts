"use client";


import { useCallback, useLayoutEffect, useMemo, useRef, useSyncExternalStore } from "react";

import { useAccounts, usePlatformAccounts } from "@/hooks/useAccounts";
import { useEmployeeKey } from "@/hooks/useEmployeeKey";
import { fanIdFromParam, type FanId } from "@/lib/fanId";
import { readStorage, subscribeToStorage } from "@/lib/storageSync";

export type FanTab = { accountId: string; fanId: FanId; name: string };

export const FAN_TABS_MAX = 100;

export const FAN_TABS_FULL_LABEL = `Fan tab limit reached (${FAN_TABS_MAX})`;

export function fanTabKey(accountId: string, fanId: FanId): string {
  return `${accountId}:${String(fanId)}`;
}

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

  const accounts = useAccounts();
  // Query flags, not data: a chatter session's `data` is defined while pending; a failed refetch keeps the last answered list.
  const creatorsLoaded = accounts.isSuccess || accounts.isRefetchError;
  const creators = usePlatformAccounts();
  const tabs = useMemo(() => {
    if (!creatorsLoaded) return stored;
    const live = new Set(creators.map((a) => a.id));
    return stored.filter((t) => live.has(t.accountId));
  }, [creatorsLoaded, creators, stored]);

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

  return { tabs, stored, full: stored.length >= FAN_TABS_MAX, employeeKey, open, close };
}

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
