import { describe, expect, it } from "vitest";

import { GIF_LOOP_INIT, gifLoopReducer, gifMounted, gifVisible, type GifLoopAction, type GifLoopState } from "./vaultGifLoopState";

const run = (acts: GifLoopAction["type"][], s: GifLoopState = GIF_LOOP_INIT) =>
  acts.reduce((st, type) => gifLoopReducer(st, { type } as GifLoopAction), s);

describe("gifLoopReducer", () => {
  it.each<[string, GifLoopAction["type"][], GifLoopState, boolean, boolean]>([
    // name, actions, state, mounted, visible
    ["initial: mounted for the observer, no src, still shown", [], { attached: false, playing: false, failed: false }, true, false],
    ["first on screen: src on, still until it plays", ["attach"], { attached: true, playing: false, failed: false }, true, false],
    ["playing: video over the still", ["attach", "playing"], { attached: true, playing: true, failed: false }, true, true],
    ["off screen (paused): still again, src kept", ["attach", "playing", "paused"], { attached: true, playing: false, failed: false }, true, false],
    ["back on screen: plays again", ["attach", "playing", "paused", "attach", "playing"], { attached: true, playing: true, failed: false }, true, true],
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
  });
});
