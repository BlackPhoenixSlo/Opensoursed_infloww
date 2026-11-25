import type { FanVaultEntry } from "@/hooks/useFanVaultHistory";
import { fmtCents, fmtPrice } from "@/lib/format";
import type { VaultMedia } from "@/lib/relay";

export type TileStatus = "unlocked" | "free" | "locked" | "on-wall";

export const STATUS_RING_CLASS: Record<TileStatus, string> = {
  unlocked: "border-ok",
  free:     "border-warn",
  locked:   "border-err",
  "on-wall":"border-info",
};

export const STATUS_DOT_CLASS: Record<TileStatus, string> = {
  unlocked: "bg-ok",
  free:     "bg-warn",
  locked:   "bg-err",
  "on-wall":"bg-info",
};

export function resolveStatus(entry: FanVaultEntry | undefined, onWall: boolean): TileStatus | null {
  // Unlocked dominates: a chatter must not resell paid content.
  if (entry?.was_purchased) return "unlocked";
  if (entry) {
    return entry.last_price_cents > 0 ? "locked" : "free";
  }
  if (onWall) return "on-wall";
  return null;
}

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

export function pillText(status: TileStatus, entry: FanVaultEntry | undefined, wallCents: number): string {
  switch (status) {
    case "unlocked":
    // BOUGHT shows the total the fan paid, never the last ask price.
      return entry && entry.total_paid_cents > 0 ? `BOUGHT ${fmtCents(entry.total_paid_cents)}` : "BOUGHT";
    case "locked":
      return entry && entry.last_price_cents > 0 ? `SENT ${fmtPrice(entry.last_price_cents)}` : "SENT PPV";
    case "free":
      return "SENT FREE";
    case "on-wall":
      return wallCents > 0 ? `WALL ${fmtPrice(wallCents)}` : "WALL";
  }
}
