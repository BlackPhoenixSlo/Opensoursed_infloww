/**
 * offerFormat — the wording of Growth's Profile promotion and Free trial links rows, as Infloww's cells word them
 * (bundle: PromoCell, ClaimsCell, the free trial "Claim" column): pure, so the tabs and their tests share it. The
 * link figures and the Details fan table's money are linkMetrics'.
 */

import { discountOptions } from "@/lib/ofMirrorOffers";

/** Infloww's PromoCell audience line: OF's "all" is new subscribers. The mirror keeps both as "all,expired". */
export function promoAudience(type: string | null | undefined): string {
  const t = new Set((type || "all").split(","));
  if (t.has("all") && t.has("expired")) return "For expired and new subscribers";
  return t.has("expired") ? "For expired subscribers" : "For new subscribers";
}

/** Infloww's Claims / Claim cell: "3 / 10", an uncapped offer (0 or none) as "3 / ∞". */
export const claimsText = (claimed: number | null | undefined, cap: number | null | undefined) =>
  `${claimed ?? 0} / ${cap ? cap : "∞"}`;

/** Infloww's date in the Promo cell ("Oct. 01, 2026"); "" without a date. */
export function offerDate(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const m = d.toLocaleString("en-US", { month: "short", timeZone: "UTC" });
  return `${m}. ${String(d.getUTCDate()).padStart(2, "0")}, ${d.getUTCFullYear()}`;
}

/** The promo's offer line, as Infloww's PromoCell: a free trial (100% off, or OF's price 0) and its days, else the
 *  discount. OF does not echo a discount on its list, so an OnlyFans-only discount row reads just "Discount". */
export function promoOffer(c: { discount_percent: number | null; price_cents: number; subscribe_days: number }): string {
  const trial = c.discount_percent === 100 || (c.discount_percent == null && c.price_cents <= 0);
  if (trial) return c.subscribe_days > 0 ? `Free trial for ${c.subscribe_days} days` : "Free trial";
  return c.discount_percent != null ? `Discount - ${c.discount_percent}%` : "Discount";
}

/** Infloww's "Show expired" switch: off (its default) lists only the campaigns still on offer. */
export const visibleOffers = <T extends { status: string }>(rows: T[], showExpired: boolean): T[] =>
  showExpired ? rows : rows.filter((r) => r.status !== "finished");

/** The discount steps for the page's price (OF's); with no price read yet, every 5% step up to 95%. */
export const discountSteps = (price: number) => discountOptions(price > 0 ? price : 1e9);
