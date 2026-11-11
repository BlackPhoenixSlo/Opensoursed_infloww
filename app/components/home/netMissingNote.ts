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

/** Referrals' figure title, Dashboard and Creator reports, when OnlyFans' referrals read failed outright or for every
 *  Creator: the figure shows "-", not a made-up $0.00. */
export const REFERRALS_FAILED = "OnlyFans referrals are unavailable for this period";

/** Referrals' figure title on the Dashboard when OnlyFans' referrals read failed for some Creators, not all. */
export const REFERRALS_UNAVAILABLE = "OnlyFans referrals are unavailable for some creators, counted as $0.00";

/** Total earnings' partial marker, Dashboard and Creator reports: some or all of the referrals could not be read. */
export const TOTAL_PARTIAL = "Partial: OnlyFans referrals could not be read for some creators and are left out";

/** Total earnings' growth title, Creator reports, when either window's referrals are not whole: the growth compares
 *  both windows' earnings without referrals (#22). */
export const TOTAL_GROWTH_EXCL = "Growth of earnings excl. referrals: OnlyFans referrals could not be read for one or both periods";
