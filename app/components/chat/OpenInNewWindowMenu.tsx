"use client";

/**
 * OpenInNewWindowMenu — wraps its child, and a right-click on it opens a
 * one-item menu, "Open in a new window", which opens `href` as a separate
 * window, with the size left to the browser (docs/spec/phase-02-fan-list-pane.md,
 * Interfaces; story 38; docs/spec/phase-01-window-chrome-tabs.md, Contracts).
 * It is a `.pop` menu (`MP.menu`) with the shared Fan List menu's dismissal.
 * Fan List rows, Creator tabs and Fan tabs use it.
 *
 * The wrapper draws no box (`contents`), so the child stays the item its
 * row or strip lays out. The menu is pinned to the viewport under the
 * child's bottom-left corner, so a tab strip's sideways scroller cannot clip
 * it. As a native context menu does, it closes on any scroll or a resize, so
 * it never drifts off the row or tab it was opened on.
 */

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
    // Capture: a scroll does not bubble, so a scrolling list or strip is
    // only heard on its way down.
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
        // The wrapper draws no box, so the child is what is measured.
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
