"use client";


import { type MouseEvent } from "react";

import { type FanVaultEntry } from "@/hooks/useFanVaultHistory";
import { SCRUB_FRAMES, type useHoverPreview } from "@/hooks/useHoverPreview";
import { type ThumbRetry } from "@/hooks/useThumbAutoRefresh";
import { type VaultMediaStat } from "@/hooks/useVaultMediaStats";
import { type FanId } from "@/lib/fanId";
import { fmtDuration } from "@/lib/format";
import { mirrorPosterSrc, proxyImage, proxyScrubFrame } from "@/lib/mediaUrl";
import { type VaultMedia } from "@/lib/relay";
import { cn } from "@/lib/utils";
import { notWiredTitle } from "./NotWired";
import { aiCaptionFor, VaultAiCaptionOverlay } from "./vaultAiCaption";
import { VaultGifLoop } from "./VaultGifLoop";
import { cardAction } from "./VaultMediaDetails";
import {
  VAULT_CARD_CHECK, VAULT_CARD_CHECK_UNDER_INFO, VAULT_CARD_FOOT, VAULT_CARD_GIF, VAULT_CARD_GREYED, VAULT_CARD_INFO,
  VAULT_CARD_TAG, VAULT_CARD_TAGS, VAULT_CARD_UNSEND, VAULT_SHEET,
} from "./vaultPickerSheet";
import { type usePhotoHover } from "./vaultPickerSelection";
import { statsLabel } from "./vaultPickerStats";
import { tilePreview } from "./vaultTilePreview";
import { describeTile, pillText, resolveStatus, STATUS_DOT_CLASS, STATUS_RING_CLASS } from "./vaultTileStatus";
import { gifClipSrc, isDrmOnlyVideo, progressiveVideoSrc, videoPosterFrames } from "./VaultVideoPreview";

export const TILE_HINT = "Click to select · double-click to attach";

type HoverPreview = ReturnType<typeof useHoverPreview>;

function startHoverIntent(
  hover: HoverPreview,
  id: number,
  duration: number,
  rawUrl: string | null,
  posterUrls?: string[],
) {
  if (posterUrls && typeof Image !== "undefined") {
    for (const u of posterUrls.slice(0, 2)) {
      const pre = new Image();
      pre.decoding = "async";
      pre.src = u;
    }
  }
  hover.start(id, duration, rawUrl);
}

export interface VaultPickerTileProps {
  m: VaultMedia;
  selected: boolean;
  accountId: string | null;
  fanId: FanId | null;
  sheetTile: string | undefined;
  useLocalVault: boolean;
  blurCls: string;
  captionOn: boolean;
  fanEntry: FanVaultEntry | undefined;
  stat: VaultMediaStat | undefined;
  onWall: boolean;
  wallCents: number;
  hover: HoverPreview;
  photoHover: ReturnType<typeof usePhotoHover>;
  firstTileRef?: (el: HTMLButtonElement | null) => void;
  onTileClick: (m: VaultMedia, e: MouseEvent) => void;
  onAttach: (m: VaultMedia) => void;
  onPreview: (m: VaultMedia) => void;
  onDetails: (d: { media: VaultMedia; atHistory: boolean }) => void;
  thumbs: ThumbRetry;
}

export function VaultPickerTile({
  m, selected, accountId, fanId, sheetTile, useLocalVault, blurCls, captionOn,
  fanEntry, stat, onWall, wallCents, hover, photoHover, firstTileRef,
  onTileClick, onAttach, onPreview, onDetails, thumbs,
}: VaultPickerTileProps) {
  const closePhoto = photoHover.close;
  const thumb = thumbs.tile(m);
  // No fallback to files.preview.url: a static poster JPEG in <video> or /img/scrub made DRM items fail.
  const rawVideoSrc = progressiveVideoSrc(m);
  const gifSrc = accountId ? proxyImage(gifClipSrc(m), accountId, m.id) : "";
  const drmOnly = isDrmOnlyVideo(m);
  const posterFrames = m.type === "video" ? videoPosterFrames(m) : [];
  const posterCount = accountId ? posterFrames.length : 0;
  const pv = tilePreview(hover.state, {
    id: m.id,
    posterCount,
    drmOnly,
    canBuild: !!rawVideoSrc && !!accountId,
  });
  // Never pass the held url as `u=`: it made a render endpoint fetch any client-named host and saved nothing.
  const useCachedPoster = drmOnly && !!accountId;
  const posterSrcFor = (u: string, idx: number) =>
    useCachedPoster
      ? mirrorPosterSrc(accountId!, m.id, idx)
      : proxyImage(u, accountId, m.id);
  const status = resolveStatus(fanEntry, onWall);
  // Advisory: card stays selectable; the relay's 409 guards re-sales.
  const greyed = status === "unlocked" || status === "free";
  const cap = aiCaptionFor(m);
  return (
    <button
      ref={firstTileRef}
      type="button"
      data-tile-id={m.id}
      onClick={(e) => onTileClick(m, e)}
      onDoubleClick={() => onAttach(m)}
      title={fanEntry ? `${describeTile(m, fanEntry, onWall)} · ${TILE_HINT}` : TILE_HINT}
      // Pointer events, not touch: a tap fires mouseenter with no mouseleave, committing a cold build per tap.
      onPointerEnter={(e) => {
        if (e.pointerType === "touch") return;
        if (m.type === "video") {
          startHoverIntent(hover, m.id, m.duration ?? 0, rawVideoSrc,
            drmOnly ? posterFrames.map((u, idx) => posterSrcFor(u, idx)).slice(pv.posterStart) : undefined);
        } else if (m.type === "photo") photoHover.start(m, e.currentTarget);
      }}
      onPointerLeave={m.type === "video" ? hover.stop : m.type === "photo" ? closePhoto : undefined}
      className={cn(
        "relative aspect-square rounded-md overflow-hidden bg-bg-elev-1",
        sheetTile,
        "border-2 transition-colors",
        "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent",
        selected
          ? "border-accent ring-2 ring-accent/40"
          : status
          ? STATUS_RING_CLASS[status]
          : "border-border hover:border-fg-dim/40",
      )}
    >
      {(pv.showScrub || pv.showPosters) ? (
        <>
          {thumb.src && (
            <img
              src={thumb.src}
              alt=""
              aria-hidden
              loading={useLocalVault ? "eager" : "lazy"}
              decoding="async"
              onError={thumb.onError}
              className={cn(
                "absolute inset-0 w-full h-full object-cover",
                blurCls,
              )}
            />
          )}
          {pv.showPosters && posterFrames.map((u, idx) => (
            idx < pv.posterStart ? null : (
            <img
              key={`${m.id}-pf-${idx}`}
              src={posterSrcFor(u, idx)}
              alt=""
              aria-hidden={idx !== pv.posterIdx}
              decoding="async"
              onLoad={hover.onPosterLoad}
              onError={useCachedPoster ? (e) => {
                const img = e.currentTarget;
                if (!img.dataset.fellback) {
                  img.dataset.fellback = "1";
                  img.src = proxyImage(u, accountId, m.id);
                }
              } : undefined}
              style={{ opacity: idx === pv.posterIdx ? 1 : 0 }}
              className={cn(
                "absolute inset-0 w-full h-full object-cover transition-opacity duration-200",
                blurCls,
              )}
            />
            )
          ))}
          {pv.posterBadge && (
            <div
              aria-hidden
              className="absolute inset-0 grid place-items-center pointer-events-none"
            >
              <span className="text-white/85 text-base font-semibold drop-shadow-[0_1px_3px_rgba(0,0,0,0.7)] tabular-nums">
                {pv.posterBadge}
              </span>
            </div>
          )}
          {pv.showScrub && Array.from({ length: SCRUB_FRAMES }).map((_, idx) => (
            <img
              key={`${m.id}-frame-${idx}`}
              src={proxyScrubFrame(rawVideoSrc, accountId, idx, m.duration, hover.state.sid, m.id)}
              alt=""
              aria-hidden={idx !== pv.scrubVisibleIdx}
              decoding="async"
              {...hover.frameProps(idx)}
              style={{ opacity: idx === pv.scrubVisibleIdx ? 1 : 0 }}
              className={cn(
                "absolute inset-0 w-full h-full object-cover transition-opacity duration-200",
                blurCls,
              )}
            />
          ))}
          {pv.scrubBadge && (
            pv.scrubBadge.kind === "hd" ? (
              <span className="absolute top-1 right-1 bg-black/55 text-white/90 text-[9px] px-1.5 py-0.5 rounded-full pointer-events-none tabular-nums">
                HD {pv.scrubBadge.label}
              </span>
            ) : (
              <>
                <div aria-hidden className="scrub-shimmer pointer-events-none" />
                <div
                  aria-hidden
                  className="absolute inset-0 grid place-items-center pointer-events-none"
                >
                  <span className="text-white/85 text-lg font-semibold drop-shadow-[0_1px_3px_rgba(0,0,0,0.7)] tabular-nums">
                    {pv.scrubBadge.label}
                  </span>
                </div>
              </>
            )
          )}
        </>
      ) : thumb.src ? (
        <img
          src={thumb.src}
          alt=""
          loading={useLocalVault ? "eager" : "lazy"}
          decoding="async"
          onError={thumb.onError}
          className={cn("w-full h-full object-cover", blurCls)}
        />
      ) : (
        <div className="w-full h-full grid place-items-center text-[10px] text-fg-dim">
          {m.type}
        </div>
      )}
      {gifSrc && <VaultGifLoop src={gifSrc} className={blurCls} />}
      {greyed && <span data-testid="vault-card-greyed" aria-hidden className={VAULT_CARD_GREYED} />}
      {captionOn && cap && <VaultAiCaptionOverlay caption={cap} />}
      {m.type === "video" && (
        <span
          role="button"
          tabIndex={0}
          onClick={(e) => {
            e.stopPropagation();
            onPreview(m);
          }}
          onDoubleClick={(e) => e.stopPropagation()}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === " ") {
              e.preventDefault();
              e.stopPropagation();
              onPreview(m);
            }
          }}
          className={cn("absolute bottom-1 right-1 bg-black/60 hover:bg-black/85 text-white grid place-items-center md:block text-[12px] md:text-[10px] min-h-[40px] md:min-h-0 px-3 md:px-1.5 py-0 md:py-0.5 rounded cursor-pointer select-none", sheetTile != null && VAULT_SHEET.duration)}
          title="Preview video"
        >
          ▶ {fmtDuration(m.duration)}
        </span>
      )}
      {drmOnly && (
        <span
          className="absolute top-1 left-1 bg-black/60 text-white text-[10px] px-1 py-0.5 rounded leading-none select-none"
          title="DRM-protected video — preview shows OnlyFans' poster frames; full playback only after sending"
        >
          🔒
        </span>
      )}
      {(fanId != null || m.type === "gif" || stat) && (
        <div className={VAULT_CARD_FOOT}>
          {stat && (
            <span data-testid="vault-card-stats" className={VAULT_CARD_TAG}
              title="1:1 chat sends (mass sends not counted): fans sent to · fans who unlocked · unlock rate of priced sends">
              {statsLabel(stat)}
            </span>
          )}
          {fanId != null && (
            <>
              {cap && cap.tags.length > 0 && (
                <ul aria-label="Tags" className={VAULT_CARD_TAGS}>
                  {cap.tags.slice(0, 3).map((t) => <li key={t} className={VAULT_CARD_TAG}>{t}</li>)}
                </ul>
              )}
              {/* Notes: the relay stores none, and the AI description is not one. */}
              <span data-testid="vault-card-notes" />
            </>
          )}
          {m.type === "gif" && <span className={VAULT_CARD_GIF}>GIF</span>}
          {fanEntry && (
            <span
              {...cardAction(() => {})}
              aria-label="Unsend"
              aria-disabled="true"
              title={notWiredTitle("vaultUnsend")}
              className={VAULT_CARD_UNSEND}
            >
              ↶
            </span>
          )}
        </div>
      )}
      {status && (
        <span
          {...(fanId != null
            ? { ...cardAction(() => onDetails({ media: m, atHistory: true })), title: "Price history" }
            : { "aria-hidden": true })}
          className={cn(
            "absolute top-1 left-1 max-w-[calc(100%-2rem)] truncate px-1.5 h-4 rounded-full text-[9px] font-bold leading-4 shadow",
            STATUS_DOT_CLASS[status],
            status === "free" ? "text-bg" : "text-white",
            fanId != null && "cursor-pointer",
          )}
        >
          {pillText(status, fanEntry, wallCents)}
        </span>
      )}
      {fanId != null && (
        <span
          {...cardAction(() => onDetails({ media: m, atHistory: false }))}
          aria-label="Media details"
          title="Media details"
          className={VAULT_CARD_INFO}
        >
          ⓘ
        </span>
      )}
      {selected && (
        <span className={cn("absolute w-5 h-5 rounded-full bg-accent text-white grid place-items-center text-[11px] font-bold shadow", fanId != null ? VAULT_CARD_CHECK_UNDER_INFO : VAULT_CARD_CHECK)}>
          ✓
        </span>
      )}
    </button>
  );
}
