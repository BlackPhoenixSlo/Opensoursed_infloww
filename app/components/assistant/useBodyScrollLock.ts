"use client";

/**
 * useBodyScrollLock — locks the page under the phone's full-screen help sheet
 * so the iOS keyboard cannot scroll it out from under the sheet.
 *
 * iOS Safari answers a focused input by scrolling the LAYOUT viewport (the
 * document) until the input is visible. A `position: fixed; top: 0` sheet is
 * pinned to that layout viewport, so it rides up with it and the dashboard
 * behind shows with the keyboard open (owner, iPhone). While `active`: body
 * `position: fixed` at `top: -scrollY`, html/body `overflow: hidden`, so the
 * page has nothing to scroll; on unmount only the properties it set are put
 * back (another lock's inline styles survive) and the scroll is restored.
 * The other half — pinning the sheet to the visual viewport — is
 * AssistantWidget's `VARIANT.sheet` frame (`--vvt` / `--vvh`, app/layout.tsx).
 *
 * Inferred, not measured on a device: Playwright cannot raise a real iOS
 * keyboard (a resized viewport stands in for it in the proof).
 */
import { useEffect } from "react";

const BODY_LOCK = ["position", "top", "left", "right", "width", "overflow"] as const;

export function useBodyScrollLock(active: boolean): void {
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
      // While locked the page sits at 0, so only a non-zero offset needs putting back.
      if (y) window.scrollTo(0, y);
    };
  }, [active]);
}
