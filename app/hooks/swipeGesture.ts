export type SwipeDir = "left" | "right";

export const SWIPE_MIN_PX = 50;
export const SWIPE_FLICK_MIN_PX = 25;
export const SWIPE_FLICK_PX_PER_MS = 0.4;
export const SWIPE_MAX_SLOPE = Math.tan(Math.PI / 6);
export const SWIPE_DISMISS_AT = 0.75;
// UIScrollView .normal coasts v*499ms; a short sheet projects 300ms, between .fast and .normal.
export const SWIPE_PROJECT_MS = 300;
export const SWIPE_VELOCITY_WINDOW_MS = 100;
export const RUBBER_BAND = 3;
export const SPRING = { stiffness: 400, damping: 36, mass: 1, maxMs: 350 } as const;
export const DISMISS_MS = 280;
// Mirrored by globals.css sheet-out-left/right (calc(+-100% +- 40px)): keep equal.
export const OUT_PX = 40;
export const LOCK_PX = 10;

export function swipeDirection(dx: number, dy: number, ms: number): SwipeDir | null {
  const dist = Math.abs(dx);
  if (Math.abs(dy) > dist * SWIPE_MAX_SLOPE) return null;
  const fast = dist >= SWIPE_FLICK_MIN_PX && dist / Math.max(ms, 1) >= SWIPE_FLICK_PX_PER_MS;
  if (dist < SWIPE_MIN_PX && !fast) return null;
  return dx > 0 ? "right" : "left";
}

export function projectRelease(offset: number, velocity: number): number {
  return offset + velocity * SWIPE_PROJECT_MS;
}

export function releaseDismisses(offset: number, velocity: number, width: number, dismissAt = SWIPE_DISMISS_AT): boolean {
  if (velocity <= -SWIPE_FLICK_PX_PER_MS) return false;
  if (velocity >= SWIPE_FLICK_PX_PER_MS && offset >= SWIPE_FLICK_MIN_PX) return true;
  return projectRelease(offset, velocity) >= dismissAt * width;
}

export function rubberBand(over: number, width: number): number {
  if (!width) return 0;
  return over / (1 + (Math.abs(over) * RUBBER_BAND) / width);
}

export function releaseVelocity(samples: { x: number; t: number }[], now: number): number {
  const recent = samples.filter((s) => now - s.t <= SWIPE_VELOCITY_WINDOW_MS);
  if (recent.length < 2) return 0;
  const a = recent[0], b = recent[recent.length - 1];
  return b.t > a.t ? (b.x - a.x) / (b.t - a.t) : 0;
}

export function springKeyframes(from: number, to: number, velocity: number, stopAt?: number): { frames: { x: number; t: number }[]; ms: number } {
  const { stiffness, damping, mass, maxMs } = SPRING;
  const frames = [{ x: from, t: 0 }];
  const end = stopAt ?? to;
  const side = Math.sign(end - from);
  let x = from, v = velocity * 1000;
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

export function settlePlan(from: number, to: number, velocity: number, width: number) {
  const out = to > 0;
  if (out && from >= width) return { frames: [], ms: 0, duration: 0 };
  const { frames, ms } = springKeyframes(from, to, velocity, out ? width : undefined);
  return { frames, ms, duration: out ? Math.min(ms, DISMISS_MS) : ms };
}

export type Anchor = { p: number; o: number };

export function backdropOpacity(p: number, width: number, anchor: Anchor): number {
  if (p <= 0) return 1;
  if (p <= anchor.p) return 1 - ((1 - anchor.o) * p) / anchor.p;
  return Math.max(0, anchor.o * (1 - (p - anchor.p) / Math.max((width || 1) - anchor.p, 1)));
}

export type Phase = "idle" | "pending" | "caught" | "locked" | "springBack" | "leaving";

export interface GestureState {
  phase: Phase;
  dir: SwipeDir;
  dismissAt: number;
  start: { x: number; y: number; t: number } | null;
  sheet: { width: number } | null;
  pos: number;
  base: number;
  anchor: Anchor;
  samples: { x: number; t: number }[];
  run: number;
}

export type GestureAction =
  | { type: "start"; x: number; y: number; t: number; sheet?: { width: number; caught?: { pos: number; opacity: number } } }
  | { type: "move"; x: number; y: number; t: number }
  | { type: "end"; x: number; y: number; t: number }
  | { type: "cancel" }
  | { type: "scroll"; own: boolean }
  | { type: "settled"; run: number }
  | { type: "teardown" };

export type GestureEffect =
  | { type: "paint"; pos: number; width: number }
  | { type: "hold" }
  | { type: "settle"; from: number; to: number; velocity: number; width: number; run: number }
  | { type: "stop" }
  | { type: "rest" }
  | { type: "fire" };

export type GestureStep = { state: GestureState; effects: GestureEffect[] };

export function initialGesture(dir: SwipeDir, dismissAt = SWIPE_DISMISS_AT): GestureState {
  return {
    phase: "idle", dir, dismissAt, start: null, sheet: null,
    pos: 0, base: 0, anchor: { p: 0, o: 1 }, samples: [], run: 0,
  };
}

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

function abandon(s: GestureState): GestureStep {
  if (!fingerDown(s)) return same(s);
  if (s.sheet && s.phase !== "pending") return settle(s, s.sheet.width, 0, 0);
  return same(toIdle(s));
}

export function swipeReducer(s: GestureState, a: GestureAction): GestureStep {
  const sign = s.dir === "right" ? 1 : -1;
  switch (a.type) {
    case "start": {
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
        if (Math.abs(dy) > Math.abs(dx) * SWIPE_MAX_SLOPE) return abandon(s);
        phase = "locked";
        if (s.sheet) effects.push({ type: "hold" });
      } else if (!s.sheet && Math.abs(dy) >= Math.abs(dx)) {
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
        if (s.phase === "caught") return abandon(s);
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
      if (!a.own || (s.phase === "locked" && s.sheet)) return same(s);
      return abandon(s);
    case "settled":
      if (a.run !== s.run) return same(s);
      if (s.phase === "leaving") return { state: toIdle(s), effects: [{ type: "rest" }, { type: "fire" }] };
      if (s.phase === "springBack") return { state: toIdle(s), effects: [{ type: "rest" }] };
      return same(s);
    // Torn down mid-dismissal: finish it now so the panel is not left off screen with its owner never told.
    case "teardown":
      if (s.phase === "leaving") return { state: toIdle(s), effects: [{ type: "stop" }, { type: "rest" }, { type: "fire" }] };
      if (s.sheet && (s.phase === "locked" || s.phase === "caught")) {
        return { state: { ...toIdle(s), pos: 0 }, effects: [{ type: "paint", pos: 0, width: s.sheet.width }, { type: "rest" }] };
      }
      if (s.phase === "springBack") return { state: toIdle(s), effects: [{ type: "rest" }] };
      return same(toIdle(s));
  }
}
