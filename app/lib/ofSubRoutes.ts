/** OF's Subscription page parts and the /api/of/ route each reads and writes. Its own module so a hook that only
 *  writes a bundle (useGrowth) need not import the Subscription mirror (lib/ofMirrorSubscription) and, through it,
 *  the whole OF mirror. */
export type SubPart = "promotions" | "bundles" | "campaigns" | "trials";

/** Relay route per part (`X-Account-Id` from the scope). */
export const SUB_ROUTES: Record<SubPart, string> = {
  promotions: "/api/of/v2/promotions",
  bundles: "/api/of/v2/subscriptions/bundles",
  campaigns: "/api/of/v2/campaigns",
  trials: "/api/of/v2/trials",
};
