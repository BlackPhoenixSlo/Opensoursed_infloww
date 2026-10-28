"use client";

import { useEffect, useState } from "react";

/**
 * `value` once it has rested `ms` with no further change (a trailing debounce): while it keeps changing, the last
 * settled value. A value `now(value)` accepts comes through at once, in the same render (e.g. a cleared search box).
 * Compared with `Object.is`, so pass a primitive. The Fan List's search uses it.
 */
export function useTrailingDebounce<T>(value: T, ms: number, now: (v: T) => boolean = () => false): T {
  const [settled, setSettled] = useState(value);
  const immediate = now(value);
  // Adjusted during render, not in an effect: the next change debounces from this value, never an older one.
  if (immediate && !Object.is(settled, value)) setSettled(value);
  useEffect(() => {
    if (immediate) return;
    const t = window.setTimeout(() => setSettled(value), ms);
    return () => window.clearTimeout(t);
  }, [value, ms, immediate]);
  return immediate ? value : settled;
}
