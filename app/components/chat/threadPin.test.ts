import { describe, expect, it } from "vitest";

import {
  afterRender, AT_BOTTOM_PX, atBottom, AUTO_PIN_BACKSTOP_MS, distanceFromBottom, MAX_FILL_PAGES, mayLoadOlder,
  onScrollDecision, rowsPrepended, SENTINEL_MARGIN_PX, touchReleases, type AfterRender, type Point, type Scroll,
} from "./threadPin";

describe("threadPin constants", () => {
  it("keeps the 80px bottom band, the 5s backstop, the 200px sentinel margin and 4 fill pages", () => {
    expect(AT_BOTTOM_PX).toBe(80);
    expect(AUTO_PIN_BACKSTOP_MS).toBe(5000);
    expect(SENTINEL_MARGIN_PX).toBe(200);
    expect(MAX_FILL_PAGES).toBe(4);
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
  const at = (distance: number): Scroll => ({ scrollHeight: 1000, scrollTop: 600 - distance, clientHeight: 400 });
  const bottom = at(0), up = at(600);
  type In = Parameters<typeof afterRender>[0];
  const r = (over: Partial<In>): In => ({ prevLen: 5, len: 6, pre: up, scrollHeight: 1000, prepended: false, ...over });
  it.each<[string, In, AfterRender]>([
    ["first non-empty render pins (even scrolled up)", r({ prevLen: 0, len: 5, scrollHeight: 1500 }), { kind: "initial" }],
    ["first render that is a prepend is still initial", r({ prevLen: 0, len: 5, prepended: true, scrollHeight: 1500 }), { kind: "initial" }],
    ["still empty does nothing", r({ prevLen: 0, len: 0, scrollHeight: 0 }), { kind: "none" }],
    ["still empty at the bottom pins", r({ prevLen: 0, len: 0, pre: bottom, scrollHeight: 0 }), { kind: "pin" }],
    ["no snapshot yet counts as at the bottom", r({ pre: null, scrollHeight: 1800 }), { kind: "pin" }],
    ["append at the bottom sticks", r({ pre: bottom, scrollHeight: 1100 }), { kind: "pin" }],
    ["79px up still pins", r({ pre: at(79), scrollHeight: 1100 }), { kind: "pin" }],
    ["80px up is not pinned", r({ pre: at(80), scrollHeight: 1100 }), { kind: "none" }],
    ["same length at the bottom re-pins", r({ len: 5, pre: bottom }), { kind: "pin" }],
    ["append while scrolled up: leave the view where it is", r({ scrollHeight: 1100 }), { kind: "none" }],
    ["append of many while scrolled up: still none", r({ len: 40, scrollHeight: 4000 }), { kind: "none" }],
    ["prepend while scrolled up anchors by the delta", r({ len: 25, prepended: true, scrollHeight: 1800 }), { kind: "anchor", top: 800 }],
    ["prepend at the very top (scrollTop 0) anchors", r({ len: 35, prepended: true, pre: { scrollHeight: 1000, scrollTop: 0, clientHeight: 400 }, scrollHeight: 3000 }), { kind: "anchor", top: 2000 }],
    ["prepend at the bottom pins (a short chat)", r({ len: 25, prepended: true, pre: bottom, scrollHeight: 1800 }), { kind: "pin" }],
    ["prepend that rendered no taller: leave it", r({ prepended: true, scrollHeight: 1000 }), { kind: "none" }],
    ["prepend but shorter: leave it", r({ prepended: true, scrollHeight: 900 }), { kind: "none" }],
    ["shrank while scrolled up: leave it", r({ prevLen: 6, len: 5, scrollHeight: 800 }), { kind: "none" }],
    ["same length while scrolled up: leave it", r({ len: 5, scrollHeight: 1800 }), { kind: "none" }],
  ])("%s", (_, input, out) => {
    expect(afterRender(input)).toEqual(out);
  });
});

describe("rowsPrepended", () => {
  const ids = (...xs: (number | string)[]) => xs.map((id) => ({ id }));
  it.each<[string, { id: number | string }[], { id: number | string }[], boolean]>([
    ["older page above the old top", ids(10, 11, 12), ids(7, 8, 9, 10, 11, 12), true],
    ["append at the tail", ids(10, 11, 12), ids(10, 11, 12, 13), false],
    ["optimistic append", ids(10, 11), ids(10, 11, -1), false],
    ["in-place patch (same ids)", ids(10, 11), ids(10, 11), false],
    ["tail removal", ids(10, 11, 12), ids(10, 11), false],
    ["prepend and append together", ids(10, 11), ids(8, 9, 10, 11, 12), true],
    ["old top dropped, older ids came in", ids(10, 11, 12), ids(5, 6, 11, 12), true],
    ["old top dropped, nothing older", ids(10, 11, 12), ids(11, 12, 13), false],
    ["snowflake string ids", ids("900000000000000001", "900000000000000002"), ids("900000000000000000", "900000000000000001", "900000000000000002"), true],
    ["from empty (first paint)", [], ids(1, 2), false],
    ["to empty", ids(1, 2), [], false],
  ])("%s", (_, prev, next, out) => {
    expect(rowsPrepended(prev, next)).toBe(out);
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
  const go = {
    pending: false, headSettled: false, fills: 0, intersecting: true, hasOlder: true, loadingOlder: false, failed: false,
  };
  it.each<[string, Partial<typeof go>, boolean]>([
    ["sentinel in view, older pages, idle", {}, true],
    ["sentinel out of view", { intersecting: false }, false],
    ["no older pages", { hasOlder: false }, false],
    ["a page already loading", { loadingOlder: true }, false],
    ["the last page failed: only Retry loads", { failed: true }, false],
    ["after the release the fill cap is moot", { fills: MAX_FILL_PAGES + 5 }, true],
    ["pinned, head not settled (a seed's first paint)", { pending: true }, false],
    ["pinned, head settled: a short chat fills", { pending: true, headSettled: true }, true],
    ["pinned, the last fill under the cap", { pending: true, headSettled: true, fills: MAX_FILL_PAGES - 1 }, true],
    ["pinned, fill cap reached", { pending: true, headSettled: true, fills: MAX_FILL_PAGES }, false],
    ["pinned, settled, but the sentinel is out of view (a long head)", { pending: true, headSettled: true, intersecting: false }, false],
    ["pinned, settled, but a page is loading", { pending: true, headSettled: true, loadingOlder: true }, false],
    ["pinned, settled, but the last page failed", { pending: true, headSettled: true, failed: true }, false],
  ])("%s", (_, over, out) => {
    expect(mayLoadOlder({ ...go, ...over })).toBe(out);
  });
});
