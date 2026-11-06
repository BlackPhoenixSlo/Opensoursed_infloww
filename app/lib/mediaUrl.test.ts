import { describe, expect, it } from "vitest";

import { proxyImage, proxyScrubFrame } from "./mediaUrl";

const U = "https://cdn2.onlyfans.com/files/v/ab/clip_240p.mp4?Policy=p&Signature=s&Key-Pair-Id=K";

describe("vault media urls carry the media id (the relay re-signs a stale-IP url by it)", () => {
  it.each([
    ["img with id", proxyImage(U, "acct", 42), "42"],
    ["img without id", proxyImage(U, "acct"), null],
    ["scrub with id", proxyScrubFrame(U, "acct", 3, 12, "sid", 42), "42"],
    ["scrub without id", proxyScrubFrame(U, "acct", 3, 12, "sid"), null],
  ])("%s", (_name, url, want) => {
    const q = new URLSearchParams(url.split("?")[1]);
    expect(q.get("u")).toBe(U);
    expect(q.get("media_id")).toBe(want);
  });
});
