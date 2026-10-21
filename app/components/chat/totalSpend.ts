import type { FanSpend } from "@/hooks/useFanSpend";

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
