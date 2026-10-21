/**
 * MessageList — video media and the media count: the video marker on a tile,
 * playback in the viewer, a bubble's "2 photos · 1 video" count, and the
 * fan-history crash guard. The same seam as `MessageList.test.tsx` (kept
 * under 1000 lines): the `MessageList` render through `renderWithProviders`,
 * the relay mocked by URL. Fixture identifiers are invented.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, waitFor } from "@testing-library/react";

vi.mock("@/lib/relay", async (orig) =>
  (await import("./composerTestHarness")).mockRelayModule(await orig()));

import { renderWithProviders } from "@/test-utils";
import { MessageList } from "@/components/chat/MessageList";
import type { OFMedia } from "@/lib/relay";
import { relayGet, resetComposerHarness, routeRelay } from "./composerTestHarness";
import { baseProps, msg } from "./messageListTestHarness";

const POSTER = "https://cdn/clip-poster.jpg";
const CLIP = "https://cdn/clip.mp4";

/** A video as OF sends it: the clip in `full`/`source`, its poster frame in
 *  `preview`, no `thumb`, so a tile that reads `source` gets the raw clip. */
const video = (over: Partial<OFMedia> = {}): OFMedia => ({
  id: 501,
  type: "video",
  duration: 65,
  files: { full: { url: CLIP }, source: { url: CLIP }, preview: { url: POSTER } },
  ...over,
});
const photo = (id: number): OFMedia => ({
  id,
  type: "photo",
  files: { thumb: { url: `https://cdn/p${id}.jpg` }, source: { url: `https://cdn/p${id}-full.jpg` } },
});

/** A Fan's free message holding `media`. */
const incoming = (media: OFMedia[]) => [msg({ id: 1, fromUser: { id: 42 }, media })];

const fetchSpy = vi.fn((..._args: unknown[]) => new Promise<Response>(() => {}));
const pauseSpy = vi.fn();

beforeEach(() => {
  window.localStorage.clear();
  vi.stubGlobal("IntersectionObserver", class {
    observe() {}
    unobserve() {}
    disconnect() {}
    takeRecords(): unknown[] { return []; }
  });
  vi.stubGlobal("fetch", fetchSpy);
  vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(pauseSpy);
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  fetchSpy.mockClear();
  pauseSpy.mockClear();
  resetComposerHarness();
});

/** Open the viewer on the bubble's first tile. */
function openViewer(container: HTMLElement) {
  fireEvent.click(container.querySelector("a[href]")!);
  return document.body.querySelector("[role='dialog']") as HTMLElement;
}

describe("MessageList video tiles", () => {
  it("a video tile shows a play glyph and its duration, '1:05' for 65 seconds", () => {
    const { getByRole, getByText } = renderWithProviders(
      <MessageList {...baseProps} messages={incoming([video()])} ownerUserId={555} />,
    );
    expect(getByRole("img", { name: "Video" })).toBeTruthy();
    expect(getByText("1:05")).toBeTruthy();
  });

  it("a video over an hour reads h:mm:ss", () => {
    const { getByText } = renderWithProviders(
      <MessageList {...baseProps} messages={incoming([video({ duration: 3725 })])} ownerUserId={555} />,
    );
    expect(getByText("1:02:05")).toBeTruthy();
  });

  it("reads the duration from files.full when OF puts it there (service/messages.py:186-190)", () => {
    const { getByText } = renderWithProviders(
      <MessageList {...baseProps} ownerUserId={555} messages={incoming([video({
        duration: undefined,
        files: { full: { url: CLIP, duration: 65 }, preview: { url: POSTER } },
      })])} />,
    );
    expect(getByText("1:05")).toBeTruthy();
  });

  it("a video tile loads its poster frame, never the clip", () => {
    renderWithProviders(
      <MessageList {...baseProps} messages={incoming([video()])} ownerUserId={555} />,
    );
    const urls = fetchSpy.mock.calls.map((c) => String(c[0]));
    expect(urls).toHaveLength(1);
    expect(urls[0]).toContain(encodeURIComponent(POSTER));
    expect(urls[0]).not.toContain("mp4");
  });

  it("an image tile shows no play glyph", () => {
    const { queryByRole } = renderWithProviders(
      <MessageList {...baseProps} messages={incoming([photo(601)])} ownerUserId={555} />,
    );
    expect(queryByRole("img", { name: "Video" })).toBeNull();
  });

  it("our PPV video keeps its price badge beside the duration", () => {
    const { getByText } = renderWithProviders(
      <MessageList {...baseProps} ownerUserId={555}
                   messages={[msg({ id: 2, fromUser: { id: 555 }, price: 35, media: [video()] })]} />,
    );
    expect(getByText("$35")).toBeTruthy();
    expect(getByText("1:05")).toBeTruthy();
  });
});

describe("MessageList viewer on a video", () => {
  it("renders a video element with controls, the poster and the proxied clip, not autoplaying", () => {
    const { container } = renderWithProviders(
      <MessageList {...baseProps} messages={incoming([video()])} ownerUserId={555} />,
    );
    const dialog = openViewer(container);
    const el = dialog.querySelector("video")!;
    expect(el).toBeTruthy();
    expect(el.controls).toBe(true);
    expect(el.hasAttribute("playsinline")).toBe(true);
    expect(el.autoplay).toBe(false);
    expect(el.getAttribute("poster")).toContain(encodeURIComponent(POSTER));
    expect(el.getAttribute("src")).toContain(encodeURIComponent(CLIP));
    expect(dialog.querySelector("img")).toBeNull();
  });

  it("on an image renders an img and no video", () => {
    const { container } = renderWithProviders(
      <MessageList {...baseProps} messages={incoming([photo(601)])} ownerUserId={555} />,
    );
    const dialog = openViewer(container);
    expect(dialog.querySelector("img")).toBeTruthy();
    expect(dialog.querySelector("video")).toBeNull();
  });

  it("paging away from a video pauses it", () => {
    const { container } = renderWithProviders(
      <MessageList {...baseProps} messages={incoming([video(), photo(601)])} ownerUserId={555} />,
    );
    const dialog = openViewer(container);
    expect(pauseSpy).not.toHaveBeenCalled();
    fireEvent.click(dialog.querySelector("[aria-label='Next image']")!);
    expect(pauseSpy).toHaveBeenCalled();
    expect(dialog.querySelector("video")).toBeNull();
  });

  it("arrow keys on the focused video seek it and do not page", () => {
    const { container } = renderWithProviders(
      <MessageList {...baseProps} messages={incoming([video(), photo(601)])} ownerUserId={555} />,
    );
    const dialog = openViewer(container);
    const el = dialog.querySelector("video")!;
    fireEvent.keyDown(el, { key: "ArrowRight" });
    fireEvent.keyDown(el, { key: "ArrowLeft" });
    expect(dialog.querySelector("video")).toBe(el);
    expect(dialog.textContent).toContain("1 / 2");
  });

  it("a playable video with no still opens from a clickable tile showing the play glyph", () => {
    const { container, getByRole } = renderWithProviders(
      <MessageList {...baseProps} ownerUserId={555}
                   messages={incoming([video({ files: { full: { url: CLIP } } })])} />,
    );
    expect(getByRole("img", { name: "Video" })).toBeTruthy();
    expect(container.querySelector("a[href]")).toBeTruthy();
    const dialog = openViewer(container);
    expect(dialog.querySelector("video")?.getAttribute("src")).toContain(encodeURIComponent(CLIP));
    expect(dialog.querySelector("video")?.hasAttribute("poster")).toBe(false);
  });

  it("with no playable clip shows the poster and 'Video not available', not 'loading…'", () => {
    const { container } = renderWithProviders(
      <MessageList {...baseProps} ownerUserId={555}
                   messages={incoming([video({ files: { preview: { url: POSTER } } })])} />,
    );
    const dialog = openViewer(container);
    expect(dialog.textContent).toContain("Video not available");
    expect(dialog.textContent).not.toContain("loading");
    expect(dialog.querySelector("video")).toBeNull();
    expect(dialog.querySelector("img")?.getAttribute("src")).toContain(encodeURIComponent(POSTER));
  });
});

describe("MessageList media count", () => {
  it("a bubble with 2 photos and 1 video reads '2 photos · 1 video'", () => {
    const { getByText } = renderWithProviders(
      <MessageList {...baseProps} ownerUserId={555}
                   messages={incoming([photo(601), video(), photo(602)])} />,
    );
    expect(getByText("2 photos · 1 video")).toBeTruthy();
  });

  it("a single item shows no count", () => {
    const { container } = renderWithProviders(
      <MessageList {...baseProps} messages={incoming([video()])} ownerUserId={555} />,
    );
    expect(container.textContent).not.toMatch(/\d+ (photo|video)/);
  });
});

describe("MessageList fan-history crash guard", () => {
  it("a fan-history response without by_media still renders the thread and the strip", async () => {
    routeRelay("/admin/vault/fan-history", () => ({}));
    const { container, getByText } = renderWithProviders(
      <MessageList {...baseProps} ownerUserId={555} fanId={42}
                   messages={[msg({ id: 3, text: "for you", fromUser: { id: 555 }, media: [photo(601)] })]} />,
    );
    await waitFor(() =>
      expect(relayGet.mock.calls.some((c) => String(c[0]).includes("/admin/vault/fan-history"))).toBe(true));
    // Let the query resolve and the strip re-render with its data.
    await new Promise((r) => setTimeout(r, 0));
    expect(getByText("for you")).toBeTruthy();
    expect(container.querySelector("a[href]")).toBeTruthy();
  });
});
