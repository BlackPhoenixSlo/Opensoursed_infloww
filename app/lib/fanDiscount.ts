import { relay } from "@/lib/relay";
import { fmtPrice } from "@/lib/format";

export interface DiscountFan {
  isBlocked?: boolean;
  canTrialSend?: boolean;
  subscribedOn?: boolean | null;
  subscribedOnExpire?: string | boolean | null;
  subscribedOnExpiredNow?: boolean | null;
}

export const wasSubscriber = (f: DiscountFan) => !!(f.subscribedOn || f.subscribedOnExpiredNow || f.subscribedOnExpire);

// OF's subscription floor and smallest discount: the values OF ships (assumed).
export const MIN_SUB_PRICE = 4.99;
export const MIN_DISCOUNT = 5;
export const maxDiscount = (price: number | null | undefined) => (price ? Math.min(Math.floor((100 * (price - MIN_SUB_PRICE)) / price), 60) : 0);
export const discountShown = (f: DiscountFan, price: number | null | undefined) =>
  (!!f.canTrialSend || (!!price && (price * (100 - MIN_DISCOUNT)) / 100 >= MIN_SUB_PRICE)) && !f.isBlocked && wasSubscriber(f) && maxDiscount(price) >= MIN_DISCOUNT;

export const discountPercents = (price: number | null | undefined) => {
  const top = maxDiscount(price);
  return Array.from({ length: Math.max(0, Math.floor((top - MIN_DISCOUNT) / 5) + 1) }, (_, i) => MIN_DISCOUNT + i * 5);
};
export const offListDiscount = (current: number, percents: number[]) => !!current && !percents.includes(current);
export const DISCOUNT_PERIODS = Array.from({ length: 12 }, (_, i) => i + 1);

export const months = (n: number) => `${n} ${n === 1 ? "month" : "months"}`;
export const discountSummary = (price: number, percent: number, period: number) =>
  `${fmtPrice(Math.round(price * (1 - percent / 100) * 100))} per month for ${months(period)}`;

export const putFanDiscount = (accountId: string, fan: string | number, discount: number, period: number) =>
  relay.put(`/api/of/v2/subscriptions/${encodeURIComponent(String(fan))}/discount`, { discount, period }, { accountId });
