import { act, cleanup, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { VaultGifLoop } from "./VaultGifLoop";
import { MAX_GIF_LOOPS } from "./vaultGifLoopState";

// A controllable observer: `see(el, on)` fires the callback the tile registered for `el`.
const watchers = new Map<Element, (e: { isIntersecting: boolean }[]) => void>();
class IOMock {
  constructor(private cb: (e: { isIntersecting: boolean }[]) => void) {}
  observe(el: Element) { watchers.set(el, this.cb); }
  disconnect() { for (const [el, cb] of watchers) if (cb === this.cb) watchers.delete(el); }
  unobserve() {}
  takeRecords() { return []; }
}
const see = (el: Element, on: boolean) => act(() => watchers.get(el)!([{ isIntersecting: on }]));

let load: ReturnType<typeof vi.fn<() => void>>;
beforeEach(() => {
  watchers.clear();
  vi.stubGlobal("IntersectionObserver", IOMock);
  load = vi.fn<() => void>();
  vi.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue(undefined);
  vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(() => {});
  vi.spyOn(HTMLMediaElement.prototype, "load").mockImplementation(load);
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

const loops = (n: number) => {
  const { container } = render(
    <>{Array.from({ length: n }, (_, i) => <VaultGifLoop key={i} src={`/img?u=${i}.mp4`} />)}</>,
  );
  return [...container.querySelectorAll("video")];
};
const withSrc = (vs: HTMLVideoElement[]) => vs.filter((v) => v.getAttribute("src")).length;

describe("VaultGifLoop", () => {
  it("no src off screen; at most MAX_GIF_LOOPS hold one; a leaver detaches and hands its slot on", () => {
    const vs = loops(MAX_GIF_LOOPS + 2);
    expect(withSrc(vs)).toBe(0);
    expect(vs.every((v) => v.getAttribute("preload") === "none")).toBe(true);

    vs.forEach((v) => see(v, true));
    expect(withSrc(vs)).toBe(MAX_GIF_LOOPS);
    expect(vs[MAX_GIF_LOOPS].getAttribute("src")).toBeNull();

    see(vs[0], false);
    expect(vs[0].getAttribute("src")).toBeNull();
    expect(vs[0].getAttribute("preload")).toBe("none");
    expect(load).toHaveBeenCalledTimes(1);   // the decoder let go
    expect(vs[MAX_GIF_LOOPS].getAttribute("src")).toBe(`/img?u=${MAX_GIF_LOOPS}.mp4`);
    expect(withSrc(vs)).toBe(MAX_GIF_LOOPS);
  });

  it("unmounting frees its slot", () => {
    const first = render(<VaultGifLoop src="/a.mp4" />);
    const v = first.container.querySelector("video")!;
    see(v, true);
    first.unmount();
    // Every slot free again: MAX_GIF_LOOPS fresh loops all attach.
    const vs = loops(MAX_GIF_LOOPS);
    vs.forEach((x) => see(x, true));
    expect(withSrc(vs)).toBe(MAX_GIF_LOOPS);
  });

  it("a hidden tab pauses it; back, it plays", () => {
    const [v] = loops(1);
    see(v, true);
    const play = vi.mocked(HTMLMediaElement.prototype.play);
    const pause = vi.mocked(HTMLMediaElement.prototype.pause);
    play.mockClear();
    pause.mockClear();
    const hidden = vi.spyOn(document, "hidden", "get").mockReturnValue(true);
    act(() => { document.dispatchEvent(new Event("visibilitychange")); });
    expect(pause).toHaveBeenCalled();
    expect(play).not.toHaveBeenCalled();
    hidden.mockReturnValue(false);
    act(() => { document.dispatchEvent(new Event("visibilitychange")); });
    expect(play).toHaveBeenCalled();
  });
});
