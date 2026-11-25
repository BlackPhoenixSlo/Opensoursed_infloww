import { fmtCents, fmtPrice } from "@/lib/format";

export const DASH = "—";

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

export const TRIAL_TIPS = {
  spendClaim: "Percentage of fans who claimed a free trial that purchased subscriptions, spent on content, or gave tips",
  promoCost: "Amount spent on promotions or marketing campaigns for free trial link. Please set this for more accurate data calculations",
  earnings: "Total amount spent by fans on subscriptions and content via free trial link",
  profit: "Profit: Earnings − Promo cost",
  aeps: "Average earnings per subscriber: Earnings divided by number of subscribers",
  roi: "Return of investment: Profit divided by Promo cost, multiplied by 100.",
};

// Whole dollars; a loss under a dollar is "$0", never "-$0".
export const money = fmtCents;

export const count = (n: number) => n.toLocaleString("en-US");

// Marks a net figure that leaves out transactions OnlyFans has no net for yet.
export const PARTIAL = " *";

const hasCost = (cost: number | null | undefined): cost is number => cost != null && cost > 0;

export function profitCents(earnings: number | null | undefined, cost: number | null | undefined): number | null {
  return earnings == null || !hasCost(cost) ? null : earnings - cost;
}

export const profit = (earnings: number | null | undefined, cost: number | null | undefined): string => {
  const p = profitCents(earnings, cost);
  return p == null ? DASH : money(p);
};

export function costPer(cost: number | null | undefined, n: number | null | undefined): string {
  return !hasCost(cost) || !n ? DASH : fmtPrice(cost / n);
}

export function roi(earnings: number | null | undefined, cost: number | null | undefined): string {
  const p = profitCents(earnings, cost);
  return p == null ? DASH : `${((p / cost!) * 100).toFixed(2)}%`;
}

export interface CostedLink {
  promo_cost_cents?: number | null;
  clicks: number;
  subscribers: number;
  earnings_cents?: number | null;
  earnings_partial?: boolean;
}

// Ours: pooled over links with a Promo cost (sum cost / sum clicks...), not means of per-link figures.
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

export function share(part: number | null | undefined, whole: number | null | undefined): string {
  return part == null || !whole ? DASH : `${((part / whole) * 100).toFixed(2)}%`;
}

export function cvr({ subscribers, clicks }: { subscribers: number; clicks: number }): string {
  return share(subscribers, clicks);
}

export function per(cents: number | null | undefined, n: number | null | undefined): string | null {
  return cents == null ? null : n ? fmtPrice(cents / n) : DASH;
}

export function aeps(earnings: number | null | undefined, subs: number | null | undefined): string {
  return per(earnings, subs) ?? DASH;
}


// Infloww's input takes 11 characters: "99,999,999.99" at most once formatted.
export const PROMO_COST_MAX_LENGTH = 11;
export const PROMO_COST_MAX = 99_999_999.99;

export function parsePromoCost(text: string): number | null {
  const t = text.replace(/,/g, "").trim();
  if (!t) return null;
  if (!/^\d+(\.\d{0,2})?$/.test(t)) return NaN;
  const n = Number(t);
  return n <= PROMO_COST_MAX ? n : NaN;
}

export function formatPromoCost(text: string): string {
  const n = parsePromoCost(text);
  return n == null || Number.isNaN(n)
    ? text
    : n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

export const promoCostText = (cents: number | null | undefined): string =>
  cents == null || cents <= 0 ? "" : formatPromoCost(String(cents / 100));

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
