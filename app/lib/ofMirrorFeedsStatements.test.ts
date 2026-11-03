import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it, vi } from "vitest";
import { applyData, partsOf } from "./ofMirrorData";
import { nextOffset, pageRows } from "./ofMirrorPaging";
import { ofMoney, zoneNote, type Payout, type Transaction } from "./ofMirrorFeedsStatements";
import { TEMPLATES } from "./ofMirrorFeedsShared";
import { capture, load, shown, texts, atFixtureNow, PLACEHOLDER } from "./ofMirrorData.fixtures";

/** OF's own /payouts/transactions pages, captured through the Relay and scrubbed (app/lib/__fixtures__/of). */
const fixture = <T,>(name: string): T => JSON.parse(readFileSync(resolve(__dirname, `__fixtures__/of/statements-${name}.json`), "utf8")) as T;
type TxnPage = { list: Transaction[]; hasMore: boolean; nextMarker: number | null; marker: number };
const PAGE = fixture<TxnPage>("transactions"); // six rows, no more
const MORE = fixture<TxnPage>("transactions-more"); // OF's limit=2: two rows and hasMore
const EMPTY_PAGE = fixture<TxnPage>("transactions-empty"); // a page past the end: no rows
const TXNS = PAGE.list;
// The Agency's time zone (Settings): the dates read the same wherever the tests run.
const TZ = "Europe/Ljubljana";
const EARNINGS = "statements/earnings";
const txns = (doc: Document) => shown(doc, ".b-table tbody > tr").filter((r) => r.querySelector(".b-table__date"));
// [date, time, amount, fee, net, description HTML, [[tip label, icon] per status tip]] per row shown.
const txnRows = (doc: Document) =>
  txns(doc).map((r) => [
    r.querySelector(".b-table__date__date > span")!.textContent,
    r.querySelector(".b-table__date__time > span")!.textContent,
    r.querySelector(".b-table__amount > span")!.textContent,
    r.querySelector(".b-table__fee > span")!.textContent,
    r.querySelector(".b-table__net strong > span")!.textContent,
    r.querySelector(".b-table__desc .b-field-subscription")!.innerHTML,
    [...r.querySelectorAll(".b-table__status-tip")].map((t) => [t.getAttribute("aria-label"), t.querySelector("svg")!.getAttribute("data-icon-name")]),
  ]);
const COMPLETE = ["Complete", "icon-done"];
const DONE = [COMPLETE, COMPLETE];
const MESSAGE = "Payment for message from Synth Fan Two";
const WANT_TXNS = [
  [" Oct 12, 2026 ", " 11:41 am ", " $5.00 ", " $1.00 ", " $4.00 ", "Subscription from Synth Fan One", DONE],
  [" Aug 3, 2026 ", " 8:22 pm ", " $4.00 ", " $0.80 ", " $3.20 ", MESSAGE, DONE],
  [" Aug 3, 2026 ", " 7:05 pm ", " $25.00 ", " $5.00 ", " $20.00 ", MESSAGE, DONE],
  [" Aug 3, 2026 ", " 6:47 pm ", " $4.00 ", " $0.80 ", " $3.20 ", MESSAGE, DONE],
  [" Aug 3, 2026 ", " 6:12 pm ", " $30.00 ", " $6.00 ", " $24.00 ", MESSAGE, DONE],
  [" Aug 3, 2026 ", " 5:58 pm ", " $15.00 ", " $3.00 ", " $12.00 ", MESSAGE, DONE],
];
const EMPTY_ROW = ".b-table tbody .empty-message";
const NOTE_TZ = ".b-statements__head-timezone";
/** The page as captured outside the table's rows and its time zone note (Earnings): the balance boxes and the tabs. */
const outsideRows = (doc: Document) => {
  const c = doc.documentElement.cloneNode(true) as Element;
  c.querySelector(".b-table tbody")!.remove();
  c.querySelector(NOTE_TZ)?.remove();
  return c.outerHTML;
};
/** OF's infinite loading row's prompts shown: spinner, no more, no results, error. */
const prompts = (doc: Document) => [...doc.querySelectorAll<HTMLElement>(".infinite-loading-container > .infinite-status-prompt")].map((p) => p.style.display !== "none");

describe("statements/earnings: the Creator's earning transactions (OF's captured pages)", () => {
  it("gives Earnings the transactions", () => {
    expect(partsOf(EARNINGS)).toEqual(["transactions"]);
  });

  it("one row per transaction, in order, before the loading row: OF's money, dates in the Agency's zone, descriptions as text, a deleted fan greyed", () => {
    const doc = load(EARNINGS);
    const outside = outsideRows(doc);
    // At the fixtures' "now" (summer time), so the zone note does not follow today's date.
    atFixtureNow(() => applyData(doc, EARNINGS, { transactions: TXNS, zone: TZ }));
    expect(txnRows(doc)).toEqual(WANT_TXNS);
    const rows = txns(doc);
    expect(rows.every((r) => r.hasAttribute("data-oi-data"))).toBe(true);
    expect(rows.map((r) => r.querySelectorAll(".b-table__desc a").length)).toEqual([0, 0, 0, 0, 0, 0]);
    // The capture's fan is active; the second fan is deleted (OF: isDeleted || !isActive).
    expect(rows.map((r) => r.querySelector(".b-field-subscription")!.classList.contains("m-disabled-username"))).toEqual([false, true, true, true, true, true]);
    for (const r of rows) expect(r.textContent).not.toMatch(PLACEHOLDER);
    expect(texts(doc, NOTE_TZ)).toEqual(["Date/Time shown in local time (UTC +02:00)"]);
    const tbody = doc.querySelector(".b-table tbody")!;
    expect(rows.at(-1)!.nextElementSibling).toBe(tbody.lastElementChild);
    expect(tbody.lastElementChild!.querySelector(".infinite-loading-container")).not.toBeNull();
    expect(outsideRows(doc)).toBe(outside);
  });

  it("OF's UtilsMoney: thousands commas, its m-zero-value on a figure that rounds to 0, the currency's symbol; a pending row's tip; an absent fee empty", () => {
    const doc = load(EARNINGS);
    const [sub] = TXNS;
    applyData(doc, EARNINGS, {
      zone: TZ,
      transactions: [
        { ...sub, amount: 1234.5, fee: 246.9, net: 987.6 },
        { ...sub, amount: 0.4, fee: 0.08, net: 0.32, status: "loading", payoutPendingDays: 5 },
        { ...sub, currency: "EUR", fee: null, status: "loading" },
      ],
    });
    const rows = txnRows(doc);
    expect(rows.map((r) => r.slice(2, 5))).toEqual([
      [" $1,234.50 ", " $246.90 ", " $987.60 "],
      [" $0.40 ", " $0.08 ", " $0.32 "],
      [" €5.00 ", "", " €4.00 "],
    ]);
    expect(rows.map((r) => r[6])).toEqual([DONE, Array(2).fill(["Earning will become available in 5 days", "icon-loading"]), Array(2).fill([null, "icon-loading"])]);
    const zero = txns(doc).map((r) => [".b-table__amount > span", ".b-table__fee > span"].map((s) => r.querySelector(s)!.classList.contains("m-zero-value")));
    expect(zero).toEqual([[false, false], [true, true], [false, false]]);
    expect(ofMoney(12, "cad")).toBe("12.00 CAD");
    expect(ofMoney(1000000, "gbp")).toBe("£1,000,000.00");
  });

  it("the time zone note follows the zone (none: the browser's), as OF's dayjs().format('Z')", () => {
    const summer = new Date("2026-08-03T12:00:00Z");
    expect(zoneNote("Europe/Ljubljana", summer)).toBe("UTC +02:00");
    expect(zoneNote("America/New_York", new Date("2026-01-15T12:00:00Z"))).toBe("UTC -05:00");
    expect(zoneNote("Asia/Kolkata", summer)).toBe("UTC +05:30");
    expect(zoneNote("Not/AZone", summer)).toBe(zoneNote(null, summer));
  });

  it("an empty period (OF's page past the end) keeps OF's empty row; no example row; Creator A's rows then Creator B's leave only B's; no data restores the capture byte for byte", () => {
    const doc = load(EARNINGS);
    const html = doc.documentElement.innerHTML;
    expect(txns(doc)).toEqual([]);
    expect(texts(doc, EMPTY_ROW)).toEqual(["No earnings for this period"]);
    applyData(doc, EARNINGS, { transactions: pageRows([EMPTY_PAGE]), zone: TZ });
    expect(txns(doc)).toEqual([]);
    expect(texts(doc, EMPTY_ROW)).toEqual(["No earnings for this period"]);
    expect(shown(doc, ".infinite-loading-container")).toHaveLength(1);
    applyData(doc, EARNINGS, { transactions: TXNS, zone: TZ });
    applyData(doc, EARNINGS, { transactions: MORE.list.slice(1), zone: TZ });
    expect(txnRows(doc)).toEqual([WANT_TXNS[1]]);
    expect(texts(doc, EMPTY_ROW)).toEqual([]);
    expect(doc.querySelectorAll("[data-oi-data]")).toHaveLength(1);
    applyData(doc, EARNINGS, {});
    expect(doc.documentElement.innerHTML).toBe(html);
  });

  it("OF's pages: the next offset after a page with more, none after the last or an empty one; the pages' rows in order", () => {
    expect(nextOffset(MORE, [MORE])).toBe(2);
    expect(nextOffset(MORE, [MORE, MORE])).toBe(4);
    expect(nextOffset(PAGE, [PAGE])).toBeUndefined();
    expect(nextOffset(EMPTY_PAGE, [MORE, EMPTY_PAGE])).toBeUndefined();
    expect(pageRows([MORE, { ...PAGE, list: PAGE.list.slice(2) }])).toEqual(TXNS);
    expect(pageRows(undefined)).toBeUndefined();
    expect(pageRows([{ error: "502" }])).toBeUndefined();
  });

  it("the loading row: its spinner while the next page is read, Retry after that failed, otherwise the next page once it is in view; no data restores byte for byte", () => {
    const doc = load(EARNINGS);
    const html = doc.documentElement.innerHTML;
    const next = vi.fn();
    applyData(doc, EARNINGS, { transactions: MORE.list, zone: TZ, transactionsMore: { loading: true, error: null, next } });
    expect(prompts(doc)).toEqual([true, false, false, false]);
    applyData(doc, EARNINGS, { transactions: MORE.list, zone: TZ, transactionsMore: { loading: false, error: "502 Bad Gateway", next } });
    expect(prompts(doc)).toEqual([false, false, false, true]);
    doc.querySelector<HTMLButtonElement>(".infinite-loading-container .btn-try-infinite")!.click();
    expect(next).toHaveBeenCalledTimes(1);
    // In view: an IntersectionObserver on OF's loading row asks once, and stops watching. Its root is the frame's own
    // document, so its 300px margin reaches below the frame (the top page's viewport clips a row just under the frame's end).
    const seen: Element[] = [];
    const stop = vi.fn();
    let fire: (e: { isIntersecting: boolean }[]) => void = () => {};
    let options: IntersectionObserverInit | undefined;
    vi.stubGlobal("IntersectionObserver", class {
      constructor(cb: typeof fire, init?: IntersectionObserverInit) {
        fire = cb;
        options = init;
      }
      observe(el: Element) {
        seen.push(el);
      }
      disconnect = stop;
    });
    try {
      applyData(doc, EARNINGS, { transactions: MORE.list, zone: TZ, transactionsMore: { loading: false, error: null, next } });
      expect(prompts(doc)).toEqual([false, false, false, false]);
      expect(seen).toEqual([doc.querySelector(".infinite-loading-container")]);
      expect(options).toEqual({ root: doc, rootMargin: "0px 0px 300px 0px" });
      fire([{ isIntersecting: false }]);
      expect(next).toHaveBeenCalledTimes(1);
      fire([{ isIntersecting: true }]);
      expect(next).toHaveBeenCalledTimes(2);
      // The last page: nothing to ask for.
      seen.length = 0;
      applyData(doc, EARNINGS, { transactions: TXNS, zone: TZ, transactionsMore: { loading: false, error: null, next: null } });
      expect(seen).toEqual([]);
    } finally {
      vi.unstubAllGlobals();
    }
    applyData(doc, EARNINGS, {});
    expect(doc.documentElement.innerHTML).toBe(html);
    doc.querySelector<HTMLButtonElement>(".infinite-loading-container .btn-try-infinite")!.click();
    expect(next).toHaveBeenCalledTimes(2);
  });

  it("while the rows load the empty row says so, and on a Relay error shows it; rows replace it; no data restores byte for byte", () => {
    for (const page of [EARNINGS, "statements/index", PAYOUTS_PAGE, REFERRALS]) {
      const doc = load(page);
      const html = doc.documentElement.innerHTML;
      applyData(doc, page, { statementsStatus: null });
      expect(texts(doc, EMPTY_ROW)).toEqual(["Loading…"]);
      applyData(doc, page, { statementsStatus: "502 Bad Gateway" });
      expect(texts(doc, EMPTY_ROW)).toEqual(["Could not load: 502 Bad Gateway"]);
      applyData(doc, page, {});
      expect(doc.documentElement.innerHTML).toBe(html);
    }
  });
});

// Local times (no Z). In the Relay's order, OF's states (statements-payout.js getDescription): approved twice, rejected
// with and without a reason, pending, new, and a state OF does not know.
const PAYOUTS: Payout[] = [
  { createdAt: "2026-10-10T10:05:00", invoiceId: "INV-1001", amount: 120, state: "approved" },
  { createdAt: "2026-10-09T21:30:00", invoiceId: 1002, amount: 45.5, state: "approved" },
  { createdAt: "2026-10-08T08:00:00", invoiceId: "INV-1003", amount: 300, state: "rejected", rejectReason: "Alpha One's bank details are wrong" },
  { createdAt: "2026-10-07T12:00:00", invoiceId: "INV-1004", amount: 10, state: "rejected" },
  { createdAt: "2026-10-06T12:00:00", invoiceId: "INV-1005", amount: 20, state: "pending" },
  { state: "new" },
  { state: "done" },
];
const PAYOUTS_PAGE = "statements/payouts";
const REFERRALS = "statements/referrals";
// The `payoutRow` template as useOfData borrows it: the payouts capture, parsed inertly.
const PAYOUT_TPL = TEMPLATES.payoutRow!.pick(new DOMParser().parseFromString(capture(TEMPLATES.payoutRow!.page), "text/html"))!;
// [date, time, invoice, amount, status cell HTML] per payout row shown.
const payoutRows = (doc: Document) =>
  txns(doc).map((r) => [
    r.querySelector(".b-table__date__date > span")!.textContent,
    r.querySelector(".b-table__date__time > span")!.textContent,
    r.querySelector(".b-table__invoice")!.textContent,
    r.querySelector(".b-table__amount strong > span")!.textContent,
    r.querySelector(".b-table__desc")!.innerHTML,
  ]);
const APPROVED = '<span class="approved">Payout has been processed<svg aria-hidden="true" class="g-icon"><use href="#icon-done"></use></svg></span>';
const REJECTED = "Payout request could not be processed and this amount was returned to your Current Balance.";
const ALERT = '<svg aria-hidden="true" class="g-icon"><use href="#icon-alert"></use></svg>';
// OF's pending mark without its text (OF's wording was never captured).
const PENDING = '<span class="pending"><svg aria-hidden="true" class="g-icon"><use href="#icon-loading"></use></svg></span>';
const WANT_PAYOUTS = [
  [" Oct 10, 2026 ", " 10:05 am ", " INV-1001 ", " $120.00 ", APPROVED],
  [" Oct 9, 2026 ", " 9:30 pm ", " 1002 ", " $45.50 ", APPROVED],
  [" Oct 8, 2026 ", " 8:00 am ", " INV-1003 ", " $300.00 ", `<span class="rejected">${REJECTED}<br>Reason: Alpha One's bank details are wrong${ALERT}</span>`],
  [" Oct 7, 2026 ", " 12:00 pm ", " INV-1004 ", " $10.00 ", `<span class="rejected">${REJECTED}${ALERT}</span>`],
  [" Oct 6, 2026 ", " 12:00 pm ", " INV-1005 ", " $20.00 ", PENDING],
  ["", "", "", "", PENDING],
  ["", "", "", "", ""],
];
const ONE_PAYOUT: Payout[] = [{ createdAt: "2026-10-01T12:00:00", invoiceId: "INV-2001", amount: 7, state: "approved" }];
const WANT_ONE = [[" Oct 1, 2026 ", " 12:00 pm ", " INV-2001 ", " $7.00 ", APPROVED]];
const REFERRAL_EMPTY = ".b-table tbody .empty-message";

describe("statements/payouts and statements/referrals: the Creator's payout requests", () => {
  it("gives Payouts the payouts and Referrals the referrals", () => {
    expect(partsOf(PAYOUTS_PAGE)).toEqual(["payouts"]);
    expect(partsOf(REFERRALS)).toEqual(["referrals"]);
  });

  it("the payoutRow template is the payouts page's first approved row", () => {
    expect(TEMPLATES.payoutRow!.page).toBe(PAYOUTS_PAGE);
    expect(PAYOUT_TPL.matches(".b-table tbody tr")).toBe(true);
    expect(PAYOUT_TPL.querySelector(".b-table__date__date > span")?.textContent).toBe(" Aug 19, 2026 ");
    expect(PAYOUT_TPL.querySelector(".b-table__desc")?.innerHTML).toBe(APPROVED);
  });

  it("payouts: one row per request, in order, before the loading row: approved, rejected with and without a reason, other states, absent fields as mapped", () => {
    const doc = load(PAYOUTS_PAGE);
    const outside = outsideRows(doc);
    applyData(doc, PAYOUTS_PAGE, { payouts: PAYOUTS });
    expect(payoutRows(doc)).toEqual(WANT_PAYOUTS);
    const rows = txns(doc);
    expect(rows.every((r) => r.hasAttribute("data-oi-data"))).toBe(true);
    const tbody = doc.querySelector(".b-table tbody")!;
    expect(rows.at(-1)!.nextElementSibling).toBe(tbody.lastElementChild);
    expect(tbody.lastElementChild!.querySelector(".infinite-loading-container")).not.toBeNull();
    // "Request withdrawal" stays disabled and the balance as captured.
    expect(outsideRows(doc)).toBe(outside);
    expect(doc.querySelector<HTMLButtonElement>("button.g-btn.m-rounded[disabled]")?.textContent?.trim()).toBe("Request withdrawal");
  });

  it("payouts: no example row, OF's empty row; an empty list keeps it; Creator A's rows then Creator B's leave only B's; no data restores the capture byte for byte", () => {
    const doc = load(PAYOUTS_PAGE);
    const html = doc.documentElement.innerHTML;
    expect(txns(doc)).toEqual([]);
    expect(texts(doc, EMPTY_ROW)).toEqual(["This list is empty"]);
    applyData(doc, PAYOUTS_PAGE, { payouts: [] });
    expect(txns(doc)).toEqual([]);
    expect(texts(doc, EMPTY_ROW)).toEqual(["This list is empty"]);
    expect(shown(doc, ".infinite-loading-container")).toHaveLength(1);
    applyData(doc, PAYOUTS_PAGE, { payouts: PAYOUTS });
    applyData(doc, PAYOUTS_PAGE, { payouts: ONE_PAYOUT });
    expect(payoutRows(doc)).toEqual(WANT_ONE);
    expect(doc.querySelectorAll("[data-oi-data]")).toHaveLength(1);
    applyData(doc, PAYOUTS_PAGE, {});
    expect(doc.documentElement.innerHTML).toBe(html);
  });

  it("referrals: the borrowed row per referral payout, in order, as payouts map them; the empty-message row hidden while rows show", () => {
    const doc = load(REFERRALS);
    const outside = outsideRows(doc);
    applyData(doc, REFERRALS, { referrals: PAYOUTS, templates: { payoutRow: PAYOUT_TPL } });
    expect(payoutRows(doc)).toEqual(WANT_PAYOUTS);
    expect(txns(doc).every((r) => r.hasAttribute("data-oi-data") && r.ownerDocument === doc)).toBe(true);
    expect(shown(doc, REFERRAL_EMPTY)).toEqual([]);
    // The referral balance and "Request withdrawal" stay as captured.
    expect(outsideRows(doc)).toBe(outside);
  });

  it("referrals: an empty list keeps \"This list is empty\"; no template keeps the page as captured", () => {
    const doc = load(REFERRALS);
    const html = doc.documentElement.innerHTML;
    applyData(doc, REFERRALS, { referrals: [], templates: { payoutRow: PAYOUT_TPL } });
    expect(texts(doc, REFERRAL_EMPTY)).toEqual(["This list is empty"]);
    expect(txns(doc)).toEqual([]);
    applyData(doc, REFERRALS, { referrals: PAYOUTS });
    expect(doc.documentElement.innerHTML).toBe(html);
  });

  it("referrals: Creator A's rows then Creator B's leave only B's; no data restores the capture byte for byte", () => {
    const doc = load(REFERRALS);
    const html = doc.documentElement.innerHTML;
    applyData(doc, REFERRALS, { referrals: PAYOUTS, templates: { payoutRow: PAYOUT_TPL } });
    applyData(doc, REFERRALS, { referrals: ONE_PAYOUT, templates: { payoutRow: PAYOUT_TPL } });
    expect(payoutRows(doc)).toEqual(WANT_ONE);
    expect(doc.querySelectorAll("[data-oi-data]")).toHaveLength(1);
    applyData(doc, REFERRALS, {});
    expect(doc.documentElement.innerHTML).toBe(html);
  });
});
