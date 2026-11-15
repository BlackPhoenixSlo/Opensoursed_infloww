/**
 * fullAiRevenueView.ts — what the Full AI page's Revenue block shows (GET /admin/full-ai/revenue,
 * service/full_ai_revenue.py; spec phase-05 › Phase 07). Pure: `revenueView(api)` picks every figure and the honesty
 * line; `FullAiRevenue.tsx` only renders it.
 *
 * Honesty (ADR-0035): one Arm → the API's "no holdout: not a comparison"; two Arms → both means side by side and
 * "not readable under about 480 Fans per Arm" while either Arm's complete count is under 480; a difference between
 * the Arms only once both are at or over that floor. Never a lift, never before / after. A mean over no complete
 * 14-day window is "—", not $0. A Route with no offers is hidden.
 */

import { fmtPrice } from "@/lib/format";
import { ROUTE_LABEL, type Route } from "@/hooks/useFullAiToday";

export const ARM_FLOOR = 480;
export const NO_HOLDOUT = "no holdout: not a comparison";
export const FLOOR_LINE = "not readable under about 480 Fans per Arm";

export interface RevenueArmApi {
  fans: number;
  in_window: number;
  complete: number;
  cents: number;
  cents_per_fan: number | null;
}

export interface RevenueRouteApi {
  route: string;
  offers: number;
  bought: number;
  cents: number;
}

export interface FullAiRevenueApi {
  live_since: string | null;
  note: string;
  arms: Record<string, RevenueArmApi>;
  routes: RevenueRouteApi[];
}

export interface ArmView {
  arm: string;
  label: string;
  fans: number;
  complete: number;
  inWindow: number;
  perFan: string;
}

export interface RouteView {
  route: string;
  label: string;
  offers: number;
  bought: number;
  rate: string;
  money: string;
}

export type RevenueView =
  | { live: false }
  | { live: true; since: string; arms: ArmView[]; routes: RouteView[]; honesty: string | null; delta: string | null };

const ARM_LABEL: Record<string, string> = { all: "Enrolled Fans", treatment: "Full AI", holdout: "Holdout" };
const ARM_ORDER = ["all", "treatment", "holdout"];

const armRank = (a: string) => (ARM_ORDER.includes(a) ? ARM_ORDER.indexOf(a) : ARM_ORDER.length);

export function revenueView(api: FullAiRevenueApi): RevenueView {
  if (!api.live_since) return { live: false };
  const keys = Object.keys(api.arms).sort((a, b) => armRank(a) - armRank(b) || a.localeCompare(b));
  const arms: ArmView[] = keys.map((arm) => {
    const g = api.arms[arm];
    return {
      arm, label: ARM_LABEL[arm] ?? arm, fans: g.fans, complete: g.complete, inWindow: g.in_window,
      perFan: g.complete > 0 ? fmtPrice(g.cents_per_fan) : "—",
    };
  });
  const routes: RouteView[] = api.routes.filter((r) => r.offers > 0).map((r) => ({
    route: r.route, label: ROUTE_LABEL[r.route as Route] ?? r.route, offers: r.offers, bought: r.bought,
    rate: `${Math.round((100 * r.bought) / r.offers)}%`, money: fmtPrice(r.cents),
  }));
  let honesty: string | null = null;
  let delta: string | null = null;
  if (arms.length < 2) {
    honesty = api.note || NO_HOLDOUT;
  } else if (keys.some((k) => api.arms[k].complete < ARM_FLOOR)) {
    honesty = FLOOR_LINE;
  } else {
    const [a, b] = keys.map((k) => api.arms[k].cents_per_fan ?? 0);
    const d = a - b;
    delta = `${arms[0].label} − ${arms[1].label}: ${d < 0 ? "-" : "+"}${fmtPrice(Math.abs(d))} per Fan (14 days)`;
  }
  return { live: true, since: api.live_since.slice(0, 10), arms, routes, honesty, delta };
}
