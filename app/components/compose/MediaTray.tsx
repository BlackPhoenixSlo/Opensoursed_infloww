"use client";

/**
 * MediaTray — shared attachment strip for the New-post + Mass-message
 * modals. Renders thumbnails for already-attached vault media plus an
 * "Add from vault" button.
 *
 * Upload-from-computer is intentionally removed for now (the producer
 * pipeline has open bugs; revisit once those are fixed). Vault-pick +
 * reorder + PPV preview-count UI remain functional.
 */

import { Fragment } from "react";
import { ChevronLeft, ChevronRight, Image as ImageIcon, Minus, Plus, X } from "lucide-react";

import { useReorder } from "@/hooks/useReorder";
import { canBeFreePreview } from "@/lib/composeDraft";
import { type VaultMedia } from "@/lib/relay";
import { proxyImage } from "@/lib/mediaUrl";
import { IfButton } from "@/components/ui/infloww";
import { cn } from "@/lib/utils";

/** The free-previews stepper's −/+ buttons. */
const STEP = "grid h-10 w-10 place-items-center rounded border border-border text-fg hover:border-accent hover:text-accent disabled:opacity-30 md:h-6 md:w-6";

export function MediaTray({
  accountId, attached, onChange, onOpenVaultPicker,
  price, previewCount, onPreviewCountChange,
}: {
  accountId: string | null;
  attached: VaultMedia[];
  onChange: (next: VaultMedia[]) => void;
  onOpenVaultPicker: () => void;
  /** Per-message PPV price (dollars). When > 0, tiles show FREE/PAID
   *  badges + a divider chip. Omit for free-only callers. */
  price?: number;
  /** How many leading tiles are free previews. Required alongside `price`
   *  for the badge/divider UI to render. */
  previewCount?: number;
  onPreviewCountChange?: (n: number) => void;
}) {
  const reorder = useReorder(attached, onChange, (m) => m.id);
  const numericPrice = typeof price === "number" && Number.isFinite(price) ? price : 0;
  const showPpv = numericPrice > 0 && typeof previewCount === "number";
  const effectivePreviewCount = showPpv
    ? Math.max(0, Math.min(previewCount, attached.length))
    : 0;
  const showDivider =
    showPpv && effectivePreviewCount > 0 && effectivePreviewCount < attached.length;
  const priceLabel = numericPrice > 0
    ? `$${numericPrice % 1 === 0 ? numericPrice : numericPrice.toFixed(2)}`
    : "";

  function remove(id: number) {
    onChange(attached.filter((m) => m.id !== id));
  }

  return (
    <div className="space-y-1.5">
      {attached.length > 0 ? (
        <div className="flex flex-wrap items-center gap-2 rounded-md border border-border p-2">
          {showPpv && onPreviewCountChange && (
            <div
              className="mr-1 flex items-center gap-1.5 text-[12px] text-fg-dim"
              title="How many tiles are free previews. Drag a tile across the divider to flip its side."
            >
              <span>Free previews</span>
              <button
                type="button"
                onClick={() => onPreviewCountChange(Math.max(0, effectivePreviewCount - 1))}
                disabled={effectivePreviewCount === 0}
                className={STEP}
                aria-label="Fewer free previews"
              ><Minus className="h-3.5 w-3.5" aria-hidden /></button>
              <span className="tabular-nums text-fg">
                {effectivePreviewCount}/{attached.length}
              </span>
              <button
                type="button"
                onClick={() => onPreviewCountChange(Math.min(attached.length, effectivePreviewCount + 1))}
                disabled={effectivePreviewCount >= attached.length}
                className={STEP}
                aria-label="More free previews"
              ><Plus className="h-3.5 w-3.5" aria-hidden /></button>
            </div>
          )}
          {attached.map((m, idx) => {
            const rawThumb =
              m.files?.thumb?.url ||
              m.files?.squarePreview?.url ||
              m.files?.preview?.url ||
              null;
            const thumb = proxyImage(rawThumb, accountId);
            // A fresh upload can't be a free teaser yet (lib/composeDraft canBeFreePreview).
            const isFreeTile = idx < effectivePreviewCount && canBeFreePreview(m);
            const isDragging = reorder.draggingIndex === idx;
            const isDragOver = reorder.dragOverIndex === idx && !isDragging;
            return (
              <Fragment key={m.id}>
                {showDivider && idx === effectivePreviewCount && (
                  <div
                    className="flex h-16 select-none flex-col items-center justify-center gap-1 border-x border-border px-1.5 text-[12px] leading-none"
                    title="Items left of this line are free previews; items right are PPV-locked"
                    aria-hidden
                  >
                    <span className="inline-flex items-center text-fg-dim"><ChevronLeft className="h-3 w-3" />Free</span>
                    <span className="inline-flex items-center text-err">Paid<ChevronRight className="h-3 w-3" /></span>
                  </div>
                )}
                <div
                  draggable
                  onDragStart={(e) => reorder.onDragStart(e, idx)}
                  onDragOver={(e) => reorder.onDragOver(e, idx)}
                  onDrop={(e) => reorder.onDrop(e, idx)}
                  onDragEnd={reorder.onDragEnd}
                  tabIndex={0}
                  onKeyDown={(e) => {
                    if (e.key === "ArrowLeft") {
                      e.preventDefault();
                      reorder.onKeyboardMove(idx, -1);
                    } else if (e.key === "ArrowRight") {
                      e.preventDefault();
                      reorder.onKeyboardMove(idx, 1);
                    }
                  }}
                  className={cn(
                    "relative w-16 h-16 rounded-md overflow-hidden border bg-bg-elev-1 select-none",
                    "motion-safe:transition-transform motion-safe:duration-150",
                    "cursor-grab active:cursor-grabbing",
                    "focus:outline-none focus:ring-2 focus:ring-accent",
                    isDragging ? "opacity-40 border-accent" : "border-border",
                    isDragOver && "ring-2 ring-accent",
                  )}
                >
                  {thumb ? (
                    <img src={thumb} alt="" loading="lazy" decoding="async" draggable={false} className="w-full h-full object-cover pointer-events-none" />
                  ) : (
                    <div className="w-full h-full grid place-items-center text-[10px] text-fg-dim">
                      {m.type}
                    </div>
                  )}
                  {showPpv && (
                    <div
                      className={cn(
                        "absolute top-0.5 left-0.5 px-1 rounded text-[9px] font-bold leading-tight text-white shadow",
                        isFreeTile ? "bg-fg-dim" : "bg-err",
                      )}
                      title={isFreeTile ? "Free preview" : "PPV-locked"}
                    >
                      {isFreeTile ? "FREE" : priceLabel || "PPV"}
                    </div>
                  )}
                  <button
                    type="button"
                    onClick={() => remove(m.id)}
                    className="absolute top-0.5 right-0.5 w-7 h-7 md:w-4 md:h-4 rounded-full bg-black/70 text-white grid place-items-center opacity-90"
                    aria-label="Remove"
                  ><X className="h-3 w-3" aria-hidden /></button>
                </div>
              </Fragment>
            );
          })}
          <IfButton icon={ImageIcon} onClick={onOpenVaultPicker} disabled={!accountId} title="Pick from vault">
            Pick from vault
          </IfButton>
        </div>
      ) : (
        <IfButton icon={ImageIcon} onClick={onOpenVaultPicker} disabled={!accountId}>
          Add from vault
        </IfButton>
      )}
    </div>
  );
}
