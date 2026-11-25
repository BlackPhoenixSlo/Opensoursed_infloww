"use client";


import {
  createContext, useCallback, useContext, useEffect, useId, useLayoutEffect, useRef, useState, type ReactNode, type RefObject,
} from "react";
import { createPortal } from "react-dom";
import { X } from "lucide-react";

import { HB_HAIR, HB_TEXT } from "@/components/ui/ifSelect";
import { useExitGhost } from "@/hooks/useExitGhost";
import { cn } from "@/lib/utils";


const FOCUSABLE = 'a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])';

function bodyChild(el: Element): Element | null {
  let n: Element | null = el;
  while (n && n.parentElement !== document.body) n = n.parentElement;
  return n;
}

function inPortalAbove(box: HTMLElement, at: Element): boolean {
  const a = bodyChild(at);
  const b = bodyChild(box);
  return !!a && !!b && a !== b && !!(b.compareDocumentPosition(a) & Node.DOCUMENT_POSITION_FOLLOWING);
}

type Layer = { el: () => HTMLElement | null };
const layers: Layer[] = [];
const leaving = new Set<HTMLElement>();

const elOf = (l: Layer) => l.el() as HTMLElement;
const liveLayers = () => layers.filter((l) => l.el()?.isConnected);

function topOf(list: Layer[]): Layer | null {
  let top: Layer | null = null;
  for (const l of list) {
    if (!top || elOf(top).compareDocumentPosition(elOf(l)) & Node.DOCUMENT_POSITION_FOLLOWING) top = l;
  }
  return top;
}

function useLayer(layer: Layer, onLeave: (wasTop: boolean, survivors: Layer[]) => void) {
  const leaveRef = useRef(onLeave);
  useLayoutEffect(() => {
    leaveRef.current = onLeave;
  });
  useLayoutEffect(() => {
    layers.push(layer);
    return () => {
      const el = layer.el();
      const survivors = liveLayers().filter((l) => l !== layer && !(el && el.contains(elOf(l))));
      const wasTop = !!el?.isConnected && topOf([...survivors, layer]) === layer;
      layers.splice(layers.indexOf(layer), 1);
      if (el) {
        leaving.add(el);
        queueMicrotask(() => leaving.delete(el));
      }
      leaveRef.current(wasTop, survivors);
    };
  }, [layer]);
  return useCallback(() => layers.includes(layer) && topOf(liveLayers()) === layer, [layer]);
}

export function useModalFocus<T extends HTMLElement>(ref: RefObject<T | null>, onEscape?: () => void) {
  const escapeRef = useRef(onEscape);
  const [firstOpener] = useState(() => {
    if (typeof document === "undefined" || typeof HTMLElement === "undefined") return null;
    const at = document.activeElement;
    return at instanceof HTMLElement && at !== document.body ? at : null;
  });
  const openerRef = useRef(firstOpener);
  const [layer] = useState<Layer>(() => ({ el: () => ref.current }));
  const isTop = useLayer(layer, (wasTop, survivors) => {
    const opener = openerRef.current;
    const top = topOf(survivors);
    const gone = (n: Node) => [...leaving].some((b) => b.contains(n));
    if (wasTop && opener?.isConnected && !gone(opener) && (!top || elOf(top).contains(opener))) {
      opener.focus();
      return;
    }
    if (!top) return;
    if (wasTop) { elOf(top).focus(); return; }
    const at = document.activeElement;
    if (!at || gone(at) || !survivors.some((l) => elOf(l).contains(at))) elOf(top).focus();
  });
  useEffect(() => {
    escapeRef.current = onEscape;
  });
  useLayoutEffect(() => {
    const box = ref.current;
    const was = document.activeElement;
    if (!openerRef.current?.isConnected && was instanceof HTMLElement && was !== document.body && !box?.contains(was)) {
      openerRef.current = was;
    }
    if (box && !box.contains(document.activeElement)) box.focus();
    const onKey = (e: KeyboardEvent) => {
      if (!box || !isTop()) return;
      const at = document.activeElement;
      if (at && !box.contains(at) && inPortalAbove(box, at)) return;
      if (e.key === "Escape") {
        const escape = escapeRef.current;
        if (!escape || e.defaultPrevented) return;
        e.preventDefault();
        e.stopPropagation();
        escape();
      } else if (e.key === "Tab") {
        // A control in a disabled <fieldset> is `:disabled` with no attribute of its own.
        const items = Array.from(box.querySelectorAll<HTMLElement>(FOCUSABLE)).filter((el) => !el.matches(":disabled"));
        if (!items.length) { e.preventDefault(); box.focus(); return; }
        const first = items[0];
        const last = items[items.length - 1];
        if (e.shiftKey && (at === first || at === box || !box.contains(at))) { e.preventDefault(); last.focus(); }
        else if (!e.shiftKey && (at === last || !box.contains(at))) { e.preventDefault(); first.focus(); }
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [isTop, ref]);
}

type ModalProps = {
  title?: ReactNode;
  label?: string;
  width?: number;
  footer?: ReactNode;
  onClose: () => void;
  closable?: boolean;
  keyboard?: boolean;
  children?: ReactNode;
  className?: string;
};

const FooterSlotContext = createContext<HTMLElement | null | undefined>(undefined);

export function EditorFooter({ children }: { children: ReactNode }) {
  const slot = useContext(FooterSlotContext);
  if (slot === undefined) return <div className="mt-4 flex flex-wrap items-center justify-end gap-3">{children}</div>;
  return slot ? createPortal(children, slot) : null;
}

export const IF_MODAL_MASK = "bg-black/70";
export const IF_MODAL_BOX = "rounded-[10px] bg-[#1f1f1f] text-fg shadow-2xl outline-none [html[data-theme=light]_&]:bg-white";

const widthStyle = (width: number) => ({ width: `min(${width}px, calc(100vw - 32px))` });

function ModalMask({ onMaskClick, children }: { onMaskClick?: () => void; children: ReactNode }) {
  const maskRef = useRef<HTMLDivElement>(null);
  useExitGhost(true, maskRef);
  return (
    <div ref={maskRef} onClick={onMaskClick && ((e) => { if (e.target === e.currentTarget) onMaskClick(); })} className={cn("pop-backdrop fixed inset-x-0 top-[var(--vvt,0px)] z-50 grid h-[var(--vvh,100dvh)] place-items-center overflow-y-auto p-4 max-sm:items-start", IF_MODAL_MASK)}>
      {children}
    </div>
  );
}

export function IfModal({
  title, label, width = 520, size, footer, footerSlot = false, onClose, closable = true, keyboard = closable, children,
  className, maskClosable = false, describedBy,
}: ModalProps & {
  describedBy?: string;
  size?: "editor";
  footerSlot?: boolean;
  maskClosable?: boolean;
}) {
  const boxRef = useRef<HTMLDivElement>(null);
  useModalFocus(boxRef, keyboard ? onClose : undefined);
  const titleId = useId();
  const [slot, setSlot] = useState<HTMLElement | null>(null);
  return (
    <ModalMask onMaskClick={maskClosable ? onClose : undefined}>
      <div
        ref={boxRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={title ? titleId : undefined}
        aria-label={title ? undefined : label}
        aria-describedby={describedBy}
        tabIndex={-1}
        style={widthStyle(width)}
        className={cn("pop-modal relative flex max-h-[calc(var(--vvh,100dvh)-32px)] flex-col", IF_MODAL_BOX,
          size === "editor" && "max-sm:h-[calc(100dvh-32px)]", className)}
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
        <div className="min-h-0 flex-1 overflow-y-auto p-6 text-[14px] text-fg">
          <FooterSlotContext.Provider value={footerSlot ? slot : undefined}>{children}</FooterSlotContext.Provider>
        </div>
        {(footer || footerSlot) && (
          <div className={cn("flex flex-wrap items-center justify-end gap-2 px-6 pb-5",
            size === "editor" && "max-sm:border-t max-sm:border-border max-sm:pt-4")}>
            {footer}
            {footerSlot && <span ref={setSlot} className="contents" />}
          </div>
        )}
      </div>
    </ModalMask>
  );
}

export function HbModal({ title, label, width = 600, footer, onClose, closable = true, keyboard = closable, children, className }: ModalProps) {
  const boxRef = useRef<HTMLDivElement>(null);
  useModalFocus(boxRef, keyboard ? onClose : undefined);
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
        style={{ ...widthStyle(width), minWidth: "min(480px, calc(100vw - 32px))" }}
        className={cn("pop-modal flex max-h-[80vh] flex-col rounded-[12px] border bg-panel px-4 py-3 outline-none shadow-2xl", HB_HAIR, className)}
      >
        {(title || closable) && (
          <div className={cn("flex items-center justify-between gap-3 border-b px-4 pb-3", HB_HAIR)}>
            {title && <h2 id={titleId} className={cn("text-[24px] font-medium", HB_TEXT)}>{title}</h2>}
            {closable && (
              <button type="button" aria-label="Close" onClick={onClose}
                className={cn("ml-auto grid h-7 w-7 shrink-0 place-items-center rounded-[4px] hover:opacity-80", HB_TEXT)}>
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
