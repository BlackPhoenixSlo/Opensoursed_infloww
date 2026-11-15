"use client";

/**
 * useViewLease — the React face of `holdLease` (lib/viewLease.ts, ADR-0031 phase-01): while mounted, this component
 * leases `accountIds` (its own hold, keyed by `source` — a label only — and its `useId`); a new set replaces it, [] or
 * unmount releases it. The open chat (ChatSurface) calls it; the visible-row sources call `useOnScreenLease(source)`,
 * which leases the rows its `track` ref finds on screen (an IntersectionObserver): the rail (MoneyRailPanel), the roster
 * strip (CreatorTabs) and OF Manager's Creator column (CreatorColumn). So the All view, or a chatter with permission
 * "all", leases only what is on screen.
 */

import { useCallback, useEffect, useId, useRef, useState } from "react";

import { holdLease } from "@/lib/viewLease";
import { sortedIds } from "@/lib/viewLeaseState";

export function useViewLease(accountIds: readonly string[], source = "view"): void {
  const id = useId();
  const key = sortedIds(accountIds).join("\n");
  useEffect(() => (key ? holdLease(`${source}#${id}`, key.split("\n")) : undefined), [source, id, key]);
}

/** A row on screen shows some of itself: an edge-adjacent row (ratio 0) does not count. A browser calls back only
 *  when a row crosses a threshold, so 1e-6 (below any real sliver: a layout unit is 1/64 px) splits "touching" from
 *  "showing"; with 0.01 a sliver sliding to edge-adjacent would stay leased. */
const THRESHOLD = [0, 1e-6];

/** Leases, under `source`, the Creators of the rows on screen now. Returns `track(id, key = id)`: the row element's
 *  ref (stable per key while the row is mounted; a Creator may have several rows, each its own key). Rows clipped by
 *  a scrolling ancestor (the strip, the rail, the column) or outside the viewport are off screen. Without
 *  IntersectionObserver nothing is on screen. */
export function useOnScreenLease(source: string): (id: string, key?: string) => (el: Element | null) => void {
  const [onScreen, setOnScreen] = useState<readonly string[]>([]);
  useViewLease(onScreen, source);
  const io = useRef<IntersectionObserver | null>(null);
  const idOf = useRef(new Map<Element, string>());
  const elOf = useRef(new Map<string, Element>());
  const shown = useRef(new Set<Element>());
  const refs = useRef(new Map<string, (el: Element | null) => void>());

  const publish = useCallback(() => {
    setOnScreen((prev) => sortedIds([...shown.current].map((el) => idOf.current.get(el)!), prev));
  }, []);

  useEffect(() => {
    if (typeof IntersectionObserver === "undefined") return;
    const shownEls = shown.current;
    const obs = new IntersectionObserver((entries) => {
      for (const e of entries) {
        if (!idOf.current.has(e.target)) continue;
        if (e.isIntersecting && e.intersectionRatio > 0) shownEls.add(e.target);
        else shownEls.delete(e.target);
      }
      publish();
    }, { threshold: THRESHOLD });
    io.current = obs;
    for (const el of idOf.current.keys()) obs.observe(el);
    return () => {
      obs.disconnect();
      io.current = null;
      shownEls.clear();
      publish();
    };
  }, [publish]);

  return useCallback((id: string, key: string = id) => {
    const known = refs.current.get(key);
    if (known) return known;
    // Stable while the row is mounted (a new ref each render would make React detach and re-attach it, a loss and a
    // gain); dropped when the row unmounts, so rows that come and go (the rail's) leave nothing behind.
    const ref = (el: Element | null) => {
      const old = elOf.current.get(key);
      if (old === el) return;
      if (old) {
        io.current?.unobserve(old);
        idOf.current.delete(old);
        elOf.current.delete(key);
        if (shown.current.delete(old)) publish();
      }
      if (el) {
        refs.current.set(key, ref);
        elOf.current.set(key, el);
        idOf.current.set(el, id);
        io.current?.observe(el);
      } else if (refs.current.get(key) === ref) {
        refs.current.delete(key);
      }
    };
    refs.current.set(key, ref);
    return ref;
  }, [publish]);
}
