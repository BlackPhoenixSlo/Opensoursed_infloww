"use client";

import { useSyncExternalStore } from "react";

/** Tailwind's `lg`: from here up the app docks its sidebar and Messages Pro
 *  shows its panes side by side (and neither the nav drawer nor the phone's
 *  swipes exist). */
export const LG = "(min-width: 1024px)";

function subscribe(cb: () => void) {
  const mq = window.matchMedia(LG);
  mq.addEventListener("change", cb);
  return () => mq.removeEventListener("change", cb);
}

/** True while the viewport is at least 1024px wide; false on the server. */
export function useIsDesktop(): boolean {
  return useSyncExternalStore(subscribe, () => window.matchMedia(LG).matches, () => false);
}
