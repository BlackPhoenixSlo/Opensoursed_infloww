"use client";


import { useSyncExternalStore } from "react";
import { rowsOf } from "@/lib/ofMirrorData";
import { valid } from "@/lib/ofMirrorDom";
import { basePage } from "@/lib/ofMirrorRow";
import { moneyOf } from "@/lib/ofMirrorMoney";
import { at, num, pad, wallOf } from "@/lib/ofMirrorStatsDom";
import { listeners, subscribe, type Period } from "@/lib/ofMirrorStatsPeriod";

export const TIPS_SOURCES: Record<string, [source: string, title: string]> = {
  all: ["", "Earnings"], profile: ["profile", "Profile tips"], post: ["post_all", "Posts tips"], chat: ["chat", "Messages tips"],
  stream: ["stream", "Streams tips"], story: ["story", "Stories tips"],
};
export const chartCategory = (type: EarningsType, tips = "all") => (type === "chat_messages" ? "messages" : type === "tips" && tips !== "all" ? `tips_${tips}` : type);
export type EarningsType = "total" | "subscribes" | "tips" | "post" | "chat_messages" | "stream";
export type PostsBy = "purchases" | "tips" | "views" | "likes" | "comments";
// OF reads every country (limit=0); today's Relay accepts at most 50.
export const COUNTRIES_ALL = 50;

export const PICK_DEFAULTS = {
  type: "total", by: "purchases", countries: "", tpost: "", tips: "all", ref: "earnings", row: "total", msg: "group", q: "", streams: "purchases", stories: "tips",
  visitors: "total", subs: "total", top: "total", fan: "total", tmsg: "", tstream: "", tstory: "", csort: "", fantab: "subscription",
  smonth: "0", stab: "current",
} as const;
export type PickName = keyof typeof PICK_DEFAULTS;
export type Picks = Record<PickName, string>;
let picks: Picks = { ...PICK_DEFAULTS };
export function setPick(name: PickName, value: string): void {
  const next = name === "type" ? { ...picks, type: value, tips: "all" } : name === "stab" ? { ...picks, stab: value, smonth: "0" } : { ...picks, [name]: value };
  if (Object.keys(next).every((k) => next[k as PickName] === picks[k as PickName])) return;
  picks = next;
  for (const l of listeners) l();
}
export function resetPicks(): void {
  const next = { ...PICK_DEFAULTS, type: picks.type };
  if (Object.keys(next).every((k) => next[k as PickName] === picks[k as PickName])) return;
  picks = next;
  for (const l of listeners) l();
}
const DEFAULT_PICKS: Picks = { ...PICK_DEFAULTS };
export const usePicks = () => useSyncExternalStore(subscribe, () => picks, () => DEFAULT_PICKS);
export const currentPicks = () => picks;

const picksBound = new WeakSet<Document>();
export function bindPicks(doc: Document): void {
  if (picksBound.has(doc)) return;
  picksBound.add(doc);
  doc.addEventListener("click", (ev) => {
    const el = (ev.target as Element | null)?.closest?.<HTMLElement>("[data-oi-pick]");
    if (!el || el.hasAttribute("disabled") || el.getAttribute("aria-disabled") === "true") return;
    const [name, ...rest] = el.getAttribute("data-oi-pick")!.split(":");
    if (!(name in PICK_DEFAULTS)) return;
    if (el.closest("a[href]")) ev.preventDefault();
    setPick(name as PickName, rest.join(":"));
    const href = el.getAttribute("data-oi-href");
    if (href && !doc.querySelector(`[data-oi-pick^='${name}:']:not([data-oi-href])`)) {
      const a = doc.createElement("a");
      a.href = href;
      a.target = "_top";
      a.style.display = "none";
      doc.body.append(a);
      a.click();
      a.remove();
    }
  });
}


const OVERVIEW = ["earnings", "visitors", "posts", "messages", "fans", "promo", "trials", "streams", "story", "campaign"] as const;
export const V2_READS = [
  "earningsChart", "payoutsChart", "referralsChart", "chargebacksChart", "topMessage", "topStream", "topStory", "topFan",
  "streaks", "streaksTop", "todayActivity", "messagesChart", "streamsChart", "storiesChart", "promotionsChart", "trialsChart",
  "campaignsChart", "fansActivity", "fansHours", "earningsSide", "streakSummary",
] as const;
export const V2_LISTS = [
  "chargebacksList", "referredCreators", "referredUsers", "streamsTop", "storiesTop", "promotionsList", "trialsList",
  "campaignsList", "subsLatest", "subsTop",
] as const;
export type StatSource =
  | (typeof OVERVIEW)[number]
  | (typeof V2_READS)[number]
  | (typeof V2_LISTS)[number]
  | "stats" | "transactions" | "massMessages" | "chargebacks" | "profileStats" | "subsChart" | "postsChart" | "topPost" | "postsTop"
  | "payoutRequests" | "referralRequests" | "referralBalance" | "startDate";
export const V2_ONLY: StatSource[] = [...V2_READS, ...V2_LISTS];
export const FIXED: StatSource[] = ["stats", "referralBalance", "startDate", "streaksTop", "todayActivity"];
export const PAGED: StatSource[] = ["transactions", "payoutRequests", "referralRequests", "massMessages", "postsTop", ...V2_LISTS];
export const ALL_SOURCES: StatSource[] = [...OVERVIEW, "stats", "chargebacks", "profileStats", "subsChart", "postsChart", "topPost", "referralBalance", "startDate", ...V2_READS];

export interface RouteCtx {
  picks?: Partial<Picks>;
  v2?: boolean;
  sub?: string;
  tz?: string | null;
  top?: unknown;
  v3?: boolean;
}
export interface PageParam {
  offset: number;
  marker?: string | number | null;
  endDate?: string;
}

const OVERVIEW_SERIES = ["total", "subscribes", "tips", "tips_stream", "post", "messages", "ref", "stream"];
export const OF_PAGE = 10;

export function statsRoute(source: StatSource, p: Pick<Period, "startApi" | "endApi"> & Partial<Pick<Period, "end" | "now">>, x: RouteCtx = {}): string {
  const range = (extra: Record<string, string> = {}) => new URLSearchParams({ ...extra, start: p.startApi, end: p.endApi }).toString();
  const pk: Picks = { ...PICK_DEFAULTS, ...x.picks };
  const by = pk.by;
  const allCountries = pk.countries === "all";
  if ((OVERVIEW as readonly string[]).includes(source)) return `/api/of/v2/users/me/stats/overview?${new URLSearchParams({ by: source, start: p.startApi, end: p.endApi })}`;
  if (PAGED.includes(source)) return listRoute(source, p, { offset: 0 }, x);
  switch (source) {
    case "stats": return "/api/of/v2/payouts/stats";
    case "chargebacks": return `/api/of/v2/payouts/chargebacks/ratio?${range()}`;
    case "profileStats":
      return x.v2
        ? `/api/of/v2/users/me/profile/stats?${range({ by: pk.visitors, limit: allCountries ? "0" : "3" })}`
        : `/api/of/v2/users/me/profile/stats?${range({ limit: allCountries ? String(COUNTRIES_ALL) : "3" })}`;
    case "subsChart": return `/api/of/v2/subscriptions/subscribers/chart?${range(x.v2 ? { by: pk.subs } : {})}`;
    case "postsChart": return `/api/of/v2/posts/chart?${range(x.v2 ? { by } : {})}`;
    case "topPost": return `/api/of/v2/users/me/stats/top/post?${range()}`;
    case "referralBalance": return "/api/of/v2/payments/referrals/balance";
    case "earningsChart": {
      const keys = x.sub === "overview/earnings" ? OVERVIEW_SERIES.map((c) => `${c}_amount`) : ((c) => [`${c}_count`, `${c}_amount`])(chartCategory(pk.type as EarningsType, pk.tips));
      return `/api/of/v2/earnings/chart?${range({ filter: keys.join(",") })}`;
    }
    case "earningsSide": return `/api/of/v2/earnings/chart?${range({ filter: SIDE_SERIES.flatMap((c) => [`${c}_count`, `${c}_amount`]).join(",") })}`;
    case "payoutsChart": return `/api/of/v2/payouts/chart?${range()}`;
    case "referralsChart": return `/api/of/v2/payouts/referrals/chart?${range()}`;
    case "chargebacksChart": return `/api/of/v2/payouts/chargebacks/chart?${range()}`;
    case "topMessage": return `/api/of/v2/users/me/stats/top/message?${range()}`;
    case "topStream": return `/api/of/v2/users/me/stats/top/stream?${range()}`;
    case "topStory": return `/api/of/v2/users/me/stats/top/story?${range()}`;
    case "topFan": return `/api/of/v2/users/me/stats/top/fan?${range()}`;
    case "streaks": {
      const w = wallOf(p.now ?? new Date(), x.tz ?? null);
      const back = Math.max(0, parseInt(pk.smonth, 10) || 0);
      if (!back) return `/api/of/v2/streaks?${new URLSearchParams({ start: `${w.y}-${pad(w.m)}-01 00:00:00`, end: `${w.y}-${pad(w.m)}-${pad(w.d)} ${pad(w.h)}:${pad(w.mi)}:${pad(w.s)}` })}`;
      const { y, m } = monthBack(w, back);
      return `/api/of/v2/streaks?${new URLSearchParams({ start: `${y}-${pad(m)}-01 00:00:00`, end: `${y}-${pad(m)}-${pad(new Date(Date.UTC(y, m, 0)).getUTCDate())} 23:59:59` })}`;
    }
    case "streakSummary": {
      const a = at(x.top, "startDate");
      const b = at(x.top, "endDate");
      const start = typeof a === "string" ? utcApi(a) : undefined;
      const end = typeof b === "string" ? utcApi(b) : undefined;
      return start && end ? `/api/of/v2/users/me/stats/overview?${new URLSearchParams({ by: "earnings", start, end })}` : "";
    }
    case "streaksTop": return "/api/of/v2/streaks/top";
    case "todayActivity": return "/api/of/v2/users/me/stats/today-activity";
    case "messagesChart": return `/api/of/v2/messages/queue/chart?${range({ type: pk.msg })}`;
    case "streamsChart": return `/api/of/v2/streams/chart?${range({ by: pk.streams })}`;
    case "storiesChart": return `/api/of/v2/stories/chart?${range({ by: pk.stories })}`;
    case "promotionsChart": return `/api/of/v2/promotions/chart?${range()}`;
    case "trialsChart": return `/api/of/v2/trials/chart?${range()}`;
    case "campaignsChart": return `/api/of/v2/campaigns/chart?${range()}`;
    case "fansActivity":
    case "fansHours":
      return `/api/of/v2/fans-activity/list?${new URLSearchParams({ format: source === "fansActivity" ? "table" : "hours", start: p.startApi, end: p.endApi, timeZone: x.tz ?? Intl.DateTimeFormat().resolvedOptions().timeZone ?? "UTC" })}`;
    default: return "/api/of/v2/users/me/start-date-model";
  }
}

// OF reads 10 a page by offset; today's Relay forwards no offset, so its most (50) at once.
export const PAGE_SIZE = 50;
export function pagedRoute(source: StatSource, offset: number, type: EarningsType = "total", p?: Pick<Period, "startApi" | "endApi">): string {
  if (source === "massMessages")
    return `/api/of/v2/users/me/stats/messages/group?${new URLSearchParams({ startDate: p?.startApi ?? "", endDate: p?.endApi ?? "", limit: String(PAGE_SIZE), offset: String(offset) })}`;
  const q = new URLSearchParams({ limit: String(PAGE_SIZE), offset: String(offset), ...(source === "transactions" && type !== "total" ? { type } : {}) });
  const path = source === "transactions" ? "payouts/transactions" : source === "payoutRequests" ? "payouts/requests" : "payouts/requests/referral";
  return `/api/of/v2/${path}?${q}`;
}

// OF's own first marker: period end in unix s, shifted by its UTC offset unless it ends today.
export function firstMarker(p: Pick<Period, "end" | "now" | "tz">): number {
  const end = Math.floor(p.end.getTime() / 1000);
  const e = wallOf(p.end, p.tz);
  const n = wallOf(p.now, p.tz);
  if (e.y === n.y && e.m === n.m && e.d === n.d) return end;
  const off = Math.round((Date.UTC(e.y, e.m - 1, e.d, e.h, e.mi, e.s) - end * 1000) / 1000);
  return end + off;
}

export function listRoute(source: StatSource, p: Pick<Period, "startApi" | "endApi"> & Partial<Pick<Period, "end" | "now" | "tz">>, param: PageParam, x: RouteCtx = {}): string {
  const pk: Picks = { ...PICK_DEFAULTS, ...x.picks };
  const by = pk.by;
  const query = (extra: Record<string, string | number | null | undefined>, dated = true) => {
    const q = new URLSearchParams();
    for (const [k, v] of Object.entries(extra)) if (v !== undefined && v !== null && v !== "") q.set(k, String(v));
    if (dated) {
      q.set("start", p.startApi);
      q.set("end", p.endApi);
    }
    return q.toString();
  };
  const range = (extra: Record<string, string | number | null | undefined>) => query(extra);
  const type = pk.type as EarningsType;
  switch (source) {
    case "transactions":
      if (!x.v2 || !p.end || !p.now) return pagedRoute("transactions", param.offset, type);
      return `/api/of/v2/payouts/transactions?${query({
        limit: OF_PAGE, startDate: p.startApi, marker: param.marker ?? firstMarker({ end: p.end, now: p.now, tz: p.tz ?? null }),
        type: type === "total" ? undefined : type, tipsSource: type === "tips" ? TIPS_SOURCES[pk.tips]?.[0] : undefined,
      }, false)}`;
    case "payoutRequests":
    case "referralRequests":
      if (!x.v3) return pagedRoute(source, param.offset);
      return `/api/of/v2/${source === "payoutRequests" ? "payouts/requests" : "payouts/requests/referral"}?${query({ limit: OF_PAGE, offset: param.offset, marker: param.marker }, true)}`;
    case "massMessages": {
      if (!x.v2) return pagedRoute("massMessages", param.offset, "total", p);
      const search = pk.q.trim().length >= 3 ? pk.q.trim() : "";
      return `/api/of/v2/users/me/stats/messages/${pk.msg === "direct" ? "direct" : "group"}?${query({
        startDate: p.startApi, endDate: param.endDate ?? p.endApi, limit: OF_PAGE, offset: search ? param.offset : 0, query: search,
      }, false)}`;
    }
    case "postsTop": return x.v2 ? `/api/of/v2/posts/top?${range({ by, limit: OF_PAGE, offset: param.offset })}` : `/api/of/v2/posts/top?${range({ by, limit: "50" })}`;
    case "chargebacksList": return `/api/of/v2/payouts/chargebacks?${range({ limit: OF_PAGE, offset: param.offset, marker: param.marker })}`;
    case "referredCreators":
    case "referredUsers":
      return `/api/of/v2/users/me/referrals?${range({ onlyPerformers: source === "referredCreators" ? 1 : 0, offset: param.offset, marker: param.marker })}`;
    case "streamsTop": return `/api/of/v2/streams/top?${range({ by: pk.streams, limit: OF_PAGE, offset: param.offset })}`;
    case "storiesTop": return `/api/of/v2/stories/top?${range({ by: pk.stories, limit: 4, offset: param.offset })}`;
    case "promotionsList": return `/api/of/v2/promotions/stats?${range({ limit: OF_PAGE, offset: param.offset })}`;
    case "trialsList": return `/api/of/v2/trials/stats?${range({ limit: OF_PAGE, offset: param.offset })}`;
    case "campaignsList": {
      const [field, sort] = pk.csort ? pk.csort.split(":") : [];
      return `/api/of/v2/campaigns/stats?${range({ limit: OF_PAGE, offset: param.offset, field, sort })}`;
    }
    case "subsLatest": return `/api/of/v2/subscriptions/subscribers/latest?${range({ by: pk.subs, offset: param.offset })}`;
    case "subsTop": return `/api/of/v2/subscriptions/subscribers/top?${range({ by: pk.top, offset: param.offset })}`;
    default: return "";
  }
}

export const monthBack = (w: { y: number; m: number }, back: number) => {
  const i = w.y * 12 + (w.m - 1) - back;
  return { y: Math.floor(i / 12), m: (i % 12) + 1 };
};

const utcApi = (iso: string) => {
  const d = valid(iso);
  if (!d) return undefined;
  const w = wallOf(d, "UTC");
  return `${w.y}-${pad(w.m)}-${pad(w.d)} ${pad(w.h)}:${pad(w.mi)}:${pad(w.s)}`;
};

export function nextParam(source: StatSource, last: unknown, pages: unknown[], x: RouteCtx = {}): PageParam | undefined {
  const rows = listOf<{ id?: unknown; date?: string }>(last);
  const offset = pages.reduce<number>((n, pg) => n + (listOf(pg)?.length ?? 0), 0);
  if ((source === "transactions" || source === "massMessages") && x.v2 && nothingNew(last, pages)) return undefined;
  if (source === "transactions" && x.v2) {
    const m = (last as { nextMarker?: unknown } | null)?.nextMarker;
    return rows?.length && (last as { hasMore?: unknown }).hasMore !== false && (typeof m === "number" || (typeof m === "string" && /^\d+$/.test(m))) ? { offset, marker: m } : undefined;
  }
  if (source === "massMessages" && x.v2) {
    if (!rows?.length || (last as { hasMore?: unknown }).hasMore === false) return undefined;
    if (({ ...PICK_DEFAULTS, ...x.picks }).q.trim().length >= 3) return { offset };
    const end = rows.at(-1)?.date;
    return end && utcApi(end) ? { offset: 0, endDate: utcApi(end) } : undefined;
  }
  if (source === "postsTop" && !x.v2) return undefined;
  const size = (V2_LISTS as readonly string[]).includes(source) || source === "postsTop" || (source === "massMessages" && x.v2) || ((source === "payoutRequests" || source === "referralRequests") && x.v3) ? OF_PAGE : PAGE_SIZE;
  const n = nextOffset(last, pages, size);
  if (n === undefined) return undefined;
  const marker = (last as { marker?: unknown } | null)?.marker;
  return { offset: n, ...(typeof marker === "string" || typeof marker === "number" ? { marker } : {}) };
}

const SIDEBAR_OVERVIEW: StatSource[] = ["earnings", "visitors", "posts", "messages", "streams"];
const SIDEBAR_STATEMENTS: StatSource[] = ["earnings", "fans", "posts", "messages", "streams", "referralBalance", "referralRequests", "earningsSide"];
const SIDE_SERIES = ["total", "subscribes", "tips", "messages", "post", "stream"];

export function statsSources(page: string): StatSource[] {
  const p = basePage(page);
  if (!p.startsWith("statistics/")) return [];
  const sub = p.slice("statistics/".length);
  const own = ((): StatSource[] => {
    if (sub === "overview/earnings") return [...SIDEBAR_OVERVIEW, "fans", "stats", "referralBalance", "referralRequests", "earningsChart"];
    if (sub === "overview/top-highlights") return [...SIDEBAR_OVERVIEW, "topPost", "topMessage", "topStream", "topFan"];
    if (sub === "overview/streaks") return [...SIDEBAR_OVERVIEW, "streaks", "streaksTop", "todayActivity", "streakSummary"];
    if (sub.startsWith("overview/")) return SIDEBAR_OVERVIEW;
    if (sub === "statements/earnings") return [...SIDEBAR_STATEMENTS, "transactions", "earningsChart"];
    if (sub === "statements/disputes") return [...SIDEBAR_STATEMENTS, "chargebacks", "chargebacksList", "chargebacksChart"];
    if (sub === "statements/payout-request") return [...SIDEBAR_STATEMENTS, "payoutRequests", "payoutsChart"];
    if (sub.startsWith("statements/referrals/")) return [...SIDEBAR_STATEMENTS, "referralsChart", "referredCreators", "referredUsers"];
    if (sub.startsWith("statements/")) return SIDEBAR_STATEMENTS;
    if (sub === "engagement/posts") return ["posts", "postsChart", "topPost", "postsTop"];
    if (sub === "engagement/messages") return ["messages", "massMessages", "messagesChart", "topMessage"];
    if (sub === "engagement/stories") return ["story", "storiesTop", "storiesChart", "topStory"];
    if (sub === "engagement/streaming") return ["streams", "streamsTop", "streamsChart", "topStream"];
    if (sub === "fans/subscriptions") return ["fans", "subsChart", "subsLatest", "topFan"];
    if (sub === "fans/top-fans") return ["fans", "subsTop", "topFan"];
    if (sub === "fans/activity") return ["fans", "fansActivity", "fansHours", "topFan"];
    if (sub.startsWith("fans/")) return ["fans"];
    if (sub === "reach/profile-visitors") return ["visitors", "profileStats"];
    if (sub === "reach/promotions") return ["promo", "promotionsList", "promotionsChart"];
    if (sub === "reach/trial-links") return ["trials", "trialsList", "trialsChart"];
    if (sub === "reach/tracking-links") return ["campaign", "campaignsList", "campaignsChart"];
    return [];
  })();
  return [...own, "startDate"];
}

export type StatsData = Partial<Record<StatSource | "derived", unknown>>;

export interface MassMessage {
  date?: string | null;
  text?: string | null;
  isFree?: boolean;
  mediaCount?: number;
  sentCount?: number;
  viewedCount?: number;
  price?: number | null;
  purchasedCount?: number | null;
  canUnsend?: boolean;
  isCanceled?: boolean;
}

export interface PayoutRow {
  createdAt?: string;
  id?: unknown;
  invoiceId?: string | number | null;
  amount?: number | null;
  currency?: string | null;
  state?: string;
  rejectReason?: string | null;
}

export const listOf = <T,>(body: unknown): T[] | undefined => {
  const b = body as { items?: unknown; users?: unknown } | null;
  return rowsOf<T>(body) ?? (Array.isArray(b?.items) ? (b.items as T[]) : Array.isArray(b?.users) ? (b.users as T[]) : undefined);
};

export interface PagedBody {
  list: unknown[];
  hasMore: boolean;
  loading: boolean;
  more: (() => void) | null;
  stalled?: boolean;
}

export function nextOffset(last: unknown, pages: unknown[], size = PAGE_SIZE): number | undefined {
  const rows = listOf<{ id?: unknown; invoiceId?: unknown }>(last);
  if (!rows?.length) return undefined;
  const more = (last as { hasMore?: unknown }).hasMore;
  if (more === false || (more === undefined && rows.length < size)) return undefined;
  if (nothingNew(last, pages)) return undefined;
  return pages.reduce<number>((n, pg) => n + (listOf(pg)?.length ?? 0), 0);
}

const realId = (v: unknown) => ((typeof v === "number" && v !== 0) || (typeof v === "string" && v !== "" && v !== "0") ? String(v) : undefined);
export function rowId(r: unknown): string | undefined {
  const o = r as { id?: unknown; invoiceId?: unknown; payment?: { id?: unknown } | null } | null;
  return realId(o?.id) ?? realId(o?.invoiceId) ?? realId(o?.payment?.id);
}

export function uniqueRows(pages: unknown[]): PayoutRow[] {
  const seen = new Set<string>();
  return pages.flatMap((pg) => listOf<PayoutRow>(pg) ?? []).filter((r) => {
    const k = rowId(r);
    if (k === undefined) return true;
    if (seen.has(k)) return false;
    seen.add(k);
    return true;
  });
}

export function nothingNew(last: unknown, pages: unknown[]): boolean {
  const rows = listOf<{ id?: unknown; invoiceId?: unknown }>(last);
  if (!rows?.length || pages.length < 2) return false;
  const id = (r: unknown) => rowId(r) ?? JSON.stringify(r);
  const seen = new Set(pages.slice(0, -1).flatMap((pg) => (listOf<unknown>(pg) ?? []).map(id)));
  return rows.every((r) => seen.has(id(r)));
}

export function pagedDone(body: unknown, p: Period): boolean {
  const list = listOf<PayoutRow>(body);
  if (!list || (body as { stalled?: boolean }).stalled) return false;
  return !(body as { hasMore?: boolean }).hasMore || list.some((r) => (timeOf(r) ?? Infinity) < p.start.getTime());
}


const timeOf = (r: { createdAt?: string; date?: string | null }) => valid(r.createdAt ?? r.date ?? undefined)?.getTime();
export { timeOf };
export const inPeriod = (iso: string | undefined, p: Pick<Period, "start" | "end">) => {
  const t = valid(iso)?.getTime();
  return t !== undefined && t >= p.start.getTime() && t <= p.end.getTime();
};

export const sourceBody = (data: StatsData, src: string): unknown => (src === "stats" ? moneyOf("earningStats", data.stats).earningStats : data[src as StatSource]);
export const valueOf = (data: StatsData, key: string): number | null => {
  const i = key.indexOf(":");
  return num(at(sourceBody(data, key.slice(0, i)), key.slice(i + 1)));
};

