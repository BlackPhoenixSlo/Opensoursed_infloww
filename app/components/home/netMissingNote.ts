export function netMissingNote(n: number, noun: "Net" | "net earnings"): string {
  const verb = noun === "Net" ? "leaves" : "leave";
  return n === 1
    ? `1 sale in this period has no net figure from OnlyFans yet, so ${noun} ${verb} it out.`
    : `${n} sales in this period have no net figure from OnlyFans yet, so ${noun} ${verb} them out.`;
}

export const CHARGEBACKS_UNAVAILABLE = "Chargebacks are unavailable";

// The figure shows "-", not a made-up $0.00, when the referrals read failed.
export const REFERRALS_FAILED = "OnlyFans referrals are unavailable for this period";

export const REFERRALS_UNAVAILABLE = "OnlyFans referrals are unavailable for some creators, counted as $0.00";

export const TOTAL_PARTIAL = "Partial: OnlyFans referrals could not be read for some creators and are left out";

export const TOTAL_GROWTH_EXCL = "Growth of earnings excl. referrals: OnlyFans referrals could not be read for one or both periods";
