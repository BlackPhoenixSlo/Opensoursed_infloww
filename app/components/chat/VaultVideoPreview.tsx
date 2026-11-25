"use client";

import { useEffect, useRef, useState } from "react";

import { useModalFocus } from "@/components/ui/ifModal";

import { type VaultMedia } from "@/lib/relay";
import { proxyImage } from "@/lib/mediaUrl";


// Never falls back to files.preview.url: it is a poster JPEG, which <video> and /img/scrub cannot play.
export function progressiveVideoSrc(m: VaultMedia): string | null {
  return m.type === "video" ? clipUrl(m) : null;
}

export function gifClipSrc(m: VaultMedia): string | null {
  return m.type === "gif" ? clipUrl(m) : null;
}

function clipUrl(m: VaultMedia): string | null {
  return m.videoSources?.["240"] || m.videoSources?.["720"] || m.files?.full?.url || null;
}

// DRM-only videos are SAMPLE-AES encrypted: these OF poster frames are their only renderable form.
export function videoPosterFrames(m: VaultMedia): string[] {
  return (m.files?.preview?.options ?? [])
    .map((o) => o?.url)
    .filter((u): u is string => !!u);
}

// DRM is per file (set at upload under the content-protection setting), not a live account property: key off files.drm.
export function isDrmVideo(m: VaultMedia): boolean {
  if (m.type !== "video") return false;
  const man = m.files?.drm?.manifest;
  return !!(man?.hls || man?.dash);
}

// Defensive: if OF ships both a manifest and a progressive mp4, prefer playing the mp4.
export function isDrmOnlyVideo(m: VaultMedia): boolean {
  return isDrmVideo(m) && !progressiveVideoSrc(m);
}

export function VaultVideoPreview({
  media, accountId, onClose,
}: { media: VaultMedia; accountId: string | null; onClose: () => void }) {
  const rawSrc = progressiveVideoSrc(media);
  const drmOnly = isDrmOnlyVideo(media);
  const drmFrames = videoPosterFrames(media);
  const drm = drmOnly && drmFrames.length > 0;
  const [loadError, setLoadError] = useState(false);
  useEffect(() => { setLoadError(false); }, [media.id]);
  const boxRef = useRef<HTMLDivElement | null>(null);
  useModalFocus(boxRef, onClose);
  useEffect(() => {
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => { document.body.style.overflow = prev; };
  }, []);
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
  const src = proxyImage(rawSrc, accountId, media.id);
  const poster = proxyImage(
    media.files?.preview?.url || media.files?.thumb?.url || null,
    accountId,
    media.id,
  );
  const showError = !src || loadError;
  return (
    // `fixed`, not `absolute`: reused outside the picker's portal (/vault), where absolute sizes to the wrong ancestor.
    <div ref={boxRef} tabIndex={-1} role="dialog" aria-modal="true" aria-label="Video preview" className="fixed inset-0 z-50 flex items-center justify-center">
      <button
        type="button"
        aria-label="Close preview"
        onClick={onClose}
        className="absolute inset-0 bg-black/80"
      />
      <div className="relative max-w-[95vw] max-h-[95vh] flex flex-col items-center gap-3">
        {drm ? (
          <>
            <div className="relative">
              <img
                src={proxyImage(drmFrames[frameIdx], accountId, media.id)}
                alt={`Frame ${frameIdx + 1} of ${drmFrames.length}`}
                className="max-w-[92vw] max-h-[88vh] rounded-md shadow-2xl bg-black object-contain"
              />
              {drmFrames.length > 1 && (
                <>
                  <button
                    type="button"
                    aria-label="Previous frame"
                    title="Previous frame"
                    onClick={() => setFrameIdx((n) => (n - 1 + drmFrames.length) % drmFrames.length)}
                    className="absolute left-1 top-1/2 -translate-y-1/2 w-8 h-8 rounded-full bg-black/55 hover:bg-black/80 text-white grid place-items-center"
                  >
                    ‹
                  </button>
                  <button
                    type="button"
                    aria-label="Next frame"
                    title="Next frame"
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
