export type SubPart = "promotions" | "bundles" | "campaigns" | "trials";

// Its own module so a hook that only writes a bundle (useGrowth) need not import the Subscription mirror and, through it, the whole OF mirror.
export const SUB_ROUTES: Record<SubPart, string> = {
  promotions: "/api/of/v2/promotions",
  bundles: "/api/of/v2/subscriptions/bundles",
  campaigns: "/api/of/v2/campaigns",
  trials: "/api/of/v2/trials",
};
