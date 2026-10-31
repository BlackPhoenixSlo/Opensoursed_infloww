"use client";

/** `infloww.tsx`'s modals (re-exported there): `IfModal`, `HbModal`, and the focus / Escape / modal-stack hook they share. */

import { useEffect, useId, useRef, type ReactNode } from "react";
import { X } from "lucide-react";

import { HB_HAIR, HB_TEXT } from "@/components/ui/ifSelect";
import { useExitGhost } from "@/hooks/useExitGhost";
import { cn } from "@/lib/utils";

// ── Modals ──────────────────────────────────────────────────────────────────────────────────────────────────────

const FOCUSABLE = 'a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])';

/** Open modals, top last: only the top one answers Escape and traps Tab. */
const modalStack: object[] = [];

/**
 * The one dialog hook both modal looks share: focus moves into the box (unless a child already took it with
 * `autoFocus`), Tab and Shift+Tab cycle inside it, Escape closes when `keyboard`, and focus returns to the opener.
 */
function useModalFocus(onClose: () => void, keyboard: boolean) {
  const boxRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef(onClose);
  const keyboardRef = useRef(keyboard);
  useEffect(() => {
    closeRef.current = onClose;
    keyboardRef.current = keyboard;
  });
  useEffect(() => {
    const token = {};
    modalStack.push(token);
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const box = boxRef.current;
    if (box && !box.contains(document.activeElement)) box.focus();
    const onKey = (e: KeyboardEvent) => {
      if (modalStack[modalStack.length - 1] !== token || !box) return;
      if (e.key === "Escape" && keyboardRef.current) {
        e.preventDefault();
        closeRef.current();
      } else if (e.key === "Tab") {
        const items = Array.from(box.querySelectorAll<HTMLElement>(FOCUSABLE));
        if (!items.length) { e.preventDefault(); box.focus(); return; }
        const first = items[0];
        const last = items[items.length - 1];
        const at = document.activeElement;
        if (e.shiftKey && (at === first || at === box)) { e.preventDefault(); last.focus(); }
        else if (!e.shiftKey && (at === last || !box.contains(at))) { e.preventDefault(); first.focus(); }
      }
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      modalStack.splice(modalStack.indexOf(token), 1);
      if (opener?.isConnected) opener.focus();
    };
  }, []);
  return boxRef;
}

type ModalProps = {
  title?: ReactNode;
  /** The dialog's accessible name when it draws no `title`. */
  label?: string;
  width?: number;
  footer?: ReactNode;
  onClose: () => void;
  /** Draws the × (Infloww's `closable`); Escape too unless `keyboard` says otherwise. */
  closable?: boolean;
  /** Escape closes (antd's `keyboard`); defaults to `closable`. `closable={false} keyboard` is a modal with no × that
   *  Escape still closes (Delete proxy). */
  keyboard?: boolean;
  children?: ReactNode;
  className?: string;
};

const widthStyle = (width: number) => ({ width: `min(${width}px, calc(100vw - 32px))` });

/** Both modals' mask: it pops in (the mask fades, the box scales from 0.96, globals.css `pop-*`) and leaves on a copy
 *  that takes no click (`useExitGhost`), so closing never holds up the page. */
function ModalMask({ children }: { children: ReactNode }) {
  const maskRef = useRef<HTMLDivElement>(null);
  useExitGhost(true, maskRef);
  return (
    <div ref={maskRef} className="pop-backdrop fixed inset-0 z-50 grid place-items-center overflow-y-auto bg-black/70 p-4">
      {children}
    </div>
  );
}

/** antd's modal: a 70% black mask; the box `colorBgElevated` #1f1f1f, radius 10, no border; header `22px 24px 0`
 *  (16 / 600 T1), body 24px, footer right with 8px between buttons; the 16px T3 × 16px in from the top right. */
export function IfModal({ title, label, width = 520, footer, onClose, closable = true, keyboard = closable, children, className }: ModalProps) {
  const boxRef = useModalFocus(onClose, keyboard);
  const titleId = useId();
  return (
    <ModalMask>
      <div
        ref={boxRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={title ? titleId : undefined}
        aria-label={title ? undefined : label}
        tabIndex={-1}
        style={widthStyle(width)}
        className={cn("pop-modal relative flex max-h-[calc(100vh-32px)] flex-col rounded-[10px] bg-[#1f1f1f] outline-none shadow-2xl",
          "[html[data-theme=light]_&]:bg-white", className)}
      >
        {closable && (
          <button type="button" aria-label="Close" onClick={onClose}
            className="absolute right-4 top-4 grid h-6 w-6 place-items-center rounded text-muted hover:text-fg">
            <X className="h-4 w-4" aria-hidden />
          </button>
        )}
        {title && (
          <h2 id={titleId} className={cn("px-6 pt-[22px] text-[16px] font-semibold text-fg", closable && "pr-12")}>{title}</h2>
        )}
        <div className="min-h-0 flex-1 overflow-y-auto p-6 text-[14px] text-fg">{children}</div>
        {footer && <div className="flex items-center justify-end gap-2 px-6 pb-5">{footer}</div>}
      </div>
    </ModalMask>
  );
}

/** HB's modal (`.hb-design-modal-content`): #171717 with a 1px 9%-white border, radius 12, `padding:12px 16px`, at
 *  least 480 wide and at most 80vh tall; the title 24px / 500 white over a hairline (`padding:0 16px 12px`), the body
 *  16px / 1.25 at 62% white, the footer over a hairline (`padding:12px 16px 0`) with its buttons right, 12px apart. */
export function HbModal({ title, width = 600, footer, onClose, closable = true, keyboard = closable, children, className }: ModalProps) {
  const boxRef = useModalFocus(onClose, keyboard);
  const titleId = useId();
  return (
    <ModalMask>
      <div
        ref={boxRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={title ? titleId : undefined}
        tabIndex={-1}
        style={{ ...widthStyle(width), minWidth: "min(480px, calc(100vw - 32px))" }}
        className={cn("pop-modal flex max-h-[80vh] flex-col rounded-[12px] border bg-panel px-4 py-3 outline-none shadow-2xl", HB_HAIR, className)}
      >
        {(title || closable) && (
          <div className={cn("flex items-center justify-between gap-3 border-b px-4 pb-3", HB_HAIR)}>
            <h2 id={titleId} className={cn("text-[24px] font-medium", HB_TEXT)}>{title}</h2>
            {closable && (
              <button type="button" aria-label="Close" onClick={onClose}
                className={cn("grid h-7 w-7 shrink-0 place-items-center rounded-[4px] hover:opacity-80", HB_TEXT)}>
                <X className="h-5 w-5" aria-hidden />
              </button>
            )}
          </div>
        )}
        <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4 text-[16px] leading-[1.25] text-white/[.62] [html[data-theme=light]_&]:text-black/[.62]">
          {children}
        </div>
        {footer && <div className={cn("flex items-center justify-end gap-3 border-t px-4 pt-3", HB_HAIR)}>{footer}</div>}
      </div>
    </ModalMask>
  );
}
