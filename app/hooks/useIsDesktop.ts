"use client";

import { useSyncExternalStore } from "react";

export const LG = "(min-width: 1024px)";

function subscribe(cb: () => void) {
  const mq = window.matchMedia(LG);
  mq.addEventListener("change", cb);
  return () => mq.removeEventListener("change", cb);
}

export function useIsDesktop(): boolean {
  return useSyncExternalStore(subscribe, () => window.matchMedia(LG).matches, () => false);
}
