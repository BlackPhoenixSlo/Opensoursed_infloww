"use client";

import { useEffect, type RefObject } from "react";

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
      const at = document.activeElement;
      if (at?.closest('[aria-modal="true"]') && !ref.current?.contains(at)) return;
      // One Escape closes one layer; Find's window listener must not hear it.
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
