"use client";

/** The house popover menu, moved out of `settings/EmployeesTab` (ticket 30) when the Organization Chart reused it. */

import { type ReactNode, useEffect, useRef, useState } from "react";

import { useExitGhost } from "@/hooks/useExitGhost";

import { Button } from "@/components/ui/primitives";
import { cn } from "@/lib/utils";

export type MenuItem = { label: string; onClick?: () => void; disabled?: boolean; title?: string };

/** The popover box and an item's base classes, shared with popovers that need more than `Menu`'s items (the Vault
 *  folder rail's sort popover, with radio items and separators). It pops in from its top edge (`pop-menu`,
 *  globals.css); a popover anchored in a corner sets that corner's `origin-*`. */
export const MENU_PANEL = "pop-menu origin-top absolute z-10 mt-1 rounded-md border border-border bg-bg py-1 shadow-lg";
export const MENU_ITEM = "block w-full px-3 py-1.5 text-left text-xs";

/** An open flag that closes on a mousedown outside the returned ref's element. */
export function useOutsideClose<T extends HTMLElement = HTMLDivElement>() {
  const [open, setOpen] = useState(false);
  const ref = useRef<T>(null);
  useEffect(() => {
    if (!open) return;
    const close = (ev: MouseEvent) => {
      if (!ref.current?.contains(ev.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open]);
  return { open, setOpen, ref };
}

/** A trigger and its popover menu: Manage employees' row "More" (`link`, right-aligned) and "Batch actions", and
 *  the Organization Chart's ⋮ (`ariaLabel` names a trigger whose `label` is only a glyph). Closes on an outside
 *  click, on picking an item, and when the trigger turns off. It pops from the trigger's corner and fades out on
 *  a copy that takes no click (`useExitGhost`). */
export function Menu({ label, ariaLabel, items, disabled = false, link = false }: {
  /** Text, or an icon (the Vault rail's 20px row menu) with `ariaLabel` naming it. */
  label: ReactNode;
  ariaLabel?: string;
  items: MenuItem[];
  disabled?: boolean;
  link?: boolean;
}) {
  const { open, setOpen, ref } = useOutsideClose();
  if (open && disabled) setOpen(false);
  const panelRef = useRef<HTMLDivElement>(null);
  useExitGhost(open, panelRef);

  const toggle = () => setOpen((o) => !o);
  return (
    <div ref={ref} className="relative inline-block text-left">
      {link ? (
        <button type="button" aria-label={ariaLabel} aria-haspopup="menu" aria-expanded={open} disabled={disabled}
          onClick={toggle} className="text-[11px] text-fg-dim hover:text-fg underline underline-offset-2">
          {label}
        </button>
      ) : (
        <Button size="sm" variant="ghost" type="button" aria-label={ariaLabel} aria-haspopup="menu" aria-expanded={open}
          disabled={disabled}
          onClick={toggle}>
          {label}
        </Button>
      )}
      {open && (
        <div ref={panelRef} role="menu" className={cn(MENU_PANEL, link ? "right-0 w-32 origin-top-right" : "left-0 w-40 origin-top-left")}>
          {items.map((item) => (
            <button
              key={item.label}
              type="button"
              role="menuitem"
              disabled={item.disabled}
              title={item.title}
              onClick={() => {
                setOpen(false);
                item.onClick?.();
              }}
              className={cn(
                MENU_ITEM,
                item.disabled ? "text-fg-dim cursor-not-allowed" : "hover:bg-bg-elev-1",
              )}
            >
              {item.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
