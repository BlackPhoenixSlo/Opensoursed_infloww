"use client";

import { useEffect } from "react";

const BODY_LOCK = ["position", "top", "left", "right", "width", "overflow"] as const;

export function useBodyScrollLock(active: boolean): void {
  // iOS Safari scrolls the layout viewport to reveal a focused input, dragging the fixed sheet with it; lock the body so there is nothing to scroll.
  useEffect(() => {
    if (!active) return;
    const { body, documentElement: html } = document;
    const y = window.scrollY;
    const prevBody = BODY_LOCK.map((p) => body.style[p]);
    const prevHtml = html.style.overflow;
    Object.assign(body.style, { position: "fixed", top: `${-y}px`, left: "0", right: "0", width: "100%", overflow: "hidden" });
    html.style.overflow = "hidden";
    return () => {
      BODY_LOCK.forEach((p, i) => { body.style[p] = prevBody[i]; });
      html.style.overflow = prevHtml;
      if (y) window.scrollTo(0, y);
    };
  }, [active]);
}
