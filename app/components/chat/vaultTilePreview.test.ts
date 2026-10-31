import { describe, expect, it } from "vitest";

import { hoverPreviewReducer, IDLE_HOVER, type HoverPreviewState } from "@/hooks/useHoverPreview";
import { tilePreview, type TileInput, type TilePreview } from "./vaultTilePreview";

const T0 = 1_000_000;
const hovering = (patch: Partial<HoverPreviewState> = {}): HoverPreviewState => ({
  ...hoverPreviewReducer(IDLE_HOVER, { type: "enter", id: 7, durationSec: 30, url: "u", sid: "s1", now: T0 }),
  ...patch,
});
const progressive: TileInput = { id: 7, posterCount: 5, drmOnly: false, canBuild: true };
const drm: TileInput = { id: 7, posterCount: 5, drmOnly: true, canBuild: false };
const noPosters: TileInput = { id: 7, posterCount: 0, drmOnly: false, canBuild: true };

describe("tilePreview", () => {
  const cases: [string, HoverPreviewState, TileInput, Partial<TilePreview>][] = [
    ["another tile hovered: plain thumb", hovering(), { ...progressive, id: 8 },
      { showScrub: false, showPosters: false, scrubVisibleIdx: null, posterBadge: null, scrubBadge: null }],
    ["idle: plain thumb", IDLE_HOVER, progressive,
      { showScrub: false, showPosters: false, posterBadge: null, scrubBadge: null }],
    ["drm: posters at once with their countdown, no storyboard", hovering(), drm,
      { showScrub: false, showPosters: true, posterBadge: "2.5s", scrubBadge: null }],
    ["drm: first poster painted drops the countdown", hovering({ posterLoaded: true }), drm,
      { showPosters: true, posterBadge: null }],
    ["cold, inside the grace: storyboard building, no posters yet", hovering(), progressive,
      { showScrub: true, showPosters: false, scrubVisibleIdx: null, scrubBadge: { kind: "hd", label: "7s" } }],
    ["cold after the grace: posters over the build, HD pill", hovering({ posterGrace: true, now: T0 + 1000 }), progressive,
      { showScrub: true, showPosters: true, posterBadge: "1.5s", scrubBadge: { kind: "hd", label: "6s" } }],
    ["poster ETA overdue reads …", hovering({ posterGrace: true, now: T0 + 3000 }), progressive,
      { posterBadge: "…" }],
    ["warm: storyboard visible on its frame, posters never shown", hovering({ scrub: "ready", frame: 4, posterGrace: true }), progressive,
      { showScrub: true, showPosters: false, scrubVisibleIdx: 4, posterBadge: null, scrubBadge: null }],
    ["failed frame 0: no badge, thumb fallback", hovering({ scrub: "failed" }), noPosters,
      { showScrub: true, scrubVisibleIdx: null, scrubBadge: null }],
    ["no posters: full-tile shimmer", hovering(), noPosters,
      { showScrub: true, showPosters: false, scrubBadge: { kind: "shimmer", label: "7s" } }],
    ["build overdue reads …", hovering({ now: T0 + 60_000 }), noPosters,
      { scrubBadge: { kind: "shimmer", label: "…" } }],
    ["no source: nothing to build", hovering(), { ...noPosters, canBuild: false },
      { showScrub: false, showPosters: false, scrubBadge: null }],
  ];
  it.each(cases)("%s", (_, state, tile, expected) => {
    expect(tilePreview(state, tile)).toMatchObject(expected);
  });

  it.each([
    // posters, beat → visible poster, first poster (frame 0 skipped when there is another)
    [5, 0, 1, 1], [5, 11, 4, 1], [1, 7, 0, 0], [0, 3, 0, 0], [2, 11, 1, 1],
  ])("%i posters on beat %i show poster %i, start %i", (posterCount, frame, idx, start) => {
    const pv = tilePreview(hovering({ frame }), { ...drm, posterCount });
    expect(pv.posterIdx).toBe(idx);
    expect(pv.posterStart).toBe(start);
  });
});
