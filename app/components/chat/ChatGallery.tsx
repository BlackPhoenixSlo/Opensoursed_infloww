"use client";

/**
 * ChatGallery — the "Chat gallery" sheet the Chat header's "Gallery" opens
 * (docs/spec/phase-03-chat-header-message-list.md, M4 and F29; ticket 88).
 *
 * Every media file exchanged with this Fan, in both directions and purchased
 * or not: pages of 30 from the existing chat-media request, through
 * `useFanChatMedia` with `creatorOnly: false`, so it never shares a cache
 * entry with Fan insights' Sales list. One tile per file that has a URL, as
 * the Clone builds them (m.js:2626-2630), each a `MediaTile` that SFW mode
 * blurs. A paid item's files carry its price tag. Tiles have no click action,
 * as in the Clone.
 *
 * Ticket 89: "Load more" under the grid fetches the next page by the last
 * item's id while the relay reports one, as Fan insights' Sales list pages.
 * "↻ Refresh" re-pulls the query from the first page. An empty list reads
 * "No media in this chat". A failed request with nothing loaded shows the
 * relay's error and "↻ Refresh" in place of the grid, so nothing pretends to
 * have loaded. A failure after tiles loaded (a "Load more" or a Refresh)
 * keeps them and shows the error under the grid, as Fan insights' Sales list
 * keeps its rows (`FanDrawer.tsx:1277-1287`).
 */

import { useEffect } from "react";
import { createPortal } from "react-dom";

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

/** The Clone's tile list (m.js:2626-2630): each file of each item, by its
 *  smallest still that has a URL, carrying the item's price. */
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
  // The Infloww palette when opened from Messages Pro; nothing anywhere else.
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
  // Nothing loaded: the error takes the grid's place, with the one Refresh.
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

  // One layer per Escape (the house rule, `FanDrawer.tsx:335-338`): this
  // `document` listener runs before the `window` ones of Find (`ChatSearch`)
  // and the overlay Fan insights, and stops the key there.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      e.stopPropagation();
      onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  if (typeof document === "undefined") return null;
  // Portalled to <body>, as the Vault picker is, so no ancestor of the Chat
  // header traps the fixed sheet.
  return createPortal(
    <div className={cn(O.backdrop, "fixed flex items-stretch md:items-center md:justify-center")} style={palette}>
      {/* The backdrop closes it too, as the Clone's does (m.js:143). */}
      <button
        type="button"
        tabIndex={-1}
        aria-hidden
        onClick={onClose}
        className="absolute inset-0 bg-black/60 cursor-default"
      />
      <div role="dialog" aria-modal="true" aria-label="Chat gallery" className={cn(S.panel, "relative flex flex-col overflow-hidden w-full bg-panel border-border shadow-2xl")}>
        <div className={cn(S.head, "flex items-center border-border")}>
          <h2 className="mr-auto">Chat gallery</h2>
          {/* With nothing loaded, the one "↻ Refresh" sits with the error. */}
          {!failedEmpty && refreshButton}
          <button
            type="button"
            onClick={onClose}
            // The sheet is modal, so focus moves into it on open.
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
                    fallbackUrl={t.url}
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
