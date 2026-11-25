"use client";


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
  fallbacks?: (string | null | undefined)[];
  onClose: () => void;
}) {
  // Always the aspect-preserving full frame, never the 300x300 crop: the crop hides waistbands/genitalia at the edge of a portrait.
  const still = useStillLadder([mirrorFullSrc(accountId, mediaId), ...fallbacks]);
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
