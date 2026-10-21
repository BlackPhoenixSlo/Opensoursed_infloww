"use client";

import { useEffect, useState } from "react";

/**
 * Infinite scroll's sentinel: give the returned callback ref to an element under the list, and the next page loads
 * when it comes within 200px of the viewport (and there is one, and none is loading).
 *
 * A callback ref, not `useRef`: the observer follows the element itself, so a sentinel that unmounts (an error
 * state) and mounts again (Retry) is observed again; a ref object's change would not rerun the effect.
 */
export function useLoadMoreSentinel(
  hasNextPage: boolean, isFetchingNextPage: boolean, fetchNextPage: () => unknown,
): (el: HTMLElement | null) => void {
  const [el, setEl] = useState<HTMLElement | null>(null);
  useEffect(() => {
    if (!el || !hasNextPage) return;
    const io = new IntersectionObserver((entries) => {
      if (entries[0]?.isIntersecting && !isFetchingNextPage) void fetchNextPage();
    }, { rootMargin: "200px" });
    io.observe(el);
    return () => io.disconnect();
  }, [el, hasNextPage, isFetchingNextPage, fetchNextPage]);
  return setEl;
}
