/** MediaStrip: existing callers (no `thumbSrc`) keep the OF-url thumb through `proxyImage`; `thumbSrc` replaces it. */
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render } from "@testing-library/react";

import { MediaStrip } from "@/components/settings/MediaStrip";
import { proxyImage } from "@/lib/mediaUrl";

afterEach(cleanup);

const media = [
  { id: 1, type: "photo", files: { thumb: { url: "https://cdn.example/t1.jpg" } } },
  { id: 2, type: "video" },
];
const srcs = (c: HTMLElement) => [...c.querySelectorAll("img")].map((i) => i.getAttribute("src"));

describe("MediaStrip", () => {
  it("without thumbSrc: the OF thumb through proxyImage, the type when there is none (callers unchanged)", () => {
    const { container, getByText } = render(<MediaStrip media={media} accountId="acc-a" />);
    expect(srcs(container)).toEqual([proxyImage("https://cdn.example/t1.jpg", "acc-a")]);
    expect(getByText("video")).toBeTruthy();
  });

  it("with thumbSrc: every tile from it, files ignored", () => {
    const { container } = render(<MediaStrip media={media} accountId="acc-a" thumbSrc={(m) => `/local/${m.id}`} />);
    expect(srcs(container)).toEqual(["/local/1", "/local/2"]);
  });
});
