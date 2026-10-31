/**
 * The swipe gesture `useSwipe` runs, as a pure state machine: `swipeReducer`
 * takes the finger's events and returns the next state and the effects the
 * hook carries out on the DOM (paint the panel, run its settle, call
 * `onSwipe`). The release physics (projection, rubber band, spring) are pure
 * helpers here too.
 *
 * Phases: `idle` (no finger, nothing moving); `pending` (a finger down, its
 * intent not known yet); `caught` (a finger took hold of a panel mid-motion:
 * springing back, or still in its CSS slide-in; intent not known yet);
 * `locked` (the finger moves sideways, within 30° of horizontal; a sheet
 * follows it); `springBack` (no finger, the panel springs back open);
 * `leaving` (no finger, a decided dismissal slides off; it takes no touch).
 * A touch moves the panel (`sheet`) or not (plain: only its release decides;
 * no panel, or reduced motion).
 * A dismissal calls `onSwipe` (effect `fire`) once, on leaving `leaving`:
 * when its settle finishes or the hook is torn down, whichever is first.
 */

export type SwipeDir = "left" | "right";

/** Past this many px a swipe counts at any speed. */
export const SWIPE_MIN_PX = 50;
/** A quick flick counts from here, at `SWIPE_FLICK_PX_PER_MS` or faster. */
export const SWIPE_FLICK_MIN_PX = 25;
export const SWIPE_FLICK_PX_PER_MS = 0.4;
/** At most 30° off horizontal: |dy| <= |dx| * tan(30°). */
export const SWIPE_MAX_SLOPE = Math.tan(Math.PI / 6);
/** Dismiss once the projected release passes this share of the panel's width. */
export const SWIPE_DISMISS_AT = 0.75;
/** UIScrollView's `.normal` deceleration (0.998/ms) coasts v·499ms; a sheet is
 *  short (≤420px), so we project a 300ms coast: between `.fast` (99ms) and `.normal`. */
export const SWIPE_PROJECT_MS = 300;
/** Release velocity is measured over the finger's last this-many ms. */
export const SWIPE_VELOCITY_WINDOW_MS = 100;
/** Past the open position the panel gives at most a third of its width. */
export const RUBBER_BAND = 3;
/** The settle spring: stiffness 400, damping 36, mass 1 (ζ = 0.9, a hair under
 *  critical). Its keyframes are cut at `maxMs`: a spring still moving then
 *  jumps the rest of the way (under a px for a sheet's travel). */
export const SPRING = { stiffness: 400, damping: 36, mass: 1, maxMs: 350 } as const;
/** A dismissal's slide off screen is compressed to at most this, so release to
 *  unmount (with the owner's re-render) stays within 350ms. */
export const DISMISS_MS = 280;
/** A dismissed panel springs toward this much past its width (so it is still
 *  moving briskly as it leaves); it is done, and unmounts, at its width.
 *  Mirrored by globals.css `sheet-out-left/right` (`calc(±100% ± 40px)`), the
 *  button/Esc exit: keep the two equal. */
export const OUT_PX = 40;
/** Below this the finger's intent is not known yet. */
export const LOCK_PX = 10;

/** The swipe a finger's move (`dx`, `dy` px over `ms`) makes, or null. */
export function swipeDirection(dx: number, dy: number, ms: number): SwipeDir | null {
  const dist = Math.abs(dx);
  if (Math.abs(dy) > dist * SWIPE_MAX_SLOPE) return null;
  const fast = dist >= SWIPE_FLICK_MIN_PX && dist / Math.max(ms, 1) >= SWIPE_FLICK_PX_PER_MS;
  if (dist < SWIPE_MIN_PX && !fast) return null;
  return dx > 0 ? "right" : "left";
}

/** Where a panel `offset` px toward dismissal (negative: past open), let go at
 *  `velocity` px/ms (positive: toward dismissal), would coast to. */
export function projectRelease(offset: number, velocity: number): number {
  return offset + velocity * SWIPE_PROJECT_MS;
}

/** Whether a release dismisses a panel `width` px wide: a flick back always
 *  cancels, a flick out (from `SWIPE_FLICK_MIN_PX`) always dismisses, and
 *  otherwise the projected release must reach `dismissAt` of the width. */
export function releaseDismisses(offset: number, velocity: number, width: number, dismissAt = SWIPE_DISMISS_AT): boolean {
  if (velocity <= -SWIPE_FLICK_PX_PER_MS) return false;
  if (velocity >= SWIPE_FLICK_PX_PER_MS && offset >= SWIPE_FLICK_MIN_PX) return true;
  return projectRelease(offset, velocity) >= dismissAt * width;
}

/** A pull `over` px past the open position, as the panel shows it: it gives
 *  less the further it goes, never more than `width / RUBBER_BAND`. */
export function rubberBand(over: number, width: number): number {
  if (!width) return 0;
  return over / (1 + (Math.abs(over) * RUBBER_BAND) / width);
}

/** The finger's px/ms over its last `SWIPE_VELOCITY_WINDOW_MS` up to `now`
 *  (0 if it held still that long). */
export function releaseVelocity(samples: { x: number; t: number }[], now: number): number {
  const recent = samples.filter((s) => now - s.t <= SWIPE_VELOCITY_WINDOW_MS);
  if (recent.length < 2) return 0;
  const a = recent[0], b = recent[recent.length - 1];
  return b.t > a.t ? (b.x - a.x) / (b.t - a.t) : 0;
}

/** `SPRING` from `from` to `to` px, starting at `velocity` px/ms, sampled each
 *  ~16ms (`t` ms from the start); `ms` is when it rests (within 0.5px), at most
 *  `SPRING.maxMs`, and the last frame is always `to`. With `stopAt` (between
 *  `from` and `to`) it ends where it first reaches `stopAt` instead, and that is
 *  the last frame (a panel leaving the screen is done once it is off). */
export function springKeyframes(from: number, to: number, velocity: number, stopAt?: number): { frames: { x: number; t: number }[]; ms: number } {
  const { stiffness, damping, mass, maxMs } = SPRING;
  const frames = [{ x: from, t: 0 }];
  const end = stopAt ?? to;
  const side = Math.sign(end - from);
  let x = from, v = velocity * 1000; // px/s
  for (let t = 1; t <= maxMs; t++) {
    v += ((-stiffness * (x - to) - damping * v) / mass) / 1000;
    x += v / 1000;
    const reached = stopAt !== undefined && side !== 0 && (x - end) * side >= 0;
    if (reached || (Math.abs(x - to) < 0.5 && Math.abs(v) < 20) || t === maxMs) {
      frames.push({ x: end, t });
      return { frames, ms: t };
    }
    if (t % 16 === 0) frames.push({ x, t });
  }
  return { frames, ms: maxMs };
}

/** The settle from `from` to `to` (a dismissal when `to` > 0, done at `width`):
 *  its keyframes, when the spring rests (`ms`, ≤ 1: nothing to animate) and how
 *  long it plays (a dismissal at most `DISMISS_MS`). */
export function settlePlan(from: number, to: number, velocity: number, width: number) {
  const out = to > 0;
  // Already off screen (dragged all the way out): nothing left to animate.
  if (out && from >= width) return { frames: [], ms: 0, duration: 0 };
  const { frames, ms } = springKeyframes(from, to, velocity, out ? width : undefined);
  return { frames, ms, duration: out ? Math.min(ms, DISMISS_MS) : ms };
}

/** Where the panel's offset passes through (`p` px, backdrop opacity `o`). */
export type Anchor = { p: number; o: number };

/** The backdrop's opacity for a panel `p` px toward dismissal: 1 at open, 0 at
 *  `width`, through `anchor` (where a caught panel was and the opacity its
 *  backdrop showed then: mid slide-in the two need not agree), so taking hold
 *  of it never makes the backdrop jump. */
export function backdropOpacity(p: number, width: number, anchor: Anchor): number {
  if (p <= 0) return 1;
  if (p <= anchor.p) return 1 - ((1 - anchor.o) * p) / anchor.p;
  return Math.max(0, anchor.o * (1 - (p - anchor.p) / Math.max((width || 1) - anchor.p, 1)));
}

export type Phase = "idle" | "pending" | "caught" | "locked" | "springBack" | "leaving";

export interface GestureState {
  phase: Phase;
  /** The direction that dismisses (`onSwipe`) and its `dismissAt`: fixed for the hook's life. */
  dir: SwipeDir;
  dismissAt: number;
  /** The finger's start, while it is down. */
  start: { x: number; y: number; t: number } | null;
  /** This touch moves the panel (a sheet shown, motion allowed), `width` px wide
   *  (read at the touch's start); null: a plain touch, only its release decides. */
  sheet: { width: number } | null;
  /** The panel's offset toward dismissal (px; negative is past open) and where
   *  this touch caught it. */
  pos: number;
  base: number;
  anchor: Anchor;
  /** The finger's recent positions, for its release velocity. */
  samples: { x: number; t: number }[];
  /** Which settle is current: a `settled` from an older one is ignored. */
  run: number;
}

export type GestureAction =
  /** A touch the hook accepted (one finger, below lg, not ignored). `sheet`: it
   *  moves the panel, `width` px wide (> 0); `caught` is where the panel was,
   *  mid-motion, and the opacity its backdrop showed. A finger still down must
   *  be cancelled first. */
  | { type: "start"; x: number; y: number; t: number; sheet?: { width: number; caught?: { pos: number; opacity: number } } }
  | { type: "move"; x: number; y: number; t: number }
  | { type: "end"; x: number; y: number; t: number }
  /** Not a swipe after all: the platform took it (touchcancel), a second finger. */
  | { type: "cancel" }
  /** The browser scrolled; `own`: what the finger started on, or the page. */
  | { type: "scroll"; own: boolean }
  /** Settle `run` finished. */
  | { type: "settled"; run: number }
  /** The hook is torn down (disabled, unmounted). */
  | { type: "teardown" };

export type GestureEffect =
  /** Show the panel (`width` px wide) `pos` px toward dismissal, its backdrop faded to match. */
  | { type: "paint"; pos: number; width: number }
  /** The panel is about to follow the finger (will-change on). */
  | { type: "hold" }
  /** Spring the panel from `from` to `to` at `velocity`; a dismissal (`to` > 0)
   *  first stops taking taps. Report the end as `settled` with `run`. */
  | { type: "settle"; from: number; to: number; velocity: number; width: number; run: number }
  /** Cancel the panel's running animations (a settle, its CSS slide-in). */
  | { type: "stop" }
  /** The panel is at rest (will-change off). */
  | { type: "rest" }
  | { type: "fire" };

export type GestureStep = { state: GestureState; effects: GestureEffect[] };

export function initialGesture(dir: SwipeDir, dismissAt = SWIPE_DISMISS_AT): GestureState {
  return {
    phase: "idle", dir, dismissAt, start: null, sheet: null,
    pos: 0, base: 0, anchor: { p: 0, o: 1 }, samples: [], run: 0,
  };
}

/** A finger is down on this gesture. */
export const fingerDown = (s: GestureState) => s.phase === "pending" || s.phase === "caught" || s.phase === "locked";

const same = (s: GestureState): GestureStep => ({ state: s, effects: [] });
const toIdle = (s: GestureState): GestureState => ({ ...s, phase: "idle", start: null, samples: [] });

function settle(s: GestureState, width: number, to: number, velocity: number): GestureStep {
  const run = s.run + 1;
  return {
    state: { ...s, phase: to > 0 ? "leaving" : "springBack", start: null, samples: [], pos: to, run },
    effects: [{ type: "settle", from: s.pos, to, velocity, width, run }],
  };
}

/** Not a swipe after all (it turned vertical, scrolled, or the platform took
 *  it): a panel this touch moved or caught springs back open. */
function abandon(s: GestureState): GestureStep {
  if (!fingerDown(s)) return same(s);
  if (s.sheet && s.phase !== "pending") return settle(s, s.sheet.width, 0, 0);
  return same(toIdle(s));
}

export function swipeReducer(s: GestureState, a: GestureAction): GestureStep {
  const sign = s.dir === "right" ? 1 : -1;
  switch (a.type) {
    case "start": {
      // A panel already leaving takes no touch (and gets none: it lets taps through).
      if (s.phase === "leaving") return same(s);
      const caught = a.sheet?.caught;
      const pos = caught?.pos ?? 0;
      const anchor = caught && pos > 0 && caught.opacity >= 0 && caught.opacity <= 1
        ? { p: pos, o: caught.opacity } : { p: 0, o: 1 };
      return {
        state: {
          ...s, phase: caught ? "caught" : "pending", start: { x: a.x, y: a.y, t: a.t },
          sheet: a.sheet ? { width: a.sheet.width } : null, pos, base: pos, anchor, samples: [{ x: a.x, t: a.t }],
        },
        // Caught mid-motion: stop it where it is and hold it there.
        effects: a.sheet && caught ? [{ type: "stop" }, { type: "hold" }, { type: "paint", pos, width: a.sheet.width }] : [],
      };
    }
    case "move": {
      if (!fingerDown(s) || !s.start) return same(s);
      const dx = a.x - s.start.x, dy = a.y - s.start.y;
      const effects: GestureEffect[] = [];
      let phase = s.phase;
      if (phase !== "locked") {
        if (Math.max(Math.abs(dx), Math.abs(dy)) < LOCK_PX) return same(s);
        // Sideways only within 30° of horizontal; anything steeper is a scroll: not ours.
        if (Math.abs(dy) > Math.abs(dx) * SWIPE_MAX_SLOPE) return abandon(s);
        phase = "locked";
        if (s.sheet) effects.push({ type: "hold" });
      } else if (!s.sheet && Math.abs(dy) >= Math.abs(dx)) {
        // A plain swipe that turns vertical is a scroll from here on. A sheet held
        // sideways stays held: its finger may drift diagonally.
        return abandon(s);
      }
      const samples = [...s.samples, { x: a.x, t: a.t }].slice(-24);
      if (!s.sheet) return { state: { ...s, phase, samples }, effects };
      const raw = s.base + sign * dx;
      const pos = raw >= 0 ? raw : rubberBand(raw, s.sheet.width);
      return { state: { ...s, phase, samples, pos }, effects: [...effects, { type: "paint", pos, width: s.sheet.width }] };
    }
    case "end": {
      if (!fingerDown(s) || !s.start) return same(s);
      if (s.phase !== "locked" || !s.sheet) {
        if (s.phase === "caught") return abandon(s); // a tap on a caught panel: it carries on
        const hit = swipeDirection(a.x - s.start.x, a.y - s.start.y, a.t - s.start.t) === s.dir;
        return { state: toIdle(s), effects: hit ? [{ type: "fire" }] : [] };
      }
      const samples = [...s.samples, { x: a.x, t: a.t }];
      const velocity = sign * releaseVelocity(samples, a.t);
      const { width } = s.sheet;
      const hit = releaseDismisses(s.pos, velocity, width, s.dismissAt);
      return settle(s, width, hit ? width + OUT_PX : 0, velocity);
    }
    case "cancel":
      return abandon(s);
    case "scroll":
      // Once a sheet is held sideways an inner scroll no longer lets go of it.
      if (!a.own || (s.phase === "locked" && s.sheet)) return same(s);
      return abandon(s);
    case "settled":
      if (a.run !== s.run) return same(s);
      if (s.phase === "leaving") return { state: toIdle(s), effects: [{ type: "rest" }, { type: "fire" }] };
      if (s.phase === "springBack") return { state: toIdle(s), effects: [{ type: "rest" }] };
      return same(s);
    case "teardown":
      // Torn down mid-dismissal: finish it now, so the panel is not left off
      // screen and untouchable with its owner never told.
      if (s.phase === "leaving") return { state: toIdle(s), effects: [{ type: "stop" }, { type: "rest" }, { type: "fire" }] };
      // Mid-drag: put the panel back.
      if (s.sheet && (s.phase === "locked" || s.phase === "caught")) {
        return { state: { ...toIdle(s), pos: 0 }, effects: [{ type: "paint", pos: 0, width: s.sheet.width }, { type: "rest" }] };
      }
      // A spring back finishes on its own, but its `settled` will meet an idle gesture: end its hold now.
      if (s.phase === "springBack") return { state: toIdle(s), effects: [{ type: "rest" }] };
      return same(toIdle(s));
  }
}
