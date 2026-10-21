import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it, vi } from "vitest";
import {
  amountError,
  applyMoney,
  earningsChart,
  minSumMessage,
  moneyOf,
  moneyParts,
  payoutDate,
  payoutsDisabled,
  resultDescription,
  withdrawDisabled,
  withdrawError,
  type Balances,
  type EarningStats,
  type MoneyActions,
  type PayoutUser,
} from "./ofMirrorMoney";
import { RelayError } from "./relay";
import { linesOf } from "./ofMirrorChart";
import { applyData, partsOf } from "./ofMirrorData";
import type { Transaction } from "./ofMirrorFeeds";

const capture = (p: string) => readFileSync(resolve(__dirname, `../public/of-mirror/pages/${p}.html`), "utf8");
const load = (p: string) => {
  document.documentElement.innerHTML = capture(p);
  return document;
};
const visible = (el: Element) => !el.closest("[style*='display:none']");
const texts = (doc: Document, sel: string) => [...doc.querySelectorAll(sel)].filter(visible).map((e) => e.textContent?.trim());

/** OF's own /payouts/balances, captured through the Relay (synthetic figures; app/lib/__fixtures__/of). */
const CAPTURED: Balances = JSON.parse(readFileSync(resolve(__dirname, "__fixtures__/of/statements-balances.json"), "utf8"));
// OF's shape with figures that show the formatting: thousands, a zero, another minimum and frequency.
const BAL: Balances = { ...CAPTURED, payoutAvailable: 1234.5, payoutPending: 0, minPayoutSumm: 50, withdrawalPeriod: "weekly" };
const OPTIONS = ".balance-block .v-select-list > .v-list-item";
const options = (doc: Document) => [...doc.querySelectorAll(OPTIONS)].filter((o) => !(o as HTMLElement).style.display).map((o) => [o.textContent!.trim(), o.getAttribute("aria-selected"), o.classList.contains("v-list-item--active")]);

describe("moneyParts", () => {
  it("balances on Statements (not Support) and Statistics' Overview and Statements tabs; one figure per page beside", () => {
    expect(moneyParts("statements/index")).toEqual(["balances"]);
    expect(moneyParts("statements/stats/earnings/state-date-range")).toEqual(["balances", "earningStats"]);
    expect(moneyParts("statements/referrals")).toEqual(["balances", "referralBalance"]);
    expect(moneyParts("statistics/statements/referrals/earnings")).toEqual(["balances", "referralBalance"]);
    expect(moneyParts("statistics/statements/disputes")).toEqual(["balances"]); // its ratio follows the period: ofMirrorStats
    expect(moneyParts("statistics/overview/earnings/state-period-dropdown")).toEqual(["balances"]);
    for (const p of ["statements/support", "statistics/engagement/messages", "statistics/fans/top-fans", "bank/index", "bank/payout_types", "home/index"]) expect(moneyParts(p)).toEqual([]);
  });

  it("reads OF's fields: /payouts/stats from its list", () => {
    expect(moneyOf("earningStats", { list: { total: { all: { total_net: 1 } } } })).toEqual({ earningStats: { total: { all: { total_net: 1 } } } });
    expect(moneyOf("referralBalance", { referralEarnings: 3, pendingEarnings: 1 })).toEqual({ referralEarnings: 3 });
    expect(moneyOf("balances", null)).toEqual({});
  });
});

describe("balances", () => {
  it("Statements' box: current, pending (zero-marked), frequency name and minimum; no data restores byte for byte", () => {
    const doc = load("statements/earnings");
    const html = doc.documentElement.innerHTML;
    applyMoney(doc, "statements/earnings", { balances: BAL });
    expect(texts(doc, ".b-statements__current-balance__value > span")).toEqual(["$1,234.50"]);
    expect(texts(doc, ".b-statements__pending-balance__value > span")).toEqual(["$0.00"]);
    expect(doc.querySelector(".b-statements__pending-balance__value > span")!.classList.contains("m-zero-value")).toBe(true);
    expect(texts(doc, ".balance-block .v-select__selection")).toEqual(["Weekly payouts"]);
    // Weekly payouts: OF's minSumMessage gives the next payout's day (OF reads availableAmount, absent from its balances).
    expect(texts(doc, ".b-statements__min-payout-summ")).toEqual([`Once your balance is over $50 next payout will be scheduled on: ${payoutDate("weekly", new Date())}`]);
    applyMoney(doc, "statements/earnings", { balances: { ...BAL, payoutAvailable: 7 } });
    expect(texts(doc, ".b-statements__current-balance__value > span")).toEqual(["$7.00"]);
    applyMoney(doc, "statements/earnings", {});
    expect(doc.documentElement.innerHTML).toBe(html);
  });

  it("OF's captured balances: its figures, frequency and minimum; the frequency menu's options are OF's, the current one selected; fewer or more options than captured; byte for byte after", () => {
    const doc = load("statements/earnings");
    const html = doc.documentElement.innerHTML;
    applyMoney(doc, "statements/earnings", { balances: CAPTURED });
    expect(texts(doc, ".b-statements__current-balance__value > span")).toEqual(["$12.80"]);
    expect(texts(doc, ".b-statements__pending-balance__value > span")).toEqual(["$0.00"]);
    expect(texts(doc, ".balance-block .v-select__selection")).toEqual(["Manual payouts"]);
    expect(texts(doc, ".b-statements__min-payout-summ")).toEqual(["Minimum withdrawal amount is $20"]);
    expect(options(doc)).toEqual([["Manual payouts", "true", true], ["Weekly payouts", "false", false], ["Monthly payouts", "false", false]]);
    applyMoney(doc, "statements/earnings", { balances: { ...CAPTURED, withdrawalPeriod: "weekly", withdrawalPeriodOptions: CAPTURED.withdrawalPeriodOptions!.slice(0, 2) } });
    expect(options(doc)).toEqual([["Manual payouts", "false", false], ["Weekly payouts", "true", true]]);
    const four = [...CAPTURED.withdrawalPeriodOptions!, { code: "daily", name: "Daily payouts" }];
    applyMoney(doc, "statements/earnings", { balances: { ...CAPTURED, withdrawalPeriod: "daily", withdrawalPeriodOptions: four } });
    expect(options(doc).map((o) => o[0])).toEqual(["Manual payouts", "Weekly payouts", "Monthly payouts", "Daily payouts"]);
    expect(options(doc).map((o) => o[2])).toEqual([false, false, false, true]);
    // Request withdrawal: disabled by OF's rule (a balance under the minimum), no tooltip.
    expect([...doc.querySelectorAll<HTMLButtonElement>(".balance-block .g-btn")].map((b) => [b.disabled, b.title])).toEqual([[true, ""]]);
    applyMoney(doc, "statements/earnings", {});
    expect(doc.documentElement.innerHTML).toBe(html);
  });

  it("Statistics' sidebar: both sums, frequency and minimum; an absent amount a dash", () => {
    const doc = load("statistics/statements/earnings");
    applyMoney(doc, "statistics/statements/earnings", { balances: { ...BAL, payoutPending: undefined } });
    expect(texts(doc, ".b-statements-balances__sum")).toEqual(["$1,234.50", "—"]);
    expect(texts(doc, ".balance-block .b-holder-options__title")).toEqual(["Weekly payouts"]);
    expect(texts(doc, ".balance-block .b-holder-options .g-sm-text")).toEqual(["Minimum withdrawal amount is $50"]);
  });

  it("an unknown frequency code shows none", () => {
    const doc = load("statements/index");
    applyMoney(doc, "statements/index", { balances: { ...BAL, withdrawalPeriod: "daily" } });
    expect(texts(doc, ".balance-block .v-select__selection")).toEqual([""]);
  });

  it("no data: Statements shows no example figure (dashes, no frequency, no account alerts); Request withdrawal and the frequency select disabled as OF draws them before the balances", () => {
    for (const p of ["statements/index", "statements/earnings", "statements/payouts", "statements/referrals", "statements/stats/earnings"]) {
      const doc = load(p);
      applyMoney(doc, p, {});
      expect(texts(doc, ".b-statements__current-balance__value > span, .b-statements__pending-balance__value > span")).toEqual(["—", "—"]);
      expect(texts(doc, ".balance-block .v-select__selection")).toEqual([""]);
      expect(doc.querySelector(".alert-danger, .m-panel")).toBeNull();
      const off = doc.querySelector<HTMLButtonElement>(".g-btn__wrapper > button")!;
      expect([off.textContent!.trim(), off.disabled, off.title, off.hasAttribute("data-oi-wired")]).toEqual(["Request withdrawal", true, "", true]);
      const select = doc.querySelector(".balance-block .v-select")!;
      expect([select.classList.contains("v-input--is-disabled"), select.getAttribute("title"), select.querySelector("[role='button']"), !!select.querySelector(".v-input__slot[data-oi-wired]")]).toEqual([true, null, null, true]);
    }
  });

  it("the balance box's header collapses and expands it, in either scope", () => {
    const doc = load("statements/earnings");
    applyMoney(doc, "statements/earnings", {});
    const head = doc.querySelector<HTMLButtonElement>(".balance-block > button.g-box__header")!;
    const content = doc.querySelector<HTMLElement>(".balance-block > .g-box__content")!;
    expect(head.hasAttribute("data-oi-wired")).toBe(true);
    head.click();
    const box = head.closest(".g-box")!;
    const icon = head.querySelector(".g-box__collapse-icon svg")!;
    // OF's Balances: v-show on the content, GBoxWrapper's m-roll-state, icon-arrow-down while collapsed.
    expect([content.style.display, box.classList.contains("m-roll-state"), icon.getAttribute("data-icon-name"), icon.querySelector("use")!.getAttribute("href")]).toEqual(["none", true, "icon-arrow-down", "#icon-arrow-down"]);
    applyMoney(doc, "statements/earnings", { balances: BAL }); // a re-apply binds no second handler
    head.click();
    expect([content.style.display, box.classList.contains("m-roll-state"), icon.getAttribute("data-icon-name"), icon.querySelector("use")!.getAttribute("href")]).toEqual(["", false, "icon-arrow-up", "#icon-arrow-up"]);
  });

  it("is ignored on a page without balances", () => {
    const doc = load("statistics/engagement/messages");
    const html = doc.documentElement.innerHTML;
    applyMoney(doc, "statistics/engagement/messages", { balances: BAL });
    expect(doc.documentElement.innerHTML).toBe(html);
  });
});

// Month keys: each month's start, unix seconds (local time, so the titles read the same in every zone).
const sec = (y: number, m: number) => String(new Date(y, m, 1).getTime() / 1000);
const STATS: EarningStats = {
  total: {
    all: { total_gross: 2500, total_net: 2000 },
    subscribes: { total_gross: 100, total_net: 80 },
    tips: { total_gross: 50, total_net: 40 },
    chat_messages: { total_gross: 2350, total_net: 1880 },
  },
  months: {
    [sec(2026, 8)]: { total_gross: 1500, total_net: 1200 },
    [sec(2026, 9)]: { total_gross: 1000, total_net: 800 },
    [sec(2025, 1)]: { total_gross: 0, total_net: 0 },
  },
};
const NOW = new Date(2026, 9, 16, 12, 0);

describe("Earning Statistics", () => {
  const page = "statements/stats/earnings";

  it("all-time net, gross and net per category (absent: $0.00), totals, date range and one row per month, newest first", () => {
    const doc = load(page);
    applyMoney(doc, page, { earningStats: STATS }, NOW);
    expect(texts(doc, ".b-stats-row.m-expanded > .b-stats-row__head .b-stats-row__total-net")).toEqual(["$2,000.00"]);
    const cats = [...doc.querySelectorAll(".b-stats-row__content > .b-stats-row__label:not(.m-total)")].map((r) => [
      r.querySelector(".b-stats-row__name")!.textContent!.trim(),
      ...[...r.querySelectorAll(".b-stats-row__val")].map((v) => v.textContent!.trim()),
    ]);
    expect(cats).toEqual([
      ["Subscriptions", "$100.00", "$80.00"],
      ["Tips", "$50.00", "$40.00"],
      ["Posts", "$0.00", "$0.00"],
      ["Messages", "$2,350.00", "$1,880.00"],
      ["Referrals", "$0.00", "$0.00"],
    ]);
    expect(texts(doc, ".m-total .m-total-item .b-stats-row__val")).toEqual(["$2,500.00", "$2,000.00"]);
    expect(texts(doc, ".b-stats-row.m-expanded .b-date-value")).toEqual(["Feb 1, 2025", "Oct 16, 2026"]);
    expect(doc.querySelector<HTMLButtonElement>(".m-time-period")!.disabled).toBe(true); // no range: all time only
    const months = [...doc.querySelectorAll(".b-stats-wrap > .b-stats-row:not(.m-expanded)")].filter(visible);
    expect(months.map((r) => [r.querySelector(".b-stats-row__month")!.textContent, r.querySelector(".b-stats-row__total-net")!.textContent!.trim()])).toEqual([
      [" October, 2026 ", "$800.00"],
      [" September, 2026 ", "$1,200.00"],
      [" February, 2025 ", "$0.00"],
    ]);
    expect(months.every((r) => r.hasAttribute("data-oi-data"))).toBe(true);
  });

  it("no data: every figure a dash and no month row; no months: all time only; new data replaces; no data restores byte for byte", () => {
    for (const p of [page]) {
      const doc = load(p);
      expect([...doc.querySelectorAll(".b-stats-wrap > .b-stats-row")].filter(visible)).toHaveLength(1);
      expect(new Set(texts(doc, ".b-stats-row__total-net > span, .b-stats-row__val, .b-date-value"))).toEqual(new Set(["—"]));
      const html = doc.documentElement.innerHTML;
      applyMoney(doc, p, { earningStats: {} }, NOW);
      expect([...doc.querySelectorAll(".b-stats-wrap > .b-stats-row")].filter(visible)).toHaveLength(1);
      expect(texts(doc, ".b-stats-row.m-expanded > .b-stats-row__head .b-stats-row__total-net")).toEqual(["$0.00"]);
      applyMoney(doc, p, { earningStats: STATS }, NOW);
      applyMoney(doc, p, { earningStats: { months: { [sec(2026, 9)]: { total_net: 5 } } } }, NOW);
      expect(doc.querySelectorAll("[data-oi-data]")).toHaveLength(1);
      applyMoney(doc, p, {}, NOW);
      expect(doc.documentElement.innerHTML).toBe(html);
    }
  });
});

describe("Earning Statistics: OF's expanded row and chart", () => {
  const page = "statements/stats/earnings";
  const at = (y: number, m: number, d: number) => new Date(y, m, d, 12).getTime() / 1000;
  // OF's months: each category's earnings (gross, net, time), summed per month by OF itself.
  const ITEMS: EarningStats = {
    total: { all: { total_gross: 60, total_net: 48 }, subscribes: { total_gross: 10, total_net: 8 }, tips: { total_gross: 50, total_net: 40 } },
    months: {
      [sec(2026, 9)]: { total_gross: 35, total_net: 28, subscribes: [{ gross: 10, net: 8, time: at(2026, 9, 2) }], tips: [{ gross: 20, net: 16, time: at(2026, 9, 3) }, { gross: 5, net: 4, time: at(2026, 9, 9) }] },
      [sec(2026, 8)]: { total_gross: 25, total_net: 20, tips: [{ gross: 25, net: 20, time: at(2026, 8, 20) }] },
    },
  };
  const head = (doc: Document, title: string) =>
    [...doc.querySelectorAll<HTMLElement>(".b-stats-wrap > .b-stats-row > .b-stats-row__head")].find((h) => visible(h) && h.querySelector(".b-stats-row__month")!.textContent!.trim() === title)!;
  const open = (doc: Document) => [...doc.querySelectorAll(".b-stats-wrap > .b-stats-row.m-expanded")].filter(visible);
  const sums = (doc: Document) =>
    [...open(doc)[0].querySelectorAll(".b-stats-row__content > .b-stats-row__label:not(.m-total)")].map((r) => [...r.querySelectorAll(".b-stats-row__val")].map((v) => v.textContent!.trim()).join(" "));

  it("a month's head expands it alone: its date range, its categories summed from its earnings, its totals; All time's head brings All time back", () => {
    const doc = load(page);
    applyMoney(doc, page, { earningStats: ITEMS }, NOW);
    expect(open(doc).map((r) => r.querySelector(".b-stats-row__month")!.textContent!.trim())).toEqual(["All time"]);
    expect(linesOf(open(doc)[0].querySelector("canvas")!)?.lines).toHaveLength(6); // All time's chart is drawn, not blank
    head(doc, "September, 2026").click();
    expect(linesOf(open(doc)[0].querySelector("canvas")!)?.lines).toHaveLength(6);
    expect(open(doc).map((r) => r.querySelector(".b-stats-row__month")!.textContent!.trim())).toEqual(["September, 2026"]);
    expect(texts(doc, ".b-stats-row__body .b-date-value")).toEqual(["September, 2026", "September, 2026"]);
    expect(sums(doc)).toEqual(["$0.00 $0.00", "$25.00 $20.00", "$0.00 $0.00", "$0.00 $0.00", "$0.00 $0.00"]);
    expect(texts(doc, ".b-stats-row__body .m-total .m-total-item .b-stats-row__val")).toEqual(["$25.00", "$20.00"]);
    expect([...doc.querySelectorAll(".b-stats-row__body")].filter(visible)).toHaveLength(1);
    head(doc, "October, 2026").click();
    expect(sums(doc)).toEqual(["$10.00 $8.00", "$25.00 $20.00", "$0.00 $0.00", "$0.00 $0.00", "$0.00 $0.00"]);
    expect([...doc.querySelectorAll(".b-stats-row__body")].filter(visible)).toHaveLength(1);
    head(doc, "All time").click();
    expect(open(doc).map((r) => r.querySelector(".b-stats-row__month")!.textContent!.trim())).toEqual(["All time"]);
    expect(sums(doc)).toEqual(["$10.00 $8.00", "$50.00 $40.00", "$0.00 $0.00", "$0.00 $0.00", "$0.00 $0.00"]);
    expect(texts(doc, ".b-stats-row__body .b-date-value")).toEqual(["Sep 1, 2026", "Oct 16, 2026"]);
    head(doc, "All time").click(); // OF's head expands; it never collapses
    expect(open(doc)).toHaveLength(1);
  });

  it("a category row picks its line (m-current); a refetch keeps the open month and the pick; no data restores byte for byte", () => {
    const doc = load(page);
    const html = doc.documentElement.innerHTML;
    applyMoney(doc, page, { earningStats: ITEMS }, NOW);
    head(doc, "October, 2026").click();
    open(doc)[0].querySelector<HTMLElement>(".b-stats-row__label.m-tips")!.click();
    expect(texts(doc, ".b-stats-row__body .b-stats-row__label.m-current .b-stats-row__name")).toEqual(["Tips"]);
    applyMoney(doc, page, { earningStats: ITEMS }, NOW);
    expect(open(doc).map((r) => r.querySelector(".b-stats-row__month")!.textContent!.trim())).toEqual(["October, 2026"]);
    expect(texts(doc, ".b-stats-row__body .b-stats-row__label.m-current .b-stats-row__name")).toEqual(["Tips"]);
    applyMoney(doc, page, {}, NOW);
    expect(doc.documentElement.innerHTML).toBe(html);
    head(doc, "All time").click(); // no data: nothing to expand
    expect(doc.documentElement.innerHTML).toBe(html);
  });

  it("the chart: OF's 15 slots to the period's end, each earning's gross in its nearest slot, summed up; the picked line bright", () => {
    const start = new Date(2026, 9, 1).getTime();
    const end = new Date(2026, 10, 1).getTime() - 1;
    const spec = earningsChart([ITEMS.months![sec(2026, 9)]], start, end, "tips");
    expect(spec.labels).toHaveLength(15);
    expect([spec.labels[0], spec.labels[14]]).toEqual(["01 Oct 26", "31 Oct 26"]);
    expect(spec.lines.map((l) => l.title)).toEqual(["Subscriptions", "Tips", "Posts", "Messages", "Referrals", "Streams"]);
    const subs = spec.lines[0].values;
    const tips = spec.lines[1].values;
    expect([subs[0], subs[1], subs[14]]).toEqual([0, 10, 10]); // slots ~2.07 days apart: Oct 2 noon -> slot 1 (Oct 3 01:36), then summed up
    expect([tips[0], tips[3], tips[4], tips[14]]).toEqual([0, 20, 25, 25]); // Oct 3 -> slot 1, Oct 9 -> slot 4
    expect(tips[1]).toBe(20);
    expect(spec.lines.map((l) => l.color)).toEqual(["rgba(33,150,243,0.4)", "#00bcd4", "rgba(236,64,122,0.4)", "rgba(255,112,67,0.4)", "rgba(149,117,205,0.4)", "rgba(255,160,0,0.4)"]);
    expect(spec.lines.every((l) => l.kind === "money")).toBe(true);
  });
});

describe("referral earnings and chargeback ratio", () => {
  it("Statements' Referrals box and its minimum", () => {
    const doc = load("statements/referrals");
    applyMoney(doc, "statements/referrals", { referralEarnings: 42.1, balances: BAL });
    expect(texts(doc, ".g-box__header__inner__value > span")).toEqual(["$42.10"]);
    expect(doc.querySelector(".g-box__header__inner__value > span")!.classList.contains("m-zero-value")).toBe(false);
    expect(texts(doc, ".g-box__header__subtext")[0]).toContain("minimum payout ($50)");
  });

  it("Statistics' Referrals count", () => {
    const doc = load("statistics/statements/referrals/earnings");
    const html = doc.documentElement.innerHTML;
    applyMoney(doc, "statistics/statements/referrals/earnings", { referralEarnings: 3 });
    expect(texts(doc, ".b-referrals-state__count")).toEqual(["$3.00"]);
    applyMoney(doc, "statistics/statements/referrals/earnings", {});
    expect(doc.documentElement.innerHTML).toBe(html);
  });

  it("Referrals' link: OF's ?ref= link with the Creator's id, which Copy link copies; no model: a note asks for one", async () => {
    const doc = load("statements/referrals");
    const html = doc.documentElement.innerHTML;
    const copy = doc.querySelector<HTMLButtonElement>("[at-attr='referrals_url'] button")!;
    expect([copy.hasAttribute("data-oi-wired"), texts(doc, ".b-referrals__copy-description")]).toEqual([true, ["—"]]);
    applyMoney(doc, "statements/referrals", {});
    copy.click();
    expect(doc.getElementById("oi-note")?.textContent).toBe("Select a model to copy its referral link");
    const writeText = vi.fn(() => Promise.resolve());
    Object.defineProperty(doc.defaultView!.navigator, "clipboard", { value: { writeText }, configurable: true });
    applyMoney(doc, "statements/referrals", { meId: 80000112 });
    expect(texts(doc, ".b-referrals__copy-description")).toEqual(["https://onlyfans.com?ref=80000112"]);
    copy.click();
    await Promise.resolve();
    expect(writeText).toHaveBeenCalledWith("https://onlyfans.com?ref=80000112");
    expect(doc.getElementById("oi-note")?.textContent).toBe("Link copied");
    doc.getElementById("oi-note")!.remove();
    applyMoney(doc, "statements/referrals", {});
    expect(doc.documentElement.innerHTML).toBe(html);
  });

  it("Statistics › Referrals prints OF's referral link, not the captured one", () => {
    const doc = load("statistics/statements/referrals/earnings");
    applyMoney(doc, "statistics/statements/referrals/earnings", { meId: 1001, referralEarnings: 0 });
    expect(texts(doc, ".b-referrals-state__copy-url__link")).toEqual(["https://onlyfans.com?ref=1001"]);
    expect(texts(doc, ".b-referrals-state__count")).toEqual(["$0.00"]);
  });
});

describe("statements/index: its Earnings tab lists the transactions", () => {
  it("maps to transactions; a pending item without the pending row shows no status tips", () => {
    expect(partsOf("statements/index")).toEqual(["transactions"]);
    const doc = load("statements/index");
    const html = doc.documentElement.innerHTML;
    // OF's captured rows (app/lib/__fixtures__/of), the second as pending.
    const [sub, msg] = (JSON.parse(readFileSync(resolve(__dirname, "__fixtures__/of/statements-transactions.json"), "utf8")) as { list: Transaction[] }).list;
    applyData(doc, "statements/index", { transactions: [sub, { ...msg, status: "loading", payoutPendingDays: 3 }] });
    const rows = [...doc.querySelectorAll(".b-table tbody > tr")].filter((r) => visible(r) && r.querySelector(".b-table__date"));
    expect(rows.map((r) => [r.querySelector(".b-table__desc .b-field-subscription")!.textContent, r.querySelectorAll(".b-table__status-tip").length])).toEqual([
      ["Subscription from Synth Fan One", 2],
      ["Payment for message from Synth Fan Two", 0],
    ]);
    applyData(doc, "statements/index", {});
    expect(doc.documentElement.innerHTML).toBe(html);
  });
});

// ---------------------------------------------------------------- withdrawals, the payout frequency and Support

const fixture = <T,>(name: string): T => JSON.parse(readFileSync(resolve(__dirname, `__fixtures__/of/statements-${name}.json`), "utf8")) as T;
type Call = { request: { method: string; path: string; body: Record<string, unknown> }; response: { status: number; body: unknown } };
/** OF's live answers to the writes (account balance $4.40, minimum $20): one withdrawal, a frequency change and its restore. */
const WRITES = fixture<Record<"withdrawal" | "periodChange" | "periodRestore", Call>>("payout-writes");
const WEEKLY = fixture<Balances>("balances-weekly");
const RECEIVE = fixture<PayoutUser>("check-receive");
/** OF's live balances at the withdrawal attempt: the captured shape with the account's real $4.40. */
const LIVE: Balances = { ...CAPTURED, payoutAvailable: WRITES.withdrawal.request.body.withdrawal_amount as number };
/** A balance OF lets withdraw: over the minimum (OF's max is still its maxPayoutSumm, $20). */
const RICH: Balances = { ...CAPTURED, payoutAvailable: 25.6 };
const USER: PayoutUser = { canReceiveManualPayout: RECEIVE.canReceiveManualPayout, hasPayoutsIssue: null };
/** The Relay's error for an OF refusal: `_proxy`'s 502 with OF's body. */
const refusal = (c: Call) => new RelayError(502, { detail: { upstream_status: c.response.status, upstream_body: JSON.stringify(c.response.body) } }, "upstream");
const SAT = new Date(2026, 9, 17, 16, 0); // a Saturday

const button = (doc: Document) => doc.querySelector<HTMLButtonElement>(".balance-block .g-btn__wrapper > button")!;
const slot = (doc: Document) => doc.querySelector<HTMLElement>(".balance-block .v-select .v-input__slot")!;
const menu = (doc: Document) => doc.querySelector<HTMLElement>(".balance-block .v-menu__content")!;
const dialog = (doc: Document) => doc.querySelector<HTMLElement>("[data-oi-payouts]");
const alertText = (doc: Document) => doc.querySelector("[data-oi-alert] .dialog_message")?.innerHTML ?? null;
const actions = (over: Partial<MoneyActions> = {}): MoneyActions & { withdraw: ReturnType<typeof vi.fn>; setPeriod: ReturnType<typeof vi.fn> } =>
  ({ withdraw: vi.fn(async () => ({})), setPeriod: vi.fn(async () => WRITES.periodChange.response.body), ...over }) as never;
const type = (doc: Document, v: string) => {
  const input = dialog(doc)!.querySelector<HTMLInputElement>("#tipInput")!;
  input.value = v;
  input.dispatchEvent(new Event("input", { bubbles: true }));
};
const field = (doc: Document) => {
  const d = dialog(doc)!;
  return {
    error: d.querySelector(".v-messages__message")?.textContent ?? null,
    hint: (d.querySelector<HTMLElement>(".v-input__append-outer")!.style.display === "none" ? null : d.querySelector(".g-input__help")!.textContent),
    submit: d.querySelector<HTMLButtonElement>(".modal-footer button[type='submit']")!.disabled,
    max: d.querySelector<HTMLButtonElement>("[data-oi-max]")!.disabled,
  };
};

describe("OF's withdrawal rules (useBalances, ModalPayouts, InputTips)", () => {
  it("Request withdrawal is disabled below the minimum, as for the live $4.40; enabled at or over it for an account that can receive a manual payout", () => {
    expect(withdrawDisabled(LIVE, USER)).toBe(true);
    expect(withdrawDisabled(CAPTURED, USER)).toBe(true);
    expect(withdrawDisabled(RICH, USER)).toBe(false);
    expect(withdrawDisabled({ ...RICH, payoutAvailable: 20 }, USER)).toBe(false);
    expect(withdrawDisabled(RICH, { canReceiveManualPayout: false })).toBe(true);
    expect(withdrawDisabled(RICH, { canReceiveManualPayout: false, hasPayoutsIssue: true })).toBe(false); // it opens Billing Support
    expect(withdrawDisabled(RICH, undefined)).toBe(true);
    expect(withdrawDisabled({}, USER)).toBe(true);
    expect(payoutsDisabled(RICH, USER)).toBe(false);
    expect(payoutsDisabled(RICH, { canReceiveManualPayout: false, hasPayoutsIssue: true })).toBe(true);
  });

  it("the amount's messages: OF's minimum and maximum, none while empty", () => {
    expect(amountError("", 20, 20, "USD")).toBe("");
    expect(amountError("4.4", 20, 20, "USD")).toBe("Minimum $20 USD");
    expect(amountError("25", 20, 20, "USD")).toBe("Maximum $20 USD");
    expect(amountError(20, 20, 20, "USD")).toBe("");
  });

  it("the line under the frequency: OF's minimum for manual payouts, the next payout's day otherwise", () => {
    expect(minSumMessage(CAPTURED, SAT)).toBe("Minimum withdrawal amount is $20");
    expect(minSumMessage(WEEKLY, SAT)).toBe("Once your balance is over $20 next payout will be scheduled on: Oct 19, 2026");
    expect(minSumMessage({ ...WEEKLY, withdrawalPeriod: "monthly" }, SAT)).toBe("Once your balance is over $20 next payout will be scheduled on: Nov 1, 2026");
    expect(minSumMessage({ ...WEEKLY, availableAmount: 25 }, SAT)).toBe("Next payout scheduled on: Oct 19, 2026");
  });

  it("OF's answers: a request's state as OF words it; OF's own error message, else its generic one", () => {
    expect(resultDescription({ list: [{ state: "pending" }, { state: "approved" }] })).toBe("Payout request is being processed<br/>Payout has been processed");
    expect(resultDescription({ list: [{ state: "rejected", rejectReason: "Bank <details>" }] })).toBe("Bank &lt;details&gt;");
    expect(resultDescription(WRITES.periodChange.response.body)).toBe("");
    expect(withdrawError(refusal(WRITES.withdrawal))).toBe("Not enough funds to request a payout");
    expect(withdrawError(new RelayError(404, { detail: "Not Found" }))).toBe("Something went wrong. Please try again later.");
  });
});

describe("Statements' balance box writes", () => {
  it("below the minimum (OF's live $4.40): Request withdrawal disabled, a click opens nothing", () => {
    const doc = load("statements/earnings");
    const a = actions();
    applyMoney(doc, "statements/earnings", { balances: LIVE, payoutUser: USER, actions: a }, SAT);
    expect(texts(doc, ".b-statements__current-balance__value > span")).toEqual(["$4.40"]);
    expect([button(doc).disabled, button(doc).title]).toEqual([true, ""]);
    button(doc).removeAttribute("disabled"); // even if forced: OF's onManualWithdrawalClick checks the rule
    button(doc).click();
    expect(dialog(doc)).toBeNull();
    expect(a.withdraw).not.toHaveBeenCalled();
  });

  it("OF's dialog: the amount's hint and errors, Max, and OF's refusal shown in its alert", async () => {
    const doc = load("statements/earnings");
    const a = actions({ withdraw: vi.fn(async () => Promise.reject(refusal(WRITES.withdrawal))) });
    applyMoney(doc, "statements/earnings", { balances: RICH, payoutUser: USER, actions: a }, SAT);
    expect(button(doc).disabled).toBe(false);
    button(doc).click();
    const d = dialog(doc)!;
    expect(d.querySelector(".modal-title")!.textContent!.trim()).toBe("Manual payouts");
    expect(d.querySelector<HTMLInputElement>("#tipInput")!.placeholder).toBe("Withdrawal amount");
    expect(d.querySelector("[data-oi-max]")!.textContent!.replace(/\s+/g, " ").trim()).toBe("Max $20");
    expect([...d.querySelectorAll(".modal-footer button")].map((b) => b.textContent!.trim())).toEqual(["Cancel", "Request withdrawal"]);
    expect(field(doc)).toEqual({ error: null, hint: "Minimum $20 USD", submit: true, max: false });
    type(doc, "4.40");
    expect(field(doc)).toEqual({ error: "Minimum $20 USD", hint: null, submit: true, max: false });
    type(doc, "25");
    expect(field(doc)).toEqual({ error: "Maximum $20 USD", hint: null, submit: true, max: false });
    d.querySelector<HTMLButtonElement>("[data-oi-max]")!.click();
    expect(field(doc)).toEqual({ error: null, hint: "Minimum $20 USD", submit: false, max: true });
    d.querySelector<HTMLButtonElement>(".modal-footer button[type='submit']")!.click();
    await vi.waitFor(() => expect(alertText(doc)).not.toBeNull());
    expect(a.withdraw).toHaveBeenCalledExactlyOnceWith(20);
    expect(alertText(doc)).toBe("Not enough funds to request a payout");
    expect(dialog(doc)).toBeNull();
    expect(doc.querySelector("[data-oi-alert] .modal-footer button")!.textContent!.trim()).toBe("Close");
    doc.querySelector<HTMLButtonElement>("[data-oi-alert] .modal-footer button")!.click();
    expect(doc.querySelector("[data-oi-alert]")).toBeNull();
  });

  it("OF's success: the new request's state in its alert", async () => {
    const doc = load("statements/earnings");
    // OF's answer lists the request (its shape as OF's /payouts/requests rows, captured: statistics-payout-requests.json), now pending.
    const row = JSON.parse(readFileSync(resolve(__dirname, "__fixtures__/of/statistics-payout-requests.json"), "utf8")).list[0];
    const a = actions({ withdraw: vi.fn(async () => ({ list: [{ ...row, state: "pending" }] })) });
    applyMoney(doc, "statements/earnings", { balances: RICH, payoutUser: USER, actions: a }, SAT);
    button(doc).click();
    type(doc, "20");
    dialog(doc)!.querySelector("form")!.dispatchEvent(new Event("submit", { cancelable: true }));
    await vi.waitFor(() => expect(alertText(doc)).toBe("Payout request is being processed"));
    // Cancel closes the dialog and sends nothing.
    button(doc).click();
    dialog(doc)!.querySelector<HTMLButtonElement>(".modal-footer button[type='button']")!.click();
    expect(dialog(doc)).toBeNull();
    expect(a.withdraw).toHaveBeenCalledTimes(1);
  });

  it("a payouts issue: Request withdrawal opens Billing Support", () => {
    const doc = load("statements/earnings");
    const assign = vi.fn();
    vi.spyOn(window, "location", "get").mockReturnValue({ assign } as unknown as Location);
    applyMoney(doc, "statements/earnings", { balances: RICH, payoutUser: { canReceiveManualPayout: false, hasPayoutsIssue: true }, actions: actions() }, SAT);
    button(doc).click();
    expect(assign).toHaveBeenCalledWith("/of-manager/statements/support");
    expect(dialog(doc)).toBeNull();
    vi.restoreAllMocks();
  });

  it("the frequency select: OF's options open from the select; another one is sent; weekly hides Request withdrawal and shows the next payout's day; disabled while saving", () => {
    const doc = load("statements/earnings");
    const html = doc.documentElement.innerHTML;
    const a = actions();
    applyMoney(doc, "statements/earnings", { balances: CAPTURED, payoutUser: USER, actions: a }, SAT);
    expect([slot(doc).getAttribute("role"), slot(doc).closest(".v-input")!.classList.contains("v-input--is-disabled")]).toEqual(["button", false]);
    expect(menu(doc).style.display).toBe("none");
    slot(doc).click();
    expect([menu(doc).style.display, slot(doc).getAttribute("aria-expanded")]).toEqual(["block", "true"]);
    menu(doc).querySelectorAll<HTMLElement>(".v-list-item")[0].click(); // the current one: nothing sent
    expect([menu(doc).style.display, a.setPeriod.mock.calls]).toEqual(["none", []]);
    slot(doc).click();
    menu(doc).querySelectorAll<HTMLElement>(".v-list-item")[1].click();
    expect(a.setPeriod.mock.calls).toEqual([[WRITES.periodChange.request.body.withdrawalPeriod]]);
    // The hook keeps the new one while it saves (the select disabled), then OF's answer: the balances read weekly.
    applyMoney(doc, "statements/earnings", { balances: WEEKLY, payoutUser: USER, actions: a, periodSaving: true }, SAT);
    expect([slot(doc).getAttribute("role"), slot(doc).closest(".v-input")!.classList.contains("v-input--is-disabled")]).toEqual([null, true]);
    applyMoney(doc, "statements/earnings", { balances: WEEKLY, payoutUser: USER, actions: a }, SAT);
    expect(texts(doc, ".balance-block .v-select__selection")).toEqual(["Weekly payouts"]);
    expect(texts(doc, ".b-statements__min-payout-summ")).toEqual(["Once your balance is over $20 next payout will be scheduled on: Oct 19, 2026"]);
    expect(button(doc).closest(".g-btn__wrapper")!.getAttribute("style")).toBe("display:none");
    expect(options(doc).map((o) => o[2])).toEqual([false, true, false]);
    // Escape and a click elsewhere close the menu.
    slot(doc).click();
    doc.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
    expect(menu(doc).style.display).toBe("none");
    slot(doc).click();
    doc.body.click();
    expect(menu(doc).style.display).toBe("none");
    applyMoney(doc, "statements/earnings", {});
    expect(doc.documentElement.innerHTML).toBe(html);
  });
});

describe("Statements' Support (the header's ?)", () => {
  it("is OF's StatementsSupportLink: a link to Billing Support labelled Support, as OF's router-link to StatementsSupport", () => {
    for (const p of ["statements/earnings", "statements/index", "statements/payouts"]) {
      const doc = load(p);
      const help = [...doc.querySelectorAll<HTMLAnchorElement>(".g-page__header .b-btns-group a, h1 ~ .b-btns-group a")].filter((a) => a.querySelector("[data-icon-name='icon-support']"));
      expect(help.map((a) => [a.getAttribute("href"), a.getAttribute("aria-label"), a.getAttribute("target")])).toEqual([["/of-manager/statements/support", "Support", "_top"]]);
    }
    // OF's Billing Support page, its SupportForm as captured; its Send needs OF's captcha, so it stays disabled with the tooltip.
    const doc = load("statements/support");
    expect(doc.querySelector("h1")!.textContent!.trim()).toBe("Billing Support");
    expect(texts(doc, "form.contact_form ~ p, .g-default-text")[0]).toBe("If you have any questions, please fill out the form below to contact us.");
    const send = [...doc.querySelectorAll<HTMLButtonElement>("form.contact_form button")].find((b) => b.textContent!.trim() === "Send")!;
    expect([send.disabled, send.title]).toEqual([true, "Not available in Inflowwww yet"]);
  });
});

describe("Statistics' sidebar Request withdrawal (Statements', in OF's g-btn__row)", () => {
  const sidebar = (doc: Document) => doc.querySelector<HTMLButtonElement>(".balance-block .g-btn__row > button")!;

  it.each(["statistics/statements/earnings", "statistics/overview/earnings"])("%s: wired, disabled as OF draws it until the balances allow it, then OF's dialog", (page) => {
    const doc = load(page);
    expect([sidebar(doc).disabled, sidebar(doc).title, sidebar(doc).hasAttribute("data-oi-wired")]).toEqual([true, "", true]);
    const a = actions();
    applyMoney(doc, page, { balances: LIVE, payoutUser: USER, actions: a }, SAT);
    expect(sidebar(doc).disabled).toBe(true);
    applyMoney(doc, page, { balances: RICH, payoutUser: USER, actions: a }, SAT);
    expect(sidebar(doc).disabled).toBe(false);
    sidebar(doc).click();
    expect(dialog(doc)!.querySelector(".modal-title")!.textContent!.trim()).toBe("Manual payouts");
  });
});
