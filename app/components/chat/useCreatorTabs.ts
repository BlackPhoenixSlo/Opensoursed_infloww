"use client";


import { useCallback, useEffect, useMemo, useState, useSyncExternalStore } from "react";

import { useAccounts, usePlatformAccounts } from "@/hooks/useAccounts";
import { useCreatorFreshnessState } from "@/hooks/useCreatorFreshness";
import { useEmployeeKey } from "@/hooks/useEmployeeKey";
import { useRosterCountsRead } from "@/hooks/useRosterCounts";
import { eventBus } from "@/lib/events";
import type { AccountMeta } from "@/lib/relay";
import { readStorage, subscribeToStorage } from "@/lib/storageSync";
import { amberCircle, type AmberCircle } from "./amberCircle";
import { redCircle, shownUnread, type RedCircle } from "./redCircle";

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

export function sortTabs(open: AccountMeta[], sort: CreatorSort, unreadOf: (id: string) => number): AccountMeta[] {
  if (sort === "custom") return open;
  const name = (a: AccountMeta) => a.nickname || a.id;
  const out = open.slice();
  if (sort === "unread") out.sort((a, b) => unreadOf(b.id) - unreadOf(a.id));
  else out.sort((a, b) => (sort === "az" ? 1 : -1) * name(a).localeCompare(name(b), undefined, { sensitivity: "base" }));
  return out;
}

function useRelayReachable(): boolean {
  const [up, setUp] = useState(true);
  useEffect(() => eventBus.onStateChange(setUp), []);
  return up;
}

export function useShownCreatorTabs(store: CreatorTabsStore): {
  open: AccountMeta[]; circles: Record<string, RedCircle>; ambers: Record<string, AmberCircle>; known: boolean;
} {
  const { counts, settled } = useRosterCountsRead();
  const freshness = useCreatorFreshnessState();
  const reachable = useRelayReachable();
  const { open, sort, ready } = store;
  const circles = useMemo(() => Object.fromEntries(open.map((a) => [
    a.id, redCircle(freshness[a.id]?.values.unread_total, reachable, counts[a.id]?.unread, settled),
  ])), [open, freshness, reachable, counts, settled]);
  const ambers = useMemo(() => Object.fromEntries(open.map((a) => [
    a.id, amberCircle(freshness[a.id]?.values.unread_total, circles[a.id].kind, counts[a.id]?.owe_reply),
  ])), [open, freshness, circles, counts]);
  const shown = useMemo(() => sortTabs(open, sort, (id) => shownUnread(circles[id])), [open, sort, circles]);
  return { open: shown, circles, ambers, known: ready && (sort !== "unread" || settled) };
}

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

  // Read from query status, not data: a chatter session has data while still pending.
  const ready = accountsSettled && storageKey !== null;

  const raw = useSyncExternalStore(subscribe, () => readStorage(storageKey), () => null);
  const saved = useMemo(() => parseSavedTabs(raw), [raw]);

  const update = useCallback((change: (prev: SavedTabs) => SavedTabs) => {
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
      const full = [...new Set([...prev.order, ...creators.map((a) => a.id)])];
      let next = 0;
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
