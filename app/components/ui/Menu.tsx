"use client";


import {
  type KeyboardEvent as ReactKeyboardEvent, type MouseEvent as ReactMouseEvent, type ReactNode, useEffect,
  useLayoutEffect, useRef, useState,
} from "react";

import { useExitGhost } from "@/hooks/useExitGhost";

import { Button } from "@/components/ui/primitives";
import { cn } from "@/lib/utils";

export type MenuItem = {
  label: ReactNode;
  key?: string;
  onClick?: () => void;
  disabled?: boolean;
  title?: string;
  danger?: boolean;
};

export type MenuTriggerProps = {
  "aria-haspopup": "menu";
  "aria-expanded": boolean;
  disabled: boolean;
  onClick: (e: ReactMouseEvent<HTMLElement>) => void;
};

export const MENU_PANEL = "pop-menu origin-top absolute z-10 mt-1 rounded-md border border-border bg-bg py-1 shadow-lg";
export const MENU_ITEM = "block w-full px-3 py-1.5 text-left text-xs";

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

export function Menu({
  label, ariaLabel, items, disabled = false, link = false, align, trigger, menuLabel, panelClassName, itemClassName,
  position = "below",
}: {
  label?: ReactNode;
  ariaLabel?: string;
  items: MenuItem[];
  disabled?: boolean;
  link?: boolean;
  align?: "left" | "right";
  trigger?: (p: MenuTriggerProps) => ReactNode;
  menuLabel?: string;
  panelClassName?: string;
  itemClassName?: string;
  position?: "below" | "flip" | "fixed";
}) {
  const { open, setOpen, ref } = useOutsideClose();
  if (open && disabled) setOpen(false);
  const panelRef = useRef<HTMLDivElement>(null);
  useExitGhost(open, panelRef);
  const [up, setUp] = useState(false);
  const [at, setAt] = useState<{ top: number; right: number } | null>(null);

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
