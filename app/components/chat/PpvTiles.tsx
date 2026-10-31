"use client";

/**
 * PpvTiles — the PPV row's tiles: attached media (FREE / PPV / BOUGHT badge,
 * the free ↑ / paid ↓ divider, drag and arrow-key reorder), upload chips and
 * picked GIFs, each with its ✕. The Composer owns the draft; this only draws it.
 */

import { Fragment } from "react";

import { cn } from "@/lib/utils";
import { MP } from "@/lib/messagesPro";
import { type VaultMedia } from "@/lib/relay";
import { proxyImage } from "@/lib/mediaUrl";
import { uploadErrorText, type useComposerUploads } from "@/hooks/useComposerUploads";
import type { FanVaultEntry } from "@/hooks/useFanVaultHistory";
import type { UseReorderResult } from "@/hooks/useReorder";

import { canBeFreePreview, type composerView } from "./composerDraft";
import type { PickedGif } from "./GifPicker";

export interface PpvTilesProps {
  attached: VaultMedia[];
  /** `previews`: leading tiles shown FREE; `paid`: the price, null when free. */
  view: Pick<ReturnType<typeof composerView>, "previews" | "paid" | "priceLabel" | "showDivider">;
  /** The upload chips, and their Retry and ✕. */
  uploads: Pick<ReturnType<typeof useComposerUploads>, "chips" | "retry" | "remove">;
  accountId: string | null;
  disabled?: boolean;
  reorder: UseReorderResult;
  /** The Fan's vault history (BOUGHT badges); absent outside a Fan chat. */
  byMedia?: Record<string, FanVaultEntry>;
  onRemove: (id: number) => void;
  gifs: PickedGif[];
  onRemoveGif: (id: string) => void;
}

export function PpvTiles({
  attached, view, uploads, accountId, disabled, reorder, byMedia, onRemove, gifs, onRemoveGif,
}: PpvTilesProps) {
  const { previews, paid, priceLabel, showDivider } = view;
  return (
    <>
      {attached.map((m, idx) => {
        const rawThumb =
          m.files?.thumb?.url ||
          m.files?.squarePreview?.url ||
          m.files?.preview?.url ||
          null;
        // A just-uploaded file shows its own blob: preview (the CDN has
        // not seen it yet; a claim has no `files` at all).
        const thumb = m._localPreview || proxyImage(rawThumb, accountId);
        // A tile only renders FREE if it's within the preview range
        // AND would actually survive the `previews` filter on send. A
        // still-uploading `_claim` tile is sent as media but cannot be
        // referenced by id in `previews`, so OF locks it — showing FREE
        // there would lie about what the fan sees. Render it as PPV.
        const isFreeTile = idx < previews && canBeFreePreview(m);
        const isDragging = reorder.draggingIndex === idx;
        const isDragOver = reorder.dragOverIndex === idx && !isDragging;
        // Three-state badge: BOUGHT (green) wins over the PPV split —
        // this fan already paid for this vault item, so the chatter
        // should know before sending it again. Falls through to the
        // free/paid colors below when no purchase record exists.
        const fanEntry = byMedia?.[String(m.id)];
        const wasBought = fanEntry?.was_purchased === true;
        return (
          <Fragment key={m.id}>
            {showDivider && idx === previews && (
              <div
                className={cn(MP.ours.Composer.divider, "flex flex-col items-center justify-center uppercase select-none border-dashed border-fg-dim/60")}
                title="Items left of this line are free previews; items right are PPV-locked"
                aria-hidden
              >
                <span className="text-fg-dim leading-none">free ↑</span>
                <span className="text-muted leading-none">/</span>
                <span className="text-err leading-none">paid ↓</span>
              </div>
            )}
            <div
              draggable={!disabled}
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
                MP.ppvRow.attachment,
                "relative overflow-hidden bg-bg-elev-1 group select-none",
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
                <div className={cn(MP.ours.Composer.tileType, "w-full h-full grid place-items-center text-fg-dim")}>
                  {m.type}
                </div>
              )}
              {(paid != null || wasBought) && (
                <div
                  className={cn(
                    MP.ours.Composer.tileBadge,
                    "absolute text-white shadow",
                    wasBought
                      ? "bg-ok"
                      : isFreeTile ? "bg-[var(--inf-offline,var(--color-fg-dim))]" : "bg-err",
                  )}
                  title={
                    wasBought
                      ? "BOUGHT — this fan has already purchased this item"
                      : isFreeTile
                        ? "Free preview — fans see this before paying"
                        : "PPV-locked — fans see this after paying"
                  }
                >
                  {wasBought ? "BOUGHT" : isFreeTile ? "FREE" : priceLabel || "PPV"}
                </div>
              )}
              <button
                type="button"
                onClick={() => onRemove(m.id)}
                className={cn(MP.ppvRow.attachmentRemove, MP.ours.Composer.tileRemove, "absolute bg-black/75 text-white")}
                aria-label="Remove attachment"
              >
                ✕
              </button>
            </div>
          </Fragment>
        );
      })}
      {uploads.chips.map((u) => (
        <div
          key={u.key}
          role="group"
          aria-label={u.status === "failed" ? `Upload failed: ${u.file.name}` : `Uploading ${u.file.name}`}
          title={u.status === "failed" ? `${u.file.name}: ${u.error ?? ""}` : `Uploading ${u.file.name}…`}
          className={cn(
            MP.ppvRow.attachment,
            "relative overflow-hidden bg-bg-elev-1",
            u.status === "failed" ? cn(MP.ours.Composer.uploadFailed, "w-auto flex items-center border-err/50 text-err") : "border-border",
          )}
        >
          {u.status === "uploading" ? (
            <>
              {u.previewUrl && u.file.type.startsWith("image/") && (
                // eslint-disable-next-line @next/next/no-img-element
                <img src={u.previewUrl} alt="" className="w-full h-full object-cover opacity-50" />
              )}
              <span role="status" aria-label="Uploading" className="absolute inset-0 grid place-items-center">
                <span aria-hidden className="size-4 rounded-full border-2 border-fg-dim/40 border-t-accent motion-safe:animate-spin" />
              </span>
            </>
          ) : (
            <>
              <span className="truncate min-w-0">⚠ {uploadErrorText(u.error ?? "")}</span>
              <button
                type="button"
                onClick={() => uploads.retry(u.key)}
                className="shrink-0 underline hover:text-fg"
              >
                Retry
              </button>
            </>
          )}
          <button
            type="button"
            onClick={() => uploads.remove(u.key)}
            className={cn(MP.ppvRow.attachmentRemove, MP.ours.Composer.tileRemove, "absolute bg-black/75 text-white")}
            aria-label="Remove upload"
          >
            ✕
          </button>
        </div>
      ))}
      {gifs.map((g) => (
        <div
          key={g.id}
          title={gifs.length > 1 ? `${gifs.length} GIFs — sent as separate messages` : "1 GIF attached"}
          className={cn(MP.ppvRow.attachment, "relative overflow-hidden border-border bg-bg-elev-1")}
        >
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={g.thumbUrl} alt={g.title || "GIF"} className="w-full h-full object-cover" />
          <button
            type="button"
            onClick={() => onRemoveGif(g.id)}
            className={cn(MP.ppvRow.attachmentRemove, MP.ours.Composer.tileRemove, "absolute bg-black/75 text-white")}
            aria-label="Remove GIF"
          >
            ✕
          </button>
        </div>
      ))}
    </>
  );
}
