/** Growth's Profile promotion and Free trial links wording, as Infloww's cells (PromoCell, ClaimsCell, Claim). */
import { describe, expect, it } from "vitest";

import { claimsText, discountSteps, offerDate, promoAudience, promoOffer, visibleOffers } from "./offerFormat";

describe("offerFormat", () => {
  it("words the audience as Infloww's PromoCell, OF's 'all' being new subscribers", () => {
    expect(promoAudience("all")).toBe("For new subscribers");
    expect(promoAudience(null)).toBe("For new subscribers");
    expect(promoAudience("expired")).toBe("For expired subscribers");
    expect(promoAudience("all,expired")).toBe("For expired and new subscribers");
  });

  it("shows an uncapped offer's claims as infinity", () => {
    expect(claimsText(3, 10)).toBe("3 / 10");
    expect(claimsText(3, 0)).toBe("3 / ∞");
    expect(claimsText(null, null)).toBe("0 / ∞");
  });

  it("dates as Infloww's 'MMM. DD, YYYY', nothing without a date", () => {
    expect(offerDate("2026-10-01T10:00:00+00:00")).toBe("Oct. 01, 2026");
    expect(offerDate(null)).toBe("");
    expect(offerDate("not a date")).toBe("");
  });

  it("reads a free trial from 100% off or from OF's price 0, else the discount", () => {
    expect(promoOffer({ discount_percent: 100, price_cents: 0, subscribe_days: 7 })).toBe("Free trial for 7 days");
    expect(promoOffer({ discount_percent: null, price_cents: 0, subscribe_days: 3 })).toBe("Free trial for 3 days");
    expect(promoOffer({ discount_percent: 40, price_cents: 300, subscribe_days: 0 })).toBe("Discount - 40%");
    // OF does not echo the discount on its list: an OnlyFans-only discount row says only that.
    expect(promoOffer({ discount_percent: null, price_cents: 599, subscribe_days: 0 })).toBe("Discount");
  });

  it("hides ended campaigns until Show expired is on (Infloww's default off)", () => {
    const rows = [{ status: "active" }, { status: "finished" }, { status: "unknown" }];
    expect(visibleOffers(rows, false)).toEqual([{ status: "active" }, { status: "unknown" }]);
    expect(visibleOffers(rows, true)).toHaveLength(3);
  });

  it("offers OF's discount steps for the price, every 5% to 95% before the price is read", () => {
    expect(discountSteps(0).map((o) => o.value)).toEqual(Array.from({ length: 19 }, (_, i) => String(5 + i * 5)));
    // $5: OF keeps the price at or over its $3 minimum, so 40% is the most.
    expect(discountSteps(5).at(-1)?.value).toBe("40");
  });
});
