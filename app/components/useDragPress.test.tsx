import { describe, expect, it, vi } from "vitest";
import { renderHook } from "@testing-library/react";

import { dragThreshold, useDragPress } from "./useDragPress";

/** A window pointer event with the fields the hook reads. */
function fire(type: string, pointerId: number, clientX: number, clientY = 0) {
  const ev = new MouseEvent(type, { clientX, clientY });
  Object.defineProperty(ev, "pointerId", { value: pointerId });
  window.dispatchEvent(ev);
}

function press(pointerType: string, pointerId = 1) {
  const h = { begin: vi.fn(() => ({ x: 0, y: 0 })), move: vi.fn(), drop: vi.fn() };
  const { result } = renderHook(() => useDragPress(h));
  result.current.onPointerDown({ button: 0, pointerId, pointerType, clientX: 0, clientY: 0 } as unknown as React.PointerEvent<HTMLElement>);
  return { h, swallowClick: () => result.current.swallowClick() };
}

describe("useDragPress", () => {
  it.each<[string, number]>([["mouse", 4], ["pen", 4], ["touch", 10]])("slop for %s is %ipx", (type, px) => {
    expect(dragThreshold(type)).toBe(px);
  });

  it.each<[string, string, number, boolean]>([
    ["mouse 5px is a drag", "mouse", 5, true],
    ["touch 8px jitter is still a tap", "touch", 8, false],
    ["touch 11px is a drag", "touch", 11, true],
  ])("%s", (_name, pointerType, dx, drags) => {
    const { h, swallowClick } = press(pointerType);
    fire("pointermove", 1, dx);
    fire("pointerup", 1, dx);
    expect(h.move).toHaveBeenCalledTimes(drags ? 1 : 0);
    expect(h.drop).toHaveBeenCalledTimes(drags ? 1 : 0);
    expect(swallowClick()).toBe(drags);
  });

  it("tracks only the pointer that pressed: a second finger never moves or drops it", () => {
    const { h } = press("touch", 1);
    fire("pointermove", 2, 80);
    fire("pointerup", 2, 80);
    expect(h.move).not.toHaveBeenCalled();
    expect(h.drop).not.toHaveBeenCalled();
    fire("pointermove", 1, 30);
    fire("pointerup", 1, 30);
    expect(h.move).toHaveBeenCalledWith({ x: 0, y: 0 }, 30, 0);
    expect(h.drop).toHaveBeenCalledWith({ x: 0, y: 0 }, 30, 0);
  });
});
