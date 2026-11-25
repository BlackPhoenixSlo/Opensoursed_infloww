"use client";


import { useEffect, useReducer, useRef } from "react";
import { sameUserId } from "@/lib/fanId";
import { cachedImg, imgIdentity, rememberImg } from "@/lib/imgBlobs";
import { MP } from "@/lib/messagesPro";
import { cn } from "@/lib/utils";
import { MEDIA_TILE_INIT, mediaTileLoadKey, mediaTileReducer } from "./mediaTileState";

// Keyed by string: Fansly snowflake ids exceed 2^53, numeric keys collide.
const mediaIdToHash = new Map<string, string>();

function rewriteToByHash(legacyUrl: string, hash: string): string {
  const qIdx = legacyUrl.indexOf("?");
  if (qIdx < 0) return legacyUrl;
  const search = new URLSearchParams(legacyUrl.slice(qIdx + 1));
  search.delete("u");
  return `/img/by-hash/${hash}?${search.toString()}`;
}

interface MediaTileProps {
  mediaId: number | string | null | undefined;
  proxiedUrl: string;
  eager: boolean;
  className?: string;
  alt?: string;
}

export function MediaTile({
  mediaId,
  proxiedUrl,
  eager,
  className,
  alt = "",
}: MediaTileProps) {
  const [state, dispatch] = useReducer(mediaTileReducer, MEDIA_TILE_INIT);
  const placeholderRef = useRef<HTMLDivElement | null>(null);

  const identity = proxiedUrl ? imgIdentity(proxiedUrl) ?? proxiedUrl : "";
  const urlRef = useRef(proxiedUrl);
  urlRef.current = proxiedUrl;
  const loadKey = mediaTileLoadKey(state, proxiedUrl);

  useEffect(() => {
    if (!loadKey) return;
    // loading="lazy" does not cancel in-flight fetches on unmount; abort frees the 6 HTTP slots for the next chat.
    const ctrl = new AbortController();
    let cancelled = false;
    let io: IntersectionObserver | null = null;

    const fetchOnce = async (urlToFetch: string, allowFallback: boolean): Promise<string | null> => {
      const resp = await fetch(urlToFetch, {
        signal: ctrl.signal,
        priority: eager ? "high" : "low",
      });
      if (!resp.ok) {
        // by-hash 404 (hash evicted) / 410 (OF signed URL aged out): the legacy /img?u= URL repopulates it.
        if (allowFallback && (resp.status === 404 || resp.status === 410)) {
          if (mediaId != null) mediaIdToHash.delete(String(mediaId));
          return fetchOnce(urlRef.current, false);
        }
        return null;
      }
      const hash = resp.headers.get("x-img-hash");
      if (hash && mediaId != null) mediaIdToHash.set(String(mediaId), hash);
      return URL.createObjectURL(await resp.blob());
    };

    const load = async (): Promise<string | null> => {
      const knownHash = mediaId != null ? mediaIdToHash.get(String(mediaId)) : undefined;
      const initial = knownHash
        ? rewriteToByHash(urlRef.current, knownHash)
        : urlRef.current;
      return fetchOnce(initial, knownHash != null);
    };

    const start = async () => {
      const shared = cachedImg(identity);
      let url = shared ? await shared : null;
      if (cancelled) return;
      if (!url) url = await rememberImg(identity, load());
      // Aborted (chat switch, scroll-away) is not a failure: don't paint the failed state.
      if (cancelled) return;
      if (url) dispatch({ type: "loaded", url });
      else dispatch({ type: "failed", at: urlRef.current });
    };

    if (eager || cachedImg(identity)) {
      start();
    } else if (placeholderRef.current) {
      io = new IntersectionObserver(
        ([entry], obs) => {
          if (entry.isIntersecting) {
            obs.disconnect();
            io = null;
            start();
          }
        },
        { rootMargin: "200px" },
      );
      io.observe(placeholderRef.current);
    } else {
      start();
    }

    return () => {
      cancelled = true;
      ctrl.abort();
      io?.disconnect();
    };
  // proxiedUrl is read via urlRef: a re-signed URL is the same bytes and must not restart a successful load.
  }, [identity, mediaId, eager, loadKey]);

  if (state.kind === "failed") {
    return (
      <div
        ref={placeholderRef}
        className={cn(
          "w-full h-full bg-bg/30 grid place-items-center opacity-70",
          MP.ours.MediaTile.skeleton, MP.ours.MediaTile.failedLabel,
          className,
        )}
      >
        failed
      </div>
    );
  }
  if (state.kind !== "loaded") {
    return (
      <div
        ref={placeholderRef}
        className={cn("w-full h-full bg-bg/30", MP.ours.MediaTile.skeleton, className)}
      />
    );
  }
  return (
    <img
      src={state.url}
      alt={alt}
      decoding="async"
      className={cn("w-full h-full object-cover", className)}
    />
  );
}

export function pickEagerMediaIds(
  messages: { id: number | string; fromUser?: { id?: number | string };
              media?: { id?: number | string }[] }[],
  ownerUserId: number | string | null,
): Set<string> {
  const out = new Set<string>();
  let haveOut = false;
  let haveIn = false;
  for (let i = messages.length - 1; i >= 0; i--) {
    const m = messages[i];
    const firstMediaId = m.media?.[0]?.id;
    if (firstMediaId == null) continue;
    const isOutgoing = sameUserId(m.fromUser?.id, ownerUserId);
    if (isOutgoing && !haveOut) {
      out.add(String(firstMediaId));
      haveOut = true;
    } else if (!isOutgoing && !haveIn) {
      out.add(String(firstMediaId));
      haveIn = true;
    }
    if (haveOut && haveIn) break;
  }
  return out;
}
