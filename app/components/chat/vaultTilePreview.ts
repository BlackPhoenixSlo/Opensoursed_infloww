import {
  posterCountdownSec,
  scrubCountdownSec,
  SCRUB_FRAMES,
  type HoverPreviewState,
} from "@/hooks/useHoverPreview";

export function evenFrameIndex(beat: number, frameCount: number, totalBeats = SCRUB_FRAMES): number {
  if (frameCount <= 1) return 0;
  return Math.min(frameCount - 1, Math.floor((beat / totalBeats) * frameCount));
}

export interface TileInput {
  id: number;
  posterCount: number;
  drmOnly: boolean;
  canBuild: boolean;
}

export interface TilePreview {
  showScrub: boolean;
  showPosters: boolean;
  posterStart: number;
  posterIdx: number;
  scrubVisibleIdx: number | null;
  posterBadge: string | null;
  scrubBadge: { kind: "hd" | "shimmer"; label: string } | null;
}

export function tilePreview(s: HoverPreviewState, t: TileInput): TilePreview {
  const hovering = s.id === t.id;
  // Skip poster frame 0: it is ~the static thumbnail already on the tile.
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
