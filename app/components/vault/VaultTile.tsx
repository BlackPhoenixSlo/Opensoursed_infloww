"use client";

/**
 * VaultTile — one media tile with hover preview + select/describe/order affordances.
 *
 * Hover: the vault picker's preview (useHoverPreview + tilePreview): OF poster
 * frames → HD storyboard (via /img/scrub), cancel on leave. Optional selection checkbox, a describe-status dot, and a per-folder
 * manual-order input (0,1,2,3 / -1,-2,-3) shown only in a folder view.
 */

import {
  progressiveVideoSrc,
  videoPosterFrames,
  isDrmOnlyVideo,
  aiCaptionFor,
  useCaptionOverlay,
  VaultAiCaptionOverlay,
} from "@/components/chat/VaultPicker";
import { tilePreview } from "@/components/chat/vaultTilePreview";
import { HOVER_DELAY_MS, SCRUB_FRAMES, useHoverPreview } from "@/hooks/useHoverPreview";
import { vaultTileThumb } from "@/hooks/useVaultCache";
import { type VaultMedia } from "@/lib/relay";
import { proxyImage, proxyScrubFrame } from "@/lib/mediaUrl";
import { fmtDuration } from "@/lib/format";
import { EXTRA_LABEL } from "@/lib/openinflowwwwExtras";

interface AiMeta {
  describe_status?: string | null;
  manual_order?: number | null;
  description?: string | null;
  video_description?: string | null;
  tags?: string[] | null;
}

export interface VaultTileProps {
  media: VaultMedia & { _ai?: AiMeta };
  accountId: string | null;
  onClick?: (m: VaultMedia) => void;
  /** When set, the duration pill becomes a play button that opens the picker's
   *  full-screen VaultVideoPreview (one click, same as the chat picker). */
  onPlay?: (m: VaultMedia) => void;
  selected?: boolean;
  selectMode?: boolean;
  checked?: boolean;
  onCheck?: (m: VaultMedia) => void;
  showOrder?: boolean;
  onOrder?: (m: VaultMedia, value: number | null) => void;
  /** Force the AI caption overlay on/off. When omitted, follows the persisted
   *  manager toggle (default ON). */
  aiCaption?: boolean;
}

export default function VaultTile({
  media: m,
  accountId,
  onClick,
  onPlay,
  selected,
  selectMode,
  checked,
  onCheck,
  showOrder,
  onOrder,
  aiCaption,
}: VaultTileProps) {
  const [managerCaptionOn] = useCaptionOverlay("manager");
  const captionOn = aiCaption ?? managerCaptionOn;
  const caption = captionOn ? aiCaptionFor(m) : null;
  // Dwell, session id, slideshow cursor and the cancel POST live in the hook;
  // what the tile shows is tilePreview's read of it, as in the picker.
  const hover = useHoverPreview(HOVER_DELAY_MS);

  // "" for a media with no picture (a voice note) — the placeholder renders.
  const thumb = vaultTileThumb(m, accountId);
  const dur = fmtDuration(m.duration);
  const isVideo = m.type === "video";
  const rawVideoSrc = isVideo ? progressiveVideoSrc(m) : null;
  const posterFrames = isVideo ? videoPosterFrames(m) : [];
  const drmOnly = isVideo && isDrmOnlyVideo(m);
  // The storyboard needs an account to proxy through; without one there is no build to start or cancel.
  const canScrub = isVideo && !!rawVideoSrc && !!accountId;
  // Posters proxy through the account too.
  const posterCount = accountId ? posterFrames.length : 0;
  const described = m._ai?.describe_status === "described";

  const pv = tilePreview(hover.state, {
    id: m.id,
    posterCount,
    drmOnly,
    canBuild: canScrub,
  });

  function handleClick() {
    if (selectMode) onCheck?.(m);
    else onClick?.(m);
  }

  return (
    <div
      onPointerEnter={(e) => {
        // Nothing to show (no account, or no source and no posters): no session to start.
        if (e.pointerType === "mouse" && (canScrub || posterCount > 0)) {
          hover.start(m.id, m.duration ?? 0, canScrub ? rawVideoSrc : null);
        }
      }}
      onPointerLeave={(e) => {
        if (e.pointerType === "mouse") hover.stop();
      }}
      onClick={handleClick}
      title={`#${m.id} · ${m.type}${dur ? ` · ${dur}` : ""}`}
      className={`relative aspect-square rounded-lg overflow-hidden bg-bg-elev-1 border cursor-pointer transition-colors ${
        selected || checked ? "border-accent ring-2 ring-accent/40" : "border-border hover:border-fg-dim/50"
      }`}
    >
      {thumb ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={thumb}
          alt=""
          aria-hidden
          loading="lazy"
          decoding="async"
          className="absolute inset-0 w-full h-full object-cover"
        />
      ) : (
        <div className="absolute inset-0 grid place-items-center text-[10px] text-fg-dim">{m.type}</div>
      )}

      {pv.showPosters &&
        posterFrames.map((u, idx) => idx < pv.posterStart ? null : (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            key={`pf-${idx}`}
            src={proxyImage(u, accountId)}
            alt=""
            aria-hidden
            decoding="async"
            onLoad={hover.onPosterLoad}
            style={{ opacity: idx === pv.posterIdx ? 1 : 0 }}
            className="absolute inset-0 w-full h-full object-cover transition-opacity duration-200"
          />
        ))}

      {pv.showScrub &&
        Array.from({ length: SCRUB_FRAMES }).map((_, idx) => (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            key={`sf-${idx}`}
            src={proxyScrubFrame(rawVideoSrc, accountId, idx, m.duration, hover.state.sid)}
            alt=""
            aria-hidden
            decoding="async"
            {...hover.frameProps(idx)}
            style={{ opacity: idx === pv.scrubVisibleIdx ? 1 : 0 }}
            className="absolute inset-0 w-full h-full object-cover transition-opacity duration-200"
          />
        ))}

      {caption && <VaultAiCaptionOverlay caption={caption} />}

      {/* selection checkbox */}
      {selectMode && (
        <div
          className={`absolute top-1 right-1 w-5 h-5 rounded-full border-2 grid place-items-center text-[11px] ${
            checked ? "bg-accent border-accent text-white" : "bg-black/40 border-white/70 text-transparent"
          }`}
        >
          ✓
        </div>
      )}

      {/* per-folder manual order input */}
      {showOrder && (
        <input
          type="number"
          defaultValue={m._ai?.manual_order ?? ""}
          onClick={(e) => e.stopPropagation()}
          onBlur={(e) => {
            const v = e.target.value.trim();
            onOrder?.(m, v === "" ? null : Number(v));
          }}
          placeholder="#"
          title={`${EXTRA_LABEL}\nSet # to reorder this folder`}
          className="hidden md:block absolute top-1 left-1 w-10 px-1 py-0.5 rounded bg-black/60 text-white text-[11px] border border-white/40 outline-none"
        />
      )}

      {/* described dot — in a folder view the order input owns this corner on
       *  desktop, but that input is hidden on phone, so the dot takes it back. */}
      {described && (
        <div
          className={`absolute top-1 left-1 w-2.5 h-2.5 rounded-full bg-ok ring-1 ring-black/40${
            showOrder ? " md:hidden" : ""
          }`}
          title="described"
        />
      )}

      {/* The duration pill IS the play affordance, same as the picker. A nested
       *  <button> isn't legal HTML inside the clickable tile, so role="button" +
       *  stopPropagation keeps tile-click = open detail and pill-click = play. */}
      {isVideo && onPlay && (
        <span
          role="button"
          tabIndex={0}
          onClick={(e) => {
            e.stopPropagation();
            onPlay(m);
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === " ") {
              e.preventDefault();
              e.stopPropagation();
              onPlay(m);
            }
          }}
          title="Preview video"
          className="absolute bottom-1 right-1 px-1.5 py-0.5 rounded bg-black/60 hover:bg-black/85 text-white text-[10px] leading-none cursor-pointer select-none"
        >
          ▶ {dur}
        </span>
      )}
      {isVideo && !onPlay && (
        <div className="absolute bottom-1 right-1 px-1.5 py-0.5 rounded bg-black/60 text-white text-[10px] leading-none pointer-events-none">
          {dur || "▶"}
        </div>
      )}
      {m.type === "gif" && (
        <div className="absolute bottom-1 right-1 px-1.5 py-0.5 rounded bg-black/60 text-white text-[10px] leading-none pointer-events-none">
          GIF
        </div>
      )}
      {drmOnly && (
        <div className="absolute bottom-1 left-1 px-1 py-0.5 rounded bg-warn/80 text-white text-[9px] leading-none pointer-events-none">
          DRM
        </div>
      )}
    </div>
  );
}
