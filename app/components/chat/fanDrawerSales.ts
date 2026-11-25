import { fmtPrice } from "@/lib/format";
import { stripOFHtml } from "@/lib/ofHtml";
import { type FanChatMediaItem } from "@/hooks/useFanChatMedia";
import { type PpvHistoryItem, type PpvHistoryResp } from "@/hooks/useFanPpvHistory";

const UNSOLD_SHOWN = 2;
export const UNSOLD_MAX_PAGES = 5;

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
  rawUrl: string;
  rawFullUrl: string;
  rawVideoUrl: string;
  durationSec: number;
  isVideo: boolean;
}

export interface PpvSaleRowData {
  key: string;
  ofMessageId: number | null;
  text: string;
  priceCents: number;
  purchasedAt: string | null;
  thumbs: PpvSaleThumb[];
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

export function pageFigure(
  q: { data?: PpvHistoryResp; isPlaceholderData: boolean },
  salesLimit: number, key: "avg_cents" | "max_cents",
): string {
  const items = q.data?.items ?? [];
  if (!q.data || q.isPlaceholderData || items.length === 0 || items.length === salesLimit) return "—";
  return fmtPrice(q.data.summary[key]);
}

// OF reports 0 for long-tenure/hidden accounts even with activity, so 0 counts as missing.
export function fmtSummDollars(ofDollars: number | null | undefined, dbCents: number | null | undefined): string {
  if (typeof ofDollars === "number" && ofDollars > 0) return `$${Math.round(ofDollars).toLocaleString("en-US")}`;
  if (typeof dbCents === "number" && dbCents > 0) return `$${Math.round(dbCents / 100).toLocaleString("en-US")}`;
  return "—";
}

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

// Relay stamps can be tz-naive UTC.
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
    const fullUrl =
      f.full?.url ?? f.preview?.url ?? f.squarePreview?.url ?? f.thumb?.url ?? "";
    const isVideo = m.type === "video";
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

// OF list price vs ledger gross: VAT (~12% EU), FX rounding; strict candidates +-2c, loose +-10%.
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

// Ledger is the spine; each OF item is consumed at most once so same-priced rows cannot share one.
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
    if (it.message_id != null) {
      const direct = mediaById.get(it.message_id);
      if (direct && !usedMediaIds.has(direct.id)) return direct;
    }
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
