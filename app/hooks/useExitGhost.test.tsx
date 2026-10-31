/**
 * useExitGhost: closing a layer leaves an inert copy, without ids, that an
 * open-dialog lookup (`OPEN_DIALOG`) skips, dropped after its exit; none under
 * reduced motion, for a strict-mode remount, a layer holding live media, or one
 * a swipe already slid away.
 */
import { act, render } from "@testing-library/react";
import { StrictMode, useRef, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { EXIT_GHOST } from "./layerMarks";
import { useExitGhost } from "./useExitGhost";
import { OPEN_DIALOG } from "./useSwipe";

let reduced = false;
beforeEach(() => {
  reduced = false;
  window.matchMedia = vi.fn(() => ({ matches: reduced })) as unknown as typeof window.matchMedia;
});
afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

function Layer({ open, children }: { open: boolean; children?: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  useExitGhost(open, ref);
  return (
    <div data-testid="host">
      {open && (
        <div ref={ref} role="dialog" aria-modal="true" id="layer" data-state="open" data-testid="layer">
          <span id="inner" data-foo="1" role="menuitem">hi</span>
          {children}
        </div>
      )}
    </div>
  );
}

const ghosts = () => document.querySelectorAll(`.${EXIT_GHOST}`);
const tick = () => new Promise<void>((r) => queueMicrotask(r));

describe("useExitGhost", () => {
  it("leaves an inert copy without ids or names, which OPEN_DIALOG skips, when the layer closes", async () => {
    const { rerender, getByTestId } = render(<Layer open><input type="radio" name="pick" defaultChecked /></Layer>);
    rerender(<Layer open={false} />);
    await tick();
    expect(ghosts()).toHaveLength(1);
    const ghost = ghosts()[0] as HTMLElement;
    expect(ghost.parentElement).toBe(getByTestId("host"));
    expect(ghost.getAttribute("aria-hidden")).toBe("true");
    expect(ghost.textContent).toBe("hi");
    for (const el of [ghost, ...ghost.querySelectorAll("*")]) {
      expect(el.hasAttribute("id")).toBe(false);
      expect(el.hasAttribute("name")).toBe(false); // a radio in the copy joins no group
    }
    // It looks as it did on screen: role and data-* stay.
    expect(ghost.getAttribute("role")).toBe("dialog");
    expect(ghost.getAttribute("data-state")).toBe("open");
    expect(document.querySelector(OPEN_DIALOG)).toBeNull();
  });

  it("drops the copy once its exit is over", () => {
    vi.useFakeTimers();
    const { rerender } = render(<Layer open />);
    rerender(<Layer open={false} />);
    expect(ghosts()).toHaveLength(1);
    act(() => { vi.advanceTimersByTime(259); });
    expect(ghosts()).toHaveLength(1);
    act(() => { vi.advanceTimersByTime(1); });
    expect(ghosts()).toHaveLength(0);
  });

  it("makes no copy under reduced motion", async () => {
    reduced = true;
    const { rerender } = render(<Layer open />);
    rerender(<Layer open={false} />);
    await tick();
    expect(ghosts()).toHaveLength(0);
  });

  it("drops the copy a strict-mode remount makes", async () => {
    render(<StrictMode><Layer open /></StrictMode>);
    await tick();
    expect(ghosts()).toHaveLength(0);
  });

  it("makes no copy of live media or of a layer a swipe slid away", async () => {
    for (const child of [<video key="v" />, <iframe key="f" title="f" />, <canvas key="c" />, <div key="s" data-swiped="" />]) {
      const { rerender, unmount } = render(<Layer open>{child}</Layer>);
      rerender(<Layer open={false}>{child}</Layer>);
      await tick();
      expect(ghosts()).toHaveLength(0);
      unmount();
    }
  });
});
