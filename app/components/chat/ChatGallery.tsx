"use client";


import { useRef } from "react";
import { createPortal } from "react-dom";

import { useModalFocus } from "@/components/ui/ifModal";
import { cn } from "@/lib/utils";
import { fmtPrice } from "@/lib/format";
import { proxyImage } from "@/lib/mediaUrl";
import { describeLoadError } from "@/lib/relay";
import { MP } from "@/lib/messagesPro";
import type { FanId } from "@/lib/fanId";
import { blurImageClass, useBlurMode } from "@/hooks/useBlurMode";
import { useFanChatMedia, type FanChatMediaItem } from "@/hooks/useFanChatMedia";

import { useInflowwPalette } from "./InflowwPalette";
import { MediaTile } from "./MediaTile";

const S = MP.sheet;
const O = MP.ours.ChatGallery;

interface GalleryTile {
  key: string;
  mediaId: number;
  url: string;
  price: number;
}

function toTiles(items: FanChatMediaItem[]): GalleryTile[] {
  return items.flatMap((item) =>
    item.media.flatMap((m) => {
      const f = m.files;
      const url = (f?.thumb ?? f?.squarePreview ?? f?.preview ?? f?.full)?.url;
      return url ? [{ key: `${item.id}-${m.id}`, mediaId: m.id, url, price: item.price }] : [];
    }),
  );
}

export function ChatGallery({ accountId, fanId, onClose }: {
  accountId: string;
  fanId: FanId;
  onClose: () => void;
}) {
  const palette = useInflowwPalette();
  const q = useFanChatMedia(accountId, fanId, { purchased: false, creatorOnly: false, limit: 30 });
  const tiles = toTiles(q.data?.pages.flatMap((p) => p.list) ?? []);
  const refresh = () => { void q.refetch(); };
  const refreshButton = (
    <button
      type="button"
      onClick={refresh}
      disabled={q.isFetching}
      className={cn(O.refresh, "bg-bg-elev-2 text-fg hover:bg-bg-elev-1 disabled:opacity-50")}
    >
      ↻ Refresh
    </button>
  );
  const failedEmpty = q.isError && !q.data;
  const errorNotice = (withRefresh: boolean) => (
    <div role="alert" className={cn(O.notice, "flex flex-col items-start border-dashed border-border text-fg-dim")}>
      <p><b className="font-semibold text-fg">Gallery unavailable</b><br />
        {describeLoadError(q.error, "This chat no longer exists on OnlyFans.")}</p>
      {withRefresh && refreshButton}
    </div>
  );
  const [blurMode] = useBlurMode();
  const blurCls = blurImageClass(blurMode);

  const boxRef = useRef<HTMLDivElement>(null);
  useModalFocus(boxRef, onClose);

  if (typeof document === "undefined") return null;
  // Portalled to body so no Chat header ancestor traps the fixed sheet.
  return createPortal(
    <div className={cn(O.backdrop, "fixed flex items-stretch md:items-center md:justify-center")} style={palette}>
      <button
        type="button"
        tabIndex={-1}
        aria-hidden
        onClick={onClose}
        className="absolute inset-0 bg-black/60 cursor-default"
      />
      <div ref={boxRef} role="dialog" aria-modal="true" aria-label="Chat gallery" tabIndex={-1} className={cn(S.panel, "relative flex flex-col overflow-hidden w-full bg-panel border-border shadow-2xl outline-none")}>
        <div className={cn(S.head, "flex items-center border-border")}>
          <h2 className="mr-auto">Chat gallery</h2>
          {!failedEmpty && refreshButton}
          <button
            type="button"
            onClick={onClose}
            autoFocus
            className={cn(S.close, "text-fg-dim hover:text-fg hover:bg-bg-elev-1")}
            aria-label="Close"
            title="Close"
          >
            ✕
          </button>
        </div>
        <div className={cn(S.body, "flex-1 overflow-auto")}>
          {q.isLoading ? (
            <p className="text-fg-dim">Loading media…</p>
          ) : failedEmpty ? (
            errorNotice(true)
          ) : tiles.length === 0 && !q.hasNextPage ? (
            <p className={cn(O.notice, "flex flex-col items-start border-dashed border-border text-fg-dim")}>
              <b className="font-semibold text-fg">No media in this chat</b>
            </p>
          ) : (<>
            <ul className={cn(S.grid, "grid")}>
              {tiles.map((t) => (
                <li key={t.key} className={cn(S.tile, "relative aspect-square overflow-hidden border-border bg-bg-elev-2")}>
                  <MediaTile
                    mediaId={t.mediaId}
                    proxiedUrl={proxyImage(t.url, accountId)}
                    eager={false}
                    className={cn("rounded-none", blurCls)}
                  />
                  {t.price > 0 && (
                    <span className={cn(S.tileTag, "absolute bg-black/70 text-white")}>
                      {fmtPrice(Math.round(t.price * 100))}
                    </span>
                  )}
                </li>
              ))}
            </ul>
            {q.isError && <div className={O.moreError}>{errorNotice(false)}</div>}
            {q.hasNextPage && (
              <button
                type="button"
                onClick={() => { void q.fetchNextPage(); }}
                disabled={q.isFetching}
                className={cn(O.more, "w-full border-dashed border-accent/50 text-[var(--inf-accent-text,var(--color-accent))] disabled:opacity-50 disabled:cursor-progress")}
              >
                {q.isFetchingNextPage ? "Loading…" : "Load more"}
              </button>
            )}
          </>)}
        </div>
      </div>
    </div>,
    document.body,
  );
}
