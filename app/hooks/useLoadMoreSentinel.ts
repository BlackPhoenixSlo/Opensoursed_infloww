"use client";

import { useEffect, useState } from "react";

/**
 * Infinite scroll's sentinel: give the returned callback ref to an element under the list, and the next page loads
 * when it comes within 200px of the viewport (and there is one, none is loading, and the last one did not fail).
 *
 * A callback ref, not `useRef`: the observer follows the element itself, so a sentinel that unmounts (an error
 * state) and mounts again (Retry) is observed again; a ref object's change would not rerun the effect.
 *
 * `isError` (the query's, React Query's): after a failed page the sentinel stays still, else a foot still in view
 * would ask again on every fetch flip. The list's own Load more / Retry / refetch is the way on; the flag stays set
 * while either retry runs (`isFetchNextPageError` would drop during a refetch, letting the sentinel cancel it with
 * a next page), and clears when a page loads, which resumes auto-loading.
 */
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
