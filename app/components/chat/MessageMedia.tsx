"use client";

/**
 * A bubble's media: the tile strip (MediaStrip), its click-to-zoom lightbox
 * (MediaLightbox) and the tile footprint (mediaTileBox, re-exported by
 * MessageList).
 */

import { useEffect, useState } from "react";
import { createPortal } from "react-dom";

import type { OFMedia, OFMessage } from "@/lib/relay";
import { proxyImage } from "@/lib/mediaUrl";
import { type FanId } from "@/lib/fanId";
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
  // Per-fan vault history → drives the green BOUGHT badge on outbound
  // PPV tiles. Only the outbound side queries — inbound media is the
  // fan's tip-back and our purchase signal doesn't apply.
  const fanVaultQ = useFanVaultHistory(accountId, fanId, isOutgoing && fanId != null);
  const isPPV = !!msg.price && msg.price > 0;
  const previewIds = msg.previews ?? [];
  // Attachments OF itself refused on a failed send; empty on every other
  // message. Same shape and same membership test as `previewIds` above — both
  // are "which of these tiles is special", and a bundle is small enough that a
  // Set would be ceremony.
  const refusedIds = msg._failedMediaIds ?? [];
  // Price label fits in the same 5-char corner pill as "BOUGHT" / "FREE".
  const priceLabel = msg.price != null ? ppvPriceLabel(msg.price) : "";
  // PPV gifts can attach 40+ items; rendering them all blows up the bubble
  // and floods the relay /img proxy. Cap at:
  //   • 2 tiles when the message is still locked (the lock icon repeats —
  //     beyond 2 it's pure noise)
  //   • 3 tiles for visible thumbnails (a clean 3-up row in the bubble)
  // The user expands to see the rest via the "+N more" pill.
  const LOCKED_CAP = 2;
  const IMAGE_CAP = 3;
  const cap = locked ? LOCKED_CAP : IMAGE_CAP;
  // The tiles OF actually refused, as an INTERSECTION with what this bubble
  // holds — never `_failedMediaIds` counted on its own. The count below and
  // the marks on the tiles are both driven from this one list, so they cannot
  // disagree; deriving the count from `msg.media.length` instead let the
  // footer claim "remove 1 of 4" over a row where nothing was marked.
  const sameId = (a: unknown, b: unknown) => a != null && b != null && String(a) === String(b);
  const refusedHere = items.filter((m) => m.id != null && refusedIds.some((r) => sameId(r, m.id)));
  // THE COLLAPSED VIEW CARRIES THE REFUSED TILES. Expansion is the operator's
  // alone again — a plain boolean, default closed — because the question "may a
  // tile OF named be hidden?" is no longer answered by state at all: a refused
  // tile is in the collapsed set by construction, so no click order can reach
  // it. Four earlier attempts all put that decision in a boolean and each fixed
  // one ordering while breaking another:
  //   • `expanded || refusedHidden` in `visible` — opened, but left `expanded`
  //     false, so neither "+N" nor "show less" rendered: pinned with no way back.
  //   • `useState(refusedHidden)` — read once at mount, and the live ordering
  //     mounts this strip on the PENDING bubble (appendLocal runs before the
  //     POST) then patches the row in place. Always read before the failure.
  //   • `override ?? refusedHidden` — tracked the prop, but nothing cleared the
  //     override, so one collapse taken mid-flight outranked every later refusal.
  //   • `refusedHidden || (override ?? false)` + a gated "show less" — no click
  //     could hide a mark, but the row then pinned open exactly as the first
  //     attempt did, on a bubble that can be neither retried away nor dismissed.
  // Slicing by MEMBERSHIP instead of by length dissolves the whole question: the
  // row collapses normally, "+N" and "show less" behave as they always did, and
  // the marked tile is simply always in view.
  const [expanded, setExpanded] = useState(false);
  // Pairs, not bare media: the collapsed set is no longer a prefix, so the
  // `visible[i] === items[i]` identity the lightbox relies on is gone. Each
  // entry carries its ORIGINAL index, which is what setLightboxIdx must store.
  const indexed = items.map((m, i) => [m, i] as const);
  const visible = expanded
    ? indexed
    : indexed.filter(([m, i]) => i < cap || (m.id != null && refusedIds.some((r) => sameId(r, m.id))));
  const hiddenCount = items.length - visible.length;
  // Click-to-zoom lightbox. Holds the index into `items` of the tile being
  // viewed full-res (null = closed) — taken from the pair above, never from the
  // map's own position, which no longer matches once a refused tile is pulled
  // forward into the collapsed set.
  const [lightboxIdx, setLightboxIdx] = useState<number | null>(null);
  // Tile geometry (T-GRID): media renders as small, fixed-footprint
  // thumbnails so a bundle never towers over the bubble. Each tile's box
  // is computed up-front by mediaTileBox() from the payload's width/height
  // — NOT from <img> onload — so the layout is definite from first paint
  // and never reflows when the async bytes land. The image and EVERY
  // placeholder (lock / processing / skeleton) read the SAME box, so the
  // swap-on-load causes zero movement. flex-wrap lets 1–3 little tiles sit
  // in a row and wrap; a single image is just one small box (no half-bubble
  // crop). The fallback box (used when OF didn't size the media) is also
  // what the "+N more" pill and any unknown-dim tile claim.
  const fallbackBox = mediaTileBox(compactMedia, null, null);
  const countLabel = mediaCountLabel(items);
  return (
    <div className="mt-2">
      {countLabel && <div className={cn(MP.ours.MessageList.mediaCount, "opacity-70")}>{countLabel}</div>}
      <div className="flex flex-wrap gap-1.5">
        {visible.map(([m, i]) => {
          const isVideo = isVideoMedia(m);
          // A video's tile shows its poster frame, never the clip itself.
          const rawThumb = isVideo
            ? stillUrl(m)
            : m.files?.thumb?.url || m.files?.source?.url || m.url || null;
          const thumb = proxyImage(rawThumb, accountId);
          // A video's link and click target is its clip, which also lets a
          // clip OF sent no still for open from a bare ▶ tile.
          const clip = isVideo ? clipUrl(m) : null;
          const fullRaw = clip || m.files?.source?.url || rawThumb;
          const full = proxyImage(fullRaw, accountId);
          // One source of truth for the tile footprint. Aspect-fit inside the
          // max box when OF gave us dims (box matches the true ratio, so
          // object-contain shows the whole image with no bars); a neutral
          // fallback box (letterboxed) when dims are null.
          const box = mediaTileBox(compactMedia, m.width, m.height);
          // Three-state badge mirrors the composer: green BOUGHT > gray FREE
          // (preview teaser) > red $X (PPV locked). Free-message outbound
          // (price=0) gets a badge only if the fan has bought it from us
          // at some earlier point.
          const fanEntry = m.id != null ? fanVaultQ.data?.by_media[String(m.id)] : undefined;
          // Only assert BOUGHT once the per-fan vault query has actually
          // resolved — otherwise a free (price=0) tile paints with no badge
          // and then flashes one in when the async lookup lands. `isSuccess`
          // distinguishes "not loaded" from "confirmed not bought".
          const wasBought = fanVaultQ.isSuccess && fanEntry?.was_purchased === true;
          const inPreviews = m.id != null && previewIds.some((pv) => sameId(pv, m.id));
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
          // OF named this exact id in `payload.removeFromInputMediaIds`, so say
          // it ON the tile: the failure line below can only repeat OF's
          // sentence, which talks about "media" without saying which — and a
          // bundle of near-identical thumbs is exactly where that fails the
          // operator (lib/sendFailure records what it cost on 2026-08-16).
          const wasRefused = m.id != null && refusedIds.some((r) => sameId(r, m.id));
          // Fansly locked media reports price=0 (so message-level `locked` is
          // false) but canView=false — treat per-media canView===false as
          // locked → 🔒 tile, not a grey skeleton. Guard on !isOutgoing: OF
          // media CAN carry canView:false, and Bubble's `locked`
          // deliberately exempts outgoing so a chatter always sees the PPV they
          // sent — mirror that. Our own Fansly media is canView:true, so this
          // costs nothing on Fansly. (§1d — no purchasing; §1e OF-regression fix.)
          const mLocked = locked || (m.canView === false && !isOutgoing);
          // Everything painted ON the tile, as one node. The three branches
          // below differ in what they wrap, not in the chrome they carry, so
          // the chrome is composed once here — including the outline, which is
          // an inset element rather than a class so no branch has to grow a
          // conditional className for it.
          const overlays = (
            <>
              {badge}
              {/* A locked tile keeps its 🔒 in the centre; a refused one's
               *  REMOVE bar covers the duration's corner. */}
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
            // Generic lock placeholder (incoming, unpaid). Same box as a
            // loaded tile would claim — its real dims don't matter until the
            // fan unlocks it, so the fallback/aspect box is fine.
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
            // Pre-thumb placeholder. Reserve the SAME box the loaded image
            // will take so the swap doesn't reflow.
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
              // Left-click opens the in-app full-res lightbox; ctrl/cmd/middle
              // click falls through to the href so power users can still pop a
              // raw tab. The href also keeps this keyboard-focusable.
              onClick={(e) => {
                if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;
                e.preventDefault();
                setLightboxIdx(i);
              }}
              style={{ width: box.w, height: box.h }}
              // Fixed box (mediaTileBox) gives a definite footprint that the
              // skeleton and loaded image both fill via h-full, so the swap on
              // load causes zero reflow. object-contain shows the whole image:
              // for known dims the box matches the ratio (no bars); for unknown
              // dims it letterboxes inside the neutral fallback box.
              className="relative block flex-none overflow-hidden rounded-md bg-black/20 cursor-zoom-in"
            >
              {overlays}
              {thumb && (
                <MediaTile
                  mediaId={m.id ?? null}
                  proxiedUrl={thumb}
                  fallbackUrl={rawThumb ?? ""}
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
            style={{ width: fallbackBox.w, height: fallbackBox.h }}
            className="flex-none rounded-md border border-border bg-bg-elev-1 hover:bg-bg-elev-2 text-xs text-fg-dim flex items-center justify-center gap-1"
          >
            +{hiddenCount}
          </button>
        )}
      </div>
      {/* The count lives HERE, beside the tiles it counts, and reads off the
       *  same `refusedHere` the marks do. In the footer it was computed from
       *  `_failedMediaIds.length` over `msg.media.length` — two different sets,
       *  free to disagree, and they did: an id past the render cap (or an id
       *  OF names that this bubble never held) produced a confident number
       *  over an unmarked row, which is the exact "nothing says which" state
       *  this feature exists to end. */}
      {refusedHere.length > 0 && (
        <div
          // Carries its OWN background. This sits INSIDE the bubble, and a
          // failed send's bubble is `bg-accent text-white` — bare `text-err`
          // measured 1.26:1 there (it was 5.6:1 in the footer it moved from),
          // i.e. the one number this feature exists to show, unreadable. Same
          // treatment as the REMOVE bar on the tiles, for the same reason.
          className={cn(MP.ours.MessageList.refusedCount, "inline-block bg-err/85 text-white")}
          title="These exact attachments were refused — drop them and re-send; a plain retry sends the same bundle."
        >
          remove {refusedHere.length} of {items.length}
        </div>
      )}
      {/* "show less" sits OUTSIDE the tile row so it keeps its natural button
       *  height instead of inheriting a tile box. It needs no refusal-aware
       *  gate: collapsing returns to a set that still CONTAINS every refused
       *  tile, so there is no longer a state where it could hide a mark — the
       *  membership slice above is what makes that true. */}
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

/** Full-resolution click-to-zoom overlay. Portaled to <body> so no ancestor
 *  transform/overflow can clip it. Click the dimmed backdrop (or the ×, or
 *  Esc) to close; clicking the image itself does NOT close. ←/→ (and the
 *  on-screen arrows) page through every item in the bundle, wrapping at the
 *  ends. Loads the source/full URL — a genuinely higher-res asset than the
 *  in-bubble thumbnail — via a plain <img> (the relay /img endpoint serves
 *  bytes straight to src; no need for MediaTile's hash/abort plumbing here). */
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
  // The Infloww palette when opened from Messages Pro; nothing anywhere else.
  const palette = useInflowwPalette();
  const [loaded, setLoaded] = useState(false);
  const count = items.length;
  const m = items[index];
  const fullRaw = m?.files?.source?.url || m?.files?.thumb?.url || m?.url || null;
  const full = proxyImage(fullRaw, accountId);
  // A video plays (or says it can't) in place of the image and its spinner.
  const isVideo = m != null && isVideoMedia(m);

  // Reset the spinner whenever we page to a different image.
  useEffect(() => {
    setLoaded(false);
  }, [index]);

  // Esc closes; ←/→ page (wrap). Bound at the document so it works no matter
  // where focus landed after the tile click — except on a focused video, whose
  // own controls seek with ←/→.
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
        className="absolute top-4 right-4 z-10 w-10 h-10 grid place-items-center rounded-full bg-white/10 hover:bg-white/20 text-white text-2xl leading-none"
      >
        ×
      </button>

      {count > 1 && (
        <>
          <button
            type="button"
            aria-label="Previous image"
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

      {/* Clicking the image must NOT close — only the backdrop does. */}
      <div className={cn(MP.ours.MessageList.zoomFrame, "relative")} onClick={(e) => e.stopPropagation()}>
        {/* Keyed by position: paging away unmounts the video, which pauses it. */}
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

/** Side length (px) of an in-bubble media tile. compact → small, normal →
 *  larger. The two tile sizes are the only knobs. */
const COMPACT_TILE_PX = 64;
const NORMAL_TILE_PX = 155;

/** Displayed pixel footprint of an in-bubble media tile. Pure + exported as
 *  the testable seam for the T-GRID layout: the image AND every placeholder
 *  (lock / processing / skeleton) read the SAME box, so the async byte swap
 *  never reflows.
 *
 *  EVERY tile is a FIXED SQUARE — the size depends ONLY on the compact toggle,
 *  NOT on the media's width/height. This is deliberate: OF dimensions arrive
 *  late and best-effort (the client-measured PATCH lands after first paint),
 *  so any box derived from them would RESIZE when the dims show up — that's
 *  the lazy-load bounce. A constant square is reserved identically before and
 *  after the bytes/dims arrive, so messages never shift. The image fills the
 *  square via object-contain (whole image, letterboxed) so nothing is cropped.
 *  width/height are accepted (and ignored) so the signature stays stable. */
export function mediaTileBox(
  compact: boolean,
  _width?: number | null,
  _height?: number | null,
): { w: number; h: number } {
  const side = compact ? COMPACT_TILE_PX : NORMAL_TILE_PX;
  return { w: side, h: side };
}
