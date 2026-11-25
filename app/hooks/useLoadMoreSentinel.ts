"use client";

import { useEffect, useState } from "react";

// Callback ref, not useRef: a sentinel that unmounts (error state) and remounts (Retry) must be observed again.
export function useLoadMoreSentinel(
  hasNextPage: boolean, isFetchingNextPage: boolean, fetchNextPage: () => unknown,
  isError = false,
): (el: HTMLElement | null) => void {
  const [el, setEl] = useState<HTMLElement | null>(null);
  useEffect(() => {
    if (!el || !hasNextPage || isError) return;
    const io = new IntersectionObserver((entries) => {
      if (entries[0]?.isIntersecting && !isFetchingNextPage) void fetchNextPage();
    }, { rootMargin: "200px" });
    io.observe(el);
    return () => io.disconnect();
  }, [el, hasNextPage, isFetchingNextPage, fetchNextPage, isError]);
  return setEl;
}
