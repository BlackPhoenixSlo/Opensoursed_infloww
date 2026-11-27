import { describe, expect, it } from "vitest";

import { activeScene, NONE_FOUND, PREVIEW_BADGE, sceneView, type Cue, type SceneLeak } from "./popupOverlay";

const CUES: Cue[] = [
  { t_s: 3, kind: "google" }, { t_s: 9.5, kind: "google_images" }, { t_s: 16, kind: "mega" },
  { t_s: 22, kind: "forum" }, { t_s: 28, kind: "x" }, { t_s: 40, kind: "end" },
];
const LEAK: SceneLeak = { leak_id: "lk_0001", leak_site: "example-leaks.test", kind: "page", title: "miavale onlyfans leak",
  pill: "live", preview: null };

describe("activeScene", () => {
  it.each([
    ["before the first cue", 0, null],
    ["just before the first cue", 2.99, null],
    ["on google", 3, { kind: "google", start: 3, end: 9.5 }],
    ["between google and images", 6, { kind: "google", start: 3, end: 9.5 }],
    ["on images", 9.5, { kind: "google_images", start: 9.5, end: 16 }],
    ["on mega", 16, { kind: "mega", start: 16, end: 22 }],
    ["on forum", 22, { kind: "forum", start: 22, end: 28 }],
    ["on x", 28, { kind: "x", start: 28, end: 40 }],
    ["on end", 40, { kind: "end", start: 40, end: null }],
    ["after end", 41.9, { kind: "end", start: 40, end: null }],
  ] as const)("%s", (_, t, want) => {
    expect(activeScene(CUES, t)).toEqual(want);
  });

  it("no cue table means no scene at any time", () => {
    for (const t of [0, 3, 40]) expect(activeScene(null, t)).toBeNull();
    expect(activeScene([], 5)).toBeNull();
  });

  it("two cues at one time: the later one runs", () => {
    expect(activeScene([{ t_s: 3, kind: "google" }, { t_s: 3, kind: "mega" }], 3)).toEqual({ kind: "mega", start: 3, end: null });
  });
});

describe("sceneView", () => {
  it.each([
    ["start", 3, false],
    ["just before the midpoint", 6.24, false],
    ["the midpoint", 6.25, true],
    ["after the midpoint", 9, true],
  ] as const)("google at %s flipped=%s", (_, t, flipped) => {
    const view = sceneView([LEAK], t, 3, 9.5);
    expect(view).toEqual({ kind: "cards", flipped, badge: flipped ? PREVIEW_BADGE : null, cards: [LEAK] });
  });

  it("every flipped view carries the badge", () => {
    for (let t = 3; t < 9.5; t += 0.25) {
      const view = sceneView([LEAK, { ...LEAK, leak_id: "lk_0002" }], t, 3, 9.5);
      if (view.kind === "cards" && view.flipped) expect(view.badge).toBe(PREVIEW_BADGE);
    }
  });

  it("an empty scene reads None found here and never flips", () => {
    expect(sceneView([], 9, 3, 9.5)).toEqual({ kind: "empty", text: NONE_FOUND });
  });

  it("a last scene with no next cue never flips", () => {
    expect(sceneView([LEAK], 99, 28, null)).toMatchObject({ flipped: false, badge: null });
  });
});
