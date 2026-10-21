"use client";

/**
 * Statistics › Fans with the phase-2 Relay reads (omf-statistics-relay), read only once useOfStats' probe finds that
 * Relay; until then the page keeps the generator's honest state:
 * - Subscriptions: OF's All / Renews / New subscribers tabs, the tab's chart and summary (`/subscriptions/subscribers/chart
 *   ?by=`: "<n> Subscribers", the earnings and their change) and table (`/subscriptions/subscribers/latest?by=`: the fan,
 *   price or "free", total duration / renew date / subscription date; an expired one grey);
 * - Top fans: OF's Total / Subscriptions / Tips / Messages / Posts / Streams tabs and table
 *   (`/subscriptions/subscribers/top?by=`: the fan, the tab's sum, the total);
 * - Fans activity: OF's "Subscribers activity" sectors chart (`/fans-activity/list?format=table`) and "Most active hours"
 *   bars (`format=hours`), each hour's share, with OF's tooltips (ofMirrorChart). OF's "Data available starting from"
 *   alert reads `/init`'s fansActivityDate, which the Relay grants Home only: not shown;
 * - every Fans tab's sidebar Top Fan card (`/users/me/stats/top/fan`): the fan, the category tabs, OF's Subscription and
 *   Earnings details. The fan's actions (Lists, Discount, Restrict, Add notes, More) stay disabled: Inflowwww has no
 *   write for them (app/lib/ofMirrorWrites.ts).
 */

import { clearFans, drawBars, drawSectors, sectorsOf } from "@/lib/ofMirrorChart";
import { plain } from "@/lib/ofMirrorData";
import type { Period } from "@/lib/ofMirrorStatsPeriod";
import type { PagedBody, Picks, StatsData } from "@/lib/ofMirrorStatsSources";
import { add, at, dateOf, display, elOf, enable, isObj, level, moreAt, num, pickTabs, setClass, setText, swapIn, track, dayText } from "@/lib/ofMirrorStatsDom";
import { fanCell, topItems } from "@/lib/ofMirrorStatsKit";
import { avatarOf, type Fan } from "@/lib/ofMirrorAvatar";
import { FANS_FAN_TABS, fanSum } from "@/lib/ofMirrorStatsOverview";
import { usd } from "@/lib/ofMirrorMoney";

export interface FansCtx {
  picks: Picks;
  v2: boolean;
  img?: (u: string) => string;
}

/** Fans › Subscriptions' third column per tab (OF's durationText). */
const SUBS_COLUMN: Record<string, string> = { total: "Total duration", renew: "Renew date", new: "Subscription date" };
/** Top fans' tabs: their title and sum (statistics-fans-top.js). */
const TOP_TABS: Record<string, [title: string, field: string]> = {
  total: ["Total", "totalSumm"], subscribes: ["Subscriptions", "subscribesSumm"], tips: ["Tips", "tipsSumm"],
  messages: ["Messages", "messagesSumm"], post: ["Posts", "postsSumm"], streams: ["Streams", "streamsSumm"],
};

type Subscriber = Fan & { subscribedOnDuration?: string | null; subscribedOnData?: Record<string, unknown> | null };

/** Fans › Subscriptions' summary from OF's chart for the tab (`subscribers`, `total`, `delta`), else the overview's. */
export const subsRekey = (chart: unknown, v2: boolean) => (_el: Element, key: string) => {
  if (!v2 || !isObj(chart)) return key;
  if (key === "fans:fans.subscribers.total" && num(chart.subscribers) !== null) return "subsChart:subscribers";
  if (key === "fans:fans.earnings.total" && num(chart.total) !== null) return "subsChart:total";
  if (key.startsWith("fans:fans.") && key.endsWith(".delta") && num(chart.delta) !== null) return "subsChart:delta";
  return key;
};

function tableRows(doc: Document, sel: string, body: Partial<PagedBody> | undefined, row: (u: Subscriber) => HTMLElement) {
  const table = doc.querySelector<HTMLElement>(`[data-oi-table='${sel}']`);
  const tbody = table?.querySelector("tbody");
  if (!body?.list || !tbody) return null;
  for (const u of body.list as Subscriber[]) {
    const tr = row(u);
    tr.dataset.oiData = "";
    add(doc, tr, tbody);
  }
  const empty = tbody.querySelector<HTMLElement>(":scope > tr .empty-message")?.closest("tr");
  if (body.list.length) display(doc, empty, false);
  else if (!body.hasMore) {
    const span = empty?.querySelector("[data-oi-empty]");
    if (span) setText(doc, span, span.getAttribute("data-oi-empty")!);
  }
  const wrapper = table?.closest(".b-statistics-page-content__wrapper");
  if (wrapper) setClass(doc, wrapper, "m-empty-wrapper", !body.list.length);
  moreAt(doc, tbody.lastElementChild, body.more);
  return table;
}

function subscriptionsPage(doc: Document, data: StatsData, p: Period, x: FansCtx) {
  const tab = x.picks.subs;
  if (x.v2) {
    for (const b of doc.querySelectorAll("[data-oi-pick^='subs:'][data-oi-enable]")) enable(doc, b);
    pickTabs(doc, "subs", tab);
  }
  // OF's fansSummary: the chart's change for the tab (none for All time).
  const delta = x.v2 && isObj(data.subsChart) ? num(data.subsChart.delta) : null;
  const holder = doc.querySelector(".b-statistics-page-content__wrapper > .b-elements-determinant__value");
  if (holder && delta && p.key !== "all" && !holder.querySelector(".b-statistics-level")) add(doc, level(doc, delta, true), holder);
  const head = doc.querySelectorAll("[data-oi-table='subs'] thead th")[2];
  if (head && x.v2) swapIn(doc, head, /Total duration|Renew date|Subscription date/, SUBS_COLUMN[tab] ?? "Total duration");
  const el = elOf(doc);
  tableRows(doc, "subs", data.subsLatest as Partial<PagedBody> | undefined, (u) => {
    const d = u.subscribedOnData ?? {};
    const expired = dateOf(d.expiredAt);
    const tr = el("tr", `m-responsive__reset-pb m-responsive__grid m-cols-1fr-auto${expired && expired < p.now ? " g-gray-text" : ""}`);
    const price = num(d.price) ?? 0;
    const priceCell = el("td", "m-responsive__grid__data-cell m-fans-table-cell");
    if (price) priceCell.append(el("span", "", usd(price)));
    else priceCell.textContent = " free ";
    const text = tab === "renew" ? (dateOf(d.renewedAt) ? dayText(dateOf(d.renewedAt)!, p.tz, false) : "") : tab === "new" ? (dateOf(d.subscribeAt) ? dayText(dateOf(d.subscribeAt)!, p.tz, false) : "") : plain(u.subscribedOnDuration);
    tr.append(fanCell(doc, u, x.img), priceCell, el("td", "m-responsive__grid__data-cell text-right m-fans-table-cell", ` ${text} `));
    return tr;
  });
}

function topFansPage(doc: Document, data: StatsData, x: FansCtx) {
  const tab = x.picks.top;
  if (x.v2) {
    for (const b of doc.querySelectorAll("[data-oi-pick^='top:'][data-oi-enable]")) enable(doc, b);
    pickTabs(doc, "top", tab);
  }
  const [title, field] = TOP_TABS[tab] ?? TOP_TABS.total;
  const total = tab === "total";
  const headRow = doc.querySelector("[data-oi-table='topfans'] thead tr");
  if (headRow && !total && x.v2) add(doc, elOf(doc)("th", "m-responsive__hidden", ` ${title} `), headRow.children[0], "after");
  const el = elOf(doc);
  tableRows(doc, "topfans", data.subsTop as Partial<PagedBody> | undefined, (u) => {
    const d = u.subscribedOnData ?? {};
    const tr = el("tr", "m-responsive__reset-pb m-responsive__grid m-cols-1fr-auto");
    tr.append(fanCell(doc, u, x.img));
    if (!total) {
      const own = el("td", "m-responsive__grid__data-cell");
      own.append(el("strong", "", usd(num(d[field]) ?? 0)));
      tr.append(own);
    }
    const sum = el("td", "m-responsive__grid__data-cell text-right");
    const v = usd(num(d.totalSumm) ?? 0);
    sum.append(total ? el("strong", "", v) : el("span", "", v));
    tr.append(sum);
    return tr;
  });
}

/**
 * Fans activity's two charts, as OF's page (statistics-fans-activity.js 159239): the sectors chart from `format=table`
 * (always drawn, even empty), the hours bars from `format=hours` (`ratio * 100` each; OF's "No Profile activity during
 * selected period" only for no hours at all). Drawn by ofMirrorChart's drawSectors / drawBars.
 */
function activityPage(doc: Document, data: StatsData) {
  const show = (which: string, raw: unknown, draw: (c: HTMLCanvasElement) => void) => {
    const box = doc.querySelector<HTMLElement>(`[data-oi-activity='${which}']`);
    const note = doc.querySelector<HTMLElement>(`[data-oi-activity-empty='${which}']`);
    if (!box || raw === undefined) return false;
    display(doc, box, true);
    display(doc, note, false);
    const canvas = box.querySelector("canvas");
    if (canvas) {
      draw(canvas);
      track(doc, () => clearFans(canvas));
    }
    return true;
  };
  if (isObj(data.fansActivity)) show("sectors", data.fansActivity, (c) => drawSectors(c, sectorsOf(at(data.fansActivity, "data"))));
  const raw = at(data.fansHours, "data");
  if (!Array.isArray(raw)) return;
  // OF's hoursData: `(ratio || 0) * 100`.
  const values = raw.map((h) => 100 * (num(at(h, "ratio")) || 0));
  if (values.length) show("hours", raw, (c) => drawBars(c, values));
  else {
    const span = doc.querySelector("[data-oi-activity-empty='hours'] [data-oi-empty]");
    if (span) setText(doc, span, span.getAttribute("data-oi-empty")!);
  }
}

/** OF's Top Fan card on the Fans tabs: the fan, the category tabs, Subscription or Earnings. */
function fanCard(doc: Document, data: StatsData, p: Period, x: FansCtx) {
  const card = doc.querySelector<HTMLElement>("[data-oi-fan-card]");
  const items = topItems(data.topFan, FANS_FAN_TABS.map(([k]) => k));
  if (!card || !items) return;
  const clean = card.previousElementSibling as HTMLElement | null;
  const enabled = FANS_FAN_TABS.filter(([k]) => items[k]);
  if (!enabled.length) {
    const empty = clean?.querySelector("[data-oi-empty]");
    if (empty) setText(doc, empty, empty.getAttribute("data-oi-empty")!);
    return;
  }
  const key = enabled.find(([k]) => k === x.picks.fan)?.[0] ?? enabled[0][0];
  const fan = items[key]!;
  display(doc, card, true);
  display(doc, clean, false);
  for (const b of card.querySelectorAll<HTMLElement>("[data-oi-pick^='fan:']")) {
    const k = b.getAttribute("data-oi-pick")!.slice(4);
    if (items[k]) enable(doc, b);
    else setClass(doc, b, "m-disabled", true);
  }
  pickTabs(doc, "fan", key);
  pickTabs(doc, "fantab", x.picks.fantab);
  const slot = card.querySelector("[data-oi-fan-avatar]");
  if (slot) add(doc, avatarOf(doc, fan as Fan, 50, x.img, "m-absolute"), slot, "after");
  display(doc, slot as HTMLElement, false);
  setText(doc, card.querySelector(".g-user-name"), ` ${plain(fan.name as string | null) || String(fan.username ?? "")} `);
  setText(doc, card.querySelector(".g-user-username"), ` @${String(fan.username ?? "")} `);
  const list = card.querySelector(".b-fans__item__list");
  if (!list) return;
  for (const r of list.querySelectorAll<HTMLElement>(":scope > .b-fans__item__list__item")) display(doc, r, false);
  const d = (fan.subscribedOnData ?? {}) as Record<string, unknown>;
  const rows: [string, string][] =
    x.picks.fantab === "earnings"
      ? [["Total", usd(fanSum(fan, "total") ?? 0)], ["Subscriptions", usd(fanSum(fan, "subscriptions") ?? 0)], ["Tips", usd(fanSum(fan, "tips") ?? 0)], ["Messages", usd(fanSum(fan, "messages") ?? 0)], ["Streams", usd(fanSum(fan, "streams") ?? 0)]]
      : ([
          ["Current subscription", num(d.price) ? usd(num(d.price)!) : "free"],
          ["Started", (dateOf(d.subscribeAt) ? dayText(dateOf(d.subscribeAt)!, p.tz, false) : "")],
          ["Total duration", plain(fan.subscribedOnDuration as string | null)],
          ["Renews", (dateOf(d.renewedAt ?? d.expiredAt) ? dayText(dateOf(d.renewedAt ?? d.expiredAt)!, p.tz, false) : "")],
        ] as [string, string][]).filter(([, v]) => v);
  const el = elOf(doc);
  for (const [label, value] of rows) {
    const item = el("div", "b-fans__item__list__item");
    item.append(el("span", "b-fans__item__list__label", ` ${label} `), el("span", "", value));
    add(doc, item, list);
  }
}

/** The Fans tabs' phase-2 parts for page `sub`. */
export function applyFans(doc: Document, sub: string, data: StatsData, p: Period, x: FansCtx) {
  if (sub === "fans/subscriptions") subscriptionsPage(doc, data, p, x);
  if (sub === "fans/top-fans") topFansPage(doc, data, x);
  if (sub === "fans/activity") activityPage(doc, data);
  fanCard(doc, data, p, x);
}
