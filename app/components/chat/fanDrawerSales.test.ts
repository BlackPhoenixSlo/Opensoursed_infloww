import { describe, expect, it } from "vitest";

import { type FanChatMediaItem } from "@/hooks/useFanChatMedia";
import { type PpvHistoryItem } from "@/hooks/useFanPpvHistory";
import { buildSaleRows, priceMatchScore, UNSOLD_MAX_PAGES, unsoldOf } from "./fanDrawerSales";

const tx = (id: number, cents: number, at: string, extra: Partial<PpvHistoryItem> = {}): PpvHistoryItem => ({
  transaction_id: id, message_id: null, price_cents: cents,
  net_cents: null, fee_cents: null, vat_cents: null,
  purchased_at: at, sent_at: null, sent_by_employee_id: null, employee_name: null, employee_color: null,
  ...extra,
});
const media = (id: number, dollars: number, at: string, extra: Partial<FanChatMediaItem> = {}): FanChatMediaItem => ({
  id, text: `m${id}`, price: dollars, isFree: dollars === 0, isOpened: true, isFromQueue: false,
  mediaCount: 1, createdAt: at, media: [{ id, type: "photo", files: { thumb: { url: `t${id}` } } }], ...extra,
});
/** Each ledger row's matched gallery id (null: ledger-only, so no thumbs), in row order. */
const matched = (m: FanChatMediaItem[], l: PpvHistoryItem[]) =>
  buildSaleRows(m, l).map((r) => [r.key, r.thumbs.length ? r.ofMessageId : null]);

describe("priceMatchScore", () => {
  it.each<[string, number, PpvHistoryItem, "strict" | "loose" | null]>([
    ["exact", 1800, tx(1, 1800, "x"), "strict"],
    ["±2¢ rounding", 1800, tx(1, 1802, "x"), "strict"],
    ["3¢ off is loose, not strict", 1800, tx(1, 1803, "x"), "loose"],
    ["ledger VAT-inclusive (amount − vat)", 1800, tx(1, 2016, "x", { vat_cents: 216 }), "strict"],
    ["ledger ex-VAT (amount + vat)", 1800, tx(1, 1600, "x", { vat_cents: 200 }), "strict"],
    ["net + fee", 1800, tx(1, 2500, "x", { net_cents: 1440, fee_cents: 360 }), "strict"],
    ["within 10% → loose", 1800, tx(1, 1700, "x"), "loose"],
    ["beyond 10% → none", 1800, tx(1, 1500, "x"), null],
    ["zero ledger price never loose", 100, tx(1, 0, "x"), null],
  ])("%s", (_name, ofCents, it_, want) => {
    expect(priceMatchScore(ofCents, it_)).toBe(want);
  });
});

describe("buildSaleRows", () => {
  it.each<[string, FanChatMediaItem[], PpvHistoryItem[], (string | number | null)[][]]>([
    ["message_id match first, over a nearer price match",
      [media(10, 18, "2026-05-01T10:00:00Z"), media(11, 25, "2026-04-01T10:00:00Z")],
      [tx(1, 1800, "2026-05-01T10:00:00Z", { message_id: 11 })],
      [["tx-1", 11]]],
    ["strict beats loose even when loose is nearer in time",
      [media(10, 17, "2026-05-01T10:00:00Z"), media(11, 18, "2026-04-01T10:00:00Z")],
      [tx(1, 1800, "2026-05-01T10:00:00Z")],
      [["tx-1", 11]]],
    ["loose only when no strict exists",
      [media(10, 17, "2026-05-01T10:00:00Z")],
      [tx(1, 1800, "2026-05-01T10:00:00Z")],
      [["tx-1", 10]]],
    ["nearest time wins among strict",
      [media(10, 18, "2026-05-01T08:00:00Z"), media(11, 18, "2026-05-01T11:00:00Z")],
      [tx(1, 1800, "2026-05-01T10:00:00Z")],
      [["tx-1", 11]]],
    ["each gallery item claimed once (two same-price same-day ledger rows)",
      [media(10, 18, "2026-05-01T09:00:00Z")],
      [tx(1, 1800, "2026-05-01T10:00:00Z"), tx(2, 1800, "2026-05-01T09:30:00Z")],
      [["tx-1", 10], ["tx-2", null]]],
    ["newest-first order",
      [],
      [tx(1, 500, "2026-01-01T00:00:00Z"), tx(2, 500, "2026-03-01T00:00:00Z"), tx(3, 500, "2026-02-01T00:00:00Z")],
      [["tx-2", null], ["tx-3", null], ["tx-1", null]]],
  ])("%s", (_name, m, l, want) => {
    expect(matched(m, l)).toEqual(want);
  });

  it("ledger-only rows when the gallery is empty keep the accounting", () => {
    const [row] = buildSaleRows([], [tx(7, 1800, "2026-05-01T10:00:00Z", {
      message_id: 99, net_cents: 1440, fee_cents: 360, employee_name: "Kay", employee_color: "#f00",
    })]);
    expect(row).toEqual({
      key: "tx-7", ofMessageId: 99, text: "", priceCents: 1800, purchasedAt: "2026-05-01T10:00:00Z",
      thumbs: [], netCents: 1440, feeCents: 360, vatCents: null, employeeName: "Kay", employeeColor: "#f00",
    });
  });
});

describe("unsoldOf", () => {
  const unsold = (id: number, at: string) => media(id, 10, at, { isOpened: false });
  const page = (...list: FanChatMediaItem[]) => ({ list });
  it.each<[string, { list: FanChatMediaItem[] }[] | undefined, number[], boolean]>([
    ["no pages yet: nothing, no paging", undefined, [], false],
    ["paid + unopened only, newest first, latest 2",
      [page(unsold(1, "2026-01-01T00:00:00Z"), media(2, 0, "2026-04-01T00:00:00Z", { isOpened: false }),
        media(3, 10, "2026-04-02T00:00:00Z"), unsold(4, "2026-03-01T00:00:00Z")),
       page(unsold(5, "2026-02-01T00:00:00Z"))],
      [4, 5], false],
    ["fewer than 2 found: page on", [page(unsold(1, "2026-01-01T00:00:00Z"))], [1], true],
    ["empty first page: page on", [page()], [], true],
    ["stops at UNSOLD_MAX_PAGES", Array.from({ length: UNSOLD_MAX_PAGES }, () => page()), [], false],
  ])("%s", (_name, pages, ids, wantMore) => {
    const r = unsoldOf(pages);
    expect(r.items.map((m) => m.id)).toEqual(ids);
    expect(r.wantMore).toBe(wantMore);
  });
});
