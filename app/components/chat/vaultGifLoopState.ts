// OF stores a gif as a short .mp4, so a still never moves; the video shows only while it actually plays.
export interface GifLoopState {
  attached: boolean;
  playing: boolean;
  failed: boolean;
}

export type GifLoopAction =
  | { type: "attach" }
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

export const gifMounted = (s: GifLoopState) => !s.failed;
export const gifVisible = (s: GifLoopState) => s.attached && s.playing && !s.failed;

// A phone (iOS Safari) has a handful of video decoders; a 500-item vault has no cap of its own.
export const MAX_GIF_LOOPS = 4;

export function gifSlots(max: number) {
  const held = new Set<object>();
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
