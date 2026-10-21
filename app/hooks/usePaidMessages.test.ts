import { describe, expect, it } from "vitest";

import { canOfferUnsend } from "@/components/messages/UnsendMessageButton";
import { buildPaidMessagesQuery, type PaidMessageRow } from "@/hooks/usePaidMessages";

describe("the Message dashboard's filters on /admin/paid-messages", () => {
  it("sends only the filters that narrow, in the relay's names and units", () => {
    const qs = new URLSearchParams(buildPaidMessagesQuery({
      from: "2026-10-01", to: "2026-10-02", q: "shower", min_price_cents: 500,
      max_price_cents: 2000, unsent_only: true, sender_type: "automation", kind: "mass",
    }));
    expect(qs.get("q")).toBe("shower");
    expect(qs.get("min_price_cents")).toBe("500");
    expect(qs.get("max_price_cents")).toBe("2000");
    expect(qs.get("unsent_only")).toBe("true");
    expect(qs.get("sender_type")).toBe("automation");
    expect(qs.get("kind")).toBe("mass");
  });

  it("leaves the defaults and a 1-char search off the wire", () => {
    const qs = new URLSearchParams(buildPaidMessagesQuery({
      from: "2026-10-01", to: "2026-10-02", q: "s", unsent_only: false, sender_type: "any", kind: "all",
    }));
    for (const k of ["q", "min_price_cents", "max_price_cents", "unsent_only", "sender_type", "kind"]) {
      expect(qs.has(k)).toBe(false);
    }
  });
});

describe("which rows offer Unsend", () => {
  const row = (over: Partial<PaidMessageRow>): PaidMessageRow => ({
    account_id: "a", fan_id: 1, message_id: 10977996348669,
    fan: { username: null, display_name: null, avatar_url: null },
    body: "", media_count: 0, price_cents: 0, is_paid: false, direction: "out",
    sent_at: null, purchased_at: null, sent_by_employee_id: null, employee_name: null, ...over,
  });

  it("our own live outbound message with a real OnlyFans id", () => {
    expect(canOfferUnsend(row({}))).toBe(true);
  });

  it("not the fan's message, an unsent one, a mass copy, a mass summary or a placeholder id", () => {
    expect(canOfferUnsend(row({ direction: "in" }))).toBe(false);
    expect(canOfferUnsend(row({ is_unsent: true }))).toBe(false);
    expect(canOfferUnsend(row({ is_mass_summary: true }))).toBe(false);
    expect(canOfferUnsend(row({ mass_run_id: 7 }))).toBe(false);
    expect(canOfferUnsend(row({ message_id: 5_000_000_000_000_042 }))).toBe(false);
  });
});
