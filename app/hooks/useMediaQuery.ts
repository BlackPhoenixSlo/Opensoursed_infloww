"use client";

import { useCallback, useSyncExternalStore } from "react";

/** Live `matchMedia(query).matches`. False on the server and where
 *  matchMedia is missing (jsdom), so those render the desktop layout. */
export function useMediaQuery(query: string): boolean {
  const subscribe = useCallback((cb: () => void) => {
    if (typeof window === "undefined" || !window.matchMedia) return () => {};
    const m = window.matchMedia(query);
    m.addEventListener("change", cb);
    return () => m.removeEventListener("change", cb);
  }, [query]);
  return useSyncExternalStore(
    subscribe,
    () => typeof window !== "undefined" && !!window.matchMedia && window.matchMedia(query).matches,
    () => false,
  );
}
