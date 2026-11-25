"use client";


import { useEffect, useMemo, type RefObject } from "react";
import { useInfiniteQuery, useQueries, useQuery } from "@tanstack/react-query";
import { useScope } from "@/contexts/ScopeContext";
import { useAppliedSettings } from "@/lib/appliedSettings";
import { relay, RelayError } from "@/lib/relay";
import { proxyImage } from "@/lib/mediaUrl";
import { rowsOf } from "@/lib/ofMirrorData";
import type { Transaction } from "@/lib/ofMirrorFeedsStatements";
import { DASH, usd } from "@/lib/ofMirrorMoney";
import { BLUE } from "@/lib/ofMirrorChart";
import { basePage } from "@/lib/ofMirrorRow";
import { ofMeQuery, type OfMe } from "@/lib/ofMirrorIdentity";
import { add, at, display, elOf, iconOf, isObj, level, num, restoreStats, setClass, setText, zero } from "@/lib/ofMirrorStatsDom";
import { bindUserLists, drawLine, drawPair } from "@/lib/ofMirrorStatsKit";
import { POST_STATS_PROBE, postStatsProbe } from "@/lib/ofMirrorStatsPostStat";
import { applyRange, bindMenu, periodOf, startOf, usePeriodKey, type Period } from "@/lib/ofMirrorStatsPeriod";
import {
  ALL_SOURCES, FIXED, PAGED, PICK_DEFAULTS, V2_ONLY, bindPicks, inPeriod, listOf, listRoute, nextParam, nothingNew, pagedDone,
  resetPicks, setPick, statsRoute, statsSources, timeOf, uniqueRows, usePicks, valueOf,
  type EarningsType, type MassMessage, type PageParam, type PagedBody, type PayoutRow, type Picks, type PostsBy, type RouteCtx, type StatSource, type StatsData,
} from "@/lib/ofMirrorStatsSources";
import {
  applyEarningsAside, applyEarningsTabs, applyPayouts, applyRatio, applyStatements, applyTransactions, rekeyFor, rekeyReferrals, statementsSeries,
} from "@/lib/ofMirrorStatsStatements";
import { applyOverview, overviewRekey } from "@/lib/ofMirrorStatsOverview";
import { applyEngagement, applyEngagementPosts, applyMassMessages, messagesRekey, postsRekey } from "@/lib/ofMirrorStatsEngagement";
import { applyCampaignSummary, applyReach, applyVisitors, type ProfileStats } from "@/lib/ofMirrorStatsReach";
import { applyFans, subsRekey } from "@/lib/ofMirrorStatsFans";
import { lastGoodKey, selectionOf, shownFor } from "@/lib/ofMirrorStatsLastGood";

export { wallOf } from "@/lib/ofMirrorStatsDom";
export * from "@/lib/ofMirrorStatsPeriod";
export * from "@/lib/ofMirrorStatsSources";


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
  if (p.key === "all") return;
  for (const el of doc.querySelectorAll("[data-oi-delta]")) {
    const d = valueOf(data, rekey(el, el.getAttribute("data-oi-delta")!));
    if (d) add(doc, level(doc, d, inSummary(el)), el, "append");
  }
}

const PROOFS: Record<string, (data: StatsData, el: Element, page: string, p: Period) => boolean> = {
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
    if (basePage(page).endsWith("statements/earnings")) display(doc, el.closest(".b-statements-table")?.querySelector<HTMLElement>("thead"), false);
  }
}



const ROW_CHARTS: Record<string, string> = {
  "Profile visitors": "visitors:visitors.chartData",
  Posts: "posts:posts.chartData",
  Messages: "messages:massMessages.chartData",
  Subscribers: "fans:fans.chartData",
  "Mass-offers": "promo:promo.chartData",
  Trials: "trials:trials.chartData",
};
const SUMMARY_COLORS: Record<string, string> = { Posts: BLUE, Messages: "#ffa000" };
const SUMMARY_GREY = "#8d96a2";

function applyCharts(doc: Document, sub: string, data: StatsData, p: Period, by: string) {
  const tz = p.key === "24h" ? "UTC" : p.tz; // OF dates Last 24 hours' points in UTC
  const root = doc.querySelector(".b-statistics-page-content__wrapper");
  if (sub === "reach/profile-visitors") drawPair(doc, root, [at(data.profileStats, "chart.visitors"), "Visitors", "count"], [at(data.profileStats, "chart.duration"), "View duration", "duration"], tz);
  if (sub === "fans/subscriptions") drawPair(doc, root, [at(data.subsChart, "earnings"), "Earnings", "money"], [at(data.subsChart, "subscribes"), "Subscribers", "count"], tz);
  if (sub === "engagement/posts" && by === "purchases" && listOf(data.postsTop)?.length)
    drawPair(doc, root, [at(data.postsChart, "purchases.chart"), "Purchases", "money"], [at(data.postsChart, "posts.chart"), "Posts", "count"], tz);
  if (sub === "engagement/messages" && !isObj(data.messagesChart)) drawPair(doc, root, [at(data.messages, "massMessages.chartData"), "Mass messages purchases", "money"], null, tz);
  for (const c of doc.querySelectorAll<HTMLCanvasElement>(".l-wrapper__sidebar .b-elements-determinant canvas")) {
    const summary = c.closest(".b-elements-determinant.m-chart-summary");
    const label = ((summary ? summary.closest(".b-statistics-item") : c.closest(".b-elements-determinant"))?.querySelector(".b-elements-determinant__label")?.textContent ?? "").trim();
    const key = ROW_CHARTS[label];
    const i = key?.indexOf(":") ?? -1;
    if (key) drawLine(doc, c, [at(data[key.slice(0, i) as StatSource], key.slice(i + 1)), label, "money"], summary ? (SUMMARY_COLORS[label] ?? SUMMARY_GREY) : BLUE, 0, false, tz);
  }
}


export interface ApplyCtx {
  picks?: Partial<Picks>;
  v2?: boolean;
  v3?: boolean;
  me?: OfMe | null;
  accountId?: string | null;
  img?: (u: string) => string;
  retry?: (() => void) | null;
  asOf?: number | null;
  tz?: string | null;
}

export const asOfText = (at: number, tz: string | null) =>
  new Date(at).toLocaleString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit", ...(tz ? { timeZone: tz } : {}) }).replace(/\s?([AP])M$/, (_m, a: string) => ` ${a.toLowerCase()}m`);

function failedNotice(doc: Document, retry: () => void, asOf?: number | null, tz?: string | null) {
  const content = doc.querySelector(".b-statistics-page-content");
  if (!content) return;
  const el = elOf(doc);
  const box = el("div", "alert alert-info m-wider mb-0");
  box.setAttribute("data-oi-failed", "");
  const text = el("div", "alert-text-wrapper mb-0 flex-row align-items-center");
  const btn = el("button", "g-btn m-flat m-link m-no-uppercase m-reset-width ml-auto", "Retry");
  btn.setAttribute("type", "button");
  btn.addEventListener("click", retry);
  text.append(el("span", "", asOf ? `Some figures couldn't be loaded. Showing the last ones, as of ${asOfText(asOf, tz ?? null)}.` : "Some figures couldn't be loaded."), btn);
  box.append(iconOf(doc, "alert", "m-alert-icon g-icon"), text);
  add(doc, box, content, "before");
}

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
  if (x.retry) failedNotice(doc, x.retry, x.asOf, x.tz);
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
  if (sub === "statements/earnings" && PROOFS["No data during selected period"](all, doc.body, page, p))
    for (const el of doc.querySelectorAll<HTMLElement>(".b-statistics-page-content__wrapper > .b-elements-determinant, .b-statistics-page-content__wrapper > .b-chart")) display(doc, el, false);
  applyCharts(doc, sub, all, p, by);
}

// Reading ahead to a past period: OF jumps there with its `marker`, which the Relay does not forward.
const SKIP_PAGES = 5;

const PERMANENT = [400, 401, 403, 404, 409, 422];
export function retryable(err: unknown): boolean {
  if (!(err instanceof RelayError)) return true;
  const detail = isObj(err.body) ? err.body.detail : undefined;
  const up = isObj(detail) ? detail.upstream_status : undefined;
  return !PERMANENT.includes(err.status) && !(typeof up === "number" && PERMANENT.includes(up));
}
const RETRY = { retry: (n: number, err: unknown) => n < 2 && retryable(err), retryDelay: (n: number) => (n ? 3000 : 1000) };

export function usePaged(accountId: string | null, route: ((param: PageParam) => string) | null, next: (last: unknown, pages: unknown[]) => PageParam | undefined, p: Period, skip: boolean) {
  const q = useInfiniteQuery({
    queryKey: ["of-mirror-data", accountId, route ? route({ offset: 0 }) : null, "pages"],
    queryFn: ({ pageParam }) => relay.get<unknown>(route!(pageParam), { accountId }),
    initialPageParam: { offset: 0 } as PageParam,
    getNextPageParam: (last: unknown, pages: unknown[]) => next(last, pages),
    enabled: !!accountId && !!route,
    staleTime: 60_000,
    ...RETRY,
  });
  const pages = q.data?.pages;
  const list = pages && listOf(pages[0]) ? uniqueRows(pages) : undefined;
  const reached = !!list?.some((r) => (timeOf(r) ?? Infinity) < p.start.getTime());
  const ahead = !!list?.length && list.every((r) => (timeOf(r) ?? -Infinity) > p.end.getTime());
  const { hasNextPage, isFetching, fetchNextPage } = q;
  const pageFailed = q.isFetchNextPageError;
  useEffect(() => {
    if (skip && ahead && hasNextPage && !isFetching && !pageFailed && (pages?.length ?? 0) < SKIP_PAGES) void fetchNextPage();
  }, [skip, ahead, hasNextPage, isFetching, pageFailed, pages?.length, fetchNextPage]);
  const stalled = (!!pages && nothingNew(pages.at(-1), pages)) || (skip && ahead && !!hasNextPage && (pages?.length ?? 0) >= SKIP_PAGES) || pageFailed;
  const more = !!hasNextPage && !(skip && reached) && !stalled;
  const body: PagedBody | undefined = list && { list, hasMore: more, loading: isFetching, more: more && !isFetching ? () => void fetchNextPage() : null, stalled };
  const refetch = pageFailed ? () => fetchNextPage() : q.refetch;
  return { body, stamp: `${q.dataUpdatedAt}:${q.status}:${isFetching}:${pages?.length ?? 0}`, error: q.isError, failure: q.error, refetch, at: q.dataUpdatedAt, route: route ? route({ offset: 0 }) : null };
}

export const isV2 = (body: unknown) => isObj(body);
const V2_PROBE = "/api/of/v2/streaks/top";

export function useOfStats(frameRef: RefObject<HTMLIFrameElement | null>, src: string): void {
  const { accountId } = useScope();
  const tz = useAppliedSettings().data?.preferences?.tz ?? null;
  const key = usePeriodKey();
  const pk = usePicks();
  const page = /^\/of-mirror\/pages\/(.+)\.html$/.exec(src)?.[1] ?? "";
  const sources = statsSources(page);
  const sub = basePage(page).slice("statistics/".length);
  const now = useMemo(() => new Date(), [key, src]); // eslint-disable-line react-hooks/exhaustive-deps
  let phase2 = false;
  const query = (source: StatSource | "probe", route: string | null) => ({
    queryKey: ["of-mirror-data", accountId, route],
    queryFn: () => relay.get<unknown>(route!, { accountId }),
    enabled: !!accountId && !!route && (source === "probe" ? sources.length > 0 : sources.includes(source) && (phase2 || !V2_ONLY.includes(source))),
    staleTime: source === "probe" ? Infinity : 60_000,
    ...(source === "probe" ? { retry: false } : RETRY),
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
  const known = (!probeQ.isPending && !(v2 && probe3Q.isPending)) || !accountId;
  const userStart = startOf(startQ.data, tz);
  const p = periodOf(key, now, tz, userStart);
  const ready = (key !== "all" || !!userStart) && known;
  const x: RouteCtx = { picks: pk, v2, v3, sub, tz, top: probeQ.data };
  const routes = ALL_SOURCES.map((s) => (FIXED.includes(s) ? fixedRoute(s) : ready ? statsRoute(s, p, x) : null));
  const results = useQueries({ queries: ALL_SOURCES.map((s, i) => query(s, routes[i])) });
  const skipAhead: Partial<Record<StatSource, boolean>> = v3
    ? {}
    : v2
    ? { payoutRequests: sub === "statements/payout-request", referralRequests: sub.startsWith("statements/referrals/") }
    : { transactions: sub === "statements/earnings", payoutRequests: sub === "statements/payout-request", referralRequests: sub.startsWith("statements/referrals/") };
  const lists = PAGED.map((s) =>
    // eslint-disable-next-line react-hooks/rules-of-hooks
    usePaged(accountId, sources.includes(s) && ready && (v2 || !V2_ONLY.includes(s)) ? (param) => listRoute(s, p, param, x) : null, (last, pages) => nextParam(s, last, pages, x), p, !!skipAhead[s]),
  );
  const stamp = [...results.map((r) => `${r.dataUpdatedAt}:${r.status}`), ...lists.map((l) => l.stamp), probeQ.dataUpdatedAt].join(",");
  const failed = [...results.filter((r, i) => r.isError && sources.includes(ALL_SOURCES[i])), ...lists.filter((l, i) => l.error && sources.includes(PAGED[i]))];
  const retry = failed.length ? () => failed.forEach((q) => void q.refetch()) : null;
  useEffect(() => resetPicks(), [src]);

  useEffect(() => {
    const frame = frameRef.current;
    if (!frame || !sources.length) return;
    const data: StatsData = {};
    let asOf: number | null = null;
    const selection = selectionOf(p);
    const shown = (s: StatSource, route: string | null, r: { data: unknown; failed: boolean; at: number; error: unknown }) => {
      const got = shownFor(lastGoodKey(accountId, selection, route), { ...r, permanent: r.failed && !retryable(r.error) });
      if (got.asOf && sources.includes(s)) asOf = Math.min(asOf ?? Infinity, got.asOf);
      return got.data;
    };
    if (accountId) {
      ALL_SOURCES.forEach((s, i) => (data[s] = shown(s, routes[i], { data: results[i].data, failed: results[i].isError, at: results[i].dataUpdatedAt, error: results[i].error })));
      PAGED.forEach((s, i) => {
        const l = lists[i];
        const body = l.body && !l.error ? { ...l.body, loading: false, more: null } : l.body;
        const got = shown(s, l.route, { data: body, failed: l.error, at: l.at, error: l.failure });
        data[s] = l.body && !l.error ? l.body : got;
      });
    }
    const apply = () => {
      const doc = frame.contentDocument;
      if (!doc?.body) return;
      bindMenu(doc, p, userStart);
      bindPicks(doc);
      applyStats(doc, page, data, p, { picks: pk, v2, v3, me, accountId, img: (u) => proxyImage(u, accountId), retry, asOf, tz });
    };
    if (frame.contentDocument?.readyState === "complete") apply();
    frame.addEventListener("load", apply);
    return () => frame.removeEventListener("load", apply);
  }, [frameRef, src, page, accountId, stamp, key, tz, p.startApi, p.endApi, pk, v2, v3, me]); // eslint-disable-line react-hooks/exhaustive-deps
}
