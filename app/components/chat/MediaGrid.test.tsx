import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent } from "@testing-library/react";

import { renderWithProviders } from "@/test-utils";
import { MessageList, mediaTileBox } from "@/components/chat/MessageList";
import type { OFMedia, OFMessage } from "@/lib/relay";

class IOStub {
  observe() {}
  unobserve() {}
  disconnect() {}
  takeRecords(): unknown[] {
    return [];
  }
}

const baseProps = {
  accountId: "acct1",
  ownerUserId: null,
  isLoading: false,
  isError: false,
  hasOlder: false,
  loadingOlder: false,
  onLoadOlder: () => {},
  onRetry: () => {},
};

function media(over: Partial<OFMedia> & { id: number }): OFMedia {
  return {
    type: "photo",
    files: { thumb: { url: `https://cdn.test/${over.id}.jpg` } },
    ...over,
  } as OFMedia;
}

function withMedia(items: OFMedia[]): OFMessage {
  return {
    id: 1,
    text: "",
    fromUser: { id: 42 },
    createdAt: "2026-06-04T12:00:00.000Z",
    media: items,
  } as OFMessage;
}

beforeEach(() => {
  window.localStorage.clear();
  vi.stubGlobal("IntersectionObserver", IOStub);
  vi.stubGlobal("fetch", vi.fn(() => new Promise(() => {})));
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("mediaTileBox", () => {
  it("is always a square sized only by the compact toggle", () => {
    expect(mediaTileBox(true)).toEqual({ w: 64, h: 64 });
    expect(mediaTileBox(false)).toEqual({ w: 155, h: 155 });
  });
  it("ignores the media's width/height (the box must NOT depend on async dims)", () => {
    expect(mediaTileBox(false, 1200, 800)).toEqual({ w: 155, h: 155 });
    expect(mediaTileBox(false, 800, 1200)).toEqual({ w: 155, h: 155 });
    expect(mediaTileBox(false, null, null)).toEqual({ w: 155, h: 155 });
    expect(mediaTileBox(true, 800, 1200)).toEqual({ w: 64, h: 64 });
    expect(mediaTileBox(true, null, null)).toEqual({ w: 64, h: 64 });
  });
});

describe("MediaStrip tile box", () => {
  function anchors(container: HTMLElement): HTMLAnchorElement[] {
    return Array.from(container.querySelectorAll("a"));
  }

  it("tiles wrap in a flex row (no fixed-row grid)", () => {
    const { container } = renderWithProviders(
      <MessageList
        {...baseProps}
        messages={[withMedia([media({ id: 100, width: 1200, height: 800 })])]}
      />,
    );
    const strip = container.querySelector(".flex-wrap");
    expect(strip).toBeTruthy();
  });

  it("every tile is the SAME fixed square regardless of orientation (compact default = 64)", () => {
    const { container } = renderWithProviders(
      <MessageList
        {...baseProps}
        messages={[
          withMedia([
            media({ id: 100, width: 1200, height: 800 }),
            media({ id: 200, width: 800, height: 1200 }),
          ]),
        ]}
      />,
    );
    const tiles = anchors(container);
    expect(tiles).toHaveLength(2);
    for (const tile of tiles) {
      expect(tile.style.width).toBe("64px");
      expect(tile.style.height).toBe("64px");
    }
  });

  it("null dimensions reserve the same square (no throw, no dependence on dims)", () => {
    const { container } = renderWithProviders(
      <MessageList
        {...baseProps}
        messages={[withMedia([media({ id: 300, width: null, height: null })])]}
      />,
    );
    const [tile] = anchors(container);
    expect(tile).toBeTruthy();
    expect(tile.style.width).toBe("64px");
    expect(tile.style.height).toBe("64px");
  });

  it("a still-processing tile reserves the SAME square the loaded image will (no reflow on load)", () => {
    const { container } = renderWithProviders(
      <MessageList
        {...baseProps}
        messages={[withMedia([{ id: 400, type: "photo", width: 800, height: 1200 } as OFMedia])]}
      />,
    );
    const ph = container.querySelector('div[style*="width"]') as HTMLElement;
    expect(ph).toBeTruthy();
    expect(ph.style.width).toBe("64px");
    expect(ph.style.height).toBe("64px");
  });
});

describe("MediaLightbox (click-to-zoom)", () => {
  it("left-clicking a tile pops the full-res overlay; backdrop click closes it", () => {
    const { container } = renderWithProviders(
      <MessageList
        {...baseProps}
        messages={[withMedia([media({ id: 100, width: 1200, height: 800 })])]}
      />,
    );
    fireEvent.click(container.querySelector("a")!);

    const dialog = document.querySelector('[role="dialog"]') as HTMLElement;
    expect(dialog).toBeTruthy();
    expect(dialog.querySelector("img")).toBeTruthy();

    fireEvent.click(dialog);
    expect(document.querySelector('[role="dialog"]')).toBeNull();
  });

  it("clicking the image itself does NOT close the overlay", () => {
    const { container } = renderWithProviders(
      <MessageList
        {...baseProps}
        messages={[withMedia([media({ id: 100, width: 1200, height: 800 })])]}
      />,
    );
    fireEvent.click(container.querySelector("a")!);
    const img = document.querySelector('[role="dialog"] img') as HTMLElement;
    fireEvent.click(img);
    expect(document.querySelector('[role="dialog"]')).toBeTruthy();
  });
});
