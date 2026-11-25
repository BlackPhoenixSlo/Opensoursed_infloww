"use client";


import { useCallback, useEffect, useId, useRef, useState } from "react";

import { holdLease } from "@/lib/viewLease";
import { sortedIds } from "@/lib/viewLeaseState";

export function useViewLease(accountIds: readonly string[], source = "view"): void {
  const id = useId();
  const key = sortedIds(accountIds).join("\n");
  useEffect(() => (key ? holdLease(`${source}#${id}`, key.split("\n")) : undefined), [source, id, key]);
}

// 1e-6 splits an edge-adjacent row (ratio 0) from one showing a sliver; 0.01 would keep a sliver leased.
const THRESHOLD = [0, 1e-6];

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
