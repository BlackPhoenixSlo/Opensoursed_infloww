"use client";

import { useEffect } from "react";
import { BRAND_NAME } from "@/lib/brand";

export function useDocumentTitle(title: string, enabled = true): void {
  useEffect(() => {
    if (!enabled) return;
    document.title = title;
    // Next's layout reapplies its static title on re-renders/HMR; a plain assignment loses.
    const obs = new MutationObserver(() => {
      if (document.title !== title) document.title = title;
    });
    obs.observe(document.head, { childList: true, subtree: true, characterData: true });
    return () => { obs.disconnect(); document.title = BRAND_NAME; };
  }, [title, enabled]);
}
