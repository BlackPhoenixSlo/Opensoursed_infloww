"use client";

import { useCallback, useEffect, useState } from "react";

export function useRenderCap(total: number, resetKey: string, step = 200) {
  const [s, setS] = useState({ key: resetKey, cap: step });
  if (s.key !== resetKey) setS({ key: resetKey, cap: step });
  const cap = s.key === resetKey ? s.cap : step;
  const hasMore = cap < total;
  const more = useCallback(() => setS((p) => ({ ...p, cap: p.cap + step })), [step]);
  const [el, setEl] = useState<HTMLElement | null>(null);
  useEffect(() => {
    if (!el || !hasMore || typeof IntersectionObserver === "undefined") return;
    const io = new IntersectionObserver((e) => {
      if (e[0]?.isIntersecting) more();
    }, { rootMargin: "400px" });
    io.observe(el);
    return () => io.disconnect();
  }, [el, hasMore, cap, more]);
  return { cap, hasMore, more, sentinel: setEl };
}
