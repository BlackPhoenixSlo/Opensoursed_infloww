"use client";

/**
 * Real figures on the OF mirror's Statistics pages (reads only) for the period picked (ofMirrorStatsPeriod) and the
 * in-place picks (ofMirrorStatsSources), each page's parts drawn by its group's module (ofMirrorStatsStatements, …Overview,
 * …Engagement, …Reach, …Fans) on the generator's markup:
 * - `/users/me/stats/overview?by=<by>`: every figure the generator keyed (`data-oi-stat="<source>:<path>"`), its change
 *   (`data-oi-delta`: OF's level mark; signed in a Summary block, as OF prints it there); `derived`: Tips and Stream tips
 *   are $0.00 when the period's total is the sum of the other categories (all are non-negative); Referrals are $0.00 for
 *   every period when the referral balance is $0.00 and no referral payout was ever made. Otherwise a dash.
 * - A captured "No … during selected period" or Top card (data-oi-empty) shows OF's own text once these figures prove
 *   the period empty (PROOFS); else "Not available in Inflowwww yet", as the generator draws it.
 * - The charts' canvases get their series in OF's colours, axes and tooltip (ofMirrorChart).
 * Shapes: app/lib/__fixtures__/of/statistics-*.json (live bodies, scrubbed; the phase-2 Relay's synthetic, in OF's shapes).
 * No data yet, a field missing or a Relay error: a dash, as the generator draws it.
 */

import { useEffect, useMemo, type RefObject } from "react";
import { useInfiniteQuery, useQueries, useQuery } from "@tanstack/react-query";
import { useScope } from "@/contexts/ScopeContext";
import { useAppliedSettings } from "@/lib/appliedSettings";
import { relay } from "@/lib/relay";
import { proxyImage } from "@/lib/mediaUrl";
import { rowsOf } from "@/lib/ofMirrorData";
import type { Transaction } from "@/lib/ofMirrorFeeds";
import { DASH, usd } from "@/lib/ofMirrorMoney";
import { BLUE } from "@/lib/ofMirrorChart";
import { basePage } from "@/lib/ofMirrorRow";
import { ofMeQuery, type OfMe } from "@/lib/ofMirrorIdentity";
import { add, at, display, isObj, level, num, restoreStats, setClass, setText, zero } from "@/lib/ofMirrorStatsDom";
import { bindUserLists, drawLine, drawPair } from "@/lib/ofMirrorStatsKit";
import { POST_STATS_PROBE, postStatsProbe } from "@/lib/ofMirrorStatsPostStat";
import { applyRange, bindMenu, periodOf, startOf, usePeriodKey, type Period } from "@/lib/ofMirrorStatsPeriod";
import {
  ALL_SOURCES, FIXED, PAGED, PICK_DEFAULTS, V2_ONLY, bindPicks, inPeriod, listOf, listRoute, nextParam, nothingNew, pagedDone,
  resetPicks, setPick, statsRoute, statsSources, timeOf, usePicks, valueOf,
  type EarningsType, type MassMessage, type PageParam, type PagedBody, type PayoutRow, type Picks, type PostsBy, type RouteCtx, type StatSource, type StatsData,
} from "@/lib/ofMirrorStatsSources";
import {
  applyEarningsAside, applyEarningsTabs, applyPayouts, applyRatio, applyStatements, applyTransactions, rekeyFor, rekeyReferrals, statementsSeries,
} from "@/lib/ofMirrorStatsStatements";
import { applyOverview, overviewRekey } from "@/lib/ofMirrorStatsOverview";
import { applyEngagement, applyEngagementPosts, applyMassMessages, messagesRekey, postsRekey } from "@/lib/ofMirrorStatsEngagement";
import { applyCampaignSummary, applyReach, applyVisitors, type ProfileStats } from "@/lib/ofMirrorStatsReach";
import { applyFans, subsRekey } from "@/lib/ofMirrorStatsFans";

export { wallOf } from "@/lib/ofMirrorStatsDom";
export * from "@/lib/ofMirrorStatsPeriod";
export * from "@/lib/ofMirrorStatsSources";

// ---------------------------------------------------------------- the page

/**
 * The sums OF has no Relay route for (see the header): `tips`, `tips_stream`, `ref` as `{total, gross}`, each present
 * only when the other figures prove it.
 */
export function derive(data: StatsData): Record<string, { total: number; gross: number }> {
  const out: Record<string, { total: number; gross: number }> = {};
  const parts = ["fans:fans.earnings", "posts:posts.earnings", "messages:massMessages.earnings", "streams:streams.earnings"];
  const sum = (f: "total" | "gross") => {
    const all = valueOf(data, `earnings:earning.${f}`);
    const each = parts.map((p) => valueOf(data, `${p}.${f}`));
    return all === null || each.some((v) => v === null) ? null : all - each.reduce<number>((a, b) => a + b!, 0);
  };
  if (zero(sum("total")) && zero(sum("gross"))) {
    out.tips = { total: 0, gross: 0 };
    out.tips_stream = { total: 0, gross: 0 };
  }
  const referral = num(at(data.referralBalance, "referralEarnings"));
  const paid = data.referralRequests as { list?: unknown[]; hasMore?: boolean } | undefined;
  if (zero(referral) && Array.isArray(paid?.list) && !paid.list.length && !paid.hasMore) out.ref = { total: 0, gross: 0 };
  return out;
}

const inSummary = (el: Element) => [...(el.closest(".b-useful-data")?.querySelectorAll(":scope > .b-useful-data__header") ?? [])].some((h) => h.textContent?.trim() === "Summary");

function applyFigures(doc: Document, data: StatsData, p: Period, rekey: (el: Element, key: string) => string = (_el, k) => k) {
  for (const el of doc.querySelectorAll("[data-oi-stat]")) {
    const key = rekey(el, el.getAttribute("data-oi-stat")!);
    const v = key ? valueOf(data, key) : null;
    const money = el.hasAttribute("data-oi-money");
    if (v === null) setText(doc, el, money ? DASH : "—");
    else setText(doc, el, money ? ` ${usd(v)} ` : v.toLocaleString("en-US"));
    if (money) setClass(doc, el, "m-zero-value", v !== null && Math.round(v) === 0);
  }
  if (p.key === "all") return; // OF shows no change for All time
  for (const el of doc.querySelectorAll("[data-oi-delta]")) {
    const d = valueOf(data, rekey(el, el.getAttribute("data-oi-delta")!));
    if (d) add(doc, level(doc, d, inSummary(el)), el, "append");
  }
}

/**
 * OF's own empty text (data-oi-empty) where the Relay's figures prove the period empty: the Top cards (Post: no top
 * post at all; Message: no message earnings; Stream, Stories: no streams or stories), a tab with no streams or stories,
 * Chargebacks (a 0% ratio), Payout Requests and Referrals (no request in the period), Engagement › Posts (no top post).
 */
const PROOFS: Record<string, (data: StatsData, el: Element, page: string, p: Period) => boolean> = {
  // Streams: OF counts their minutes ("0m"), or says it has no statistic at all.
  "No Streaming activity during selected period": (d) => at(d.streams, "streams.hasStatistic") === false || /^0(\D|$)/.test(String(at(d.streams, "streams.count.total"))),
  "No Stories activity during selected period": (d) => zero(num(at(d.story, "stories.count.total"))),
  "No Message activity during selected period": (d) => zero(valueOf(d, "messages:massMessages.earnings.total")),
  "No Profile activity during selected period": (d) => zero(valueOf(d, "visitors:visitors.visitors.total")),
  "No tracking links during selected period": (d) => at(d.campaign, "campaigns.hasStatistic") === false,
  "No Post activity during selected period": (d, el, _page, p) => {
    if (el.closest(".b-clean-state")) {
      const top = d.topPost as Record<string, unknown> | undefined;
      return !!top && typeof top === "object" && !Array.isArray(top) && Object.values(top).every((v) => v == null);
    }
    // The period's posts as usePaged hands them over: none, and none to come.
    const items = listOf(d.postsTop);
    return !!items && !items.length && pagedDone(d.postsTop, p);
  },
  "No data during selected period": (d, _el, page, p) => {
    if (page.endsWith("statements/disputes")) return zero(num(at(d.chargebacks, "chargebacksRatio")));
    const sub = basePage(page);
    if (sub.endsWith("engagement/messages")) {
      const items = listOf(d.massMessages);
      return !!items && !items.length && pagedDone(d.massMessages, p);
    }
    const body = sub.endsWith("statements/payout-request") ? d.payoutRequests : sub.includes("statements/referrals/") ? d.referralRequests : sub.endsWith("statements/earnings") ? d.transactions : undefined;
    const list = rowsOf<PayoutRow>(body);
    return !!list && pagedDone(body, p) && !list.some((r) => inPeriod(r.createdAt, p));
  },
};
function applyEmpties(doc: Document, page: string, data: StatsData, p: Period) {
  for (const el of doc.querySelectorAll("[data-oi-empty]")) {
    const text = el.getAttribute("data-oi-empty")!;
    if (!PROOFS[text]?.(data, el, page, p)) continue;
    setText(doc, el, text);
    // Statements › Earnings: OF shows its empty placeholder instead of the table (statistics-earnings.js `listCount`).
    if (basePage(page).endsWith("statements/earnings")) display(doc, el.closest(".b-statements-table")?.querySelector<HTMLElement>("thead"), false);
  }
}


// ---------------------------------------------------------------- charts

/** The sidebar chart of a row (its first label) from `/users/me/stats/overview`'s chartData (each the day's earnings). */
const ROW_CHARTS: Record<string, string> = {
  "Profile visitors": "visitors:visitors.chartData",
  Posts: "posts:posts.chartData",
  Messages: "messages:massMessages.chartData",
  Subscribers: "fans:fans.chartData",
  "Mass-offers": "promo:promo.chartData",
  Trials: "trials:trials.chartData",
};

/**
 * The main charts Phase 1 draws, OF's pair (DoubleLineChart: the first series on the upper chart in blue, the second
 * under it in grey with the dates); the series' titles are OF's copy (texts_en.json, build 202610091632):
 * - Reach › Profile visitors: visitors over the view duration (`/users/me/profile/stats`' chart);
 * - Fans › Subscriptions: earnings over new subscribers (`/subscriptions/subscribers/chart`, OF's order);
 * - Engagement › Posts (Purchases): purchases over posts;
 * - Engagement › Messages: the mass messages' daily earnings (the overview's chartData) until OF's own chart is read.
 * The sidebar rows' sparklines: the day's earnings, a line only. The group modules draw the phase-2 charts.
 */
function applyCharts(doc: Document, sub: string, data: StatsData, p: Period, by: string) {
  const tz = p.key === "24h" ? "UTC" : p.tz; // OF dates Last 24 hours' points in UTC
  const root = doc.querySelector(".b-statistics-page-content__wrapper");
  if (sub === "reach/profile-visitors") drawPair(doc, root, [at(data.profileStats, "chart.visitors"), "Visitors", "count"], [at(data.profileStats, "chart.duration"), "View duration", "duration"], tz);
  if (sub === "fans/subscriptions") drawPair(doc, root, [at(data.subsChart, "earnings"), "Earnings", "money"], [at(data.subsChart, "subscribes"), "Subscribers", "count"], tz);
  if (sub === "engagement/posts" && by === "purchases" && listOf(data.postsTop)?.length)
    drawPair(doc, root, [at(data.postsChart, "purchases.chart"), "Purchases", "money"], [at(data.postsChart, "posts.chart"), "Posts", "count"], tz);
  if (sub === "engagement/messages" && !isObj(data.messagesChart)) drawPair(doc, root, [at(data.messages, "massMessages.chartData"), "Mass messages purchases", "money"], null, tz);
  for (const c of doc.querySelectorAll<HTMLCanvasElement>(".l-wrapper__sidebar .b-elements-determinant canvas")) {
    const label = c.closest(".b-elements-determinant")?.querySelector(".b-elements-determinant__label")?.textContent?.trim() ?? "";
    const key = ROW_CHARTS[label];
    const i = key?.indexOf(":") ?? -1;
    if (key) drawLine(doc, c, [at(data[key.slice(0, i) as StatSource], key.slice(i + 1)), label, "money"], BLUE, 0, false, tz);
  }
}

// ---------------------------------------------------------------- apply

/** What applyStats reads besides the data: the picks, whether the Relay has the phase-2 reads, the model, its images. */
export interface ApplyCtx {
  picks?: Partial<Picks>;
  v2?: boolean;
  /** The Relay has the phase-1 per-item reads (useOfStats' second probe). */
  v3?: boolean;
  /** The Creator's `/users/me` (OF's authUser), while known. */
  me?: OfMe | null;
  accountId?: string | null;
  img?: (u: string) => string;
}

/** Show `data` for period `p` on `doc` (the generator's dashes again for what it lacks; idempotent). */
export function applyStats(doc: Document, page: string, data: StatsData, p: Period, x: ApplyCtx = {}): void {
  restoreStats(doc);
  if (!statsSources(page).length) return;
  const picks: Picks = { ...PICK_DEFAULTS, ...x.picks };
  const { img } = x;
  const v2 = !!x.v2;
  const v3 = v2 && !!x.v3;
  const type = picks.type as EarningsType;
  const by = picks.by as PostsBy;
  const userStart = startOf(data.startDate, p.tz);
  const sub = basePage(page).slice("statistics/".length);
  const series = sub === "statements/earnings" ? statementsSeries(data, type, picks.tips) : null;
  const all: StatsData & { series?: unknown } = { ...data, derived: derive(data), ...(series ? { series } : {}) };
  applyRange(doc, p);
  const rekeys: Record<string, (el: Element, key: string) => string> = {
    "statements/earnings": rekeyFor(type, !!series),
    "statements/referrals/earnings": rekeyReferrals(isObj(data.referralsChart)),
    "overview/earnings": overviewRekey(data.earningsChart),
    "engagement/messages": messagesRekey(data.messagesChart, picks.msg === "direct" ? "direct" : "group"),
    "engagement/posts": v2 ? postsRekey(data.postsChart, by) : (_el, k) => k,
    "fans/subscriptions": subsRekey(data.subsChart, v2),
  };
  applyFigures(doc, all, p, rekeys[sub]);
  applyEarningsAside(doc, all, p);
  const mass = listOf<MassMessage>(data.massMessages);
  if (sub === "engagement/messages" && mass) applyMassMessages(doc, mass, p.tz, data.massMessages as Partial<PagedBody>);
  if (sub === "engagement/posts") applyEngagementPosts(doc, all, p, by, img, v3);
  const tx = rowsOf<Transaction>(data.transactions);
  if (sub === "statements/earnings") {
    applyEarningsTabs(doc, type);
    if (tx) applyTransactions(doc, tx, p, data.transactions as Partial<PagedBody>);
  }
  if (sub === "statements/payout-request") applyPayouts(doc, "payouts", data.payoutRequests, p);
  if (sub === "statements/referrals/earnings") applyPayouts(doc, "referrals", data.referralRequests, p);
  if (sub === "reach/profile-visitors" && isObj(data.profileStats)) applyVisitors(doc, data.profileStats as ProfileStats, picks.countries === "all");
  if (sub === "reach/tracking-links") applyCampaignSummary(doc, data.campaign);
  if (sub === "statements/disputes") applyRatio(doc, data.chargebacks);
  if (sub.startsWith("statements/")) applyStatements(doc, sub, all, p, { picks, v2, type, accountId: x.accountId, img });
  applyOverview(doc, sub, all, p, { picks, v2, v3, img, userStart, username: x.me?.username, sub });
  if (sub.startsWith("engagement/")) applyEngagement(doc, sub, all, p, { picks, v2, by, img, pick: setPick });
  if (sub.startsWith("reach/")) applyReach(doc, sub, all, p, { picks, v2, v3, me: x.me, pick: setPick });
  if (sub.startsWith("fans/")) applyFans(doc, sub, all, p, { picks, v2, img });
  bindUserLists(doc, { accountId: x.accountId, img });
  applyEmpties(doc, page, all, p);
  // Statements › Earnings with no earning in the period: OF shows its empty state alone, no summary or chart.
  if (sub === "statements/earnings" && PROOFS["No data during selected period"](all, doc.body, page, p))
    for (const el of doc.querySelectorAll<HTMLElement>(".b-statistics-page-content__wrapper > .b-elements-determinant, .b-statistics-page-content__wrapper > .b-chart")) display(doc, el, false);
  applyCharts(doc, sub, all, p, by);
}

/**
 * Most pages read ahead to reach a past period (OF jumps there with its `marker`, which today's Relay does not forward):
 * 250 rows; a period further back stays in the generator's state rather than reading on.
 */
const SKIP_PAGES = 5;

/** Each page's rows, once (a page read twice, or a list OF re-sent from an earlier end: its rows once). */
const uniqueRows = (pages: unknown[]) => {
  const seen = new Set<string>();
  return pages.flatMap((pg) => listOf<PayoutRow>(pg) ?? []).filter((r) => {
    const id = r.id ?? r.invoiceId;
    if (id === undefined || id === null) return true;
    const k = String(id);
    if (seen.has(k)) return false;
    seen.add(k);
    return true;
  });
};

/**
 * A paged source (PAGED) for `route(param)` (null: not on this page), as one body (PagedBody) and a stamp that changes
 * with it. `skip`: while every row read is newer than the period, the next page is read (at most SKIP_PAGES); then the
 * next page waits for OF's infinite loading (the last row scrolling into view).
 */
function usePaged(accountId: string | null, route: ((param: PageParam) => string) | null, next: (last: unknown, pages: unknown[]) => PageParam | undefined, p: Period, skip: boolean) {
  const q = useInfiniteQuery({
    queryKey: ["of-mirror-data", accountId, route ? route({ offset: 0 }) : null, "pages"],
    queryFn: ({ pageParam }) => relay.get<unknown>(route!(pageParam), { accountId }),
    initialPageParam: { offset: 0 } as PageParam,
    getNextPageParam: (last: unknown, pages: unknown[]) => next(last, pages),
    enabled: !!accountId && !!route,
    staleTime: 60_000,
    retry: false,
  });
  const pages = q.data?.pages;
  const list = pages && listOf(pages[0]) ? uniqueRows(pages) : undefined;
  const reached = !!list?.some((r) => (timeOf(r) ?? Infinity) < p.start.getTime());
  const ahead = !!list?.length && list.every((r) => (timeOf(r) ?? -Infinity) > p.end.getTime());
  const { hasNextPage, isFetching, fetchNextPage } = q;
  useEffect(() => {
    if (skip && ahead && hasNextPage && !isFetching && (pages?.length ?? 0) < SKIP_PAGES) void fetchNextPage();
  }, [skip, ahead, hasNextPage, isFetching, pages?.length, fetchNextPage]);
  // Stopped short of the period: the cap reached while every row is still newer, or the Relay repeated a page.
  const stalled = (!!pages && nothingNew(pages.at(-1), pages)) || (skip && ahead && !!hasNextPage && (pages?.length ?? 0) >= SKIP_PAGES);
  const more = !!hasNextPage && !(skip && reached) && !stalled;
  const body: PagedBody | undefined = list && { list, hasMore: more, loading: isFetching, more: more && !isFetching ? () => void fetchNextPage() : null, stalled };
  return { body, stamp: `${q.dataUpdatedAt}:${isFetching}:${pages?.length ?? 0}` };
}

/**
 * Whether the Relay has the phase-2 Statistics reads (omf-statistics-relay): its `/streaks/top` answers an object
 * (today's Relay: 404). Until then every control that needs one of their params (a chip's `by`, the search, OF's
 * Statements paging) keeps today's state: today's Relay drops unknown params and would answer for another tab.
 */
export const isV2 = (body: unknown) => isObj(body);
const V2_PROBE = "/api/of/v2/streaks/top";
// The phase-1 per-item reads (the post buyer and tip lists, the claim and subscriber lists, the item stats headers):
// ofMirrorStatsPostStat's postStatsProbe. Until it finds them the counts that open those lists stay plain figures.

/** On a Statistics page, show the model's figures for the period picked on every frame load, data or period change. */
export function useOfStats(frameRef: RefObject<HTMLIFrameElement | null>, src: string): void {
  const { accountId } = useScope();
  const tz = useAppliedSettings().data?.preferences?.tz ?? null;
  const key = usePeriodKey();
  const pk = usePicks();
  const page = /^\/of-mirror\/pages\/(.+)\.html$/.exec(src)?.[1] ?? "";
  const sources = statsSources(page);
  const sub = basePage(page).slice("statistics/".length);
  // The clock is read once per page and period, so the routes (and their cache) stay put between renders.
  const now = useMemo(() => new Date(), [key, src]); // eslint-disable-line react-hooks/exhaustive-deps
  let phase2 = false; // set from the probe below, before any phase-2 read is built
  const query = (source: StatSource | "probe", route: string | null) => ({
    queryKey: ["of-mirror-data", accountId, route],
    queryFn: () => relay.get<unknown>(route!, { accountId }),
    // A phase-2 read only once the probe found that Relay: today's gets the probe's one 404, nothing else.
    enabled: !!accountId && !!route && (source === "probe" ? sources.length > 0 : sources.includes(source) && (phase2 || !V2_ONLY.includes(source))),
    staleTime: source === "probe" ? Infinity : 60_000,
    retry: false,
  });
  const fixedRoute = (s: StatSource) => statsRoute(s, { startApi: "", endApi: "" });
  const [startQ, probeQ, probe3Q] = useQueries({
    queries: [
      query("startDate", fixedRoute("startDate")),
      query("probe", V2_PROBE),
      { ...query("probe", POST_STATS_PROBE), ...postStatsProbe(accountId) },
    ],
  });
  const v2 = isV2(probeQ.data);
  const v3 = v2 && probe3Q.data === true;
  const { data: me } = useQuery(ofMeQuery(accountId));
  phase2 = v2;
  // Today's Relay answers the probe 404 at once; a phase-2 read waits for it so it is asked with the right params.
  // With phase 2, the second probe too: the payout lists are asked OF's way only on the phase-1 Relay.
  const known = (!probeQ.isPending && !(v2 && probe3Q.isPending)) || !accountId;
  const userStart = startOf(startQ.data, tz);
  const p = periodOf(key, now, tz, userStart);
  // All time needs the Creator's start before it can ask for anything.
  const ready = (key !== "all" || !!userStart) && known;
  const x: RouteCtx = { picks: pk, v2, v3, sub, tz, top: probeQ.data };
  const results = useQueries({
    queries: ALL_SOURCES.map((s) => query(s, FIXED.includes(s) ? fixedRoute(s) : ready ? statsRoute(s, p, x) : null)),
  });
  // The read-ahead cap only where the Relay cannot page OF's way: transactions before phase 2, the payout lists before phase 1.
  const skipAhead: Partial<Record<StatSource, boolean>> = v3
    ? {}
    : v2
    ? { payoutRequests: sub === "statements/payout-request", referralRequests: sub.startsWith("statements/referrals/") }
    : { transactions: sub === "statements/earnings", payoutRequests: sub === "statements/payout-request", referralRequests: sub.startsWith("statements/referrals/") };
  // One reader per paged source, always in PAGED's order.
  const lists = PAGED.map((s) =>
    // eslint-disable-next-line react-hooks/rules-of-hooks
    usePaged(accountId, sources.includes(s) && ready && (v2 || !V2_ONLY.includes(s)) ? (param) => listRoute(s, p, param, x) : null, (last, pages) => nextParam(s, last, pages, x), p, !!skipAhead[s]),
  );
  const stamp = [...results.map((r) => r.dataUpdatedAt), ...lists.map((l) => l.stamp), probeQ.dataUpdatedAt].join(",");
  // OF opens each page on its default tabs (the top countries collapsed, Posts on Purchases).
  useEffect(() => resetPicks(), [src]);

  useEffect(() => {
    const frame = frameRef.current;
    if (!frame || !sources.length) return;
    const data: StatsData = {};
    if (accountId) {
      ALL_SOURCES.forEach((s, i) => (data[s] = results[i].data));
      PAGED.forEach((s, i) => (data[s] = lists[i].body));
    }
    const apply = () => {
      const doc = frame.contentDocument;
      if (!doc?.body) return;
      bindMenu(doc, p, userStart);
      bindPicks(doc);
      applyStats(doc, page, data, p, { picks: pk, v2, v3, me, accountId, img: (u) => proxyImage(u, accountId) });
    };
    if (frame.contentDocument?.readyState === "complete") apply();
    frame.addEventListener("load", apply);
    return () => frame.removeEventListener("load", apply);
    // results: by their stamp; p: by its key, tz and start.
  }, [frameRef, src, page, accountId, stamp, key, tz, p.startApi, p.endApi, pk, v2, v3, me]); // eslint-disable-line react-hooks/exhaustive-deps
}
