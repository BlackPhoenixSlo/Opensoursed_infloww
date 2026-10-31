"use client";

import type { SavedReply } from "@/lib/relay";
import { proxyImage } from "@/lib/mediaUrl";

/** A saved reply's media as a row of small thumbnails (first 6, then "+N"). */
export function MediaStrip({
  media, accountId,
}: {
  media: Array<{ id: number; type?: string; files?: SavedReply["media"][number]["files"] }>;
  accountId: string | null;
}) {
  return (
    <div className="flex items-center gap-1.5 mt-2 flex-wrap">
      {media.slice(0, 6).map((m) => {
        const rawThumb =
          m.files?.thumb?.url ||
          m.files?.squarePreview?.url ||
          m.files?.preview?.url ||
          null;
        const thumb = proxyImage(rawThumb, accountId);
        return (
          <div key={m.id} className="w-10 h-10 rounded border border-border overflow-hidden bg-bg-elev-1">
            {thumb ? (
              <img src={thumb} alt="" loading="lazy" decoding="async" className="w-full h-full object-cover" />
            ) : (
              <div className="w-full h-full grid place-items-center text-[9px] text-fg-dim">
                {m.type ?? "?"}
              </div>
            )}
          </div>
        );
      })}
      {media.length > 6 && (
        <span className="text-[10px] text-fg-dim">+{media.length - 6}</span>
      )}
    </div>
  );
}
