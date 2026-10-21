"use client";

/**
 * useInsightsBlocks — the order of Fan insights' Insights blocks and which
 * of them are removed, persisted for this browser. The grip drags a block to
 * a new place, its × removes it and the head's "+" adds a removed one back
 * at its old place. The `useFocusModeSettings` storage pattern, so the pinned
 * pane and its slide-over twin share one layout.
 *
 * A stored layout keeps only the ids it knows; a block it lacks (one added
 * since it was saved) is shown, after the stored ones. Anything that is not
 * this shape reads as the default: `INSIGHTS_BLOCKS` order, with
 * `DEFAULT_HIDDEN` removed (still re-addable from the "+").
 */

import { useCallback, useSyncExternalStore } from "react";

import { subscribeToStorage } from "@/lib/storageSync";

/** Every Insights block, in its default order: the selling order — who the Fan
 *  is, what he spends, what to resell him, what we know, whether mass sends
 *  reach him, then the reference blocks. */
export const INSIGHTS_BLOCKS = [
  "fan", "spending", "unsoldPpvs", "notes", "massExclude",
  "subscription", "profile", "lists", "org",
] as const;

export type InsightsBlockId = (typeof INSIGHTS_BLOCKS)[number];

/** Removed by default; the "+" adds it back. */
const DEFAULT_HIDDEN: readonly InsightsBlockId[] = ["org"];

type Layout = { order: InsightsBlockId[]; hidden: InsightsBlockId[] };

// v2 (2026-10-21): a new default order with Organization metrics removed. The
// new key resets layouts saved under the first one once.
const STORAGE_KEY = "chatterly:fan-insights-blocks:v2";
const EVENT = "chatterly-fan-insights-blocks-change";
const subscribe = subscribeToStorage(EVENT);

const isId = (v: unknown): v is InsightsBlockId =>
  (INSIGHTS_BLOCKS as readonly unknown[]).includes(v);

function readRaw(): string | null {
  return window.localStorage.getItem(STORAGE_KEY);
}

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
    } catch { /* not JSON: the default */ }
  }
  return { order: [...order, ...INSIGHTS_BLOCKS.filter((id) => !order.includes(id))], hidden };
}

// Parsed once per raw string, so the layout keeps its identity between renders.
let cache: { raw: string | null; value: Layout } = { raw: null, value: parse(null) };
function parsed(raw: string | null): Layout {
  if (cache.raw !== raw) cache = { raw, value: parse(raw) };
  return cache.value;
}

function write(next: Layout) {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
    window.dispatchEvent(new Event(EVENT));
  } catch { /* quota: silent */ }
}

export function useInsightsBlocks() {
  const layout = parsed(useSyncExternalStore(subscribe, readRaw, () => null));
  const shown = layout.order.filter((id) => !layout.hidden.includes(id));
  const removed = layout.order.filter((id) => layout.hidden.includes(id));

  /** `next` is the shown blocks in their new order; removed blocks keep their slots. */
  const reorder = useCallback((next: InsightsBlockId[]) => {
    const cur = parsed(readRaw());
    const queue = [...next];
    write({ ...cur, order: cur.order.map((id) => (cur.hidden.includes(id) ? id : queue.shift() ?? id)) });
  }, []);
  const remove = useCallback((id: InsightsBlockId) => {
    const cur = parsed(readRaw());
    if (!cur.hidden.includes(id)) write({ ...cur, hidden: [...cur.hidden, id] });
  }, []);
  const add = useCallback((id: InsightsBlockId) => {
    const cur = parsed(readRaw());
    if (cur.hidden.includes(id)) write({ ...cur, hidden: cur.hidden.filter((h) => h !== id) });
  }, []);

  return { shown, removed, reorder, remove, add };
}
