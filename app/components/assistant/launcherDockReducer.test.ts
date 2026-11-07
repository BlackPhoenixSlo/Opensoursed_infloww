import { describe, expect, it } from "vitest";

import {
  DEFAULT_LAUNCHER_DOCK, MARGIN, SIZE, TUCK_PAST,
  initialLauncherState, launcherDockReducer, launcherSpot, parseLauncherDock, snapDock,
  type LauncherAction, type LauncherDock, type LauncherState,
} from "./launcherDockReducer";

const VW = 390;
const VH = 844;
const loaded: LauncherState = launcherDockReducer(initialLauncherState, { type: "load", dock: null, vw: VW, vh: VH });
const run = (s: LauncherState, ...as: LauncherAction[]) => as.reduce(launcherDockReducer, s);

describe("snapDock", () => {
  it.each<[string, number, number, LauncherDock]>([
    ["near the left side", 30, 400, { edge: "left", along: VH - 448, tucked: false }],
    ["near the right side", 300, 400, { edge: "right", along: VH - 448, tucked: false }],
    ["mid-width, low: the bottom edge", 170, 790, { edge: "bottom", along: 170, tucked: false }],
    ["mid-width, high: a side, not the bottom", 160, 300, { edge: "left", along: VH - 348, tucked: false }],
    ["just short of tucking left", -TUCK_PAST, 400, { edge: "left", along: VH - 448, tucked: false }],
    ["past the left edge: tucked", -TUCK_PAST - 1, 400, { edge: "left", along: VH - 448, tucked: true }],
    ["past the right edge: tucked", VW - SIZE + TUCK_PAST + 1, 400, { edge: "right", along: VH - 448, tucked: true }],
    ["dragged to the very top: kept under the top bar", 10, 0, { edge: "left", along: VH - SIZE - 64, tucked: false }],
    ["dragged into the bottom corner: side, along clamped to the margin", 0, VH - SIZE, { edge: "left", along: MARGIN, tucked: false }],
    ["bottom edge near the right: along clamped", VW - SIZE - 2, VH - SIZE, { edge: "bottom", along: VW - SIZE - MARGIN, tucked: false }],
  ])("%s", (_, x, y, want) => {
    expect(snapDock(x, y, VW, VH)).toEqual(want);
  });
});

describe("launcherDockReducer", () => {
  it("loads the default when nothing is stored, and draws it bottom-right above the composer", () => {
    expect(loaded.loaded).toBe(true);
    expect(loaded.dock).toEqual(DEFAULT_LAUNCHER_DOCK);
    expect(launcherSpot(loaded)).toEqual({ left: VW - SIZE - MARGIN, top: VH - SIZE - DEFAULT_LAUNCHER_DOCK.along });
  });

  it("follows the drag 1:1, then snaps on drop and asks for one save", () => {
    const mid = run(loaded, { type: "dragMove", x: 40, y: 300 });
    expect(launcherSpot(mid)).toEqual({ left: 40, top: 300 });
    expect(mid.saves).toBe(0);
    const dropped = run(mid, { type: "drop" });
    expect(dropped.drag).toBeNull();
    expect(dropped.dock).toEqual({ edge: "left", along: VH - 348, tucked: false });
    expect(launcherSpot(dropped)).toEqual({ left: MARGIN, top: 300 });
    expect(dropped.saves).toBe(1);
  });

  it("keeps a quarter of the icon on screen mid-drag", () => {
    expect(run(loaded, { type: "dragMove", x: -500, y: -50 }).drag).toEqual({ x: -SIZE * 0.75, y: 0 });
    expect(run(loaded, { type: "dragMove", x: 9999, y: 9999 }).drag).toEqual({ x: VW - SIZE * 0.25, y: VH - SIZE });
  });

  it("tucks when dropped past a side edge; untuck pulls it out at the same height", () => {
    const tucked = run(loaded, { type: "dragMove", x: -40, y: 500 }, { type: "drop" });
    expect(tucked.dock).toEqual({ edge: "left", along: VH - 548, tucked: true });
    const out = run(tucked, { type: "untuck" });
    expect(out.dock).toEqual({ edge: "left", along: VH - 548, tucked: false });
    expect(out.saves).toBe(2);
  });

  it.each<[string, LauncherAction]>([
    ["a drop with no drag (a tap)", { type: "drop" }],
    ["untuck when not tucked", { type: "untuck" }],
    ["a resize to the same size", { type: "resize", vw: VW, vh: VH }],
  ])("%s is a no-op (same object)", (_, a) => {
    expect(launcherDockReducer(loaded, a)).toBe(loaded);
  });

  it("clamps a stored spot into a smaller viewport at draw time", () => {
    const high = run(loaded, { type: "load", dock: { edge: "right", along: 800, tucked: false }, vw: VW, vh: VH });
    const small = run(high, { type: "resize", vw: 320, vh: 500 });
    expect(launcherSpot(small)).toEqual({ left: 320 - SIZE - MARGIN, top: 64 });
    const bottom = run(loaded, { type: "load", dock: { edge: "bottom", along: 380, tucked: false }, vw: 320, vh: 500 });
    expect(launcherSpot(bottom)).toEqual({ left: 320 - SIZE - MARGIN, top: 500 - SIZE - MARGIN });
  });
});

describe("parseLauncherDock", () => {
  it.each<[string, string | null, LauncherDock | null]>([
    ["nothing stored", null, null],
    ["junk", "{nope", null],
    ["unknown edge", '{"edge":"top","along":10,"tucked":false}', null],
    ["non-number along", '{"edge":"left","along":"10"}', null],
    ["a side dock", '{"edge":"left","along":120,"tucked":true}', { edge: "left", along: 120, tucked: true }],
    ["missing tucked reads untucked", '{"edge":"right","along":120}', { edge: "right", along: 120, tucked: false }],
    ["the bottom edge never tucks", '{"edge":"bottom","along":120,"tucked":true}', { edge: "bottom", along: 120, tucked: false }],
  ])("%s", (_, raw, want) => {
    expect(parseLauncherDock(raw)).toEqual(want);
  });
});
