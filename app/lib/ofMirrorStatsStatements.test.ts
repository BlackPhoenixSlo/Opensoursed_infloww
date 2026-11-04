/**
 * ofMirrorStatsStatements, unit by unit: the chart lookup (statementsSeries), the summary rekeys, and each apply* on the
 * real mirror pages (app/public/of-mirror/pages/statistics/statements/*) with the OF-shaped fixtures
 * (app/lib/__fixtures__/of/statistics-*.json) or inline rows in OF's shapes.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("./relay", async (orig) => ({ ...(await orig<typeof import("./relay")>()), relayFile: vi.fn() }));

import { relayFile } from "./relay";
import { PICK_DEFAULTS, periodOf, startOf, type EarningsType, type PagedBody, type Picks, type StatsData } from "./ofMirrorStats";
import { applyEarningsAside, applyEarningsTabs, applyPayouts, applyRatio, applyStatements, applyTransactions, rekeyFor, rekeyReferrals, statementsSeries, type StatementsCtx } from "./ofMirrorStatsStatements";
import { chartSpecOf } from "./ofMirrorChart";
import type { Transaction } from "./ofMirrorFeedsStatements";
import { NOT_YET } from "./ofMirrorWrites";

const capture = (p: string) => readFileSync(resolve(__dirname, `../public/of-mirror/pages/${p}.html`), "utf8");
const load = (p: string) => {
  document.documentElement.innerHTML = capture(p);
  return document;
};
const visible = (el: Element) => !el.closest("[style*='display:none'], [style*='display: none']");
const squash = (s: string | null | undefined) => (s ?? "").replace(/\s+/g, " ").trim();
const texts = (doc: ParentNode, sel: string) => [...doc.querySelectorAll(sel)].filter(visible).map((e) => squash(e.textContent));
const rows = (doc: ParentNode, sel: string) => [...doc.querySelectorAll(`${sel} tbody > tr`)].filter(visible).map((r) => [...r.querySelectorAll(":scope > td")].map((c) => squash(c.textContent)));
const TZ = "Europe/Ljubljana";
const NOW = new Date("2026-10-17T10:00:00Z"); // 12:00 in Ljubljana (UTC +02:00)
const fixture = <T = unknown,>(name: string): T => JSON.parse(readFileSync(resolve(__dirname, `__fixtures__/of/statistics-${name}.json`), "utf8")) as T;
const START = startOf(fixture("start-date"), TZ);
const D30 = periodOf("d30", NOW, TZ, START);
const ALL = periodOf("all", NOW, TZ, START);
const H24 = periodOf("24h", NOW, TZ, START);
const picks = (p: Partial<Picks> = {}): Picks => ({ ...PICK_DEFAULTS, ...p });
const ctx = (x: Partial<StatementsCtx> = {}): StatementsCtx => ({ picks: picks(), v2: false, type: "total", ...x });
const spec = (doc: Document, sel: string) => {
  const c = doc.querySelector<HTMLCanvasElement>(sel);
  return c ? chartSpecOf(c) : undefined;
};
const TYPES: EarningsType[] = ["total", "subscribes", "tips", "post", "chat_messages", "stream"];
/** A payout request in OF's shape (Payout Requests and Referrals' rows). */
const payout = (r: Record<string, unknown> = {}) => ({ createdAt: "2026-10-10T08:00:00+00:00", invoiceId: "61000000", amount: 50, state: "approved", ...r });

/**
 * jsdom has no IntersectionObserver (and its document.defaultView is globalThis, measured): a stand-in recording what
 * moreAt observes; `fire()` scrolls it into view.
 */
function stubIO() {
  const seen: { el: Element; fire: (isIntersecting?: boolean) => void; disconnected: boolean }[] = [];
  class IO {
    cb: (entries: { isIntersecting: boolean }[]) => void;
    rec?: (typeof seen)[number];
    constructor(cb: (entries: { isIntersecting: boolean }[]) => void) {
      this.cb = cb;
    }
    observe(el: Element) {
      this.rec = { el, fire: (isIntersecting = true) => this.cb([{ isIntersecting }]), disconnected: false };
      seen.push(this.rec);
    }
    disconnect() {
      if (this.rec) this.rec.disconnected = true;
    }
  }
  vi.stubGlobal("IntersectionObserver", IO);
  return seen;
}
afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  vi.clearAllMocks();
});

describe("statementsSeries: the type tab's chart figures (OF's summary), else null", () => {
  const chartOf = (key: string, total: unknown = 10, gross: unknown = 12.5, delta: unknown = -5) => ({
    [key]: { total, gross, delta, chartAmount: [{ date: "2026-10-16T00:00:00+00:00", count: 10 }], chartCount: [{ date: "2026-10-16T00:00:00+00:00", count: 2 }] },
  });
  it.each(TYPES.map((t) => [t] as const))("%s: read from the chart under its own key; Tips' sub-tab ignored off Tips", (type) => {
    expect(statementsSeries({ earningsChart: chartOf(type) }, type, "all")).toEqual({ total: 10, gross: 12.5, delta: -5 });
    expect(statementsSeries({ earningsChart: chartOf(type) }, type, type === "tips" ? "all" : "chat")).toEqual({ total: 10, gross: 12.5, delta: -5 });
  });
  it.each([
    ["all", "tips"],
    ["profile", "tips_profile"],
    ["post", "tips_post"],
    ["chat", "tips_chat"],
    ["stream", "tips_stream"],
    ["story", "tips_story"],
  ])("Tips › %s reads `%s`, nothing else", (tips, key) => {
    expect(statementsSeries({ earningsChart: chartOf(key, 3, 4, 0) }, "tips", tips)).toEqual({ total: 3, gross: 4, delta: 0 });
    const other = key === "tips" ? "tips_chat" : "tips";
    expect(statementsSeries({ earningsChart: chartOf(other) }, "tips", tips)).toBeNull();
  });
  it("the fixtures: Tips' $12.50 ($15.63 gross, +25%); an all-zero period's $0.00 is figures, not null", () => {
    expect(statementsSeries({ earningsChart: fixture("earnings-chart-tips") }, "tips", "all")).toEqual({ total: 12.5, gross: 15.63, delta: 25 });
    expect(statementsSeries({ earningsChart: fixture("earnings-chart-zero") }, "total", "all")).toEqual({ total: 0, gross: 0, delta: 0 });
    expect(statementsSeries({ earningsChart: fixture("earnings-chart-tips") }, "total", "all")).toBeNull();
  });
  it("null: today's Relay (`[]`), no chart, no total (a chart alone), a non-object entry; string numbers are read", () => {
    expect(statementsSeries({ earningsChart: fixture("earnings-chart") }, "total", "all")).toBeNull(); // `[]`
    expect(statementsSeries({}, "total", "all")).toBeNull();
    expect(statementsSeries({ earningsChart: chartOf("total", null) }, "total", "all")).toBeNull();
    expect(statementsSeries({ earningsChart: { total: 5 } }, "total", "all")).toBeNull();
    expect(statementsSeries({ earningsChart: { total: { total: 5 } } }, "total", "all")).toEqual({ total: 5, gross: null, delta: null });
    expect(statementsSeries({ earningsChart: chartOf("total", "7.5", "9", "x") }, "total", "all")).toEqual({ total: 7.5, gross: 9, delta: null });
  });
  it("Messages reads `chat_messages` from the reply (the route's filter asks `messages_*`): a reply keyed `messages` is not read", () => {
    // Inferred, unverified against OF: chartCategory (the route) maps chat_messages -> messages, chartTab here does not.
    expect(statementsSeries({ earningsChart: chartOf("messages") }, "chat_messages", "all")).toBeNull();
  });
});

describe("rekeyFor and rekeyReferrals: the summary's figure keys", () => {
  const page = document.createElement("div");
  page.innerHTML = `<div class="b-statistics-page-content__wrapper"><span id="in"></span></div><span id="out"></span>`;
  const inside = page.querySelector("#in")!;
  const outside = page.querySelector("#out")!;

  it.each([
    ["total", "earnings:earning.total"],
    ["subscribes", "fans:fans.earnings.total"],
    ["tips", "derived:tips.total"],
    ["post", "posts:posts.earnings.total"],
    ["chat_messages", "messages:massMessages.earnings.total"],
    ["stream", "streams:streams.earnings.total"],
  ] as [EarningsType, string][])("no chart, %s: the overview's figures for the type (%s); its gross and change alike", (type, want) => {
    const r = rekeyFor(type);
    expect(r(inside, "earnings:earning.total")).toBe(want);
    expect(r(inside, "earnings:earning.delta")).toBe(want.replace(/\.total$/, ".delta"));
    expect(r(inside, "earnings:earning.gross")).toBe(want.replace(/\.total$/, ".gross"));
  });
  it.each(TYPES.map((t) => [t] as const))("chart, %s: OF's own chart figures (series:<field>) whatever the type", (type) => {
    const r = rekeyFor(type, true);
    expect(r(inside, "earnings:earning.total")).toBe("series:total");
    expect(r(inside, "earnings:earning.gross")).toBe("series:gross");
    expect(r(inside, "earnings:earning.delta")).toBe("series:delta");
  });
  it("kept as is: outside the page's content (the sidebar), other sources, the bare key without a field", () => {
    for (const chart of [false, true]) {
      const r = rekeyFor("subscribes", chart);
      expect(r(outside, "earnings:earning.total")).toBe("earnings:earning.total");
      expect(r(inside, "fans:fans.earnings.total")).toBe("fans:fans.earnings.total");
      expect(r(inside, "earnings:earning")).toBe("earnings:earning");
      expect(r(inside, "earnings:earningX.total")).toBe("earnings:earningX.total");
      expect(r(inside, "derived:ref.total")).toBe("derived:ref.total");
    }
  });
  it("rekeyReferrals: with the Relay's chart, derived:ref.<f> -> referralsChart:<f>; else, or any other key, as is", () => {
    expect(rekeyReferrals(true)(inside, "derived:ref.total")).toBe("referralsChart:total");
    expect(rekeyReferrals(true)(outside, "derived:ref.delta")).toBe("referralsChart:delta"); // no wrapper check
    expect(rekeyReferrals(false)(inside, "derived:ref.total")).toBe("derived:ref.total");
    for (const k of ["derived:referral.total", "derived:ref", "earnings:earning.total", "referralsChart:total"]) expect(rekeyReferrals(true)(inside, k)).toBe(k);
  });
});

describe("applyEarningsAside: the Statements sidebar's Earnings", () => {
  const SIDEBAR = ".l-wrapper__sidebar [data-oi-pick^='type:'][data-oi-href]";
  const sideRows = (doc: Document) => [...doc.querySelectorAll<HTMLElement>(SIDEBAR)].filter(visible);
  const sideText = (doc: Document) => sideRows(doc).map((r) => squash(r.textContent));
  const empty = (doc: Document) => doc.querySelector<HTMLElement>("[data-oi-earnings-empty]")!;
  /** The overview's figures per category (no phase-2 sidebar chart). */
  const overview = (e: Partial<Record<"earnings" | "fans" | "tips" | "messages" | "posts" | "streams", { total: number; delta?: number }>>): StatsData => ({
    earnings: { earning: e.earnings },
    fans: { fans: { earnings: e.fans } },
    derived: { tips: e.tips },
    messages: { massMessages: { earnings: e.messages } },
    posts: { posts: { earnings: e.posts } },
    streams: { streams: { earnings: e.streams } },
  });

  it("the overview's categories with earnings, in OF's order (Messages before Posts); each opens its type tab; no chart", () => {
    const doc = load("statistics/statements/payout-request");
    applyEarningsAside(doc, overview({ earnings: { total: 30, delta: 50 }, fans: { total: 8, delta: 0 }, tips: { total: 0 }, messages: { total: 4, delta: -20 }, posts: { total: 18, delta: 12.345 }, streams: { total: 0.001 } }), D30);
    expect(sideText(doc)).toEqual(["Total $30.00 50%", "Subscriptions $8.00", "Messages $4.00 -20%", "Posts $18.00 12.35%"]);
    const rs = sideRows(doc);
    expect(rs.map((r) => r.getAttribute("data-oi-pick"))).toEqual(["type:total", "type:subscribes", "type:chat_messages", "type:post"]);
    for (const r of rs) {
      expect(r.getAttribute("data-oi-href")).toBe("/of-manager/statistics/statements/earnings");
      expect(r.classList.contains("g-pointer-cursor")).toBe(true);
      expect(r.hasAttribute("data-oi-template")).toBe(false);
      expect(r.querySelector(".b-elements-determinant__unit.m-chart")).toBeNull();
    }
    expect(rs[0].querySelector(".b-elements-determinant__label")!.textContent).toBe(" Total ");
    expect(rs[2].querySelector(".b-statistics-level")!.classList.contains("m-level-down")).toBe(true);
    expect(rs[0].querySelector(".b-statistics-level")!.classList.contains("m-level-up")).toBe(true);
    // The rows follow the template, in order; the template stays hidden.
    const tpl = doc.querySelector<HTMLElement>("[data-oi-template='earning']")!;
    expect(tpl.style.display).toBe("none");
    expect(tpl.nextElementSibling).toBe(rs[0]);
    expect(visible(empty(doc))).toBe(false);
  });
  it("a value rounding to $0 is marked m-zero-value; All time: no change marks", () => {
    const doc = load("statistics/statements/payout-request");
    applyEarningsAside(doc, overview({ earnings: { total: 0.4, delta: 10 } }), ALL);
    expect(sideText(doc)).toEqual(["Total $0.40"]);
    expect(sideRows(doc)[0].querySelector(".b-elements-determinant__value > span")!.classList.contains("m-zero-value")).toBe(true);
    expect(doc.querySelector(".l-wrapper__sidebar .b-statistics-level")).toBeNull();
  });
  it("no total (the overview unread): nothing touched", () => {
    const doc = load("statistics/statements/payout-request");
    applyEarningsAside(doc, overview({ fans: { total: 8 } }), D30);
    expect(sideRows(doc)).toEqual([]);
    expect(empty(doc).style.display).toBe("none");
  });
  it("a $0.00 total: OF's \"No earnings for this period\" alone", () => {
    const doc = load("statistics/statements/payout-request");
    applyEarningsAside(doc, overview({ earnings: { total: 0 }, fans: { total: 8 } }), D30);
    expect(sideRows(doc)).toEqual([]);
    expect(texts(doc, "[data-oi-earnings-empty]")).toEqual(["No earnings for this period"]);
  });
  it("a page without the template: no-op", () => {
    document.documentElement.innerHTML = "<body><div data-oi-earnings-empty style='display:none'></div></body>";
    applyEarningsAside(document, overview({ earnings: { total: 0 } }), D30);
    expect(document.querySelector<HTMLElement>("[data-oi-earnings-empty]")!.style.display).toBe("none");
  });
  it("the phase-2 sidebar (fixture): OF's rows from its category charts with a non-zero point, each a line in OF's colour", () => {
    const doc = load("statistics/statements/earnings");
    applyEarningsAside(doc, { ...overview({ earnings: { total: 999 } }), earningsSide: fixture("earnings-side") }, D30);
    expect(sideText(doc)).toEqual(["Total $12.00 20%", "Subscriptions $8.00 -10%", "Tips $4.00"]);
    const lines = sideRows(doc).map((r) => chartSpecOf(r.querySelector("canvas")!)!);
    expect(lines.map((l) => [l.series.title, l.series.color, l.series.kind, l.series.values])).toEqual([
      ["Total", "#8A96A3", "money", [0, 8, 4]],
      ["Subscriptions", "#7CB342", "money", [0, 8, 0]],
      ["Tips", "#9575CD", "money", [0, 0, 4]],
    ]);
  });
  it("the phase-2 sidebar (fixture), every category at $0.00: OF's empty text, no row, whatever the overview says", () => {
    const zero = load("statistics/statements/earnings");
    applyEarningsAside(zero, { ...overview({ earnings: { total: 999 } }), earningsSide: fixture("earnings-side-zero") }, D30);
    expect(sideRows(zero)).toEqual([]);
    expect(texts(zero, "[data-oi-earnings-empty]")).toEqual(["No earnings for this period"]);
  });
  it("the phase-2 sidebar: a category without both charts, or with only zero points, is left out; one with counts only is in", () => {
    const pts = (...n: number[]) => n.map((count, i) => ({ date: `2026-10-1${5 + i}T00:00:00+00:00`, count }));
    const doc = load("statistics/statements/earnings");
    applyEarningsAside(doc, {
      earningsSide: {
        total: { total: 3, delta: 0, chartAmount: pts(0, 0, 0), chartCount: pts(0, 1, 0) }, // counts only: listed
        subscribes: { total: 3, chartAmount: pts(0, 3, 0) }, // no chartCount: out
        stream: { total: 0, chartAmount: pts(0, 0, 0), chartCount: pts(0, 0, 0) },
      },
    }, D30);
    expect(sideText(doc)).toEqual(["Total $3.00"]);
  });
});

describe("applyTransactions: Statements › Earnings' rows", () => {
  const TABLE = ".b-statements-table";
  let ids = 0;
  const tx = (t: { [K in keyof Transaction]?: unknown } & Record<string, unknown>): Transaction => ({ id: `tx${++ids}`, status: "done", ...t }) as Transaction;
  const pg = (p: Partial<PagedBody>): Partial<PagedBody> => ({ list: [], hasMore: false, loading: false, more: null, ...p });

  // The date cell is OF's two adjacent inline-block spans ("Oct 12, 2026," and "11:41 am"): no text space between them.
  it("the period's rows only: date and time in the owner's zone, amount, fee, net, the description as plain text", () => {
    const doc = load("statistics/statements/earnings");
    applyTransactions(doc, [
      tx({ createdAt: "2026-10-12T09:41:07+00:00", amount: 10, fee: 2, net: 8, description: "Subscription from <a href=\"https://onlyfans.com/u1\">Fan One</a>" }),
      tx({ createdAt: "2026-10-01T22:05:00+00:00", amount: 1234.5, fee: 0, net: 1234.5, description: null }),
      tx({ createdAt: "2026-08-01T10:00:00+00:00", amount: 99, description: "Before the period" }),
      tx({ createdAt: "not a date", amount: 1 }),
    ], D30);
    expect(rows(doc, TABLE)).toEqual([
      ["Oct 12, 2026,11:41 am", "$10.00", "$2.00", "$8.00", "Subscription from Fan One"],
      ["Oct 02, 2026,12:05 am", "$1,234.50", "$0.00", "$1,234.50", ""],
    ]);
    // The generator's empty row is hidden once rows are in; the templates stay hidden.
    expect(texts(doc, `${TABLE} .empty-message`)).toEqual([]);
    expect([...doc.querySelectorAll<HTMLElement>(`${TABLE} tr[data-oi-template]`)].every((t) => t.style.display === "none")).toBe(true);
  });
  it("status: done keeps OF's Complete mark; loading the pending days (none: no label); any other status no mark", () => {
    const doc = load("statistics/statements/earnings");
    applyTransactions(doc, [
      tx({ createdAt: "2026-10-12T09:00:00+00:00", status: "done", amount: 1 }),
      tx({ createdAt: "2026-10-11T09:00:00+00:00", status: "loading", amount: 1, payoutPendingDays: 5 }),
      tx({ createdAt: "2026-10-10T09:00:00+00:00", status: "loading", amount: 1 }),
      tx({ createdAt: "2026-10-09T09:00:00+00:00", status: "canceled", amount: null, fee: undefined, net: "x" }),
    ], D30);
    const trs = [...doc.querySelectorAll(`${TABLE} tbody > tr`)].filter(visible);
    const tip = (i: number) => trs[i].querySelector(".b-table__status-tip");
    expect(tip(0)!.getAttribute("aria-label")).toBe("Complete");
    expect(tip(0)!.querySelector("use")!.getAttribute("href")).toBe("#icon-done");
    expect(tip(1)!.getAttribute("aria-label")).toBe("Earning will become available in 5 days");
    expect(tip(1)!.querySelector("use")!.getAttribute("href")).toBe("#icon-loading");
    expect(tip(2)!.hasAttribute("aria-label")).toBe(false);
    expect(tip(3)).toBeNull();
    // No money: empty cells, never "$NaN".
    expect(rows(doc, TABLE)[3].slice(1, 4)).toEqual(["", "", ""]);
  });
  it("paged: OF's next page is read when the last row scrolls into view; the observer then disconnects", () => {
    const seen = stubIO();
    const more = vi.fn();
    const doc = load("statistics/statements/earnings");
    const list = [tx({ createdAt: "2026-10-12T09:00:00+00:00", amount: 1 }), tx({ createdAt: "2026-10-11T09:00:00+00:00", amount: 2 })];
    applyTransactions(doc, list, D30, pg({ list, hasMore: true, more }));
    const last = [...doc.querySelectorAll(`${TABLE} tbody > tr[data-oi-data]`)].at(-1)!;
    expect(seen.map((s) => s.el)).toEqual([last]);
    seen[0].fire();
    expect(more).toHaveBeenCalledTimes(1);
    expect(seen[0].disconnected).toBe(true);
  });
  it("no more pages (or no rows): nothing observed", () => {
    const seen = stubIO();
    const doc = load("statistics/statements/earnings");
    applyTransactions(doc, [tx({ createdAt: "2026-10-12T09:00:00+00:00" })], D30, pg({ more: null }));
    applyTransactions(load("statistics/statements/earnings"), [], D30, pg({ hasMore: true, more: vi.fn() }));
    expect(seen).toEqual([]);
  });
  it("none in the period: \"Loading…\" while reading toward it; read to its start, stalled, or unpaged: the generator's text", () => {
    const empty = (paged?: Partial<PagedBody>, items: Transaction[] = []) => {
      const doc = load("statistics/statements/earnings");
      applyTransactions(doc, items, D30, paged);
      return texts(doc, `${TABLE} .empty-message`);
    };
    expect(empty(pg({ hasMore: true }))).toEqual(["Loading…"]);
    expect(empty(pg({ hasMore: false }))).toEqual([NOT_YET]);
    expect(empty(pg({ hasMore: true, stalled: true }))).toEqual([NOT_YET]);
    expect(empty(undefined)).toEqual([NOT_YET]);
    // A row from before the period was read: the period is complete, no rows to wait for.
    const old = [tx({ createdAt: "2026-08-01T10:00:00+00:00" })];
    expect(empty(pg({ list: old, hasMore: true }), old)).toEqual([NOT_YET]);
    // The fixture: OF's own page (hasMore false), rows years older than the last 30 days.
    const real = fixture<{ list: Transaction[]; hasMore: boolean }>("transactions");
    expect(empty(pg({ list: real.list, hasMore: real.hasMore }), real.list)).toEqual([NOT_YET]);
  });
  it("the fixture over All time: OF's six rows, the first May 19, 2026", () => {
    const real = fixture<{ list: Transaction[] }>("transactions");
    const doc = load("statistics/statements/earnings");
    applyTransactions(doc, real.list, ALL);
    const r = rows(doc, TABLE);
    expect(r.length).toBe(6);
    expect(r[0]).toEqual(["May 19, 2026,03:57 pm", "$63.91", "$63.28", "$33.68", "Subscription from Fan One"]);
  });
});

describe("applyPayouts: Payout Requests and Referrals' rows", () => {
  it("Payout Requests (fixture, All time): date, invoice, amount, OF's status and icon; Download invoice disabled with its data", () => {
    const doc = load("statistics/statements/payout-request");
    applyPayouts(doc, "payouts", fixture("payout-requests"), ALL);
    expect(rows(doc, "[data-oi-table='payouts']")).toEqual([
      ["Jan 26, 2025, 10:05 pm", "60000000", "$85.23", "Payout has been processed Download invoice"],
      ["Jun 05, 2024, 03:02 pm", "60000001", "$95.73", "Payout has been processed Download invoice"],
    ]);
    const tr = doc.querySelector("[data-oi-table='payouts'] tbody > tr")!;
    expect(tr.hasAttribute("data-oi-data")).toBe(true);
    expect(tr.querySelector(".approved")!.textContent).toBe(" Payout has been processed ");
    expect(tr.querySelector(".useable-icon.m-payout-cell.m-done use")!.getAttribute("href")).toBe("#icon-done");
    const dl = tr.querySelector<HTMLButtonElement>(".download-invoice-link")!;
    expect([dl.type, dl.disabled, dl.title, dl.getAttribute("data-oi-invoice"), dl.getAttribute("data-oi-refbonus")]).toEqual(["button", true, NOT_YET, "60000000", "0"]);
    expect(visible(doc.querySelector("[data-oi-table='payouts']")!)).toBe(true);
    expect(texts(doc, ".b-statistics-page-content__wrapper .empty-message")).toEqual([]);
  });
  it("each state: pending/new processing, rejected with its reason, unknown none; no invoice, a non-numeric one, $0 and no amount", () => {
    const doc = load("statistics/statements/payout-request");
    applyPayouts(doc, "payouts", { list: [
      payout({ state: "pending", invoiceId: 1, amount: 0.3 }),
      payout({ state: "new", invoiceId: null, amount: null }),
      payout({ state: "rejected", rejectReason: "Bank <b>declined</b>" }),
      payout({ state: "rejected", rejectReason: null }),
      payout({ state: "weird" }),
      payout({ state: "approved", invoiceId: "INV-7" }),
    ] }, D30);
    expect(rows(doc, "[data-oi-table='payouts']").map((r) => r.slice(1))).toEqual([
      ["1", "$0.30", "Payout request is being processed"],
      ["", "", "Payout request is being processed"],
      ["61000000", "$50.00", "Payout request could not be processed and this amount was returned to your Current Balance. Reason: Bank declined"],
      ["61000000", "$50.00", "Payout request could not be processed and this amount was returned to your Current Balance."],
      ["61000000", "$50.00", ""],
      ["INV-7", "$50.00", "Payout has been processed Download invoice"],
    ]);
    const trs = [...doc.querySelectorAll("[data-oi-table='payouts'] tbody > tr")];
    expect(trs[0].querySelector("td:nth-child(3) span")!.classList.contains("m-zero-value")).toBe(true);
    expect(trs[5].querySelector("td:nth-child(3) span")!.classList.contains("m-zero-value")).toBe(false);
    expect(trs[0].querySelector(".m-loading use")!.getAttribute("href")).toBe("#icon-loading");
    expect(trs[2].querySelector(".rejected br")).not.toBeNull();
    expect(trs[2].querySelector(".m-alert use")!.getAttribute("href")).toBe("#icon-alert");
    expect(trs[4].querySelector("td:last-child")!.childElementCount).toBe(0);
    // Download invoice only on approved; OF's link needs a numeric invoice id.
    expect(trs.map((t) => !!t.querySelector(".download-invoice-link"))).toEqual([false, false, false, false, false, true]);
    expect(trs[5].querySelector(".download-invoice-link")!.hasAttribute("data-oi-invoice")).toBe(false);
  });
  it("Referrals: OF's text without padding, the icon inside it, the refbonus flag on Download invoice", () => {
    const doc = load("statistics/statements/referrals/earnings");
    applyPayouts(doc, "referrals", { list: [payout({ invoiceId: 62000001 }), payout({ state: "rejected", rejectReason: "No" })] }, D30);
    const trs = [...doc.querySelectorAll("[data-oi-table='referrals'] tbody > tr")];
    const span = trs[0].querySelector("td:last-child > span.approved")!;
    expect(span.firstChild!.textContent).toBe("Payout has been processed");
    expect(span.querySelector(".b-state-icon use")!.getAttribute("href")).toBe("#icon-done");
    expect(trs[0].querySelector(".useable-icon")).toBeNull();
    expect(trs[0].querySelector(".download-invoice-link")!.getAttribute("data-oi-refbonus")).toBe("1");
    expect(trs[1].querySelector(".rejected .b-state-icon use")!.getAttribute("href")).toBe("#icon-alert");
    expect(squash(trs[1].querySelector(".rejected")!.textContent)).toMatch(/Reason: No$/);
    expect(visible(doc.querySelector("[data-oi-table='referrals']")!)).toBe(true);
  });
  it("BUG (pinned): Referrals with rows: the page's \"Not available\" text under the table stays visible", () => {
    // BUG: see PR — applyPayouts hides `.b-statistics-page-content__wrapper .empty-message` with querySelector, i.e. the
    // FIRST match; on Referrals that is the (already hidden) `[data-oi-referred-empty]`, so the referral payouts' own
    // `.empty-message[data-oi-ref-earnings]` stays next to the rows (also through applyStats). Correct: once rows are in,
    // no empty text is visible (this assertion becomes `[]`).
    const doc = load("statistics/statements/referrals/earnings");
    applyPayouts(doc, "referrals", { list: [payout()] }, D30);
    expect(texts(doc, ".empty-message[data-oi-ref-earnings]")).toEqual([NOT_YET]);
  });
  it("none in the period: the table stays hidden; no list or no table: no-op", () => {
    const doc = load("statistics/statements/payout-request");
    applyPayouts(doc, "payouts", fixture("payout-requests"), D30); // both requests are older
    expect(doc.querySelector<HTMLElement>("[data-oi-table='payouts']")!.style.display).toBe("none");
    expect(rows(doc, "[data-oi-table='payouts']")).toEqual([]);
    applyPayouts(doc, "payouts", null, ALL);
    applyPayouts(doc, "payouts", { nope: 1 }, ALL);
    applyPayouts(doc, "referrals", fixture("payout-requests"), ALL); // no Referrals table on this page
    expect(doc.querySelectorAll("tbody > tr[data-oi-data]").length).toBe(0);
  });
  it("BUG (pinned): none in the period yet more to read: no \"Loading…\" appears (the loading row is looked for under a div)", () => {
    // BUG: see PR — with no row in the period and more to read, applyPayouts passes the wrapper's `.empty-message` parent
    // <div> to loadingRow, which only looks for `:scope > tr .empty-message > span`; the payout pages have no such <tr>,
    // so it is a no-op and the generator's "Not available" text stays while older pages are still being read. Correct:
    // the empty text reads "Loading…" (as applyTransactions' does) until the period is read.
    const doc = load("statistics/statements/payout-request");
    applyPayouts(doc, "payouts", { list: [payout({ createdAt: "2026-10-30T00:00:00+00:00" })], hasMore: true }, D30);
    expect(texts(doc, ".b-statistics-page-content__wrapper .empty-message")).toEqual([NOT_YET]);
  });
  it("paged: the next page is read when the last row scrolls into view", () => {
    const seen = stubIO();
    const more = vi.fn();
    const doc = load("statistics/statements/payout-request");
    applyPayouts(doc, "payouts", { list: [payout(), payout({ invoiceId: "61000001" })], hasMore: true, loading: false, more }, D30);
    expect(seen.map((s) => s.el)).toEqual([doc.querySelector("[data-oi-table='payouts'] tbody")!.lastElementChild]);
    seen[0].fire();
    expect(more).toHaveBeenCalledTimes(1);
  });
});

describe("applyRatio: Chargebacks' \"Chargeback ratio N%\"", () => {
  const ratio = (doc: Document) => squash(doc.querySelector(".m-statistics-alert .alert-text-wrapper > p")!.textContent);
  it.each([
    [0, "0%"],
    [1.5, "1.5%"],
    [1.23456, "1.23%"],
    [0.005, "0.01%"],
    ["2.5", "2.5%"],
    [12345, "12345%"],
  ])("%s -> %s (OF's two places), replacing the generator's dash", (v, want) => {
    const doc = load("statistics/statements/disputes");
    expect(ratio(doc)).toBe("Chargeback ratio —");
    applyRatio(doc, { chargebacksRatio: v });
    expect(ratio(doc)).toBe(`Chargeback ratio ${want}`);
  });
  it("a new period replaces the previous ratio; no ratio (404, null, text): the page as it is", () => {
    const doc = load("statistics/statements/disputes");
    applyRatio(doc, fixture("chargebacks-ratio"));
    expect(ratio(doc)).toBe("Chargeback ratio 0%");
    applyRatio(doc, { chargebacksRatio: 3.333 });
    expect(ratio(doc)).toBe("Chargeback ratio 3.33%");
    for (const body of [undefined, null, {}, { chargebacksRatio: null }, { chargebacksRatio: "n/a" }]) applyRatio(doc, body);
    expect(ratio(doc)).toBe("Chargeback ratio 3.33%");
    // The tooltip's "under 1%" text is outside the swapped text: untouched.
    expect(doc.querySelector(".m-statistics-alert .g-icon-info")!.getAttribute("aria-label")).toMatch(/under 1%\.$/);
  });
});

describe("applyEarningsTabs: Statements › Earnings' type tabs", () => {
  it("each type: its tab current (no pointer, out of the tab order), the others not; Tips' sub-tabs only under Tips", () => {
    const doc = load("statistics/statements/earnings");
    const nav = () => doc.querySelector("[data-oi-pick='type:total']")!.closest(".b-tabs__nav")!;
    for (const type of TYPES) {
      applyEarningsTabs(doc, type);
      const tabs = [...doc.querySelectorAll<HTMLElement>("[data-oi-pick^='type:']:not([data-oi-href])")];
      expect(tabs.filter((b) => b.classList.contains("m-current")).map((b) => b.getAttribute("data-oi-pick")), type).toEqual([`type:${type}`]);
      for (const b of tabs) {
        const on = b.getAttribute("data-oi-pick") === `type:${type}`;
        expect([b.classList.contains("m-no-pointer"), b.getAttribute("tabindex")]).toEqual([on, on ? "-1" : "0"]);
      }
      const tips = type === "tips";
      expect(visible(doc.querySelector("[data-oi-tips-tabs]")!), type).toBe(tips);
      expect([nav().classList.contains("m-bottom-bordered"), nav().classList.contains("pb-0")], type).toEqual([tips, tips]);
    }
  });
  it("Tips then All: the sub-tabs hidden again, OF's tab row border back to its own", () => {
    const doc = load("statistics/statements/earnings");
    applyEarningsTabs(doc, "tips");
    expect(texts(doc, "[data-oi-tips-tabs] button")).toEqual(["All tips", "Profile", "Posts", "Messages", "Streams", "Stories"]);
    applyEarningsTabs(doc, "total");
    expect(texts(doc, "[data-oi-tips-tabs] button")).toEqual([]);
    expect(doc.querySelector("[data-oi-pick='type:total']")!.closest(".b-tabs__nav")!.classList.contains("m-bottom-bordered")).toBe(false);
  });
});

describe("applyStatements: the phase-2 parts per Statements page", () => {
  const MAIN = ".b-statistics-page-content__wrapper > .b-chart canvas.b-chart__double-line__main";
  const ASIDE = ".b-statistics-page-content__wrapper > .b-chart canvas.b-chart__double-line__aside";
  const tipsChart = (key: string) => {
    const c = fixture<{ tips: unknown }>("earnings-chart-tips").tips;
    return { [key]: c };
  };

  it("Earnings, v2: Tips' sub-tabs enabled with the picked one current; the chart titled by the sub-tab, over Transactions", () => {
    const doc = load("statistics/statements/earnings");
    applyStatements(doc, "statements/earnings", { earningsChart: tipsChart("tips_post") }, D30, ctx({ v2: true, type: "tips", picks: picks({ type: "tips", tips: "post" }) }));
    const subs = [...doc.querySelectorAll<HTMLButtonElement>("[data-oi-tips-tabs] button")];
    expect(subs.map((b) => [squash(b.textContent), b.disabled, b.hasAttribute("title"), b.classList.contains("m-current")])).toEqual([
      ["All tips", false, false, false], ["Profile", false, false, false], ["Posts", false, false, true],
      ["Messages", false, false, false], ["Streams", false, false, false], ["Stories", false, false, false],
    ]);
    const main = spec(doc, MAIN)!;
    expect([main.series.title, main.series.kind, main.series.values.reduce((a, b) => a + b, 0)]).toEqual(["Posts tips", "money", 12.5]);
    expect([spec(doc, ASIDE)!.series.title, spec(doc, ASIDE)!.series.kind]).toEqual(["Transactions", "count"]);
  });
  it.each(TYPES.filter((t) => t !== "tips").map((t) => [t] as const))("Earnings, %s: the chart titled Earnings", (type) => {
    const doc = load("statistics/statements/earnings");
    applyStatements(doc, "statements/earnings", { earningsChart: tipsChart(type) }, D30, ctx({ v2: true, type }));
    expect(spec(doc, MAIN)!.series.title).toBe("Earnings");
  });
  it("Earnings without v2: Tips' sub-tabs keep the generator's disabled state, no chart", () => {
    const doc = load("statistics/statements/earnings");
    applyStatements(doc, "statements/earnings", { earningsChart: [] }, D30, ctx({ type: "tips", picks: picks({ type: "tips" }) }));
    const rest = [...doc.querySelectorAll<HTMLButtonElement>("[data-oi-tips-tabs] button")].slice(1);
    expect(rest.every((b) => b.disabled && b.title === NOT_YET)).toBe(true);
    expect(spec(doc, MAIN)).toBeUndefined();
  });
  it("Earnings without a chart amount: no chart", () => {
    const doc = load("statistics/statements/earnings");
    applyStatements(doc, "statements/earnings", { earningsChart: { total: { total: 5, gross: 6 } } }, D30, ctx({ v2: true }));
    expect(spec(doc, MAIN)).toBeUndefined();
  });
  it("Earnings without a chart count: the main chart, no aside", () => {
    const doc = load("statistics/statements/earnings");
    const c = fixture<{ total: Record<string, unknown> }>("earnings-chart-zero").total;
    applyStatements(doc, "statements/earnings", { earningsChart: { total: { ...c, chartCount: undefined } } }, D30, ctx({ v2: true }));
    expect(spec(doc, MAIN)!.series.values.every((v) => v === 0)).toBe(true);
    expect(spec(doc, ASIDE)).toBeUndefined();
  });
  it("Chargebacks: a dispute without its payment has no description cell; dashes for missing dates", () => {
    const doc = load("statistics/statements/disputes");
    applyStatements(doc, "statements/disputes", { chargebacksList: { list: [{ id: 1, createdAt: "2026-10-03T10:00:00+00:00", payment: null }, { id: 2, payment: { amount: 3, fee: 0.6, net: 2.4, description: "A <i>tip</i>" } }], hasMore: false, loading: false, more: null } }, D30, ctx());
    expect(rows(doc, "[data-oi-table='disputes']")).toEqual([
      ["Oct 03, 2026 12:00 pm", "—", "", ""],
      ["—", "—", "$3.00", "$0.60 $2.40", "A tip"],
    ]);
    expect(texts(doc, "[data-oi-chartbox='disputes']")).toEqual([]); // no chart read
  });
  it("Earnings over the last 24 hours: the chart's hours in UTC (OF's), other periods in the owner's zone", () => {
    const pts = [{ date: "2026-10-16T22:00:00+00:00", count: 1 }, { date: "2026-10-16T23:00:00+00:00", count: 2 }];
    const labels = (p: typeof D30) => {
      const doc = load("statistics/statements/earnings");
      applyStatements(doc, "statements/earnings", { earningsChart: { total: { total: 3, chartAmount: pts, chartCount: pts } } }, p, ctx({ v2: true }));
      return spec(doc, MAIN)!.labels;
    };
    expect(labels(H24)).toEqual(["22:00", "23:00"]);
    expect(labels(D30)).toEqual(["0:00", "1:00"]); // Ljubljana, +02:00
  });
  it("Chargebacks over the last 24 hours: the chart's hours in UTC (OF's), other periods in the owner's zone", () => {
    // 22:00Z / 23:00Z are midnight and 1 am in Ljubljana (+02:00), the next day: the fixture's T00:00Z daily points
    // can't tell UTC from the owner's zone. The chart draws only with a row shown.
    const pts = [{ date: "2026-10-16T22:00:00+00:00", count: 1 }, { date: "2026-10-16T23:00:00+00:00", count: 2 }];
    const labels = (p: typeof D30) => {
      const doc = load("statistics/statements/disputes");
      applyStatements(doc, "statements/disputes", { chargebacksList: { list: [{ id: 1, payment: null }], hasMore: false, loading: false, more: null }, chargebacksChart: { total: 2, delta: 0, chartAmount: pts, chartCount: pts } }, p, ctx());
      return spec(doc, "[data-oi-chartbox='disputes'] canvas.b-chart__double-line__main")!.labels;
    };
    expect(labels(H24)).toEqual(["22:00", "23:00"]);
    expect(labels(D30)).toEqual(["0:00", "1:00"]); // Ljubljana, +02:00
  });
  it("Chargebacks with rows (fixture, 24 hours): OF's summary, change and chart, the last row observed", () => {
    const seen = stubIO();
    const more = vi.fn();
    const doc = load("statistics/statements/disputes");
    applyStatements(doc, "statements/disputes", { chargebacksList: { ...fixture<PagedBody>("chargebacks"), hasMore: true, loading: false, more }, chargebacksChart: fixture("chargebacks-chart") }, H24, ctx());
    // Row dates stay in the owner's zone; a $0 payment's figures are money, not dashes.
    expect(rows(doc, "[data-oi-table='disputes']")).toEqual([
      ["Oct 03, 2026 12:00 pm", "Sep 20, 2026 12:00 pm", "$5.00", "$1.00 $4.00", "Synthetic payment description"],
      ["Oct 01, 2026 10:30 am", "Sep 18, 2026 11:15 pm", "$0.00", "$0.00 $0.00", ""],
    ]);
    expect(texts(doc, "[data-oi-chartbox='disputes']")).toEqual(["$5.00 -50%"]);
    const main = spec(doc, "[data-oi-chartbox='disputes'] canvas.b-chart__double-line__main")!;
    expect([main.series.title, main.labels[0]]).toEqual(["Charged back", "Sep 17, 2026"]);
    expect(seen.map((s) => s.el)).toEqual([doc.querySelector("[data-oi-table='disputes'] tbody")!.lastElementChild]);
    seen[0].fire();
    expect(more).toHaveBeenCalledTimes(1);
  });
  it("Payout Requests: OF's summary and chart only while the table is shown", () => {
    const doc = load("statistics/statements/payout-request");
    const data = { payoutsChart: fixture("payouts-chart") };
    applyStatements(doc, "statements/payout-request", data, D30, ctx());
    expect(texts(doc, "[data-oi-chartbox='payouts']")).toEqual([]);
    applyPayouts(doc, "payouts", fixture("payout-requests"), ALL);
    applyStatements(doc, "statements/payout-request", data, ALL, ctx());
    expect(texts(doc, "[data-oi-chartbox='payouts'] .b-elements-determinant__value")).toEqual(["$85.23"]);
    expect(spec(doc, "[data-oi-chartbox='payouts'] canvas.b-chart__double-line__aside")!.series.title).toBe("Invoices");
  });
  it("Referrals: the chart's change marked except for All time; Referred tabs enabled only once their lists answer", () => {
    const chart = { ...fixture<Record<string, unknown>>("referrals-chart-zero"), total: 6, delta: -40 };
    let doc = load("statistics/statements/referrals/earnings");
    applyStatements(doc, "statements/referrals/earnings", { referralsChart: chart, referredCreators: { list: [], hasMore: false } }, D30, ctx());
    expect(texts(doc, ".b-separate-section.pt-0 .b-statistics-level")).toEqual(["-40%"]);
    const tab = (k: string) => doc.querySelector<HTMLElement>(`[data-oi-pick='ref:${k}']`)!;
    expect([tab("creators").hasAttribute("disabled"), tab("users").hasAttribute("disabled")]).toEqual([false, true]);
    expect(tab("earnings").classList.contains("m-current")).toBe(true);
    doc = load("statistics/statements/referrals/earnings");
    applyStatements(doc, "statements/referrals/earnings", { referralsChart: chart }, ALL, ctx());
    expect(doc.querySelector(".b-statistics-level")).toBeNull();
  });
  it("Download invoice: enabled only with v2; a click reads OF's file through the Relay with its refbonus flag, then a note", async () => {
    const blob = new Blob(["%PDF"]);
    vi.mocked(relayFile).mockResolvedValue({ blob, name: "inv.pdf" });
    const created = vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:x");
    vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
    const doc = load("statistics/statements/referrals/earnings");
    applyPayouts(doc, "referrals", { list: [payout()] }, D30);
    applyStatements(doc, "statements/referrals/earnings", {}, D30, ctx());
    const dl = doc.querySelector<HTMLButtonElement>("button[data-oi-invoice]")!;
    expect(dl.disabled).toBe(true);
    dl.click();
    expect(relayFile).not.toHaveBeenCalled();
    applyStatements(doc, "statements/referrals/earnings", {}, D30, ctx({ v2: true, accountId: "7" }));
    expect([dl.disabled, dl.hasAttribute("title"), dl.hasAttribute("data-oi-wired")]).toEqual([false, false, true]);
    dl.click();
    expect(dl.disabled).toBe(true); // while reading
    expect(relayFile).toHaveBeenCalledWith("/api/of/v2/payouts/download-approved-invoice?invoiceId=61000000&isRefbonus=1", { accountId: "7" });
    await vi.waitFor(() => expect(dl.disabled).toBe(false));
    expect(created).toHaveBeenCalledWith(blob);
    expect(doc.getElementById("oi-note")!.textContent).toContain("Invoice downloaded");
  });

  describe("Referrals › Referred creators / users: OF's child page instead of the referral payouts", () => {
    const REFERRED = "[data-oi-table='referred']";
    const wrapper = (doc: Document) => doc.querySelector(".b-statistics-page-content__wrapper")!;
    const refData = (body: Partial<PagedBody>, key: "referredCreators" | "referredUsers" = "referredCreators"): StatsData => ({ [key]: body });

    it("Referred creators: a row per creator (OF's fan cell, Joined in the owner's zone, Earnings), the payouts part hidden", () => {
      const doc = load("statistics/statements/referrals/earnings");
      applyStatements(doc, "statements/referrals/earnings", refData(fixture("referred-creators")), D30, ctx({ picks: picks({ ref: "creators" }) }));
      expect(rows(doc, REFERRED)).toEqual([
        ["SC Synthetic Creator F @u_synthetic_f", "Sep 1, 2026", "$12.40"],
        ["u900010 @u900010", "Aug 15, 2026", "$0.00"],
      ]);
      const trs = [...doc.querySelectorAll(`${REFERRED} tbody > tr[data-oi-data]`)];
      expect(trs[1].querySelector("td:last-child > span")!.classList.contains("m-zero-value")).toBe(true);
      expect(trs[0].querySelector("td:last-child > span")!.classList.contains("m-zero-value")).toBe(false);
      expect(visible(doc.querySelector(REFERRED)!)).toBe(true);
      expect([...doc.querySelectorAll("[data-oi-ref-earnings]")].filter(visible)).toEqual([]);
      expect(visible(doc.querySelector("[data-oi-referred-empty]")!)).toBe(false);
      expect(wrapper(doc).classList.contains("m-empty-wrapper")).toBe(false);
      const tab = (k: string) => doc.querySelector(`[data-oi-pick='ref:${k}']`)!;
      expect([tab("earnings").classList.contains("m-current"), tab("creators").classList.contains("m-current")]).toEqual([false, true]);
    });
    it("Referred users: read from its own list; a join date missing: OF's dash", () => {
      const doc = load("statistics/statements/referrals/earnings");
      const users = { list: [{ id: 1, name: "User One", username: "u_one", avatar: null, earnings: 3 }], hasMore: false };
      applyStatements(doc, "statements/referrals/earnings", { ...refData(fixture("referred-creators")), ...refData(users, "referredUsers") }, D30, ctx({ picks: picks({ ref: "users" }) }));
      expect(rows(doc, REFERRED)).toEqual([["UO User One @u_one", "—", "$3.00"]]);
    });
    it("an empty list and no more: OF's \"No data during selected period\", the table hidden, the empty wrapper", () => {
      const doc = load("statistics/statements/referrals/earnings");
      applyStatements(doc, "statements/referrals/earnings", refData(fixture("referred-empty")), D30, ctx({ picks: picks({ ref: "creators" }) }));
      expect(texts(doc, "[data-oi-referred-empty]")).toEqual(["No data during selected period"]);
      expect(visible(doc.querySelector(REFERRED)!)).toBe(false);
      expect(wrapper(doc).classList.contains("m-empty-wrapper")).toBe(true);
    });
    it("an empty list with more to read: no empty claim yet", () => {
      const doc = load("statistics/statements/referrals/earnings");
      applyStatements(doc, "statements/referrals/earnings", refData({ list: [], hasMore: true }), D30, ctx({ picks: picks({ ref: "creators" }) }));
      expect(texts(doc, "[data-oi-referred-empty]")).toEqual([]);
      expect(visible(doc.querySelector(REFERRED)!)).toBe(false);
    });
    it("paged: the last row observed, the next page read when it scrolls into view", () => {
      const seen = stubIO();
      const more = vi.fn();
      const doc = load("statistics/statements/referrals/earnings");
      applyStatements(doc, "statements/referrals/earnings", refData({ ...fixture<PagedBody>("referred-creators"), hasMore: true, more }), D30, ctx({ picks: picks({ ref: "creators" }) }));
      expect(seen.map((s) => s.el)).toEqual([doc.querySelector(`${REFERRED} tbody`)!.lastElementChild]);
      seen[0].fire();
      expect(more).toHaveBeenCalledTimes(1);
    });
    it("the list not read yet: the payouts part hidden, nothing drawn", () => {
      const doc = load("statistics/statements/referrals/earnings");
      applyStatements(doc, "statements/referrals/earnings", {}, D30, ctx({ picks: picks({ ref: "creators" }) }));
      expect([...doc.querySelectorAll("[data-oi-ref-earnings]")].filter(visible)).toEqual([]);
      expect(doc.querySelectorAll(`${REFERRED} tbody > tr[data-oi-data]`)).toHaveLength(0);
      expect(visible(doc.querySelector(REFERRED)!)).toBe(false);
    });
  });
});
