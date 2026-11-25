import { discountOptions } from "@/lib/ofMirrorOffers";

export function promoAudience(type: string | null | undefined): string {
  const t = new Set((type || "all").split(","));
  if (t.has("all") && t.has("expired")) return "For expired and new subscribers";
  return t.has("expired") ? "For expired subscribers" : "For new subscribers";
}

export const claimsText = (claimed: number | null | undefined, cap: number | null | undefined) =>
  `${claimed ?? 0} / ${cap ? cap : "∞"}`;

export function offerDate(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const m = d.toLocaleString("en-US", { month: "short", timeZone: "UTC" });
  return `${m}. ${String(d.getUTCDate()).padStart(2, "0")}, ${d.getUTCFullYear()}`;
}

// OF does not echo a discount on its list, so an OF-only discount row reads just "Discount".
export function promoOffer(c: { discount_percent: number | null; price_cents: number; subscribe_days: number }): string {
  const trial = c.discount_percent === 100 || (c.discount_percent == null && c.price_cents <= 0);
  if (trial) return c.subscribe_days > 0 ? `Free trial for ${c.subscribe_days} days` : "Free trial";
  return c.discount_percent != null ? `Discount - ${c.discount_percent}%` : "Discount";
}

export const visibleOffers = <T extends { status: string }>(rows: T[], showExpired: boolean): T[] =>
  showExpired ? rows : rows.filter((r) => r.status !== "finished");

export const discountSteps = (price: number) => discountOptions(price > 0 ? price : 1e9);
