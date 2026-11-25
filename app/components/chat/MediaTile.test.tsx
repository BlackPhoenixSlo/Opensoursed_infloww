import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, waitFor } from "@testing-library/react";

import { MediaTile } from "@/components/chat/MediaTile";

class IOStub {
  observe() {}
  unobserve() {}
  disconnect() {}
  takeRecords(): unknown[] {
    return [];
  }
}

beforeEach(() => {
  vi.stubGlobal("IntersectionObserver", IOStub);
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  delete (URL as unknown as { createObjectURL?: unknown }).createObjectURL;
  delete (URL as unknown as { revokeObjectURL?: unknown }).revokeObjectURL;
});

describe("MediaTile skeleton", () => {
  it("reserved-box: the skeleton reserves a min-height and uses no hard aspect ratio", () => {
    const { container } = render(
      <MediaTile
        mediaId={1}
        proxiedUrl="https://cdn.test/a.jpg"
        eager={false}
        className="rounded-md border border-black/10"
      />,
    );

    const ph = container.firstElementChild as HTMLElement;
    expect(ph.tagName).toBe("DIV");
    expect(container.querySelector("img")).toBeNull();
    expect(ph.className).toMatch(/min-h-\[/);
    expect(ph.className).not.toContain("aspect-[4/5]");
  });

  it("reserved-box: once loaded, the image fills the box with object-cover", async () => {
    const blob = new Blob(["x"], { type: "image/jpeg" });
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({
        ok: true,
        status: 200,
        headers: { get: () => null },
        blob: async () => blob,
      })),
    );
    (URL as unknown as { createObjectURL: () => string }).createObjectURL = () => "blob:obj-1";
    (URL as unknown as { revokeObjectURL: (u: string) => void }).revokeObjectURL = () => {};

    const { container } = render(
      <MediaTile
        mediaId={2}
        proxiedUrl="https://cdn.test/b.jpg"
        eager
        alt="photo"
        className="rounded-md border border-black/10"
      />,
    );

    const img = await waitFor(() => {
      const el = container.querySelector("img");
      if (!el) throw new Error("img not yet rendered");
      return el as HTMLImageElement;
    });

    expect(img.getAttribute("src")).toBe("blob:obj-1");
    expect(img.className).toContain("object-cover");
    expect(img.className).not.toContain("aspect-[4/5]");
  });
});
