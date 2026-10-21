/**
 * Row badges — the Fan's key facts as the Fan List row states them
 * (docs/spec/phase-02-fan-list-pane.md, Rows › `rowBadges` rules). Pure, so
 * the row and Phase 1's Fan tab signal read the same answer from the same
 * facts and `now`.
 */

import { interpretSubStatus } from "@/lib/utils";

/** A Row badge, in the spec's order. */
export type RowBadge = "New" | "🔥" | "❄️" | "❌" | "Off";

/** What each Row badge means, its tooltip and screen-reader name wherever
 *  it shows (the Fan List row, the Fan tab's signal). */
export const ROW_BADGE_LABEL: Record<RowBadge, string> = {
  New: "Subscribed within 7 days",
  "🔥": "Bought a PPV within 7 days",
  "❄️": "No message for over 72 hours",
  "❌": "Subscription expired",
  Off: "Auto-renew off",
};

export interface RowBadgeFacts {
  /** ISO time the Fan subscribed. No field the Fan List fetches carries it,
   *  so in production it is absent and New stays dark (spec, Rows, New). */
  subscribedAt?: string | null;
  /** ISO time of the Fan's last PPV purchase, from Fan activity's
   *  `lastPpvPurchase` (the Creator's 50 most recent transactions). */
  lastPpvPurchase: string | null;
  /** ISO time of the chat's last message, from either side. */
  lastMessageAt: string | null | undefined;
  /** spend-batch's raw subscription status and expiry. */
  subscriptionStatus: string | null;
  expiredAt: string | null;
  /** The relay's `withUser.autoRenewOff` stamp off the last roster crawl,
   *  which lights Off at first paint, before spend-batch lands. */
  autoRenewOff?: boolean;
}

const HOUR_MS = 3_600_000;
/** New and 🔥: subscribed, or bought a PPV, within 7×24h; exactly 7×24h
 *  still lights. */
const WEEK_WINDOW_MS = 7 * 24 * HOUR_MS;
/** ❄️: the last message is more than 72h old; exactly 72h does not light. */
const COLD_AFTER_MS = 72 * HOUR_MS;

/** How long before `now` `iso` was, or null when it is missing, unparseable
 *  or in the future, which lights nothing. */
function ageMs(iso: string | null | undefined, now: number): number | null {
  if (!iso) return null;
  const t = Date.parse(iso);
  if (Number.isNaN(t) || t > now) return null;
  return now - t;
}

/** The subset of New, 🔥, ❄️, ❌ and Off that `facts` light at `now`, in that
 *  order. ❌ and Off come from the app's one subscription-status reading,
 *  whose buckets are exclusive: an expired Fan reads "Expired", never
 *  "Won't renew", so ❌ and Off never appear together; the relay's
 *  `autoRenewOff` stamp also lights Off, and still yields to ❌. */
export function rowBadges(facts: RowBadgeFacts, now: number): RowBadge[] {
  const out: RowBadge[] = [];
  const subscribed = ageMs(facts.subscribedAt, now);
  if (subscribed !== null && subscribed <= WEEK_WINDOW_MS) out.push("New");
  const ppv = ageMs(facts.lastPpvPurchase, now);
  if (ppv !== null && ppv <= WEEK_WINDOW_MS) out.push("🔥");
  const quiet = ageMs(facts.lastMessageAt, now);
  if (quiet !== null && quiet > COLD_AFTER_MS) out.push("❄️");
  const status = interpretSubStatus(facts.subscriptionStatus, facts.expiredAt, now);
  if (status.expired) out.push("❌");
  else if (status.short === "Won't renew" || facts.autoRenewOff) out.push("Off");
  return out;
}
