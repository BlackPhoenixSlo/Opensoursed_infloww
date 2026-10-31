"use client";

/**
 * One VaultPicker grid card: the thumb, the hover preview layers (OF poster
 * frames, then the HD ffmpeg storyboard), the per-fan status ring + corner
 * pill, and the card's own actions (video preview, media details).
 */

import { type MouseEvent } from "react";

import { type FanVaultEntry } from "@/hooks/useFanVaultHistory";
import { SCRUB_FRAMES, type useHoverPreview } from "@/hooks/useHoverPreview";
import { vaultTileThumb } from "@/hooks/useVaultCache";
import { type VaultMediaStat } from "@/hooks/useVaultMediaStats";
import { type FanId } from "@/lib/fanId";
import { fmtDuration } from "@/lib/format";
import { proxyImage, proxyScrubFrame } from "@/lib/mediaUrl";
import { type VaultMedia } from "@/lib/relay";
import { cn } from "@/lib/utils";
import { notWiredTitle } from "./NotWired";
import { aiCaptionFor, VaultAiCaptionOverlay } from "./vaultAiCaption";
import { cardAction } from "./VaultMediaDetails";
import {
  VAULT_CARD_CHECK, VAULT_CARD_CHECK_UNDER_INFO, VAULT_CARD_FOOT, VAULT_CARD_GIF, VAULT_CARD_GREYED, VAULT_CARD_INFO,
  VAULT_CARD_TAG, VAULT_CARD_TAGS, VAULT_CARD_UNSEND, VAULT_SHEET,
} from "./vaultPickerSheet";
import { type usePhotoHover } from "./vaultPickerSelection";
import { statsLabel } from "./vaultPickerStats";
import { tilePreview } from "./vaultTilePreview";
import { describeTile, pillText, resolveStatus, STATUS_DOT_CLASS, STATUS_RING_CLASS } from "./vaultTileStatus";
import { isDrmOnlyVideo, progressiveVideoSrc, videoPosterFrames } from "./VaultVideoPreview";

export const TILE_HINT = "Click to select · double-click to attach";

type HoverPreview = ReturnType<typeof useHoverPreview>;

// Hover-dwell debounce (in useHoverPreview): we won't kick off a hover
// preview until the pointer has been over a tile for HOVER_DELAY_MS — kills
// "brush past 20 tiles in 200ms" thrash. The relay only pays the storyboard
// build cost when the user actually commits.
function startHoverIntent(
  hover: HoverPreview,
  id: number,
  duration: number,
  rawUrl: string | null,
  posterUrls?: string[],
) {
  // Kick the first poster frame(s) fetch IMMEDIATELY, in parallel with the
  // dwell — so by the time the preview commits (HOVER_DELAY_MS later) the
  // frame is already warm in the browser + relay /img cache instead of
  // paying a ~0.85s cold OF fetch ON TOP of the dwell (the "2s wait").
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
  /** The Messages Pro sheet's tile class; undefined outside Messages Pro. */
  sheetTile: string | undefined;
  useLocalVault: boolean;
  blurCls: string;
  captionOn: boolean;
  fanEntry: FanVaultEntry | undefined;
  stat: VaultMediaStat | undefined;
  onWall: boolean;
  /** OF's wall price for this media, 0 when free / not on the wall. */
  wallCents: number;
  hover: HoverPreview;
  photoHover: ReturnType<typeof usePhotoHover>;
  /** Set on the first card only: VaultPicker's `vault.open` painted mark. */
  firstTileRef?: (el: HTMLButtonElement | null) => void;
  onTileClick: (m: VaultMedia, e: MouseEvent) => void;
  onAttach: (m: VaultMedia) => void;
  onPreview: (m: VaultMedia) => void;
  onDetails: (d: { media: VaultMedia; atHistory: boolean }) => void;
}

export function VaultPickerTile({
  m, selected, accountId, fanId, sheetTile, useLocalVault, blurCls, captionOn,
  fanEntry, stat, onWall, wallCents, hover, photoHover, firstTileRef,
  onTileClick, onAttach, onPreview, onDetails,
}: VaultPickerTileProps) {
  const closePhoto = photoHover.close;
  // Permanent cached thumb on the mirror path, proxied OF url on the
  // live one, "" for a media with no picture at all (a voice note) —
  // in which case the `{m.type}` placeholder below renders.
  const thumb = vaultTileThumb(m, accountId);
  // The playable mp4 — null for DRM-only videos. We do NOT fall
  // back to files.preview.url here: that's a static poster JPEG,
  // and feeding it to <video>/`/img/scrub` is exactly what made
  // DRM items fail ("Couldn't load" + 502 storyboard build).
  const rawVideoSrc = progressiveVideoSrc(m);
  // DRM (encrypted) videos have no progressive source; we slideshow
  // OF's own poster frames instead of the impossible ffmpeg scrub.
  // The 🔒 marker keys off the manifest (authoritative), so it
  // shows even on the rare DRM file with no poster frames.
  const drmOnly = isDrmOnlyVideo(m);
  // OF's pre-extracted poster frames — available on MOST videos
  // (up to ~9), not just DRM ones. We now use them as the instant
  // hover preview for ALL videos: they're a single CDN GET each
  // (~0.85s cold, instant warm) vs the ~11.5s cold ffmpeg build.
  const posterFrames = m.type === "video" ? videoPosterFrames(m) : [];
  // Posters first, the ffmpeg storyboard built behind them and
  // swapped in once a frame lands; see vaultTilePreview.
  const posterCount = accountId ? posterFrames.length : 0;
  const pv = tilePreview(hover.state, {
    id: m.id,
    posterCount,
    drmOnly,
    canBuild: !!rawVideoSrc && !!accountId,
  });
  // DRM videos serve poster frames from the relay's PERMANENT on-disk
  // cache (media-id keyed, signature-free). It self-heals: on a miss
  // the relay resolves the media by id straight from OF for a freshly
  // signed url, then stores the bytes — so hovering a DRM video caches
  // its posters even on an UN-collected account (the cache fills as you
  // browse; Collect just pre-warms everything). Not gated on cache-mode
  // — works on any owned account.
  //
  // We deliberately do NOT pass the url we happen to be holding. The
  // route used to take it as `u=`, which made a render endpoint fetch
  // whatever host the client named, and it saved nothing: the by-id
  // read is the same call the relay makes when a stored url has gone
  // stale, and unlike our copy it cannot already be expired.
  const useCachedPoster = drmOnly && !!accountId;
  const posterSrcFor = (u: string, idx: number) =>
    useCachedPoster
      ? `/admin/vault-ai/poster?account_id=${encodeURIComponent(accountId!)}&media_id=${m.id}&i=${idx}`
      : proxyImage(u, accountId);
  const status = resolveStatus(fanEntry, onWall);
  // The Fan already has it (bought, or last sent free). Advisory:
  // the card stays selectable; the relay's 409 guards re-sales.
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
      // Pointer events, no touch: a touch tap fires a synthetic
      // mouseenter and no mouseleave until the next tap elsewhere,
      // which would commit a preview and a cold build per tap.
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
        // Status ring wins unless the tile is selected — once
        // the user picks it the accent ring takes over so
        // their selection state is unambiguous.
        selected
          ? "border-accent ring-2 ring-accent/40"
          : status
          ? STATUS_RING_CLASS[status]
          : "border-border hover:border-fg-dim/40",
      )}
    >
      {(pv.showScrub || pv.showPosters) ? (
        <>
          {/* LAYER 0 — base thumb. Already loaded by the grid, so
           *  it paints instantly and fills any gap when the cursor
           *  lands on a poster/HD frame that hasn't finished
           *  loading yet — without it those beats flash black
           *  (empty <img> over the dark tile). Never animates;
           *  the frame layers sit on top at object-cover. */}
          {thumb && (
            <img
              src={thumb}
              alt=""
              aria-hidden
              // Cache path = permanent on-disk thumbs → load ALL at
              // once, paint as each arrives. Live path stays lazy so
              // we don't flood OF with off-screen fetches.
              loading={useLocalVault ? "eager" : "lazy"}
              decoding="async"
              className={cn(
                "absolute inset-0 w-full h-full object-cover",
                blurCls,
              )}
            />
          )}
          {/* LAYER 1 — OF poster frames (instant). The hover
           *  preview the user sees first: one CDN GET per frame
           *  (~0.85s cold, instant warm) vs the ~11.5s cold
           *  ffmpeg build. Shown for DRM videos (the only option)
           *  and for progressive videos UNTIL the HD storyboard
           *  is ready. Layered + opacity-toggled so ticking the
           *  cursor never cancels an in-flight load. */}
          {pv.showPosters && posterFrames.map((u, idx) => (
            // Don't render/fetch frame 0 (the thumbnail-like frame).
            idx < pv.posterStart ? null : (
            <img
              key={`${m.id}-pf-${idx}`}
              src={posterSrcFor(u, idx)}
              alt=""
              aria-hidden={idx !== pv.posterIdx}
              decoding="async"
              // First poster image to land clears the gray-state
              // decimal countdown.
              onLoad={hover.onPosterLoad}
              onError={useCachedPoster ? (e) => {
                // If the cached-poster endpoint isn't up yet (relay
                // pre-restart) fall back once to the direct OF url so
                // DRM tiles never break — just aren't cached yet.
                const img = e.currentTarget;
                if (!img.dataset.fellback) {
                  img.dataset.fellback = "1";
                  img.src = proxyImage(u, accountId);
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
          {/* Gray-state countdown — fine decimal (2.3 → 2.2 → 2.1)
           *  painted over the thumb base until OF's first poster
           *  image arrives — not held past load, which made a cached
           *  poster read as a 2s wait. Distinct from the
           *  whole-second HD pill (the ffmpeg-upgrade ETA). */}
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
          {/* LAYER 2 — HD ffmpeg storyboard (12 frames, sharper +
           *  evenly spaced). Mounted as soon as we hover a
           *  progressive video so the background build starts
           *  immediately; sits at opacity 0 UNDER the posters and
           *  takes over the moment a frame lands.
           *  Each <img> keeps its own src for the whole hover — no
           *  src swaps, so the browser never cancels an in-flight
           *  frame fetch. The first frame to load is the
           *  poster→HD handoff; a frame-0 error drops the HD
           *  pill / shimmer so the tile falls back to its thumb. */}
          {pv.showScrub && Array.from({ length: SCRUB_FRAMES }).map((_, idx) => (
            <img
              key={`${m.id}-frame-${idx}`}
              src={proxyScrubFrame(rawVideoSrc, accountId, idx, m.duration, hover.state.sid)}
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
          {/* LAYER 3 — HD-build affordance while ffmpeg runs. With
           *  posters visible we DON'T cover them with the shimmer;
           *  a small corner ETA pill ("HD 7s", ×1.3-padded) tells
           *  the user a sharper version is coming. No posters
           *  (rare) → keep the full-tile shimmer as before. */}
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
      ) : thumb ? (
        <img
          src={thumb}
          alt=""
          loading={useLocalVault ? "eager" : "lazy"}
          decoding="async"
          className={cn("w-full h-full object-cover", blurCls)}
        />
      ) : (
        <div className="w-full h-full grid place-items-center text-[10px] text-fg-dim">
          {m.type}
        </div>
      )}
      {greyed && <span data-testid="vault-card-greyed" aria-hidden className={VAULT_CARD_GREYED} />}
      {captionOn && cap && <VaultAiCaptionOverlay caption={cap} />}
      {m.type === "video" && (
        // Repurposed as the preview-open affordance. Nested
        // <button> isn't legal HTML so we use a span with
        // role="button" + stopPropagation, which keeps tile
        // selection on the tile click and play-modal on the
        // pill click. Hover styling makes the interactivity
        // discoverable.
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
          // Phone: a real 40px tap pill (it is the only way to
          // open the video preview). The md: half restores the
          // original 10px/px-1.5/py-0.5 badge exactly; the box is
          // absolutely positioned, so grid vs block is inert.
          className={cn("absolute bottom-1 right-1 bg-black/60 hover:bg-black/85 text-white grid place-items-center md:block text-[12px] md:text-[10px] min-h-[40px] md:min-h-0 px-3 md:px-1.5 py-0 md:py-0.5 rounded cursor-pointer select-none", sheetTile != null && VAULT_SHEET.duration)}
          title="Preview video"
        >
          ▶ {fmtDuration(m.duration)}
        </span>
      )}
      {drmOnly && (
        // DRM (FairPlay) marker. These have no progressive mp4, so
        // hover + click show OF's poster frames, not real playback.
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
              {/* The mirror's AI tags; live media carries none. */}
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
          {/* Not wired: fan-history returns no message id to unsend. */}
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
      {/* Price/state corner: replaces the plain dot with a
       *  small pill that carries the price for locked/unlocked
       *  ($X), the word "FREE" for sent-free, and the wall
       *  marker. Still color-matches the ring so the state is
       *  legible at the smallest grid sizes. */}
      {/* With a Fan in scope the pill opens "Media details" at
       *  the price history. */}
      {status && (
        <span
          {...(fanId != null
            ? { ...cardAction(() => onDetails({ media: m, atHistory: true })), title: "Price history" }
            : { "aria-hidden": true })}
          className={cn(
            "absolute top-1 left-1 px-1.5 h-4 rounded-full text-[9px] font-bold leading-4 shadow",
            STATUS_DOT_CLASS[status],
            // Yellow needs dark text for legibility; the
            // rest are bright-on-dark.
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
