import type { FanSpend } from "@/hooks/useFanSpend";
import { FAN_SPEND_SOURCES } from "@/lib/chatSlots";
import type { FanRecord } from "@/lib/relayTypes";

export function storedSpendCents(fan: FanRecord | null | undefined): number {
  if (!fan) return 0;
  return largerSpendCents(fan.lifetime_spend_cents || 0, ...FAN_SPEND_SOURCES.map((f) => f(fan)));
}

// Larger of the figures, never their sum: each can miss what another saw.
export function largerSpendCents(ledgerCents: number, ...others: (number | null | undefined)[]): number {
  return Math.max(ledgerCents, ...others.map((c) => c ?? 0));
}

// Null = unknown (no spend-batch entry), not 0.
export function totalSpendOf(entry: FanSpend | undefined, ledgerCents: number | undefined): number | null {
  return entry ? Math.max(entry.spend_cents, ledgerCents ?? 0) : null;
}
