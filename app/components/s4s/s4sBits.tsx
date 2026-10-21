"use client";

/** Share for Share's shared bits: the partner avatar, UTC dates (Infloww's S4S pages are in UTC), the error text, the
 *  media thumbnails and carousel. */

import { useState } from "react";
import { ChevronLeft, ChevronRight, Image as ImageIcon, ImageOff, Play, Video } from "lucide-react";

import { cn } from "@/lib/utils";
import { s4sMediaUrl, type S4SMedia, type S4SProjection } from "@/lib/s4s";

export const UTC_NOTE = "Date/Time shown in UTC time zone";

const MONTHS = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];
export const monthName = (m: number) => MONTHS[m];
const pad = (n: number) => String(n).padStart(2, "0");

/** "MMMM DD, YYYY" in UTC. */
export function utcDate(iso: string | Date): string {
  const d = typeof iso === "string" ? new Date(iso) : iso;
  return `${MONTHS[d.getUTCMonth()]} ${pad(d.getUTCDate())}, ${d.getUTCFullYear()}`;
}

/** "HH:mm" in UTC. */
export function utcTime(iso: string): string {
  const d = new Date(iso);
  return `${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}`;
}

/** The UTC day key "YYYY-MM-DD". */
export const utcDay = (d: Date) => `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())}`;

export const message = (e: unknown) => (e instanceof Error ? e.message : String(e));

/** A Creator's avatar as the projection stored it: `px` square, round or with `rounded` corners; the initial when
 *  there is no URL. */
export function ProjectionAvatar({ item, px, round }: { item: Pick<S4SProjection, "avatar_url" | "display_name">; px: number; round?: boolean }) {
  const shape = round ? "rounded-full" : "rounded-lg";
  const style = { width: px, height: px };
  if (item.avatar_url) {
    // eslint-disable-next-line @next/next/no-img-element
    return <img src={item.avatar_url} alt={item.display_name} style={style} className={cn("shrink-0 object-cover", shape)} />;
  }
  return (
    <span aria-hidden style={style}
      className={cn("flex shrink-0 items-center justify-center bg-bg-elev-2 text-sm font-semibold text-fg", shape)}>
      {item.display_name.slice(0, 1).toUpperCase()}
    </span>
  );
}

/** Thumbnails of S4S media: a still of each item, which the Relay reads live from its Creator's vault (ADR-0015). */
export function S4SMediaStrip({ media }: { media: S4SMedia[] }) {
  if (media.length === 0) return null;
  return (
    <div className="flex flex-wrap gap-1">
      {media.map((m) => (
        // eslint-disable-next-line @next/next/no-img-element -- a Relay-served still, not a Next asset
        <img key={m.id} src={s4sMediaUrl(m.id)} alt={`S4S ${m.media_type}`} className="h-10 w-10 rounded object-cover" />
      ))}
    </div>
  );
}

/** A post's media as Infloww's S4S pop-up shows it: one still at a time (`s4sMediaUrl`), prev/next arrows and a dot
 *  pager when there is more than one, and a photo/video count chip. A post with no media, and a still the Relay cannot
 *  read (the item left its vault), show a placeholder, never an error. */
export function S4SMediaCarousel({ media, className }: { media: S4SMedia[]; className?: string }) {
  const [at, setAt] = useState(0);
  const [broken, setBroken] = useState<ReadonlySet<number>>(() => new Set());
  const m = media[at] as S4SMedia | undefined;
  const videos = media.filter((x) => x.media_type === "video").length;
  const photos = media.length - videos;
  const step = (d: number) => setAt((i) => (i + d + media.length) % media.length);
  const arrow = "absolute top-1/2 grid h-8 w-8 -translate-y-1/2 place-items-center rounded-full bg-black/50 text-white hover:bg-black/70";
  return (
    <div className={cn("relative overflow-hidden rounded-lg bg-bg-elev-1", className)}>
      {!m || broken.has(m.id) ? (
        <div className="flex h-full flex-col items-center justify-center gap-2 text-[12px] text-[#999]">
          <ImageOff className="h-8 w-8" aria-hidden />
          {m ? "Preview unavailable" : "No media on this post"}
        </div>
      ) : (
        <>
          {/* eslint-disable-next-line @next/next/no-img-element -- a Relay-served still, not a Next asset */}
          <img key={m.id} src={s4sMediaUrl(m.id)} alt={`S4S ${m.media_type} ${at + 1} of ${media.length}`}
            onError={() => setBroken((b) => new Set(b).add(m.id))} className="h-full w-full object-cover" />
          {m.media_type === "video" && (
            <span aria-hidden className="absolute left-1/2 top-1/2 grid h-12 w-12 -translate-x-1/2 -translate-y-1/2 place-items-center rounded-full bg-black/50 text-white">
              <Play className="h-5 w-5" />
            </span>
          )}
        </>
      )}
      {media.length > 1 && (
        <>
          <button type="button" aria-label="Previous media" onClick={() => step(-1)} className={cn(arrow, "left-3")}>
            <ChevronLeft className="h-5 w-5" aria-hidden />
          </button>
          <button type="button" aria-label="Next media" onClick={() => step(1)} className={cn(arrow, "right-3")}>
            <ChevronRight className="h-5 w-5" aria-hidden />
          </button>
          <div className="absolute bottom-4 right-4 flex gap-1.5">
            {media.map((x, i) => (
              <button key={x.id} type="button" aria-label={`Media ${i + 1}`} aria-current={i === at}
                onClick={() => setAt(i)} className={cn("h-2 w-2 rounded-full", i === at ? "bg-accent" : "bg-white/50")} />
            ))}
          </div>
        </>
      )}
      {media.length > 0 && (
        <span aria-label={`${videos} videos, ${photos} photos`}
          className="absolute bottom-3 left-3 flex items-center gap-1.5 rounded-md bg-black/60 px-2 py-1 text-[13px] text-white">
          {videos > 0 && <><Video className="h-4 w-4" aria-hidden />{videos}</>}
          {videos > 0 && photos > 0 && <span aria-hidden>·</span>}
          {photos > 0 && <><ImageIcon className="h-4 w-4" aria-hidden />{photos}</>}
        </span>
      )}
    </div>
  );
}
