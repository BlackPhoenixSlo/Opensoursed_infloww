/**
 * What one vault picker tile shows for the current hover preview, as a pure
 * read of the useHoverPreview state. VaultPicker renders the fields only.
 *
 *   • Storyboard (12 ffmpeg frames): mounted as soon as a progressive video is
 *     hovered so the build starts, visible once a frame lands.
 *   • OF poster frames: the only preview for a DRM video; for a progressive
 *     one they cover a cold build after POSTER_GRACE_MS (a warm storyboard is
 *     ready before the grace, so posters never fetch).
 *   • Badges: the poster decimal countdown until the first poster paints, and
 *     the storyboard ETA — a corner "HD" pill over posters, else a shimmer.
 */
import {
  posterCountdownSec,
  scrubCountdownSec,
  SCRUB_FRAMES,
  type HoverPreviewState,
} from "@/hooks/useHoverPreview";

/** Map a slideshow beat (0..totalBeats-1) onto one of `frameCount` available
 *  frames, spread EVENLY. Used so the N (≤9) OF poster frames fill the same
 *  12-beat cursor the 12-frame ffmpeg storyboard uses — no `% N` repeat-jump,
 *  and never an out-of-range index (which would render a black/empty <img>).
 *  At frameCount === totalBeats it's the identity. */
export function evenFrameIndex(beat: number, frameCount: number, totalBeats = SCRUB_FRAMES): number {
  if (frameCount <= 1) return 0;
  return Math.min(frameCount - 1, Math.floor((beat / totalBeats) * frameCount));
}

export interface TileInput {
  /** The tile's vault media id. */
  id: number;
  /** OF poster frames the tile can show (0 without an account to proxy them). */
  posterCount: number;
  drmOnly: boolean;
  /** A progressive source and an account: the storyboard can be built. */
  canBuild: boolean;
}

export interface TilePreview {
  /** Mount the storyboard frames. */
  showScrub: boolean;
  /** Mount the poster frames from `posterStart`. */
  showPosters: boolean;
  posterStart: number;
  /** The visible poster frame. */
  posterIdx: number;
  /** The visible storyboard frame; null until one has painted. */
  scrubVisibleIdx: number | null;
  /** Poster decimal countdown ("2.3s" / "…") until the first poster paints. */
  posterBadge: string | null;
  /** Storyboard ETA while it builds: a corner pill over posters, else a shimmer. */
  scrubBadge: { kind: "hd" | "shimmer"; label: string } | null;
}

export function tilePreview(s: HoverPreviewState, t: TileInput): TilePreview {
  const hovering = s.id === t.id;
  // Skip poster frame 0 — it's ~the static thumbnail already on the tile — so
  // the preview starts on something new.
  const posterStart = t.posterCount > 1 ? 1 : 0;
  const showScrub = hovering && t.canBuild;
  const showPosters = hovering && t.posterCount > 0
    && (t.drmOnly || (s.scrub !== "ready" && s.posterGrace));
  const posterIdx = t.posterCount > 0
    ? posterStart + evenFrameIndex(s.frame, t.posterCount - posterStart)
    : 0;
  const poster = posterCountdownSec(s);
  const scrub = scrubCountdownSec(s);
  return {
    showScrub,
    showPosters,
    posterStart,
    posterIdx,
    scrubVisibleIdx: showScrub && s.scrub === "ready" ? s.frame : null,
    posterBadge: showPosters && !s.posterLoaded ? (poster > 0 ? `${poster.toFixed(1)}s` : "…") : null,
    scrubBadge: showScrub && s.scrub === "loading"
      ? {
          kind: t.posterCount > 0 ? "hd" : "shimmer",
          label: scrub > 0 ? `${Math.ceil(scrub)}s` : "…",
        }
      : null,
  };
}
