"use client";

import { useEffect, useState } from "react";

import { type VaultMedia } from "@/lib/relay";
import { proxyImage } from "@/lib/mediaUrl";

// The DRM / progressive-source helpers live here next to the preview modal;
// the grid tile (VaultPickerTile) uses them too, and VaultPicker re-exports
// them for its existing importers.

/** The progressive (downloadable/playable) mp4 source for a video, or null
 *  when OF only exposes a DRM (FairPlay) stream. NOTE: deliberately does NOT
 *  fall back to `files.preview.url` — that's a static poster JPEG, and
 *  resolving to it is exactly the bug that made `<video>` + /img/scrub fail
 *  on DRM items (the JPEG can't be played or sliced into frames).
 *  Prefer the CHEAPEST source (240p) first: these frames are only ever
 *  scaled down to a small storyboard width for ffmpeg scrubbing, so pulling
 *  the 720p mp4 is wasted bandwidth. Fall back to 720p, then files.full. */
export function progressiveVideoSrc(m: VaultMedia): string | null {
  if (m.type !== "video") return null;
  return m.videoSources?.["240"] || m.videoSources?.["720"] || m.files?.full?.url || null;
}

/** OF's own pre-extracted poster frames for a video (`preview.options[]`).
 *  For DRM-only videos these are the sole renderable representation — the
 *  segments are SAMPLE-AES encrypted so ffmpeg/<video>/hls.js can't decode
 *  them. Returns [] when none are present. */
export function videoPosterFrames(m: VaultMedia): string[] {
  return (m.files?.preview?.options ?? [])
    .map((o) => o?.url)
    .filter((u): u is string => !!u);
}

/** Authoritative DRM signal: OF returns an HLS/DASH manifest under
 *  `files.drm` for files it delivers with content protection (FairPlay/
 *  Widevine). This is per-FILE — baked in when the file was uploaded under
 *  the creator's "content protection" setting — NOT a live account property,
 *  which is why one account has both playable and DRM videos and toggling
 *  the setting never changes existing files. We key off this, never the
 *  account setting. (Absence of a progressive mp4 is a *consequence* of DRM,
 *  not the cause, so we check the manifest directly.) */
export function isDrmVideo(m: VaultMedia): boolean {
  if (m.type !== "video") return false;
  const man = m.files?.drm?.manifest;
  return !!(man?.hls || man?.dash);
}

/** DRM video with no progressive fallback — the kind we genuinely cannot
 *  play or slice (segments are encrypted). Defensive: if OF ever ships BOTH
 *  a manifest and a progressive mp4, prefer playing the mp4. */
export function isDrmOnlyVideo(m: VaultMedia): boolean {
  return isDrmVideo(m) && !progressiveVideoSrc(m);
}

/** Full-screen modal video player. Sits above the picker's slide-over
 *  pane so backdrop click closes only the preview. The native <video>
 *  controls give scrub/volume/fullscreen; we don't reimplement them. */
export function VaultVideoPreview({
  media, accountId, onClose,
}: { media: VaultMedia; accountId: string | null; onClose: () => void }) {
  // Progressive mp4 only — NOT files.preview.url (a poster JPEG). Resolving
  // to the poster is what made DRM previews mount a <video> on a still image
  // and fail. DRM items get the poster-frame lightbox below instead.
  const rawSrc = progressiveVideoSrc(media);
  const drmOnly = isDrmOnlyVideo(media);
  const drmFrames = videoPosterFrames(media);
  // Show the poster-frame lightbox only when we actually have frames; a DRM
  // file with none falls through to the friendly "can't preview" panel.
  const drm = drmOnly && drmFrames.length > 0;
  // Distinguish "no URL at all" (rawSrc null) from "URL was returned but
  // upstream rejected it" (loadError set by the <video> onError). Both
  // surface the same friendly hint about refresh + transcoding.
  const [loadError, setLoadError] = useState(false);
  useEffect(() => { setLoadError(false); }, [media.id]);
  // Lock background scroll while open. The overlay is viewport-level (`fixed`),
  // so without this the page behind it still scrolls under the backdrop.
  useEffect(() => {
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => { document.body.style.overflow = prev; };
  }, []);
  // DRM poster-frame lightbox cursor. Auto-advances so the user sees the
  // whole set; arrow keys / on-screen arrows let them step manually.
  const [frameIdx, setFrameIdx] = useState(0);
  useEffect(() => { setFrameIdx(0); }, [media.id]);
  useEffect(() => {
    if (!drm || drmFrames.length < 2) return;
    const id = window.setInterval(
      () => setFrameIdx((n) => (n + 1) % drmFrames.length),
      900,
    );
    return () => window.clearInterval(id);
  }, [drm, drmFrames.length]);
  // Diagnostic for the "no source" case — logs the full vault item so we
  // can see which fields OF actually populated for priced/PPV videos and
  // extend the fallback list above. No-op when a source resolved fine.
  useEffect(() => {
    if (!rawSrc) {
      console.warn("[vault-preview] no playable source", {
        id: media.id,
        type: media.type,
        isReady: media.isReady,
        canView: media.canView,
        hasVideoSources: !!media.videoSources,
        fileKeys: media.files ? Object.keys(media.files) : [],
        media,
      });
    }
  }, [rawSrc, media]);
  const src = proxyImage(rawSrc, accountId);
  const poster = proxyImage(
    media.files?.preview?.url || media.files?.thumb?.url || null,
    accountId,
  );
  const showError = !src || loadError;
  return (
    // `fixed`, not `absolute`: this is reused OUTSIDE the picker's own portal
    // (e.g. the /vault manager), where an absolute overlay would size itself to
    // whatever positioned ancestor it landed in — which rendered the video tiny
    // and left the page behind it scrollable.
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <button
        type="button"
        aria-label="Close preview"
        onClick={onClose}
        className="absolute inset-0 bg-black/80"
      />
      <div className="relative max-w-[95vw] max-h-[95vh] flex flex-col items-center gap-3">
        {drm ? (
          <>
            {/* DRM (FairPlay) video — segments are encrypted, so we can't
             *  play it here. Show OF's pre-extracted poster frames as a
             *  steppable slideshow; the user can still attach/send it. */}
            <div className="relative">
              <img
                src={proxyImage(drmFrames[frameIdx], accountId)}
                alt={`Frame ${frameIdx + 1} of ${drmFrames.length}`}
                className="max-w-[92vw] max-h-[88vh] rounded-md shadow-2xl bg-black object-contain"
              />
              {drmFrames.length > 1 && (
                <>
                  <button
                    type="button"
                    aria-label="Previous frame"
                    onClick={() => setFrameIdx((n) => (n - 1 + drmFrames.length) % drmFrames.length)}
                    className="absolute left-1 top-1/2 -translate-y-1/2 w-8 h-8 rounded-full bg-black/55 hover:bg-black/80 text-white grid place-items-center"
                  >
                    ‹
                  </button>
                  <button
                    type="button"
                    aria-label="Next frame"
                    onClick={() => setFrameIdx((n) => (n + 1) % drmFrames.length)}
                    className="absolute right-1 top-1/2 -translate-y-1/2 w-8 h-8 rounded-full bg-black/55 hover:bg-black/80 text-white grid place-items-center"
                  >
                    ›
                  </button>
                </>
              )}
              <span className="absolute top-2 left-2 bg-black/65 text-white text-[11px] px-2 py-0.5 rounded-full">
                🔒 DRM · frame {frameIdx + 1}/{drmFrames.length}
              </span>
            </div>
            <div className="text-[11px] text-fg-dim text-center max-w-md opacity-80">
              OnlyFans protects this video with DRM, so it can&apos;t play in the
              picker — these are OF&apos;s own preview frames. You can still attach
              and send it; the fan sees full playback in OnlyFans.
            </div>
          </>
        ) : !showError ? (
          <video
            src={src}
            poster={poster || undefined}
            autoPlay
            controls
            loop
            playsInline
            onError={() => {
              setLoadError(true);
              console.warn("[vault-preview] video element error", {
                id: media.id, rawSrc, src,
              });
            }}
            className="vault-video max-w-[92vw] max-h-[88vh] rounded-md shadow-2xl bg-black"
          />
        ) : (
          <div className="px-6 py-12 bg-panel rounded-md text-sm text-fg-dim border border-border max-w-md text-center space-y-2">
            <div>
              {drmOnly
                ? "🔒 DRM-protected video."
                : rawSrc
                ? "Couldn't load this video."
                : "No playable source for this video."}
            </div>
            <div className="text-[11px] opacity-70">
              {drmOnly
                ? "OnlyFans protects this video with DRM, so it can't play in the picker (and OF didn't include preview frames for it). You can still attach and send it — the fan sees full playback in OnlyFans."
                : rawSrc
                ? "OF returned a URL but the upstream rejected it — usually a signed URL that expired in cache. Close this and click \"refresh\" at the top of the vault to pull fresh URLs."
                : `OF didn't return a streamable URL for vault id ${media.id}. Freshly-uploaded videos sit without a source until OF finishes transcoding (a few minutes). Try refresh once it's done.`}
            </div>
          </div>
        )}
        <button
          type="button"
          onClick={onClose}
          className="text-xs text-white/80 hover:text-white px-3 py-1 rounded-md bg-black/40 border border-white/15"
        >
          Close (Esc)
        </button>
      </div>
    </div>
  );
}
