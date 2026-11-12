"use client";

/** The house popover menu, moved out of `settings/EmployeesTab` (ticket 30) when the Organization Chart reused it. */

import {
  type KeyboardEvent as ReactKeyboardEvent, type MouseEvent as ReactMouseEvent, type ReactNode, useEffect,
  useLayoutEffect, useRef, useState,
} from "react";

import { useExitGhost } from "@/hooks/useExitGhost";

import { Button } from "@/components/ui/primitives";
import { cn } from "@/lib/utils";

export type MenuItem = {
  label: ReactNode;
  /** React key when `label` is not a string. */
  key?: string;
  onClick?: () => void;
  disabled?: boolean;
  title?: string;
  /** Red text (Delete). */
  danger?: boolean;
};

/** What a custom `trigger` spreads onto its button. */
export type MenuTriggerProps = {
  "aria-haspopup": "menu";
  "aria-expanded": boolean;
  disabled: boolean;
  onClick: (e: ReactMouseEvent<HTMLElement>) => void;
};

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
    const esc = (ev: KeyboardEvent) => {
      if (ev.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", esc);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", esc);
    };
  }, [open]);
  return { open, setOpen, ref };
}

/**
 * A menu's keyboard, on its wrapper: ArrowDown / ArrowUp move between the enabled `menuitem`s (wrapping), Escape
 * calls `close` (which closes and puts focus back on the trigger, as a pick does).
 */
export function menuKeys(e: ReactKeyboardEvent<HTMLElement>, close: () => void) {
  if (e.key === "Escape") {
    e.preventDefault();
    e.stopPropagation();
    close();
    return;
  }
  if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
  const items = Array.from(e.currentTarget.querySelectorAll<HTMLElement>("[role='menuitem']:not([disabled])"));
  if (!items.length) return;
  e.preventDefault();
  const at = items.indexOf(document.activeElement as HTMLElement);
  const by = e.key === "ArrowDown" ? 1 : -1;
  const next = at < 0 ? (by > 0 ? 0 : items.length - 1) : (at + by + items.length) % items.length;
  items[next].focus();
}

/** A trigger and its popover menu: Manage employees' row "More" (`link`, right-aligned) and "Batch actions", and
 *  the Organization Chart's ⋮ (`ariaLabel` names a trigger whose `label` is only a glyph). Closes on an outside
 *  click, on picking an item, and when the trigger turns off. It pops from the trigger's corner and fades out on
 *  a copy that takes no click (`useExitGhost`). Also every row ⋯ (Auto Post / Mass phone rows, the links lists,
 *  the Scripts sidebar, Auto Story's header), each drawing its own `trigger`. Arrows move between items; a pick or
 *  Escape puts focus back on the trigger. */
export function Menu({
  label, ariaLabel, items, disabled = false, link = false, align, trigger, menuLabel, panelClassName, itemClassName,
  position = "below",
}: {
  /** Text, or an icon (the Vault rail's 20px row menu) with `ariaLabel` naming it. */
  label?: ReactNode;
  ariaLabel?: string;
  items: MenuItem[];
  disabled?: boolean;
  link?: boolean;
  /** Which trigger edge the popover lines up with; default right for `link`, left otherwise (Auto Funnel's phone
   *  row ⋯ sits at the row's right edge). */
  align?: "left" | "right";
  /** A caller-drawn trigger (row ⋯ icons, Auto Story's IfButton) instead of `label`'s button; spread the props. */
  trigger?: (p: MenuTriggerProps) => ReactNode;
  /** The menu's accessible name. */
  menuLabel?: string;
  /** Merged over the panel (width, z-index, a page's own dropdown look). */
  panelClassName?: string;
  /** Merged over each item (size, layout, a page's own hover). */
  itemClassName?: string;
  /** `flip` opens upward when it would hang past the page body (main clips) or the viewport (the last table rows);
   *  `fixed` overlays the viewport under the trigger, above a scrolling table's sticky cells. */
  position?: "below" | "flip" | "fixed";
}) {
  const { open, setOpen, ref } = useOutsideClose();
  if (open && disabled) setOpen(false);
  const panelRef = useRef<HTMLDivElement>(null);
  useExitGhost(open, panelRef);
  const [up, setUp] = useState(false);
  const [at, setAt] = useState<{ top: number; right: number } | null>(null);

  // `flip`: measured below first, turned upward before paint if it overhangs.
  useLayoutEffect(() => {
    if (!open || position !== "flip" || !panelRef.current) return;
    const floor = Math.min(window.innerHeight, ref.current?.closest("main")?.getBoundingClientRect().bottom ?? Infinity);
    if (panelRef.current.getBoundingClientRect().bottom > floor) setUp(true);
  }, [open, position, ref]);

  const toggle = (e: ReactMouseEvent<HTMLElement>) => {
    if (!open) {
      setUp(false);
      const r = e.currentTarget.getBoundingClientRect();
      if (position === "fixed") setAt({ top: r.bottom + 4, right: Math.max(8, window.innerWidth - r.right) });
    }
    setOpen((o) => !o);
  };
  /** Closes and puts focus back on the trigger (a pick, Escape). */
  const close = () => {
    setOpen(false);
    ref.current?.querySelector<HTMLElement>("[aria-haspopup]")?.focus();
  };
  const right = (align ?? (link ? "right" : "left")) === "right";
  return (
    <div ref={ref} className="relative inline-block text-left" onKeyDown={(e) => open && menuKeys(e, close)}>
      {trigger ? trigger({ "aria-haspopup": "menu", "aria-expanded": open, disabled, onClick: toggle }) : link ? (
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
      {open && (position !== "fixed" || at) && (
        <div ref={panelRef} role="menu" aria-label={menuLabel}
          style={position === "fixed" && at ? { top: at.top, right: at.right } : undefined}
          className={cn(MENU_PANEL, link ? "w-32" : "w-40",
            right ? "right-0 origin-top-right" : "left-0 origin-top-left",
            up && cn("bottom-full mb-1 mt-0", right ? "origin-bottom-right" : "origin-bottom-left"),
            position === "fixed" && "fixed z-50 mt-0",
            panelClassName)}>
          {items.map((item) => (
            <button
              key={item.key ?? String(item.label)}
              type="button"
              role="menuitem"
              disabled={item.disabled}
              title={item.title}
              onClick={() => {
                close();
                item.onClick?.();
              }}
              className={cn(
                MENU_ITEM,
                !item.disabled && "hover:bg-bg-elev-1",
                itemClassName,
                item.danger && "text-err",
                item.disabled && "text-fg-dim cursor-not-allowed",
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
