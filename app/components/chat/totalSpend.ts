import type { FanSpend } from "@/hooks/useFanSpend";
import { FAN_SPEND_SOURCES } from "@/lib/chatSlots";
import type { FanRecord } from "@/lib/relayTypes";

/**
 * A Fan's stored total spend in cents: our ledger's lifetime figure
 * (`fans.lifetime_spend_cents`: every tip / PPV / subscription the relay has
 * ingested, only since it started watching; a stub row reads 0), or a
 * plugin's figure for him (lib/chatSlots.ts `fanSpendCents`) when larger.
 * Each can miss what another saw, so none is added to another.
 */
export function storedSpendCents(fan: FanRecord | null | undefined): number {
  if (!fan) return 0;
  return largerSpendCents(fan.lifetime_spend_cents || 0, ...FAN_SPEND_SOURCES.map((f) => f(fan)));
}

/** The lifetime-spend rule: the larger of our ledger's figure and every other
 *  figure for the Fan (null/undefined = never seen), never their sum. */
export function largerSpendCents(ledgerCents: number, ...others: (number | null | undefined)[]): number {
  return Math.max(ledgerCents, ...others.map((c) => c ?? 0));
}

/**
 * A Fan's Total spend in cents (docs/spec/phase-02-fan-list-pane.md, Rows):
 * the larger of spend-batch's lifetime figure and the recent ledger sum.
 *
 * `entry` is the Fan's spend-batch entry, absent while spend-batch loads and
 * for a Fan it has none for. `ledgerCents` is the Fan's sum in the ledger
 * page; a Fan absent from it has no recent spend. Null means unknown: no
 * spend-batch entry, whatever the ledger holds, so the slot shows the photo
 * and no pill (spec, Rows). 0 is a known zero.
 */
export function totalSpendOf(entry: FanSpend | undefined, ledgerCents: number | undefined): number | null {
  return entry ? Math.max(entry.spend_cents, ledgerCents ?? 0) : null;
}
