/**
 * useSwipe, the hook's DOM side (the gesture's rules are swipeGesture.test.ts's
 * tables): a one-finger, mostly-horizontal swipe below lg calls `onSwipe`;
 * text fields, a second finger, a platform-taken gesture (touchcancel), desktop
 * width, the OS edge zone and an open dialog (not a leaving copy) do not. A
 * sheet (`sheet`) tracks the finger, lets go of taps the moment a dismissal is
 * decided (a modal Radix layer's hold on <body> too), calls `onSwipe` once, and
 * is caught where it is mid-spring.
 */
import { fireEvent, render } from "@testing-library/react";
import { useRef } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { EXIT_GHOST } from "./layerMarks";
import { DISMISS_MS } from "./swipeGesture";
import { OPEN_DIALOG, startsInIgnored, useSwipe, type SwipeDir } from "./useSwipe";

let wide = false;
let reduced = false;
/** Layout, which the test DOM has none of: every element is 300px wide; and
 *  `animate` records its animations, finished by hand (`onfinish`). */
type Anim = { cancel: ReturnType<typeof vi.fn>; onfinish: (() => void) | null; playState: string; timing: KeyframeAnimationOptions };
let anims: Anim[] = [];
const animate = vi.fn((_frames: Keyframe[], timing: KeyframeAnimationOptions) => {
  const a: Anim = { cancel: vi.fn(() => { a.playState = "idle"; }), onfinish: null, playState: "running", timing };
  anims.push(a);
  return a as unknown as Animation;
});
beforeEach(() => {
  wide = false;
  reduced = false;
  anims = [];
  animate.mockClear();
  window.matchMedia = vi.fn((q: string) => ({
    matches: q.includes("reduced-motion") ? reduced : wide,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  })) as unknown as typeof window.matchMedia;
  vi.spyOn(HTMLElement.prototype, "offsetWidth", "get").mockReturnValue(300);
  Object.defineProperty(HTMLElement.prototype, "animate", { value: animate, configurable: true, writable: true });
  Object.defineProperty(HTMLElement.prototype, "getAnimations", { value: () => [], configurable: true, writable: true });
});
afterEach(() => {
  vi.restoreAllMocks();
  document.body.style.pointerEvents = "";
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

function Box({ dir, onSwipe, onLetGo, sheet = true, enabled = true, edgeGuard, ignoreWhile }: {
  dir: SwipeDir; onSwipe: () => void; onLetGo?: () => void; sheet?: boolean; enabled?: boolean; edgeGuard?: number;
  ignoreWhile?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const bd = useRef<HTMLDivElement>(null);
  useSwipe(ref, { enabled, dir, onSwipe, sheet: sheet ? { panel: ref, backdrop: bd, onLetGo } : undefined, edgeGuard, ignoreWhile });
  return (
    <>
      <div ref={bd} data-testid="backdrop" />
      <div ref={ref} data-testid="box">
        <input data-testid="field" /><p data-testid="text">x</p><div data-testid="list" />
      </div>
    </>
  );
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

/** A slow drag from x0 to x1 that holds still before lifting: velocity 0, the position alone decides. */
function dragAndHold(el: Element, x0: number, x1: number) {
  vi.useFakeTimers({ toFake: ["Date"] });
  const at = (ms: number) => vi.setSystemTime(new Date(1_000_000 + ms));
  at(0);
  fireEvent.touchStart(el, { touches: [pt(x0, 100)] });
  at(100);
  fireEvent.touchMove(el, { touches: [pt((x0 + x1) / 2, 100)] });
  at(200);
  fireEvent.touchMove(el, { touches: [pt(x1, 100)] });
  at(500);
  fireEvent.touchEnd(el, { touches: [], changedTouches: [pt(x1, 100)] });
  vi.useRealTimers();
}

describe("useSwipe: a plain swipe", () => {
  it("calls onSwipe for a swipe its way, not the other way or a scroll", () => {
    const onSwipe = vi.fn();
    const { getByTestId } = render(<Box dir="right" onSwipe={onSwipe} sheet={false} />);
    const text = getByTestId("text");
    swipe(text, 20, 100, 200, 110);
    expect(onSwipe).toHaveBeenCalledTimes(1);
    swipe(text, 200, 100, 20, 100);
    swipe(text, 100, 20, 110, 300);
    expect(onSwipe).toHaveBeenCalledTimes(1);
  });

  it("ignores a swipe that starts in a text field, a cancelled one, a two-finger one, and desktop width", () => {
    const onSwipe = vi.fn();
    const { getByTestId } = render(<Box dir="right" onSwipe={onSwipe} sheet={false} />);
    swipe(getByTestId("field"), 20, 100, 200, 100);
    swipe(getByTestId("text"), 20, 100, 200, 100, false);
    fireEvent.touchStart(getByTestId("text"), { touches: [pt(20, 100), pt(40, 100)] });
    fireEvent.touchEnd(getByTestId("text"), { touches: [], changedTouches: [pt(200, 100)] });
    wide = true;
    swipe(getByTestId("text"), 20, 100, 200, 100);
    expect(onSwipe).not.toHaveBeenCalled();
  });

  it("ignores a touch in the OS edge zone (edgeGuard)", () => {
    const onSwipe = vi.fn();
    const { getByTestId } = render(<Box dir="right" onSwipe={onSwipe} sheet={false} edgeGuard={24} />);
    swipe(getByTestId("text"), 10, 100, 200, 100);
    expect(onSwipe).not.toHaveBeenCalled();
    swipe(getByTestId("text"), 30, 100, 200, 100);
    expect(onSwipe).toHaveBeenCalledTimes(1);
  });

  it("ignores a touch while a dialog is open (ignoreWhile: OPEN_DIALOG), not while only a leaving copy is", () => {
    const onSwipe = vi.fn();
    const { getByTestId } = render(<Box dir="right" onSwipe={onSwipe} sheet={false} ignoreWhile={OPEN_DIALOG} />);
    const dialog = document.createElement("div");
    dialog.setAttribute("role", "dialog");
    document.body.appendChild(dialog);
    swipe(getByTestId("text"), 30, 100, 200, 100);
    expect(onSwipe).not.toHaveBeenCalled();
    dialog.className = EXIT_GHOST;
    dialog.innerHTML = `<div aria-modal="true"></div>`;
    swipe(getByTestId("text"), 30, 100, 200, 100);
    expect(onSwipe).toHaveBeenCalledTimes(1);
    dialog.remove();
  });

  it("a move that turns vertical is not a swipe, even if it ends sideways", () => {
    const onSwipe = vi.fn();
    const { getByTestId } = render(<Box dir="right" onSwipe={onSwipe} sheet={false} />);
    const el = getByTestId("text");
    fireEvent.touchStart(el, { touches: [pt(0, 0)] });
    for (const [x, y] of [[12, 1], [12, 100], [200, 100]]) fireEvent.touchMove(el, { touches: [pt(x, y)] });
    fireEvent.touchEnd(el, { touches: [], changedTouches: [pt(200, 100)] });
    expect(onSwipe).not.toHaveBeenCalled();
    swipe(el, 0, 0, 200, 10);
    expect(onSwipe).toHaveBeenCalledTimes(1);
  });

  it("a swipe whose start scrolled (the browser took it as a pan) is not a swipe", () => {
    const onSwipe = vi.fn();
    const { getByTestId } = render(<Box dir="right" onSwipe={onSwipe} sheet={false} />);
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
});

describe("useSwipe: a sheet", () => {
  it("follows the finger 1:1 its way, rubber-bands the other, and not under reduced motion", () => {
    const { getByTestId } = render(<Box dir="left" onSwipe={vi.fn()} />);
    const box = getByTestId("box");
    fireEvent.touchStart(box, { touches: [pt(200, 100)] });
    fireEvent.touchMove(box, { touches: [pt(140, 102)] });
    expect(box.style.transform).toBe("translateX(-60px)");
    expect(box.style.willChange).toBe("transform");
    fireEvent.touchMove(box, { touches: [pt(260, 102)] });
    const pulled = Number(/translateX\(([-\d.]+)px\)/.exec(box.style.transform)?.[1]);
    expect(pulled).toBeGreaterThan(0);
    expect(pulled).toBeLessThan(60);
    fireEvent.touchCancel(box, { touches: [] });
    expect(box.style.transform).toBe("");
    anims[0].onfinish?.();
    expect(box.style.willChange).toBe("");

    reduced = true;
    fireEvent.touchStart(box, { touches: [pt(200, 100)] });
    fireEvent.touchMove(box, { touches: [pt(140, 102)] });
    expect(box.style.transform).toBe("");
  });

  it("a panel with no width (not shown) takes no sheet gesture", () => {
    vi.spyOn(HTMLElement.prototype, "offsetWidth", "get").mockReturnValue(0);
    const onSwipe = vi.fn();
    const { getByTestId } = render(<Box dir="left" onSwipe={onSwipe} />);
    const box = getByTestId("box");
    swipe(box, 290, 100, 20, 100);
    expect(box.style.transform).toBe("");
    expect(onSwipe).not.toHaveBeenCalled();
  });

  it("locks sideways only within 30 degrees of horizontal", () => {
    const { getByTestId } = render(<Box dir="left" onSwipe={vi.fn()} />);
    const box = getByTestId("box");
    // 15px left, 10px down: 34 degrees off horizontal at the lock, a scroll.
    fireEvent.touchStart(box, { touches: [pt(200, 100)] });
    fireEvent.touchMove(box, { touches: [pt(185, 110)] });
    fireEvent.touchMove(box, { touches: [pt(100, 110)] });
    expect(box.style.transform).toBe("");
    fireEvent.touchEnd(box, { touches: [], changedTouches: [pt(100, 110)] });
    // 15px left, 8px down: 28 degrees, a sheet drag.
    fireEvent.touchStart(box, { touches: [pt(200, 100)] });
    fireEvent.touchMove(box, { touches: [pt(185, 108)] });
    expect(box.style.transform).toBe("translateX(-15px)");
  });

  it("a sheet held sideways stays held through a diagonal drag and an inner scroll", () => {
    const { getByTestId } = render(<Box dir="left" onSwipe={vi.fn()} />);
    const box = getByTestId("box");
    fireEvent.touchStart(box, { touches: [pt(300, 100)] });
    fireEvent.touchMove(box, { touches: [pt(280, 102)] });
    // The finger drifts down more than sideways, and the list under it scrolls: still the sheet's.
    fireEvent.touchMove(box, { touches: [pt(260, 160)] });
    fireEvent.scroll(getByTestId("list"));
    fireEvent.touchMove(box, { touches: [pt(200, 140)] });
    expect(box.style.transform).toBe("translateX(-100px)");
  });

  it("takes no tap from the moment it is decided, nor holds <body>, tells onLetGo, and slides off within DISMISS_MS", () => {
    const onSwipe = vi.fn(), onLetGo = vi.fn();
    const { getByTestId } = render(<Box dir="left" onSwipe={onSwipe} onLetGo={onLetGo} />);
    const box = getByTestId("box"), bd = getByTestId("backdrop");
    document.body.style.pointerEvents = "none"; // a modal Radix layer holds the page
    dragAndHold(box, 290, 50);
    expect(onLetGo).toHaveBeenCalledTimes(1);
    expect(box.style.pointerEvents).toBe("none");
    expect(bd.style.pointerEvents).toBe("none");
    expect(document.body.style.pointerEvents).toBe("");
    expect(box.hasAttribute("data-swiped")).toBe(true);
    expect(onSwipe).not.toHaveBeenCalled();
    expect((animate.mock.calls[0][1] as { duration: number }).duration).toBeLessThanOrEqual(DISMISS_MS);
    // The panel's keyframes end at its width (just off screen), not past it.
    const frames = animate.mock.calls[0][0] as { transform: string }[];
    expect(frames[frames.length - 1].transform).toBe("translateX(-300px)");
    anims[0].onfinish?.();
    expect(onSwipe).toHaveBeenCalledTimes(1);
  });

  it("leaves <body> held while another dialog is still open", () => {
    const { getByTestId } = render(<Box dir="left" onSwipe={vi.fn()} />);
    const other = document.createElement("div");
    other.setAttribute("aria-modal", "true");
    document.body.appendChild(other);
    document.body.style.pointerEvents = "none";
    dragAndHold(getByTestId("box"), 290, 50);
    expect(document.body.style.pointerEvents).toBe("none");
    other.remove();
  });

  it("torn down mid-dismissal it finishes at once, and onSwipe is called once", () => {
    const onSwipe = vi.fn();
    const { getByTestId, rerender } = render(<Box dir="left" onSwipe={onSwipe} />);
    dragAndHold(getByTestId("box"), 290, 50);
    expect(onSwipe).not.toHaveBeenCalled();
    rerender(<Box dir="left" onSwipe={onSwipe} enabled={false} />);
    expect(onSwipe).toHaveBeenCalledTimes(1);
    expect(anims[0].cancel).toHaveBeenCalled();
    anims[0].onfinish?.(); // a late finish fires nothing more
    expect(onSwipe).toHaveBeenCalledTimes(1);
  });

  it("unmounted mid-drag, the panel is put back", () => {
    const { getByTestId, rerender } = render(<Box dir="left" onSwipe={vi.fn()} />);
    const box = getByTestId("box");
    fireEvent.touchStart(box, { touches: [pt(200, 100)] });
    fireEvent.touchMove(box, { touches: [pt(140, 102)] });
    rerender(<Box dir="left" onSwipe={vi.fn()} enabled={false} />);
    expect(box.style.transform).toBe("");
    expect(box.style.willChange).toBe("");
  });

  it("torn down while springing back, the panel's will-change goes too", () => {
    const onLetGo = vi.fn();
    const { getByTestId, rerender } = render(<Box dir="left" onSwipe={vi.fn()} onLetGo={onLetGo} />);
    const box = getByTestId("box");
    dragAndHold(box, 290, 200);
    expect(box.style.willChange).toBe("transform");
    rerender(<Box dir="left" onSwipe={vi.fn()} onLetGo={onLetGo} enabled={false} />);
    expect(box.style.willChange).toBe("");
    expect(onLetGo).not.toHaveBeenCalled();
  });

  it("a snap back keeps taking taps", () => {
    const onSwipe = vi.fn();
    const { getByTestId } = render(<Box dir="left" onSwipe={onSwipe} />);
    const box = getByTestId("box");
    dragAndHold(box, 290, 200);
    expect(box.style.pointerEvents).toBe("");
    anims[0].onfinish?.();
    expect(onSwipe).not.toHaveBeenCalled();
  });

  it("a touch during the spring back catches the panel where it is; a tap lets it carry on", () => {
    const { getByTestId } = render(<Box dir="left" onSwipe={vi.fn()} />);
    const box = getByTestId("box");
    dragAndHold(box, 290, 200);
    expect(anims).toHaveLength(2); // panel + backdrop
    vi.spyOn(window, "getComputedStyle").mockReturnValue({ transform: "matrix(1, 0, 0, 1, -40, 0)", opacity: "0.7" } as CSSStyleDeclaration);
    globalThis.DOMMatrixReadOnly ??= class { m41: number; constructor(s: string) { this.m41 = Number(/,\s*([-\d.]+),\s*[-\d.]+\)$/.exec(s)?.[1]); } } as unknown as typeof DOMMatrixReadOnly;
    fireEvent.touchStart(box, { touches: [pt(200, 100)] });
    expect(anims[0].cancel).toHaveBeenCalled();
    expect(anims[1].cancel).toHaveBeenCalled();
    expect(box.style.transform).toBe("translateX(-40px)");
    fireEvent.touchEnd(box, { touches: [], changedTouches: [pt(200, 100)] });
    expect(anims).toHaveLength(4); // a new spring back from -40px
    expect((animate.mock.calls[2][0] as { transform: string }[])[0].transform).toBe("translateX(-40px)");
  });
});
