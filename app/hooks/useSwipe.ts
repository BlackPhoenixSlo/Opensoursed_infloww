"use client";

import { useEffect, useRef, type RefObject } from "react";

/**
 * A one-finger horizontal swipe on a phone: it opens the shell's nav drawer from
 * a dashboard page, and dismisses that drawer or Messages Pro's Fan insights
 * slide-over. Dependency-free: passive touch listeners, so scrolling is never
 * blocked and a mouse never triggers it.
 *
 * It fires only below lg (where those overlays exist), for a mostly-horizontal
 * move (`swipeDirection`) that did not start in a text field, a `data-no-swipe`
 * element or a horizontal scroller (`startsInIgnored`). A `touchcancel` (the
 * platform took the gesture: iOS edge-back, a system gesture) aborts it, so the
 * browser's own action and ours never both run. `edgeGuard` also drops a touch
 * that starts within that many px of either side, the OS's own back/forward
 * zone, and `ignoreWhile` one made while that selector matches (an open
 * dialog). A gesture that turns vertical (the finger's whole move from its
 * start becomes mostly vertical) or scrolls what it started in is not a swipe
 * for the rest of that touch, even if it ends sideways. Back/forward is left to the
 * platform: Messages Pro gives it a history entry instead (`useChatBackEntry`).
 *
 * `follow` slides that element with the finger in the swipe's direction and
 * eases it back if the swipe falls short; never under prefers-reduced-motion.
 */

export type SwipeDir = "left" | "right";

/** Past this many px a swipe counts at any speed. */
export const SWIPE_MIN_PX = 50;
/** A quick flick counts from here, at `SWIPE_FLICK_PX_PER_MS` or faster. */
export const SWIPE_FLICK_MIN_PX = 25;
export const SWIPE_FLICK_PX_PER_MS = 0.4;
/** At most 30° off horizontal: |dy| <= |dx| * tan(30°). */
export const SWIPE_MAX_SLOPE = Math.tan(Math.PI / 6);
/** Below this the finger's intent is not known yet. */
const LOCK_PX = 10;
/** `useIsDesktop`'s lg: from here up neither overlay exists. */
const LG = "(min-width: 1024px)";
const REDUCED = "(prefers-reduced-motion: reduce)";
const IGNORE = "input, textarea, select, [contenteditable=''], [contenteditable='true'], [data-no-swipe]";

/** The swipe a finger's move (`dx`, `dy` px over `ms`) makes, or null. */
export function swipeDirection(dx: number, dy: number, ms: number): SwipeDir | null {
  const dist = Math.abs(dx);
  if (Math.abs(dy) > dist * SWIPE_MAX_SLOPE) return null;
  const fast = dist >= SWIPE_FLICK_MIN_PX && dist / Math.max(ms, 1) >= SWIPE_FLICK_PX_PER_MS;
  if (dist < SWIPE_MIN_PX && !fast) return null;
  return dx > 0 ? "right" : "left";
}

/** A touch on `target` belongs to something else: a text field, a `data-no-swipe`
 *  element, or a horizontal scroller between it and `root` (inclusive). */
export function startsInIgnored(target: EventTarget | null, root: Element | null): boolean {
  let el = target instanceof Element ? target : null;
  if (el?.closest(IGNORE)) return true;
  for (; el; el = el.parentElement) {
    if (el.scrollWidth > el.clientWidth + 1 && /auto|scroll/.test(getComputedStyle(el).overflowX)) return true;
    if (el === root) break;
  }
  return false;
}

export interface SwipeOptions {
  enabled: boolean;
  dir: SwipeDir;
  onSwipe: () => void;
  follow?: RefObject<HTMLElement | null>;
  /** Ignore a touch starting within this many px of the left or right side. */
  edgeGuard?: number;
  /** Ignore a touch made while something matches this selector. */
  ignoreWhile?: string;
}

/** iOS's edge-back zone is ~20px, Android's back gesture about as wide. */
export const OS_EDGE_PX = 24;

/** Listen on `target`'s element, or on the whole document when `target` is null. */
export function useSwipe(target: RefObject<HTMLElement | null> | null, {
  enabled, dir, onSwipe, follow, edgeGuard = 0, ignoreWhile,
}: SwipeOptions) {
  const onSwipeRef = useRef(onSwipe);
  useEffect(() => { onSwipeRef.current = onSwipe; });

  useEffect(() => {
    if (!enabled) return;
    const root: HTMLElement | Document | null = target ? target.current : document;
    if (!root) return;
    let start: { x: number; y: number; t: number } | null = null;
    let from: Node | null = null;
    let horizontal = false;
    const sign = dir === "right" ? 1 : -1;

    const slide = (dx: number) => {
      const el = follow?.current;
      if (!el || window.matchMedia(REDUCED).matches) return;
      el.style.transition = dx === 0 ? "transform 150ms ease-out" : "none";
      el.style.transform = dx === 0 ? "" : `translateX(${dx}px)`;
    };
    const reset = () => {
      if (horizontal) slide(0);
      start = null;
      from = null;
      horizontal = false;
    };
    const onStart = (e: TouchEvent) => {
      reset();
      if (e.touches.length !== 1 || window.matchMedia(LG).matches) return;
      if (startsInIgnored(e.target, root instanceof Document ? null : root)) return;
      const t = e.touches[0];
      if (t.clientX < edgeGuard || t.clientX > window.innerWidth - edgeGuard) return;
      if (ignoreWhile && document.querySelector(ignoreWhile)) return;
      start = { x: t.clientX, y: t.clientY, t: e.timeStamp };
      from = e.target instanceof Node ? e.target : null;
    };
    const onMove = (e: TouchEvent) => {
      if (!start) return;
      if (e.touches.length !== 1) { reset(); return; }
      const t = e.touches[0];
      const dx = t.clientX - start.x, dy = t.clientY - start.y;
      if (!horizontal && Math.max(Math.abs(dx), Math.abs(dy)) < LOCK_PX) return;
      if (Math.abs(dy) >= Math.abs(dx)) { reset(); return; } // a scroll, now or from here: not ours
      horizontal = true;
      slide(sign * dx > 0 ? dx : 0);
    };
    const onEnd = (e: TouchEvent) => {
      if (!start) return;
      const t = e.changedTouches[0];
      const hit = t && swipeDirection(t.clientX - start.x, t.clientY - start.y, e.timeStamp - start.t) === dir;
      reset();
      if (hit) onSwipeRef.current();
    };
    // The browser scrolled what the finger is on (it took the touch as a pan): not ours.
    const onScroll = (e: Event) => {
      const s = e.target;
      if (start && (s === document || (s instanceof Node && from && s.contains(from)))) reset();
    };
    const opts = { passive: true } as const;
    document.addEventListener("scroll", onScroll, { capture: true, passive: true });
    root.addEventListener("touchstart", onStart as EventListener, opts);
    root.addEventListener("touchmove", onMove as EventListener, opts);
    root.addEventListener("touchend", onEnd as EventListener, opts);
    root.addEventListener("touchcancel", reset, opts);
    return () => {
      reset();
      document.removeEventListener("scroll", onScroll, { capture: true });
      root.removeEventListener("touchstart", onStart as EventListener);
      root.removeEventListener("touchmove", onMove as EventListener);
      root.removeEventListener("touchend", onEnd as EventListener);
      root.removeEventListener("touchcancel", reset);
    };
  }, [enabled, target, dir, follow, edgeGuard, ignoreWhile]);
}
