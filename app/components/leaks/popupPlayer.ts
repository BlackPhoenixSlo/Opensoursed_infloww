import type { OfferVideo } from "./popupOverlay";

export type PlayerState = { failed: boolean; t: number };
export type PlayerAction =
  | { type: "video_failed" }
  | { type: "captions_failed" }
  | { type: "time"; t: number };

export const PLAYER_START: PlayerState = { failed: false, t: 0 };

export function playerReducer(state: PlayerState, action: PlayerAction): PlayerState {
  switch (action.type) {
    case "video_failed":
    case "captions_failed":
      return state.failed ? state : { ...state, failed: true };
    case "time":
      return Number.isFinite(action.t) && action.t !== state.t ? { ...state, t: action.t } : state;
  }
}

export function playerView(video: OfferVideo | null, state: PlayerState): { player: boolean; poster: boolean; overlay: boolean } {
  const player = !!video && !state.failed;
  return { player, poster: player && video.has_poster, overlay: player && !!video.cues };
}
