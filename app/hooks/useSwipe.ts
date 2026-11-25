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


// iOS edge-back zone is ~20px, Android's about as wide.
export const OS_EDGE_PX = 24;
const DIALOGS = "[role='dialog'], [aria-modal='true']";
export const OPEN_DIALOG = notInGhost(DIALOGS);
const IGNORE = "input, textarea, select, [contenteditable=''], [contenteditable='true'], [data-no-swipe]";

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
  sheet?: { panel: RefObject<HTMLElement | null>; backdrop?: RefObject<HTMLElement | null>; onLetGo?: () => void };
  dismissAt?: number;
  edgeGuard?: number;
  ignoreWhile?: string;
}

export function useSwipe(target: RefObject<HTMLElement | null> | null, {
  enabled, dir, onSwipe, sheet, dismissAt = SWIPE_DISMISS_AT, edgeGuard = 0, ignoreWhile,
}: SwipeOptions) {
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
    const letGo = () => {
      const el = panel();
      for (const x of [el, backdrop?.current]) if (x) { x.setAttribute(SWIPED_ATTR, ""); x.style.pointerEvents = "none"; }
      const others = [...document.querySelectorAll(OPEN_DIALOG)].filter((d) => !el?.contains(d));
      if (document.body.style.pointerEvents === "none" && !others.length) document.body.style.pointerEvents = "";
      onLetGoRef.current?.();
    };
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
          paint(e.to, e.width);
          if (!el || ms <= 1) { dispatch({ type: "settled", run: e.run }); return; }
          const timing = { duration, easing: "linear" };
          anims = [el.animate(frames.map((f) => ({ transform: shift(f.x), offset: f.t / ms })), timing)];
          const bd = backdrop?.current;
          if (bd) anims.push(bd.animate(frames.map((f) => ({ opacity: backdropOpacity(f.x, e.width, s.anchor), offset: f.t / ms })), timing));
          anims[0].onfinish = anims[0].oncancel = () => dispatch({ type: "settled", run: e.run });
        }
      }
    };
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
    const catchPanel = (el: HTMLElement) => {
      if (!running().length) return undefined;
      const bd = backdrop?.current;
      const tf = getComputedStyle(el).transform;
      const opacity = bd ? parseFloat(getComputedStyle(bd).opacity) : NaN;
      return { pos: tf && tf !== "none" ? sign * new DOMMatrixReadOnly(tf).m41 : 0, opacity };
    };

    const onStart = (e: TouchEvent) => {
      dispatch({ type: "cancel" });
      if (e.touches.length !== 1 || window.matchMedia(LG).matches) return;
      if (startsInIgnored(e.target, root instanceof Document ? null : root)) return;
      const t = e.touches[0];
      if (t.clientX < edgeGuard || t.clientX > window.innerWidth - edgeGuard) return;
      if (ignoreWhile && document.querySelector(ignoreWhile)) return;
      const el = panel();
      const moves = !!el && !prefersReducedMotion();
      const width = el && moves ? el.offsetWidth : 0;
      if (moves && !width) return;
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
