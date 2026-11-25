import { interpretSubStatus } from "@/lib/utils";

export type RowBadge = "New" | "🔥" | "❄️" | "❌" | "Off";

export const ROW_BADGE_LABEL: Record<RowBadge, string> = {
  New: "Subscribed within 7 days",
  "🔥": "Bought a PPV within 7 days",
  "❄️": "No message for over 72 hours",
  "❌": "Subscription expired",
  Off: "Auto-renew off",
};

export interface RowBadgeFacts {
  subscribedAt?: string | null;
  lastPpvPurchase: string | null;
  lastMessageAt: string | null | undefined;
  subscriptionStatus: string | null;
  expiredAt: string | null;
  autoRenewOff?: boolean;
}

const HOUR_MS = 3_600_000;
const WEEK_WINDOW_MS = 7 * 24 * HOUR_MS;
const COLD_AFTER_MS = 72 * HOUR_MS;

function ageMs(iso: string | null | undefined, now: number): number | null {
  if (!iso) return null;
  const t = Date.parse(iso);
  if (Number.isNaN(t) || t > now) return null;
  return now - t;
}

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
