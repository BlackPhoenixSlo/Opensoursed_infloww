"use client";

/**
 * FanDrawer's Sales pieces: the Sales table, the Purchases over time bars,
 * the purchased-media rows (with the video hover-scrub thumb and the media
 * lightbox) and the Unsold PPVs block's body.
 */

import { useEffect, useState } from "react";

import { type FanChatMediaItem } from "@/hooks/useFanChatMedia";
import { type PpvHistoryItem } from "@/hooks/useFanPpvHistory";
import { HOVER_DELAY_MS, scrubCountdownSec, SCRUB_FRAMES, useHoverPreview } from "@/hooks/useHoverPreview";
import { fmtPrice } from "@/lib/format";
import { proxyImage, proxyScrubFrame } from "@/lib/mediaUrl";
import { fmtCents } from "@/lib/messageFormat";
import { MP } from "@/lib/messagesPro";
import { stripOFHtml } from "@/lib/ofHtml";
import { extraTitle } from "@/lib/openinflowwwwExtras";
import { type VaultMedia } from "@/lib/relay";
import { cn, fmtRelTime } from "@/lib/utils";
import { vaultFilesFromChat } from "@/lib/vaultFiles";
import {
  buildSaleRows, fmtFullDateTime, formatAccounting, parseUtcMs, pickThumbs, salesBars,
  type LightboxMedia, type PpvSaleRowData, type PpvSaleThumb,
} from "./fanDrawerSales";
import { type PickedTemplate } from "./TemplatePicker";

/** The Clone's Sales table (`messages.js:1525-1528`, `.stab` at
 *  `messages.html:488-492`): Date, Gross, Net and Sent by at 12px, one row
 *  per ledger item. Nothing when the ledger is empty; the media rows below
 *  carry the empty text. */
export function SalesTable({ items }: { items: PpvHistoryItem[] }) {
  if (items.length === 0) return null;
  const th = cn(MP.insights.salesHead, "border-border text-fg-dim");
  const td = cn(MP.insights.salesCell, "border-border whitespace-nowrap");
  return (
    <table className={cn(MP.insights.salesTable, "w-full border-collapse")}>
      <thead>
        <tr>
          <th className={cn(th, "text-left")}>Date</th>
          <th className={cn(th, "text-right")}>Gross</th>
          <th className={cn(th, "text-right")}>Net</th>
          <th className={cn(th, "text-left")}>Sent by</th>
        </tr>
      </thead>
      <tbody>
        {items.map((i) => {
          const t = parseUtcMs(i.purchased_at);
          return (
            <tr key={i.transaction_id}>
              <td className={td}>
                {t == null ? "—" : new Date(t).toLocaleDateString([], { month: "short", day: "numeric" })}
              </td>
              <td className={cn(td, "text-right")}>{fmtPrice(i.price_cents)}</td>
              <td className={cn(td, "text-right text-fg-dim")}>{i.net_cents == null ? "—" : fmtPrice(i.net_cents)}</td>
              <td className={td}>{i.employee_name ?? "—"}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

/** How many sale rows to render before "show more". */
const INITIAL_SALE_ROWS = 3;

/** The Clone's Purchases over time bars (`messages.js:1472-1504`, `.bars`
 *  and `.axis` at `messages.html:493-496`): 12 gross-cent buckets from the
 *  Fan's first purchase to now. Shown on Insights and atop the Sales tab. */
export function PurchasesOverTime({ items, loading }: { items: PpvHistoryItem[]; loading: boolean }) {
  if (loading && items.length === 0) {
    return <div className={cn(MP.ours.FanDrawer.status, "text-fg-dim")}>Loading purchase history…</div>;
  }
  if (items.length === 0) {
    return <div className={cn(MP.ours.FanDrawer.status, "text-fg-dim")}>No PPV purchases yet.</div>;
  }
  const { buckets, max, first, step } = salesBars(items);
  const day = (ms: number) => new Date(ms).toLocaleDateString();
  return (
    <>
      <div role="img" aria-label="Purchases over time" className={cn(MP.insights.chart, "flex items-end")}>
        {buckets.map((v, i) => (
          <span
            key={i}
            title={`${day(first + i * step)} – ${day(first + (i + 1) * step)}: ${fmtCents(v)}`}
            style={{ height: `${max > 0 ? Math.max(2, Math.round((v * 100) / max)) : 2}%` }}
            className={cn(MP.insights.bar, "flex-1 block", v ? "bg-accent" : "bg-bg-elev-2")}
          />
        ))}
      </div>
      <div className={cn(MP.insights.axis, "flex justify-between text-fg-dim")}>
        <span>{new Date(first).toLocaleDateString([], { month: "short", day: "numeric", year: "2-digit" })}</span>
        <span>peak {fmtCents(max)}</span>
        <span>now</span>
      </div>
    </>
  );
}

/** The purchased-media rows, last in the Sales tab's Sales block (below the
 *  table, under the block's own title). Renders newest-first; first `INITIAL_SALE_ROWS` shown,
 *  remainder revealed via a "Show N more" button at the BOTTOM (so
 *  scrolling down naturally exposes more, the way infinite-scroll
 *  feeds work). */
export function PpvSalesSection({
  items, loading,
  chatMedia, chatMediaLoading, chatMediaFetching, chatMediaUpdatedAt,
  accountId,
  salesLimit, onLoadMore, onRefresh, onOpenMedia, serverFetching,
}: {
  items: PpvHistoryItem[];
  loading: boolean;
  chatMedia: FanChatMediaItem[];
  chatMediaLoading: boolean;
  /** True whenever React Query is fetching ANY page (initial OR
   *  background SWR refetch). Spins the refresh button while active. */
  chatMediaFetching: boolean;
  /** ms epoch the cached chat-media was last refreshed. 0 if never. */
  chatMediaUpdatedAt: number;
  accountId: string;
  /** Current page size requested from both ppv-history + chat-media. */
  salesLimit: number;
  /** Bumps the page size in the parent. Hidden once we've hit the
   *  server cap or the ledger has clearly returned fewer rows than
   *  requested (= no more to load). */
  onLoadMore: () => void;
  /** Invalidates the chat-media cache and refetches both purchased +
   *  unsold filter modes. Wired to the ↻ button above the media rows. */
  onRefresh: () => void;
  /** Opens a media tile in the drawer-level lightbox. Lifted to the
   *  drawer so its Esc handler can yield to the open lightbox. */
  onOpenMedia: (m: LightboxMedia) => void;
  /** True while either upstream is mid-refetch — used to disable the
   *  Load-more button so a fast double-click doesn't queue two bumps. */
  serverFetching: boolean;
}) {
  // OF gallery is the spine (thumbnails + text); ledger items get
  // fuzzy-matched on top for accounting/employee. Falls back to a
  // ledger-only render when OF hasn't responded yet so the section
  // never blanks.
  const detailRows = buildSaleRows(chatMedia, items);

  const [showAll, setShowAll] = useState(false);
  const [expandedKeys, setExpandedKeys] = useState<Set<string>>(() => new Set());

  // Delay the "loading media…" text by 300ms so cached data — which resolves
  // almost instantly — renders its timestamp directly instead of flashing the
  // loading state for a frame or two.
  const [showLoading, setShowLoading] = useState(false);
  useEffect(() => {
    if (!(chatMediaLoading && chatMedia.length === 0)) {
      setShowLoading(false);
      return;
    }
    const t = window.setTimeout(() => setShowLoading(true), 300);
    return () => window.clearTimeout(t);
  }, [chatMediaLoading, chatMedia.length]);

  const toggleExpanded = (key: string) => {
    setExpandedKeys((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key); else next.add(key);
      return next;
    });
  };

  const visibleRows = showAll ? detailRows : detailRows.slice(0, INITIAL_SALE_ROWS);
  const hiddenCount = detailRows.length - visibleRows.length;

  return (
    <div className="space-y-2 mt-3">
      <div className="flex items-center justify-end gap-2">
        {showLoading && (
          <span className={cn(MP.ours.FanDrawer.mediaStamp, "text-fg-dim")}>loading media…</span>
        )}
        {!chatMediaLoading && chatMediaUpdatedAt > 0 && (
          <span className={cn(MP.ours.FanDrawer.mediaStamp, "text-fg-dim")} title={new Date(chatMediaUpdatedAt).toLocaleString()}>
            {fmtRelTime(new Date(chatMediaUpdatedAt).toISOString())}
          </span>
        )}
        <button
          type="button"
          onClick={onRefresh}
          disabled={chatMediaFetching}
          title="Refresh OnlyFans gallery now (otherwise auto-refreshes after 30 min)"
          aria-label="Refresh gallery"
          className={cn(
            MP.ours.FanDrawer.mediaRefresh,
            "grid md:block place-items-center text-fg-dim hover:text-fg disabled:opacity-50",
            chatMediaFetching && "animate-spin",
          )}
        >
          ↻
        </button>
      </div>
      {loading && items.length === 0 ? (
        <div className={cn(MP.ours.FanDrawer.status, "text-fg-dim")}>Loading purchase history…</div>
      ) : items.length === 0 ? (
        <div className={cn(MP.ours.FanDrawer.status, "text-fg-dim")}>No PPV purchases yet.</div>
      ) : (
        <div className="space-y-2">
          {visibleRows.map((row) => (
            <PpvSaleRow
              key={row.key}
              row={row}
              accountId={accountId}
              expanded={expandedKeys.has(row.key)}
              onToggle={() => toggleExpanded(row.key)}
              onOpenMedia={onOpenMedia}
            />
          ))}
          {/* Show-more lives at the BOTTOM — newest-first feed pattern,
           *  scroll down to load older. */}
          {hiddenCount > 0 && !showAll && (
            <button
              type="button"
              onClick={() => setShowAll(true)}
              className={cn(MP.ours.FanDrawer.showMore, "w-full text-fg-dim hover:text-fg border-dashed border-border")}
            >
              Show {hiddenCount} more
            </button>
          )}
          {showAll && detailRows.length > INITIAL_SALE_ROWS && (
            <button
              type="button"
              onClick={() => setShowAll(false)}
              className={cn(MP.ours.FanDrawer.showMore, "w-full text-fg-dim hover:text-fg border-dashed border-border")}
            >
              Show less
            </button>
          )}
          {/* Server-side pagination. Only meaningful once everything
           *  already fetched is visible (i.e. user has expanded the
           *  client-side hidden rows) — otherwise "Load more" would
           *  confuse with "Show more". Hidden when the ledger came back
           *  with fewer rows than requested (no more to fetch) OR we're
           *  at the server's hard cap. */}
          {showAll
            && items.length >= salesLimit
            && salesLimit < 200 && (
            <button
              type="button"
              onClick={onLoadMore}
              disabled={serverFetching}
              className={cn(MP.ours.FanDrawer.loadMore, "w-full text-[var(--inf-accent-text,var(--color-accent))] border-dashed border-accent/50 disabled:opacity-50 disabled:cursor-progress")}
            >
              {serverFetching ? "Loading…" : "Load more from server"}
            </button>
          )}
        </div>
      )}
    </div>
  );
}

/** Latest 2 unsold PPVs the creator has sent this fan, the Unsold PPVs
 *  block's body. Each row has a "Send to chat" button that populates the
 *  parent Composer with the exact same payload (text + media + price) so the
 *  operator can re-pitch the unlock in one click; without `onComposeWith`
 *  (read-only) the button is hidden. Always renders: a status line while
 *  loading, when the read failed, and when there are none. */
export function UnsoldPpvsSection({
  items, loading, failed, onRetry, accountId, onComposeWith,
}: {
  items: FanChatMediaItem[];
  loading: boolean;
  /** The OF read failed and nothing of this Fan's is loaded. */
  failed: boolean;
  onRetry: () => void;
  accountId: string;
  onComposeWith?: (t: PickedTemplate) => void;
}) {
  const status = cn(MP.ours.FanDrawer.status, "text-fg-dim");
  return (
    <div title={extraTitle("Unsold PPVs")} className="space-y-2">
      {items.length > 0 ? items.map((m) => (
        <UnsoldPpvRow
          key={m.id}
          item={m}
          accountId={accountId}
          onComposeWith={onComposeWith}
        />
      )) : loading ? (
        <div className={status}>Loading unsold PPVs…</div>
      ) : failed ? (
        <div className={status}>
          Couldn&apos;t load unsold PPVs.{" "}
          <button type="button" onClick={onRetry} className="underline hover:text-fg">Retry</button>
        </div>
      ) : (
        <div className={status}>No unsold PPVs sent.</div>
      )}
    </div>
  );
}

function UnsoldPpvRow({
  item, accountId, onComposeWith,
}: {
  item: FanChatMediaItem;
  accountId: string;
  onComposeWith?: (t: PickedTemplate) => void;
}) {
  const text = stripOFHtml(item.text);
  const priceCents = Math.round((item.price ?? 0) * 100);
  const thumbs = pickThumbs(item.media);
  const handleSend = () => {
    if (!onComposeWith) return;
    // Synthesize a PickedTemplate so Composer's existing onPickTemplate
    // handler does the full replace (text + attached vault media + price
    // + lock + previewCount). VaultMedia ids ARE the same ids OF returns
    // on chat-media `media[i].id`, so attaching by id Just Works on send.
    // Chat-media files can lack a url; vaultFilesFromChat drops those.
    const media: VaultMedia[] = item.media.map((mm) => ({
      id: mm.id,
      type: (mm.type as VaultMedia["type"]) || "photo",
      duration: mm.duration,
      files: vaultFilesFromChat(mm.files),
    }));
    onComposeWith({
      source: "of",
      text,
      displayText: item.text,
      mediaCount: item.mediaCount ?? media.length,
      price: item.price ?? 0,
      // OF chat-media doesn't expose lockedText separately; we leave it
      // off so the resend defaults to unlocked-text, matching what the
      // operator usually wants for a follow-up pitch.
      lockedText: false,
      isWelcome: false,
      media,
      previews: [],
      taggedUsers: [],
    });
  };
  return (
    <div className="rounded-md bg-[var(--inf-card,var(--color-bg-elev-1))] border border-[var(--inf-card-border,var(--color-border))] overflow-hidden">
      <div className="flex items-center gap-2 px-2 py-1.5">
        <span className={cn(MP.ours.FanDrawer.pricePill, "inline-flex items-center bg-warn text-white")}>
          <span className="opacity-90">$</span>{fmtPrice(priceCents).slice(1)}
        </span>
        <span className={cn(MP.ours.FanDrawer.rowDate, "text-fg-dim flex-1 min-w-0 truncate")}>
          {fmtFullDateTime(item.createdAt)}
        </span>
        {onComposeWith && (
          <button
            type="button"
            onClick={handleSend}
            className={cn(MP.ours.FanDrawer.sendToChat, "bg-accent hover:bg-accent-hover text-white")}
            title="Load this PPV into the composer"
          >
            Send to chat
          </button>
        )}
      </div>
      {thumbs.length > 0 && (
        <div className="flex gap-1.5 overflow-x-auto px-2 pb-2 -mt-0.5">
          {thumbs.map((t, i) => (
            <div
              key={i}
              className="relative shrink-0 w-16 h-16 rounded-md bg-bg-elev-2 border border-border overflow-hidden"
            >
              {t.rawUrl ? (
                <img
                  src={proxyImage(t.rawUrl, accountId)}
                  alt=""
                  loading="lazy"
                  decoding="async"
                  className="w-full h-full object-cover"
                />
              ) : (
                <div className={cn(MP.ours.FanDrawer.thumbEmpty, "w-full h-full grid place-items-center text-fg-dim")}>—</div>
              )}
              {t.isVideo && (
                <span className="absolute inset-0 grid place-items-center bg-black/20 text-white text-base pointer-events-none">
                  ▶
                </span>
              )}
            </div>
          ))}
        </div>
      )}
      {text && (
        <div className={cn(MP.ours.FanDrawer.unsoldText, "text-fg-dim line-clamp-2 whitespace-pre-wrap break-words")}>
          {text}
        </div>
      )}
    </div>
  );
}

function PpvSaleRow({
  row, accountId, expanded, onToggle, onOpenMedia,
}: {
  row: PpvSaleRowData;
  accountId: string;
  expanded: boolean;
  onToggle: () => void;
  onOpenMedia: (m: LightboxMedia) => void;
}) {
  const accounting = formatAccounting(row);
  return (
    <div className="rounded-md bg-[var(--inf-card,var(--color-bg-elev-1))] border border-[var(--inf-card-border,var(--color-border))] overflow-hidden">
      {/* Header row — green price pill + full date + expand chevron.
       *  Clicking anywhere on this strip toggles the body text. */}
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={expanded}
        className="w-full flex items-center gap-2 px-2 py-1.5 text-left hover:bg-bg-elev-2/40"
      >
        <span className={cn(MP.ours.FanDrawer.pricePill, "inline-flex items-center bg-ok text-white")}>
          <span className="opacity-90">$</span>{fmtPrice(row.priceCents).slice(1)}
        </span>
        <span className={cn(MP.ours.FanDrawer.rowDate, "text-fg-dim flex-1 min-w-0 truncate")}>
          {fmtFullDateTime(row.purchasedAt)}
        </span>
        <span className={cn(MP.ours.FanDrawer.rowChevron, "text-fg-dim transition-transform", expanded && "rotate-180")}>
          ▾
        </span>
      </button>

      {/* Media strip — horizontal scroll, vault-style square tiles.
       *  Click a tile to open it in the lightbox. Videos hover-scrub. */}
      {row.thumbs.length > 0 && (
        <div className="flex gap-1.5 overflow-x-auto px-2 pb-2 -mt-0.5 scrollbar-thin">
          {row.thumbs.map((t, i) => {
            const openInLightbox = () => {
              if (!t.rawFullUrl && !t.rawUrl && !t.rawVideoUrl) return;
              onOpenMedia({
                // Videos: prefer the playable mp4 so the lightbox's
                // <video> can stream it. Photos fall through to the
                // best still.
                proxiedUrl: proxyImage(
                  t.isVideo ? (t.rawVideoUrl || t.rawFullUrl || t.rawUrl)
                            : (t.rawFullUrl || t.rawUrl),
                  accountId,
                ),
                isVideo: t.isVideo,
              });
            };
            return t.isVideo && t.rawVideoUrl ? (
              <VideoScrubThumb
                key={i}
                thumb={t}
                accountId={accountId}
                onClick={openInLightbox}
              />
            ) : (
              <button
                key={i}
                type="button"
                onClick={(e) => { e.stopPropagation(); openInLightbox(); }}
                className="relative shrink-0 w-20 h-20 rounded-md bg-bg-elev-2 border border-border overflow-hidden group"
                title="Click to preview"
              >
                {t.rawUrl ? (
                  <img
                    src={proxyImage(t.rawUrl, accountId)}
                    alt=""
                    loading="lazy"
                    decoding="async"
                    className="w-full h-full object-cover transition-transform group-hover:scale-105"
                  />
                ) : (
                  <div className={cn(MP.ours.FanDrawer.thumbEmpty, "w-full h-full grid place-items-center text-fg-dim")}>—</div>
                )}
                {t.isVideo && (
                  <span className="absolute inset-0 grid place-items-center bg-black/20 text-white text-lg pointer-events-none">
                    ▶
                  </span>
                )}
              </button>
            );
          })}
        </div>
      )}

      {/* Expanded body — full text + accounting/employee. The screenshot's
       *  "Read more" is implicit here: header click opens / closes. */}
      {expanded && (
        <div className={MP.ours.FanDrawer.saleBody}>
          {row.text ? (
            <div className="text-fg whitespace-pre-wrap break-words">{row.text}</div>
          ) : row.thumbs.length > 0 ? (
            // OF matched but no caption — just media. Don't say
            // "media only" as a body since the thumbs above already
            // make that obvious.
            null
          ) : (
            // No OF match at all. The accounting line still shows
            // below; the user knows what was paid even without the
            // captioned content cached. Common causes: the OF gallery
            // page that contains this sale hasn't been loaded yet (try
            // Load more), or the message was deleted on OF.
            <div className="text-fg-dim italic">
              No matching OnlyFans gallery item — try Load more, or the
              original message may have been deleted.
            </div>
          )}
          {(accounting || row.employeeName) && (
            <div className={cn(MP.ours.FanDrawer.saleAccounting, "text-fg-dim flex flex-wrap border-border/60")}>
              {accounting && <span>{accounting}</span>}
              {row.employeeName && (
                <span style={row.employeeColor ? { color: row.employeeColor } : undefined}>
                  · {row.employeeName}
                </span>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/** Video thumb with vault-style hover scrub. Hover-intent debounce
 *  (HOVER_DELAY_MS) kills brush-past thrash; once committed we render
 *  all 12 storyboard frames as overlayed <img> with opacity toggled,
 *  cycling every SCRUB_INTERVAL_MS. Dwell, frame count and pace come from
 *  useHoverPreview, shared with VaultPicker so the relay's /img/scrub disk
 *  cache (keyed by mp4 hash + frame index, not by caller) serves every
 *  surface — so a re-hover is free.
 *  On mouseleave (or unmount) we fire-and-forget a /img/scrub/cancel POST
 *  so the relay can abort the build if it's still mid-download. */
export function VideoScrubThumb({
  thumb, accountId, onClick,
}: {
  thumb: PpvSaleThumb;
  accountId: string;
  onClick: () => void;
}) {
  // Dwell, per-hover session id, slideshow cursor, the cold-build countdown
  // (same ETA as VaultPicker) and the cancel POST all live in the hook.
  const hover = useHoverPreview(HOVER_DELAY_MS);
  const { sid, frame } = hover.state;
  const hovered = hover.state.id !== null;
  const frameReady = hover.state.scrub === "ready";
  const countdownSec = scrubCountdownSec(hover.state);
  // Touch devices synthesise mouseenter on tap, so every tap on this thumb
  // would commit a 12-frame relay ffmpeg storyboard build (and the cancel
  // POST rides on mouseleave, which may never fire) while the click opens
  // the lightbox on top of it. Real pointers keep the hover-scrub exactly
  // as it is today.
  const [canHover] = useState(
    () =>
      typeof window !== "undefined" &&
      window.matchMedia("(hover: hover) and (pointer: fine)").matches,
  );

  return (
    <button
      type="button"
      onClick={(e) => { e.stopPropagation(); onClick(); }}
      // One tile per hook here, so the tile id `start` keys on is a constant 0.
      onMouseEnter={canHover ? () => hover.start(0, thumb.durationSec, thumb.rawVideoUrl) : undefined}
      onMouseLeave={canHover ? () => hover.stop() : undefined}
      className="relative shrink-0 w-20 h-20 rounded-md bg-bg-elev-2 border border-border overflow-hidden group"
      title={canHover ? "Hover to scrub, click to play" : "Tap to play"}
    >
      {/* Static thumb — always rendered as the loading state /
       *  fallback when frames fail. Frames fade in on top. */}
      {thumb.rawUrl ? (
        <img
          src={proxyImage(thumb.rawUrl, accountId)}
          alt=""
          loading="lazy"
          decoding="async"
          className="absolute inset-0 w-full h-full object-cover"
        />
      ) : (
        <div className={cn(MP.ours.FanDrawer.scrubEmpty, "absolute grid place-items-center text-fg-dim")}>—</div>
      )}
      {hovered && sid &&
        Array.from({ length: SCRUB_FRAMES }).map((_, idx) => (
          <img
            // Per-frame key bound to the session id so re-hovers force
            // fresh elements — prevents a stale paint from the previous
            // hover bleeding into the new session.
            key={`${sid}-${idx}`}
            src={proxyScrubFrame(
              thumb.rawVideoUrl,
              accountId,
              idx,
              thumb.durationSec,
              sid,
            )}
            alt=""
            aria-hidden={idx !== frame}
            decoding="async"
            // The first frame that paints clears the shimmer (any frame, so a
            // failed frame-0 fetch can't pin it); a frame-0 error drops the
            // shimmer so we fall back to the static thumb.
            {...hover.frameProps(idx)}
            style={{
              opacity: idx === frame && frameReady ? 1 : 0,
            }}
            className="absolute inset-0 w-full h-full object-cover transition-opacity duration-200"
          />
        ))}
      {/* Cold-build shimmer + countdown — covers the thumb while the
       *  relay is extracting the storyboard. Unmounts as soon as a frame
       *  paints (the slideshow takes over) or frame 0 fails. Cached videos
       *  go straight to ready on the first frame's onLoad so the shimmer
       *  is invisible there. */}
      {hovered && hover.state.scrub === "loading" && (
        <>
          <div aria-hidden className="scrub-shimmer pointer-events-none" />
          <div
            aria-hidden
            className="absolute inset-0 grid place-items-center pointer-events-none"
          >
            <span className={cn(MP.ours.FanDrawer.countdown, "text-white/85 drop-shadow-black/70")}>
              {countdownSec > 0 ? `${Math.ceil(countdownSec)}s` : "…"}
            </span>
          </div>
        </>
      )}
      {!hovered && (
        <span className="absolute inset-0 grid place-items-center bg-black/20 text-white text-lg pointer-events-none">
          ▶
        </span>
      )}
    </button>
  );
}

export function MediaLightbox({ media, onClose }: { media: LightboxMedia; onClose: () => void }) {
  // Close on Esc — mirrors the drawer's own Esc handling so the keyboard
  // story is consistent (Esc collapses one layer at a time).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Media"
      className="fixed inset-0 z-50 bg-black/80 flex items-center justify-center p-4"
      onClick={onClose}
    >
      {media.isVideo ? (
        <video
          src={media.proxiedUrl}
          controls
          autoPlay
          playsInline
          className="max-w-full max-h-full rounded-md"
          onClick={(e) => e.stopPropagation()}
        />
      ) : (
        <img
          src={media.proxiedUrl}
          alt=""
          className="max-w-full max-h-full rounded-md"
          onClick={(e) => e.stopPropagation()}
        />
      )}
      <button
        type="button"
        onClick={onClose}
        className={cn(MP.ours.FanDrawer.lightboxClose, "absolute text-white grid place-items-center bg-black/40 hover:bg-black/60")}
        aria-label="Close preview"
        title="Close preview"
      >
        ×
      </button>
    </div>
  );
}
