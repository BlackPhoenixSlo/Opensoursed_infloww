"use client";

import { useEffect, useState } from "react";

export function useTrailingDebounce<T>(value: T, ms: number, now: (v: T) => boolean = () => false): T {
  const [settled, setSettled] = useState(value);
  // Adjusted during render, not in an effect: the next change debounces from this value, never an older one.
  const immediate = now(value);
  if (immediate && !Object.is(settled, value)) setSettled(value);
  useEffect(() => {
    if (immediate) return;
    const t = window.setTimeout(() => setSettled(value), ms);
    return () => window.clearTimeout(t);
  }, [value, ms, immediate]);
  return immediate ? value : settled;
}
