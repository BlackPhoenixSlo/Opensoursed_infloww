"use client";


import { type ReactNode, useEffect, useRef, useState } from "react";
import { Loader2 } from "lucide-react";

import { gifClipSrc, isDrmOnlyVideo, progressiveVideoSrc } from "@/components/chat/VaultPicker";
import { releaseVideo } from "@/components/chat/VaultGifLoop";
import ImageLightbox from "@/components/vault/ImageLightbox";
import { useStillLadder } from "@/hooks/useStillLadder";
import { mirrorFullSrc, proxyImage } from "@/lib/mediaUrl";
import { type VaultMedia } from "@/lib/relay";

const VIDEO_REVEAL_DELAY_MS = 500;
const VIDEO_LOAD_TIMEOUT_MS = 15_000;
type VideoLoad = "loading" | "ready" | "error";
const toReady = (s: VideoLoad): VideoLoad => (s === "loading" ? "ready" : s);

function VaultInlineVideo({ src, poster, h }: { src: string; poster?: string; h: string }) {
  const [state, setState] = useState<VideoLoad>("loading");
  const revealTimer = useRef<number | undefined>(undefined);

  useEffect(() => {
    const t = window.setTimeout(() => setState(toReady), VIDEO_LOAD_TIMEOUT_MS);
    return () => {
      window.clearTimeout(t);
      window.clearTimeout(revealTimer.current);
    };
  }, []);

  function onPlayable() {
    if (revealTimer.current === undefined) revealTimer.current = window.setTimeout(() => setState(toReady), VIDEO_REVEAL_DELAY_MS);
  }

  if (state === "error") {
    return (
      <div role="alert" className="w-full py-10 text-center text-xs text-err">
        Couldn&apos;t load this video — try ⤢ for the full player.
      </div>
    );
  }
  return (
    <>
      <video
        src={src}
        poster={poster}
        controls
        loop
        playsInline
        preload="auto"
        onLoadedData={onPlayable}
        onCanPlay={onPlayable}
        onError={() => setState("error")}
        className={`vault-video w-full ${h} object-contain bg-black${state === "loading" ? " invisible min-h-[160px]" : ""}`}
      />
      {state === "loading" && (
        <div role="status" aria-label="Loading video" className="absolute inset-0 grid place-items-center bg-black text-fg-dim">
          <Loader2 size={24} className="animate-spin" aria-hidden />
        </div>
      )}
    </>
  );
}

function VaultInlineGif({ src, poster, fallback, h }: {
  src: string; poster: string | null; fallback: ReactNode; h: string;
}) {
  const [failed, setFailed] = useState(false);
  const ref = useRef<HTMLVideoElement | null>(null);
  useEffect(() => {
    const el = ref.current;
    // src goes back on here: StrictMode's dev double-mount runs the release once and React won't re-set an unchanged prop.
    if (el && !el.getAttribute("src")) el.setAttribute("src", src);
    return () => { if (el) releaseVideo(el); };
  }, [src]);
  if (failed) return fallback;
  return (
    <video
      ref={ref}
      data-gif-loop
      src={src}
      poster={poster || undefined}
      autoPlay
      muted
      loop
      playsInline
      onError={() => setFailed(true)}
      className={`w-full ${h} object-contain bg-black`}
    />
  );
}

function VaultAudioPreview({
  media: m,
  accountId,
}: {
  media: VaultMedia;
  accountId: string;
}) {
  const src = proxyImage(m.files?.full?.url, accountId, m.id);
  return (
    <div className="w-full rounded-lg bg-black px-3 py-4 grid gap-2 justify-items-center text-fg-dim">
      <span className="text-2xl leading-none" aria-hidden>🎤</span>
      <audio src={src || undefined} controls preload="none" className="w-full" />
    </div>
  );
}

export default function VaultPreviewMedia({
  media: m,
  accountId,
  onExpand,
  fill = false,
}: {
  media: VaultMedia;
  accountId: string;
  onExpand: () => void;
  fill?: boolean;
}) {
  const h = fill ? "h-full" : "max-h-[30vh]";
  const isVideo = m.type === "video";
  const rawSrc = isVideo ? progressiveVideoSrc(m) : null;
  const drmOnly = isVideo && isDrmOnlyVideo(m);
  const playable = isVideo && !!rawSrc && !drmOnly;
  const gifSrc = gifClipSrc(m);
  const idNum = Number(m.id);
  const [zoom, setZoom] = useState(false);

  // A photo shows the full frame, not `_thumb` (a 300x300 centre-crop that lops a 3:4 portrait).
  const photoFull = !isVideo && Number.isFinite(idNum) ? mirrorFullSrc(accountId, idNum) : null;
  const fallbacks = [
    m._thumb,
    proxyImage(
      m.files?.full?.url || m.files?.preview?.url || m.files?.thumb?.url,
      accountId,
      m.id,
    ),
  ];
  const still = useStillLadder([photoFull, ...fallbacks]);

  if (m.type === "audio") return <VaultAudioPreview media={m} accountId={accountId} />;

  const noPreview = (
    <div className="w-full py-10 text-center text-xs text-fg-dim">
      {isVideo
        ? "No preview frame — press ▶ to play, or run Collect to cache one."
        : "No preview available — the media is in the vault; run Collect to cache its picture."}
    </div>
  );

  const stillView = still.src ? (
    // eslint-disable-next-line @next/next/no-img-element
    <img
      src={still.src}
      alt=""
      aria-hidden={isVideo}
      onError={still.onError}
      onClick={isVideo ? undefined : () => setZoom(true)}
      title={isVideo ? undefined : "Click to view full size"}
      className={`w-full ${h} object-contain${isVideo ? "" : " cursor-zoom-in"}`}
    />
  ) : (
    // Say so: a blank box reads as a missing upload, and a re-upload hits OF's byte dedupe (same id, no change).
    noPreview
  );

  return (
    <div className={`relative w-full overflow-hidden bg-black ${fill ? "h-full flex items-center justify-center" : "rounded-lg"}`}>
      {gifSrc ? (
        <VaultInlineGif key={gifSrc} src={proxyImage(gifSrc, accountId, m.id)} poster={still.src}
          fallback={stillView} h={h} />
      ) : playable ? (
        <VaultInlineVideo
          key={rawSrc}
          src={proxyImage(rawSrc, accountId, m.id)}
          poster={still.src || undefined}
          h={h}
        />
      ) : (
        <>
          {stillView}
          {isVideo && (
            <button
              type="button"
              onClick={onExpand}
              title={drmOnly ? "DRM — show preview frames" : "Preview video"}
              aria-label="Preview video"
              className="absolute inset-0 grid place-items-center group"
            >
              <span className="w-14 h-14 rounded-full bg-black/60 border border-white/70 grid place-items-center text-white text-xl pl-1 transition-colors group-hover:bg-black/85">
                ▶
              </span>
            </button>
          )}
        </>
      )}
      <button
        type="button"
        onClick={isVideo ? onExpand : () => setZoom(true)}
        title="Full screen"
        aria-label="Full screen"
        className={`absolute rounded bg-black/60 hover:bg-black/85 text-white leading-none ${
          fill ? "top-3 right-3 grid h-8 w-8 place-items-center rounded-full border border-white/25 text-base" : "top-1 right-1 px-1.5 py-0.5 text-xs"
        }`}
      >
        ⤢
      </button>
      {zoom && Number.isFinite(idNum) && (
        <ImageLightbox
          accountId={accountId}
          mediaId={idNum}
          fallbacks={fallbacks}
          onClose={() => setZoom(false)}
        />
      )}
    </div>
  );
}
