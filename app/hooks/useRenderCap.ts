"use client";

import { useCallback, useEffect, useState } from "react";

/**
 * Incremental render for a long in-memory list (Growth > Scripts at 10k scripts, the chat's template picker): the
 * first `step` rows, then `step` more each time the returned `sentinel` (a ref for an element after the last row)
 * comes near the viewport, or on `more()` (its Show more button, where IntersectionObserver is missing). A new
 * `resetKey` (another list, another search) starts over at `step`.
 */
export function useRenderCap(total: number, resetKey: string, step = 200) {
  const [s, setS] = useState({ key: resetKey, cap: step });
  if (s.key !== resetKey) setS({ key: resetKey, cap: step });
  const cap = s.key === resetKey ? s.cap : step;
  const hasMore = cap < total;
  const more = useCallback(() => setS((p) => ({ ...p, cap: p.cap + step })), [step]);
  const [el, setEl] = useState<HTMLElement | null>(null);
  useEffect(() => {
    if (!el || !hasMore || typeof IntersectionObserver === "undefined") return;
    // Re-observed after each step (`cap`): a sentinel still in view grows the list again.
    const io = new IntersectionObserver((e) => {
      if (e[0]?.isIntersecting) more();
    }, { rootMargin: "400px" });
    io.observe(el);
    return () => io.disconnect();
  }, [el, hasMore, cap, more]);
  return { cap, hasMore, more, sentinel: setEl };
}
