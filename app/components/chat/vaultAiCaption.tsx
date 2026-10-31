"use client";

import { useEffect, useState } from "react";

import { type VaultAiFields, type VaultMedia } from "@/lib/relay";
import { cn } from "@/lib/utils";

// ── AI description overlay (S9) ──────────────────────────────────────────
// Renders the vault-AI mirror `description` / `video_description` (+ a short
// `tags` list) as a blurred, gradient-backed caption across the BOTTOM HALF of
// a thumb. Pure FE over the existing /items `_ai` overlay — no new endpoint.
// Toggle default ON in the /vault manager, OFF in this chat picker (so it
// doesn't fight the send flow).

/** Pull the one-glance caption for a tile: the video description for videos
 *  (falling back to the still description), the image description otherwise,
 *  plus up to four tag chips. Returns null when the item has neither — the
 *  overlay then doesn't render at all. */
export function aiCaptionFor(
  m: VaultMedia & { _ai?: VaultAiFields },
): { text: string; tags: string[] } | null {
  const ai = m._ai;
  if (!ai) return null;
  const primary = m.type === "video" ? ai.video_description : ai.description;
  const text = (primary || ai.description || ai.video_description || "").trim();
  const tags = (Array.isArray(ai.tags) ? ai.tags : [])
    .map((t) => String(t).trim())
    .filter(Boolean)
    .slice(0, 4);
  if (!text && tags.length === 0) return null;
  return { text, tags };
}

/** Blurred, gradient-backed caption across the BOTTOM HALF of a vault thumb.
 *  Absolutely positioned so it NEVER shifts the grid; pointer-events-none so
 *  it never intercepts tile selection. The linear mask fades both the dark
 *  gradient and the frosted backdrop-blur upward, leaving the top half of the
 *  media clear and the text readable at a glance. */
export function VaultAiCaptionOverlay({
  caption,
}: {
  caption: { text: string; tags: string[] };
}) {
  return (
    <div
      aria-hidden
      className="absolute inset-x-0 bottom-0 h-1/2 pointer-events-none select-none"
    >
      {/* ONLY the frosted backdrop is masked, so it still fades upward and
       *  leaves the top half of the media clear. The text layer below is
       *  deliberately OUTSIDE this element: masking the copy too is what washed
       *  the description out to an unreadable ghost — it sits above the tags,
       *  i.e. exactly in the fade zone. */}
      <div
        className={cn(
          "absolute inset-0",
          "bg-gradient-to-t from-black/85 via-black/55 to-transparent",
          "backdrop-blur-[2px]",
          "[mask-image:linear-gradient(to_top,black_55%,transparent)]",
          "[-webkit-mask-image:linear-gradient(to_top,black_55%,transparent)]",
        )}
      />
      {/* Unmasked content — always fully opaque. Description first (clamped to
       *  a short 2 lines so it reads at a glance), tag chips under it. */}
      <div className="absolute inset-x-0 bottom-0 flex flex-col gap-1 p-1.5">
        {caption.text && (
          <p className="text-white text-[10px] leading-snug line-clamp-2 drop-shadow-[0_1px_2px_rgba(0,0,0,0.95)]">
            {caption.text}
          </p>
        )}
        {caption.tags.length > 0 && (
          <div className="flex flex-wrap gap-0.5">
            {caption.tags.map((t) => (
              <span
                key={t}
                className="px-1 py-px rounded-full bg-white/20 text-white/95 text-[8px] leading-tight"
              >
                {t}
              </span>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

export type CaptionSurface = "manager" | "picker";

const CAPTION_EVENT = "chatterly-vault-caption-change";

function captionKey(surface: CaptionSurface): string {
  return `chatterly:vault-ai-caption:${surface}`;
}

/** Default ON in the manager, OFF in the picker; only a stored value overrides. */
function readCaptionOn(surface: CaptionSurface): boolean {
  const dflt = surface === "manager";
  if (typeof window === "undefined") return dflt;
  const raw = window.localStorage.getItem(captionKey(surface));
  if (raw === "1") return true;
  if (raw === "0") return false;
  return dflt;
}

/** Persisted, cross-instance caption toggle (mirrors useBlurMode's shape) so a
 *  flip from either surface's control updates every mounted tile at once. */
export function useCaptionOverlay(
  surface: CaptionSurface,
): [boolean, (next: boolean) => void] {
  const [on, setOn] = useState<boolean>(() => readCaptionOn(surface));
  useEffect(() => {
    const sync = () => setOn(readCaptionOn(surface));
    window.addEventListener(CAPTION_EVENT, sync);
    window.addEventListener("storage", sync);
    return () => {
      window.removeEventListener(CAPTION_EVENT, sync);
      window.removeEventListener("storage", sync);
    };
  }, [surface]);
  function update(next: boolean) {
    setOn(next);
    try {
      window.localStorage.setItem(captionKey(surface), next ? "1" : "0");
      window.dispatchEvent(new Event(CAPTION_EVENT));
    } catch {
      /* quota / private mode — silent */
    }
  }
  return [on, update];
}
