"use client";

import { useEffect, useId, useRef, useState } from "react";

export function useFanListMenu<T extends HTMLElement>() {
  const [open, setOpen] = useState(false);
  const ref = useRef<T | null>(null);
  useEffect(() => {
    if (!open) return;
    const onClick = (e: MouseEvent) => {
      if (!ref.current?.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    // pointerdown, not mousedown: iOS only synthesises mousedown for taps on clickable nodes.
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
