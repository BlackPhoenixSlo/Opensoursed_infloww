/**
 * A vault gif's loop on its picker tile (VaultGifLoop.tsx): which layer shows.
 * OnlyFans stores a gif as a short .mp4 (service/of_shapes.py `still_url`), so a
 * tile showing only the still never moves, and one whose first frame is black is
 * a black tile. The video paints over the still only while it actually plays;
 * paused, buffering or not attached, the still shows. An error is the still for good.
 */

export interface GifLoopState {
  /** The src is on the element (first on screen, or hovered under reduced motion). */
  attached: boolean;
  /** The element fired `playing` and has not paused since. */
  playing: boolean;
  /** The element errored. */
  failed: boolean;
}

export type GifLoopAction =
  | { type: "attach" }
  | { type: "playing" }
  | { type: "paused" }
  | { type: "error" };

export const GIF_LOOP_INIT: GifLoopState = { attached: false, playing: false, failed: false };

export function gifLoopReducer(s: GifLoopState, a: GifLoopAction): GifLoopState {
  if (s.failed) return s;
  switch (a.type) {
    case "attach":
      return s.attached ? s : { ...s, attached: true };
    case "playing":
      return s.attached && !s.playing ? { ...s, playing: true } : s;
    case "paused":
      return s.playing ? { ...s, playing: false } : s;
    case "error":
      return { attached: false, playing: false, failed: true };
  }
}

/** Mount the <video> (it carries the observer before it has a src). */
export const gifMounted = (s: GifLoopState) => !s.failed;
/** Paint the video over the still. */
export const gifVisible = (s: GifLoopState) => s.attached && s.playing && !s.failed;
