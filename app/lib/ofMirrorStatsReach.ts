"use client";

/**
 * Statistics › Reach with the phase-2 Relay reads (omf-statistics-relay), read only once useOfStats' probe finds that
 * Relay; until then the page keeps the generator's honest state:
 * - Profile visitors: OF's All / Guests / Users chips (`/users/me/profile/stats?by=`; "View all" asks OF's `limit=0`);
 * - Promotions and Trial links: OF's summary ("<n> claims", "<n> offers" / "Trials"), chart (`/promotions/chart`,
 *   `/trials/chart`: claims over the other series) and PromotionsAndTrialLinksTable (`/promotions/stats`, `/trials/stats`);
 * - Tracking links: OF's summary ("<n> Subscribers"), chart (`/campaigns/chart`: subscribers over clicks) and
 *   ReachCampaignsTable (`/campaigns/stats`), its Start date and Subscribers headers sorting it as OF's.
 * Each table reads on by OF's offset as its last row scrolls into view; none in the period: OF's empty text.
 */

import { viewDuration } from "@/lib/ofMirrorChart";
import { plain } from "@/lib/ofMirrorData";
import type { Period } from "@/lib/ofMirrorStatsPeriod";
import type { PagedBody, Picks, StatsData } from "@/lib/ofMirrorStatsSources";
import { add, at, cell, dateOf, dayText, display, elOf, enable, iconOf, isObj, level, moreAt, num, ofCount, pickTabs, setAttr, setClass, setText, swapIn, track } from "@/lib/ofMirrorStatsDom";
import { drawPair, intoRows, seriesOf, usersLink } from "@/lib/ofMirrorStatsKit";
import { toast } from "@/lib/ofMirrorPost";

export interface ProfileStats {
  topCountries?: { hasMore?: boolean; totals?: Record<string, unknown>; rows?: { rank?: number; countryName?: string; countryCode?: string; viewsCount?: Record<string, unknown> }[] };
  topDurationUsers?: { totals?: Record<string, unknown> };
  chart?: { visitors?: { count?: number }[]; duration?: { count?: number }[] };
}

/** Reach › Profile visitors: the stat rows (visitors, view duration by guests, users, total) and OF's top countries. */
export function applyVisitors(doc: Document, s: ProfileStats, all = false) {
  const fill = (el: HTMLElement, cells: string[]) =>
    cells.forEach((v, i) => {
      const td = cell(el, i + 1);
      const target = td?.querySelector("strong") ?? td;
      if (target) target.textContent = ` ${v} `;
    });
  const visitors = s.topCountries?.totals ?? {};
  const time = s.topDurationUsers?.totals ?? {};
  for (const [kind, cells] of [
    ["stat-visitors", ["guests", "users", "total"].map((k) => ofCount(visitors[k]))],
    ["stat-duration", ["guests", "users", "total"].map((k) => (num(time[k]) === null ? "—" : viewDuration(num(time[k])!)))],
  ] as const) {
    const tpl = doc.querySelector<HTMLElement>(`tr[data-oi-template='${kind}']`);
    intoRows(doc, tpl?.parentElement, [cells], () => tpl, (el, c) => fill(el, [...c]));
  }
  const country = doc.querySelector<HTMLElement>("tr[data-oi-template='country']");
  const others = doc.querySelector<HTMLElement>("tr[data-oi-template='others']");
  const rows = [...(s.topCountries?.rows ?? [])].sort((a, b) => (a.rank ?? 0) - (b.rank ?? 0));
  intoRows(doc, country?.parentElement, rows, (r) => (r.countryCode ? country : others ?? country), (el, r) => {
    const flag = el.querySelector(".vti__flag");
    if (flag) flag.className = `vti__flag ${(r.countryCode ?? "").toLowerCase()}`;
    const name = el.querySelector("td strong");
    if (name) name.textContent = r.countryCode ? (r.countryName ?? "") : (r.countryName ?? "Others");
    fill(el, ["guests", "users", "total"].map((k) => ofCount(r.viewsCount?.[k])));
  });
  // OF's BtnCollapse: "View all" while OF has more, "View less" once all are shown.
  const more = doc.querySelector<HTMLElement>("[data-oi-countries-more]");
  display(doc, more, !!s.topCountries?.hasMore || all);
  const button = more?.querySelector("button");
  // OF's BtnCollapse picks all of them, or OF's preview again (the `countries` pick).
  if (button) setAttr(doc, button, "data-oi-pick", all ? "countries:" : "countries:all");
  if (button) {
    swapIn(doc, button, /View (all|less)/, all ? "View less" : "View all");
    const use = button.querySelector("use");
    const want = all ? "#icon-arrow-up" : "#icon-arrow-down";
    if (use && use.getAttribute("href") !== want) {
      const was = use.getAttribute("href");
      track(doc, () => (was === null ? use.removeAttribute("href") : use.setAttribute("href", was)));
      use.setAttribute("href", want);
      use.setAttribute("xlink:href", want);
    }
  }
}


/** Reach › Tracking links' Summary (OF's SummaryBlock, reachCampaigns): shown once the period has campaign statistics. */
export function applyCampaignSummary(doc: Document, body: unknown) {
  if (at(body, "campaigns.hasStatistic") !== true) return;
  const block = doc.querySelector<HTMLElement>("[data-oi-campaign-summary]");
  const box = block?.closest(".b-useful-data");
  if (!block || !box) return;
  display(doc, block, true);
  display(doc, box.querySelector<HTMLElement>(":scope > .empty-message"), false);
  setClass(doc, box, "pb-0", true);
  const head = box.querySelector(":scope > .b-useful-data__header");
  if (head) setClass(doc, head, "m-without-content", false);
}


export interface ReachCtx {
  picks: Picks;
  v2: boolean;
  /** The Relay has the phase-1 claim and subscriber lists (omf-statistics-relay-2). */
  v3?: boolean;
  pick: (name: "csort", value: string) => void;
  /** The Creator's `/users/me` (OF's authUser): its subscription price and username, while known. */
  me?: { subscribePrice?: number | null; username?: string | null } | null;
}

const plural = (n: number, one: string, many: string) => `${n.toLocaleString("en-US")} ${n === 1 ? one : many}`;

/** OF's ChartSummary over a Reach list: its two items and the change. */
function summary(doc: Document, kind: string, a: string, b: string | null, delta: number | null, p: Period) {
  const box = doc.querySelector<HTMLElement>(`[data-oi-summary='${kind}']`);
  if (!box) return;
  display(doc, box, true);
  setText(doc, box.querySelector("[data-oi-summary-a]"), ` ${a} `);
  const second = box.querySelector<HTMLElement>("[data-oi-summary-b]");
  setText(doc, second, b ? ` ${b} ` : "");
  display(doc, second, !!b);
  if (delta && p.key !== "all") add(doc, level(doc, delta, true), box);
}

interface Offer {
  id?: unknown;
  price?: number | null;
  /** OF's client reads it first, though `/promotions/stats` sends none: the discount comes from the prices. */
  discount?: number | null;
  subscribeDays?: number | null;
  subscribeCounts?: number | null;
  claimsCount?: number | null;
  claimCounts?: number | null;
  isFinished?: boolean;
  createdAt?: string;
  finishedAt?: string | null;
  expiredAt?: string | null;
  trialLinkName?: string | null;
}

/**
 * OF's promotion text (PromotionsAndTrialLinksTable's promotionDetailsText, module 391477; copy: texts_en.json): free,
 * "Free trial for N day(s)!" (no length: 30); else the discount off the Creator's subscription price, rounded, for its
 * days (none: the days in this month). The price not known yet: a dash for the discount.
 */
export function promotionText(o: Offer, subscribePrice: number | null | undefined, now: Date): string {
  const price = num(o.price) ?? 0;
  if (price <= 0) {
    const n = num(o.subscribeDays) || 30;
    return `Limited offer - Free trial for ${n} ${n === 1 ? "day" : "days"}!`;
  }
  const sp = num(subscribePrice);
  const off = num(o.discount) || (sp === null ? null : sp > price ? Math.round(((sp - price) / sp) * 100) : 0);
  const days = num(o.subscribeDays) || new Date(now.getFullYear(), now.getMonth() + 1, 0).getDate();
  return `Limited offer - ${off ?? "—"}% off for ${days} days!`;
}

/** PromotionsAndTrialLinksTable's name cell: OF's offer text (or the trial link's name and length) and its state. */
function offerCell(doc: Document, o: Offer, trials: boolean, me: ReachCtx["me"], now: Date) {
  const el = elOf(doc);
  const ended = trials ? !!o.subscribeCounts && o.subscribeCounts === o.claimCounts : !!o.claimsCount && o.subscribeCounts === 0;
  const live = !o.isFinished && !ended;
  const td = el("td", "m-responsive__border-line__under");
  const flex = el("div", "b-table-flex-cell");
  const col = el("div", "b-table-flex-cell__col m-flex-all");
  const item = el("div", "b-nowrap-table-item");
  // OF opens the offer's settings page while it is live (SettingsSubscription / SettingsTrialLinks).
  const text = live ? el("a", "b-nowrap-table-item__text g-page__link") : el("div", "b-nowrap-table-item__text");
  if (live) {
    text.setAttribute("href", trials ? "/of-manager/settings/subscription/trial-links" : "/of-manager/settings/subscription/promotion-campaign");
    text.setAttribute("target", "_top");
  }
  const icon = el("div", `b-icon-table ${live ? "m-icon-link" : "m-icon-gray"}`);
  const price = num(o.price) ?? 0;
  icon.append(iconOf(doc, trials ? "link" : price > 0 ? "discount" : "trial"));
  text.append(icon);
  const days = num(o.subscribeDays);
  if (!trials) text.append(el("strong", "", ` ${promotionText(o, me?.subscribePrice, now)} `));
  else {
    text.append(el("strong", "", plain(o.trialLinkName) || ""));
    if (days) {
      const span = el("span", "m-default-font-weight", days < 30 ? ` (${days === 1 ? "1 day" : `${days} days`} free trial) ` : ` (${days / 30 === 1 ? "1 month" : `${days / 30} months`} free trial) `);
      text.append(span);
    }
  }
  item.append(text);
  col.append(item);
  const state = el("div", "b-table-flex-cell__col", ended ? " Limit ended " : o.isFinished ? " Expired " : " Active ");
  flex.append(col, state);
  td.append(flex);
  return { td, live };
}

function offersPage(doc: Document, kind: "promotions" | "trials", data: StatsData, p: Period, x: ReachCtx) {
  const body = data[kind === "promotions" ? "promotionsList" : "trialsList"] as Partial<PagedBody> | undefined;
  const wrap = doc.querySelector<HTMLElement>(`[data-oi-table='${kind}']`);
  const tbody = wrap?.querySelector("tbody");
  const empty = doc.querySelector(".b-statistics-page-content__wrapper > .empty-message [data-oi-empty]");
  if (!body?.list || !tbody) return;
  const el = elOf(doc);
  for (const o of body.list as Offer[]) {
    const { td, live } = offerCell(doc, o, kind === "trials", x.me, p.now);
    const tr = el("tr", `m-responsive__reset-pb m-responsive__justify-between${live ? "" : " m-expired"}`);
    tr.dataset.oiData = "";
    const start = dateOf(o.createdAt);
    const end = dateOf(o.finishedAt ?? o.expiredAt ?? undefined);
    const claimed = el("td", "m-responsive__last-child text-right");
    // OF's claimed count opens its claims list (UserList "Claims": the offer's subscribers) when there are any.
    const n = num(o.claimsCount || o.claimCounts) ?? 0;
    const strong = el("strong", "", ofCount(n));
    claimed.append(n > 0 && x.v3 && o.id !== undefined ? usersLink(doc, ofCount(n), kind === "promotions" ? "promo-claims" : "trial-claims", o.id) : strong);
    tr.append(td, el("td", "", start ? ` ${dayText(start, p.tz, false)} ` : " — "), el("td", "", end ? ` ${dayText(end, p.tz, false)} ` : " Unlimited "), el("td", "text-right", ` ${typeof o.subscribeCounts === "number" ? o.subscribeCounts : "–"} `), claimed);
    add(doc, tr, tbody);
  }
  listShown(doc, wrap, empty, body);
  if (!body.list.length) return;
  // OF's summary (the overview's claims and offers) and chart (claims over the other series).
  const ov = at(data[kind === "promotions" ? "promo" : "trials"], kind === "promotions" ? "promo" : "trials");
  const claims = num(at(ov, "claims.total"));
  const offers = num(at(ov, "offers.total"));
  if (claims !== null || offers !== null)
    summary(doc, kind, plural(claims ?? 0, "claim", "claims"), kind === "promotions" ? plural(offers ?? 0, "offer", "offers") : `${(offers ?? 0).toLocaleString("en-US")} Trials`, num(at(ov, "offers.delta")), p);
  chartOf(doc, kind, data[kind === "promotions" ? "promotionsChart" : "trialsChart"], p);
}

/**
 * OF's Reach chart titles (app.js 263601 `ie`: Promotions claims over mass offers, Trial links claims over trials;
 * Tracking links has none there, so OF titles its lines by their keys, which its CSS capitalises).
 */
const CHART_TITLES: Record<string, [string, string]> = { promotions: ["Claims", "Mass-offers"], trials: ["Claims", "Trials"], campaigns: ["Subscribers", "Clicks"] };

/**
 * A Reach chart (OF's DoubleLineChart: its reply's first series over its second). Promotions and Trial links answer
 * `{claims: {chart}, offers: {chart}}`; Tracking links bare lists, `{clicks: [], claims: [], total, delta}`, which OF's
 * store (fetchCampaignsChart) reorders as `{subscribers: claims, clicks, …}`.
 */
function chartOf(doc: Document, kind: "promotions" | "trials" | "campaigns", chart: unknown, p: Period) {
  if (!isObj(chart)) return;
  const [main, aside] = kind === "campaigns" ? [chart.claims, chart.clicks] : [seriesOf(chart, "claims")?.chart, seriesOf(chart, "offers")?.chart];
  if (!Array.isArray(main)) return;
  const box = doc.querySelector<HTMLElement>(`[data-oi-chart='${kind}']`);
  display(doc, box, true);
  const [a, b] = CHART_TITLES[kind];
  drawPair(doc, box, [main, a, "count"], Array.isArray(aside) ? [aside, b, "count"] : null, p.key === "24h" ? "UTC" : p.tz);
}

/** A list's table shown with rows (OF's empty text when none and none to come), the next page on scrolling. */
function listShown(doc: Document, wrap: HTMLElement | null | undefined, empty: Element | null, body: Partial<PagedBody>) {
  const n = body.list?.length ?? 0;
  if (n) {
    display(doc, wrap, true);
    display(doc, empty?.closest<HTMLElement>(".empty-message"), false);
    const w = wrap?.closest(".b-statistics-page-content__wrapper");
    if (w) setClass(doc, w, "m-empty-wrapper", false);
    moreAt(doc, wrap?.querySelector("tbody")?.lastElementChild, body.more);
  } else if (!body.hasMore && empty) setText(doc, empty, empty.getAttribute("data-oi-empty")!);
}

interface Campaign {
  id?: unknown;
  campaignCode?: string | number | null;
  campaignName?: string | null;
  createdAt?: string;
  endDate?: string | null;
  countTransitions?: number | null;
  countSubscribers?: number | null;
}

/**
 * A tracking link's end (`/campaigns/stats` sends "YYYY-MM-DD HH:mm:ss", not ISO): OF's dayjs reads it as a wall time and
 * shows its date as written, so it is read as that wall time (shown in UTC: the same date).
 */
function endOf(v: string | null | undefined): Date | null {
  const m = /^(\d{4})-(\d\d)-(\d\d)[ T](\d\d):(\d\d)(?::(\d\d))?$/.exec(v ?? "");
  return m ? new Date(Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4], +m[5], +(m[6] ?? 0))) : dateOf(v ?? undefined);
}

function campaignsPage(doc: Document, data: StatsData, p: Period, x: ReachCtx) {
  const body = data.campaignsList as Partial<PagedBody> | undefined;
  const wrap = doc.querySelector<HTMLElement>("[data-oi-table='campaigns']");
  const tbody = wrap?.querySelector("tbody");
  const empty = doc.querySelector(".b-statistics-page-content__wrapper > .empty-message [data-oi-empty]");
  if (!body?.list || !tbody) return;
  const [field] = x.picks.csort.split(":");
  for (const th of wrap!.querySelectorAll<HTMLElement>("th[data-oi-sort]")) {
    setClass(doc, th, "m-active", th.getAttribute("data-oi-sort") === field);
    enable(doc, th);
  }
  bindSort(doc, x);
  bindCopy(doc);
  const el = elOf(doc);
  for (const c of body.list as Campaign[]) {
    const tr = el("tr", `m-responsive__reset-pb m-responsive__justify-between${c.endDate ? " g-gray-text" : ""}`);
    tr.dataset.oiData = "";
    const name = el("td", "m-responsive__border-line__under");
    const flex = el("div", "b-table-flex-cell");
    const col = el("div", "b-table-flex-cell__col m-flex-all");
    const item = el("div", "b-nowrap-table-item");
    const text = el("div", "b-nowrap-table-item__text");
    // OF's icon copies a running link as its client builds it (ReachCampaignsTable's copyLink): an ended one does nothing.
    const link = !c.endDate && x.me?.username && c.campaignCode !== undefined && c.campaignCode !== null ? `https://onlyfans.com/${x.me.username}/c${c.campaignCode}` : null;
    const icon = el("div", `b-icon-table${link ? " g-pointer-cursor" : ""}`);
    if (link) {
      icon.setAttribute("data-oi-copy", link);
      icon.setAttribute("role", "button");
      icon.setAttribute("data-oi-wired", "");
    }
    icon.append(iconOf(doc, "link"));
    text.append(icon, el("strong", "", plain(c.campaignName)));
    item.append(text);
    col.append(item);
    flex.append(col);
    name.append(flex);
    const start = dateOf(c.createdAt);
    const end = endOf(c.endDate);
    const subs = el("td", "text-right");
    // OF's subscribers count opens the link's subscribers (UserList CampaignClaimers) when there are any.
    const n = num(c.countSubscribers) ?? 0;
    subs.append(n > 0 && x.v3 && c.id !== undefined ? usersLink(doc, String(n), "campaign", c.id) : el("span", "", String(n)));
    tr.append(name, el("td", "", start ? ` ${dayText(start, p.tz, false)} ` : " — "), el("td", "", end ? ` ${dayText(end, "UTC", false)} ` : " - "), el("td", "text-right", ` ${num(c.countTransitions) ?? 0} `), subs);
    add(doc, tr, tbody);
  }
  listShown(doc, wrap, empty, body);
  if (!body.list.length) return;
  // OF's summary (ReachCampaigns' reachSummary): the chart's total subscribers and change, once there is one.
  const total = num(at(data.campaignsChart, "total"));
  if (total) summary(doc, "campaigns", `${total.toLocaleString("en-US")} Subscribers`, null, num(at(data.campaignsChart, "delta")), p);
  chartOf(doc, "campaigns", data.campaignsChart, p);
}

const copyBound = new WeakSet<Document>();
/** A tracking link's icon copies its link (OF's toast: "Tracking link copied!", else "Failed to copy to clipboard"). */
function bindCopy(doc: Document) {
  if (copyBound.has(doc)) return;
  copyBound.add(doc);
  doc.addEventListener("click", (ev) => {
    const icon = (ev.target as Element | null)?.closest?.("[data-oi-copy]");
    if (!icon) return;
    const clipboard = doc.defaultView?.navigator.clipboard;
    const failed = () => toast(doc, "Failed to copy to clipboard");
    if (!clipboard) return failed();
    clipboard.writeText(icon.getAttribute("data-oi-copy")!).then(() => toast(doc, "Tracking link copied!"), failed);
  });
}

const sortCtx = new WeakMap<Document, ReachCtx>();
/** Tracking links' Start date / Subscribers headers: OF's sort (a new field descending, the same field reversed). */
function bindSort(doc: Document, x: ReachCtx) {
  const bound = sortCtx.has(doc);
  sortCtx.set(doc, x);
  if (bound) return;
  doc.addEventListener("click", (ev) => {
    const th = (ev.target as Element | null)?.closest?.("th[data-oi-sort]");
    if (!th) return;
    const cur = sortCtx.get(doc)!;
    const field = th.getAttribute("data-oi-sort")!;
    const [f, o] = cur.picks.csort.split(":");
    cur.pick("csort", `${field}:${f === field && o === "desc" ? "asc" : "desc"}`);
  });
}

/** The Reach tabs' phase-2 parts for page `sub`. */
export function applyReach(doc: Document, sub: string, data: StatsData, p: Period, x: ReachCtx) {
  if (sub === "reach/profile-visitors" && x.v2) {
    for (const b of doc.querySelectorAll("[data-oi-pick^='visitors:'][data-oi-enable]")) enable(doc, b);
    pickTabs(doc, "visitors", x.picks.visitors);
  }
  if (sub === "reach/promotions") offersPage(doc, "promotions", data, p, x);
  if (sub === "reach/trial-links") offersPage(doc, "trials", data, p, x);
  if (sub === "reach/tracking-links") campaignsPage(doc, data, p, x);
}
