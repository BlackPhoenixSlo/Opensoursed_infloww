// OF's minimum message price ("Minimum $3 USD or free").
export const MIN_PRICE = 3;
export const PRICE_NOTE = "Minimum $3 USD or free";

export function priceNote(price: number | null): string | null {
  return price != null && price > 0 && price < MIN_PRICE ? PRICE_NOTE : null;
}

export const SEND_GAP_MS = 3000;
export const SEND_GAP_NOTE = "OnlyFans does not allow sending too many messages at once. Wait 3 seconds";

const lastSendAt = new Map<string, number>();

export function claimSendGap(accountId: string | null, now = Date.now()): boolean {
  if (accountId == null) return true;
  if (now - (lastSendAt.get(accountId) ?? 0) < SEND_GAP_MS) return false;
  lastSendAt.set(accountId, now);
  return true;
}

export function resetSendGapForTests(): void {
  lastSendAt.clear();
}
