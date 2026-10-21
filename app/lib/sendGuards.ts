/**
 * The OnlyFans send rules a composer checks before it sends, in Infloww's
 * words (gap 04 P7 and M27): a message is free or costs at least $3, and
 * the chatter's own sends at once are at least 3 seconds apart. Both are
 * checked inline on what the chatter sends; the follow-up sends a composer
 * makes itself (a multi-GIF pick's extra GIFs) are not rate-guarded.
 */

/** OF's minimum message price (the price dialog: "Minimum $3 USD or free"). */
export const MIN_PRICE = 3;
export const PRICE_NOTE = "Minimum $3 USD or free";

/** `PRICE_NOTE` for a price OF refuses (above free, under `MIN_PRICE`), else null. */
export function priceNote(price: number | null): string | null {
  return price != null && price > 0 && price < MIN_PRICE ? PRICE_NOTE : null;
}

/** Infloww's composer send-rate guard. */
export const SEND_GAP_MS = 3000;
export const SEND_GAP_NOTE = "OnlyFans does not allow sending too many messages at once. Wait 3 seconds";

/** When a composer last sent at once, per model (account id), shared by every
 *  composer in the window: the guard carries over between that model's Fans
 *  (a queue's Cmd+Enter moves to the next Fan's composer at once), and
 *  never holds a send to another model. */
const lastSendAt = new Map<string, number>();

/** Claim a send at once from `accountId` for the rate guard: false (nothing
 *  recorded) within SEND_GAP_MS of that model's last claimed one. No model
 *  (null) has no clock to keep: always true, nothing recorded. */
export function claimSendGap(accountId: string | null, now = Date.now()): boolean {
  if (accountId == null) return true;
  if (now - (lastSendAt.get(accountId) ?? 0) < SEND_GAP_MS) return false;
  lastSendAt.set(accountId, now);
  return true;
}

/** Test seam: forget the last sends. */
export function resetSendGapForTests(): void {
  lastSendAt.clear();
}
