"use client";


import { useEffect, useState } from "react";
import { createPortal } from "react-dom";

import type { OFMedia, OFMessage } from "@/lib/relay";
import { proxyImage } from "@/lib/mediaUrl";
import { sameUserId, type FanId } from "@/lib/fanId";
import { cn } from "@/lib/utils";
import { stillUrl } from "@/lib/ofMedia";
import { blurImageClass, useBlurMode } from "@/hooks/useBlurMode";
import { useCompactMedia } from "@/hooks/useCompactMedia";
import { useFanVaultHistory } from "@/hooks/useFanVaultHistory";
import { MediaTile } from "@/components/chat/MediaTile";
import { clipUrl, isVideoMedia, mediaCountLabel, VideoTileMarks, ViewerVideo } from "@/components/chat/MediaVideo";
import { useInflowwPalette } from "@/components/chat/InflowwPalette";
import { ppvPriceLabel } from "@/components/chat/PpvStatus";
import { MP } from "@/lib/messagesPro";

export function MediaStrip({ msg, locked, accountId, fanId, isOutgoing, eagerMediaIds }: {
  msg: OFMessage;
  locked: boolean;
  accountId: string | null;
  fanId: FanId | null;
  isOutgoing: boolean;
  eagerMediaIds: Set<string>;
}) {
  const items = msg.media ?? [];
  const [blurMode] = useBlurMode();
  const [compactMedia] = useCompactMedia();
  const blurCls = blurImageClass(blurMode);
  const fanVaultQ = useFanVaultHistory(accountId, fanId, isOutgoing && fanId != null);
  const isPPV = !!msg.price && msg.price > 0;
  const previewIds = msg.previews ?? [];
  const refusedIds = msg._failedMediaIds ?? [];
  const priceLabel = msg.price != null ? ppvPriceLabel(msg.price) : "";
  const LOCKED_CAP = 2;
  const IMAGE_CAP = 3;
  const cap = locked ? LOCKED_CAP : IMAGE_CAP;
  const isRefused = (m: OFMedia) => refusedIds.some((r) => sameUserId(r, m.id));
  const refusedHere = items.filter(isRefused);
  const [expanded, setExpanded] = useState(false);
  const indexed = items.map((m, i) => [m, i] as const);
  const visible = expanded
    ? indexed
    // Slice by membership, not length: a tile OF refused always stays in the collapsed view.
    : indexed.filter(([m, i]) => i < cap || isRefused(m));
  const hiddenCount = items.length - visible.length;
  const [lightboxIdx, setLightboxIdx] = useState<number | null>(null);
  const fallbackBox = mediaTileBox(compactMedia, null, null);
  const countLabel = mediaCountLabel(items);
  return (
    <div className="mt-2">
      {countLabel && <div className={cn(MP.ours.MessageList.mediaCount, "opacity-70")}>{countLabel}</div>}
      <div className="flex flex-wrap gap-1.5">
        {visible.map(([m, i]) => {
          const isVideo = isVideoMedia(m);
          const rawThumb = isVideo
            ? stillUrl(m)
            : m.files?.thumb?.url || m.files?.source?.url || m.url || null;
          const thumb = proxyImage(rawThumb, accountId);
          const clip = isVideo ? clipUrl(m) : null;
          const fullRaw = clip || m.files?.source?.url || rawThumb;
          const full = proxyImage(fullRaw, accountId);
          const box = mediaTileBox(compactMedia, m.width, m.height);
          const fanEntry = m.id != null ? fanVaultQ.data?.by_media[String(m.id)] : undefined;
          // Assert BOUGHT only once the vault query resolved, else a free tile flashes a badge in.
          const wasBought = fanVaultQ.isSuccess && fanEntry?.was_purchased === true;
          const inPreviews = previewIds.some((pv) => sameUserId(pv, m.id));
          const showBadge = isOutgoing && (wasBought || isPPV);
          const badge = (
            showBadge ? (
              <div
                className={cn(
                  MP.ours.MessageList.tileBadge, "absolute text-white shadow z-10 pointer-events-none",
                  wasBought
                    ? "bg-ok"
                    : inPreviews ? "bg-[var(--inf-offline,var(--color-fg-dim))]" : "bg-err",
                )}
                title={
                  wasBought
                    ? "BOUGHT — this fan has purchased this item"
                    : inPreviews
                      ? "Free preview — sent unlocked"
                      : "PPV-locked — fan hasn't unlocked this tile"
                }
              >
                {wasBought ? "BOUGHT" : inPreviews ? "FREE" : priceLabel || "PPV"}
              </div>
            ) : null
          );
          const wasRefused = isRefused(m);
          // Fansly locked media reports price=0 but canView=false; outgoing exempt as Bubble does.
          const mLocked = locked || (m.canView === false && !isOutgoing);
          const overlays = (
            <>
              {badge}
              {isVideo && <VideoTileMarks media={m} glyph={!mLocked} duration={!wasRefused} />}
              {wasRefused && (
                <>
                  <div className="absolute inset-0 rounded-md border-2 border-err pointer-events-none z-10" />
                  <div
                    className={cn(MP.ours.MessageList.refusedBar, "absolute bg-err/85 text-white text-center z-10 pointer-events-none")}
                    title="This attachment was refused — remove it and the rest of the bundle sends"
                  >
                    REMOVE
                  </div>
                </>
              )}
            </>
          );
          if (mLocked) {
            return (
              <div
                key={m.id ?? i}
                style={{ width: box.w, height: box.h }}
                className={cn(MP.ours.MessageList.lockedTile, "relative flex-none bg-black/30 grid place-items-center text-warn border-warn/30 overflow-hidden")}
              >
                {overlays}
                🔒
              </div>
            );
          }
          if (!thumb && !clip) {
            return (
              <div
                key={m.id ?? i}
                style={{ width: box.w, height: box.h }}
                className={cn(MP.ours.MessageList.pendingTile, "relative flex-none bg-bg/30 grid place-items-center text-center opacity-70 overflow-hidden")}
              >
                {overlays}
                …
              </div>
            );
          }
          const isEager = m.id != null && eagerMediaIds.has(String(m.id));
          return (
            <a
              key={m.id ?? i}
              href={full || thumb}
              target="_blank"
              rel="noreferrer"
              onClick={(e) => {
                if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;
                e.preventDefault();
                setLightboxIdx(i);
              }}
              style={{ width: box.w, height: box.h }}
              className="relative block flex-none overflow-hidden rounded-md bg-black/20 cursor-zoom-in"
            >
              {overlays}
              {thumb && (
                <MediaTile
                  mediaId={m.id ?? null}
                  proxiedUrl={thumb}
                  eager={isEager}
                  alt=""
                  className={cn("rounded-md border border-black/10 object-contain", blurCls)}
                />
              )}
            </a>
          );
        })}
        {hiddenCount > 0 && (
          <button
            type="button"
            onClick={() => setExpanded(true)}
            title={`Show ${hiddenCount} more`}
            style={{ width: fallbackBox.w, height: fallbackBox.h }}
            className="flex-none rounded-md border border-border bg-bg-elev-1 hover:bg-bg-elev-2 text-xs text-fg-dim flex items-center justify-center gap-1"
          >
            +{hiddenCount}
          </button>
        )}
      </div>
      {refusedHere.length > 0 && (
        <div
          className={cn(MP.ours.MessageList.refusedCount, "inline-block bg-err/85 text-white")}
          title="These exact attachments were refused — drop them and re-send; a plain retry sends the same bundle."
        >
          remove {refusedHere.length} of {items.length}
        </div>
      )}
      {expanded && items.length > cap && (
        <button
          type="button"
          onClick={() => setExpanded(false)}
          className={cn(MP.ours.MessageList.showLess, "w-full border-border bg-bg-elev-1 hover:bg-bg-elev-2 text-fg-dim")}
        >
          show less
        </button>
      )}
      {lightboxIdx != null && items[lightboxIdx] && (
        <MediaLightbox
          items={items}
          accountId={accountId}
          index={lightboxIdx}
          onClose={() => setLightboxIdx(null)}
          onIndex={setLightboxIdx}
        />
      )}
    </div>
  );
}

function MediaLightbox({
  items,
  accountId,
  index,
  onClose,
  onIndex,
}: {
  items: OFMedia[];
  accountId: string | null;
  index: number;
  onClose: () => void;
  onIndex: (next: number) => void;
}) {
  const palette = useInflowwPalette();
  const [loaded, setLoaded] = useState(false);
  const count = items.length;
  const m = items[index];
  const fullRaw = m?.files?.source?.url || m?.files?.thumb?.url || m?.url || null;
  const full = proxyImage(fullRaw, accountId);
  const isVideo = m != null && isVideoMedia(m);

  useEffect(() => {
    setLoaded(false);
  }, [index]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.defaultPrevented || e.target instanceof HTMLMediaElement) {
        if (e.key !== "Escape") return;
      }
      if (e.key === "Escape") {
        e.preventDefault();
        onClose();
      } else if (count > 1 && e.key === "ArrowLeft") {
        e.preventDefault();
        onIndex((index - 1 + count) % count);
      } else if (count > 1 && e.key === "ArrowRight") {
        e.preventDefault();
        onIndex((index + 1) % count);
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [index, count, onClose, onIndex]);

  if (!full && !isVideo) return null;

  return createPortal(
    <div
      className={cn(MP.ours.MessageList.zoomBackdrop, "fixed bg-black/85 backdrop-blur-sm flex items-center justify-center")}
      style={palette}
      onClick={onClose}
      role="dialog"
      aria-modal="true"
    >
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          onClose();
        }}
        aria-label="Close image"
        title="Close image"
        className="absolute top-4 right-4 z-10 w-10 h-10 grid place-items-center rounded-full bg-white/10 hover:bg-white/20 text-white text-2xl leading-none"
      >
        ×
      </button>

      {count > 1 && (
        <>
          <button
            type="button"
            aria-label="Previous image"
            title="Previous image"
            onClick={(e) => {
              e.stopPropagation();
              onIndex((index - 1 + count) % count);
            }}
            className="absolute left-3 top-1/2 -translate-y-1/2 z-10 w-11 h-11 grid place-items-center rounded-full bg-white/10 hover:bg-white/20 text-white text-3xl leading-none"
          >
            ‹
          </button>
          <button
            type="button"
            aria-label="Next image"
            title="Next image"
            onClick={(e) => {
              e.stopPropagation();
              onIndex((index + 1) % count);
            }}
            className="absolute right-3 top-1/2 -translate-y-1/2 z-10 w-11 h-11 grid place-items-center rounded-full bg-white/10 hover:bg-white/20 text-white text-3xl leading-none"
          >
            ›
          </button>
          <div className="absolute bottom-4 left-1/2 -translate-x-1/2 z-10 text-white/80 text-xs bg-black/40 rounded-full px-3 py-1">
            {index + 1} / {count}
          </div>
        </>
      )}

      <div className={cn(MP.ours.MessageList.zoomFrame, "relative")} onClick={(e) => e.stopPropagation()}>
        {isVideo ? <ViewerVideo key={index} media={m} accountId={accountId} /> : (
          <>
            {!loaded && (
              <div className="absolute inset-0 grid place-items-center text-white/70 text-sm">
                loading…
              </div>
            )}
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={full}
              alt=""
              onLoad={() => setLoaded(true)}
              className={cn(
                MP.ours.MessageList.zoomImage, "object-contain transition-opacity duration-150",
                loaded ? "opacity-100" : "opacity-0",
              )}
            />
          </>
        )}
      </div>
    </div>,
    document.body,
  );
}

const COMPACT_TILE_PX = 64;
const NORMAL_TILE_PX = 155;

export function mediaTileBox(
  compact: boolean,
  _width?: number | null,
  _height?: number | null,
): { w: number; h: number } {
  // Fixed square: OF dims arrive late, so any dim-derived box would resize on load.
  const side = compact ? COMPACT_TILE_PX : NORMAL_TILE_PX;
  return { w: side, h: side };
}
