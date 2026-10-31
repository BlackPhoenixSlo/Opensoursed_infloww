/**
 * VaultTile — a tile must never ask for a picture that cannot exist.
 *
 * A voice note has no frame: OF ships audio with ONE variant, `files.full`, and
 * that file IS the audio. Pointing an <img> at it costs two OF calls and one of
 * six process-wide in-flight still slots before it 404s, uncached, on every
 * render — for 17.6% of one account's 2,527 items.
 *
 * There is no audio branch in the tile, and these cases are why there does not
 * need to be. Two rules do it structurally: the relay stamps `_thumb` only for a
 * kind that HAS a still, and `vaultTileThumb`'s chain stops at `preview` — never
 * `files.full`, which across a 6,388-item mirror is the sole variant for audio
 * and for nothing else. Nothing resolves, so nothing is requested.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";

import VaultTile from "@/components/vault/VaultTile";
import type { VaultMedia } from "@/lib/relay";

const ACCT = "8000149";
const OF_URL = "https://cdn2.onlyfans.com/files/2021_11_22/0g/0gw/0gwnzeh3cf8dgfj70262";
const CACHED = `/admin/vault-ai/thumb?account_id=${ACCT}&media_id=2281172673`;

/** A row as the browser receives it. `_thumb` is present exactly when the relay
 *  decided this kind has a still — that is the contract these cases hold it to. */
function tile(type: string, files: VaultMedia["files"], thumb?: string): VaultMedia {
  return { id: 2281172673, type, files, _thumb: thumb };
}

/** The prod shapes: audio carries `full` and nothing else; a picture always
 *  carries a real variant (measured over the whole mirror). */
const AUDIO_FILES = { full: { url: OF_URL } };
const PICTURE_FILES = {
  thumb: { url: `${OF_URL}_thumb` },
  preview: { url: `${OF_URL}_preview` },
  full: { url: OF_URL },
};

const mount = (m: VaultMedia) => render(<VaultTile media={m} accountId={ACCT} />);

afterEach(cleanup);

describe("VaultTile", () => {
  it("an audio row issues no image request at all", () => {
    // As the relay now serves it: no `_thumb`, because audio has no still.
    const { container } = mount(tile("audio", AUDIO_FILES));

    expect(container.querySelectorAll("img")).toHaveLength(0);
    expect(container.innerHTML).not.toContain("/admin/vault-ai/thumb");
    expect(container.innerHTML).not.toContain("/img?");
    // …and says what it is instead of showing a broken frame.
    expect(screen.getByText("audio")).toBeInTheDocument();
  });

  it("never falls back to files.full — the audio file itself", () => {
    // THE regression that made the first fix useless: dropping `_thumb` while
    // the chain still ended at `full` just moved the doomed request from
    // /admin/vault-ai/thumb to /img. `full` is not in the chain, so any media
    // whose only variant is `full` renders a placeholder, whatever its type.
    const { container } = mount(tile("photo", { full: { url: OF_URL } }));

    expect(container.querySelectorAll("img")).toHaveLength(0);
    expect(container.innerHTML).not.toContain("/img?");
  });

  it("a photo renders the relay's cached thumb", () => {
    const { container } = mount(tile("photo", PICTURE_FILES, CACHED));

    const imgs = container.querySelectorAll("img");
    expect(imgs).toHaveLength(1);
    expect(imgs[0].getAttribute("src")).toBe(CACHED);
  });

  it("a video renders the relay's cached thumb", () => {
    const { container } = mount(tile("video", PICTURE_FILES, CACHED));

    const imgs = container.querySelectorAll("img");
    expect(imgs).toHaveLength(1);
    expect(imgs[0].getAttribute("src")).toBe(CACHED);
  });

  it("a photo on the live path still proxies the OF url", () => {
    // No `_thumb` — the uncached/live source. A picture must keep its fallback.
    const { container } = mount(tile("photo", PICTURE_FILES));

    const imgs = container.querySelectorAll("img");
    expect(imgs).toHaveLength(1);
    expect(imgs[0].getAttribute("src")).toContain("/img?");
  });
});

/**
 * The hover glue: the tile drives the shared useHoverPreview (mouse only, after
 * the dwell) and every storyboard GET and the one cancel POST carry the same
 * session id.
 */
describe("VaultTile hover preview", () => {
  const MP4 = "https://cdn.example/v-240.mp4";
  const VIDEO: VaultMedia = { id: 7, type: "video", duration: 34, files: { full: { url: MP4 } }, _thumb: CACHED };

  const fetchMock = vi.fn((..._args: unknown[]) => Promise.resolve(new Response(null)));
  const cancelSids = () =>
    fetchMock.mock.calls
      .map(([u]) => new URL(String(u), "http://x"))
      .filter((u) => u.pathname === "/img/scrub/cancel")
      .map((u) => u.searchParams.get("sid"));
  const frames = () => document.querySelectorAll<HTMLImageElement>('img[src^="/img/scrub?"]');
  const sidsOf = () => new Set([...frames()].map((f) => new URL(f.src, "http://x").searchParams.get("sid")));
  const tileEl = () => screen.getByTitle(/^#7 · video/);

  function hover(accountId: string | null = ACCT, pointerType = "mouse") {
    const view = render(<VaultTile media={VIDEO} accountId={accountId} />);
    fireEvent.pointerEnter(tileEl(), { pointerType });
    act(() => { vi.advanceTimersByTime(400); });
    return view;
  }

  beforeEach(() => {
    fetchMock.mockClear();
    vi.stubGlobal("fetch", fetchMock);
    vi.useFakeTimers();
  });
  afterEach(() => {
    cleanup();
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("a mouse dwell mounts the storyboard under one session", () => {
    hover();
    expect(frames()).toHaveLength(12);
    const sids = sidsOf();
    expect(sids.size).toBe(1);
    expect([...sids][0]).toBeTruthy();
  });

  it("no frames before the dwell", () => {
    render(<VaultTile media={VIDEO} accountId={ACCT} />);
    fireEvent.pointerEnter(tileEl(), { pointerType: "mouse" });
    act(() => { vi.advanceTimersByTime(399); });
    expect(frames()).toHaveLength(0);
  });

  it("leave unmounts the frames and posts exactly one cancel for that session", () => {
    hover();
    const [sid] = sidsOf();
    fireEvent.pointerLeave(tileEl(), { pointerType: "mouse" });
    expect(frames()).toHaveLength(0);
    expect(cancelSids()).toEqual([sid]);
  });

  it("unmount mid-hover posts exactly one cancel for that session", () => {
    const { unmount } = hover();
    const [sid] = sidsOf();
    unmount();
    expect(cancelSids()).toEqual([sid]);
  });

  it("no account: no session (no slideshow timers), no storyboard, no fetch", () => {
    const { unmount } = hover(null);
    expect(vi.getTimerCount()).toBe(0);
    expect(frames()).toHaveLength(0);
    unmount();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it.each(["touch", "pen"])("a %s pointer starts nothing", (pointerType) => {
    const { unmount } = hover(ACCT, pointerType);
    expect(frames()).toHaveLength(0);
    unmount();
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
