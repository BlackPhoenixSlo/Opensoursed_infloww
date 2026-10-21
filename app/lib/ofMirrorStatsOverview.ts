"use client";

/**
 * Statistics › Overview (and the Top cards other tabs share) with the phase-2 Relay reads (omf-statistics-relay), read
 * only once useOfStats' probe finds that Relay; until then the page keeps the generator's honest state:
 * - Earnings: OF's category radios and chart (`/earnings/chart` with OF's eight `<c>_amount` series: the picked row's
 *   daily amount), the period's gross and net per category from it (StatisticsOverview's statisticData);
 * - Top highlights (and Engagement's, Fans' sidebars): OF's Top Message (`/users/me/stats/top/message`), Top Stream
 *   (`…/top/stream`), Top Story (`…/top/story`) and Top Fan (`…/top/fan`) cards, each with its tabs;
 * - Activity Streak: OF's Current / Longest streak counts and this month's calendar with the streak days marked
 *   (`/streaks`, `/streaks/top`, `/users/me/stats/today-activity`).
 */

import { BLUE } from "@/lib/ofMirrorChart";
import { make, plain, valid } from "@/lib/ofMirrorData";
import { moneyOf } from "@/lib/ofMirrorMoney";
import { ELSEWHERE } from "@/lib/ofMirrorTooltip";
import { NOT_YET } from "@/lib/ofMirrorWrites";
import type { Period } from "@/lib/ofMirrorStatsPeriod";
import { monthBack, type Picks, type StatsData } from "@/lib/ofMirrorStatsSources";
import { add, agendaText, at, dateOf, dayText, display, elOf, enable, iconOf, isObj, level, num, ofCount, pad, setAttr, setClass, setText, track, wallOf, MONTHS, type Wall } from "@/lib/ofMirrorStatsDom";
import { amount, drawLine, mediaCounts, moreButton, openUsers, topCard, topItems, usersLink, type MoreItem, type TopPostItem } from "@/lib/ofMirrorStatsKit";
import { avatarOf, type Fan } from "@/lib/ofMirrorAvatar";
import { usd } from "@/lib/ofMirrorMoney";
import { toast } from "@/lib/ofMirrorPost";
import { fullStat, openPostStats } from "@/lib/ofMirrorStatsPostStat";


export interface OverviewCtx {
  picks: Picks;
  v2: boolean;
  img?: (u: string) => string;
  userStart: Date | null;
  /** The phase-1 Relay (useOfStats' second probe): the per-post stats and buyer lists. */
  v3?: boolean;
  /** The Creator's username (the post links OF copies), while known. */
  username?: string | null;
  /** The page (Top Post's menu has "View post" on Overview only). */
  sub?: string;
}


// ---------------------------------------------------------------- Earnings

/**
 * Overview › Earnings' period figures from OF's chart once it answers: the period row's net (`total.total`) and each
 * category's gross and net (`<row>.gross|total`), else the overview's (Phase 1's keys).
 */
export const overviewRekey = (chart: unknown) => (el: Element, key: string) => {
  if (!isObj(chart)) return key;
  const name = el.closest(".b-stats-row__label")?.querySelector("input[name]")?.getAttribute("name");
  if (name && isObj(chart[name])) return `earningsChart:${name}.${key.endsWith(".gross") ? "gross" : "total"}`;
  if (key === "earnings:earning.total" && el.closest(".b-stats-row__head") && isObj(chart.total)) return "earningsChart:total.total";
  return key;
};

function earningsPage(doc: Document, data: StatsData, p: Period, x: OverviewCtx) {
  const chart = data.earningsChart;
  if (!isObj(chart)) return;
  const row = x.picks.row;
  for (const input of doc.querySelectorAll<HTMLInputElement>(".m-overview-earnings-table input.b-input-radio[name]")) {
    const name = input.getAttribute("name")!;
    if (!isObj(chart[name])) continue;
    enable(doc, input);
    const holder = input.closest(".b-input-radio__container");
    if (holder) setAttr(doc, holder, "data-oi-pick", `row:${name}`);
    const on = name === row;
    if (input.checked !== on) {
      const was = input.checked;
      input.checked = on;
      track(doc, () => (input.checked = was));
    }
    const label = input.closest(".b-stats-row__label");
    if (label) setClass(doc, label, "m-current", on);
  }
  const series = chart[row];
  const canvas = doc.querySelector<HTMLCanvasElement>(".b-chart__double-line__base__wrapper canvas");
  const title = doc.querySelector(`.m-overview-earnings-table input[name='${row}'] ~ label`)?.textContent?.trim() || "Total";
  if (isObj(series)) drawLine(doc, canvas, [series.chartAmount, title, "money"], BLUE, 4, true, p.key === "24h" ? "UTC" : p.tz);
}

// ---------------------------------------------------------------- Top cards

const STREAM_TABS: [string, string][] = [["purchases", "Purchases"], ["tips", "Tips"], ["views", "Viewers"], ["likes", "Likes"], ["comments", "Comments"]];
const STORY_TABS: [string, string][] = [["tips", "Tips"], ["views", "Viewers"], ["likes", "Likes"], ["comments", "Comments"]];
const FAN_TABS: [string, string][] = [["total", "Total"], ["subscriptions", "Subscriptions"], ["tips", "Tips"], ["messages", "Messages"]];
/** Fans' sidebar Top Fan adds Streams (statistics-fans.js). */
export const FANS_FAN_TABS: [string, string][] = [...FAN_TABS, ["streams", "Streams"]];

/** OF's card header: the date, the price with its lock, the More button with the card's menu (`menu`). */
function header(doc: Document, date: Date | null, price: number | null, tz: string | null, menu: MoreItem[][] = []) {
  const el = elOf(doc);
  const h = el("div", "b-top-statistic__header");
  h.append(el("strong", "b-top-statistic__header__date", date ? ` ${agendaText(date, tz)} ` : " — "));
  const d = el("div", "b-top-statistic__header__details");
  if (price && price > 0) {
    const tag = el("div", "b-price");
    tag.append(el("span", "", ` ${usd(price)} `), iconOf(doc, "locked"));
    d.append(tag);
  }
  d.append(moreButton(doc, NOT_YET, menu));
  h.append(d);
  return h;
}
/** A stream's or story's media rows (TopStream's dropdownItems, TopStory's): composers this Mirror does not open. */
const COMPOSE: MoreItem[] = ["Add to a new post", "Send to post in a new tab", "Add to a new message", "Add to your story"].map((label) => ({ label }));
/** Their last row: OF's stream statistics modal (it plays the recording) and story viewer are not built. */
const DETAILED: MoreItem[] = [{ label: "View detailed statistics" }];

/** Copy `text` and show OF's toast `done` (else "Failed to copy to clipboard"). */
function copy(doc: Document, text: string, done: string) {
  const clipboard = doc.defaultView?.navigator.clipboard;
  const failed = () => toast(doc, "Failed to copy to clipboard");
  if (!clipboard) return failed();
  clipboard.writeText(text).then(() => toast(doc, done), failed);
}

/**
 * Top Post's More menu (PostDropdown, statistics-overview chunk module 480916, its postMixin flags for the Creator's
 * own post): "Copy link to post" (OF's post link, copied), the post writes (pin, share to story, edit, archive, add a
 * tag) and "View post" (OF's post page) disabled, "Show who bought" and "View detailed statistics" with the phase-1 Relay.
 */
export function postMenu(doc: Document, post: Record<string, unknown>, x: Pick<OverviewCtx, "v3" | "username" | "sub">, tz: string | null): MoreItem[][] {
  if (post.isDeleted) return [];
  const id = post.id;
  const live = !post.isArchived && !post.isPrivateArchived;
  const media = Array.isArray(post.media) ? post.media.length : 0;
  const first: MoreItem[] = [
    { label: "Copy link to post", onPick: x.username && id != null ? () => copy(doc, `https://onlyfans.com/${String(id)}/${x.username}`, "Link to post has been copied to clipboard!") : undefined },
  ];
  if (live) first.push({ label: post.isPinned ? "Unpin from your profile" : "Pin to your profile page", className: "b-post__btn-pin" });
  if (media || post.rawText) first.push({ label: "Share post to story" });
  if (x.sub?.startsWith("overview/")) first.push({ label: "View post" });
  if (post.canEdit) first.push({ label: "Edit post" });
  first.push({ label: post.isArchived ? "Restore Post" : "Archive Post" }, { label: post.isPrivateArchived ? "Restore Post" : "Add to private archive" }, { label: "Add a tag" });
  if (post.hasPurchases) first.push({ label: "Show who bought", onPick: x.v3 && id != null ? () => openUsers(doc, `post-buyers:${String(id)}:0`) : undefined });
  return [first, [{ label: "View detailed statistics", onPick: x.v3 && id != null ? () => openPostStats(doc, id, tz, undefined, !!post.streamId) : undefined }]];
}

/** OF's picture box (the thumb through the Relay's image proxy). */
function picture(doc: Document, url: unknown, img: ((u: string) => string) | undefined, cls = "b-top-statistic__img") {
  if (typeof url !== "string" || !url || !img) return null;
  const box = elOf(doc)("div", cls);
  const i = elOf(doc)("img") as HTMLImageElement;
  i.src = img(url);
  i.alt = "";
  box.append(i);
  return box;
}
/** OF's figures table (TopStreamBody, TopStory): a row per figure, the picked tab's in bold; a value may be OF's link. */
function figures(doc: Document, rows: [label: string, value: (string | Node)[], bold: boolean][]) {
  const el = elOf(doc);
  const t = el("table", "table m-list-determination m-reset-mb");
  for (const [label, value, bold] of rows) {
    const tr = el("tr");
    const v = el("td", `text-right${bold ? " g-semibold" : ""}`);
    v.append(" ", ...value.map((x) => (typeof x === "string" ? doc.createTextNode(x) : x)), " "); // OF pads each value with spaces
    tr.append(el("td", "", label), v);
    t.append(tr);
  }
  return t;
}
const thumbOf = (item: Record<string, unknown>) =>
  at(item, "media.files.thumb.url") ?? (Array.isArray(item.media) ? at(item.media.find((m) => at(m, "files.thumb.url")), "files.thumb.url") : undefined);

/** Overview › Earnings: one month row per month from the Creator's start (or the first month with earnings) to now. */
function applyMonths(doc: Document, data: StatsData, p: Period, userStart: Date | null) {
  const tpl = doc.querySelector<HTMLElement>("[data-oi-template='month']");
  const months = moneyOf("earningStats", data.stats).earningStats?.months;
  if (!tpl || !months) return;
  const net = new Map<string, number>();
  let first: Wall | null = userStart ? wallOf(userStart, p.tz) : null;
  for (const [k, m] of Object.entries(months)) {
    const d = new Date(Number(k) * 1000);
    if (Number.isNaN(d.getTime())) continue;
    const w = wallOf(d, p.tz);
    net.set(`${w.y}-${w.m}`, (net.get(`${w.y}-${w.m}`) ?? 0) + (num(m?.total_net) ?? 0));
    if (!first || w.y * 12 + w.m < first.y * 12 + first.m) first = w;
  }
  if (!first) return;
  const now = wallOf(p.now, p.tz);
  let after: Element = tpl;
  for (let i = now.y * 12 + now.m - 1; i >= first.y * 12 + first.m - 1; i--) {
    const y = Math.floor(i / 12), m = (i % 12) + 1;
    const el = make(tpl);
    el.style.removeProperty("display");
    const title = ` ${MONTHS[m - 1]}, ${y} `;
    el.setAttribute("data-name", title.trim());
    const head = el.querySelector(".b-stats-row__month");
    if (head) head.textContent = title;
    const span = el.querySelector(".b-stats-row__total-net > span");
    if (span) {
      const n = net.get(`${y}-${m}`) ?? 0; // a month /payouts/stats lists no earnings for: OF's $0.00
      span.textContent = ` ${usd(n)} `;
      span.classList.toggle("m-zero-value", Math.round(n) === 0);
    }
    add(doc, el, after, "after");
    after = el;
  }
}

/** OF's Top Post tabs in order (248806 `Gn`), their titles (texts_en.json streaming_summary_<key>_title), money or not. */
const POST_TABS: [key: string, title: string, money: boolean][] = [
  ["purchases", "Purchases", true], ["tips", "Tips", true], ["views", "Views", false], ["likes", "Likes", false], ["comments", "Comments", false],
];
/**
 * Top Post (TopPost, Overview › Top highlights and Engagement › Posts), once `/users/me/stats/top/post` names a post for a
 * metric: the date, price with OF's lock, its first picture (the Relay's image proxy) or OF's no-picture layout, its text,
 * "Full stat" (OF's Post statistics popup with the phase-1 Relay, else disabled), its More menu (postMenu) and OF's
 * footer of its non-zero figures, the picked one marked.
 */
function topPost(doc: Document, body: unknown, p: Period, x: OverviewCtx) {
  const items = topItems(body, POST_TABS.map(([k]) => k));
  topCard(doc, "Top Post", POST_TABS.map(([k, t]) => [k, t]), items, x.picks.tpost, "tpost", (k) => {
    const post = items![k]! as TopPostItem;
    const el = elOf(doc);
    const stat = el("div", "b-top-statistic");
    stat.append(header(doc, valid(post.postedAt) ?? null, num(post.price), p.tz, postMenu(doc, post as Record<string, unknown>, x, p.tz)));
    const pic = picture(doc, post.media?.[0]?.files?.thumb?.url, x.img);
    const b = el("div", `b-top-statistic__body${pic ? "" : " m-without-img"}`);
    if (pic) b.append(pic);
    const content = el("div", "b-top-statistic__content");
    const text = el("div", "b-top-statistic__text");
    text.append(el("p", "", plain(post.rawText ?? post.text)));
    const row = el("div", "b-top-statistic__btns-row");
    const btns = el("div", "b-top-statistic__btns");
    btns.append(fullStat(doc, post, !!x.v3, p.tz));
    const icons = mediaCounts(doc, post as Record<string, unknown>, false);
    if (icons) row.append(icons);
    row.append(btns);
    content.append(text, row);
    b.append(content);
    stat.append(b);
    const values: Record<string, number | null> = {
      purchases: num(post.stats?.purchasedSumm), tips: amount(post.tipsAmount), views: num(post.stats?.lookCount),
      likes: num(post.stats?.likeCount), comments: num(post.commentsCount),
    };
    const shown = POST_TABS.filter(([key]) => values[key]);
    if (shown.length) {
      const footer = el("div", "b-top-statistic__footer");
      const list = el("div", "b-summary-list d-flex flex-wrap g-position-relative");
      const inner = el("div", "m-gaps-inside m-gaps-outside");
      for (const [key, title, isMoney] of shown) {
        const item = el("span", `b-dot-item m-dot-bold b-summary-list__item m-lowercase g-md-text m-default-font-weight d-inline-block${key === k ? " m-current" : ""}`);
        item.append(el("strong", "", isMoney ? usd(values[key]!) : values[key]!.toLocaleString("en-US")), doc.createTextNode(` ${title.toLowerCase()} `));
        inner.append(item);
      }
      list.append(inner);
      footer.append(list);
      stat.append(footer);
    }
    return [stat];
  });
}

/** Top Message (TopMassMessage): its date, price, More menu, picture, text, Unsend (phase 4: disabled) and OF's purchases and views. */
function topMessage(doc: Document, body: unknown, p: Period, x: OverviewCtx) {
  const items = topItems(body, ["purchases"]);
  topCard(doc, "Top Message", [["purchases", "Purchases"]], items, "purchases", "tmsg", (k) => {
    const m = items![k]!;
    const el = elOf(doc);
    const stat = el("div", "b-top-statistic");
    // TopMassMessage's menu: "Show who bought" (a paid message with buyers: its buyer list), then Unsend (phase 4).
    const who: MoreItem[] = !m.isFree && num(m.purchasedCount) ? [{ label: "Show who bought", onPick: x.v2 && m.id !== undefined ? () => openUsers(doc, `buyers:${String(m.id)}:0`) : undefined }] : [];
    stat.append(header(doc, dateOf(m.date), num(m.price), p.tz, [who, [{ label: "Unsend", className: "m-danger", disabledTitle: ELSEWHERE.unsendMass }]]));
    const pic = picture(doc, thumbOf(m), x.img);
    const b = el("div", `b-top-statistic__body${pic ? "" : " m-without-img"}`);
    if (pic) b.append(pic);
    const content = el("div", "b-top-statistic__content");
    const text = el("div", "b-top-statistic__text");
    text.append(el("p", "g-truncated-text m-break-word", plain((m.rawText ?? m.text) as string | null)));
    const row = el("div", "b-top-statistic__btns-row");
    const btns = el("div", "b-top-statistic__btns");
    const unsend = el("button", "g-btn m-flat m-btn-gaps m-ex-sm", " Unsend ") as HTMLButtonElement;
    unsend.type = "button";
    unsend.disabled = true;
    unsend.title = ELSEWHERE.unsendMass;
    btns.append(unsend);
    const icons = mediaCounts(doc, m, false);
    if (icons) row.append(icons);
    row.append(btns);
    content.append(text, row);
    b.append(content);
    const foot = el("div", "b-top-statistic__footer");
    const list = el("div", "b-summary-list d-flex flex-wrap g-position-relative");
    const inner = el("div", "m-gaps-inside m-gaps-outside");
    const bought = num(m.purchasedCount);
    if (bought && !m.isFree) {
      const s = el("span", "b-dot-item b-summary-list__item m-lowercase g-md-text m-default-font-weight d-inline-block m-current");
      // OF's own figure: TopMassMessage's footer renders utils-money with `purchasedCount * price` (statistics-overview
      // chunk, module 309753); the reply carries no sum of its own.
      const sum = usd(bought * (num(m.price) ?? 0));
      s.append(x.v2 && m.id !== undefined ? usersLink(doc, sum, "buyers", m.id) : el("span", "", sum), doc.createTextNode(" purchases "));
      inner.append(s);
    }
    const v = el("span", "b-dot-item b-summary-list__item m-lowercase g-md-text m-default-font-weight d-inline-block");
    v.append(el("strong", "", String(num(m.viewedCount) ?? 0)), doc.createTextNode(" views "));
    inner.append(v);
    list.append(inner);
    foot.append(list);
    stat.append(b, foot);
    return [stat];
  });
}

/** A count: OF's link to its list when it has one (and the Relay reads it), else the number. */
const linked = (doc: Document, n: number, kind: "streams" | "stories", id: unknown, tips: boolean, links: boolean): string | Node =>
  links && n > 0 && id !== undefined ? usersLink(doc, ofCount(n), kind, id, tips) : ofCount(n);

/** A stream's card (TopStreamBody): date, price, picture, Viewers (purchases), Likes, Comments, Tips (their sum). */
export function streamBody(doc: Document, s: Record<string, unknown>, k: string, tz: string | null, img: ((u: string) => string) | undefined, links: boolean): Node[] {
  const el = elOf(doc);
  const pic = picture(doc, at(s, "media.files.thumb.url"), img, "b-top-statistic__img b-photos m-reset-grid");
  const b = el("div", `b-top-statistic__body ${pic ? "m-img-size-lg" : "m-without-img"}`);
  if (pic) b.append(pic);
  const content = el("div", "b-top-statistic__content");
  content.append(figures(doc, [
    ["Viewers", [linked(doc, num(s.viewsCount) ?? 0, "streams", s.id, false, links), ` (${usd(num(s.purchaseAmount) ?? 0)})`], k === "views" || k === "purchases"],
    ["Likes", [ofCount(num(s.likesCount) ?? 0)], k === "likes"],
    ["Comments", [ofCount(num(s.commentsCount) ?? 0)], k === "comments"],
    ["Tips", [linked(doc, num(s.tipsCount) ?? 0, "streams", s.id, true, links), ` (${usd(num(s.tipsSum) ?? 0)})`], k === "tips"],
  ]));
  b.append(content);
  return [header(doc, dateOf(s.startedAt), num(s.price), tz, [s.media && s.canAddToPosts ? COMPOSE : [], DETAILED]), b];
}

/** A story's card (TopStory): date, price, picture, Viewers, Likes, Comments, Tips (their sum). */
export function storyBody(doc: Document, s: Record<string, unknown>, k: string, tz: string | null, img: ((u: string) => string) | undefined, links: boolean): Node[] {
  const el = elOf(doc);
  const pic = picture(doc, at(s, "media.0.files.thumb.url") ?? at(s, "media.files.thumb.url"), img);
  const b = el("div", `b-top-statistic__body ${pic ? "m-img-size-lg" : "m-without-img"}`);
  if (pic) b.append(pic);
  const content = el("div", "b-top-statistic__content");
  content.append(figures(doc, [
    ["Viewers", [linked(doc, num(s.viewersCount) ?? 0, "stories", s.id, false, links)], k === "views"],
    ["Likes", [ofCount(num(s.likesCount) ?? 0)], k === "likes"],
    ["Comments", [ofCount(num(s.commentsCount) ?? 0)], k === "comments"],
    ["Tips", [linked(doc, num(s.tipsCount) ?? 0, "stories", s.id, true, links), ` (${usd(num(s.tipsAmountRaw) ?? 0)})`], k === "tips"],
  ]));
  b.append(content);
  const media = Array.isArray(s.media) ? s.media.length : s.media ? 1 : 0;
  return [header(doc, dateOf(s.createdAt), num(s.price), tz, [media ? COMPOSE : [], DETAILED]), b];
}

/** Top Stream (TopStream). */
function topStream(doc: Document, body: unknown, p: Period, x: OverviewCtx) {
  const items = topItems(body, STREAM_TABS.map(([k]) => k));
  topCard(doc, "Top Stream", STREAM_TABS, items, x.picks.tstream, "tstream", (k) => {
    const stat = elOf(doc)("div", "b-top-statistic");
    stat.append(...streamBody(doc, items![k]!, k, p.tz, x.img, x.v2));
    return [stat];
  });
}

/** Top Story (TopStory). */
function topStory(doc: Document, body: unknown, p: Period, x: OverviewCtx) {
  const items = topItems(body, STORY_TABS.map(([k]) => k));
  topCard(doc, "Top Story", STORY_TABS, items, x.picks.tstory, "tstory", (k) => {
    const stat = elOf(doc)("div", "b-top-statistic");
    stat.append(...storyBody(doc, items![k]!, k, p.tz, x.img, x.v2));
    return [stat];
  });
}

/** A top fan's sum for a tab (OF's subscriber: totalSumm, subscribesSumm, tipsSumm, messagesSumm, streamsSumm). */
const FAN_SUMS: Record<string, string> = { total: "totalSumm", subscriptions: "subscribesSumm", tips: "tipsSumm", messages: "messagesSumm", streams: "streamsSumm" };
export const fanSum = (fan: Record<string, unknown>, key: string) => num(at(fan, `subscribedOnData.${FAN_SUMS[key]}`) ?? fan[FAN_SUMS[key]]);

/** OF's Top Fan body (TopFan): the fan with their price and time subscribed, the tab's total. */
export function topFanBody(doc: Document, fan: Record<string, unknown>, key: string, img: ((u: string) => string) | undefined) {
  const el = elOf(doc);
  const stat = el("div", "b-top-statistic");
  const t = el("table", "table m-reset-mb m-user-economy");
  const tb = el("tbody");
  const tr = el("tr");
  const who = el("td");
  const head = el("div", "b-user-header m-reset-mb m-size-avatar-36");
  head.append(avatarOf(doc, fan as Fan, 36, img));
  const r1 = el("div", "b-username-row");
  const n = el("span", "b-username");
  n.append(el("div", "g-user-name m-md-size", ` ${plain(fan.name as string | null) || String(fan.username ?? "")} `));
  r1.append(n);
  const r2 = el("div", "b-username-row");
  r2.append(el("span", "g-user-username", ` @${String(fan.username ?? "")} `));
  head.append(r1, r2);
  who.append(head);
  const price = el("td", "text-right");
  price.append(el("span", "", usd(num(at(fan, "subscribedOnData.price") ?? fan.price) ?? 0)), el("br"), doc.createTextNode(` ${plain(fan.subscribedOnDuration as string | null)} `));
  tr.append(who, price);
  tb.append(tr);
  const tf = el("tfoot");
  const ft = el("tr");
  const l = el("td");
  l.append(el("strong", "", "Total"));
  const v = el("td", "text-right");
  v.append(el("strong", "", usd(fanSum(fan, key) ?? 0)));
  ft.append(l, v);
  tf.append(ft);
  t.append(tb, tf);
  stat.append(t);
  return stat;
}

/** Top Fan on Overview › Top highlights (TopFan). Fans' sidebar card (with its actions) is ofMirrorStatsFans'. */
function topFan(doc: Document, body: unknown, x: OverviewCtx) {
  const items = topItems(body, FAN_TABS.map(([k]) => k));
  topCard(doc, "Top Fan", FAN_TABS, items, x.picks.fan, "fan", (k) => [topFanBody(doc, items![k]!, k, x.img)]);
}

// ---------------------------------------------------------------- Activity Streak

interface Streak {
  id?: unknown;
  startDate?: string;
  endDate?: string;
  isActive?: boolean;
  daysCount?: number;
  frozenDays?: string[];
}
const dayKey = (w: { y: number; m: number; d: number }) => `${w.y}-${pad(w.m)}-${pad(w.d)}`;

/** OF's streak counts (OverviewStreaks): the active streak's days (with today's activity and its rest days) and the top one's. */
export function streakCounts(list: Streak[], top: unknown, today: unknown, now: Date, tz: string | null) {
  const was = isObj(today) && Object.values(today).some(Boolean);
  const todayN = was ? 1 : 0;
  const yesterday = dayKey(wallOf(new Date(now.getTime() - 86_400_000), tz));
  const active = list.find((s) => s.isActive);
  const frozen = (s: Streak) => (s.frozenDays ?? []).filter((f) => was || dayKey(wallOf(dateOf(f) ?? now, tz)) !== yesterday);
  const current = active ? (num(active.daysCount) ?? 0) + todayN + frozen(active).length : todayN;
  const t = isObj(top) ? (top as Streak) : null;
  const longest = !t || !Object.keys(t).length ? 0 : t.isActive ? current : (num(t.daysCount) ?? 0) + (t.frozenDays?.length ?? 0);
  return { current, longest, today: was };
}

/** OF's duration (OverviewStreaks' getTime: dayjs' "H[h] m[min]" from an hour, else "m[min] s[sec]"). */
export const streakTime = (sec: number) => {
  const h = Math.floor(sec / 3600) % 24;
  const m = Math.floor((sec % 3600) / 60);
  return sec >= 3600 ? `${h}h ${m}min` : `${m}min ${Math.floor(sec % 60)}sec`;
};
/** OverviewStreaks' topStreakDataMap: the Longest streak's rows. */
const TOP_ROWS: [title: string, field: string, time?: boolean][] = [
  ["Created posts", "postsCount"], ["Published stories", "storiesCount"], ["Replies to followers", "chatsCount"], ["Time in live streaming", "streamsDuration", true],
];

/**
 * OF's Longest streak tab (OverviewStreaks, `?tab=top`): "Your longest streak was on <dates>. …active <days> days, with:",
 * its counts and, when the overview's earnings for its dates have a total and a change, "Total earnings".
 */
function topStreakView(doc: Document, top: Streak & Record<string, unknown>, summary: unknown, p: Period, today: boolean) {
  const el = elOf(doc);
  const fmt = (d: Date | null) => (d ? dayText(d, p.tz) : "");
  const end = top.isActive && today ? p.now : dateOf(top.endDate);
  const days = top.isActive ? (num(top.daysCount) ?? 0) + (today ? 1 : 0) : num(top.daysCount) ?? 0;
  const view = el("div");
  view.setAttribute("data-oi-streak-top", "");
  view.append(el("p", "g-default-text m-mb-14", ` Your longest streak was on ${fmt(dateOf(top.startDate))} - ${fmt(end)}. During this period you were active ${days} days, with: `));
  const table = el("table", "table m-list-determination m-large-gaps m-reset-mb");
  const tbody = el("tbody");
  for (const [title, field, time] of TOP_ROWS) {
    const v = num(top[field]) ?? 0;
    const tr = el("tr");
    tr.append(el("td", "", title), el("td", "text-right", ` ${time ? streakTime(v) : v.toLocaleString("en-US", { maximumFractionDigits: 2 })} `));
    tbody.append(tr);
  }
  table.append(tbody);
  const total = num(at(summary, "earning.total"));
  const delta = num(at(summary, "earning.delta"));
  if (total && delta) {
    const foot = el("tfoot");
    const tr = el("tr", "g-border-top");
    const td = el("td", "text-right");
    const value = el("span", "b-elements-determinant__value m-inline", ` ${usd(total)} `);
    value.append(level(doc, delta, false));
    td.append(value);
    tr.append(el("td", "", "Total earnings"), td);
    foot.append(tr);
    table.append(foot);
  }
  view.append(table);
  return view;
}

/**
 * OF's Activity Streak (OverviewStreaks): the Current / Longest tabs with their counts; Current streak: the calendar month
 * `smonth` months back (OF's v-calendar, weeks from Sunday) with the streak days marked as OF marks them, its month
 * switch from the Creator's first month to this one; Longest streak: topStreakView (disabled with no top streak, as OF's).
 */
function streaksPage(doc: Document, data: StatsData, p: Period, x: OverviewCtx) {
  const box = doc.querySelector<HTMLElement>("[data-oi-streaks]");
  const list = at(data.streaks, "list");
  if (!box || !Array.isArray(list) || !isObj(data.streaksTop)) return;
  const streaks = list as Streak[];
  const { current, longest, today } = streakCounts(streaks, data.streaksTop, data.todayActivity, p.now, p.tz);
  display(doc, box, true);
  display(doc, doc.querySelector<HTMLElement>("[data-oi-streaks-clean]"), false);
  const counts = box.querySelectorAll(".b-streak-tab__count");
  setText(doc, counts[0], ` ${current} `);
  setText(doc, counts[1], ` ${longest} `);
  const li = counts[0]?.closest(".b-tabs__nav__item");
  if (li) setClass(doc, li, "m-no-streak", !current);
  // The tabs (TabOF): the picked one current, the other with OF's hover; Longest only with a top streak.
  const top = Object.keys(data.streaksTop).length ? (data.streaksTop as Streak & Record<string, unknown>) : null;
  const tab = x.picks.stab === "top" && top ? "top" : "current";
  for (const b of box.querySelectorAll<HTMLElement>("[data-oi-pick^='stab:']")) {
    const k = b.getAttribute("data-oi-pick")!.slice(5);
    if (k === "top") {
      if (top) enable(doc, b);
      else setAttr(doc, b, "title", null); // OF's is-disabled tab, no tooltip
    }
    const on = k === tab;
    setClass(doc, b, "m-current", on);
    setClass(doc, b, "m-no-pointer", on);
    setClass(doc, b, "m-with-rectangle-hover", !on);
    setClass(doc, b, "m-tb-sm", !on);
    setAttr(doc, b, "tabindex", on ? "-1" : "0");
  }
  const picker = box.querySelector<HTMLElement>(".b-datepicker-wrapper");
  if (tab === "top" && top) {
    display(doc, picker, false);
    if (picker?.parentElement) add(doc, topStreakView(doc, top, data.streakSummary, p, today), picker.parentElement);
    return;
  }
  const real = wallOf(p.now, p.tz);
  const back = Math.max(0, parseInt(x.picks.smonth, 10) || 0);
  const shown = monthBack(real, back);
  const now = { ...real, y: shown.y, m: shown.m };
  setText(doc, box.querySelector(".b-streaks-swither__time"), ` ${MONTHS[now.m - 1]} ${now.y} `);
  // The month switch: back to the Creator's first month, forward to this one (OF's isChangeMonthDisable).
  const since = x.userStart ? wallOf(x.userStart, p.tz) : null;
  for (const b of box.querySelectorAll<HTMLElement>("[data-oi-streak-month]")) {
    const prev = b.getAttribute("data-oi-streak-month") === "prev";
    const off = prev ? !!since && since.y * 12 + since.m >= now.y * 12 + now.m : back === 0;
    setAttr(doc, b, "title", null);
    setAttr(doc, b, "disabled", off ? "disabled" : null);
    setAttr(doc, b, "data-oi-pick", `smonth:${prev ? back + 1 : back - 1}`);
    setAttr(doc, b, "data-oi-wired", "");
    setClass(doc, b, "m-gray", off);
    setClass(doc, b, "m-default-color", !off);
  }
  // The marks per day of the month (OF's getDayClasses).
  const marks = new Map<string, string[]>();
  const mark = (k: string, cls: string) => marks.set(k, [...(marks.get(k) ?? []), cls]);
  const keyOf = (iso: string | undefined) => {
    const d = dateOf(iso) ?? (iso && /^\d{4}-\d{2}-\d{2}$/.test(iso) ? new Date(`${iso}T12:00:00Z`) : null);
    return d ? dayKey(wallOf(d, p.tz)) : null;
  };
  const todayKey = dayKey(real);
  for (const s of streaks) {
    const a = keyOf(s.startDate);
    const b = s.isActive ? (today ? todayKey : keyOf(s.endDate)) : keyOf(s.endDate);
    if (!a || !b) continue;
    const frozen = new Set((s.frozenDays ?? []).map((f) => keyOf(f)).filter(Boolean) as string[]);
    for (let d = new Date(`${a}T12:00:00Z`); dayKey(wallOf(d, "UTC")) <= b; d = new Date(d.getTime() + 86_400_000)) {
      const k = dayKey(wallOf(d, "UTC"));
      if (frozen.has(k)) mark(k, "m-frozen-date");
      else if (a === b) mark(k, "vc-marked-day vc-marked-single");
      else if (k === a) mark(k, "vc-marked-day vc-range-start");
      else if (k === b) mark(k, "vc-marked-day vc-range-end");
      else mark(k, "vc-marked-day");
      if (s.isActive && k === a) mark(k, "m-active-streak");
    }
  }
  if (today && !marks.has(todayKey)) mark(todayKey, "vc-marked-day vc-marked-single m-active-streak");
  // The grid: OF's weeks of this month, the days around it `v-outside`.
  const cal = box.querySelector(".v-calendar-monthly");
  const weekTpl = cal?.querySelector(".v-calendar-weekly__week");
  if (!cal || !weekTpl) return;
  const el = elOf(doc);
  const first = new Date(Date.UTC(now.y, now.m - 1, 1, 12));
  const start = new Date(first.getTime() - first.getUTCDay() * 86_400_000);
  const last = new Date(Date.UTC(now.y, now.m, 0, 12));
  const startKey = x.userStart ? dayKey(wallOf(x.userStart, p.tz)) : null;
  for (const w of cal.querySelectorAll<HTMLElement>(".v-calendar-weekly__week")) display(doc, w, false);
  for (let ws = start; ws <= last; ws = new Date(ws.getTime() + 7 * 86_400_000)) {
    const week = el("div", "v-calendar-weekly__week");
    for (let i = 0; i < 7; i++) {
      const d = new Date(ws.getTime() + i * 86_400_000);
      const w = wallOf(d, "UTC");
      const k = dayKey(w);
      const when = k < todayKey ? "v-past" : k === todayKey ? "v-present" : "v-future";
      const day = el("div", `v-calendar-weekly__day ${when}${w.m !== now.m ? " v-outside" : ""}`);
      const label = el("div", "v-calendar-weekly__day-label");
      const cls = startKey && k < startKey ? ["vc-disabled"] : marks.get(k) ?? [];
      label.append(el("span", cls.join(" "), String(w.d)));
      day.append(label);
      week.append(day);
    }
    add(doc, week, cal);
  }
}

/** The Overview tabs' (and the shared Top cards') phase-2 parts for page `sub`. */
export function applyOverview(doc: Document, sub: string, data: StatsData, p: Period, x: OverviewCtx) {
  if (sub === "overview/earnings") earningsPage(doc, data, p, x);
  applyMonths(doc, data, p, x.userStart);
  if (data.topPost !== undefined) topPost(doc, data.topPost, p, x);
  if (sub === "overview/streaks") streaksPage(doc, data, p, x);
  if (data.topMessage !== undefined) topMessage(doc, data.topMessage, p, x);
  if (data.topStream !== undefined) topStream(doc, data.topStream, p, x);
  if (data.topStory !== undefined) topStory(doc, data.topStory, p, x);
  if (data.topFan !== undefined && sub.startsWith("overview/")) topFan(doc, data.topFan, x);
}
