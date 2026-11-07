/** "1 sale … has … it" / "3 sales … have … them": the sales with no net figure from OnlyFans yet. `noun` is what
 *  leaves them out: the Dashboard's "Net" switch (one, "leaves") or Creator reports' "net earnings" (many, "leave"). */
export function netMissingNote(n: number, noun: "Net" | "net earnings"): string {
  const verb = noun === "Net" ? "leaves" : "leave";
  return n === 1
    ? `1 sale in this period has no net figure from OnlyFans yet, so ${noun} ${verb} it out.`
    : `${n} sales in this period have no net figure from OnlyFans yet, so ${noun} ${verb} them out.`;
}

/** Chargebacks' figure title, Dashboard and Creator reports, when the reversed read failed. */
export const CHARGEBACKS_UNAVAILABLE = "Chargebacks are unavailable";
