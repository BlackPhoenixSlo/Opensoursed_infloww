"use client";

import { useEffect, useId, useRef, useState } from "react";

/** One Fan List menu's open state and its dismissal, shared by the Fan List
 *  modules' menus (docs/spec/phase-02-fan-list-pane.md, Geometry and colour ›
 *  Menus). The menu closes on a pointer-down outside `ref` and on Escape.
 *  Put `ref` on the element holding both the trigger and the menu, so a
 *  press on the trigger toggles rather than closes and reopens. Spread
 *  `triggerProps` on the toggle button and `menuProps` on the menu. */
export function useFanListMenu<T extends HTMLElement>() {
  const [open, setOpen] = useState(false);
  const ref = useRef<T | null>(null);
  useEffect(() => {
    if (!open) return;
    const onClick = (e: MouseEvent) => {
      if (!ref.current?.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    // pointerdown (not mousedown): iOS only synthesises mousedown for taps on
    // clickable nodes, so tapping the panel background never dismissed this.
    // pointerdown precedes mousedown for mouse input → desktop unchanged.
    document.addEventListener("pointerdown", onClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);
  const id = useId();
  return {
    open,
    setOpen,
    ref,
    triggerProps: {
      onClick: () => setOpen((v) => !v),
      "aria-expanded": open,
      "aria-controls": open ? id : undefined,
    },
    menuProps: { id },
  };
}
