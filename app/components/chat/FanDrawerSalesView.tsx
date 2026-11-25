"use client";


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

const INITIAL_SALE_ROWS = 3;

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
  chatMediaFetching: boolean;
  chatMediaUpdatedAt: number;
  accountId: string;
  salesLimit: number;
  onLoadMore: () => void;
  onRefresh: () => void;
  onOpenMedia: (m: LightboxMedia) => void;
  serverFetching: boolean;
}) {
  const detailRows = buildSaleRows(chatMedia, items);

  const [showAll, setShowAll] = useState(false);
  const [expandedKeys, setExpandedKeys] = useState<Set<string>>(() => new Set());

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

export function UnsoldPpvsSection({
  items, loading, failed, onRetry, accountId, onComposeWith,
}: {
  items: FanChatMediaItem[];
  loading: boolean;
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
      // OF chat-media has no lockedText; resend defaults to unlocked text.
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

      {row.thumbs.length > 0 && (
        <div className="flex gap-1.5 overflow-x-auto px-2 pb-2 -mt-0.5 scrollbar-thin">
          {row.thumbs.map((t, i) => {
            const openInLightbox = () => {
              if (!t.rawFullUrl && !t.rawUrl && !t.rawVideoUrl) return;
              onOpenMedia({
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

      {expanded && (
        <div className={MP.ours.FanDrawer.saleBody}>
          {row.text ? (
            <div className="text-fg whitespace-pre-wrap break-words">{row.text}</div>
          ) : row.thumbs.length > 0 ? (
            null
          ) : (
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

export function VideoScrubThumb({
  thumb, accountId, onClick,
}: {
  thumb: PpvSaleThumb;
  accountId: string;
  onClick: () => void;
}) {
  const hover = useHoverPreview(HOVER_DELAY_MS);
  const { sid, frame } = hover.state;
  const hovered = hover.state.id !== null;
  const frameReady = hover.state.scrub === "ready";
  const countdownSec = scrubCountdownSec(hover.state);
  const [canHover] = useState(
    () =>
      typeof window !== "undefined" &&
      // Touch synthesises mouseenter on tap, which would start a 12-frame ffmpeg storyboard build.
      window.matchMedia("(hover: hover) and (pointer: fine)").matches,
  );

  return (
    <button
      type="button"
      onClick={(e) => { e.stopPropagation(); onClick(); }}
      onMouseEnter={canHover ? () => hover.start(0, thumb.durationSec, thumb.rawVideoUrl) : undefined}
      onMouseLeave={canHover ? () => hover.stop() : undefined}
      className="relative shrink-0 w-20 h-20 rounded-md bg-bg-elev-2 border border-border overflow-hidden group"
      title={canHover ? "Hover to scrub, click to play" : "Tap to play"}
    >
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
            {...hover.frameProps(idx)}
            style={{
              opacity: idx === frame && frameReady ? 1 : 0,
            }}
            className="absolute inset-0 w-full h-full object-cover transition-opacity duration-200"
          />
        ))}
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
