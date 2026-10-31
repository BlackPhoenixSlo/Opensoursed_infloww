/**
 * A vault tile's per-fan state (VaultPicker): the ring / corner-pill colour,
 * the tooltip and the corner price.
 */

import type { FanVaultEntry } from "@/hooks/useFanVaultHistory";
import { fmtCents, fmtPrice } from "@/lib/format";
import type { VaultMedia } from "@/lib/relay";

/** Mutually-exclusive tile state. Order matches the desktop-app:
 *    unlocked (fan paid) > free (we sent free) > locked (sent paid, not
 *    bought) > on-wall (public feed only). Sent-anything beats wall-only
 *    because the per-fan signal is always more actionable than the
 *    public-post signal. Unlocked stays the dominant signal — chatter
 *    must know not to resell paid content. */
export type TileStatus = "unlocked" | "free" | "locked" | "on-wall";

export const STATUS_RING_CLASS: Record<TileStatus, string> = {
  unlocked: "border-ok",      // green — fan paid
  free:     "border-warn",    // yellow — we sent free
  locked:   "border-err",     // red — sent paid, not bought yet
  "on-wall":"border-info",    // blue — on the public feed
};

export const STATUS_DOT_CLASS: Record<TileStatus, string> = {
  unlocked: "bg-ok",
  free:     "bg-warn",
  locked:   "bg-err",
  "on-wall":"bg-info",
};

export function resolveStatus(entry: FanVaultEntry | undefined, onWall: boolean): TileStatus | null {
  if (entry?.was_purchased) return "unlocked";
  if (entry) {
    return entry.last_price_cents > 0 ? "locked" : "free";
  }
  if (onWall) return "on-wall";
  return null;
}

/** Tooltip text for each tile — combines media metadata with all known
 *  state so hover gives the full picture (including secondary states the
 *  one-color border can't carry). */
export function describeTile(m: VaultMedia, entry: FanVaultEntry, onWall: boolean): string {
  const base = `${m.type} · ${m.id}`;
  const wallNote = onWall ? " · also on wall" : "";
  if (entry.was_purchased) {
    const paid = entry.total_paid_cents > 0
      ? ` (${fmtCents(entry.total_paid_cents)})`
      : "";
    return `${base} · UNLOCKED (fan paid)${paid}${wallNote}`;
  }
  const kind = entry.last_price_cents > 0
    ? `locked · sent at ${fmtPrice(entry.last_price_cents)}`
    : "sent free";
  return `${base} · ${kind} (${entry.send_count}×)${wallNote}`;
}

/** Price string for the corner badge: the last send price (locked or
 *  unlocked); the cumulative total paid lives in `describeTile`, the
 *  tooltip. Free + wall-only return null. */
function tilePriceLabel(entry: FanVaultEntry | undefined): string | null {
  if (!entry || entry.last_price_cents <= 0) return null;
  return `${fmtPrice(entry.last_price_cents)}`;
}

/** The corner pill's text: the price for locked/unlocked ($X, else PPV /
 *  PAID), "FREE" for sent-free, and the wall marker. Paid wall posts carry
 *  the price OF was charging on the wall ("WALL $6.99"); free wall posts
 *  stay a plain "WALL". */
export function pillText(status: TileStatus, entry: FanVaultEntry | undefined, wallCents: number): string {
  const priceLabel = tilePriceLabel(entry);
  switch (status) {
    case "unlocked":
      return priceLabel ?? "PAID";
    case "locked":
      return priceLabel ?? "PPV";
    case "free":
      return "FREE";
    case "on-wall":
      return wallCents > 0 ? `WALL ${fmtPrice(wallCents)}` : "WALL";
  }
}
