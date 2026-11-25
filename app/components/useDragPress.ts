"use client";


import { useRef } from "react";

export const DRAG_THRESHOLD_PX = 4;
export const TOUCH_DRAG_THRESHOLD_PX = 10;

export function dragThreshold(pointerType: string): number {
  return pointerType === "touch" ? TOUCH_DRAG_THRESHOLD_PX : DRAG_THRESHOLD_PX;
}

export interface DragPress<O> {
  begin: (e: React.PointerEvent<HTMLElement>) => O | null;
  move: (origin: O, dx: number, dy: number) => void;
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

    // window listeners, never setPointerCapture: capture retargets the click onto the capturing element and kills buttons inside it
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
      // a drag released over dead space fires no click: an armed draggedRef would eat the next real click; 0ms runs after click dispatch
      window.setTimeout(() => { draggedRef.current = false; }, 0);
      h.drop(origin, ev.clientX - startX, ev.clientY - startY);
    };

    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
    window.addEventListener("pointercancel", onUp);
  };

  const swallowClick = () => {
    if (!draggedRef.current) return false;
    draggedRef.current = false;
    return true;
  };

  return { onPointerDown, swallowClick };
}
