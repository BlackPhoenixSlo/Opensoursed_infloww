"use client";

/**
 * MediaTile — image tile that owns its own fetch lifecycle.
 *
 * Two reasons this exists instead of a plain <img loading="lazy">:
 *
 * 1. ABORT ON CHAT SWITCH. loading="lazy" defers START, but once a fetch
 *    is in flight the browser does NOT cancel it when the <img> unmounts
 *    or scrolls offscreen. Clicking from chat A to chat B leaves A's 30
 *    image fetches grinding for another 10s, holding all 6 browser HTTP
 *    slots against chat B's new /messages call. AbortController in the
 *    cleanup function makes unmount = cancel = chat B's slots freed.
 *
 * 2. CAPTURE X-Img-Hash. The relay returns a stable hash per asset in a
 *    response header. <img> doesn't expose response headers. fetch()
 *    does, so we read it and remember mediaId → hash, then on the next
 *    render of the same image we hit /img/by-hash/<h> as a stable cache
 *    key — survives OF signature rotation between /messages refreshes.
 *
 * 3. ONE LOAD PER IMAGE. Bytes are kept by a signature-blind identity (lib/imgBlobs.ts): a re-signed URL (a poll,
 *    a tab return) or a remount paints the loaded bytes with no request, and the chat open's preload lands here.
 *
 * Priority: `eager` tiles fire immediately with fetchpriority="high".
 * The rest wait until an IntersectionObserver sees the placeholder enter
 * a 200px-rootMargin window, then fire with fetchpriority="low".
 */

import { useEffect, useReducer, useRef } from "react";
import { sameUserId } from "@/lib/fanId";
import { cachedImg, imgIdentity, rememberImg } from "@/lib/imgBlobs";
import { MP } from "@/lib/messagesPro";
import { cn } from "@/lib/utils";
import { MEDIA_TILE_INIT, mediaTileLoadKey, mediaTileReducer } from "./mediaTileState";

// Module-level mapping captured from the X-Img-Hash response header.
// Shared across all MediaTile instances + chat renders, so /img/by-hash
// gets re-used on subsequent paints without re-deriving the hash.
// Keyed by STRING id: Fansly media ids are snowflakes above JS's 2^53, and a
// bundle's ids differ only in their last digits, so numeric keys collide and
// five sibling tiles would share one hash (painting the same image 5x).
const mediaIdToHash = new Map<string, string>();

function rewriteToByHash(legacyUrl: string, hash: string): string {
  // Take the /img?u=… URL we'd otherwise fetch and rewrite it to the
  // stable /img/by-hash/<h>?account_id=…&t=… form. Preserves any other
  // query params (account_id, share token) by parsing them off.
  const qIdx = legacyUrl.indexOf("?");
  if (qIdx < 0) return legacyUrl;
  const search = new URLSearchParams(legacyUrl.slice(qIdx + 1));
  search.delete("u");
  return `/img/by-hash/${hash}?${search.toString()}`;
}

interface MediaTileProps {
  mediaId: number | string | null | undefined;
  proxiedUrl: string;         // already wrapped by proxyImage()
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
  // Loading, loaded or failed (mediaTileState.ts).
  const [state, dispatch] = useReducer(mediaTileReducer, MEDIA_TILE_INIT);
  const placeholderRef = useRef<HTMLDivElement | null>(null);

  // The bytes' identity: the same image across OnlyFans' re-signed URLs (else the URL itself).
  const identity = proxiedUrl ? imgIdentity(proxiedUrl) ?? proxiedUrl : "";
  // The newest signature (a lazy tile starts after a re-sign with it); a failed load retries on a new one only.
  const urlRef = useRef(proxiedUrl);
  urlRef.current = proxiedUrl;
  const loadKey = mediaTileLoadKey(state, proxiedUrl);

  useEffect(() => {
    if (!loadKey) return;
    const ctrl = new AbortController();
    let cancelled = false;
    let io: IntersectionObserver | null = null;

    // The object URL of the bytes, or null (failed or aborted). The cache (lib/imgBlobs.ts) owns it.
    const fetchOnce = async (urlToFetch: string, allowFallback: boolean): Promise<string | null> => {
      const resp = await fetch(urlToFetch, {
        signal: ctrl.signal,
        // Supported on Chromium/Safari/FF 132+; older browsers ignore it
        // harmlessly. TypeScript DOM lib accepts it from TS 5.4+.
        priority: eager ? "high" : "low",
      });
      if (!resp.ok) {
        // /img/by-hash returns 404 when the hash map evicted the entry
        // (LRU at the 50k cap) or 410 when the OF signed URL aged out
        // beyond the relay's 1h TTL. Either way, re-fetching the legacy
        // /img?u= URL repopulates the hash and serves fresh bytes.
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
      return fetchOnce(initial, /* allowFallback */ knownHash != null);
    };

    const start = async () => {
      // Another tile's (or the preload's) load of the same bytes first; failed or aborted: our own.
      const shared = cachedImg(identity);
      let url = shared ? await shared : null;
      if (cancelled) return;
      if (!url) url = await rememberImg(identity, load());
      // AbortError (chat switch, scroll-away) is not a failure: don't paint the failed state.
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
        // 200px above + below the viewport so the fetch finishes just
        // before the tile is visible. Tunable; lower = more aggressive
        // cancel-on-scroll, higher = fewer placeholder flashes.
        { rootMargin: "200px" },
      );
      io.observe(placeholderRef.current);
    } else {
      // Mounted with no ref (shouldn't happen in practice) — be safe.
      start();
    }

    return () => {
      cancelled = true;
      ctrl.abort();
      io?.disconnect();
    };
    // Not proxiedUrl (read via urlRef): a re-signed URL is the same bytes (`identity`), so it shouldn't restart a
    // successful load (`loadKey` carries it only for a failed tile's retry).
  }, [identity, mediaId, eager, loadKey]);

  if (state.kind === "failed") {
    // The placeholder's ref too: a retry waits for the lazy observer like a first load.
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
    // Skeleton: a reserved box (never 0-height) the image paints into.
    // h-full fills the parent's reserved box; `MP.ours.MediaTile.skeleton` is
    // the floor when there's no sized parent (no aspect-ratio, see its comment).
    return (
      <div
        ref={placeholderRef}
        className={cn("w-full h-full bg-bg/30", MP.ours.MediaTile.skeleton, className)}
      />
    );
  }
  // The image fills the same reserved box with object-cover (crop, not
  // letterbox), so swapping skeleton → image causes zero vertical shift.
  return (
    <img
      src={state.url}
      alt={alt}
      decoding="async"
      className={cn("w-full h-full object-cover", className)}
    />
  );
}

/**
 * Pick the media ids that should fetch eagerly when a chat opens. The
 * rule: most recent inbound message's first media, plus most recent
 * outbound message's first media. Walks newest → oldest, stops as soon
 * as it has one of each.
 *
 * If a chat has only inbound media, only that one is eager. If it has
 * none, the set is empty and every tile lazy-loads via the
 * IntersectionObserver path.
 */
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
