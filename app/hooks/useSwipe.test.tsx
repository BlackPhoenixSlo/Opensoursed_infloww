/**
 * useSwipe: a one-finger, mostly-horizontal swipe below lg calls `onSwipe`;
 * scrolls, short drags, text fields, `data-no-swipe`, horizontal scrollers, a
 * second finger, a platform-taken gesture (touchcancel), a move that turns vertical
 * or scrolls what it started on, and desktop width do not.
 */
import { fireEvent, render } from "@testing-library/react";
import { useRef } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  startsInIgnored, swipeDirection, useSwipe, SWIPE_FLICK_MIN_PX, SWIPE_MIN_PX, type SwipeDir,
} from "./useSwipe";

let wide = false;
let reduced = false;
beforeEach(() => {
  wide = false;
  reduced = false;
  window.matchMedia = vi.fn((q: string) => ({
    matches: q.includes("reduced-motion") ? reduced : wide,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  })) as unknown as typeof window.matchMedia;
});
afterEach(() => vi.restoreAllMocks());

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

describe("startsInIgnored", () => {
  it("ignores text fields and data-no-swipe, not plain content", () => {
    document.body.innerHTML = `<div id="root"><input id="i"><textarea id="t"></textarea>
      <div data-no-swipe><span id="n">x</span></div><p id="p">x</p></div>`;
    const root = document.getElementById("root");
    for (const id of ["i", "t", "n"]) expect(startsInIgnored(document.getElementById(id), root)).toBe(true);
    expect(startsInIgnored(document.getElementById("p"), root)).toBe(false);
  });
  it("ignores a touch inside a horizontal scroller, not one inside a clipped box", () => {
    document.body.innerHTML = `<div id="root"><div id="s" style="overflow-x:auto"><b id="a">x</b></div>
      <div id="c" style="overflow-x:hidden"><b id="b">x</b></div></div>`;
    for (const id of ["s", "c"]) {
      const el = document.getElementById(id)!;
      Object.defineProperty(el, "scrollWidth", { value: 800 });
      Object.defineProperty(el, "clientWidth", { value: 300 });
    }
    const root = document.getElementById("root");
    expect(startsInIgnored(document.getElementById("a"), root)).toBe(true);
    expect(startsInIgnored(document.getElementById("b"), root)).toBe(false);
  });
});

function Box({ dir, onSwipe }: { dir: SwipeDir; onSwipe: () => void }) {
  const ref = useRef<HTMLDivElement>(null);
  useSwipe(ref, { enabled: true, dir, onSwipe, follow: ref });
  return <div ref={ref} data-testid="box"><input data-testid="field" /><p data-testid="text">x</p></div>;
}

const pt = (x: number, y: number) => ({ clientX: x, clientY: y });
/** A finger from (x0, y0) to (x1, y1) on `el`; `end` false: the platform cancels it. */
function swipe(el: Element, x0: number, y0: number, x1: number, y1: number, end = true) {
  fireEvent.touchStart(el, { touches: [pt(x0, y0)] });
  fireEvent.touchMove(el, { touches: [pt((x0 + x1) / 2, (y0 + y1) / 2)] });
  fireEvent.touchMove(el, { touches: [pt(x1, y1)] });
  if (end) fireEvent.touchEnd(el, { touches: [], changedTouches: [pt(x1, y1)] });
  else fireEvent.touchCancel(el, { touches: [], changedTouches: [pt(x1, y1)] });
}

describe("useSwipe", () => {
  it("calls onSwipe for a swipe its way, not the other way or a scroll", () => {
    const onSwipe = vi.fn();
    const { getByTestId } = render(<Box dir="right" onSwipe={onSwipe} />);
    const text = getByTestId("text");
    swipe(text, 20, 100, 200, 110);
    expect(onSwipe).toHaveBeenCalledTimes(1);
    swipe(text, 200, 100, 20, 100);
    swipe(text, 100, 20, 110, 300);
    expect(onSwipe).toHaveBeenCalledTimes(1);
  });

  it("ignores a swipe that starts in a text field, a cancelled one, a two-finger one, and desktop width", () => {
    const onSwipe = vi.fn();
    const { getByTestId } = render(<Box dir="right" onSwipe={onSwipe} />);
    swipe(getByTestId("field"), 20, 100, 200, 100);
    swipe(getByTestId("text"), 20, 100, 200, 100, false);
    fireEvent.touchStart(getByTestId("text"), { touches: [pt(20, 100), pt(40, 100)] });
    fireEvent.touchEnd(getByTestId("text"), { touches: [], changedTouches: [pt(200, 100)] });
    wide = true;
    swipe(getByTestId("text"), 20, 100, 200, 100);
    expect(onSwipe).not.toHaveBeenCalled();
  });

  it("a move that turns vertical is not a swipe, even if it ends sideways", () => {
    const onSwipe = vi.fn();
    const { getByTestId } = render(<Box dir="right" onSwipe={onSwipe} />);
    const el = getByTestId("text");
    fireEvent.touchStart(el, { touches: [pt(0, 0)] });
    for (const [x, y] of [[12, 1], [12, 100], [200, 100]]) fireEvent.touchMove(el, { touches: [pt(x, y)] });
    fireEvent.touchEnd(el, { touches: [], changedTouches: [pt(200, 100)] });
    expect(onSwipe).not.toHaveBeenCalled();
    expect(getByTestId("box").style.transform).toBe("");
    swipe(el, 0, 0, 200, 10);
    expect(onSwipe).toHaveBeenCalledTimes(1);
  });

  it("a swipe whose start scrolled (the browser took it as a pan) is not a swipe", () => {
    const onSwipe = vi.fn();
    const { getByTestId } = render(<Box dir="right" onSwipe={onSwipe} />);
    const el = getByTestId("text");
    fireEvent.touchStart(el, { touches: [pt(0, 0)] });
    fireEvent.touchMove(el, { touches: [pt(20, 2)] });
    fireEvent.scroll(getByTestId("box"));
    fireEvent.touchMove(el, { touches: [pt(200, 10)] });
    fireEvent.touchEnd(el, { touches: [], changedTouches: [pt(200, 10)] });
    expect(onSwipe).not.toHaveBeenCalled();
    // A scroll elsewhere (another pane) does not cancel it.
    const other = document.createElement("div");
    document.body.appendChild(other);
    fireEvent.touchStart(el, { touches: [pt(0, 0)] });
    fireEvent.touchMove(el, { touches: [pt(20, 2)] });
    fireEvent.scroll(other);
    fireEvent.touchMove(el, { touches: [pt(200, 10)] });
    fireEvent.touchEnd(el, { touches: [], changedTouches: [pt(200, 10)] });
    expect(onSwipe).toHaveBeenCalledTimes(1);
    other.remove();
  });

  it("follows the finger only in its direction, and not under reduced motion", () => {
    const { getByTestId } = render(<Box dir="left" onSwipe={vi.fn()} />);
    const box = getByTestId("box");
    fireEvent.touchStart(box, { touches: [pt(200, 100)] });
    fireEvent.touchMove(box, { touches: [pt(140, 102)] });
    expect(box.style.transform).toBe("translateX(-60px)");
    fireEvent.touchMove(box, { touches: [pt(260, 102)] });
    expect(box.style.transform).toBe("");
    fireEvent.touchCancel(box, { touches: [] });

    reduced = true;
    fireEvent.touchStart(box, { touches: [pt(200, 100)] });
    fireEvent.touchMove(box, { touches: [pt(140, 102)] });
    expect(box.style.transform).toBe("");
  });
});
