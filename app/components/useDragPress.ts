"use client";

/**
 * useDragPress — a press that is a drag only once the pointer has moved past a
 * few px of slop (more for a finger, whose tap jitters), and a tap otherwise.
 * Only the pointer that pressed is tracked: a second finger never moves it. Shared by the MoneyRail header
 * (useRailDock) and the phone help launcher (AssistantWidget).
 *
 * The click a drag fires on release must not also act as a tap: the caller's
 * onClick asks `swallowClick()` first and returns when it is true.
 *
 * Tracked on WINDOW listeners, never with setPointerCapture: capturing the
 * pointer also retargets the compatibility mouse events, so the `click` would
 * land on the capturing element instead of the button under the cursor, which
 * silently kills every button inside it (the rail's header bar).
 *
 * The handlers are read at press time; they should close over refs and
 * `dispatch`, not render state.
 */

import { useRef } from "react";

/** Pointer slop before a press counts as a drag and not a click: a mouse or
 *  pen, and a finger (a tap moves a few px on its own). */
export const DRAG_THRESHOLD_PX = 4;
export const TOUCH_DRAG_THRESHOLD_PX = 10;

/** The slop for one press's pointer type. */
export function dragThreshold(pointerType: string): number {
  return pointerType === "touch" ? TOUCH_DRAG_THRESHOLD_PX : DRAG_THRESHOLD_PX;
}

export interface DragPress<O> {
  /** Pointer down: what the drag moves from, or null to ignore this press. */
  begin: (e: React.PointerEvent<HTMLElement>) => O | null;
  /** Each move past the slop: the pointer's offset from where it went down. */
  move: (origin: O, dx: number, dy: number) => void;
  /** Release after a drag (never after a tap). */
  drop: (origin: O, dx: number, dy: number) => void;
}

export function useDragPress<O>(h: DragPress<O>) {
  const draggedRef = useRef(false);

  const onPointerDown = (e: React.PointerEvent<HTMLElement>) => {
    if (e.button !== 0) return;
    const origin = h.begin(e);
    if (origin === null) return;
    const { pointerId } = e;
    const startX = e.clientX;
    const startY = e.clientY;
    const slop = dragThreshold(e.pointerType);
    let moved = false;

    const onMove = (ev: PointerEvent) => {
      if (ev.pointerId !== pointerId) return;
      const dx = ev.clientX - startX;
      const dy = ev.clientY - startY;
      if (!moved && Math.hypot(dx, dy) < slop) return;
      moved = true;
      draggedRef.current = true;
      h.move(origin, dx, dy);
    };

    const onUp = (ev: PointerEvent) => {
      if (ev.pointerId !== pointerId) return;
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      window.removeEventListener("pointercancel", onUp);
      if (!moved) return;
      // The click that follows this pointerup (if released over a button)
      // must be swallowed. But a drag released over dead space fires NO click,
      // and a `draggedRef` left armed would eat the user's next real click. A
      // 0ms timer runs after click dispatch but before any later interaction.
      window.setTimeout(() => { draggedRef.current = false; }, 0);
      h.drop(origin, ev.clientX - startX, ev.clientY - startY);
    };

    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
    window.addEventListener("pointercancel", onUp);
  };

  /** True (once) when this click is the tail of a drag: the caller ignores it. */
  const swallowClick = () => {
    if (!draggedRef.current) return false;
    draggedRef.current = false;
    return true;
  };

  return { onPointerDown, swallowClick };
}
