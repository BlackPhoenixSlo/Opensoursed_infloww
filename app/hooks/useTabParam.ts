"use client";

import { useEffect } from "react";

export function useTabParam<T extends string>(
  param: string,
  isValid: (v: string) => v is T,
  onFound: (tab: T) => void,
): void {
  useEffect(() => {
    // Reads window.location in an effect, not useSearchParams: that suspends and would force a Suspense boundary on every caller.
    let raw: string | null = null;
    try {
      raw = new URLSearchParams(window.location.search).get(param);
    } catch {
      return;
    }
    if (raw && isValid(raw)) onFound(raw);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
}
