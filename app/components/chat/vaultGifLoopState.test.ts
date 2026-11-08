import { describe, expect, it } from "vitest";

import { GIF_LOOP_INIT, gifLoopReducer, gifMounted, gifSlots, gifVisible, type GifLoopAction, type GifLoopState } from "./vaultGifLoopState";

const run = (acts: GifLoopAction["type"][], s: GifLoopState = GIF_LOOP_INIT) =>
  acts.reduce((st, type) => gifLoopReducer(st, { type } as GifLoopAction), s);

describe("gifLoopReducer", () => {
  it.each<[string, GifLoopAction["type"][], GifLoopState, boolean, boolean]>([
    // name, actions, state, mounted, visible
    ["initial: mounted for the observer, no src, still shown", [], { attached: false, playing: false, failed: false }, true, false],
    ["first on screen: src on, still until it plays", ["attach"], { attached: true, playing: false, failed: false }, true, false],
    ["playing: video over the still", ["attach", "playing"], { attached: true, playing: true, failed: false }, true, true],
    ["hidden tab (paused): still again, src kept", ["attach", "playing", "paused"], { attached: true, playing: false, failed: false }, true, false],
    ["back on screen: plays again", ["attach", "playing", "paused", "attach", "playing"], { attached: true, playing: true, failed: false }, true, true],
    ["off screen (detach): src off, still shown", ["attach", "playing", "detach"], { attached: false, playing: false, failed: false }, true, false],
    ["detached, back on screen: src on again, plays", ["attach", "playing", "detach", "attach", "playing"], { attached: true, playing: true, failed: false }, true, true],
    ["`playing` after detach is ignored", ["attach", "detach", "playing"], { attached: false, playing: false, failed: false }, true, false],
    ["`playing` before attach is ignored", ["playing"], { attached: false, playing: false, failed: false }, true, false],
    ["error: unmounted, the still for good", ["attach", "playing", "error"], { attached: false, playing: false, failed: true }, false, false],
    ["nothing revives a failed one", ["attach", "error", "attach", "playing"], { attached: false, playing: false, failed: true }, false, false],
  ])("%s", (_n, acts, want, mounted, visible) => {
    const s = run(acts);
    expect(s).toEqual(want);
    expect(gifMounted(s)).toBe(mounted);
    expect(gifVisible(s)).toBe(visible);
  });

  it("returns the same object on a no-op (no re-render)", () => {
    const s = run(["attach"]);
    expect(gifLoopReducer(s, { type: "attach" })).toBe(s);
    expect(gifLoopReducer(GIF_LOOP_INIT, { type: "paused" })).toBe(GIF_LOOP_INIT);
    expect(gifLoopReducer(GIF_LOOP_INIT, { type: "detach" })).toBe(GIF_LOOP_INIT);
  });
});

describe("gifSlots", () => {
  // Steps on tiles a..e: "+x" acquire, "-x" release. Want: who was granted (now or later) in order, held, queued.
  it.each<[string, string[], string[], number, number]>([
    ["under the cap: every ask granted now", ["+a", "+b"], ["a", "b"], 2, 0],
    ["over the cap: the rest queue", ["+a", "+b", "+c", "+d", "+e"], ["a", "b", "c"], 3, 2],
    ["a release grants the first in line", ["+a", "+b", "+c", "+d", "+e", "-b"], ["a", "b", "c", "d"], 3, 1],
    ["in ask order", ["+a", "+b", "+c", "+d", "+e", "-a", "-c"], ["a", "b", "c", "d", "e"], 3, 0],
    ["a queued tile that leaves is just dropped", ["+a", "+b", "+c", "+d", "-d", "-a"], ["a", "b", "c"], 2, 0],
    ["asking twice holds one slot", ["+a", "+a", "+b", "+c"], ["a", "a", "b", "c"], 3, 0],
    ["releasing what it never held frees nothing", ["+a", "+b", "+c", "+d", "-e"], ["a", "b", "c"], 3, 1],
  ])("%s", (_n, steps, granted, held, queued) => {
    const pool = gifSlots(3);
    const tiles: Record<string, object> = {};
    const got: string[] = [];
    for (const st of steps) {
      const k = st.slice(1);
      const t = (tiles[k] ??= {});
      if (st[0] === "+") { if (pool.acquire(t, () => got.push(k))) got.push(k); }
      else pool.release(t);
    }
    expect(got).toEqual(granted);
    expect(pool.held()).toBe(held);
    expect(pool.queued()).toBe(queued);
  });
});
