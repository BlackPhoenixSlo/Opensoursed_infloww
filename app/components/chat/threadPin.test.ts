import { describe, expect, it } from "vitest";

import {
  afterRender, AT_BOTTOM_PX, atBottom, AUTO_PIN_BACKSTOP_MS, distanceFromBottom, mayLoadOlder,
  onScrollDecision, touchReleases, type AfterRender, type Point, type Scroll,
} from "./threadPin";

describe("threadPin constants", () => {
  it("keeps the 80px bottom band and the 5s backstop", () => {
    expect(AT_BOTTOM_PX).toBe(80);
    expect(AUTO_PIN_BACKSTOP_MS).toBe(5000);
  });
});

describe("distanceFromBottom", () => {
  it.each<[string, Scroll, number]>([
    ["at the very bottom", { scrollHeight: 1000, scrollTop: 600, clientHeight: 400 }, 0],
    ["scrolled up 300px", { scrollHeight: 1000, scrollTop: 300, clientHeight: 400 }, 300],
    ["at the top", { scrollHeight: 1000, scrollTop: 0, clientHeight: 400 }, 600],
    ["no overflow", { scrollHeight: 400, scrollTop: 0, clientHeight: 400 }, 0],
  ])("%s", (_, s, out) => {
    expect(distanceFromBottom(s)).toBe(out);
  });
});

describe("atBottom", () => {
  it.each<[string, number, boolean]>([
    ["0px is at the bottom", 0, true],
    ["79px is at the bottom", 79, true],
    ["80px is not (strict <)", 80, false],
    ["81px is not", 81, false],
  ])("%s", (_, d, out) => {
    expect(atBottom(d)).toBe(out);
  });
});

describe("afterRender", () => {
  // Snapshots at 0 / 79 / 80 / 600 px from the bottom (scrollHeight 1000, clientHeight 400).
  const at = (distance: number): Scroll => ({ scrollHeight: 1000, scrollTop: 600 - distance, clientHeight: 400 });
  const bottom = at(0), up = at(600);
  it.each<[string, Parameters<typeof afterRender>[0], AfterRender]>([
    ["first non-empty render pins (even scrolled up)", { prevLen: 0, len: 5, pre: up, scrollHeight: 1500 }, { kind: "initial" }],
    ["still empty does nothing", { prevLen: 0, len: 0, pre: up, scrollHeight: 0 }, { kind: "none" }],
    ["still empty at the bottom pins", { prevLen: 0, len: 0, pre: bottom, scrollHeight: 0 }, { kind: "pin" }],
    ["no snapshot yet counts as at the bottom", { prevLen: 5, len: 6, pre: null, scrollHeight: 1800 }, { kind: "pin" }],
    ["new message at the bottom sticks", { prevLen: 5, len: 6, pre: bottom, scrollHeight: 1100 }, { kind: "pin" }],
    ["79px up still pins", { prevLen: 5, len: 6, pre: at(79), scrollHeight: 1000 }, { kind: "pin" }],
    ["80px up is not pinned", { prevLen: 5, len: 6, pre: at(80), scrollHeight: 1000 }, { kind: "none" }],
    ["same length at the bottom re-pins", { prevLen: 5, len: 5, pre: bottom, scrollHeight: 1000 }, { kind: "pin" }],
    // Pure-seam row: in the hook the snapshot is taken after the insert's commit, so scrollHeight
    // rarely differs from pre.scrollHeight there (see useThreadPin's layout effect).
    ["pure seam: older page while scrolled up anchors by the delta", { prevLen: 5, len: 25, pre: up, scrollHeight: 1800 }, { kind: "anchor", top: 800 }],
    ["grew but no taller: leave it", { prevLen: 5, len: 6, pre: up, scrollHeight: 1000 }, { kind: "none" }],
    ["grew but shorter: leave it", { prevLen: 5, len: 6, pre: up, scrollHeight: 900 }, { kind: "none" }],
    ["shrank while scrolled up: leave it", { prevLen: 6, len: 5, pre: up, scrollHeight: 1800 }, { kind: "none" }],
    ["same length while scrolled up: leave it", { prevLen: 5, len: 5, pre: up, scrollHeight: 1800 }, { kind: "none" }],
  ])("%s", (_, input, out) => {
    expect(afterRender(input)).toEqual(out);
  });
});

describe("touchReleases", () => {
  const o: Point = { x: 100, y: 100 };
  it.each<[string, Point | null, Point | null, boolean]>([
    ["vertical drag releases", o, { x: 104, y: 240 }, true],
    ["upward drag releases", o, { x: 100, y: 40 }, true],
    ["sideways swipe keeps the pin", o, { x: 280, y: 100 }, false],
    ["diagonal more sideways keeps the pin", o, { x: 160, y: 140 }, false],
    ["exact diagonal keeps the pin", o, { x: 150, y: 150 }, false],
    ["no move keeps the pin", o, { x: 100, y: 100 }, false],
    ["just past diagonal releases", o, { x: 150, y: 151 }, true],
    ["no start point releases", null, { x: 280, y: 100 }, true],
    ["no current point releases", o, null, true],
  ])("%s", (_, t0, t, out) => {
    expect(touchReleases(t0, t)).toBe(out);
  });
});

describe("onScrollDecision", () => {
  it.each<[string, Parameters<typeof onScrollDecision>[0], ReturnType<typeof onScrollDecision>]>([
    ["our own pin write never releases", { programmatic: true, pending: true, distance: 500 }, { release: false, showJump: true }],
    ["our own write at the bottom", { programmatic: true, pending: true, distance: 0 }, { release: false, showJump: false }],
    ["user scroll far up while pinned releases", { programmatic: false, pending: true, distance: 81 }, { release: true, showJump: false }],
    ["exactly 80px does not release (strict >)", { programmatic: false, pending: true, distance: 80 }, { release: false, showJump: false }],
    ["user scroll after release: nothing to release", { programmatic: false, pending: false, distance: 500 }, { release: false, showJump: true }],
    ["jump button from 4x the band", { programmatic: false, pending: false, distance: 321 }, { release: false, showJump: true }],
    ["no jump button at 4x the band", { programmatic: false, pending: false, distance: 320 }, { release: false, showJump: false }],
  ])("%s", (_, input, out) => {
    expect(onScrollDecision(input)).toEqual(out);
  });
});

describe("mayLoadOlder", () => {
  const go = { pending: false, intersecting: true, hasOlder: true, loadingOlder: false };
  it.each<[string, Partial<typeof go>, boolean]>([
    ["sentinel in view, older pages, idle", {}, true],
    ["first load still pinning", { pending: true }, false],
    ["sentinel out of view", { intersecting: false }, false],
    ["no older pages", { hasOlder: false }, false],
    ["a page already loading", { loadingOlder: true }, false],
  ])("%s", (_, over, out) => {
    expect(mayLoadOlder({ ...go, ...over })).toBe(out);
  });
});
