/** Infloww's link formulas (its column tooltips) and their "—" rules, and the Edit dialog's Promo cost input. */
import { describe, expect, it } from "vitest";

import {
  aeps, costPer, cvr, formatPromoCost, linkAverages, money, parsePromoCost, per, profit, profitCents, promoCostText, roi, share, updatedAgo,
} from "./linkMetrics";

describe("linkMetrics", () => {
  it("prints money as the house fmtCents: whole dollars with commas at every size, a loss with its sign", () => {
    expect(money(123450)).toBe("$1,235");
    expect(money(98760)).toBe("$988");
    expect(money(0)).toBe("$0");
    expect(money(-1200)).toBe("-$12");
  });

  it("Profit = Earnings − Promo cost, — without a cost or an earnings figure", () => {
    expect(profitCents(98760, 25000)).toBe(73760);
    expect(profit(98760, 25000)).toBe("$738");
    expect(profit(1000, 2500)).toBe("-$15");
    expect(profit(98760, null)).toBe("—");
    expect(profit(98760, 0)).toBe("—");
    expect(profit(null, 25000)).toBe("—");
  });

  it("CPC and CPS = Promo cost / clicks or subscribers, — without a cost or with nothing to divide by", () => {
    expect(costPer(25000, 200)).toBe("$1.25");
    expect(costPer(25000, 25)).toBe("$10");
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
    expect(linkAverages([one, two, free])).toEqual({ cpc: "$1.50", cps: "$12", roi: "229.20%", roiPartial: false });
    expect(linkAverages([free])).toEqual({ cpc: "—", cps: "—", roi: "—", roiPartial: false });
    expect(linkAverages([])).toEqual({ cpc: "—", cps: "—", roi: "—", roiPartial: false });
    // Costed, but no clicks or subs: "—" on those, ROI still reads.
    expect(linkAverages([two])).toEqual({ cpc: "—", cps: "—", roi: "-100.00%", roiPartial: false });
  });

  it("takes Avg ROI over the costed links with an earnings figure, marked partial when one has none", () => {
    const one = { promo_cost_cents: 25000, clicks: 200, subscribers: 25, earnings_cents: 98760 };
    const unknown = { promo_cost_cents: 5000, clicks: 100, subscribers: 5, earnings_cents: null };
    expect(linkAverages([one, unknown])).toEqual({ cpc: "$1", cps: "$10", roi: "295.04%", roiPartial: true });
    expect(linkAverages([unknown]).roi).toBe("—");
    expect(linkAverages([unknown]).roiPartial).toBe(false);
    expect(linkAverages([{ ...one, earnings_partial: true }]).roiPartial).toBe(true);
  });

  it.each([
    // [subscribers, clicks, CVR]
    [2435, 23037, "10.57%"],
    [1, 3, "33.33%"], // 33.333… to 2 decimals
    [2, 3, "66.67%"], // 66.666… rounds up
    [0, 50, "0.00%"],
    [5, 5, "100.00%"],
    [12, 0, "—"], // zero clicks: nothing to divide by
    [0, 0, "—"],
  ])("Subscription CVR of %i subs over %i clicks is %s", (subscribers, clicks, want) => {
    expect(cvr({ subscribers, clicks })).toBe(want);
  });

  it.each([
    // [earnings cents, n, EPC / AEPS]
    [14181440, 23037, "$6.16"],
    [100000, 3, "$333.33"], // 33,333.33… cents
    [1000, 4, "$2.50"],
    [100000, 100, "$10"], // whole dollars print without cents (fmtPrice)
    [0, 10, "$0"],
    [5000, 0, "—"], // zero clicks / subs
    [5000, null, "—"],
    [null, 10, null], // no earnings figure: the column has no value for this link
    [undefined, 10, null],
  ])("earnings %s cents per %s is %s", (cents, n, want) => {
    expect(per(cents, n)).toBe(want);
  });

  it.each([
    // [part, whole, Subscription CVR / Spending CVR]
    [0, 0, "—"],
    [0, 7, "0.00%"],
    [12, 0, "—"],
    [1, 800, "0.13%"], // 0.125 %: a half hundredth
    [1, 200, "0.50%"],
    [1, 3, "33.33%"],
    [2, 3, "66.67%"],
    [9_999_999, 10_000_000, "100.00%"], // large, rounds up
    [123_456_789, 987_654_321, "12.50%"],
    [5, 5, "100.00%"],
    [5, -10, "-50.00%"], // negative clicks: divided as given (current behaviour)
  ])("Subscription CVR / Spending CVR of %i over %i is %s", (part, whole, want) => {
    expect(cvr({ subscribers: part, clicks: whole })).toBe(want);
    expect(share(part, whole)).toBe(want);
  });

  it.each([
    // [fans who spent, counted fans, share] (the Spending CVR cell itself is null with no spend figure)
    [null, 10, "—"],
    [null, null, "—"],
    [3, null, "—"],
    [3, 0, "—"],
    [0, 0, "—"],
    [0, 4, "0.00%"],
  ])("share of %s fans who spent over %s counted fans is %s", (spent, counted, want) => {
    expect(share(spent, counted)).toBe(want);
  });

  it.each([
    // [earnings cents, subs, want]
    [null, 25, "—"],
    [null, 0, "—"],
    [98760, null, "—"],
    [98760, 0, "—"],
    [0, 25, "$0"],
    [1, 2, "$0.01"], // half a cent rounds away from zero
    [1001, 2, "$5.01"], // 500.5 cents
    [100000, 3, "$333.33"],
    [100000, 100, "$10"],
    [999_999_999_99, 7, "$142,857,142.86"], // large
  ])("AEPS of %s cents over %s subs is %s", (earnings, subs, want) => {
    expect(aeps(earnings, subs)).toBe(want);
  });
});
