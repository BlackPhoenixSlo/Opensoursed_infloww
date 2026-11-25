"use client";


import { type ReactNode, useCallback, useEffect, useRef, useState } from "react";
import { ChevronLeft, ChevronRight, X } from "lucide-react";

import { ifConfirm } from "@/components/ui/ifConfirm";
import { useModalFocus } from "@/components/ui/ifModal";
import VaultPreviewMedia from "@/components/vault/VaultPreviewMedia";
import { VaultDeleteButton } from "@/components/vault/VaultSelectionBar";
import { VaultItemEditor } from "@/components/vault/VaultItemEditor";
import { type Tile } from "@/components/vault/vaultManageActions";

export function mediaDate(iso: string | undefined): string | null {
  if (!iso) return null;
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? null : d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}

const typing = (t: EventTarget | null) =>
  t instanceof HTMLElement && (t.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(t.tagName));

const ARROW =
  "absolute top-1/2 -translate-y-1/2 z-10 grid h-9 w-9 place-items-center rounded-full border border-white/25 bg-black/55 text-white hover:bg-black/80 disabled:opacity-30 disabled:pointer-events-none";

export default function VaultItemModal({
  media,
  accountId,
  prev,
  next,
  onStep,
  onClose,
  onEscape,
  keysOff,
  onExpand,
  onSaved,
  onDeleted,
  describeSlot,
}: {
  media: Tile;
  accountId: string;
  prev: Tile | null;
  next: Tile | null;
  onStep: (t: Tile) => void;
  onClose: () => void;
  onEscape: () => void;
  keysOff: boolean;
  onExpand: () => void;
  onSaved: (updated: Record<string, unknown>) => void;
  onDeleted?: () => void;
  describeSlot: ReactNode;
}) {
  const boxRef = useRef<HTMLDivElement>(null);
  const dirtyRef = useRef(false);
  const onDirtyChange = useCallback((d: boolean) => {
    dirtyRef.current = d;
  }, []);
  const leave = useCallback((go: () => void) => {
    if (!dirtyRef.current) return go();
    void ifConfirm("Discard your unsaved changes?", { confirmLabel: "Discard", danger: true }).then((ok) => {
      if (ok) go();
    });
  }, []);
  const close = () => leave(onClose);
  const step = useCallback((t: Tile) => leave(() => onStep(t)), [leave, onStep]);
  // A layer above (the full-screen player) takes this Escape for itself: nothing is discarded.
  useModalFocus(boxRef, keysOff ? onEscape : () => leave(onEscape));
  const [more, setMore] = useState(false);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (keysOff || e.defaultPrevented || e.altKey || e.metaKey || e.ctrlKey || typing(e.target)) return;
      const box = boxRef.current;
      const t = e.target as Element | null;
      if (!box || (t && t !== document.body && t.closest('[role="dialog"]') !== box)) return;
      const to = e.key === "ArrowLeft" ? prev : e.key === "ArrowRight" ? next : null;
      if (!to) return;
      e.preventDefault();
      step(to);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [keysOff, prev, next, step]);

  const date = mediaDate(media.createdAt);

  return (
    <div
      className="fixed inset-x-0 top-[var(--vvt,0px)] z-50 h-[var(--vvh,100dvh)] flex items-center justify-center bg-black/70 md:p-6"
      onPointerDown={(e) => {
        // pointerdown, not click: a text selection dragged out of a field onto the backdrop must not close it.
        if (e.target === e.currentTarget) close();
      }}
    >
      <div
        ref={boxRef}
        role="dialog"
        aria-modal="true"
        aria-label={`Media #${media.id}`}
        tabIndex={-1}
        className="relative flex h-full w-full flex-col overflow-hidden bg-panel outline-none shadow-2xl pt-[env(safe-area-inset-top)] md:pt-0 md:h-[min(860px,100%)] md:max-w-[1280px] md:rounded-[10px] md:border md:border-border"
      >
        <button
          type="button"
          onClick={close}
          aria-label="Close details"
          title="Close (Esc)"
          className="absolute right-2 top-[calc(env(safe-area-inset-top)+6px)] md:top-3 md:right-3 z-20 grid h-8 w-8 place-items-center rounded-md text-fg-dim hover:text-fg hover:bg-bg-elev-1"
        >
          <X className="h-4 w-4" aria-hidden />
        </button>
        <VaultItemEditor
          key={media.id}
          media={media}
          accountId={accountId}
          onSaved={onSaved}
          describeSlot={describeSlot}
          more={more}
          onToggleMore={() => setMore((v) => !v)}
          onDirtyChange={onDirtyChange}
          mediaSlot={
            <div className="relative h-full w-full">
              <VaultPreviewMedia key={`pv-${media.id}`} media={media} accountId={accountId} onExpand={onExpand} fill />
              {date && (
                <span className="pointer-events-none absolute left-3 top-3 rounded bg-black/60 px-2 py-0.5 text-[12px] font-medium text-white">
                  {date}
                </span>
              )}
              <button type="button" aria-label="Previous item" title="Previous (←)" disabled={!prev}
                onClick={() => prev && step(prev)} className={`${ARROW} left-3`}>
                <ChevronLeft className="h-5 w-5" aria-hidden />
              </button>
              <button type="button" aria-label="Next item" title="Next (→)" disabled={!next}
                onClick={() => next && step(next)} className={`${ARROW} right-3`}>
                <ChevronRight className="h-5 w-5" aria-hidden />
              </button>
            </div>
          }
          deleteSlot={onDeleted && <VaultDeleteButton key={`del-${media.id}`} media={media} accountId={accountId} onDeleted={onDeleted} />}
        />
      </div>
    </div>
  );
}
