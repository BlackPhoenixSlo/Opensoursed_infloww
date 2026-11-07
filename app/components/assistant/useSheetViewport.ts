"use client";

/**
 * useSheetViewport — keeps the phone's full-screen help sheet on screen while
 * the iOS keyboard is up.
 *
 * iOS Safari answers a focused input by scrolling the LAYOUT viewport (the
 * document) until the input is visible. A `position: fixed; top: 0` sheet is
 * pinned to that layout viewport, so it rides up with it and the dashboard
 * behind shows with the keyboard open (owner, iPhone). Two parts:
 *
 *   • BODY LOCK while the sheet is mounted: body `position: fixed` at
 *     `top: -scrollY`, html/body `overflow: hidden`, so the page has nothing
 *     to scroll; on unmount the old inline styles come back and the scroll is
 *     restored — unless the URL changed (an answer link navigated: the new
 *     page starts at its own top, not at the old page's offset).
 *   • VISUAL VIEWPORT: the returned style pins the sheet to
 *     `visualViewport.offsetTop` with `visualViewport.height`, re-read on its
 *     resize / scroll, so the flex column's last row — the composer — sits
 *     right above the keyboard even when Safari pans the visual viewport.
 *
 * Inferred, not measured on a device: Playwright cannot raise a real iOS
 * keyboard (a resized viewport stands in for it in the proof).
 */
import { useEffect, useState, type CSSProperties } from "react";

interface Box { top: number; height: number }

const read = (): Box | null => {
  const vv = typeof window !== "undefined" ? window.visualViewport : null;
  return vv ? { top: vv.offsetTop, height: vv.height } : null;
};

export function useSheetViewport(active: boolean): CSSProperties | undefined {
  const [box, setBox] = useState<Box | null>(null);

  useEffect(() => {
    if (!active) return;
    const { body, documentElement: html } = document;
    const y = window.scrollY;
    const url = window.location.pathname + window.location.search;
    const prev = { body: body.getAttribute("style"), html: html.style.overflow };
    Object.assign(body.style, { position: "fixed", top: `${-y}px`, left: "0", right: "0", width: "100%", overflow: "hidden" });
    html.style.overflow = "hidden";

    const vv = window.visualViewport;
    const update = () => setBox(read());
    update();
    vv?.addEventListener("resize", update);
    vv?.addEventListener("scroll", update);
    return () => {
      vv?.removeEventListener("resize", update);
      vv?.removeEventListener("scroll", update);
      if (prev.body === null) body.removeAttribute("style");
      else body.setAttribute("style", prev.body);
      html.style.overflow = prev.html;
      // While locked the page sits at 0, so only a non-zero offset needs putting back.
      if (y && window.location.pathname + window.location.search === url) window.scrollTo(0, y);
      setBox(null);
    };
  }, [active]);

  return active && box ? { top: box.top, height: box.height } : undefined;
}
