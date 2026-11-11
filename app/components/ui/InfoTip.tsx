"use client";

/**
 * The ⓘ that explains the thing next to it: a styled tooltip that opens at once on hover or keyboard focus and on a
 * tap (phones have no hover), above the icon (below when the viewport has no room), clamped to the viewport. It
 * renders in a portal, so a card's `overflow` never clips it. Escape, a tap elsewhere, blur or the pointer leaving
 * close it. Replaces the native `title`, which waits ~1s, is unstyled and never shows on touch.
 */

import { useEffect, useId, useLayoutEffect, useRef, useState, type HTMLAttributes, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { Info } from "lucide-react";

import { cn } from "@/lib/utils";

const GAP = 6;
const EDGE = 8;

/** Where the tip sits: above the trigger, centred, unless it would leave the viewport. */
export function placeTip(
  trigger: Pick<DOMRect, "top" | "bottom" | "left" | "width">,
  tip: Pick<DOMRect, "width" | "height">,
  viewportWidth: number,
): { left: number; top: number } {
  const above = trigger.top - GAP - tip.height;
  const top = above >= EDGE ? above : trigger.bottom + GAP;
  const centred = trigger.left + trigger.width / 2 - tip.width / 2;
  const left = Math.max(EDGE, Math.min(centred, viewportWidth - EDGE - tip.width));
  return { left, top };
}

export function InfoTip({
  text, label, icon, iconClassName = "h-3.5 w-3.5", className, ...rest
}: Omit<HTMLAttributes<HTMLSpanElement>, "children" | "title"> & {
  /** The explanation shown in the tip. */
  text: string;
  /** The icon's accessible name; defaults to `text`. */
  label?: string;
  /** Another glyph than lucide's `Info`. */
  icon?: ReactNode;
  iconClassName?: string;
}) {
  const [open, setOpen] = useState(false);
  const trigger = useRef<HTMLSpanElement>(null);
  const tip = useRef<HTMLDivElement>(null);
  const id = useId();

  // Measured before paint, so the tip never flashes at 0,0; it renders hidden until placed.
  useLayoutEffect(() => {
    const el = tip.current;
    const t = trigger.current?.getBoundingClientRect();
    if (!open || !el || !t) return;
    const { left, top } = placeTip(t, el.getBoundingClientRect(), window.innerWidth);
    Object.assign(el.style, { left: `${left}px`, top: `${top}px`, visibility: "visible" });
  }, [open, text]);

  useEffect(() => {
    if (!open) return;
    const close = () => setOpen(false);
    const outside = (e: PointerEvent) => { if (!trigger.current?.contains(e.target as Node)) close(); };
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") close(); };
    document.addEventListener("pointerdown", outside);
    document.addEventListener("keydown", esc);
    window.addEventListener("scroll", close, true);
    window.addEventListener("resize", close);
    return () => {
      document.removeEventListener("pointerdown", outside);
      document.removeEventListener("keydown", esc);
      window.removeEventListener("scroll", close, true);
      window.removeEventListener("resize", close);
    };
  }, [open]);

  return (
    <span
      ref={trigger}
      role="img"
      aria-label={label ?? text}
      aria-describedby={open ? id : undefined}
      tabIndex={0}
      data-info-tip=""
      {...rest}
      className={cn("inline-flex shrink-0 cursor-help items-center rounded-full outline-none focus-visible:ring-2 focus-visible:ring-accent/40", className)}
      onPointerEnter={(e) => { if (e.pointerType !== "touch") setOpen(true); }}
      onPointerLeave={(e) => { if (e.pointerType !== "touch") setOpen(false); }}
      onFocus={() => setOpen(true)}
      onBlur={() => setOpen(false)}
      onClick={() => setOpen(true)}
    >
      {icon ?? <Info className={iconClassName} aria-hidden />}
      {open && createPortal(
        <div
          ref={tip}
          id={id}
          role="tooltip"
          style={{ left: 0, top: 0, visibility: "hidden" }}
          className="pointer-events-none fixed z-[2000] max-w-[min(280px,calc(100vw-16px))] whitespace-normal break-words rounded-md bg-[#424242] px-2.5 py-1.5 text-left text-[12px] font-normal leading-[18px] text-white shadow-lg"
        >
          {text}
        </div>,
        document.body,
      )}
    </span>
  );
}
