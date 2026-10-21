/**
 * A fan's personal subscription discount, as OF's own "Give user a discount" dialog (PERSONAL_OFFER) has it: percent
 * 5..max in steps of 5, 1..12 months, Clear sends {discount: 0, period: 1}. PUT /subscriptions/<fan>/discount
 * {discount, period} through the Relay. Shared by the OF mirror's chat menu (ofMirrorChatTools) and Messages Pro's
 * Avatar menu "Special offers" (AvatarMenu), so both offer the same percents and say the same price.
 */

import { relay } from "@/lib/relay";

/** The OF user fields these read (`/users/{id}` and `/users/list` both carry them). */
export interface DiscountFan {
  isBlocked?: boolean;
  canTrialSend?: boolean;
  subscribedOn?: boolean | null;
  subscribedOnExpire?: string | boolean | null;
  subscribedOnExpiredNow?: boolean | null;
}

/** OF's UserNote and the menu's discount and comments: the fan is, or was, the Creator's subscriber. */
export const wasSubscriber = (f: DiscountFan) => !!(f.subscribedOn || f.subscribedOnExpiredNow || f.subscribedOnExpire);

/** OF's subscription floor and smallest discount (its subscribers store; the values OF ships: assumed). */
export const MIN_SUB_PRICE = 4.99;
export const MIN_DISCOUNT = 5;
/** OF's discount dialog's top percent: what keeps the price above the floor, at most 60. */
export const maxDiscount = (price: number | null | undefined) => (price ? Math.min(Math.floor((100 * (price - MIN_SUB_PRICE)) / price), 60) : 0);
/** OF's menu condition for "Give user a discount" (84951 `F`). */
export const discountShown = (f: DiscountFan, price: number | null | undefined) =>
  (!!f.canTrialSend || (!!price && (price * (100 - MIN_DISCOUNT)) / 100 >= MIN_SUB_PRICE)) && !f.isBlocked && wasSubscriber(f) && maxDiscount(price) >= MIN_DISCOUNT;

/** The percents OF's select offers at `price`: MIN_DISCOUNT up to maxDiscount, by 5. */
export const discountPercents = (price: number | null | undefined) => {
  const top = maxDiscount(price);
  return Array.from({ length: Math.max(0, Math.floor((top - MIN_DISCOUNT) / 5) + 1) }, (_, i) => MIN_DISCOUNT + i * 5);
};
/** A current discount OF's list does not offer (an odd percent, or above today's top): it shows as it is, but cannot
 *  be applied again (the Relay takes 0 or 5..60 by 5). */
export const offListDiscount = (current: number, percents: number[]) => !!current && !percents.includes(current);
/** OF's "For" select: 1..12 months. */
export const DISCOUNT_PERIODS = Array.from({ length: 12 }, (_, i) => i + 1);

export const months = (n: number) => `${n} ${n === 1 ? "month" : "months"}`;
/** The dialog's help line: "$7.50 per month for 3 months". */
export const discountSummary = (price: number, percent: number, period: number) =>
  `$${(price * (1 - percent / 100)).toFixed(2)} per month for ${months(period)}`;

/** The write: `discount` 0 (period 1) clears it, as OF's Clear does. */
export const putFanDiscount = (accountId: string, fan: string | number, discount: number, period: number) =>
  relay.put(`/api/of/v2/subscriptions/${encodeURIComponent(String(fan))}/discount`, { discount, period }, { accountId });
