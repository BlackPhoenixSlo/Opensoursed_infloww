/**
 * mediaUrl.ts — building the relay's image + scrub-frame URLs.
 *
 * Split out of relay.ts: these are URL builders for the browser's <img> tags,
 * not part of the typed fetch client. They share only `resolveShareToken`
 * with it, so keeping them here lets relay.ts be about transport and wire
 * shapes while this file owns "how do we point at a proxied asset".
 */

import { type VaultMedia } from "@/lib/relayTypes";
import { resolveShareToken } from "@/lib/shareToken";

/**
 * Wrap an OF CDN URL so it loads through the relay's `/img` proxy. We have
 * to do this because OF signs CDN URLs with `AWS:SourceIp=<egress IP>/32` —
 * the browser's IP doesn't match the account's proxy egress, so the image
 * 403s. `/img` tunnels the fetch via the right account's HTTP client.
 *
 * `mediaId` (a vault media's id): the url may be signed for the account's
 * OLD proxy IP, or expired; the relay then re-signs that media and retries.
 *
 * Returns the original URL if either `url` or `accountId` is missing.
 */
export function proxyImage(
  url: string | null | undefined,
  accountId: string | null | undefined,
  mediaId?: number | null,
): string {
  if (!url) return "";
  // Browser-local URLs (blob:/data:) aren't fetchable through the relay
  // — they're already in the browser, just pass them through.
  if (url.startsWith("blob:") || url.startsWith("data:")) return url;
  if (!accountId) return url;
  const tok = resolveShareToken();
  const params = new URLSearchParams();
  params.set("u", url);
  params.set("account_id", accountId);
  if (mediaId != null) params.set("media_id", String(mediaId));
  if (tok) params.set("t", tok);
  return `/img?${params.toString()}`;
}

/**
 * Build a URL for the i-th scrub frame (0..11) of a video. The relay
 * lazily extracts a 12-frame storyboard for each video on first hit;
 * subsequent fetches serve cached JPGs straight from disk. Returns ""
 * if we don't have everything we need to build the URL.
 *
 * Passing `duration` (seconds, from VaultMedia.duration which OF already
 * tells us in the vault listing) lets the relay skip its own ffprobe
 * step and start the extraction immediately.
 */
export function proxyScrubFrame(
  url: string | null | undefined,
  accountId: string | null | undefined,
  frameIdx: number,
  duration?: number | null,
  /** Per-hover session id. The cancel POST that fires on hover-end
   *  carries the SAME id so the server can scope the abort to this
   *  exact hover session — a delayed cancel from a previous hover of
   *  the same video can't abort a freshly-started build. */
  sessionId?: string | null,
  /** The vault media's id: a stale-signed url is re-signed by the relay (see proxyImage). */
  mediaId?: number | null,
): string {
  if (!url || !accountId) return "";
  if (url.startsWith("blob:") || url.startsWith("data:")) return "";
  const tok = resolveShareToken();
  const params = new URLSearchParams();
  params.set("u", url);
  params.set("account_id", accountId);
  params.set("i", String(frameIdx));
  if (typeof duration === "number" && duration > 0) {
    params.set("dur", String(duration));
  }
  if (sessionId) params.set("sid", sessionId);
  if (mediaId != null) params.set("media_id", String(mediaId));
  if (tok) params.set("t", tok);
  return `/img/scrub?${params.toString()}`;
}

// ── The relay's vault stills (signature-free, media-id keyed): one home, one encoding ──

/**
 * The image for one vault TILE — the grid and the chat picker — or "" when the
 * media has no picture to show. The caller renders a placeholder on "".
 *
 * Two rules, and neither is a kind check:
 *
 * 1. `_thumb` first. It is the relay's permanent, signature-free copy of the
 *    300px square, stamped onto a mirror row by `vault_ai_api._overlay`, and its
 *    PRESENCE is the answer to "does this media have a still" — the relay stamps
 *    it only for a kind that can have one (`vault_mirror.has_still`). A voice
 *    note therefore arrives with no `_thumb` and falls through to…
 * 2. …a chain that stops at `preview`. `files.full` is deliberately NOT in it.
 *    Measured across a 6,388-item mirror, `full` is the sole variant for all 592
 *    audio items and for NOTHING else — every photo, video and gif carries a real
 *    picture variant. So the `full` step could only ever resolve for the one kind
 *    whose `full` IS the audio, and an <img> pointed at that costs two OF calls
 *    and one of six in-flight still slots before it 404s, on every render.
 *
 * Between them the audio case needs no branch in any component: nothing resolves,
 * so nothing is requested. Note the rule cannot be recovered from the url — OF's
 * vault CDN paths carry no extension at all (`…/0gwnzeh3cf8dgfj70262`), which is
 * why `ofMedia.stillUrl`'s extension test is the right answer for a chat bubble
 * and no answer at all here.
 */
export function vaultTileThumb(
  m: VaultMedia,
  accountId: string | null | undefined,
): string {
  return (
    m._thumb ||
    // No media id here on purpose: a stale page of tiles reloads itself once
    // (one listing call); a per-tile re-sign would be one OF call per tile.
    proxyImage(
      m.files?.thumb?.url || m.files?.squarePreview?.url || m.files?.preview?.url,
      accountId,
    )
  );
}

/** The same url `vaultTileThumb` prefers, built from an id alone — for a surface
 *  that holds no media dict. It cannot consult `has_still`, so the store answers
 *  an impossible one with an instant 404 (`vault_stills.bytes_for`).
 *  300x300 CENTRE-CROP — fine for a grid tile, wrong for judging exposure. */
export function mirrorThumbSrc(accountId: string, mediaId: number | string): string {
  return `/admin/vault-ai/thumb?account_id=${encodeURIComponent(accountId)}&media_id=${encodeURIComponent(String(mediaId))}`;
}

/** The FULL-FRAME image (aspect-preserving preview), permanent + signature-free.
 *  Use this anywhere an operator judges what is actually on show — the square
 *  thumb crops the top and bottom off a 3:4 portrait, hiding an edge-of-frame
 *  waistband or genitalia (the exact crop that misled the vision model). */
export function mirrorFullSrc(accountId: string, mediaId: number | string): string {
  return `/admin/vault-ai/image?account_id=${encodeURIComponent(accountId)}&media_id=${encodeURIComponent(String(mediaId))}`;
}

/** One of a video's poster frames (OF's own pre-extracted stills, media-id keyed
 *  and permanent — the same frames the chat VaultPicker slideshows). Used to
 *  hover-scrub a clip in the review UI: a video cannot be judged from a single
 *  still, so the operator drags across frame 0 → N-1 to see the whole thing. */
export function mirrorPosterSrc(accountId: string, mediaId: number | string, i: number): string {
  return `/admin/vault-ai/poster?account_id=${encodeURIComponent(accountId)}&media_id=${encodeURIComponent(String(mediaId))}&i=${i}`;
}
