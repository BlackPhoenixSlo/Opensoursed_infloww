"use client";

/**
 * ImageLightbox — full-screen view of ONE vault image, for judging exposure.
 *
 * Always shows the aspect-preserving full frame (`mirrorFullSrc`), never the
 * 300x300 square: the crop is precisely where a waistband or genitalia at the
 * edge of a 3:4 portrait disappears, so a correction made against the square is
 * a correction made against less of the picture than the model that set the
 * flag saw. Click anywhere (or Esc) to close.
 *
 * `fallbacks` exists because this is what the drawer's own click-to-zoom opens.
 * The tile behind it walks a ladder when the local store cannot answer for a
 * media, and this rendered the same `mirrorFullSrc` with nothing behind it — so
 * a tile that had recovered on its own gave a broken-image icon the moment you
 * clicked it. Callers that hold the media dict (the vault drawer) pass its
 * OnlyFans urls; callers that hold only an id (the flags and disputes queues)
 * pass none and get the honest message below instead of a broken image.
 */

import { useRef } from "react";
import { X } from "lucide-react";

import { useModalFocus } from "@/components/ui/ifModal";
import { useStillLadder } from "@/hooks/useStillLadder";
import { mirrorFullSrc } from "@/lib/mediaUrl";

export default function ImageLightbox({
  accountId,
  mediaId,
  fallbacks = [],
  onClose,
}: {
  accountId: string;
  mediaId: number;
  /** Further urls for the SAME media, best first, tried when the store's copy
   *  does not load. */
  fallbacks?: (string | null | undefined)[];
  onClose: () => void;
}) {
  const still = useStillLadder([mirrorFullSrc(accountId, mediaId), ...fallbacks]);
  // A modal layer over a queue's IfModal: Escape closes only this, Tab stays in it.
  const boxRef = useRef<HTMLDivElement>(null);
  useModalFocus(boxRef, onClose);

  return (
    <div
      ref={boxRef}
      role="dialog"
      aria-modal="true"
      aria-label="Image"
      tabIndex={-1}
      className="fixed inset-0 z-[60] bg-black/85 grid place-items-center p-4 cursor-zoom-out outline-none"
      onClick={onClose}
    >
      {still.src ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={still.src}
          alt=""
          onError={still.onError}
          className="max-w-full max-h-full object-contain rounded shadow-2xl"
          onClick={(e) => e.stopPropagation()}
        />
      ) : (
        <p
          className="text-sm text-white/70"
          onClick={(e) => e.stopPropagation()}
        >
          No preview available for this media — run Collect to cache its picture.
        </p>
      )}
      <button
        type="button"
        onClick={onClose}
        className="absolute right-4 top-4 grid h-6 w-6 place-items-center rounded text-white/70 hover:text-white"
        aria-label="Close"
      >
        <X className="h-4 w-4" aria-hidden />
      </button>
    </div>
  );
}
