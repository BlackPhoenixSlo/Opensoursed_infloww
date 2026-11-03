/**
 * FanDrawer's pure sales helpers: the Unsold PPVs pick, the ledger ↔ OF
 * gallery row builder, the Spending behavior figures and the purchase
 * chart's buckets. No React.
 */

import { fmtPrice } from "@/lib/format";
import { stripOFHtml } from "@/lib/ofHtml";
import { type FanChatMediaItem } from "@/hooks/useFanChatMedia";
import { type PpvHistoryItem, type PpvHistoryResp } from "@/hooks/useFanPpvHistory";

/** The Unsold PPVs block shows the latest 2, read from at most 5 pages of 20. */
const UNSOLD_SHOWN = 2;
export const UNSOLD_MAX_PAGES = 5;

/** The Unsold PPVs pick from the loaded pages of creator-sent chat media.
 *  Filter for paid + not-yet-opened items; show the latest 2 in the
 *  Unsold PPVs block. A page is every creator-sent media message, free
 *  ones and bought PPVs included, so a Fan sent a lot since his last
 *  unsold PPV has none on the first page: `wantMore` pages on until 2 are
 *  found, at most UNSOLD_MAX_PAGES pages. No pages yet: nothing, no paging. */
export function unsoldOf(pages: { list: FanChatMediaItem[] }[] | undefined): {
  items: FanChatMediaItem[]; wantMore: boolean;
} {
  const all = pages?.flatMap((p) => p.list) ?? [];
  const items = all
    .filter((m) => (m.price ?? 0) > 0 && m.isOpened === false)
    .sort((a, b) => +new Date(b.createdAt) - +new Date(a.createdAt))
    .slice(0, UNSOLD_SHOWN);
  const pageCount = pages?.length ?? 0;
  return { items, wantMore: pageCount > 0 && items.length < UNSOLD_SHOWN && pageCount < UNSOLD_MAX_PAGES };
}

export interface PpvSaleThumb {
  /** Raw signed OF CDN url — must be wrapped in proxyImage before rendering. */
  rawUrl: string;
  /** Best full-size url for the lightbox (full → preview → thumb). */
  rawFullUrl: string;
  /** Playable signed video URL for videos (used as both the hover-scrub
   *  source and the lightbox <video src>). Empty for photos. */
  rawVideoUrl: string;
  /** Video duration in seconds — lets the relay's storyboard extractor
   *  skip its own ffprobe step. */
  durationSec: number;
  isVideo: boolean;
}

export interface PpvSaleRowData {
  key: string;
  /** OF message id when available (OF gallery row), null for ledger-only fallback. */
  ofMessageId: number | null;
  text: string;
  priceCents: number;
  purchasedAt: string | null;
  thumbs: PpvSaleThumb[];
  // DB enrichment — null if no fuzzy match.
  netCents: number | null;
  feeCents: number | null;
  vatCents: number | null;
  employeeName: string | null;
  employeeColor: string | null;
}

export interface LightboxMedia {
  proxiedUrl: string;
  isVideo: boolean;
}

/** PPV Avg or Highest spend: the relay's average or maximum over the loaded
 *  purchase-history page (`service/fans.py:1006-1011`). A full page may hide
 *  older purchases, so it reads "—" then, and with no items (B11 option (b)).
 *  A placeholder page (the previous limit's or the previous Fan's, kept by
 *  `placeholderData` while a fetch is in flight) also reads "—". */
export function pageFigure(
  q: { data?: PpvHistoryResp; isPlaceholderData: boolean },
  salesLimit: number, key: "avg_cents" | "max_cents",
): string {
  const items = q.data?.items ?? [];
  if (!q.data || q.isPlaceholderData || items.length === 0 || items.length === salesLimit) return "—";
  return fmtPrice(q.data.summary[key]);
}

/** Whole-dollar formatter for ledger summaries. OF returns
 *  these as dollars (`tipsSumm: 87`); our DB returns cents. Prefer the
 *  OF number when it's a real value; fall back to DB cents otherwise.
 *  We treat `0` as "missing" on the OF side because OF reports 0 for
 *  long-tenure / hidden accounts even when activity exists — better to
 *  show our DB total than a misleading $0. */
export function fmtSummDollars(ofDollars: number | null | undefined, dbCents: number | null | undefined): string {
  if (typeof ofDollars === "number" && ofDollars > 0) return `$${Math.round(ofDollars).toLocaleString("en-US")}`;
  if (typeof dbCents === "number" && dbCents > 0) return `$${Math.round(dbCents / 100).toLocaleString("en-US")}`;
  return "—";
}

/** `salesBars` (`messages.js:1472-1490`): the window runs from the first
 *  purchase to now, at least 7 days, split into 12 equal steps. Epoch
 *  milliseconds throughout, so the buckets do not depend on the host zone. */
export function salesBars(items: PpvHistoryItem[]) {
  const now = Date.now(), N = 12;
  const times = items.map((i) => parseUtcMs(i.purchased_at)).filter((t): t is number => !!t);
  const first = times.length ? Math.min(...times) : now - 7 * 864e5;
  const span = Math.max(now - first, 7 * 864e5);
  const step = span / N;
  const buckets = new Array<number>(N).fill(0);
  for (const i of items) {
    const t = parseUtcMs(i.purchased_at);
    if (t == null) continue;
    const idx = Math.min(N - 1, Math.max(0, Math.floor((t - first) / step)));
    buckets[idx] += i.price_cents || 0;
  }
  return { buckets, max: Math.max(...buckets), first, step };
}

/** The deleted Clone's `InflowwRea.parseUtc` (tag `legacy-ui-final`): relay stamps can be tz-naive
 *  UTC, so a stamp without a zone is read as UTC. Null when unparseable. */
export function parseUtcMs(s: string | null): number | null {
  if (!s) return null;
  let str = s;
  if (/^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}/.test(str) && !/(Z|[+-]\d{2}:?\d{2})$/.test(str)) {
    str = str.replace(" ", "T") + "Z";
  }
  const t = new Date(str).getTime();
  return Number.isNaN(t) ? null : t;
}

export function fmtFullDateTime(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  // "May 24, 2026 at 7:04 PM" — matches the OF screenshot phrasing.
  const datePart = d.toLocaleDateString(undefined, {
    month: "short", day: "numeric", year: "numeric",
  });
  const timePart = d.toLocaleTimeString(undefined, {
    hour: "numeric", minute: "2-digit",
  });
  return `${datePart} at ${timePart}`;
}

export function formatAccounting(row: PpvSaleRowData): string | null {
  const parts: string[] = [];
  if (row.netCents != null) parts.push(`net ${fmtPrice(row.netCents)}`);
  if (row.feeCents != null) parts.push(`fee ${fmtPrice(row.feeCents)}`);
  if (row.vatCents != null && row.vatCents !== 0) parts.push(`VAT ${fmtPrice(row.vatCents)}`);
  return parts.length ? parts.join(" · ") : null;
}

export function pickThumbs(media: FanChatMediaItem["media"]): PpvSaleThumb[] {
  if (!media) return [];
  return media.map((m) => {
    const f = m.files ?? {};
    const thumbUrl =
      f.squarePreview?.url ?? f.thumb?.url ?? f.preview?.url ?? f.full?.url ?? "";
    // Lightbox prefers the full asset; falls back to preview then thumb
    // so a missing `full` (common on locked / no-longer-purchasable media)
    // still gives us something to render in the overlay.
    const fullUrl =
      f.full?.url ?? f.preview?.url ?? f.squarePreview?.url ?? f.thumb?.url ?? "";
    const isVideo = m.type === "video";
    // For videos OF puts the playable mp4 under files.full; preview is a
    // shorter teaser clip on some items, full on others. The relay's
    // /img/scrub builder needs a real mp4, so prefer full → preview.
    const videoUrl = isVideo ? (f.full?.url ?? f.preview?.url ?? "") : "";
    return {
      rawUrl: thumbUrl ?? "",
      rawFullUrl: fullUrl ?? "",
      rawVideoUrl: videoUrl ?? "",
      durationSec: typeof m.duration === "number" ? m.duration : 0,
      isVideo,
    };
  });
}

/** True when OF's list price (in cents) plausibly corresponds to a
 *  ledger row's gross amount. The relationship isn't always 1:1:
 *    • creator sets list price X (e.g. $18.00)
 *    • OF charges fan X + VAT (varies by region, ~12% in EU)
 *    • OF returns `price: 18` on the gallery row regardless
 *    • our ledger row carries amount_cents = gross paid by fan
 *      (sometimes $18, sometimes $18.03 due to FX rounding, $20.16
 *      with VAT, etc.)
 *
 *  We accept a match if the OF price equals any of the following
 *  derivations of the ledger amount, ±2¢ rounding tolerance:
 *    • amount_cents               (no-VAT region; common case)
 *    • amount_cents − vat_cents   (when ledger amount is VAT-inclusive)
 *    • amount_cents + vat_cents   (when ledger amount is ex-VAT)
 *    • net_cents + fee_cents      (some Phase-F rows store these split)
 *  Plus a ±10% loose fallback to catch OF's occasional ad-hoc discount
 *  rounding. The strict candidates win first; loose only fires when no
 *  strict match exists in the whole gallery. */
export function priceMatchScore(ofCents: number, it: PpvHistoryItem): "strict" | "loose" | null {
  const lc = it.price_cents;
  const candidates: number[] = [lc];
  if (it.vat_cents) {
    candidates.push(lc - it.vat_cents);
    candidates.push(lc + it.vat_cents);
  }
  if (it.net_cents != null && it.fee_cents != null) {
    candidates.push(it.net_cents + it.fee_cents);
  }
  for (const c of candidates) {
    if (Math.abs(ofCents - c) <= 2) return "strict";
  }
  if (lc > 0 && Math.abs(ofCents - lc) / lc < 0.10) return "loose";
  return null;
}

/** Unified row builder — ledger is the spine (source of truth for what
 *  was paid), OF gallery enriches with thumbnails + text.
 *
 *  Matching pass order:
 *    1. ledger.message_id == OF.id  (definitive, when ledger has the id)
 *    2. price strict-match (any of the candidate derivations ±2¢),
 *       nearest |createdAt − purchased_at| wins
 *    3. price loose-match (±10%), nearest time wins
 *
 *  Each OF item is consumed at most once so two same-priced ledger rows
 *  on the same day can't both claim a single gallery entry. */
export function buildSaleRows(
  media: FanChatMediaItem[],
  ledger: PpvHistoryItem[],
): PpvSaleRowData[] {
  const sortedLedger = [...ledger].sort(
    (a, b) =>
      +new Date(b.purchased_at ?? b.sent_at ?? 0) -
      +new Date(a.purchased_at ?? a.sent_at ?? 0),
  );
  const mediaById = new Map(media.map((m) => [m.id, m] as const));
  const usedMediaIds = new Set<number>();

  function chooseMedia(it: PpvHistoryItem): FanChatMediaItem | null {
    // Pass 1: hard message-id match.
    if (it.message_id != null) {
      const direct = mediaById.get(it.message_id);
      if (direct && !usedMediaIds.has(direct.id)) return direct;
    }
    // Pass 2+3: collect strict and loose price candidates, then pick by
    // time-proximity within the tighter bucket.
    const ts = +new Date(it.purchased_at ?? it.sent_at ?? 0);
    let bestStrict: FanChatMediaItem | null = null;
    let bestStrictDelta = Number.POSITIVE_INFINITY;
    let bestLoose: FanChatMediaItem | null = null;
    let bestLooseDelta = Number.POSITIVE_INFINITY;
    for (const m of media) {
      if (usedMediaIds.has(m.id)) continue;
      const ofCents = Math.round((m.price ?? 0) * 100);
      const score = priceMatchScore(ofCents, it);
      if (!score) continue;
      const mTs = +new Date(m.createdAt);
      const delta = ts && mTs ? Math.abs(mTs - ts) : Number.POSITIVE_INFINITY;
      if (score === "strict") {
        if (delta < bestStrictDelta) { bestStrictDelta = delta; bestStrict = m; }
      } else if (delta < bestLooseDelta) {
        bestLooseDelta = delta; bestLoose = m;
      }
    }
    return bestStrict ?? bestLoose;
  }

  return sortedLedger.map((it) => {
    const best = chooseMedia(it);
    if (best) usedMediaIds.add(best.id);
    return {
      key: `tx-${it.transaction_id}`,
      ofMessageId: best?.id ?? it.message_id,
      text: best ? stripOFHtml(best.text) : "",
      priceCents: it.price_cents,
      purchasedAt: it.purchased_at ?? it.sent_at,
      thumbs: best ? pickThumbs(best.media) : [],
      netCents: it.net_cents,
      feeCents: it.fee_cents,
      vatCents: it.vat_cents,
      employeeName: it.employee_name,
      employeeColor: it.employee_color,
    };
  });
}
