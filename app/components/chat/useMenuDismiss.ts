"use client";

import { useEffect, type RefObject } from "react";

/** A Chat header menu's dismissal (spec, Implementation Decisions, Menus):
 *  while `open`, a pointer-down outside `ref` or Escape calls `close`. The
 *  Escape is stopped at `document`, so one Escape closes one layer and Find's
 *  `window` listener (ChatSearch) never hears it. Put `ref` on the element
 *  holding both the trigger and the menu, so a press on the trigger toggles
 *  rather than closes and reopens. A menu with a submenu inside `ref` passes
 *  `escape`, which closes one layer, while an outside pointer-down still calls
 *  `close` (the Kebab menu, ticket 140). */
export function useMenuDismiss(
  ref: RefObject<HTMLElement | null>, open: boolean, close: () => void, escape: () => void = close,
) {
  useEffect(() => {
    if (!open) return;
    const onPointer = (e: PointerEvent) => {
      if (!ref.current?.contains(e.target as Node)) close();
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      e.stopPropagation();
      escape();
    };
    document.addEventListener("pointerdown", onPointer);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onPointer);
      document.removeEventListener("keydown", onKey);
    };
  }, [ref, open, close, escape]);
}
