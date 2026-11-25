"use client";


import { useEffect, useState, type ReactNode } from "react";

import { MP } from "@/lib/messagesPro";
import { cn } from "@/lib/utils";
import { MENU_ITEM, MENU_PANEL } from "./MenuParts";
import { useFanListMenu } from "./useFanListMenu";

export function OpenInNewWindowMenu({ href, children }: { href: string; children: ReactNode }) {
  const { open, setOpen, ref, menuProps } = useFanListMenu<HTMLDivElement>();
  const [at, setAt] = useState({ top: 0, left: 0 });
  useEffect(() => {
    if (!open) return;
    const close = () => setOpen(false);
    // Capture: scroll does not bubble.
    window.addEventListener("scroll", close, true);
    window.addEventListener("resize", close);
    return () => {
      window.removeEventListener("scroll", close, true);
      window.removeEventListener("resize", close);
    };
  }, [open, setOpen]);
  return (
    <div
      ref={ref}
      className="contents"
      onContextMenu={(e) => {
        e.preventDefault();
        const child = e.currentTarget.firstElementChild;
        if (!child) throw new Error("OpenInNewWindowMenu: no child element to place the menu under");
        const box = child.getBoundingClientRect();
        setAt({ top: box.bottom, left: box.left });
        setOpen(true);
      }}
    >
      {children}
      {open && (
        <section
          {...menuProps}
          aria-label="Context menu"
          style={at}
          className={cn(MENU_PANEL, MP.ours.OpenInNewWindowMenu.place, "fixed")}
        >
          <button
            type="button"
            onClick={() => {
              setOpen(false);
              window.open(href, "_blank", "popup");
            }}
            className={MENU_ITEM}
          >
            Open in a new window
          </button>
        </section>
      )}
    </div>
  );
}
