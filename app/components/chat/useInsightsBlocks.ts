"use client";


import { useCallback, useSyncExternalStore } from "react";

import { readStorage, subscribeToStorage } from "@/lib/storageSync";

export const INSIGHTS_BLOCKS = [
  "fan", "spending", "unsoldPpvs", "notes", "massExclude",
  "subscription", "profile", "lists", "org",
] as const;

export type InsightsBlockId = (typeof INSIGHTS_BLOCKS)[number];

const DEFAULT_HIDDEN: readonly InsightsBlockId[] = ["org"];

type Layout = { order: InsightsBlockId[]; hidden: InsightsBlockId[] };

const STORAGE_KEY = "chatterly:fan-insights-blocks:v2";
const EVENT = "chatterly-fan-insights-blocks-change";
const subscribe = subscribeToStorage(EVENT);

const isId = (v: unknown): v is InsightsBlockId =>
  (INSIGHTS_BLOCKS as readonly unknown[]).includes(v);

function parse(raw: string | null): Layout {
  let order: InsightsBlockId[] = [];
  let hidden: InsightsBlockId[] = [...DEFAULT_HIDDEN];
  if (raw !== null) {
    try {
      const v = JSON.parse(raw) as Record<string, unknown>;
      if (Array.isArray(v.order) && Array.isArray(v.hidden)) {
        order = [...new Set(v.order.filter(isId))];
        hidden = [...new Set(v.hidden.filter(isId))];
      }
    } catch { }
  }
  return { order: [...order, ...INSIGHTS_BLOCKS.filter((id) => !order.includes(id))], hidden };
}

let cache: { raw: string | null; value: Layout } = { raw: null, value: parse(null) };
function parsed(raw: string | null): Layout {
  if (cache.raw !== raw) cache = { raw, value: parse(raw) };
  return cache.value;
}

function write(next: Layout) {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
    window.dispatchEvent(new Event(EVENT));
  } catch { }
}

export function useInsightsBlocks(withheld: InsightsBlockId | null) {
  const layout = parsed(useSyncExternalStore(subscribe, () => readStorage(STORAGE_KEY), () => null));
  const shown = layout.order.filter((id) => id !== withheld && !layout.hidden.includes(id));
  const removed = layout.order.filter((id) => id !== withheld && layout.hidden.includes(id));

  const reorder = useCallback((next: InsightsBlockId[]) => {
    const cur = parsed(readStorage(STORAGE_KEY));
    const queue = [...next];
    write({ ...cur, order: cur.order.map((id) => (id === withheld || cur.hidden.includes(id) ? id : queue.shift() ?? id)) });
  }, [withheld]);
  const remove = useCallback((id: InsightsBlockId) => {
    const cur = parsed(readStorage(STORAGE_KEY));
    if (!cur.hidden.includes(id)) write({ ...cur, hidden: [...cur.hidden, id] });
  }, []);
  const add = useCallback((id: InsightsBlockId) => {
    const cur = parsed(readStorage(STORAGE_KEY));
    if (cur.hidden.includes(id)) write({ ...cur, hidden: cur.hidden.filter((h) => h !== id) });
  }, []);

  return { shown, removed, reorder, remove, add };
}
