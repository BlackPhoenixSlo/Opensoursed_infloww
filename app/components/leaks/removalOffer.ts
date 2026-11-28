export type RemovalStatus = "none" | "unknown" | "pending" | "active" | "former";
export type RemovalView = "offer" | "hidden" | "starting" | "track" | "past";

export type Removal = {
  status: RemovalStatus;
  view: RemovalView;
  notices_updated_at: string | null;
  stale: boolean;
  counts: Record<string, number> | null;
  offer_snoozed_until: string | null;
};

export type OfferAngle = "came_back" | "cached" | "live_30d" | "new_week" | "visible" | "clean";

export type RemovalOffer = { brand: string; contact_url: string; angle: OfferAngle; n: number };

export const OFFER_HEADING = "Removal help";
export const CONTACT_CTA = "Contact us to start removal";
export const NOT_NOW = "Not now";
export const REMOVAL_STARTING = "Removal starting";
export const NOTICES_NEVER = "Notices not updated yet";

const LEAD: Record<Exclude<OfferAngle, "clean">, (n: number) => string> = {
  came_back: (n) => (n === 1 ? "1 leak came back" : `${n} leaks came back`) + " in the last 30 days.",
  cached: (n) => (n === 1 ? "1 leak is gone from the site but still shows" : `${n} leaks are gone from the site but still show`) + " in Google.",
  live_30d: (n) => (n === 1 ? "1 leak has been up" : `${n} leaks have been up`) + " for 30 days or more.",
  new_week: (n) => (n === 1 ? "1 new leak" : `${n} new leaks`) + " this week.",
  visible: (n) => (n === 1 ? "1 leak is up" : `${n} leaks are up`) + " right now.",
};

export const leadLine = (o: RemovalOffer): string =>
  o.angle === "clean" ? `No live leaks found. ${o.brand} also handles removals if you need them.` : LEAD[o.angle](o.n);

export const followLine = (brand: string) => `${brand} files removal notices and follows them up.`;

export const hiddenUntil = (day: string) => `Removal offer hidden until ${day}.`;
