"use client";

/**
 * MediaVideo — what a bubble's media strip and viewer do differently for a
 * video: the ▶ and duration on its tile, the poster it shows instead of the
 * raw clip, playback in the viewer, and the bundle's "2 photos · 1 video"
 * count. Split out of `MessageList.tsx`, which renders these.
 *
 * A video is OF's `type === "video"`. Its clip is `files.full` (or `source`,
 * or a bare `url`); its poster is the first still `stillUrl` finds, which
 * skips the clip by extension. Both load through the relay's `/img` proxy,
 * which forwards Range requests, so `<video>` can seek.
 */

import { useEffect, useRef } from "react";

import type { OFMedia } from "@/lib/relay";
import { fmtDuration } from "@/lib/format";
import { proxyImage } from "@/lib/mediaUrl";
import { stillUrl } from "@/lib/ofMedia";
import { MP } from "@/lib/messagesPro";
import { cn } from "@/lib/utils";

export function isVideoMedia(m: OFMedia): boolean {
  return m.type === "video";
}

/** The raw (unproxied) clip URL, or null when OF gave none (locked, unbought). */
export function clipUrl(m: OFMedia): string | null {
  if (m.canView === false) return null;
  return m.files?.full?.url || m.files?.source?.url || m.url || null;
}

/** "2 photos · 1 video" for a bundle; "" for a single item. Anything that is
 *  not a video or audio counts as a photo. */
export function mediaCountLabel(items: OFMedia[]): string {
  if (items.length < 2) return "";
  const n = { photo: 0, video: 0, audio: 0 };
  for (const m of items) n[m.type === "video" ? "video" : m.type === "audio" ? "audio" : "photo"]++;
  return [
    n.photo ? `${n.photo} photo${n.photo > 1 ? "s" : ""}` : "",
    n.video ? `${n.video} video${n.video > 1 ? "s" : ""}` : "",
    n.audio ? `${n.audio} audio` : "",
  ].filter(Boolean).join(" · ");
}

/** The ▶ (viewable tiles only) and the duration, painted on a video tile. */
export function VideoTileMarks({ media, glyph, duration }: { media: OFMedia; glyph: boolean; duration: boolean }) {
  const label = duration ? fmtDuration(media.duration ?? media.files?.full?.duration) : "";
  return (
    <>
      {glyph && (
        <span
          role="img"
          aria-label="Video"
          className={cn(MP.ours.MessageList.tilePlay, "absolute grid place-items-center bg-black/55 text-white z-10 pointer-events-none")}
        >
          ▶
        </span>
      )}
      {label && (
        <span className={cn(MP.ours.MessageList.tileDuration, "absolute bg-black/60 text-white z-10 pointer-events-none")}>
          {label}
        </span>
      )}
    </>
  );
}

/** The viewer's body on a video: a `<video>` with controls and its poster
 *  (never autoplaying), paused when the viewer pages away; or the poster and
 *  "Video not available" when there is no clip to play. */
export function ViewerVideo({ media, accountId }: { media: OFMedia; accountId: string | null }) {
  const ref = useRef<HTMLVideoElement | null>(null);
  useEffect(() => {
    const el = ref.current;
    return () => el?.pause();
  }, []);
  const poster = proxyImage(stillUrl(media), accountId);
  const clip = clipUrl(media);
  if (!clip) {
    return (
      <div className="flex flex-col items-center">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        {poster && <img src={poster} alt="" className={cn(MP.ours.MessageList.zoomImage, "object-contain")} />}
        <div className={cn(MP.ours.MessageList.zoomNotice, "bg-black/60 text-white")}>Video not available</div>
      </div>
    );
  }
  return (
    <video
      ref={ref}
      controls
      playsInline
      preload="metadata"
      poster={poster || undefined}
      src={proxyImage(clip, accountId)}
      className={cn(MP.ours.MessageList.zoomImage, "bg-black")}
    />
  );
}
