import { describe, it, expect } from "vitest";
import type { VaultMedia } from "@/lib/relay";
import { progressiveVideoSrc, gifClipSrc, videoPosterFrames, isDrmVideo, isDrmOnlyVideo, evenFrameIndex } from "./VaultPicker";

const drmVideo: VaultMedia = {
  id: 4340233385,
  type: "video",
  duration: 14,
  videoSources: { "720": null, "240": null },
  files: {
    thumb: { url: "https://cdn2.onlyfans.com/.../300x300_frame_0.jpg" },
    full: { width: 576, height: 1024, sources: [] },
    preview: {
      url: "https://cdn2.onlyfans.com/.../576x1024_frame_0.jpg",
      options: [
        { id: 1, url: "https://cdn2.onlyfans.com/a/576x1024_frame_0.jpg" },
        { id: 2, url: "https://cdn2.onlyfans.com/b/576x1024_frame_1.jpg" },
        { id: 3, url: "https://cdn2.onlyfans.com/c/576x1024_frame_2.jpg" },
      ],
    },
    drm: { manifest: { hls: "https://cdn3.onlyfans.com/hls/.../x.m3u8", dash: "https://cdn3.onlyfans.com/dash/.../x.mpd" } },
  },
};

const progressiveVideo: VaultMedia = {
  id: 999,
  type: "video",
  duration: 8,
  videoSources: { "720": "https://cdn2.onlyfans.com/.../720.mp4", "240": null },
  files: { thumb: { url: "https://cdn2.onlyfans.com/.../t.jpg" } },
};

const photo: VaultMedia = {
  id: 4489341126,
  type: "photo",
  files: { full: { url: "https://cdn2.onlyfans.com/.../1852x746.jpg" } },
};

describe("vault video source resolution", () => {
  it("resolves a progressive mp4 for old uploads", () => {
    expect(progressiveVideoSrc(progressiveVideo)).toBe(
      "https://cdn2.onlyfans.com/.../720.mp4",
    );
    expect(isDrmVideo(progressiveVideo)).toBe(false);
  });

  it("prefers the cheapest source (240p) over 720p for scrub frames", () => {
    const both: VaultMedia = {
      id: 1000,
      type: "video",
      duration: 8,
      videoSources: {
        "720": "https://cdn2.onlyfans.com/.../720.mp4",
        "240": "https://cdn2.onlyfans.com/.../240.mp4",
      },
      files: { thumb: { url: "https://cdn2.onlyfans.com/.../t.jpg" } },
    };
    expect(progressiveVideoSrc(both)).toBe("https://cdn2.onlyfans.com/.../240.mp4");
  });

  it("returns NULL progressive src for DRM-only videos (never the poster JPEG)", () => {
    expect(progressiveVideoSrc(drmVideo)).toBeNull();
  });

  it("flags DRM via the authoritative files.drm manifest, exposes poster frames", () => {
    expect(isDrmVideo(drmVideo)).toBe(true);
    expect(isDrmOnlyVideo(drmVideo)).toBe(true);
    expect(videoPosterFrames(drmVideo)).toEqual([
      "https://cdn2.onlyfans.com/a/576x1024_frame_0.jpg",
      "https://cdn2.onlyfans.com/b/576x1024_frame_1.jpg",
      "https://cdn2.onlyfans.com/c/576x1024_frame_2.jpg",
    ]);
  });

  it("treats photos and non-video items as non-DRM with no progressive src", () => {
    expect(progressiveVideoSrc(photo)).toBeNull();
    expect(isDrmVideo(photo)).toBe(false);
    expect(videoPosterFrames(photo)).toEqual([]);
  });

  it("resolves a gif to its .mp4 (OF stores a gif as a clip), never DRM", () => {
    const gif: VaultMedia = {
      id: 3, type: "gif",
      files: { thumb: { url: "https://cdn2.onlyfans.com/g/150x150_frame_0.jpg" }, full: { url: "https://cdn2.onlyfans.com/g/0i1n8it6_source.mp4" } },
    };
    expect(gifClipSrc(gif)).toBe("https://cdn2.onlyfans.com/g/0i1n8it6_source.mp4");
    expect(progressiveVideoSrc(gif)).toBeNull();
    expect(isDrmOnlyVideo(gif)).toBe(false);
  });

  it("still flags DRM (via manifest) even when OF ships no poster frames", () => {
    const noFrames: VaultMedia = {
      id: 1, type: "video", videoSources: { "720": null, "240": null },
      files: { drm: { manifest: { hls: "https://cdn3.onlyfans.com/hls/x.m3u8" } } },
    };
    expect(isDrmVideo(noFrames)).toBe(true);
    expect(isDrmOnlyVideo(noFrames)).toBe(true);
    expect(videoPosterFrames(noFrames)).toEqual([]);
  });

  it("spreads N poster frames evenly across the 12-beat cursor (no repeat-jump, no out-of-range)", () => {
    const seqFor = (n: number) =>
      Array.from({ length: 12 }, (_, beat) => evenFrameIndex(beat, n, 12));

    for (const n of [1, 3, 5, 9, 12]) {
      const seq = seqFor(n);
      expect(Math.min(...seq)).toBe(0);
      expect(Math.max(...seq)).toBe(n - 1);
      expect(new Set(seq).size).toBe(n);
      for (let i = 1; i < seq.length; i++) expect(seq[i]).toBeGreaterThanOrEqual(seq[i - 1]);
    }
    expect(seqFor(12)).toEqual([0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]);
    expect(seqFor(5)).toEqual([0, 0, 0, 1, 1, 2, 2, 2, 3, 3, 4, 4]);
    expect(evenFrameIndex(11, 0, 12)).toBe(0);
  });

  it("prefers playback when a DRM file unexpectedly also has a progressive mp4", () => {
    const both: VaultMedia = {
      id: 2, type: "video",
      videoSources: { "720": "https://cdn2.onlyfans.com/x/720.mp4", "240": null },
      files: { drm: { manifest: { hls: "https://cdn3.onlyfans.com/hls/x.m3u8" } } },
    };
    expect(isDrmVideo(both)).toBe(true);
    expect(isDrmOnlyVideo(both)).toBe(false);
    expect(progressiveVideoSrc(both)).toBe("https://cdn2.onlyfans.com/x/720.mp4");
  });
});
