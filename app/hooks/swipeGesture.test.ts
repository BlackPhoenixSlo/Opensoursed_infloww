/**
 * swipeGesture: the release physics, and `swipeReducer`'s transitions as
 * tables: (actions from a state) -> (phase, effects).
 */
import { describe, expect, it } from "vitest";

import {
  backdropOpacity, initialGesture, projectRelease, releaseDismisses, releaseVelocity, rubberBand, settlePlan,
  springKeyframes, swipeDirection, swipeReducer, DISMISS_MS, OUT_PX, SPRING, SWIPE_FLICK_MIN_PX, SWIPE_FLICK_PX_PER_MS,
  SWIPE_MIN_PX, SWIPE_PROJECT_MS, type GestureAction, type GestureEffect, type GestureState, type Phase,
} from "./swipeGesture";

describe("swipeDirection", () => {
  it("counts a slow swipe past the distance threshold, either way", () => {
    expect(swipeDirection(SWIPE_MIN_PX, 0, 1000)).toBe("right");
    expect(swipeDirection(-SWIPE_MIN_PX, 0, 1000)).toBe("left");
    expect(swipeDirection(SWIPE_MIN_PX - 1, 0, 1000)).toBeNull();
  });
  it("counts a short quick flick, never a tiny one", () => {
    expect(swipeDirection(30, 0, 50)).toBe("right");          // 0.6 px/ms
    expect(swipeDirection(30, 0, 200)).toBeNull();            // 0.15 px/ms
    expect(swipeDirection(SWIPE_FLICK_MIN_PX - 1, 0, 1)).toBeNull();
  });
  it("refuses a move more than 30 degrees off horizontal", () => {
    expect(swipeDirection(100, 57, 300)).toBe("right");       // ~29.7°
    expect(swipeDirection(100, 58, 300)).toBeNull();          // ~30.1°
    expect(swipeDirection(10, 200, 300)).toBeNull();          // a scroll
  });
});

describe("the release decision (iOS projection)", () => {
  const W = 300;
  it("projects the throw a SWIPE_PROJECT_MS coast ahead", () => {
    expect(projectRelease(100, 0.3)).toBe(100 + 0.3 * SWIPE_PROJECT_MS);
    expect(projectRelease(100, 0)).toBe(100);
  });
  it("dismisses a slow release from 75% of the width, not below", () => {
    expect(releaseDismisses(0.75 * W, 0, W)).toBe(true);
    expect(releaseDismisses(0.8 * W, 0, W)).toBe(true);
    expect(releaseDismisses(0.6 * W, 0, W)).toBe(false);
    expect(releaseDismisses(0.74 * W, 0, W)).toBe(false);
  });
  it("dismisses short of 75% when the projected release reaches it", () => {
    // 130px at 0.35 px/ms (under the flick speed) coasts to 235 >= 225.
    expect(releaseDismisses(130, 0.35, W)).toBe(true);
    expect(releaseDismisses(100, 0.35, W)).toBe(false);
  });
  it("dismisses a fast flick from SWIPE_FLICK_MIN_PX, never a tiny one", () => {
    expect(releaseDismisses(SWIPE_FLICK_MIN_PX, SWIPE_FLICK_PX_PER_MS, W)).toBe(true);
    expect(releaseDismisses(40, 1.2, W)).toBe(true);
    expect(releaseDismisses(SWIPE_FLICK_MIN_PX - 15, 0.5, W)).toBe(false);
  });
  it("a flick back always cancels, even past 75%", () => {
    expect(releaseDismisses(0.9 * W, -SWIPE_FLICK_PX_PER_MS, W)).toBe(false);
    expect(releaseDismisses(0.9 * W, -1, W)).toBe(false);
    // On a wide panel (a tablet-width Thread) the projection alone would still dismiss: the flick rule cancels.
    expect(projectRelease(900, -SWIPE_FLICK_PX_PER_MS)).toBeGreaterThanOrEqual(0.75 * 1000);
    expect(releaseDismisses(900, -SWIPE_FLICK_PX_PER_MS, 1000)).toBe(false);
    // A slow drift back from past 75% is judged by where it would coast.
    expect(releaseDismisses(0.8 * W, -0.1, W)).toBe(false);   // 240 - 30 < 225
    expect(releaseDismisses(0.85 * W, -0.05, W)).toBe(true);  // 255 - 15 >= 225
  });
  it("honours a custom dismissAt", () => {
    expect(releaseDismisses(0.5 * W, 0, W, 0.5)).toBe(true);
    expect(releaseDismisses(0.5 * W, 0, W)).toBe(false);
  });
});

describe("rubberBand", () => {
  it("gives less the further it is pulled, at most a third of the width", () => {
    expect(rubberBand(0, 300)).toBe(0);
    expect(rubberBand(-30, 300)).toBeCloseTo(-30 / 1.3);
    expect(rubberBand(-300, 300)).toBeCloseTo(-75);
    expect(Math.abs(rubberBand(-1e6, 300))).toBeLessThan(100);
    expect(Math.abs(rubberBand(-60, 300))).toBeLessThan(60);
    expect(rubberBand(-10, 0)).toBe(0);
  });
});

describe("releaseVelocity", () => {
  it("reads the last 100ms only, and 0 for a finger that held still", () => {
    const s = [{ x: 0, t: 0 }, { x: 10, t: 100 }, { x: 60, t: 150 }, { x: 110, t: 200 }];
    expect(releaseVelocity(s, 200)).toBeCloseTo(1);   // 10 -> 110 over 100ms
    expect(releaseVelocity(s, 400)).toBe(0);
  });
});

describe("springKeyframes", () => {
  it("starts where the finger let go, ends exactly at rest, within 350ms", () => {
    const { frames, ms } = springKeyframes(180, 0, 0);
    expect(frames[0]).toEqual({ x: 180, t: 0 });
    expect(frames[frames.length - 1]).toEqual({ x: 0, t: ms });
    expect(ms).toBeLessThanOrEqual(SPRING.maxMs);
    for (let i = 1; i < frames.length; i++) expect(frames[i].t).toBeGreaterThan(frames[i - 1].t);
  });
  it("carries the release velocity: a throw back toward open first keeps going", () => {
    const { frames } = springKeyframes(100, 0, -1);
    expect(frames[1].x).toBeLessThan(100 - 16 * 0.5);
  });
  it("carries an outward throw past the start before springing back", () => {
    const { frames } = springKeyframes(100, 0, 1);
    expect(frames[1].x).toBeGreaterThan(100);
  });
  it("leaving the screen stops where it first reaches stopAt, faster for a faster throw", () => {
    const slow = springKeyframes(240, 380, 0, 340);
    const fast = springKeyframes(240, 380, 2, 340);
    expect(slow.frames[slow.frames.length - 1].x).toBe(340);
    expect(fast.ms).toBeLessThan(slow.ms);
    expect(slow.ms).toBeLessThan(springKeyframes(240, 380, 0).ms);
    expect(slow.ms).toBeLessThanOrEqual(SPRING.maxMs);
  });
  it("is instant when already at rest", () => {
    expect(springKeyframes(0, 0, 0).ms).toBe(1);
  });
});

describe("settlePlan", () => {
  it("a dismissal ends at the width (just off screen), within DISMISS_MS; a spring back plays in full", () => {
    const out = settlePlan(240, 300 + OUT_PX, 0, 300);
    expect(out.frames[out.frames.length - 1].x).toBe(300);
    expect(out.duration).toBeLessThanOrEqual(DISMISS_MS);
    const back = settlePlan(180, 0, 0, 300);
    expect(back.duration).toBe(back.ms);
  });
  it("a panel already dragged off screen has nothing left to animate", () => {
    expect(settlePlan(310, 300 + OUT_PX, 0, 300)).toEqual({ frames: [], ms: 0, duration: 0 });
  });
});

describe("backdropOpacity", () => {
  it("is 1 at open and 0 at the width, through the anchor a caught panel set", () => {
    const none = { p: 0, o: 1 };
    expect(backdropOpacity(0, 300, none)).toBe(1);
    expect(backdropOpacity(150, 300, none)).toBeCloseTo(0.5);
    expect(backdropOpacity(300, 300, none)).toBe(0);
    const caught = { p: 100, o: 0.2 }; // mid slide-in: the backdrop lags the panel
    expect(backdropOpacity(100, 300, caught)).toBeCloseTo(0.2);
    expect(backdropOpacity(50, 300, caught)).toBeCloseTo(0.6);
    expect(backdropOpacity(300, 300, caught)).toBe(0);
  });
});

// --- swipeReducer -----------------------------------------------------------

const W = 300;
const start = (x: number, t = 0, more: Partial<Extract<GestureAction, { type: "start" }>> = {}): GestureAction =>
  ({ type: "start", x, y: 100, t, sheet: { width: W }, ...more });
const move = (x: number, t: number, y = 100): GestureAction => ({ type: "move", x, y, t });
const end = (x: number, t: number, y = 100): GestureAction => ({ type: "end", x, y, t });
const sheet = (): GestureState => initialGesture("left");
const plain = (): GestureState => initialGesture("right");

function play(s0: GestureState, actions: GestureAction[]) {
  let state = s0;
  const effects: GestureEffect[] = [];
  for (const a of actions) {
    const step = swipeReducer(state, a);
    state = step.state;
    effects.push(...step.effects);
  }
  return { state, effects, types: effects.map((e) => e.type) };
}
/** A sheet dragged slowly from 290 to `x`, held still 300ms, let go. */
const heldDrag = (x: number) => [start(290), move((290 + x) / 2, 100), move(x, 200), end(x, 500)];

describe("swipeReducer: a sheet (dir left, 300px)", () => {
  const rows: [string, GestureState, GestureAction[], Phase, GestureEffect["type"][]][] = [
    ["a tap does nothing", sheet(), [start(200), end(200, 50)], "idle", []],
    ["under 10px its intent is unknown", sheet(), [start(200), move(195, 20)], "pending", []],
    ["a steep move is a scroll: let go, nothing to put back", sheet(), [start(200), move(190, 20, 120)], "idle", []],
    ["locking sideways holds and paints", sheet(), [start(200), move(140, 100)], "locked", ["hold", "paint"]],
    ["a held sheet stays held through a diagonal drift", sheet(), [start(300), move(280, 10, 102), move(260, 20, 160)], "locked", ["hold", "paint", "paint"]],
    ["held still at 80%: leaves", sheet(), heldDrag(50), "leaving", ["hold", "paint", "paint", "settle"]],
    ["held still at 60%: springs back", sheet(), heldDrag(110), "springBack", ["hold", "paint", "paint", "settle"]],
    ["a 60px flick out leaves", sheet(), [start(290, 0), move(260, 20), end(230, 40)], "leaving", ["hold", "paint", "settle"]],
    ["dragged to 85% and flicked back: springs back", sheet(), [start(290, 0), move(160, 300), move(35, 600), move(85, 620), end(85, 640)], "springBack", ["hold", "paint", "paint", "paint", "settle"]],
    ["touchcancel mid-drag springs back", sheet(), [start(200), move(140, 100), { type: "cancel" }], "springBack", ["hold", "paint", "settle"]],
    ["touchcancel before the lock: nothing to put back", sheet(), [start(200), { type: "cancel" }], "idle", []],
    ["touchcancel with no finger down is nothing", sheet(), [{ type: "cancel" }], "idle", []],
    ["an inner scroll before the lock lets go", sheet(), [start(200), move(195, 10), { type: "scroll", own: true }], "idle", []],
    ["an inner scroll once held does not", sheet(), [start(200), move(140, 100), { type: "scroll", own: true }], "locked", ["hold", "paint"]],
    ["torn down mid-drag: put back", sheet(), [start(200), move(140, 100), { type: "teardown" }], "idle", ["hold", "paint", "paint", "rest"]],
    ["torn down springing back: its hold ends now, not at a settle that meets an idle gesture", sheet(), [...heldDrag(110), { type: "teardown" }, { type: "settled", run: 1 }], "idle", ["hold", "paint", "paint", "settle", "rest"]],
  ];
  it.each(rows)("%s", (_name, s0, actions, phase, types) => {
    const r = play(s0, actions);
    expect(r.state.phase).toBe(phase);
    expect(r.types).toEqual(types);
  });

  it("follows the finger 1:1 its way and rubber-bands the other", () => {
    expect(play(sheet(), [start(200), move(140, 100)]).state.pos).toBe(60);
    const pulled = play(sheet(), [start(200), move(260, 100)]).state.pos;
    expect(pulled).toBeLessThan(0);
    expect(pulled).toBeGreaterThan(-60);
  });

  it("a dismissal settles from the release to its width + OUT_PX", () => {
    const s = play(sheet(), heldDrag(50)).effects.at(-1);
    expect(s).toMatchObject({ type: "settle", from: 240, to: W + OUT_PX, width: W });
  });

  it("a panel already leaving takes no touch", () => {
    const leaving = play(sheet(), heldDrag(50)).state;
    expect(swipeReducer(leaving, start(100)).state).toBe(leaving);
  });

  describe("each decided dismissal fires once", () => {
    const leaving = () => play(sheet(), heldDrag(50)).state;
    it("settled, then torn down", () => {
      const r = play(leaving(), [{ type: "settled", run: 1 }, { type: "teardown" }]);
      expect(r.types).toEqual(["rest", "fire"]);
    });
    it("torn down mid-slide, then the settle reports", () => {
      const r = play(leaving(), [{ type: "teardown" }, { type: "settled", run: 1 }]);
      expect(r.types).toEqual(["stop", "rest", "fire"]);
    });
    it("a stale settle (an older run) is ignored", () => {
      expect(play(leaving(), [{ type: "settled", run: 0 }]).types).toEqual([]);
    });
    it("a spring back's end fires nothing", () => {
      const back = play(sheet(), heldDrag(110)).state;
      expect(play(back, [{ type: "settled", run: back.run }, { type: "teardown" }]).types).toEqual(["rest"]);
    });
  });

  describe("catching a moving panel", () => {
    const caught = start(200, 0, { sheet: { width: W, caught: { pos: 80, opacity: 0.5 } } });
    it("takes it where it is, its backdrop anchored at the opacity it showed", () => {
      const r = play(sheet(), [caught]);
      expect(r.state).toMatchObject({ phase: "caught", pos: 80, base: 80, anchor: { p: 80, o: 0.5 } });
      expect(r.effects).toEqual([{ type: "stop" }, { type: "hold" }, { type: "paint", pos: 80, width: W }]);
    });
    it("a tap on it lets it carry on back open", () => {
      const r = play(sheet(), [caught, end(200, 50)]);
      expect(r.state.phase).toBe("springBack");
      expect(r.effects.at(-1)).toMatchObject({ type: "settle", from: 80, to: 0 });
    });
    it("a drag moves it on from there", () => {
      expect(play(sheet(), [caught, move(160, 100)]).state).toMatchObject({ phase: "locked", pos: 120 });
    });
    it("torn down while caught: put back", () => {
      expect(play(sheet(), [caught, { type: "teardown" }]).types).toEqual(["stop", "hold", "paint", "paint", "rest"]);
    });
  });

  it("under reduced motion (a plain touch) nothing moves and the plain rules decide", () => {
    const r = play(sheet(), [start(290, 0, { sheet: undefined }), move(200, 50), move(120, 100), end(120, 150)]);
    expect(r.types).toEqual(["fire"]);
    expect(r.state.phase).toBe("idle");
    // A plain touch that turns vertical is a scroll: no sheet-only hold.
    const turned = play(sheet(), [start(290, 0, { sheet: undefined }), move(270, 10), move(268, 100, 200), end(120, 150)]);
    expect(turned.types).toEqual([]);
  });
});

describe("swipeReducer: a plain swipe (dir right)", () => {
  const p = (x: number, t = 0) => start(x, t, { sheet: undefined });
  const rows: [string, GestureAction[], GestureEffect["type"][]][] = [
    ["a swipe its way fires", [p(20), move(110, 50, 105), end(200, 100, 110)], ["fire"]],
    ["the other way does not", [p(200), move(110, 50), end(20, 100)], []],
    ["a scroll does not", [p(100), move(102, 50, 60), end(110, 100, 300)], []],
    ["one that turns vertical does not, even if it ends sideways", [p(0), move(12, 10, 101), move(12, 20, 200), move(200, 30, 200), end(200, 40, 200)], []],
    ["one whose start scrolled does not", [p(0), move(20, 10, 102), { type: "scroll", own: true }, move(200, 20, 110), end(200, 30, 110)], []],
    ["a scroll elsewhere does not cancel it", [p(0), move(20, 10, 102), { type: "scroll", own: false }, move(200, 20, 110), end(200, 30, 110)], ["fire"]],
    ["a cancelled one does not", [p(20), move(200, 50), { type: "cancel" }, end(200, 60)], []],
  ];
  it.each(rows)("%s", (_name, actions, types) => {
    expect(play(plain(), actions).types).toEqual(types);
  });
});
