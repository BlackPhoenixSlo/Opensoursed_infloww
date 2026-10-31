/**
 * FanDrawer's PPV video thumb (`VideoScrubThumb`): the same hover preview as
 * the vault picker's tiles, through the shared useHoverPreview. It used to
 * carry its own copy of the state machine; these pin where that copy had
 * drifted from the picker's.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";

import { VideoScrubThumb } from "./FanDrawer";

const THUMB = {
  rawUrl: "https://cdn.example/v-thumb.jpg",
  rawFullUrl: "https://cdn.example/v-full.jpg",
  rawVideoUrl: "https://cdn.example/v-240.mp4",
  durationSec: 34,
  isVideo: true,
};

const fetchMock = vi.fn((..._args: unknown[]) => Promise.resolve(new Response(null)));
const cancelSids = () =>
  fetchMock.mock.calls
    .map(([u]) => new URL(String(u), "http://x"))
    .filter((u) => u.pathname === "/img/scrub/cancel")
    .map((u) => u.searchParams.get("sid"));
const frames = () => document.querySelectorAll<HTMLImageElement>('img[src^="/img/scrub?"]');
const thumb = () => screen.getByTitle("Hover to scrub, click to play");

beforeEach(() => {
  fetchMock.mockClear();
  vi.stubGlobal("fetch", fetchMock);
  vi.stubGlobal("matchMedia", (q: string) => ({ matches: true, media: q, addEventListener() {}, removeEventListener() {} }));
  vi.useFakeTimers();
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

function hoverCommitted() {
  const view = render(<VideoScrubThumb thumb={THUMB} accountId="acct-1" onClick={() => {}} />);
  fireEvent.mouseEnter(thumb());
  act(() => { vi.advanceTimersByTime(400); });
  return view;
}

describe("FanDrawer VideoScrubThumb", () => {
  // Its "copied" formula had lost VaultPicker's ×1.3 padding: a 34s clip read
  // 6s here and 8s in the picker, for the same relay build.
  it("counts down the vault picker's padded build ETA", () => {
    hoverCommitted();
    expect(frames()).toHaveLength(12);
    expect(screen.getByText("8s")).toBeInTheDocument();
  });

  // Its cancel POST only fired when `hovered` flipped false, so closing the
  // drawer mid-hover left the relay downloading a video nobody was watching.
  it("cancels the relay build when it unmounts mid-hover", () => {
    const { unmount } = hoverCommitted();
    const sid = new URL(frames()[0].src, "http://x").searchParams.get("sid");
    expect(sid).toBeTruthy();
    unmount();
    expect(cancelSids()).toEqual([sid]);
  });

  it("cancels on leave, and a re-hover runs under a new session", () => {
    hoverCommitted();
    const first = new URL(frames()[0].src, "http://x").searchParams.get("sid");
    fireEvent.mouseLeave(thumb());
    expect(frames()).toHaveLength(0);
    expect(cancelSids()).toEqual([first]);

    fireEvent.mouseEnter(thumb());
    act(() => { vi.advanceTimersByTime(400); });
    const second = new URL(frames()[0].src, "http://x").searchParams.get("sid");
    expect(second).toBeTruthy();
    expect(second).not.toBe(first);
  });

  it("drops the shimmer when a frame paints or frame 0 fails", () => {
    hoverCommitted();
    expect(document.querySelector(".scrub-shimmer")).not.toBeNull();
    fireEvent.error(frames()[0]);
    expect(document.querySelector(".scrub-shimmer")).toBeNull();
    fireEvent.load(frames()[3]);
    expect(frames()[3].style.opacity).toBe("1");
  });
});
