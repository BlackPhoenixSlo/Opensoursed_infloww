import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";

import VaultTile from "@/components/vault/VaultTile";
import type { ThumbRetry } from "@/hooks/useThumbAutoRefresh";
import { vaultTileThumb } from "@/lib/mediaUrl";
import type { VaultMedia } from "@/lib/relay";

const ACCT = "8000149";
const OF_URL = "https://cdn2.onlyfans.com/files/2021_11_22/0g/0gw/0gwnzeh3cf8dgfj70262";
const CACHED = `/admin/vault-ai/thumb?account_id=${ACCT}&media_id=2281172673`;

function tile(type: string, files: VaultMedia["files"], thumb?: string): VaultMedia {
  return { id: 2281172673, type, files, _thumb: thumb };
}

const AUDIO_FILES = { full: { url: OF_URL } };
const PICTURE_FILES = {
  thumb: { url: `${OF_URL}_thumb` },
  preview: { url: `${OF_URL}_preview` },
  full: { url: OF_URL },
};

const THUMBS: ThumbRetry = { tile: (m) => ({ src: vaultTileThumb(m, ACCT), onError: () => {} }), refreshed: () => {} };
const mount = (m: VaultMedia) => render(<VaultTile media={m} accountId={ACCT} thumbs={THUMBS} />);

afterEach(cleanup);

describe("VaultTile", () => {
  it("an audio row issues no image request at all", () => {
    const { container } = mount(tile("audio", AUDIO_FILES));

    expect(container.querySelectorAll("img")).toHaveLength(0);
    expect(container.innerHTML).not.toContain("/admin/vault-ai/thumb");
    expect(container.innerHTML).not.toContain("/img?");
    expect(screen.getByText("audio")).toBeInTheDocument();
  });

  it("never falls back to files.full — the audio file itself", () => {
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
    const { container } = mount(tile("photo", PICTURE_FILES));

    const imgs = container.querySelectorAll("img");
    expect(imgs).toHaveLength(1);
    expect(imgs[0].getAttribute("src")).toContain("/img?");
  });
});

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
    const view = render(<VaultTile media={VIDEO} accountId={accountId} thumbs={THUMBS} />);
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
    render(<VaultTile media={VIDEO} accountId={ACCT} thumbs={THUMBS} />);
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
