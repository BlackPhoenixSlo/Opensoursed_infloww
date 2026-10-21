"use client";

/**
 * Statistics › Statements with the phase-2 Relay reads (omf-statistics-relay), read only once useOfStats' probe finds
 * that Relay; until then the page keeps the generator's honest state:
 * - Earnings: OF's chart for the type tab (`/earnings/chart`, `filter=<c>_count,<c>_amount`: the amount over the
 *   transactions, statistics-earnings.js) and the Tips sub-tabs (OF's `tipsSource`, read by the transactions' marker paging);
 * - Chargebacks: OF's disputes table (`/payouts/chargebacks`, by marker) and, with rows, its summary and chart
 *   ("Charged back" over "Disputes", `/payouts/chargebacks/chart`);
 * - Payout Requests: with rows, the summary and chart ("Paid out" over "Invoices", `/payouts/chart`), and "Download
 *   invoice" (`/payouts/download-approved-invoice`, OF's file, saved as the browser saves a download);
 * - Referrals: the summary and chart ("Earnings" over "Referrals", `/payouts/referrals/chart`) and the Referred creators /
 *   Referred users tabs (`/users/me/referrals?onlyPerformers=1|0`: Name, Joined, Earnings).
 */

import { relayFile } from "@/lib/relay";
import { make, plain, valid } from "@/lib/ofMirrorData";
import type { Transaction } from "@/lib/ofMirrorFeeds";
import { NOT_YET, note } from "@/lib/ofMirrorWrites";
import type { Period } from "@/lib/ofMirrorStatsPeriod";
import { TIPS_SOURCES, inPeriod, listOf, pagedDone, valueOf, type EarningsType, type PagedBody, type PayoutRow, type Picks, type StatsData } from "@/lib/ofMirrorStatsSources";
import { add, at, cell, dateOf, dayText, display, elOf, enable, iconOf, isObj, level, loadingRow, money, moreAt, num, pickTabs, setClass, swapIn, timeText, zero } from "@/lib/ofMirrorStatsDom";
import { drawLine, drawPair, earningsSeries, fanCell, fillChartBox, intoRows, rowsOrEmpty } from "@/lib/ofMirrorStatsKit";
import type { Fan } from "@/lib/ofMirrorAvatar";
import { usd } from "@/lib/ofMirrorMoney";

/** OF's key for the tab's chart in the reply (statistics-earnings.js `currentTab.key`). */
const chartTab = (type: EarningsType, tips = "all") => (type === "tips" && tips !== "all" ? `tips_${tips}` : type);

/** Each type's figures in `/users/me/stats/overview` (the Statements sidebar's): its summary on Statements › Earnings. */
const TYPE_FIGURES: Record<EarningsType, string> = {
  total: "earnings:earning",
  subscribes: "fans:fans.earnings",
  tips: "derived:tips",
  post: "posts:posts.earnings",
  chat_messages: "messages:massMessages.earnings",
  stream: "streams:streams.earnings",
};


/** Statements › Earnings' summary follows its type tab: the overview's figures for that type. */
export const rekeyFor = (type: EarningsType, chart = false) => (el: Element, key: string) =>
  !key.startsWith("earnings:earning.") || !el.closest(".b-statistics-page-content__wrapper") ? key
  : chart ? `series:${key.slice("earnings:earning.".length)}` // OF's own: the tab's chart
  : type !== "total" ? TYPE_FIGURES[type] + key.slice("earnings:earning".length) : key;
/** Referrals' summary: its chart's total and change once the Relay reads it (OF's), else the derived $0.00. */
export const rekeyReferrals = (chart: boolean) => (_el: Element, key: string) => (chart && key.startsWith("derived:ref.") ? `referralsChart:${key.slice("derived:ref.".length)}` : key);

/** The Statements sidebar's Earnings: OF's categories with earnings in the period (StatementsStatistics). */
const CATEGORIES: [string, string, EarningsType][] = [
  ["Total", "earnings:earning", "total"],
  ["Subscriptions", "fans:fans.earnings", "subscribes"],
  ["Tips", "derived:tips", "tips"],
  ["Messages", "messages:massMessages.earnings", "chat_messages"],
  ["Posts", "posts:posts.earnings", "post"],
  ["Streams", "streams:streams.earnings", "stream"],
];
/** OF's sidebar rows from its own charts (StatementsStatistics' chartsSettings: key, title, line colour). */
const SIDE: [key: string, title: string, color: string][] = [
  ["total", "Total", "#8A96A3"], ["subscribes", "Subscriptions", "#7CB342"], ["tips", "Tips", "#9575CD"],
  ["chat_messages", "Messages", "#00AFF0"], ["post", "Posts", "#FFA000"], ["stream", "Streams", "#EC407A"],
];
const hasCounts = (v: unknown) => Array.isArray(v) && v.some((x) => num(at(x, "count")));

/**
 * The Statements sidebar's Earnings. With the phase-2 Relay, OF's own (statistics-statements.js StatementsStatistics and
 * StatementsStatisticsItem): a row per category whose chart has a non-zero point (its total, its change except for All
 * time, and its DetailLineChart: the amounts as a line in the category's colour; OF's sparkline has no tooltip, its
 * points' hit radius is 0, app.js 985738 `$r`); no category total: OF's "No earnings for this period". Else the
 * overview's figures per category, no line.
 */
export function applyEarningsAside(doc: Document, data: StatsData, p: Period) {
  const tpl = doc.querySelector<HTMLElement>("[data-oi-template='earning']");
  if (!tpl) return;
  const side = isObj(data.earningsSide) ? data.earningsSide : null;
  type Row = { label: string; v: number; d: number | null; type: EarningsType; chart?: unknown; color?: string };
  const rows: Row[] = [];
  if (side)
    for (const [key, label, color] of SIDE) {
      const c = side[key];
      if (isObj(c) && c.chartAmount && c.chartCount && (hasCounts(c.chartAmount) || hasCounts(c.chartCount)))
        rows.push({ label, v: num(c.total) ?? 0, d: num(c.delta), type: key as EarningsType, chart: c.chartAmount, color });
    }
  else
    for (const [label, key, type] of CATEGORIES) {
      const v = valueOf(data, `${key}.total`);
      if (v !== null && !zero(v)) rows.push({ label, v, d: valueOf(data, `${key}.delta`), type });
    }
  const total = side ? (SIDE.some(([k]) => num(at(side[k], "total"))) ? 1 : 0) : valueOf(data, "earnings:earning.total");
  if (total === null) return;
  display(doc, doc.querySelector<HTMLElement>("[data-oi-earnings-empty]"), zero(total));
  if (zero(total)) return;
  let after: Element = tpl;
  for (const { label, v, d, type, chart, color } of rows) {
    const el = make(tpl);
    el.style.removeProperty("display");
    // OF's row opens Statements › Earnings on its type tab (StatementsStatisticsItem's changeTab).
    el.setAttribute("data-oi-pick", `type:${type}`);
    el.setAttribute("data-oi-href", "/of-manager/statistics/statements/earnings");
    el.classList.add("g-pointer-cursor");
    const name = el.querySelector(".b-elements-determinant__label");
    if (name) name.textContent = ` ${label} `;
    const value = el.querySelector(".b-elements-determinant__value");
    const span = value?.querySelector(":scope > span"); // the template's money slot (make drops its data-oi-money)
    if (span) {
      span.textContent = ` ${usd(v)} `;
      span.classList.toggle("m-zero-value", Math.round(v) === 0);
    }
    if (value && d && p.key !== "all") value.append(level(doc, d, true)); // OF prints this change as it is
    const box = el.querySelector<HTMLElement>(".b-elements-determinant__unit.m-chart");
    add(doc, el, after, "after");
    after = el;
    if (chart && color) drawLine(doc, box?.querySelector("canvas"), [chart, label, "money"], color, 0, false, p.tz);
    else box?.remove();
  }
}

/** OF's money cell text (" $1.00 "); none: empty. */
const dollars = (v: unknown) => (money(v) ? ` ${money(v)} ` : "");

/** Statements › Earnings: OF's rows for the period (a captured row per status as the template), read by pages. */
export function applyTransactions(doc: Document, items: Transaction[], p: Period, paged?: Partial<PagedBody>) {
  const rows = items.filter((t) => inPeriod(t.createdAt, p));
  const tpl = (k: string) => doc.querySelector<HTMLElement>(`.b-statements-table tbody > tr[data-oi-template='${k}']`);
  intoRows(doc, (tpl("done") ?? tpl("loading"))?.parentElement, rows, (t) => (t.status === "loading" ? tpl("loading") : tpl("done")) ?? tpl("done") ?? tpl("loading"), (el, t) => {
    const when = valid(t.createdAt)!;
    const [day, time] = el.querySelectorAll(".m-width-statements strong > span");
    if (day) day.textContent = `${dayText(when, p.tz)},`; // OF's "Oct 06, 2026,"
    if (time) time.textContent = timeText(when, p.tz);
    for (const [i, v] of [
      [1, t.amount],
      [2, t.fee],
    ] as const) {
      const span = cell(el, i)?.querySelector("span");
      if (span) span.textContent = dollars(v);
    }
    const net = cell(el, 3)?.querySelector("strong > span");
    if (net) net.textContent = dollars(t.net);
    const desc = el.querySelector(".b-statements-text-table");
    if (desc) desc.textContent = plain(t.description);
    const tip = el.querySelector(".b-table__status-tip");
    if (tip && t.status === "loading") {
      if (t.payoutPendingDays == null) tip.removeAttribute("aria-label");
      else tip.setAttribute("aria-label", `Earning will become available in ${t.payoutPendingDays} days`);
    } else if (tip && t.status !== "done") tip.remove();
  });
  const body = (tpl("done") ?? tpl("loading"))?.parentElement;
  const last = [...(body?.querySelectorAll(":scope > tr[data-oi-data]") ?? [])].at(-1);
  if (paged?.more && last) moreAt(doc, last, paged.more);
  // Still reading toward the period: "Loading…"; reading stopped short of it: the generator's text, no claim.
  if (!rows.length && paged && !paged.stalled && !pagedDone(paged, p)) loadingRow(doc, body);
}


/** OF's "MMM DD, YYYY, hh:mm a" in `tz`. */
const payoutDate = (d: Date, tz: string | null) => `${dayText(d, tz)}, ${timeText(d, tz)}`;
/** OF's status copy (texts_en.json) and icon per payout state (getStatusIcon). */
const PAYOUT_STATES: Record<string, [cls: string, text: string, icon: string]> = {
  new: ["pending", "Payout request is being processed", "loading"],
  pending: ["pending", "Payout request is being processed", "loading"],
  rejected: ["rejected", "Payout request could not be processed and this amount was returned to your Current Balance.", "alert"],
  approved: ["approved", "Payout has been processed", "done"],
};

/**
 * Payout Requests (`kind` payouts) and Referrals (referrals): OF's table rows for the period's payouts
 * (StatisticsStatementsPayoutRequests, StatementsReferralsEarnings): the date in the owner's time zone, the invoice,
 * the amount and OF's status (its text, a rejection's "Reason: …", its icon); "Download invoice" (OF's link to its own
 * invoice file, no Relay route) is disabled with the tooltip. The next page is read when the last row scrolls into view.
 */
export function applyPayouts(doc: Document, kind: "payouts" | "referrals", body: unknown, p: Period) {
  const wrap = doc.querySelector<HTMLElement>(`[data-oi-table='${kind}']`);
  const tbody = wrap?.querySelector("tbody");
  const list = listOf<PayoutRow>(body);
  if (!wrap || !tbody || !list) return;
  const rows = list.filter((r) => inPeriod(r.createdAt, p));
  if (!rows.length) {
    if (!(body as Partial<PagedBody>).stalled && !pagedDone(body, p)) loadingRow(doc, doc.querySelector(".b-statistics-page-content__wrapper")?.querySelector(":scope .empty-message")?.parentElement);
    return;
  }
  const el = elOf(doc);
  const icon = (name: string) => iconOf(doc, name, `icon-${name} g-icon`);
  for (const r of rows) {
    const tr = el("tr", "m-responsive__reset-pb");
    tr.dataset.oiData = "";
    const date = el("td", "m-responsive__before-line-over m-width-statements");
    date.append(el("strong", "", ` ${payoutDate(valid(r.createdAt)!, p.tz)} `));
    const invoice = el("td", "m-responsive__before-line-over", r.invoiceId == null ? "" : ` ${r.invoiceId} `);
    const amount = el("td", "m-responsive__before-line-over m-last-in-row");
    const n = num(r.amount);
    const strong = el("strong");
    strong.append(el("span", n !== null && Math.round(n) === 0 ? "m-zero-value" : "", n === null ? "" : ` ${usd(n)} `));
    amount.append(strong);
    const status = el("td", "m-responsive__border-line__over text-left m-payout-cell m-payout-cell-with-download");
    const state = PAYOUT_STATES[r.state ?? ""];
    if (state) {
      const [cls, text, name] = state;
      const span = el("span", cls, kind === "payouts" ? ` ${text} ` : text);
      const reason = plain(r.rejectReason);
      if (r.state === "rejected" && reason) span.append(el("br"), doc.createTextNode(`Reason: ${reason}`));
      if (kind === "referrals") {
        // OF's referrals description: the icon inside the status text.
        const holder = el("span", "b-state-icon");
        holder.append(icon(name));
        span.append(holder);
        status.append(span);
      } else {
        status.append(span);
        const holder = el("div", `useable-icon m-payout-cell m-${name}`);
        holder.append(icon(name));
        status.append(holder);
      }
      if (r.state === "approved") {
        const dl = el("button", "download-invoice-link g-btn m-flat m-btn-gaps m-ex-sm", " Download invoice ") as HTMLButtonElement;
        dl.type = "button";
        dl.disabled = true;
        dl.title = NOT_YET;
        // OF's link to the invoice file (887384): with the phase-2 Relay, ofMirrorStatsStatements enables it.
        if (/^\d+$/.test(String(r.invoiceId ?? ""))) {
          dl.setAttribute("data-oi-invoice", String(r.invoiceId));
          dl.setAttribute("data-oi-refbonus", kind === "referrals" ? "1" : "0");
        }
        status.append(dl);
      }
    }
    tr.append(date, invoice, amount, status);
    add(doc, tr, tbody, "append");
  }
  display(doc, wrap, true);
  display(doc, doc.querySelector<HTMLElement>(".b-statistics-page-content__wrapper .empty-message"), false);
  const paged = body as Partial<PagedBody>;
  moreAt(doc, tbody.lastElementChild, paged.more);
}


/** Statements › Earnings' type tabs: OF's current tab, Tips' sub-tabs under it while Tips is picked. */
export function applyEarningsTabs(doc: Document, type: EarningsType) {
  pickTabs(doc, "type", type);
  const tips = type === "tips";
  display(doc, doc.querySelector<HTMLElement>("[data-oi-tips-tabs]"), tips);
  const first = doc.querySelector("[data-oi-pick^='type:']:not([data-oi-href])")?.closest(".b-tabs__nav");
  if (first) {
    setClass(doc, first, "m-bottom-bordered", tips);
    setClass(doc, first, "pb-0", tips);
  }
}

/** Chargebacks: "Chargeback ratio N%" for the period (OF rounds to two places; none: 0%). */
export function applyRatio(doc: Document, body: unknown) {
  const ratio = num(at(body, "chargebacksRatio"));
  if (ratio === null) return;
  for (const el of doc.querySelectorAll(".m-statistics-alert .alert-text-wrapper > p")) swapIn(doc, el, /\d[\d.,]*%|—/, `${Math.round(ratio * 100) / 100}%`);
}


export interface StatementsCtx {
  picks: Picks;
  v2: boolean;
  type: EarningsType;
  accountId?: string | null;
  img?: (u: string) => string;
}

/** Statements › Earnings' figures from its chart (OF's summary: the chart's total, gross and change), else null. */
export function statementsSeries(data: StatsData, type: EarningsType, tips: string) {
  const s = earningsSeries(data.earningsChart, chartTab(type, tips));
  return s && s.total !== null ? { total: s.total, gross: s.gross, delta: s.delta } : null;
}

function earningsPage(doc: Document, data: StatsData, p: Period, x: StatementsCtx) {
  const tipsNav = doc.querySelector<HTMLElement>("[data-oi-tips-tabs]");
  if (tipsNav && x.v2) {
    for (const b of tipsNav.querySelectorAll("[data-oi-enable]")) enable(doc, b);
    pickTabs(doc, "tips", x.picks.tips);
  }
  const s = earningsSeries(data.earningsChart, chartTab(x.type, x.picks.tips));
  if (!s?.amount) return;
  const title = x.type === "tips" ? TIPS_SOURCES[x.picks.tips]?.[1] ?? "Earnings" : "Earnings";
  const tz = p.key === "24h" ? "UTC" : p.tz;
  drawPair(doc, doc.querySelector(".b-statistics-page-content__wrapper > .b-chart"), [s.amount, title, "money"], s.count ? [s.count, "Transactions", "count"] : null, tz);
}

/** A money cell's value (OF's utils-money: a span, `m-zero-value` when it rounds to $0). */
function moneySpan(doc: Document, v: unknown) {
  const n = num(v);
  const span = elOf(doc)("span", n !== null && Math.round(n) === 0 ? "m-zero-value" : "", n === null ? "" : ` ${usd(n)} `);
  return span;
}

interface Dispute {
  id?: unknown;
  createdAt?: string;
  payment?: { createdAt?: string; amount?: unknown; fee?: unknown; net?: unknown; description?: string | null } | null;
}

/** Chargebacks: OF's StatisticsStatementsDisputes table, its summary and chart while it has rows. */
function disputesPage(doc: Document, data: StatsData, p: Period) {
  const body = data.chargebacksList as Partial<PagedBody> | undefined;
  const list = (body?.list ?? null) as Dispute[] | null;
  const table = doc.querySelector<HTMLElement>("[data-oi-table='disputes']");
  const tbody = table?.querySelector("tbody");
  const empty = doc.querySelector(".b-statistics-page-content__wrapper > .empty-message [data-oi-empty]");
  if (!list || !tbody) return;
  const el = elOf(doc);
  const both = (d: Date | null, strong: boolean) => {
    const holder = strong ? el("strong") : el("span");
    if (!d) holder.textContent = " — ";
    else holder.append(doc.createTextNode(` ${dayText(d, p.tz)} `), el("br"), doc.createTextNode(` ${timeText(d, p.tz)} `));
    return holder;
  };
  for (const r of list) {
    const tr = el("tr", "m-responsive__reset-pb");
    tr.dataset.oiData = "";
    const made = el("td", "m-responsive__before-line-over m-width-statements");
    made.append(both(dateOf(r.createdAt), true));
    const paid = el("td", "m-responsive__before-line-over");
    paid.append(both(dateOf(r.payment?.createdAt), false));
    const amount = el("td", "m-responsive__before-line-over");
    amount.append(moneySpan(doc, r.payment?.amount));
    const net = el("td", "m-responsive__before-line-over m-last-in-row");
    const strong = el("strong");
    strong.append(moneySpan(doc, r.payment?.net));
    net.append(moneySpan(doc, r.payment?.fee), el("br"), strong);
    tr.append(made, paid, amount, net);
    if (r.payment) {
      const desc = el("td", "m-responsive__border-line__over text-left");
      desc.append(el("div", "b-statements-text-table", plain(r.payment.description)), el("div", "b-table-group-btns"));
      tr.append(desc);
    }
    add(doc, tr, tbody);
  }
  rowsOrEmpty(doc, table, empty, list.length, !body?.hasMore);
  moreAt(doc, tbody.lastElementChild, body?.more);
  const c = data.chargebacksChart;
  if (list.length && isObj(c))
    fillChartBox(doc, "disputes", num(c.total), num(c.delta), true, [c.chartAmount, "Charged back", "money"], [c.chartCount, "Disputes", "count"], p.key === "24h" ? "UTC" : p.tz, p.key !== "all");
}

/** Payout Requests: with the period's rows shown, OF's summary and chart. */
function payoutsPage(doc: Document, data: StatsData, p: Period) {
  const shown = doc.querySelector<HTMLElement>("[data-oi-table='payouts']");
  const c = data.payoutsChart;
  if (!shown || shown.style.display === "none" || !isObj(c)) return;
  fillChartBox(doc, "payouts", num(c.total), num(c.delta), true, [c.chartAmount, "Paid out", "money"], [c.chartCount, "Invoices", "count"], p.key === "24h" ? "UTC" : p.tz, p.key !== "all");
}

/** Referrals: the chart and its summary (OF's for every tab), the Referred creators / users tabs. */
function referralsPage(doc: Document, data: StatsData, p: Period, x: StatementsCtx) {
  const c = data.referralsChart;
  const wrapper = doc.querySelector(".b-statistics-page-content__wrapper");
  if (isObj(c)) {
    const box = wrapper?.querySelector(".b-separate-section.pt-0");
    drawPair(doc, box, [c.chartAmount, "Earnings", "money"], [c.chartCount, "Referrals", "count"], p.key === "24h" ? "UTC" : p.tz);
    const d = num(c.delta);
    const holder = box?.querySelector(".b-elements-determinant__value");
    if (holder && d && p.key !== "all") add(doc, level(doc, d, true), holder);
  }
  const tabs: [key: string, source: "referredCreators" | "referredUsers"][] = [["creators", "referredCreators"], ["users", "referredUsers"]];
  for (const [key, source] of tabs) {
    const b = doc.querySelector(`[data-oi-pick='ref:${key}']`);
    if (b && Array.isArray((data[source] as Partial<PagedBody> | undefined)?.list)) enable(doc, b);
  }
  const tab = x.picks.ref;
  pickTabs(doc, "ref", tab);
  if (tab === "earnings") return;
  // Referred creators / users: OF's child page instead of the referral payouts (its notice, table and empty row).
  for (const el of doc.querySelectorAll<HTMLElement>("[data-oi-ref-earnings]")) display(doc, el, false);
  const body = data[tab === "creators" ? "referredCreators" : "referredUsers"] as Partial<PagedBody> | undefined;
  const table = doc.querySelector<HTMLElement>("[data-oi-table='referred']");
  const tbody = table?.querySelector("tbody");
  const empty = doc.querySelector<HTMLElement>("[data-oi-referred-empty]");
  if (!body?.list || !tbody) return;
  const el = elOf(doc);
  for (const u of body.list as (Fan & { joinDate?: string; earnings?: unknown })[]) {
    const tr = el("tr", "m-responsive__reset-pb m-responsive__grid m-cols-1fr-auto");
    tr.dataset.oiData = "";
    const joined = dateOf(u.joinDate);
    const earned = el("td", "m-responsive__grid__data-cell text-right");
    earned.append(moneySpan(doc, u.earnings));
    tr.append(fanCell(doc, u, x.img), el("td", "m-responsive__grid__data-cell", joined ? ` ${dayText(joined, p.tz, false)} ` : " — "), earned);
    add(doc, tr, tbody);
  }
  display(doc, table, body.list.length > 0);
  display(doc, empty, !body.list.length && !body.hasMore);
  if (wrapper) setClass(doc, wrapper, "m-empty-wrapper", !body.list.length);
  moreAt(doc, tbody.lastElementChild, body.more);
}

/** The Statements tabs' phase-2 parts for page `sub`. */
export function applyStatements(doc: Document, sub: string, data: StatsData, p: Period, x: StatementsCtx) {
  if (sub === "statements/earnings") earningsPage(doc, data, p, x);
  if (sub === "statements/disputes") disputesPage(doc, data, p);
  if (sub === "statements/payout-request") payoutsPage(doc, data, p);
  if (sub === "statements/referrals/earnings") referralsPage(doc, data, p, x);
  if (x.v2) for (const b of doc.querySelectorAll("button[data-oi-invoice]")) enable(doc, b);
  bindInvoices(doc, x);
}

const invoiceCtx = new WeakMap<Document, StatementsCtx>();
/** "Download invoice": OF's invoice file through the Relay, saved by the browser; no file: a note. Bound once per page. */
function bindInvoices(doc: Document, x: StatementsCtx) {
  const bound = invoiceCtx.has(doc);
  invoiceCtx.set(doc, x);
  if (bound) return;
  doc.addEventListener("click", (ev) => {
    const b = (ev.target as Element | null)?.closest?.<HTMLButtonElement>("button[data-oi-invoice]");
    if (!b || b.disabled) return;
    const id = b.getAttribute("data-oi-invoice")!;
    const ref = b.getAttribute("data-oi-refbonus") === "1" ? 1 : 0;
    const ctx = invoiceCtx.get(doc);
    b.disabled = true;
    relayFile(`/api/of/v2/payouts/download-approved-invoice?invoiceId=${encodeURIComponent(id)}&isRefbonus=${ref}`, { accountId: ctx?.accountId })
      .then(({ blob, name }) => {
        const url = URL.createObjectURL(blob);
        const a = doc.createElement("a");
        a.href = url;
        a.download = name ?? `invoice-${id}.pdf`;
        a.style.display = "none";
        doc.body.append(a);
        a.click();
        a.remove();
        setTimeout(() => URL.revokeObjectURL(url), 60_000);
        note(doc, b, "Invoice downloaded");
      })
      .catch(() => note(doc, b, "Couldn't download the invoice", true))
      .finally(() => (b.disabled = false));
  });
}
