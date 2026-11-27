import { describe, expect, it } from "vitest";

import { PLAYER_START, playerReducer, playerView, type PlayerAction, type PlayerState } from "./popupPlayer";
import type { OfferVideo } from "./popupOverlay";

const VIDEO: OfferVideo = { duration_s: 42, has_poster: true, cues: [{ t_s: 3, kind: "google" }] };
const run = (...actions: PlayerAction[]): PlayerState => actions.reduce(playerReducer, PLAYER_START);

describe("playerReducer", () => {
  it.each([
    ["a failed video", [{ type: "video_failed" }], { failed: true, t: 0 }],
    ["failed captions", [{ type: "captions_failed" }], { failed: true, t: 0 }],
    ["a time update", [{ type: "time", t: 12.5 }], { failed: false, t: 12.5 }],
    ["a non-finite time", [{ type: "time", t: Number.NaN }], PLAYER_START],
    ["time after a failure", [{ type: "video_failed" }, { type: "time", t: 4 }], { failed: true, t: 4 }],
  ] as [string, PlayerAction[], PlayerState][])("%s", (_, actions, want) => {
    expect(run(...actions)).toEqual(want);
  });

  it("repeat events keep the same state object", () => {
    const failed = run({ type: "video_failed" });
    expect(playerReducer(failed, { type: "captions_failed" })).toBe(failed);
    expect(playerReducer(PLAYER_START, { type: "time", t: 0 })).toBe(PLAYER_START);
  });
});

describe("playerView", () => {
  it.each([
    ["no video", null, PLAYER_START, { player: false, poster: false, overlay: false }],
    ["video with poster and cues", VIDEO, PLAYER_START, { player: true, poster: true, overlay: true }],
    ["no poster on the service", { ...VIDEO, has_poster: false }, PLAYER_START, { player: true, poster: false, overlay: true }],
    ["no cue table", { ...VIDEO, cues: null }, PLAYER_START, { player: true, poster: true, overlay: false }],
    ["a failed video or captions drops all", VIDEO, { ...PLAYER_START, failed: true }, { player: false, poster: false, overlay: false }],
  ] as [string, OfferVideo | null, PlayerState, ReturnType<typeof playerView>][])("%s", (_, video, state, want) => {
    expect(playerView(video, state)).toEqual(want);
  });
});
