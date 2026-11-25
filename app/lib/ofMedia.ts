import type { OFMedia, OFMediaFiles } from "@/lib/relay";

// OF stores a gif as an mp4, so a gif's `full` is a video whatever its `type` says.
const NON_IMAGE_EXTS = [
  ".mp4", ".m3u8", ".mov", ".webm", ".m4v",
  ".mp3", ".m4a", ".wav", ".aac", ".ogg", ".opus",
];

// `thumb` is a 300x300 centre-crop of a portrait: wrong default; `preview` keeps the aspect ratio. Mirrors of_shapes._VISION_VARIANTS.
const VISION_VARIANTS: (keyof OFMediaFiles)[] = [
  "preview", "full", "source", "squarePreview", "thumb",
];

function isNonImageUrl(url: string | null | undefined): boolean {
  if (!url) return false;
  const path = url.split("?")[0].toLowerCase();
  return NON_IMAGE_EXTS.some((ext) => path.endsWith(ext));
}

export function stillUrl(media: OFMedia | null | undefined): string | null {
  if (!media) return null;
  const files = media.files;
  if (files) {
    for (const key of VISION_VARIANTS) {
      const url = files[key]?.url;
      if (url && !isNonImageUrl(url)) return url;
    }
  }
  const loose = media.url;
  return loose && !isNonImageUrl(loose) ? loose : null;
}

export function giphyUrl(giphyId: string): string {
  // Fansly's shim puts a full url in `giphyId` (KLIPY, not Giphy); only a bare giphy id gets wrapped.
  if (/^https?:\/\//i.test(giphyId)) return giphyId;
  return `https://media.giphy.com/media/${giphyId}/giphy.gif`;
}
