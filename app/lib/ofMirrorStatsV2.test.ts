/**
 * The Statistics tabs with the phase-2 Relay reads (omf-statistics-relay), from synthetic fixtures in OF's shapes
 * (app/lib/__fixtures__/of/statistics-*.json), each group with an all-zero period; and today's Relay (the reads 404 or
 * answer `[]`): the generator's honest state stays.
 */
import { readFileSync } from "node:fs";
import type { OfMe } from "./ofMirrorIdentity";
import { promotionText } from "./ofMirrorStatsReach";
import { streakTime } from "./ofMirrorStatsOverview";
import { bindUserLists, drawPair, usersLink, usersRoute } from "./ofMirrorStatsKit";
import { durationText, postStatRows, postStatsProbe, postStatsRoute } from "./ofMirrorStatsPostStat";
import { ELSEWHERE } from "./ofMirrorTooltip";
import { relay, RelayError } from "./relay";
import { resolve } from "node:path";
import { describe, expect, it, vi } from "vitest";
import { PICK_DEFAULTS, applyStats, firstMarker, listRoute, nextParam, periodOf, startOf, statsRoute, type PagedBody, type Picks, type StatsData } from "./ofMirrorStats";
import { barColor, chartSpecOf, chartTooltip, fansChartOf, fansTooltip, linesOf, nextLabel, sectorColors, sectorsOf } from "./ofMirrorChart";

const capture = (p: string) => readFileSync(resolve(__dirname, `../public/of-mirror/pages/${p}.html`), "utf8");
const load = (p: string) => {
  document.documentElement.innerHTML = capture(p);
  return document;
};
const visible = (el: Element) => !el.closest("[style*='display:none'], [style*='display: none']");
const texts = (doc: ParentNode, sel: string) => [...doc.querySelectorAll(sel)].filter(visible).map((e) => e.textContent?.replace(/\s+/g, " ").trim());
const rows = (doc: ParentNode, sel: string) => [...doc.querySelectorAll(`${sel} tbody > tr`)].filter(visible).map((r) => [...r.querySelectorAll(":scope > td")].map((c) => c.textContent!.replace(/\s+/g, " ").trim()));
const NOT_YET = "Not available in Inflowwww yet";
const TZ = "Europe/Ljubljana";
const NOW = new Date("2026-10-17T10:00:00Z");
const fixture = <T = unknown,>(name: string): T => JSON.parse(readFileSync(resolve(__dirname, `__fixtures__/of/statistics-${name}.json`), "utf8")) as T;
const BASE: StatsData = { ...fixture<Record<string, unknown>>("overview"), stats: fixture("payouts-stats"), referralBalance: fixture("referrals-balance"), referralRequests: fixture("referral-requests"), startDate: fixture("start-date") };
const START = startOf(BASE.startDate, TZ);
const D30 = periodOf("d30", NOW, TZ, START);
const ALL = periodOf("all", NOW, TZ, START);
/** A paged source's body as usePaged hands it over. */
const paged = (body: unknown): PagedBody => ({ list: (body as { list?: unknown[]; items?: unknown[]; users?: unknown[] }).list ?? (body as { items: unknown[] }).items ?? (body as { users: unknown[] }).users, hasMore: !!(body as { hasMore?: boolean }).hasMore, loading: false, more: null });
const picks = (p: Partial<Picks> = {}): Picks => ({ ...PICK_DEFAULTS, ...p });
const spec = (doc: Document, sel: string) => chartSpecOf(doc.querySelector<HTMLCanvasElement>(sel)!);

describe("routes with the phase-2 Relay", () => {
  it("Statements: OF's chart filter per tab, its marker paging with its Tips source; today's Relay: offsets", () => {
    expect(statsRoute("earningsChart", D30, { picks: { type: "chat_messages" }, sub: "statements/earnings" })).toBe(
      "/api/of/v2/earnings/chart?filter=messages_count%2Cmessages_amount&start=2026-09-17+00%3A00%3A00&end=2026-10-17+10%3A00%3A00",
    );
    expect(statsRoute("earningsChart", D30, { picks: picks({ type: "tips", tips: "post" }), sub: "statements/earnings" })).toMatch(/filter=tips_post_count%2Ctips_post_amount/);
    expect(statsRoute("earningsChart", D30, { sub: "overview/earnings" })).toMatch(
      /filter=total_amount%2Csubscribes_amount%2Ctips_amount%2Ctips_stream_amount%2Cpost_amount%2Cmessages_amount%2Cref_amount%2Cstream_amount&/,
    );
    // OF's marker: the end in unix seconds (today: as is).
    expect(firstMarker(D30)).toBe(Math.floor(NOW.getTime() / 1000));
    // A past end (September): moved by its UTC offset (+02:00 in Ljubljana), as OF's `c.unix() + 60 * c.utcOffset()`.
    const sep = periodOf("m1", NOW, TZ, START);
    expect(firstMarker(sep)).toBe(Math.floor(sep.end.getTime() / 1000) + 7200);
    expect(listRoute("transactions", D30, { offset: 0 }, { v2: true, picks: picks({ type: "tips", tips: "chat" }) })).toBe(
      `/api/of/v2/payouts/transactions?limit=10&startDate=2026-09-17+00%3A00%3A00&marker=${firstMarker(D30)}&type=tips&tipsSource=chat`,
    );
    expect(listRoute("transactions", D30, { offset: 0, marker: 1791000001 }, { v2: true })).toBe("/api/of/v2/payouts/transactions?limit=10&startDate=2026-09-17+00%3A00%3A00&marker=1791000001");
    expect(listRoute("transactions", D30, { offset: 50 }, { v2: false, picks: { type: "post" } })).toBe("/api/of/v2/payouts/transactions?limit=50&offset=50&type=post");
    expect(nextParam("transactions", { list: [{ id: 1 }], hasMore: true, nextMarker: 1791000001 }, [{}], { v2: true })).toEqual({ offset: 0, marker: 1791000001 });
    expect(nextParam("transactions", { list: [{ id: 1 }], hasMore: false, nextMarker: 1791000001 }, [{}], { v2: true })).toBeUndefined();
    expect(listRoute("chargebacksList", D30, { offset: 10, marker: "1791000000" })).toBe("/api/of/v2/payouts/chargebacks?limit=10&offset=10&marker=1791000000&start=2026-09-17+00%3A00%3A00&end=2026-10-17+10%3A00%3A00");
    expect(listRoute("referredUsers", D30, { offset: 0 })).toMatch(/^\/api\/of\/v2\/users\/me\/referrals\?onlyPerformers=0&offset=0&start=/);
    expect(nextParam("referredCreators", { list: Array(10).fill(0).map((_, i) => ({ id: i })), hasMore: true, marker: "m1" }, [{ list: Array(10).fill(0).map((_, i) => ({ id: i })) }])).toEqual({ offset: 10, marker: "m1" });
  });
  it("Payout Requests and Referral payouts page OF's way (period, offset, marker; 10 a page) only with the phase-1 Relay", () => {
    const range = "start=2026-09-17+00%3A00%3A00&end=2026-10-17+10%3A00%3A00";
    expect(listRoute("payoutRequests", D30, { offset: 0 }, { v2: true, v3: true })).toBe(`/api/of/v2/payouts/requests?limit=10&offset=0&${range}`);
    expect(listRoute("referralRequests", D30, { offset: 10, marker: 1792238001 }, { v2: true, v3: true })).toBe(`/api/of/v2/payouts/requests/referral?limit=10&offset=10&marker=1792238001&${range}`);
    // Older relays drop the period and marker: the whole history by offset, 50 a page (read ahead to the period).
    expect(listRoute("payoutRequests", D30, { offset: 50 }, { v2: true })).toBe("/api/of/v2/payouts/requests?limit=50&offset=50");
    expect(listRoute("referralRequests", D30, { offset: 0 }, {})).toBe("/api/of/v2/payouts/requests/referral?limit=50&offset=0");
    // OF's reply has no hasMore (setStatementsPayoutRequests: a full page has more): the next page carries its marker.
    const real = fixture("payout-requests") as { list: Record<string, unknown>[]; marker: number };
    const full = { list: Array.from({ length: 10 }, (_, i) => ({ ...real.list[0], invoiceId: String(60000100 + i) })), marker: real.marker };
    expect(nextParam("payoutRequests", full, [full], { v2: true, v3: true })).toEqual({ offset: 10, marker: real.marker });
    expect(nextParam("referralRequests", real, [full, real], { v2: true, v3: true })).toBeUndefined();
    // An all-zero period: no rows, no next page.
    expect(nextParam("payoutRequests", { list: [], marker: real.marker }, [{ list: [] }], { v2: true, v3: true })).toBeUndefined();
    // Older relays: a 10-row page is short of their 50, so it ends there.
    expect(nextParam("payoutRequests", full, [full], { v2: true })).toBeUndefined();
  });
});

describe("Statements", () => {
  const earnings = (data: StatsData, type: "total" | "tips" = "tips", x = {}) => {
    const doc = load("statistics/statements/earnings");
    applyStats(doc, "statistics/statements/earnings", { ...BASE, transactions: { list: [], hasMore: false }, ...data }, D30, { ...x, picks: { type } });
    return doc;
  };
  it("Earnings: the type tab's chart (amount over transactions) and OF's summary from it; Tips' sub-tabs once the Relay has them", () => {
    const doc = earnings({ earningsChart: fixture("earnings-chart-tips"), transactions: { list: [{ id: 1, createdAt: "2026-10-08T10:00:00+00:00", amount: 8, fee: 1.6, net: 6.4, status: "done", description: "Synthetic tip" }], hasMore: false } }, "tips", { v2: true });
    const main = spec(doc, ".b-statistics-page-content__wrapper > .b-chart canvas.b-chart__double-line__main")!;
    expect([main.series.title, main.series.kind, main.series.values.reduce((a, b) => a + b, 0)]).toEqual(["Earnings", "money", 12.5]);
    expect(spec(doc, ".b-statistics-page-content__wrapper > .b-chart canvas.b-chart__double-line__aside")!.series.title).toBe("Transactions");
    expect(texts(doc, ".b-statistics-page-content__wrapper > .b-elements-determinant .b-elements-determinant__value")).toEqual(["$12.50 ( $15.63 Gross) 25%"]);
    const subs = [...doc.querySelectorAll<HTMLButtonElement>("[data-oi-tips-tabs] button")];
    expect(subs.map((b) => [b.textContent!.trim(), b.disabled])).toEqual([["All tips", false], ["Profile", false], ["Posts", false], ["Messages", false], ["Streams", false], ["Stories", false]]);
    expect(subs[0].classList.contains("m-current")).toBe(true);
  });
  it("Earnings, an all-zero period: OF's $0.00 summary and a flat chart", () => {
    const doc = earnings({ earningsChart: fixture("earnings-chart-zero"), transactions: { list: [{ id: 1, createdAt: "2026-10-08T10:00:00+00:00", amount: 0, fee: 0, net: 0, status: "done" }], hasMore: false } }, "total", { v2: true });
    expect(texts(doc, ".b-statistics-page-content__wrapper > .b-elements-determinant .b-elements-determinant__value")).toEqual(["$0.00 ( $0.00 Gross)"]);
    expect(spec(doc, ".b-statistics-page-content__wrapper > .b-chart canvas.b-chart__double-line__main")!.series.values.every((v) => v === 0)).toBe(true);
  });
  it("Earnings with today's Relay (`[]` for the chart, no phase-2 reads): no chart, the overview's summary, Tips' sub-tabs disabled", () => {
    const doc = earnings({ earningsChart: [] }, "tips");
    expect(spec(doc, ".b-statistics-page-content__wrapper > .b-chart canvas.b-chart__double-line__main")).toBeUndefined();
    const subs = [...doc.querySelectorAll<HTMLButtonElement>("[data-oi-tips-tabs] button")].slice(1);
    expect(subs.every((b) => b.disabled && b.title === NOT_YET)).toBe(true);
  });
  it("Earnings read short of the period (the read-ahead cap, or a repeated page): neither \"Loading…\" nor OF's \"No data\"", () => {
    const doc = earnings({ transactions: { list: [{ id: 1, createdAt: "2026-10-16T10:00:00+00:00", status: "done" }], hasMore: false, loading: false, more: null, stalled: true } }, "total");
    applyStats(doc, "statistics/statements/earnings", { ...BASE, transactions: { list: [{ id: 1, createdAt: "2026-10-16T10:00:00+00:00", status: "done" }], hasMore: false, loading: false, more: null, stalled: true } }, periodOf("m2", NOW, TZ, START));
    expect(texts(doc, ".b-statements-table .empty-message")).toEqual([NOT_YET]);
    // Paging stops when a page repeats the last (the Relay ignored the page asked), with OF's marker or end date too.
    const page = { list: [{ id: 1, date: "2026-10-09T15:00:00+00:00" }], items: [{ id: 1, date: "2026-10-09T15:00:00+00:00" }], hasMore: true, nextMarker: 1791000001 };
    expect(nextParam("transactions", page, [page, page], { v2: true })).toBeUndefined();
    expect(nextParam("massMessages", page, [page, page], { v2: true })).toBeUndefined();
    expect(nextParam("transactions", page, [page], { v2: true })).toEqual({ offset: 1, marker: 1791000001 });
  });
  it("Chargebacks: OF's disputes table, its summary and chart; none in the period: OF's \"No data\"; a 404: the generator's state", () => {
    const doc = load("statistics/statements/disputes");
    const data = { ...BASE, chargebacks: { chargebacksRatio: 1.5 }, chargebacksList: paged(fixture("chargebacks")), chargebacksChart: fixture("chargebacks-chart") };
    applyStats(doc, "statistics/statements/disputes", data, D30);
    expect(texts(doc, "[data-oi-table='disputes'] thead th")).toEqual(["Dispute date", "Payment date", "Amount", "Fee / Net"]);
    expect(rows(doc, "[data-oi-table='disputes']")).toEqual([
      ["Oct 03, 2026 12:00 pm", "Sep 20, 2026 12:00 pm", "$5.00", "$1.00 $4.00", "Synthetic payment description"],
      ["Oct 01, 2026 10:30 am", "Sep 18, 2026 11:15 pm", "$0.00", "$0.00 $0.00", ""],
    ]);
    expect(texts(doc, ".b-statistics-page-content__wrapper > .empty-message")).toEqual([]);
    expect(texts(doc, "[data-oi-chartbox='disputes'] .b-elements-determinant__value")).toEqual(["$5.00 -50%"]);
    expect(spec(doc, "[data-oi-chartbox='disputes'] canvas.b-chart__double-line__main")!.series.title).toBe("Charged back");
    expect(spec(doc, "[data-oi-chartbox='disputes'] canvas.b-chart__double-line__aside")!.series.title).toBe("Disputes");
    // An all-zero period: no dispute.
    applyStats(doc, "statistics/statements/disputes", { ...data, chargebacks: { chargebacksRatio: 0 }, chargebacksList: paged(fixture("chargebacks-empty")) }, D30);
    expect(texts(doc, ".b-statistics-page-content__wrapper .empty-message")).toEqual(["No data during selected period"]);
    expect(texts(doc, "[data-oi-chartbox='disputes']")).toEqual([]);
    // Today's Relay: no list, no chart (404), a ratio of 1.5%: the generator's text stays.
    applyStats(doc, "statistics/statements/disputes", { ...BASE, chargebacks: { chargebacksRatio: 1.5 } }, D30);
    expect(texts(doc, ".b-statistics-page-content__wrapper .empty-message")).toEqual([NOT_YET]);
  });
  it("Payout Requests: OF's summary and chart while the period has rows; Download invoice only with the phase-2 Relay", () => {
    const doc = load("statistics/statements/payout-request");
    const data = { ...BASE, payoutRequests: fixture("payout-requests"), payoutsChart: fixture("payouts-chart") };
    applyStats(doc, "statistics/statements/payout-request", data, D30);
    expect(texts(doc, "[data-oi-chartbox='payouts']")).toEqual([]); // no request in the last 30 days
    applyStats(doc, "statistics/statements/payout-request", data, ALL, { v2: true });
    expect(texts(doc, "[data-oi-chartbox='payouts'] .b-elements-determinant__value")).toEqual(["$85.23"]);
    expect(spec(doc, "[data-oi-chartbox='payouts'] canvas.b-chart__double-line__main")!.series.title).toBe("Paid out");
    const dl = doc.querySelector<HTMLButtonElement>("[data-oi-table='payouts'] .download-invoice-link")!;
    expect([dl.disabled, dl.getAttribute("title"), dl.getAttribute("data-oi-invoice"), dl.hasAttribute("data-oi-wired")]).toEqual([false, null, "60000000", true]);
    applyStats(doc, "statistics/statements/payout-request", data, ALL);
    expect(doc.querySelector<HTMLButtonElement>("[data-oi-table='payouts'] .download-invoice-link")!.disabled).toBe(true);
  });
  it("Referrals: the chart's $0.00 for an all-zero period; Referred creators and users in place once their reads answer", () => {
    const doc = load("statistics/statements/referrals/earnings");
    const tab = (k: string) => doc.querySelector<HTMLElement>(`[data-oi-pick='ref:${k}']`)!;
    applyStats(doc, "statistics/statements/referrals/earnings", BASE, D30);
    expect([tab("creators"), tab("users")].map((b) => [b.hasAttribute("disabled"), b.getAttribute("title")])).toEqual([[true, NOT_YET], [true, NOT_YET]]);
    const data = { ...BASE, referralsChart: fixture("referrals-chart-zero"), referredCreators: paged(fixture("referred-creators")), referredUsers: paged(fixture("referred-empty")) };
    applyStats(doc, "statistics/statements/referrals/earnings", data, D30);
    expect(texts(doc, ".b-elements-determinant__value.m-inline")).toEqual(["$0.00"]);
    expect(spec(doc, "canvas.b-chart__double-line__aside")!.series.title).toBe("Referrals");
    expect([tab("creators"), tab("users")].map((b) => b.hasAttribute("disabled"))).toEqual([false, false]);
    applyStats(doc, "statistics/statements/referrals/earnings", data, D30, { picks: picks({ ref: "creators" }) });
    expect(tab("creators").classList.contains("m-current")).toBe(true);
    expect(texts(doc, "[data-oi-table='referred'] thead th")).toEqual(["Name", "Joined", "Joined / Earnings"]);
    expect(rows(doc, "[data-oi-table='referred']")).toEqual([
      ["SC Synthetic Creator F @u_synthetic_f", "Sep 1, 2026", "$12.40"],
      ["u900010 @u900010", "Aug 15, 2026", "$0.00"],
    ]);
    expect(texts(doc, ".b-section-title.m-size-sm")).toEqual([]); // the referral payouts' notice is the Earnings tab's
    applyStats(doc, "statistics/statements/referrals/earnings", data, D30, { picks: picks({ ref: "users" }) });
    expect(rows(doc, "[data-oi-table='referred']")).toEqual([]);
    expect(texts(doc, ".empty-message")).toContain("No data during selected period");
  });
  it("the sidebar: OF's own rows from its category charts, each with its line in OF's colour; an all-zero period: OF's clean state", () => {
    const doc = load("statistics/statements/payout-request");
    applyStats(doc, "statistics/statements/payout-request", { ...BASE, earningsSide: fixture("earnings-side") }, D30, { v2: true });
    const rows = [...doc.querySelectorAll<HTMLElement>(".l-wrapper__sidebar [data-oi-pick^='type:']")].filter(visible);
    expect(rows.map((r) => [r.getAttribute("data-oi-pick"), r.textContent!.replace(/\s+/g, " ").trim()])).toEqual([
      ["type:total", "Total $12.00 20%"], ["type:subscribes", "Subscriptions $8.00 -10%"], ["type:tips", "Tips $4.00"],
    ]);
    const line = chartSpecOf(rows[1].querySelector("canvas")!)!;
    expect([line.series.color, line.series.values, line.ticks]).toEqual(["#7CB342", [0, 8, 0], 0]);
    expect(texts(doc, "[data-oi-earnings-empty]")).toEqual([]);
    applyStats(doc, "statistics/statements/payout-request", { ...BASE, earningsSide: fixture("earnings-side-zero") }, D30, { v2: true });
    expect([...doc.querySelectorAll(".l-wrapper__sidebar [data-oi-pick^='type:']")].filter(visible)).toEqual([]);
    expect(doc.querySelector<HTMLElement>("[data-oi-earnings-empty]")!.style.display).toBe("");
  });
});

describe("Overview", () => {
  const overview = (data: StatsData, x = {}) => {
    const doc = load("statistics/overview/earnings");
    applyStats(doc, "statistics/overview/earnings", { ...BASE, ...data }, D30, { ...x });
    return doc;
  };
  const sums = (doc: Document) => texts(doc, ".m-overview-earnings-table .b-stats-row__label").map((t) => t!.replace(/\s+/g, " "));
  it("Earnings: OF's radios pick the chart's category; the period's sums per category from the chart", () => {
    const doc = overview({ earningsChart: fixture("earnings-chart-overview") }, { picks: picks({ row: "chat_messages" }) });
    expect(sums(doc)).toEqual([
      "Total $24.00 $19.20", "Subscriptions $0.00 $0.00", "Tips $0.00 $0.00", "Stream tips $0.00 $0.00",
      "Posts $0.00 $0.00", "Messages $24.00 $19.20", "Referrals $0.00 $0.00", "Streams $0.00 $0.00",
    ]);
    const radios = [...doc.querySelectorAll<HTMLInputElement>(".m-overview-earnings-table input[type='radio']")];
    expect(radios.map((r) => [r.name, r.disabled, r.checked])).toEqual([
      ["total", false, false], ["subscribes", false, false], ["tips", false, false], ["tips_stream", false, false],
      ["post", false, false], ["chat_messages", false, true], ["ref", false, false], ["stream", false, false],
    ]);
    expect(radios[5].closest("[data-oi-pick]")!.getAttribute("data-oi-pick")).toBe("row:chat_messages");
    const c = spec(doc, ".b-chart__double-line__base__wrapper canvas")!;
    expect([c.series.title, c.series.values.reduce((a, b) => a + b, 0)]).toEqual(["Messages", 24]);
    expect(texts(doc, ".m-expanded > .b-stats-wrap > .b-stats-row > .b-stats-row__head .b-stats-row__total-net")).toEqual(["$19.20"]);
  });
  it("Earnings, an all-zero period: $0.00 everywhere and a flat Total chart; today's Relay (`[]`): radios disabled, no chart", () => {
    let doc = overview({ earningsChart: fixture("earnings-chart-overview-zero") });
    expect(sums(doc).every((t) => t!.endsWith("$0.00 $0.00"))).toBe(true);
    expect(spec(doc, ".b-chart__double-line__base__wrapper canvas")!.series.values.every((v) => v === 0)).toBe(true);
    doc = overview({ earningsChart: [] });
    expect([...doc.querySelectorAll<HTMLInputElement>(".m-overview-earnings-table input[type='radio']")].every((r) => r.disabled && r.title === NOT_YET)).toBe(true);
    expect(spec(doc, ".b-chart__double-line__base__wrapper canvas")).toBeUndefined();
  });
  it("Top highlights: OF's Top Message, Top Stream and Top Fan cards with their tabs; nothing for any tab: OF's empty text", () => {
    const doc = load("statistics/overview/top-highlights");
    const data = { ...BASE, topMessage: fixture("top-message"), topStream: fixture("top-stream"), topFan: fixture("top-fan"), topPost: { purchases: null } };
    applyStats(doc, "statistics/overview/top-highlights", data, D30, { picks: picks({ fan: "messages" }) });
    const card = (t: string) => doc.querySelector(`[data-oi-top='${t}']`)!;
    expect(texts(card("Top Message"), ".b-top-statistic__header__date, .b-top-statistic__text, .b-summary-list__item")).toEqual(["Oct 4, 2026, 02:00 pm", "Synthetic top message", "$15.00 purchases", "14 views"]);
    expect(card("Top Message").querySelector<HTMLButtonElement>(".b-top-statistic__btns button")!.disabled).toBe(true); // UNSEND: phase 5
    const tabs = (t: string) => [...card(t).querySelectorAll<HTMLButtonElement>(".b-tabs__nav__link")].map((b) => `${b.textContent!.trim()}${b.disabled ? " (off)" : ""}${b.classList.contains("m-current") ? " *" : ""}`);
    expect(tabs("Top Stream")).toEqual(["Purchases *", "Tips", "Viewers (off)", "Likes (off)", "Comments (off)"]);
    expect(texts(card("Top Stream"), "table tr")).toEqual(["Viewers 12 ($0.00)", "Likes 4", "Comments 2", "Tips 1 ($5.00)"]);
    expect(tabs("Top Fan")).toEqual(["Total", "Subscriptions", "Tips (off)", "Messages *"]);
    expect(texts(card("Top Fan"), "tbody td, tfoot td")).toEqual(["SF Synthetic Fan B @u_synthetic_b", "$9.99 3 months", "Total", "$5.00"]);
    // An all-zero period: no item for any tab.
    const empty = fixture("top-empty");
    applyStats(doc, "statistics/overview/top-highlights", { ...data, topMessage: empty, topStream: empty, topFan: empty }, D30);
    expect(doc.querySelector("[data-oi-top]")).toBeNull();
    expect(texts(doc, ".b-statistics-page-content .b-clean-state .empty-message")).toEqual(["No Post activity during selected period", "No Message activity during selected period", "No Streaming activity during selected period", "No Fans yet"]);
    // Today's Relay: the reads 404 (absent): the generator's clean states.
    applyStats(doc, "statistics/overview/top-highlights", BASE, D30);
    expect(texts(doc, ".b-statistics-page-content .b-clean-state__title")).toEqual(["Top Post", "Top Message", "Top Stream", "Top Fan"]);
  });
  it("Activity Streak reads this month up to now, whatever period the other tabs picked", () => {
    expect(statsRoute("streaks", periodOf("y2025", NOW, TZ, null), { tz: TZ })).toBe("/api/of/v2/streaks?start=2026-10-01+00%3A00%3A00&end=2026-10-17+12%3A00%3A00");
    // The month switch: an earlier month to its last second; across a year.
    expect(statsRoute("streaks", D30, { tz: TZ, picks: picks({ smonth: "1" }) })).toBe("/api/of/v2/streaks?start=2026-09-01+00%3A00%3A00&end=2026-09-30+23%3A59%3A59");
    expect(statsRoute("streaks", D30, { tz: TZ, picks: picks({ smonth: "10" }) })).toBe("/api/of/v2/streaks?start=2025-12-01+00%3A00%3A00&end=2025-12-31+23%3A59%3A59");
    // Longest streak's earnings: the overview's for the top streak's dates; no top streak: not read.
    expect(statsRoute("streakSummary", D30, { top: fixture("streaks-top") })).toBe("/api/of/v2/users/me/stats/overview?by=earnings&start=2026-07-01+08%3A00%3A00&end=2026-07-12+20%3A00%3A00");
    expect(statsRoute("streakSummary", D30, { top: {} })).toBe("");
  });
  it("Activity Streak: the month switch (back to the Creator's first month, not past this one) and the Longest streak tab", () => {
    const doc = load("statistics/overview/streaks");
    const data = { ...BASE, streaks: fixture("streaks"), streaksTop: fixture("streaks-top"), todayActivity: fixture("today-activity"), streakSummary: fixture("streak-summary") };
    applyStats(doc, "statistics/overview/streaks", data, D30, { v2: true });
    const [prev, next] = [...doc.querySelectorAll<HTMLButtonElement>("[data-oi-streak-month]")];
    expect([prev.disabled, prev.title, prev.getAttribute("data-oi-pick"), next.disabled, next.classList.contains("m-gray")]).toEqual([false, "", "smonth:1", true, true]);
    applyStats(doc, "statistics/overview/streaks", { ...data, streaks: fixture("streaks-empty") }, D30, { v2: true, picks: picks({ smonth: "1" }) });
    expect(texts(doc, ".b-streaks-swither__time")).toEqual(["September 2026"]);
    expect([prev.getAttribute("data-oi-pick"), next.disabled, next.getAttribute("data-oi-pick")]).toEqual(["smonth:2", false, "smonth:0"]);
    const days = [...doc.querySelectorAll(".v-calendar-weekly__day:not(.v-outside) .v-calendar-weekly__day-label span")].filter(visible);
    expect([days.length, days[0].textContent]).toEqual([30, "1"]);
    // The Creator's first month: no going back.
    applyStats(doc, "statistics/overview/streaks", data, D30, { v2: true, picks: picks({ smonth: "61" }) });
    expect([texts(doc, ".b-streaks-swither__time")[0], prev.disabled]).toEqual(["September 2021", true]);
    // Longest streak.
    const tabs = [...doc.querySelectorAll<HTMLButtonElement>("[data-oi-pick^='stab:']")];
    expect(tabs.map((b) => [b.disabled, b.title])).toEqual([[false, ""], [false, ""]]);
    applyStats(doc, "statistics/overview/streaks", data, D30, { v2: true, picks: picks({ stab: "top" }) });
    expect(tabs.map((b) => b.classList.contains("m-current"))).toEqual([false, true]);
    expect(doc.querySelector<HTMLElement>("[data-oi-streaks] .b-datepicker-wrapper")!.style.display).toBe("none");
    expect(texts(doc, "[data-oi-streak-top] p")).toEqual(["Your longest streak was on Jul 01, 2026 - Jul 12, 2026. During this period you were active 11 days, with:"]);
    expect(rows(doc, "[data-oi-streak-top]")).toEqual([["Created posts", "3"], ["Published stories", "5"], ["Replies to followers", "8"], ["Time in live streaming", "0min 0sec"]]);
    expect(texts(doc, "[data-oi-streak-top] tfoot tr")).toEqual(["Total earnings $24.50 12.5%"]);
    expect(doc.querySelector("[data-oi-streak-top] tfoot .b-statistics-level.m-level-down")).not.toBeNull();
    // No top streak: Longest disabled as OF's (no tooltip), Current shown.
    applyStats(doc, "statistics/overview/streaks", { ...data, streaksTop: fixture("streaks-top-empty") }, D30, { v2: true, picks: picks({ stab: "top" }) });
    expect([tabs[1].disabled, tabs[1].title, tabs[0].classList.contains("m-current")]).toEqual([true, "", true]);
    expect(doc.querySelector("[data-oi-streak-top]")).toBeNull();
    expect([streakTime(3725), streakTime(59)]).toEqual(["1h 2min", "0min 59sec"]);
  });
  it("Activity Streak: OF's counts and this month's calendar with the streak days; none: zeros; today's Relay: the clean state", () => {
    const doc = load("statistics/overview/streaks");
    applyStats(doc, "statistics/overview/streaks", { ...BASE, streaks: fixture("streaks"), streaksTop: fixture("streaks-top"), todayActivity: fixture("today-activity") }, D30);
    expect(texts(doc, "[data-oi-streaks] .b-streak-tab__count")).toEqual(["6", "12"]); // 5 days + today; the top one's 11 + a rest day
    expect(texts(doc, ".b-streaks-swither__time")).toEqual(["October 2026"]);
    const marked = [...doc.querySelectorAll(".v-calendar-weekly__day-label span[class*='vc-marked']")].filter(visible).map((s) => `${s.textContent} ${s.className}`);
    expect(marked).toEqual([
      "3 vc-marked-day vc-marked-single", "12 vc-marked-day vc-range-start m-active-streak", "13 vc-marked-day", "14 vc-marked-day",
      "15 vc-marked-day", "16 vc-marked-day", "17 vc-marked-day vc-range-end",
    ]);
    expect(texts(doc, "[data-oi-streaks-clean]")).toEqual([]);
    applyStats(doc, "statistics/overview/streaks", { ...BASE, streaks: fixture("streaks-empty"), streaksTop: fixture("streaks-top-empty"), todayActivity: fixture("today-activity-none") }, D30);
    expect(texts(doc, "[data-oi-streaks] .b-streak-tab__count")).toEqual(["0", "0"]);
    expect(doc.querySelectorAll(".v-calendar-weekly__day-label span[class*='vc-marked']").length).toBe(0);
    applyStats(doc, "statistics/overview/streaks", BASE, D30);
    expect(texts(doc, "[data-oi-streaks-clean] .empty-message")).toEqual([NOT_YET]);
  });
});

describe("Engagement", () => {
  const OV = fixture<Record<string, unknown>>("overview");
  it("routes: Messages OF's way (10 a page back from the last date; a search by offset), Posts by offset, Streaming / Stories by tab", () => {
    const x = { v2: true, picks: picks({ msg: "direct" }) };
    expect(listRoute("massMessages", D30, { offset: 0 }, { ...x })).toBe("/api/of/v2/users/me/stats/messages/direct?startDate=2026-09-17+00%3A00%3A00&endDate=2026-10-17+10%3A00%3A00&limit=10&offset=0");
    expect(nextParam("massMessages", { hasMore: true, items: [{ id: 1, date: "2026-10-09T15:00:00+00:00" }] }, [{}], x)).toEqual({ offset: 0, endDate: "2026-10-09 15:00:00" });
    expect(listRoute("massMessages", D30, { offset: 0, endDate: "2026-10-09 15:00:00" }, { ...x })).toMatch(/endDate=2026-10-09\+15%3A00%3A00&limit=10&offset=0$/);
    const q = { v2: true, picks: picks({ q: "synth" }) };
    expect(listRoute("massMessages", D30, { offset: 10 }, { ...q })).toMatch(/\/messages\/group\?.*&limit=10&offset=10&query=synth$/);
    expect(nextParam("massMessages", { hasMore: true, items: Array(10).fill(0).map((_, i) => ({ id: i, date: "2026-10-09T15:00:00+00:00" })) }, [{ items: Array(10).fill(0) }], q)).toEqual({ offset: 10 });
    expect(listRoute("massMessages", D30, { offset: 0 }, { v2: true, picks: picks({ q: "ab" }) })).not.toMatch(/query=/); // OF searches from 3 characters
    expect(listRoute("massMessages", D30, { offset: 50 })).toMatch(/\/messages\/group\?.*&limit=50&offset=50$/); // today's Relay
    expect(listRoute("postsTop", D30, { offset: 10 }, { v2: true, picks: { by: "views" } })).toMatch(/^\/api\/of\/v2\/posts\/top\?by=views&limit=10&offset=10&start=/);
    expect(nextParam("postsTop", { items: [{ id: 1 }], hasMore: true }, [{}], {})).toBeUndefined(); // today's Relay: its 50 at once
    expect(statsRoute("postsChart", D30, { v2: true, picks: { by: "likes" } })).toMatch(/^\/api\/of\/v2\/posts\/chart\?by=likes&start=/);
    expect(statsRoute("streamsChart", D30, { picks: picks({ streams: "tips" }) })).toMatch(/^\/api\/of\/v2\/streams\/chart\?by=tips&start=/);
    expect(listRoute("storiesTop", D30, { offset: 4 }, { picks: picks({ stories: "views" }) })).toMatch(/^\/api\/of\/v2\/stories\/top\?by=views&limit=4&offset=4&start=/);
  });
  it("Messages: the tabs and search with the phase-2 Relay, OF's chart and summary for the tab, a row's purchases open its buyers", () => {
    const doc = load("statistics/engagement/messages");
    const data = { ...BASE, ...OV, massMessages: paged(fixture("messages-direct")), messagesChart: fixture("messages-chart-direct") };
    applyStats(doc, "statistics/engagement/messages", data, D30, { v2: true, picks: picks({ msg: "direct" }) });
    const tabs = [...doc.querySelectorAll<HTMLButtonElement>("[data-oi-pick^='msg:']")];
    expect(tabs.map((b) => [b.textContent!.trim(), b.disabled, b.classList.contains("m-current")])).toEqual([["Mass messages", false, false], ["Direct messages", false, true]]);
    expect(doc.querySelector<HTMLInputElement>("[data-oi-search] input")!.disabled).toBe(false);
    expect(texts(doc, ".b-statistics-page-content__wrapper > .b-elements-determinant__value")).toEqual(["2 messages $9.98 12.5%"]);
    expect(spec(doc, ".b-statistics-page-content__wrapper > .b-chart canvas.b-chart__double-line__main")!.series.title).toBe("Purchases");
    expect(spec(doc, ".b-statistics-page-content__wrapper > .b-chart canvas.b-chart__double-line__aside")!.series.title).toBe("Messages");
    const buyers = doc.querySelector<HTMLElement>("[data-oi-users]")!;
    expect([buyers.getAttribute("data-oi-users"), buyers.textContent!.trim()]).toEqual(["buyers:55001:0", "2"]);
    expect(doc.querySelectorAll("[data-oi-users]").length).toBe(1); // the free message has none
    buyers.click();
    expect(texts(doc, "#oi-users .modal-title")).toEqual(["Message buyers"]);
    doc.getElementById("oi-users")!.remove();
    // An all-zero period.
    applyStats(doc, "statistics/engagement/messages", { ...data, massMessages: paged({ items: [], hasMore: false }), messagesChart: fixture("messages-chart-zero") }, D30, { v2: true });
    expect(texts(doc, ".b-statistics-page-content__wrapper > .b-elements-determinant__value")).toEqual(["0 messages $0.00"]);
    expect(texts(doc, ".b-statistics-page-content__wrapper .empty-message")).toEqual(["No data during selected period"]);
  });
  it("Messages with today's Relay: tabs and search disabled, the overview's summary and chart", () => {
    const doc = load("statistics/engagement/messages");
    applyStats(doc, "statistics/engagement/messages", { ...BASE, ...OV, massMessages: paged(fixture("messages-group")) }, D30);
    expect([...doc.querySelectorAll<HTMLButtonElement>("[data-oi-pick^='msg:']")].every((b) => b.disabled && b.title === NOT_YET)).toBe(true);
    expect(doc.querySelector<HTMLInputElement>("[data-oi-search] input")!.disabled).toBe(true);
    expect(doc.querySelector("[data-oi-users]")).toBeNull();
    expect(spec(doc, ".b-statistics-page-content__wrapper > .b-chart canvas.b-chart__double-line__main")!.series.title).toBe("Mass messages purchases");
  });
  it("Posts: a chip's own summary and chart with the phase-2 Relay (Views: views over posts); an all-zero period: 0 views", () => {
    const doc = load("statistics/engagement/posts");
    const data = { ...BASE, ...OV, postsTop: paged(fixture("posts-top")), postsChart: fixture("posts-chart-views") };
    applyStats(doc, "statistics/engagement/posts", data, D30, { v2: true, picks: { by: "views" } });
    expect(texts(doc, "[data-oi-posts-summary]")).toEqual(["1 post 3 views"]);
    expect(spec(doc, "[data-oi-posts-chart] canvas.b-chart__double-line__main")!.series.title).toBe("Views");
    expect(spec(doc, "[data-oi-posts-chart] canvas.b-chart__double-line__aside")!.series.title).toBe("Posts");
    applyStats(doc, "statistics/engagement/posts", { ...data, postsChart: fixture("posts-chart-views-zero") }, D30, { v2: true, picks: { by: "views" } });
    expect(texts(doc, "[data-oi-posts-summary]")).toEqual(["0 posts 0 views"]);
    applyStats(doc, "statistics/engagement/posts", { ...data, postsChart: fixture("posts-chart") }, D30, { picks: { by: "views" } }); // today's Relay
    expect(texts(doc, "[data-oi-posts-summary]")).toEqual([]);
  });
  it("Posts: no post in the period (read through usePaged): OF's \"No Post activity\"; more to read: no claim", () => {
    const doc = load("statistics/engagement/posts");
    applyStats(doc, "statistics/engagement/posts", { ...BASE, ...OV, postsTop: paged({ items: [], hasMore: false }), topPost: fixture("top-empty") }, D30);
    expect(texts(doc, ".b-statistics-page-content__wrapper > .empty-message")).toEqual(["No Post activity during selected period"]);
    applyStats(doc, "statistics/engagement/posts", { ...BASE, ...OV, postsTop: paged({ items: [], hasMore: true }) }, D30);
    expect(texts(doc, ".b-statistics-page-content__wrapper > .empty-message")).toEqual([NOT_YET]);
  });
  it("Streaming: OF's tabs, cards, summary and chart; Viewers and Tips open their lists; none: OF's empty text", () => {
    const doc = load("statistics/engagement/streaming");
    const data = { ...BASE, ...OV, streamsTop: paged(fixture("streams-top")), streamsChart: fixture("streams-chart-tips") };
    applyStats(doc, "statistics/engagement/streaming", data, D30, { v2: true, picks: picks({ streams: "tips" }) });
    expect([...doc.querySelectorAll<HTMLButtonElement>("[data-oi-pick^='streams:']")].map((b) => `${b.textContent!.trim()}${b.classList.contains("m-current") ? " *" : ""}${b.disabled ? " (off)" : ""}`)).toEqual(["Purchases", "Tips *", "Viewers", "Likes", "Comments"]);
    const cards = [...doc.querySelectorAll("[data-oi-list='streams'] > .b-top-statistic")];
    expect(cards.map((c) => texts(c, "tr"))).toEqual([
      ["Viewers 2 ($0.00)", "Likes 1", "Comments 0", "Tips 1 ($5.00)"],
      ["Viewers 0 ($0.00)", "Likes 0", "Comments 0", "Tips 0 ($0.00)"],
    ]);
    expect(texts(cards[0], ".b-top-statistic__header__date")).toEqual(["Oct 10, 2026, 10:00 pm"]);
    expect([...cards[0].querySelectorAll("[data-oi-users]")].map((l) => l.getAttribute("data-oi-users"))).toEqual(["streams:57001:0", "streams:57001:1"]);
    expect(texts(doc, "[data-oi-summary='streams']")).toEqual(["0h:40m $5.00"]);
    expect(spec(doc, "[data-oi-chart='streams'] canvas.b-chart__double-line__aside")!.series.kind).toBe("duration");
    applyStats(doc, "statistics/engagement/streaming", { ...data, streamsTop: paged(fixture("list-empty")), streamsChart: fixture("streams-chart-zero") }, D30, { v2: true });
    expect(texts(doc, ".b-statistics-page-content__wrapper > .empty-message")).toEqual(["No Streaming activity during selected period"]);
    expect(texts(doc, "[data-oi-chart='streams'], [data-oi-summary='streams']")).toEqual([]);
  });
  it("Stories: OF's cards, summary and chart for the tab; today's Relay: tabs disabled, the generator's state", () => {
    const doc = load("statistics/engagement/stories");
    applyStats(doc, "statistics/engagement/stories", { ...BASE, ...OV, storiesTop: paged(fixture("stories-top")), storiesChart: fixture("stories-chart-views") }, D30, { v2: true, picks: picks({ stories: "views" }) });
    expect(texts(doc, "[data-oi-list='stories'] tr")).toEqual(["Viewers 4", "Likes 2", "Comments 1", "Tips 0 ($0.00)"]);
    expect(texts(doc, "[data-oi-summary='stories']")).toEqual(["1 story 4 viewers"]);
    applyStats(doc, "statistics/engagement/stories", { ...BASE, ...OV }, D30);
    expect([...doc.querySelectorAll<HTMLButtonElement>("[data-oi-pick^='stories:']")].every((b) => b.disabled)).toBe(true);
    expect(texts(doc, "[data-oi-list='stories']")).toEqual([]);
  });
});

describe("Reach", () => {
  const OV = fixture<Record<string, unknown>>("overview");
  it("routes: the visitors chip and OF's limit 0 with the phase-2 Relay; Tracking links' sort", () => {
    expect(statsRoute("profileStats", D30, { v2: true, picks: picks({ visitors: "guests", countries: "all" }) })).toMatch(/^\/api\/of\/v2\/users\/me\/profile\/stats\?by=guests&limit=0&start=/);
    expect(statsRoute("profileStats", D30, { picks: { countries: "all" } })).toMatch(/^\/api\/of\/v2\/users\/me\/profile\/stats\?limit=50&start=/); // today's Relay
    expect(listRoute("campaignsList", D30, { offset: 10 }, { picks: picks({ csort: "subscribers_counts:asc" }) })).toBe(
      "/api/of/v2/campaigns/stats?limit=10&offset=10&field=subscribers_counts&sort=asc&start=2026-09-17+00%3A00%3A00&end=2026-10-17+10%3A00%3A00",
    );
    expect(listRoute("promotionsList", D30, { offset: 0 })).toMatch(/^\/api\/of\/v2\/promotions\/stats\?limit=10&offset=0&start=/);
  });
  it("Profile visitors: All / Guests / Users in place with the phase-2 Relay; disabled with today's", () => {
    const doc = load("statistics/reach/profile-visitors");
    applyStats(doc, "statistics/reach/profile-visitors", { ...BASE, ...OV, profileStats: fixture("profile-stats-guests") }, D30, { v2: true, picks: picks({ visitors: "guests" }) });
    expect([...doc.querySelectorAll<HTMLButtonElement>("[data-oi-pick^='visitors:']")].map((b) => [b.textContent!.trim(), b.disabled, b.classList.contains("m-current")])).toEqual([["All", false, false], ["Guests", false, true], ["Users", false, false]]);
    applyStats(doc, "statistics/reach/profile-visitors", { ...BASE, ...OV, profileStats: fixture("profile-stats") }, D30);
    expect([...doc.querySelectorAll<HTMLButtonElement>("[data-oi-pick^='visitors:']")].every((b) => b.disabled && b.title === NOT_YET)).toBe(true);
  });
  it("Promotions: OF's table, summary and chart; an all-zero period (none): OF's empty text; a 404: the generator's", () => {
    const doc = load("statistics/reach/promotions");
    applyStats(doc, "statistics/reach/promotions", { ...BASE, ...OV, promotionsList: paged(fixture("promotions-list")), promotionsChart: fixture("promotions-chart") }, D30, { me: { subscribePrice: 10, username: "u_creator" } as OfMe });
    expect(texts(doc, "[data-oi-table='promotions'] thead th")).toEqual(["Start date", "End date", "Offer limit", "Claimed"]);
    expect(rows(doc, "[data-oi-table='promotions']")).toEqual([
      ["Limited offer - Free trial for 7 days! Active", "Oct 1, 2026", "Unlimited", "10", "1"],
      ["Limited offer - 70% off for 30 days! Limit ended", "Sep 20, 2026", "Oct 5, 2026", "0", "5"],
      ["Limited offer - 51% off for 31 days! Expired", "Sep 12, 2026", "Sep 12, 2026", "–", "0"],
    ]);
    expect(doc.querySelector("[data-oi-table='promotions'] [data-oi-users]")).toBeNull(); // the claim lists' Relay is not there
    expect(doc.querySelector("[data-oi-table='promotions'] tbody a.g-page__link")!.getAttribute("href")).toBe("/of-manager/settings/subscription/promotion-campaign");
    expect(texts(doc, "[data-oi-summary='promotions']")).toEqual(["0 claims 4 offers 100%"]);
    expect(spec(doc, "[data-oi-chart='promotions'] canvas.b-chart__double-line__main")!.series.title).toBe("Claims");
    applyStats(doc, "statistics/reach/promotions", { ...BASE, ...OV, promotionsList: paged(fixture("list-empty")) }, D30);
    expect(texts(doc, ".b-statistics-page-content__wrapper > .empty-message")).toEqual(["No Profile activity during selected period"]);
    applyStats(doc, "statistics/reach/promotions", { ...BASE, ...OV }, D30);
    expect(texts(doc, ".b-statistics-page-content__wrapper > .empty-message")).toEqual([NOT_YET]);
  });
  it("Trial links: OF's row (name, length, Expired) and a flat chart for an all-zero period", () => {
    const doc = load("statistics/reach/trial-links");
    applyStats(doc, "statistics/reach/trial-links", { ...BASE, ...OV, trialsList: paged(fixture("trials-list")), trialsChart: fixture("trials-chart-zero") }, D30);
    expect(rows(doc, "[data-oi-table='trials']")).toEqual([["Synthetic trial (2 months free trial) Expired", "Sep 25, 2026", "Oct 10, 2026", "–", "2"]]);
    expect(texts(doc, "[data-oi-summary='trials']")).toEqual(["0 claims 1 Trials 100%"]);
    expect(spec(doc, "[data-oi-chart='trials'] canvas.b-chart__double-line__main")!.series.values.every((v) => v === 0)).toBe(true);
  });
  it("Tracking links: OF's table with its sortable headers, summary and chart", () => {
    const doc = load("statistics/reach/tracking-links");
    applyStats(doc, "statistics/reach/tracking-links", { ...BASE, ...OV, campaignsList: paged(fixture("campaigns-list")), campaignsChart: fixture("campaigns-chart") }, D30, { picks: picks({ csort: "created_date:desc" }) });
    expect(rows(doc, "[data-oi-table='campaigns']")).toEqual([["Synthetic link", "Oct 1, 2026", "-", "9", "1"], ["Synthetic ended link", "Sep 21, 2026", "Sep 21, 2026", "2", "0"]]);
    expect([...doc.querySelectorAll("[data-oi-table='campaigns'] tbody tr.g-gray-text")].map((r) => r.querySelector("td")!.textContent!.trim())).toEqual(["Synthetic ended link"]);
    expect(doc.querySelector("[data-oi-copy]")).toBeNull(); // no username yet
    expect(texts(doc, "[data-oi-summary='campaigns']")).toEqual(["1 Subscribers 50%"]);
    expect(spec(doc, "[data-oi-chart='campaigns'] canvas.b-chart__double-line__aside")!.series.title).toBe("Clicks");
    const th = doc.querySelector<HTMLElement>("th[data-oi-sort='created_date']")!;
    expect(th.classList.contains("m-active")).toBe(true);
  });
  it("Reach with the phase-1 Relay: Claimed / Subscribers open OF's lists; Tracking links' copy icon copies OF's link", async () => {
    let doc = load("statistics/reach/promotions");
    const me = { subscribePrice: 10, username: "u_creator" } as OfMe;
    applyStats(doc, "statistics/reach/promotions", { ...BASE, ...OV, promotionsList: paged(fixture("promotions-list")), promotionsChart: fixture("promotions-chart") }, D30, { v2: true, v3: true, me });
    expect([...doc.querySelectorAll("[data-oi-table='promotions'] [data-oi-users]")].map((l) => [l.getAttribute("data-oi-users"), l.textContent!.trim()])).toEqual([["promo-claims:59001:0", "1"], ["promo-claims:59002:0", "5"]]);
    doc = load("statistics/reach/trial-links");
    applyStats(doc, "statistics/reach/trial-links", { ...BASE, ...OV, trialsList: paged(fixture("trials-list")), trialsChart: fixture("trials-chart-zero") }, D30, { v2: true, v3: true, me });
    expect([...doc.querySelectorAll("[data-oi-users]")].map((l) => l.getAttribute("data-oi-users")!.split(":")[0])).toEqual(["trial-claims"]);
    doc = load("statistics/reach/tracking-links");
    applyStats(doc, "statistics/reach/tracking-links", { ...BASE, ...OV, campaignsList: paged(fixture("campaigns-list")), campaignsChart: fixture("campaigns-chart") }, D30, { v2: true, v3: true, me });
    expect([...doc.querySelectorAll("[data-oi-users]")].map((l) => l.getAttribute("data-oi-users"))).toEqual(["campaign:61001:0"]); // 0 subscribers: plain
    const copy = [...doc.querySelectorAll<HTMLElement>("[data-oi-copy]")];
    expect(copy.map((c) => c.getAttribute("data-oi-copy"))).toEqual(["https://onlyfans.com/u_creator/c7"]); // the ended link has none
    const writeText = vi.fn(() => Promise.resolve());
    Object.defineProperty(window.navigator, "clipboard", { value: { writeText }, configurable: true });
    copy[0].click();
    await Promise.resolve();
    await Promise.resolve();
    expect(writeText).toHaveBeenCalledWith("https://onlyfans.com/u_creator/c7");
    expect(texts(doc, "#oi-toast .toast__text")).toEqual(["Tracking link copied!"]);
  });
  it("OF's promotion text (91477 promotionDetailsText): free, a discount from the price, unknown price", () => {
    const now = new Date("2026-02-10T12:00:00Z");
    expect(promotionText({ price: 0, subscribeDays: 0 }, 10, now)).toBe("Limited offer - Free trial for 30 days!");
    expect(promotionText({ price: 0, subscribeDays: 1 }, 10, now)).toBe("Limited offer - Free trial for 1 day!");
    expect(promotionText({ price: 2.5, subscribeDays: 0 }, 10, now)).toBe("Limited offer - 75% off for 28 days!"); // February
    expect(promotionText({ price: 2.5, discount: 60, subscribeDays: 7 }, 10, now)).toBe("Limited offer - 60% off for 7 days!");
    expect(promotionText({ price: 12, subscribeDays: 7 }, 10, now)).toBe("Limited offer - 0% off for 7 days!");
  });
});

describe("Fans", () => {
  const OV = fixture<Record<string, unknown>>("overview");
  it("routes: the tab's `by` on the chart (phase-2 Relay only), the table and top fans; the owner's time zone on activity", () => {
    expect(statsRoute("subsChart", D30, { v2: true, picks: picks({ subs: "renew" }) })).toMatch(/^\/api\/of\/v2\/subscriptions\/subscribers\/chart\?by=renew&start=/);
    expect(statsRoute("subsChart", D30, { picks: picks({ subs: "renew" }) })).toMatch(/^\/api\/of\/v2\/subscriptions\/subscribers\/chart\?start=/);
    expect(listRoute("subsLatest", D30, { offset: 10 }, { picks: picks({ subs: "new" }) })).toMatch(/^\/api\/of\/v2\/subscriptions\/subscribers\/latest\?by=new&offset=10&start=/);
    expect(listRoute("subsTop", D30, { offset: 0 }, { picks: picks({ top: "post" }) })).toMatch(/^\/api\/of\/v2\/subscriptions\/subscribers\/top\?by=post&offset=0&start=/);
    expect(statsRoute("fansHours", D30, { tz: TZ })).toBe("/api/of/v2/fans-activity/list?format=hours&start=2026-09-17+00%3A00%3A00&end=2026-10-17+10%3A00%3A00&timeZone=Europe%2FLjubljana");
  });
  it("Subscriptions: OF's tabs, the tab's summary from its chart and its table; none: \"Nothing found\"; today's Relay: disabled", () => {
    const doc = load("statistics/fans/subscriptions");
    const data = { ...BASE, ...OV, subsChart: fixture("subs-chart-renew"), subsLatest: paged(fixture("subs-latest")) };
    applyStats(doc, "statistics/fans/subscriptions", data, D30, { v2: true, picks: picks({ subs: "renew" }) });
    expect([...doc.querySelectorAll<HTMLButtonElement>("[data-oi-pick^='subs:']")].map((b) => [b.textContent!.trim(), b.disabled, b.classList.contains("m-current")])).toEqual([["All", false, false], ["Renews", false, true], ["New subscribers", false, false]]);
    expect(texts(doc, ".b-statistics-page-content__wrapper > .b-elements-determinant__value")).toEqual(["2 Subscribers $19.98 -20%"]);
    expect(texts(doc, "[data-oi-table='subs'] thead th")).toEqual(["Name", "Price", "Price/ Renew date"]);
    expect(rows(doc, "[data-oi-table='subs']")).toEqual([
      ["SF Synthetic Fan D @u_synthetic_d", "free", ""],
      ["u900011 @u900011", "$9.99", "Oct 10, 2026"],
    ]);
    expect(doc.querySelectorAll("[data-oi-table='subs'] tbody tr.g-gray-text").length).toBe(1); // expired Oct 12
    applyStats(doc, "statistics/fans/subscriptions", { ...data, subsLatest: paged(fixture("users-empty")) }, D30, { v2: true });
    expect(texts(doc, "[data-oi-table='subs'] .empty-message")).toEqual(["Nothing found"]);
    applyStats(doc, "statistics/fans/subscriptions", { ...BASE, ...OV, subsChart: fixture("subscribers-chart") }, D30);
    expect([...doc.querySelectorAll<HTMLButtonElement>("[data-oi-pick^='subs:']")].every((b) => b.disabled && b.title === NOT_YET)).toBe(true);
    expect(texts(doc, "[data-oi-table='subs'] .empty-message")).toEqual([NOT_YET]);
  });
  it("Top fans: OF's tabs, the tab's sum and the total; an all-zero period: \"No users found\"", () => {
    const doc = load("statistics/fans/top-fans");
    applyStats(doc, "statistics/fans/top-fans", { ...BASE, ...OV, subsTop: paged(fixture("subs-top")) }, D30, { v2: true, picks: picks({ top: "tips" }) });
    expect(texts(doc, "[data-oi-table='topfans'] thead th")).toEqual(["Name", "Tips", "Tips / Total"]);
    expect(rows(doc, "[data-oi-table='topfans']")).toEqual([["SF Synthetic Fan E @u_synthetic_e", "$7.00", "$12.00"]]);
    applyStats(doc, "statistics/fans/top-fans", { ...BASE, ...OV, subsTop: paged(fixture("users-empty")) }, D30, { v2: true });
    expect(texts(doc, "[data-oi-table='topfans'] thead th")).toEqual(["Name", "Tips / Total"]);
    expect(texts(doc, "[data-oi-table='topfans'] .empty-message")).toEqual(["No users found"]);
  });
  it("Fans activity: OF's sectors chart and hours bars, their colours and tooltips; an all-zero period: blank boxes and zero bars", () => {
    const doc = load("statistics/fans/activity");
    const before = texts(doc, ".b-statistics-page-content__wrapper .empty-message");
    expect(before).toEqual([NOT_YET, NOT_YET]); // today's Relay: no source
    applyStats(doc, "statistics/fans/activity", { ...BASE, ...OV, fansActivity: fixture("fans-activity"), fansHours: fixture("fans-hours") }, D30);
    expect(doc.querySelector<HTMLElement>("[data-oi-activity='sectors']")!.style.display).toBe("");
    expect(doc.querySelector<HTMLElement>("[data-oi-activity='hours']")!.style.display).toBe("");
    expect(texts(doc, ".b-statistics-page-content__wrapper .empty-message")).toEqual([]);
    const sectors = doc.querySelector<HTMLCanvasElement>("[data-oi-activity='sectors'] canvas")!;
    const s = fansChartOf(sectors)!;
    expect(s.kind).toBe("sectors");
    if (s.kind !== "sectors") return;
    expect(s.spec.labels).toEqual(["12am", "3am", "6am", "9am", "12pm", "3pm", "6pm", "9pm", ""]);
    expect(s.spec.days).toEqual(["Sat", "Fri", "Thu", "Wed", "Tue", "Mon", "Sun"]);
    expect(s.spec.cells).toHaveLength(56);
    expect(s.spec.max).toBe(60);
    const mon9pm = s.spec.cells.findIndex((c) => c.day === "Mon" && c.slot === 8);
    expect(sectorColors(s.spec.cells[mon9pm], s.spec.max)).toEqual({ fill: "rgba(0, 175, 240, 0.5833333333333334)", border: "rgba(108, 162, 183, 0.35)" });
    expect(texts(fansTooltip(doc, sectors, mon9pm)!, ".b-chart__tooltip__title, .b-chart__tooltip__text")).toEqual(["Mon 9pm - 12am", "Fans online 35%"]);
    const hours = doc.querySelector<HTMLCanvasElement>("[data-oi-activity='hours'] canvas")!;
    const h = fansChartOf(hours)!;
    if (h.kind !== "bars") throw new Error("bars");
    expect(h.spec.values).toHaveLength(24);
    expect(h.spec.values[9]).toBe(5);
    expect(texts(fansTooltip(doc, hours, 9)!, ".b-chart__tooltip__title, .b-chart__tooltip__text")).toEqual(["9am - 10am", "Fans online 5%"]);
    expect(texts(fansTooltip(doc, hours, 23)!, ".b-chart__tooltip__title, .b-chart__tooltip__text")).toEqual(["11pm - 12am", "Fans online 0%"]);
    expect(barColor(0, h.spec.values)).toBe("rgba(0, 175, 240, 0)");
    // An all-zero period: OF still draws both charts (zero boxes at 1%, zero bars), no empty text.
    applyStats(doc, "statistics/fans/activity", { ...BASE, ...OV, fansActivity: fixture("fans-activity-zero"), fansHours: fixture("fans-hours-zero") }, D30);
    const z = fansChartOf(sectors)!;
    if (z.kind !== "sectors") throw new Error("sectors");
    expect(z.spec.max).toBe(0);
    expect(sectorColors(z.spec.cells[0], 0)).toEqual({ fill: "rgba(0, 175, 240, 0.01)", border: "rgba(108, 162, 183, 0.3)" });
    expect(fansChartOf(hours)!.spec).toMatchObject({ values: Array(24).fill(0) });
    expect(texts(doc, ".b-statistics-page-content__wrapper .empty-message")).toEqual([]);
    // No hours at all: OF's text.
    applyStats(doc, "statistics/fans/activity", { ...BASE, ...OV, fansHours: { data: [] } }, D30);
    expect(texts(doc, ".b-statistics-page-content__wrapper .empty-message")).toEqual([NOT_YET, "No Profile activity during selected period"]);
  });
  it("OF's next hour label (app.js `ue`) and a single-day sectors chart", () => {
    expect(nextLabel(["12am", "3am", ""], 1)).toBe("6am");
    expect(nextLabel(["12am", "3am", "6am"], 0)).toBe("3am");
    const one = sectorsOf({ Tue: { "0": { ratio: 0.1 }, "12": { ratio: "x" } } });
    expect(one).toMatchObject({ labels: ["12am", "12pm", ""], days: ["Tue"], max: 10 });
    expect(sectorColors(one.cells[1], one.max)).toEqual({ fill: "#f1f2f4", border: "#c3d1d9" });
  });
  it("The sidebar Top Fan card: the fan, the tabs with a fan, Subscription and Earnings; its actions disabled with the tooltip", () => {
    const doc = load("statistics/fans/top-fans");
    const data = { ...BASE, ...OV, topFan: fixture("top-fan") };
    applyStats(doc, "statistics/fans/top-fans", data, D30, { v2: true });
    const card = doc.querySelector<HTMLElement>("[data-oi-fan-card]")!;
    expect(card.style.display).toBe("");
    expect(texts(card, ".g-user-name, .g-user-username")).toEqual(["Synthetic Fan B", "@u_synthetic_b"]);
    expect([...card.querySelectorAll<HTMLButtonElement>("[data-oi-pick^='fan:']")].map((b) => `${b.textContent!.trim()}${b.disabled ? " (off)" : ""}${b.classList.contains("m-current") ? " *" : ""}`)).toEqual(["Total *", "Subscriptions", "Tips (off)", "Messages", "Streams (off)"]);
    expect(texts(card, ".b-fans__item__list__item")).toEqual(["Current subscription $9.99", "Total duration 3 months"]);
    const actions = [...card.querySelectorAll<HTMLButtonElement>("button")].filter((b) => /Lists|Discount|Restrict|Add notes/.test(b.textContent ?? "") || b.getAttribute("aria-label") === "More");
    expect(actions.map((b) => [b.textContent!.trim() || b.getAttribute("aria-label"), b.disabled, b.title])).toEqual([
      ["More", true, NOT_YET], ["Lists", true, NOT_YET], ["Discount", true, NOT_YET], ["Restrict", true, NOT_YET], ["Add notes", true, NOT_YET],
    ]);
    applyStats(doc, "statistics/fans/top-fans", data, D30, { v2: true, picks: picks({ fantab: "earnings", fan: "messages" }) });
    expect(texts(card, ".b-fans__item__list__item")).toEqual(["Total $42.50", "Subscriptions $29.97", "Tips $7.53", "Messages $5.00", "Streams $0.00"]);
    // An all-zero period: no top fan.
    applyStats(doc, "statistics/fans/top-fans", { ...data, topFan: fixture("top-empty") }, D30, { v2: true });
    expect(card.style.display).toBe("none");
    expect(texts(doc, ".l-wrapper__sidebar .b-clean-state .empty-message")).toEqual(["No Fans yet"]);
  });
});

describe("All pages", () => {
  it("a pair of unequal series: both on the main line's dates, the tooltip reads each line at the hovered index", () => {
    document.body.innerHTML = '<div class="b-chart"><canvas class="b-chart__double-line__main"></canvas><canvas class="b-chart__double-line__aside"></canvas></div>';
    const root = document.querySelector(".b-chart")!;
    const main = [{ date: "2026-10-01T00:00:00+00:00", count: 1 }, { date: "2026-10-02T00:00:00+00:00", count: 2 }, { date: "2026-10-03T00:00:00+00:00", count: 3 }];
    const aside = [{ date: "2026-09-01T00:00:00+00:00", count: 5 }, { date: "2026-09-02T00:00:00+00:00", count: 6 }];
    drawPair(document, root, [main, "Claims", "count"], [aside, "Offers", "count"], "UTC");
    const [m, a] = [...root.querySelectorAll("canvas")];
    expect(chartSpecOf(a)!.labels).toEqual(chartSpecOf(m)!.labels);
    expect(chartSpecOf(a)!.labels).toEqual(["0:00, Oct 01", "0:00, Oct 02", "0:00, Oct 03"]);
    expect(texts(chartTooltip(document, a, 1)!, ".b-chart__tooltip__title, .b-chart__tooltip__text")).toEqual(["0:00, Oct 02", "Claims 2", "Offers 6"]);
    expect(texts(chartTooltip(document, m, 2)!, ".b-chart__tooltip__title, .b-chart__tooltip__text")).toEqual(["0:00, Oct 03", "Claims 3"]);
    // OF's single point is drawn from the period's start (ChartJs.js 293791 `J`).
    drawPair(document, root, [[main[0]], "Claims", "count"], null, "UTC");
    expect(chartSpecOf(m)!.series.values).toEqual([0, 1]);
  });
  it("user lists: OF's 10 per page by offset, tips_only for streams and stories, the phase-1 Relay's lists", () => {
    expect(usersRoute("buyers:55001:0", 10)).toBe("/api/of/v2/messages/queue/buyers?queue_id=55001&limit=10&offset=10");
    expect(usersRoute("streams:57001:1")).toBe("/api/of/v2/streams/viewers?stream_id=57001&limit=10&offset=0&tips_only=1");
    expect(usersRoute("post-tips:1:0", 20)).toBe("/api/of/v2/posts/tips?post_id=1&limit=10&offset=20");
    expect(usersRoute("post-likes:1:0", 10)).toBe("/api/of/v2/posts/likes?post_id=1&limit=10&offset=10");
    expect(usersRoute("promo-claims:59001:0")).toBe("/api/of/v2/promotions/claims?promo_id=59001&limit=10&offset=0");
    expect(usersRoute("trial-claims:2:0")).toBe("/api/of/v2/trials/claims?trial_id=2&limit=10&offset=0");
    expect(usersRoute("campaign:61001:0")).toBe("/api/of/v2/campaigns/claimers?campaign_id=61001&limit=10&offset=0");
    expect(usersRoute("campaign:x:0")).toBeNull();
  });
  it("a user list pages as its last row scrolls into view while OF says hasMore; none: \"Nothing found\"", async () => {
    document.body.innerHTML = "";
    const fan = (i: number) => ({ id: 900000 + i, name: `Synthetic Fan ${i}`, username: `u_synthetic_${i}`, avatar: null });
    const pages: Record<string, unknown> = {
      "0": { list: Array.from({ length: 10 }, (_, i) => fan(i)), hasMore: true },
      "10": { list: [fan(10)], hasMore: false },
    };
    const get = vi.spyOn(relay, "get").mockImplementation((path: string) => Promise.resolve(pages[new URL(path, "http://x").searchParams.get("offset")!] as never));
    const seen: ((e: { isIntersecting: boolean }[]) => void)[] = [];
    (window as unknown as { IntersectionObserver: unknown }).IntersectionObserver = class {
      constructor(cb: (e: { isIntersecting: boolean }[]) => void) { seen.push(cb); }
      observe() {}
      disconnect() {}
    };
    bindUserLists(document, {});
    document.body.append(usersLink(document, "11", "post-buyers", 7001));
    document.querySelector<HTMLElement>("[data-oi-users]")!.click();
    await vi.waitFor(() => expect(document.querySelectorAll("#oi-users tbody tr").length).toBe(10));
    expect(texts(document, "#oi-users .modal-title")).toEqual(["Post Buyers"]);
    seen.at(-1)!([{ isIntersecting: true }]);
    await vi.waitFor(() => expect(document.querySelectorAll("#oi-users tbody tr").length).toBe(11));
    expect(get.mock.calls.map((c) => c[0])).toEqual(["/api/of/v2/posts/buyers?post_id=7001&limit=10&offset=0", "/api/of/v2/posts/buyers?post_id=7001&limit=10&offset=10"]);
    expect(seen).toHaveLength(1); // hasMore false: no third page
    document.getElementById("oi-users")!.remove();
    get.mockImplementation(() => Promise.resolve({ list: [], hasMore: false } as never));
    document.querySelector<HTMLElement>("[data-oi-users]")!.click();
    await vi.waitFor(() => expect(texts(document, "#oi-users .empty-message")).toEqual(["Nothing found"]));
    get.mockRestore();
  });
});

describe("Card More menus and Post statistics", () => {
  const menuRows = () => [...document.querySelectorAll<HTMLElement>("#oi-menu [role='menuitem']")].map((r) => `${r.textContent!.trim()}${r.getAttribute("aria-disabled") ? ` (${r.title})` : ""}`);
  const more = (card: Element) => card.querySelector<HTMLButtonElement>(".b-top-statistic__header .m-btn-horizontal-dots")!;
  const close = () => document.getElementById("oi-menu")?.remove();
  it("Top Message: Show who bought opens its buyers, Unsend disabled, pointing at Mass Messages; Top Stream: OF's detailed statistics disabled", async () => {
    const doc = load("statistics/overview/top-highlights");
    applyStats(doc, "statistics/overview/top-highlights", { ...BASE, topMessage: fixture("top-message"), topStream: fixture("top-stream"), topPost: { purchases: null } }, D30, { v2: true });
    const card = (t: string) => doc.querySelector(`[data-oi-top='${t}']`)!;
    const get = vi.spyOn(relay, "get").mockResolvedValue({ list: [], hasMore: false } as never);
    more(card("Top Message")).click();
    expect(menuRows()).toEqual(["Show who bought", `Unsend (${ELSEWHERE.unsendMass})`]);
    expect(doc.querySelector("#oi-menu .m-danger")!.textContent!.trim()).toBe("Unsend");
    doc.querySelector<HTMLElement>("#oi-menu [role='menuitem']")!.click();
    expect(doc.getElementById("oi-menu")).toBeNull();
    await vi.waitFor(() => expect(texts(doc, "#oi-users .modal-title")).toEqual(["Message buyers"]));
    expect(get.mock.calls[0][0]).toBe("/api/of/v2/messages/queue/buyers?queue_id=52001&limit=10&offset=0");
    doc.getElementById("oi-users")!.remove();
    more(card("Top Stream")).click();
    expect(menuRows()).toEqual([`View detailed statistics (${NOT_YET})`]); // no media: OF's composer rows are not shown
    doc.querySelector<HTMLElement>("#oi-menu [role='menuitem']")!.click(); // disabled: nothing, the menu stays
    expect(doc.getElementById("oi-menu")).not.toBeNull();
    close();
    get.mockRestore();
  });
  it("Top Post: OF's post menu (the post writes disabled), Copy link to post; Full stat and its menu row need the phase-1 Relay", async () => {
    const doc = load("statistics/overview/top-highlights");
    const data = { ...BASE, topPost: fixture("top-post") };
    applyStats(doc, "statistics/overview/top-highlights", data, D30, { v2: true, picks: picks({ tpost: "views" }), me: { id: 1001, username: "u_creator" } as OfMe });
    const card = doc.querySelector("[data-oi-top='Top Post']")!;
    const full = card.querySelector<HTMLButtonElement>(".b-top-statistic__btns button")!;
    expect([full.textContent!.trim(), full.disabled, full.title]).toEqual(["Full stat", true, NOT_YET]);
    // OF's media-count icons (QueuePostItem): two photos.
    expect([...card.querySelectorAll(".b-top-statistic__btns-row .b-content-inside-thumbs__item")].map((i) => [i.querySelector("svg")!.getAttribute("data-icon-name"), i.textContent])).toEqual([["icon-media", "2"]]);
    more(card).click();
    expect(menuRows()).toEqual([
      "Copy link to post", `Pin to your profile page (${NOT_YET})`, `Share post to story (${NOT_YET})`, `View post (${NOT_YET})`, `Edit post (${NOT_YET})`,
      `Archive Post (${NOT_YET})`, `Add to private archive (${NOT_YET})`, `Add a tag (${NOT_YET})`, `View detailed statistics (${NOT_YET})`,
    ]);
    expect(doc.querySelectorAll("#oi-menu hr.v-divider")).toHaveLength(1);
    const writeText = vi.fn(() => Promise.resolve());
    Object.defineProperty(window.navigator, "clipboard", { value: { writeText }, configurable: true });
    doc.querySelector<HTMLElement>("#oi-menu [role='menuitem']")!.click();
    await vi.waitFor(() => expect(texts(doc, "#oi-toast .toast__text")).toEqual(["Link to post has been copied to clipboard!"]));
    expect(writeText).toHaveBeenCalledWith("https://onlyfans.com/7001/u_creator");
    // The phase-1 Relay: Full stat and the menu's last row open OF's Post statistics.
    applyStats(doc, "statistics/overview/top-highlights", data, D30, { v2: true, v3: true, picks: picks({ tpost: "views" }) });
    const get = vi.spyOn(relay, "get").mockResolvedValue(fixture("post-stats") as never);
    more(doc.querySelector("[data-oi-top='Top Post']")!).click();
    expect(menuRows().at(-1)).toBe("View detailed statistics");
    expect(menuRows()[0]).toBe(`Copy link to post (${NOT_YET})`); // no username known yet
    [...doc.querySelectorAll<HTMLElement>("#oi-menu [role='menuitem']")].at(-1)!.click();
    await vi.waitFor(() => expect(doc.querySelector("#oi-post-stats .b-stats-row__content")).not.toBeNull());
    expect(get.mock.calls[0][0]).toBe("/api/of/v2/posts/stats?post_id=7001");
    expect(texts(doc, "#oi-post-stats .modal-title")).toEqual(["Post statistics"]);
    doc.getElementById("oi-post-stats")!.remove();
    doc.querySelector<HTMLButtonElement>("[data-oi-top='Top Post'] .b-top-statistic__btns button")!.click();
    await vi.waitFor(() => expect(doc.querySelector("#oi-post-stats .b-stats-row__content")).not.toBeNull());
    doc.getElementById("oi-post-stats")!.remove();
    get.mockRestore();
  });
  it("Post statistics: OF's rows, links, sums and Duration / Average; a row toggles its line (Views with Unique viewers); all zero", async () => {
    document.body.innerHTML = "";
    bindUserLists(document, {});
    const get = vi.spyOn(relay, "get").mockResolvedValue(fixture("post-stats") as never);
    const { openPostStats } = await import("./ofMirrorStatsPostStat");
    openPostStats(document, 7001, TZ);
    await vi.waitFor(() => expect(document.querySelector("#oi-post-stats .b-stats-row__content")).not.toBeNull());
    expect(texts(document, "#oi-post-stats .g-gray-text")[0]).toBe("Some statistics may be delayed or approximated");
    expect(texts(document, "#oi-post-stats .b-stats-row__label")).toEqual(["Purchases 2 ($12.00)", "Views 9", "Likes 3", "Comments 1", "Tips 2 ($7.50)", "Duration / Average 05:12 / 34"]);
    expect([...document.querySelectorAll("#oi-post-stats [data-oi-users]")].map((l) => l.getAttribute("data-oi-users"))).toEqual(["post-buyers:7001:0", "post-likes:7001:0", "post-tips:7001:0"]);
    const canvas = document.querySelector<HTMLCanvasElement>("#oi-post-stats canvas.b-chart__multiple-line")!;
    expect(linesOf(canvas)!.lines.map((l) => [l.title, l.values.join(",")])).toEqual([
      ["Purchases", "1,1,0"], ["Views", "4,3,2"], ["Unique viewers", "3,2,1"], ["Likes", "1,2,0"], ["Comments", "0,1,0"], ["Tips", "0,1,1"],
    ]);
    expect(linesOf(canvas)!.labels).toHaveLength(3);
    document.querySelector<HTMLElement>("#oi-post-stats [data-oi-stat-row='views']")!.click();
    expect(linesOf(canvas)!.lines.map((l) => l.title)).toEqual(["Purchases", "Likes", "Comments", "Tips"]);
    expect(document.querySelector("#oi-post-stats [data-oi-stat-row='views']")!.classList.contains("m-current")).toBe(false);
    // A count link opens its list, not the toggle.
    document.querySelector<HTMLElement>("#oi-post-stats [data-oi-users]")!.click();
    await vi.waitFor(() => expect(texts(document, "#oi-users .modal-title")).toEqual(["Post Buyers"]));
    expect(document.querySelector("#oi-post-stats [data-oi-stat-row='purchases']")!.classList.contains("m-current")).toBe(true);
    document.getElementById("oi-users")!.remove();
    // Likes opens the post's likers (OF's PostLikes list), read 10 at a time as the others.
    get.mockClear();
    document.querySelector<HTMLElement>("#oi-post-stats [data-oi-users^='post-likes']")!.click();
    await vi.waitFor(() => expect(texts(document, "#oi-users .modal-title")).toEqual(["Post likes"]));
    expect(get.mock.calls[0][0]).toBe("/api/of/v2/posts/likes?post_id=7001&limit=10&offset=0");
    document.getElementById("oi-users")!.remove();
    document.getElementById("oi-post-stats")!.remove();
    // An all-zero post: zeros, no links, no Duration row, flat lines.
    get.mockResolvedValue(fixture("post-stats-zero") as never);
    openPostStats(document, 7001, TZ);
    await vi.waitFor(() => expect(document.querySelector("#oi-post-stats .b-stats-row__content")).not.toBeNull());
    expect(texts(document, "#oi-post-stats .b-stats-row__label")).toEqual(["Purchases 0 ($0.00)", "Views 0", "Likes 0", "Comments 0", "Tips 0 ($0.00)"]);
    expect(document.querySelector("#oi-post-stats [data-oi-users]")).toBeNull();
    expect(linesOf(document.querySelector<HTMLCanvasElement>("#oi-post-stats canvas")!)!.lines.every((l) => l.values.every((v) => v === 0))).toBe(true);
    document.getElementById("oi-post-stats")!.remove();
    // The Relay's error: its text.
    get.mockRejectedValue(new Error("Not Found"));
    openPostStats(document, 7001, TZ);
    await vi.waitFor(() => expect(texts(document, "#oi-post-stats .empty-message")).toEqual(["Couldn't load the statistics: Not Found"]));
    get.mockRestore();
    expect([postStatsRoute("x"), durationText(3725), postStatRows(null)]).toEqual([null, "01:02:05", []]);
    expect(postStatRows(fixture("post-stats"), true)[0].tooltip).toBe("This number includes stream purchases");
  });
  it("Engagement › Posts with the phase-1 Relay: tips and purchases open their lists and Full stat opens the popup; else plain", () => {
    const first = paged(fixture("posts-top")).list[0] as Record<string, unknown>;
    const post = { ...first, tipsAmount: "$5", stats: { ...(first.stats as object), purchasedSumm: 10 } };
    const doc = load("statistics/engagement/posts");
    const data = { ...BASE, postsTop: paged({ list: [post], hasMore: false }) };
    applyStats(doc, "statistics/engagement/posts", data, D30, { v2: true, v3: true, picks: { by: "purchases" } });
    const row = doc.querySelector("[data-oi-table='posts'] tbody tr[data-oi-data]")!;
    expect([...row.querySelectorAll("[data-oi-users]")].map((l) => [l.textContent!.trim(), l.getAttribute("data-oi-users")])).toEqual([["$5.00", "post-tips:7001:0"], ["$10.00", "post-buyers:7001:0"]]);
    expect(row.querySelector<HTMLButtonElement>(".b-top-statistic__btns button")!.disabled).toBe(false);
    applyStats(doc, "statistics/engagement/posts", data, D30, { v2: true, picks: { by: "purchases" } });
    const plainRow = doc.querySelector("[data-oi-table='posts'] tbody tr[data-oi-data]")!;
    expect(plainRow.querySelector("[data-oi-users]")).toBeNull();
    expect(plainRow.querySelector<HTMLButtonElement>(".b-top-statistic__btns button")!.title).toBe(NOT_YET);
  });
});

describe("postStatsProbe: the phase-1 Relay's per-item reads, found with a 2xx (no red console line on every page)", () => {
  it("true for {supported: true} and an older Relay's 422; false for anything else, a 404 or a 403", async () => {
    const answers: [() => Promise<unknown>, boolean][] = [
      [() => Promise.resolve({ supported: true }), true],
      [() => Promise.reject(new RelayError(422, { detail: "post_id" })), true],
      [() => Promise.resolve([]), false],
      [() => Promise.resolve({ supported: "yes" }), false],
      [() => Promise.reject(new RelayError(404, null)), false],
      [() => Promise.reject(new RelayError(403, null)), false],
    ];
    for (const [answer, want] of answers) {
      const get = vi.spyOn(relay, "get").mockImplementation(answer as never);
      expect(await postStatsProbe("acct-1").queryFn()).toBe(want);
      expect(get).toHaveBeenCalledWith("/api/of/v2/posts/stats", { accountId: "acct-1" });
      get.mockRestore();
    }
  });
});
