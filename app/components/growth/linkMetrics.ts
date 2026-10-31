/**
 * linkMetrics — Infloww's link figures from Earnings and the operator's Promo cost (both in cents), and the Edit
 * dialog's promo cost input, pure so the Free trial links, Tracking links and Profile promotion tabs and their tests
 * share them. Infloww's formulas are its column tooltips (`TIPS` below, index.9f50f370.js `buildLinkListBaseColumns`
 * @14040938 and the free trial `FREE_TRIAL_LINK_CUSTOM_METRIC_OPTIONS`):
 *
 *   Profit = Earnings − Promo cost         CPC = Promo cost / clicks       CPS = Promo cost / subscribers
 *   ROI    = Profit / Promo cost × 100     AEPS = Earnings / subscribers   Spend/Claim = fans who spent / claims
 *
 * "—" when the figure cannot be read: no earnings figure yet, a Promo cost unset or 0 (nothing was spent, so the
 * cost-based figures say nothing), or a divisor of 0.
 */

import { fmtCents, fmtPrice } from "@/lib/format";

export const DASH = "—";

/** The tracking link columns' tooltips (Links list and Dashboard): the bundle's `tips` (its `useSelfCol` columns and
 *  `LINK_DASHBOARD_DATA`); the capture does not record them. */
export const TIPS = {
  cvr: "Subscription conversion rate: Percentage of clicks that become subscribers. Includes those who signed up for free trial subscription through the tracking link",
  promoCost: "Amount spent on promotions or marketing campaigns for tracking link. Please set this for more accurate data calculations",
  earnings: "Total amount spent by fans on subscriptions and content via tracking link",
  spendingCvr: "Spending conversion rate: Percentage of fans who spent on content or gave tips",
  profit: "Profit: Earnings − Promo cost",
  cpc: "Cost per click: Promo cost divided by number of clicks",
  epc: "Earnings per click: Earnings divided by number of clicks",
  cps: "Cost per subscriber: Promo cost divided by number of subscribers, including those on free trial; average acquisition cost of a subscriber",
  aeps: "Average earnings per subscriber: Earnings divided by number of subscribers",
  roi: "Return of investment: Profit divided by Promo cost, multiplied by 100.",
};

/** Infloww's tooltips on the free trial link columns (the tracking link ones are `TIPS` above). */
export const TRIAL_TIPS = {
  spendClaim: "Percentage of fans who claimed a free trial that purchased subscriptions, spent on content, or gave tips",
  promoCost: "Amount spent on promotions or marketing campaigns for free trial link. Please set this for more accurate data calculations",
  earnings: "Total amount spent by fans on subscriptions and content via free trial link",
  profit: "Profit: Earnings − Promo cost",
  aeps: "Average earnings per subscriber: Earnings divided by number of subscribers",
  roi: "Return of investment: Profit divided by Promo cost, multiplied by 100.",
};

/** A total (earnings, profit) as the house `fmtCents` prints it, whole dollars with commas as on the dashboard
 *  ("$1,235", where Infloww prints "$1,234.56"), a loss as "-$12"; a loss under a dollar is "$0", never "-$0".
 *  A per-click / per-subscriber figure and a promo cost keep their cents (`fmtPrice`), as Infloww's do. */
export function money(cents: number): string {
  return fmtCents(cents);
}

/** A count with the bundle's thousands commas (its `numberFormat`, index.9f50f370.js @13927845). */
export const count = (n: number) => n.toLocaleString("en-US");

/** The marker on a net figure that leaves out transactions OnlyFans has no net for yet. */
export const PARTIAL = " *";

const hasCost = (cost: number | null | undefined): cost is number => cost != null && cost > 0;

/** Earnings − Promo cost, in cents; null without an earnings figure or a cost. */
export function profitCents(earnings: number | null | undefined, cost: number | null | undefined): number | null {
  return earnings == null || !hasCost(cost) ? null : earnings - cost;
}

/** Profit as money, "—" when it cannot be read. */
export const profit = (earnings: number | null | undefined, cost: number | null | undefined): string => {
  const p = profitCents(earnings, cost);
  return p == null ? DASH : money(p);
};

/** CPC (per click) or CPS (per subscriber): Promo cost / n. */
export function costPer(cost: number | null | undefined, n: number | null | undefined): string {
  return !hasCost(cost) || !n ? DASH : fmtPrice(cost / n);
}

/** ROI: Profit / Promo cost × 100, "12.50%". */
export function roi(earnings: number | null | undefined, cost: number | null | undefined): string {
  const p = profitCents(earnings, cost);
  return p == null ? DASH : `${((p / cost!) * 100).toFixed(2)}%`;
}

/** A link as the Tracking links Dashboard averages it (cents; earnings net or gross as the toggle says). */
export interface CostedLink {
  promo_cost_cents?: number | null;
  clicks: number;
  subscribers: number;
  earnings_cents?: number | null;
  earnings_partial?: boolean;
}

/**
 * The Dashboard's Avg CPC, Avg CPS and Avg ROI. Ours: Infloww does not say how it averages, so these are pooled over
 * the links with a Promo cost (a link without one spent nothing and says nothing about cost), not means of per-link
 * figures, so a $5 link does not weigh as much as a $500 one:
 *
 *   Avg CPC = Σ cost / Σ clicks      Avg CPS = Σ cost / Σ subscribers
 *   Avg ROI = (Σ earnings − Σ cost) / Σ cost × 100, over the costed links that have an earnings figure
 *
 * "—" with no costed link or a divisor of 0. `roiPartial` when a costed link has no earnings figure, or its net is
 * partial: the ROI is then over what could be read.
 */
export function linkAverages(links: CostedLink[]): { cpc: string; cps: string; roi: string; roiPartial: boolean } {
  let cost = 0, clicks = 0, subs = 0, roiCost = 0, roiEarn = 0, roiPartial = false;
  for (const l of links) {
    if (!hasCost(l.promo_cost_cents)) continue;
    cost += l.promo_cost_cents;
    clicks += l.clicks || 0;
    subs += l.subscribers || 0;
    if (l.earnings_cents == null) { roiPartial = true; continue; }
    roiCost += l.promo_cost_cents;
    roiEarn += l.earnings_cents;
    if (l.earnings_partial) roiPartial = true;
  }
  return {
    cpc: costPer(cost, clicks),
    cps: costPer(cost, subs),
    roi: roiCost ? roi(roiEarn, roiCost) : DASH,
    roiPartial: roiCost > 0 && roiPartial,
  };
}

/** `part / whole` as a percent to 2 decimals ("25.00%"); "—" with no part or a zero / missing whole. */
export function share(part: number | null | undefined, whole: number | null | undefined): string {
  return part == null || !whole ? DASH : `${((part / whole) * 100).toFixed(2)}%`;
}

/** Subscription CVR (#41, #77): subs over clicks, "—" with no clicks. */
export function cvr({ subscribers, clicks }: { subscribers: number; clicks: number }): string {
  return share(subscribers, clicks);
}

/** `cents / n` as money (EPC, AEPS): null when the link has no earnings figure, "—" when `n` is zero. */
export function per(cents: number | null | undefined, n: number | null | undefined): string | null {
  return cents == null ? null : n ? fmtPrice(cents / n) : DASH;
}

/** AEPS: Earnings / subscribers, "—" without an earnings figure too. */
export function aeps(earnings: number | null | undefined, subs: number | null | undefined): string {
  return per(earnings, subs) ?? DASH;
}

// ── The Edit dialog's Promo cost ($), Infloww's `PromoCostField` ──

/** Infloww's input takes 11 characters: "99,999,999.99" at most once formatted. */
export const PROMO_COST_MAX_LENGTH = 11;
export const PROMO_COST_MAX = 99_999_999.99;

/** The typed cost in dollars: null when empty (unset), NaN when it is not an amount in range. */
export function parsePromoCost(text: string): number | null {
  const t = text.replace(/,/g, "").trim();
  if (!t) return null;
  if (!/^\d+(\.\d{0,2})?$/.test(t)) return NaN;
  const n = Number(t);
  return n <= PROMO_COST_MAX ? n : NaN;
}

/** On blur, as Infloww's: en-US with 2 decimals ("1,250.00"); text that is not an amount stays as typed. */
export function formatPromoCost(text: string): string {
  const n = parsePromoCost(text);
  return n == null || Number.isNaN(n)
    ? text
    : n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

/** A stored cost (cents) back into the input. */
export const promoCostText = (cents: number | null | undefined): string =>
  cents == null || cents <= 0 ? "" : formatPromoCost(String(cents / 100));

/** "Updated N min ago" for the cached figures; "Not read yet" before the first read. */
export function updatedAgo(iso: string | null | undefined, now: number = Date.now()): string {
  if (!iso) return "Not read yet";
  const at = Date.parse(iso);
  if (Number.isNaN(at)) return "Not read yet";
  const min = Math.max(0, Math.floor((now - at) / 60_000));
  if (min < 1) return "Updated just now";
  if (min < 60) return `Updated ${min} min ago`;
  const h = Math.floor(min / 60);
  return `Updated ${h} h ago`;
}
