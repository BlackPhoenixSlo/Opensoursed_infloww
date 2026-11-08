/**
 * A vault gif's loop on its picker tile (VaultGifLoop.tsx): which layer shows.
 * OnlyFans stores a gif as a short .mp4 (service/of_shapes.py `still_url`), so a
 * tile showing only the still never moves, and one whose first frame is black is
 * a black tile. The video paints over the still only while it actually plays;
 * paused, buffering or not attached, the still shows. An error is the still for good.
 * Off screen the clip is detached (src removed, decoder buffers released), and at most MAX_GIF_LOOPS hold one at
 * once across every tile (`gifSlots`).
 */

export interface GifLoopState {
  /** The src is on the element (on screen with a slot, or hovered under reduced motion). */
  attached: boolean;
  /** The element fired `playing` and has not paused since. */
  playing: boolean;
  /** The element errored. */
  failed: boolean;
}

export type GifLoopAction =
  | { type: "attach" }
  /** Off screen (or unhovered): the src comes off. */
  | { type: "detach" }
  | { type: "playing" }
  | { type: "paused" }
  | { type: "error" };

export const GIF_LOOP_INIT: GifLoopState = { attached: false, playing: false, failed: false };

export function gifLoopReducer(s: GifLoopState, a: GifLoopAction): GifLoopState {
  if (s.failed) return s;
  switch (a.type) {
    case "attach":
      return s.attached ? s : { ...s, attached: true };
    case "detach":
      return s.attached ? { ...s, attached: false, playing: false } : s;
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

/** How many gif loops may hold a video decoder at once, across every tile: a phone has a handful (iOS Safari), and
 *  a 500-item vault has no cap of its own. */
export const MAX_GIF_LOOPS = 4;

/** The loops' slots. A tile on screen asks (`acquire`): granted now (true), or queued, and `onGrant` runs when a slot
 *  frees, in ask order. `release` on leave, error or unmount: frees its slot (granting the next in line) or leaves the
 *  queue. */
export function gifSlots(max: number) {
  const held = new Set<object>();
  // Insertion-ordered: the first to ask is the first granted.
  const queue = new Map<object, () => void>();
  return {
    acquire(who: object, onGrant: () => void): boolean {
      if (held.has(who)) return true;
      if (held.size < max) {
        held.add(who);
        return true;
      }
      queue.set(who, onGrant);
      return false;
    },
    release(who: object): void {
      queue.delete(who);
      if (!held.delete(who)) return;
      const next = queue.entries().next();
      if (next.done) return;
      const [w, grant] = next.value;
      queue.delete(w);
      held.add(w);
      grant();
    },
    held: () => held.size,
    queued: () => queue.size,
  };
}
