"use client";

/** `infloww.tsx`'s modals (re-exported there): `IfModal`, `HbModal`, and the focus / Escape / modal-stack hook they share. */

import {
  createContext, useCallback, useContext, useEffect, useId, useLayoutEffect, useRef, useState, type ReactNode, type RefObject,
} from "react";
import { createPortal } from "react-dom";
import { X } from "lucide-react";

import { HB_HAIR, HB_TEXT } from "@/components/ui/ifSelect";
import { useExitGhost } from "@/hooks/useExitGhost";
import { cn } from "@/lib/utils";

// ── Modals ──────────────────────────────────────────────────────────────────────────────────────────────────────

const FOCUSABLE = 'a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])';

/** `el`'s ancestor that is a child of <body>: the app root, or a portal's own root. */
function bodyChild(el: Element): Element | null {
  let n: Element | null = el;
  while (n && n.parentElement !== document.body) n = n.parentElement;
  return n;
}

/** Is `at` in a widget portaled above `box` (emoji, templates, a Radix popover): under a later child of <body>? */
function inPortalAbove(box: HTMLElement, at: Element): boolean {
  const a = bodyChild(at);
  const b = bodyChild(box);
  return !!a && !!b && a !== b && !!(b.compareDocumentPosition(a) & Node.DOCUMENT_POSITION_FOLLOWING);
}

/** A modal layer: its element, read at event time (a portal's node mounts after the layer registers). */
type Layer = { el: () => HTMLElement | null };
/** Every registered layer. Which one is on top is read from the DOM when a key arrives, never from mount order:
 *  a nested modal registers before the one around it. */
const layers: Layer[] = [];
/** Layer boxes leaving in this commit (cleared next microtask): an opener inside one is not given focus back. */
const leaving = new Set<HTMLElement>();

const elOf = (l: Layer) => l.el() as HTMLElement;
const liveLayers = () => layers.filter((l) => l.el()?.isConnected);

/** The top of `list` (all live): the latest in document order. A nested layer follows the one it is inside, and a
 *  portal opened later is appended after the rest. */
function topOf(list: Layer[]): Layer | null {
  let top: Layer | null = null;
  for (const l of list) {
    if (!top || elOf(top).compareDocumentPosition(elOf(l)) & Node.DOCUMENT_POSITION_FOLLOWING) top = l;
  }
  return top;
}

/** Registers `layer` while mounted (a layout effect: its cleanup still sees the DOM). Returns "is it on top". */
function useLayer(layer: Layer, onLeave: (wasTop: boolean, survivors: Layer[]) => void) {
  const leaveRef = useRef(onLeave);
  useLayoutEffect(() => {
    leaveRef.current = onLeave;
  });
  useLayoutEffect(() => {
    layers.push(layer);
    return () => {
      const el = layer.el();
      // The ones staying: not this layer, nor one inside it (that leaves with it).
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

/**
 * The one dialog hook the modals, the vault picker and the image lightbox share: focus moves into `ref`'s box (unless a
 * child already took it with `autoFocus`), Tab and Shift+Tab cycle inside it, Escape calls `onEscape` (none: Escape is
 * left alone), all only while it is the top layer. An Escape a control inside already handled (`preventDefault`: a
 * select's listbox, the captions panel) is not taken. One it takes stops at `document` (`preventDefault` too): the
 * `window` listeners (Find, the overlay Fan insights) never see it, so one Escape closes one layer. On unmount, if this was the top, focus goes back to the opener
 * when it is in the layer now on top (or no layer is left), else to that layer's box; under another layer it stays.
 */
export function useModalFocus<T extends HTMLElement>(ref: RefObject<T | null>, onEscape?: () => void) {
  const escapeRef = useRef(onEscape);
  // Read at the first render, before a child's `autoFocus` moves it. A dialog opened by one that closes in the same
  // commit (a pop-up's Next) reads a node about to go: the mount effect below then takes where focus landed instead.
  const [firstOpener] = useState(() => {
    // Server render: no DOM, no opener.
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
    // Back to the opener only where keys still work: no layer stays, or the opener is in the one on top.
    if (wasTop && opener?.isConnected && !gone(opener) && (!top || elOf(top).contains(opener))) {
      opener.focus();
      return;
    }
    if (!top) return;
    if (wasTop) { elOf(top).focus(); return; }
    const at = document.activeElement;
    // Focus left with this layer (or was never in one): into the top one staying.
    if (!at || gone(at) || !survivors.some((l) => elOf(l).contains(at))) elOf(top).focus();
  });
  useEffect(() => {
    escapeRef.current = onEscape;
  });
  useLayoutEffect(() => {
    const box = ref.current;
    // The opener read at render left with the dialog that closed as this one opened: take the focus that dialog
    // handed back (its own opener, or the box of the layer that stays), if any.
    const was = document.activeElement;
    if (!openerRef.current?.isConnected && was instanceof HTMLElement && was !== document.body && !box?.contains(was)) {
      openerRef.current = was;
    }
    if (box && !box.contains(document.activeElement)) box.focus();
    const onKey = (e: KeyboardEvent) => {
      if (!box || !isTop()) return;
      // Focus in a portaled picker or popover above the box (emoji, templates, Radix) is that widget's: leave its keys.
      // Focus anywhere else outside (the page behind, <body>) is brought back in by Tab.
      const at = document.activeElement;
      if (at && !box.contains(at) && inPortalAbove(box, at)) return;
      if (e.key === "Escape") {
        const escape = escapeRef.current;
        if (!escape || e.defaultPrevented) return;
        e.preventDefault();
        e.stopPropagation();
        escape();
      } else if (e.key === "Tab") {
        // A control in a disabled <fieldset> is `:disabled` with no attribute of its own: it takes no focus either.
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

/** The footer node of the IfModal around (`footerSlot`); `undefined`: none, the editor stands alone. */
const FooterSlotContext = createContext<HTMLElement | null | undefined>(undefined);

/** The editor's buttons: portaled into the footer of the `IfModal footerSlot` around it, after its `footer` (none
 *  drawn until the slot mounts), or inline under the body when the editor stands alone. A submit button in it needs `form={id}`: its node is outside the form. */
export function EditorFooter({ children }: { children: ReactNode }) {
  const slot = useContext(FooterSlotContext);
  if (slot === undefined) return <div className="mt-4 flex flex-wrap items-center justify-end gap-3">{children}</div>;
  return slot ? createPortal(children, slot) : null;
}

/** IfModal's mask and box surfaces, for the few dialogs that stay on Radix (they add their own position / z). */
export const IF_MODAL_MASK = "bg-black/70";
export const IF_MODAL_BOX = "rounded-[10px] bg-[#1f1f1f] text-fg shadow-2xl outline-none [html[data-theme=light]_&]:bg-white";

const widthStyle = (width: number) => ({ width: `min(${width}px, calc(100vw - 32px))` });

/** Both modals' mask: it pops in (the mask fades, the box scales from 0.96, globals.css `pop-*`) and leaves on a copy
 *  that takes no click (`useExitGhost`), so closing never holds up the page. */
function ModalMask({ children }: { children: ReactNode }) {
  const maskRef = useRef<HTMLDivElement>(null);
  useExitGhost(true, maskRef);
  return (
    <div ref={maskRef} className={cn("pop-backdrop fixed inset-x-0 top-0 z-50 grid h-[var(--vvh,100dvh)] place-items-center overflow-y-auto p-4", IF_MODAL_MASK)}>
      {children}
    </div>
  );
}

/** antd's modal: a 70% black mask; the box `colorBgElevated` #1f1f1f, radius 10, no border; header `22px 24px 0`
 *  (16 / 600 T1), body 24px, footer right with 8px between buttons; the 16px T3 × 16px in from the top right.
 *  `footerSlot`: an editor in the body puts its buttons (`EditorFooter`) in the footer, after `footer`. */
export function IfModal({
  title, label, width = 520, size, footer, footerSlot = false, onClose, closable = true, keyboard = closable, children,
  className,
}: ModalProps & {
  /** "editor": a long form's dialog, (almost) full-screen below `sm`. */
  size?: "editor";
  footerSlot?: boolean;
}) {
  const boxRef = useRef<HTMLDivElement>(null);
  useModalFocus(boxRef, keyboard ? onClose : undefined);
  const titleId = useId();
  const [slot, setSlot] = useState<HTMLElement | null>(null);
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
          <div className="flex flex-wrap items-center justify-end gap-2 px-6 pb-5">
            {footer}
            {footerSlot && <span ref={setSlot} className="contents" />}
          </div>
        )}
      </div>
    </ModalMask>
  );
}

/** HB's modal (`.hb-design-modal-content`): #171717 with a 1px 9%-white border, radius 12, `padding:12px 16px`, at
 *  least 480 wide and at most 80vh tall; the title 24px / 500 white over a hairline (`padding:0 16px 12px`), the body
 *  16px / 1.25 at 62% white, the footer over a hairline (`padding:12px 16px 0`) with its buttons right, 12px apart. */
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
