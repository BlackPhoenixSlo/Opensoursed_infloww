"use client";

import { useEffect, useRef, type RefObject } from "react";

import { LG } from "@/hooks/useIsDesktop";
import { notInGhost, SWIPED_ATTR } from "@/hooks/layerMarks";
import { prefersReducedMotion } from "@/hooks/prefersReducedMotion";
import {
  backdropOpacity, fingerDown, initialGesture, settlePlan, swipeReducer, SWIPE_DISMISS_AT,
  type GestureAction, type GestureEffect, type SwipeDir,
} from "@/hooks/swipeGesture";

export type { SwipeDir } from "@/hooks/swipeGesture";

/**
 * A one-finger horizontal swipe on a phone (`onSwipe`), or with `sheet` a
 * panel the finger drags off. Dependency-free: passive touch listeners, so
 * scrolling is never blocked and a mouse never triggers it.
 *
 * It fires only below lg (where those overlays exist), for a mostly-horizontal
 * move (`swipeDirection`) that did not start in a text field, a `data-no-swipe`
 * element or a horizontal scroller (`startsInIgnored`). A `touchcancel` (the
 * platform took the gesture: iOS edge-back, a system gesture) aborts it, so the
 * browser's own action and ours never both run. `edgeGuard` also drops a touch
 * that starts within that many px of either side, the OS's own back/forward
 * zone, and `ignoreWhile` one made while that selector matches (an open
 * dialog: `OPEN_DIALOG`). A gesture that turns vertical (the finger's whole move
 * from its start becomes mostly vertical) or scrolls what it started in is not a
 * swipe for the rest of that touch, even if it ends sideways. Back/forward is
 * left to the platform: Messages Pro gives it a history entry instead
 * (`useChatBackEntry`).
 *
 * `sheet` makes it an iOS-style sheet gesture: `sheet.panel` tracks the finger
 * 1:1 toward dismissal and rubber-bands (`rubberBand`) the other way. Once a
 * touch locks sideways (within 30° of horizontal) it stays the sheet's until
 * the finger lifts: a diagonal drag, or an inner list the browser scrolls
 * along with it, does not let go of the panel. On release `releaseDismisses`
 * projects where the throw would coast to (the last ~100ms of velocity,
 * `projectRelease`) and dismisses at `dismissAt` of its width, or on a quick
 * flick, while a flick back always cancels. It then settles on a spring
 * (`springKeyframes`) from where and how fast the finger left it. A dismissal
 * stops taking taps the moment it is decided: the panel and its backdrop, and
 * a modal Radix layer's hold on `<body>`, so a tap during the slide lands on
 * the page under it; `sheet.onLetGo` tells the owner then (one holding a modal
 * layer can close it now, keeping the panel mounted for its slide). It calls
 * `onSwipe` once, as soon as the panel is fully off screen, at most
 * `DISMISS_MS` after the release. A new touch catches a panel springing back
 * (or still sliding in) where it is, its backdrop at the opacity it shows.
 * `sheet.backdrop` fades with the panel. A panel with no width (not shown) takes no sheet gesture. Under
 * prefers-reduced-motion nothing moves and the plain `swipeDirection` rule
 * decides, as before.
 *
 * The gesture's state and rules are `swipeReducer` (swipeGesture.ts); this
 * hook only listens, measures and paints.
 */

/** iOS's edge-back zone is ~20px, Android's back gesture about as wide. */
export const OS_EDGE_PX = 24;
const DIALOGS = "[role='dialog'], [aria-modal='true']";
/** An open dialog, for `ignoreWhile`; never a leaving copy (`useExitGhost`), which
 *  keeps the dialog's role for its last ~260ms. */
export const OPEN_DIALOG = notInGhost(DIALOGS);
const IGNORE = "input, textarea, select, [contenteditable=''], [contenteditable='true'], [data-no-swipe]";

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
  /** Called once per decided swipe. */
  onSwipe: () => void;
  /** The panel that follows the finger; `backdrop` behind it fades with its
   *  progress; `onLetGo`: a dismissal is decided (the panel slides off, taking
   *  no tap), `onSwipe` follows. */
  sheet?: { panel: RefObject<HTMLElement | null>; backdrop?: RefObject<HTMLElement | null>; onLetGo?: () => void };
  /** With `sheet`: the share of its width a projected release must reach to dismiss. */
  dismissAt?: number;
  /** Ignore a touch starting within this many px of the left or right side. */
  edgeGuard?: number;
  /** Ignore a touch made while something matches this selector. */
  ignoreWhile?: string;
}

/** Listen on `target`'s element, or on the whole document when `target` is null. */
export function useSwipe(target: RefObject<HTMLElement | null> | null, {
  enabled, dir, onSwipe, sheet, dismissAt = SWIPE_DISMISS_AT, edgeGuard = 0, ignoreWhile,
}: SwipeOptions) {
  // The refs, not the `sheet` object (a new one each render), are the effect's dependencies.
  const panelRef = sheet?.panel, backdrop = sheet?.backdrop, onLetGo = sheet?.onLetGo;
  const onSwipeRef = useRef(onSwipe);
  const onLetGoRef = useRef(onLetGo);
  useEffect(() => { onSwipeRef.current = onSwipe; onLetGoRef.current = onLetGo; });

  useEffect(() => {
    if (!enabled) return;
    const root: HTMLElement | Document | null = target ? target.current : document;
    if (!root) return;
    const sign = dir === "right" ? 1 : -1;
    let s = initialGesture(dir, dismissAt);
    // DOM-side: the running settle's animations, and what the finger started on (for `scroll`).
    let anims: Animation[] = [];
    let from: Node | null = null;

    const panel = () => panelRef?.current ?? null;
    const shift = (p: number) => `translateX(${sign * p}px)`;
    const paint = (p: number, width: number) => {
      const el = panel();
      if (!el) return;
      el.style.transform = p === 0 ? "" : shift(p);
      const bd = backdrop?.current;
      if (bd) bd.style.opacity = p <= 0 ? "" : String(backdropOpacity(p, width, s.anchor));
    };
    /** A dismissal is decided: from now on the panel and its backdrop take no tap
     *  (they unmount right after, at `onSwipe`, so this is never undone), nor does a
     *  modal Radix layer hold `<body>` (it restores body's own value on unmount):
     *  a tap lands on the page under them. `useExitGhost` makes no copy of them. */
    const letGo = () => {
      const el = panel();
      for (const x of [el, backdrop?.current]) if (x) { x.setAttribute(SWIPED_ATTR, ""); x.style.pointerEvents = "none"; }
      const others = [...document.querySelectorAll(OPEN_DIALOG)].filter((d) => !el?.contains(d));
      if (document.body.style.pointerEvents === "none" && !others.length) document.body.style.pointerEvents = "";
      onLetGoRef.current?.();
    };
    /** The panel's and its backdrop's running animations: this hook's settle, or their CSS slide-in. */
    const running = () => anims.length ? anims
      : [...(panel()?.getAnimations() ?? []), ...(backdrop?.current?.getAnimations() ?? [])].filter((a) => a.playState === "running");
    const apply = (e: GestureEffect) => {
      const el = panel();
      switch (e.type) {
        case "paint": paint(e.pos, e.width); return;
        case "hold": if (el) el.style.willChange = "transform"; return;
        case "rest": anims = []; if (el) el.style.willChange = ""; return;
        case "stop": for (const a of running()) a.cancel(); anims = []; return;
        case "fire": onSwipeRef.current(); return;
        case "settle": {
          if (e.to > 0) letGo();
          const { frames, ms, duration } = settlePlan(e.from, e.to, e.velocity, e.width);
          // Its resting value goes underneath first, so nothing flashes when it ends.
          paint(e.to, e.width);
          if (!el || ms <= 1) { dispatch({ type: "settled", run: e.run }); return; }
          const timing = { duration, easing: "linear" };
          anims = [el.animate(frames.map((f) => ({ transform: shift(f.x), offset: f.t / ms })), timing)];
          const bd = backdrop?.current;
          if (bd) anims.push(bd.animate(frames.map((f) => ({ opacity: backdropOpacity(f.x, e.width, s.anchor), offset: f.t / ms })), timing));
          // Cancelled from outside counts as done (ours, `stop`, meets a gesture that moved on: ignored).
          anims[0].onfinish = anims[0].oncancel = () => dispatch({ type: "settled", run: e.run });
        }
      }
    };
    // One action at a time: one dispatched by an effect (an instant settle) waits for the step before it.
    const queue: GestureAction[] = [];
    const dispatch = (a: GestureAction) => {
      if (queue.push(a) > 1) return;
      try {
        while (queue.length) {
          const step = swipeReducer(s, queue[0]);
          s = step.state;
          step.effects.forEach(apply);
          queue.shift();
        }
      } finally { queue.length = 0; }
    };
    /** Where a panel mid-animation (a settle, or its CSS slide-in) is now, and the
     *  opacity its backdrop shows now; undefined at rest. Reads only. */
    const catchPanel = (el: HTMLElement) => {
      if (!running().length) return undefined;
      const bd = backdrop?.current;
      const tf = getComputedStyle(el).transform;
      const opacity = bd ? parseFloat(getComputedStyle(bd).opacity) : NaN;
      return { pos: tf && tf !== "none" ? sign * new DOMMatrixReadOnly(tf).m41 : 0, opacity };
    };

    const onStart = (e: TouchEvent) => {
      dispatch({ type: "cancel" }); // a finger still down: that touch is over
      if (e.touches.length !== 1 || window.matchMedia(LG).matches) return;
      if (startsInIgnored(e.target, root instanceof Document ? null : root)) return;
      const t = e.touches[0];
      if (t.clientX < edgeGuard || t.clientX > window.innerWidth - edgeGuard) return;
      if (ignoreWhile && document.querySelector(ignoreWhile)) return;
      const el = panel();
      const moves = !!el && !prefersReducedMotion();
      const width = el && moves ? el.offsetWidth : 0;
      if (moves && !width) return; // not shown: no sheet to move
      from = e.target instanceof Node ? e.target : null;
      dispatch({ type: "start", x: t.clientX, y: t.clientY, t: e.timeStamp,
        sheet: el && moves ? { width, caught: catchPanel(el) } : undefined });
    };
    const onMove = (e: TouchEvent) => {
      if (!fingerDown(s)) return;
      if (e.touches.length !== 1) { dispatch({ type: "cancel" }); return; }
      const t = e.touches[0];
      dispatch({ type: "move", x: t.clientX, y: t.clientY, t: e.timeStamp });
    };
    const onEnd = (e: TouchEvent) => {
      const t = e.changedTouches[0];
      dispatch(t ? { type: "end", x: t.clientX, y: t.clientY, t: e.timeStamp } : { type: "cancel" });
    };
    const onCancel = () => dispatch({ type: "cancel" });
    // The browser scrolled what the finger is on (it took the touch as a pan): not ours.
    const onScroll = (e: Event) => {
      const own = e.target === document || (e.target instanceof Node && !!from && e.target.contains(from));
      dispatch({ type: "scroll", own });
    };
    const opts = { passive: true } as const;
    document.addEventListener("scroll", onScroll, { capture: true, passive: true });
    root.addEventListener("touchstart", onStart as EventListener, opts);
    root.addEventListener("touchmove", onMove as EventListener, opts);
    root.addEventListener("touchend", onEnd as EventListener, opts);
    root.addEventListener("touchcancel", onCancel, opts);
    return () => {
      dispatch({ type: "teardown" });
      document.removeEventListener("scroll", onScroll, { capture: true });
      root.removeEventListener("touchstart", onStart as EventListener);
      root.removeEventListener("touchmove", onMove as EventListener);
      root.removeEventListener("touchend", onEnd as EventListener);
      root.removeEventListener("touchcancel", onCancel);
    };
  }, [enabled, target, dir, panelRef, backdrop, dismissAt, edgeGuard, ignoreWhile]);
}
