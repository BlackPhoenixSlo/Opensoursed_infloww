/** Infloww's link formulas (its column tooltips) and their "—" rules, and the Edit dialog's Promo cost input. */
import { describe, expect, it } from "vitest";

import {
  aeps, costPer, formatPromoCost, linkAverages, money, parsePromoCost, profit, profitCents, promoCostText, roi, share, updatedAgo,
} from "./linkMetrics";

describe("linkMetrics", () => {
  it("prints money as Infloww: thousands commas, a loss with its sign", () => {
    expect(money(123450)).toBe("$1,234.50");
    expect(money(0)).toBe("$0.00");
    expect(money(-1200)).toBe("-$12.00");
  });

  it("Profit = Earnings − Promo cost, — without a cost or an earnings figure", () => {
    expect(profitCents(98760, 25000)).toBe(73760);
    expect(profit(98760, 25000)).toBe("$737.60");
    expect(profit(1000, 2500)).toBe("-$15.00");
    expect(profit(98760, null)).toBe("—");
    expect(profit(98760, 0)).toBe("—");
    expect(profit(null, 25000)).toBe("—");
  });

  it("CPC and CPS = Promo cost / clicks or subscribers, — without a cost or with nothing to divide by", () => {
    expect(costPer(25000, 200)).toBe("$1.25");
    expect(costPer(25000, 25)).toBe("$10.00");
    expect(costPer(25000, 0)).toBe("—");
    expect(costPer(null, 200)).toBe("—");
    expect(costPer(0, 200)).toBe("—");
  });

  it("ROI = Profit / Promo cost × 100, — without a cost or an earnings figure", () => {
    expect(roi(98760, 25000)).toBe("295.04%");
    expect(roi(0, 25000)).toBe("-100.00%");
    expect(roi(98760, 0)).toBe("—");
    expect(roi(null, 25000)).toBe("—");
  });

  it("AEPS = Earnings / subscribers; Spend/Claim = fans who spent / claims", () => {
    expect(aeps(98760, 25)).toBe("$39.50");
    expect(aeps(98760, 0)).toBe("—");
    expect(aeps(null, 25)).toBe("—");
    expect(share(3, 12)).toBe("25.00%");
    expect(share(0, 12)).toBe("0.00%");
    expect(share(0, 0)).toBe("—");
    expect(share(null, 12)).toBe("—");
  });

  it("reads the Promo cost input as Infloww's: commas allowed, 2 decimals, up to 99,999,999.99, empty is unset", () => {
    expect(parsePromoCost("")).toBeNull();
    expect(parsePromoCost(" 1,250.5 ")).toBe(1250.5);
    expect(parsePromoCost("0")).toBe(0);
    expect(parsePromoCost("99,999,999.99")).toBe(99_999_999.99);
    expect(parsePromoCost("100000000")).toBeNaN();
    expect(parsePromoCost("12.345")).toBeNaN();
    expect(parsePromoCost("-5")).toBeNaN();
    expect(parsePromoCost("abc")).toBeNaN();
    expect(formatPromoCost("1250.5")).toBe("1,250.50");
    expect(formatPromoCost("abc")).toBe("abc");
    expect(promoCostText(25000)).toBe("250.00");
    expect(promoCostText(null)).toBe("");
    expect(promoCostText(0)).toBe("");
  });

  it("says how old the cached figures are", () => {
    const now = Date.parse("2026-10-18T12:00:00Z");
    expect(updatedAgo(null, now)).toBe("Not read yet");
    expect(updatedAgo("2026-10-18T11:59:40Z", now)).toBe("Updated just now");
    expect(updatedAgo("2026-10-18T11:48:00Z", now)).toBe("Updated 12 min ago");
    expect(updatedAgo("2026-10-18T09:30:00Z", now)).toBe("Updated 2 h ago");
  });

  it("averages CPC, CPS and ROI pooled over the costed links (ours), — without one", () => {
    const one = { promo_cost_cents: 25000, clicks: 200, subscribers: 25, earnings_cents: 98760 };
    const two = { promo_cost_cents: 5000, clicks: 0, subscribers: 0, earnings_cents: 0 };
    const free = { promo_cost_cents: null, clicks: 1000, subscribers: 500, earnings_cents: 100000 };
    // $300.00 over 200 clicks and 25 subs; ($987.60 − $300.00) / $300.00; the uncosted link counts nowhere.
    expect(linkAverages([one, two, free])).toEqual({ cpc: "$1.50", cps: "$12.00", roi: "229.20%", roiPartial: false });
    expect(linkAverages([free])).toEqual({ cpc: "—", cps: "—", roi: "—", roiPartial: false });
    expect(linkAverages([])).toEqual({ cpc: "—", cps: "—", roi: "—", roiPartial: false });
    // Costed, but no clicks or subs: "—" on those, ROI still reads.
    expect(linkAverages([two])).toEqual({ cpc: "—", cps: "—", roi: "-100.00%", roiPartial: false });
  });

  it("takes Avg ROI over the costed links with an earnings figure, marked partial when one has none", () => {
    const one = { promo_cost_cents: 25000, clicks: 200, subscribers: 25, earnings_cents: 98760 };
    const unknown = { promo_cost_cents: 5000, clicks: 100, subscribers: 5, earnings_cents: null };
    expect(linkAverages([one, unknown])).toEqual({ cpc: "$1.00", cps: "$10.00", roi: "295.04%", roiPartial: true });
    expect(linkAverages([unknown]).roi).toBe("—");
    expect(linkAverages([unknown]).roiPartial).toBe(false);
    expect(linkAverages([{ ...one, earnings_partial: true }]).roiPartial).toBe(true);
  });
});
