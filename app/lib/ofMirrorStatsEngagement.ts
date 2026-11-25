"use client";


import { viewDuration } from "@/lib/ofMirrorChart";
import { plain } from "@/lib/ofMirrorData";
import { valid } from "@/lib/ofMirrorDom";
import type { Period } from "@/lib/ofMirrorStatsPeriod";
import { listOf, type MassMessage, type PagedBody, type Picks, type PostsBy, type StatsData } from "@/lib/ofMirrorStatsSources";
import { add, agendaText, at, cell, count, display, elOf, enable, isObj, loadingRow, moreAt, num, ofCount, pickTabs, setClass, setText } from "@/lib/ofMirrorStatsDom";
import { amount, drawPair, intoRows, mediaCounts, seriesOf, usersLink, type TopPostItem } from "@/lib/ofMirrorStatsKit";
import { fullStat } from "@/lib/ofMirrorStatsPostStat";
import { storyBody, streamBody } from "@/lib/ofMirrorStatsOverview";
import { DASH, usd } from "@/lib/ofMirrorMoney";

export function applyMassMessages(doc: Document, items: MassMessage[], tz: string | null, paged?: Partial<PagedBody>) {
  const tpl = doc.querySelector<HTMLElement>(".b-statements-table tbody > tr[data-oi-template]");
  intoRows(doc, tpl?.parentElement, items, () => tpl, (el, m) => {
    const d = valid(m.date ?? undefined);
    const date = cell(el, 0)?.querySelector("strong");
    if (date) date.textContent = d ? ` ${agendaText(d, tz)} ` : " — ";
    const sent = cell(el, 1);
    if (sent) sent.textContent = count(m.sentCount);
    const viewed = cell(el, 2)?.querySelector("span");
    if (viewed) viewed.textContent = count(m.viewedCount);
    const price = num(m.price);
    const priceCell = cell(el, 3);
    if (priceCell) priceCell.textContent = !m.isFree && price !== null ? ` ${usd(price)} ` : " — ";
    const bought = cell(el, 4)?.querySelector("span");
    if (bought) bought.textContent = !m.isFree && num(m.purchasedCount) !== null ? count(m.purchasedCount) : " — ";
    const text = el.querySelector(".b-top-statistic__text p");
    if (text) text.textContent = plain(m.text);
    const media = num(m.mediaCount) ?? 0;
    if (!media) {
      el.querySelector(".b-content-inside-thumbs")?.remove();
      const img = el.querySelector(".b-top-statistic__img");
      if (img) {
        img.className = "b-top-statistic__img b-top-statistic__img--placeholder";
        img.replaceChildren();
      }
    }
    const n = el.querySelector(".b-content-inside-thumbs__count");
    if (n) n.textContent = String(media);
    const btns = el.querySelector(".b-top-statistic__btns");
    const button = btns?.querySelector("button");
    if (btns && m.isCanceled) {
      el.classList.add("m-colored-bg");
      if (button) button.textContent = " New message ";
      btns.querySelector(".g-icon-info")?.remove();
      btns.insertAdjacentHTML(
        "beforeend",
        '<div tabindex="0" class="g-btn g-pointer-cursor m-with-round-hover m-size-sm-hover m-icon m-icon-only m-danger-color m-xs-size has-tooltip" aria-label="Canceled"><svg data-icon-name="icon-undo" aria-hidden="true" class="m-icon-sm m-block g-icon"><use href="#icon-undo" xlink:href="#icon-undo"></use></svg></div>',
      );
    } else if (btns && !m.canUnsend) btns.remove();
  });
  const last = [...(tpl?.parentElement?.querySelectorAll(":scope > tr[data-oi-data]") ?? [])].at(-1);
  moreAt(doc, last, paged?.more);
  if (!items.length && paged?.hasMore) loadingRow(doc, tpl?.parentElement);
}


interface TopRowPost extends TopPostItem {
  stats?: { purchasedSumm?: number | null; lookCount?: number | null; likeCount?: number | null; commentCount?: number | null } | null;
}
const POSTS_COLUMN: Record<PostsBy, string> = { purchases: "Tips", tips: "Tips", views: "Likes", likes: "Likes", comments: "Comments" };

export function applyEngagementPosts(doc: Document, data: StatsData, p: Period, by: PostsBy, img: ((u: string) => string) | undefined, v3 = false) {
  pickTabs(doc, "by", by);
  setText(doc, doc.querySelector("[data-oi-posts-col]"), ` ${POSTS_COLUMN[by]} `);
  const items = listOf<TopRowPost>(data.postsTop);
  const table = doc.querySelector<HTMLElement>("[data-oi-table='posts']");
  const tbody = table?.querySelector("tbody");
  if (!items?.length || !tbody) return;
  const wrapper = doc.querySelector(".b-statistics-page-content__wrapper");
  if (wrapper) setClass(doc, wrapper, "m-empty-wrapper", false);
  display(doc, wrapper?.querySelector<HTMLElement>(":scope > .empty-message"), false);
  display(doc, table, true);
  const el = elOf(doc);
  const moneyCell = (v: number | null) => (v ? ` ${usd(v)} ` : " — ");
  for (const post of items) {
    const tr = el("tr", "m-responsive__reset-pb");
    tr.dataset.oiData = "";
    const st = post.stats ?? {};
    const date = el("td", "m-responsive__before-line-over m-width-engagement");
    const posted = valid(post.postedAt);
    const holder = el("div");
    holder.append(el("strong", "", posted ? ` ${agendaText(posted, p.tz)} ` : " — "));
    date.append(holder);
    const views = el("td", `m-responsive__before-line-over${by === "views" ? " g-semibold" : ""}`, ` ${ofCount(num(st.lookCount) ?? 0)} `);
    const metric = el("td", "m-responsive__before-line-over");
    const metricValue = by === "comments" ? ` ${ofCount(num(st.commentCount) ?? 0)} ` : by === "views" || by === "likes" ? ` ${ofCount(num(st.likeCount) ?? 0)} ` : ` ${usd(amount(post.tipsAmount) ?? 0)} `;
    const tips = amount(post.tipsAmount) ?? 0;
    const linked = (text: string, kind: "post-tips" | "post-buyers", n: number): string | Node => (v3 && n > 0 && post.id != null ? usersLink(doc, text.trim(), kind, post.id) : text);
    const mv = el("span", by === "tips" || by === "likes" || by === "comments" ? "g-semibold" : "");
    mv.append(by === "tips" || by === "purchases" ? linked(metricValue, "post-tips", tips) : metricValue);
    metric.append(mv);
    const price = el("td", "m-responsive__before-line-over", moneyCell(num(post.price)));
    const bought = el("td", "m-responsive__before-line-over m-last-in-row");
    const bv = el("span", by === "purchases" ? "g-semibold" : "");
    bv.append(linked(moneyCell(num(st.purchasedSumm)), "post-buyers", num(st.purchasedSumm) ?? 0));
    bought.append(bv);
    const body = el("td", "m-responsive__border-line__over text-left");
    const stat = el("div", "b-top-statistic");
    const sb = el("div", "b-top-statistic__body");
    const thumb = post.media?.[0]?.files?.thumb?.url;
    const src = thumb && img ? img(thumb) : "";
    const pic = el("div", `b-top-statistic__img${src ? "" : " b-top-statistic__img--placeholder"}`);
    if (src) {
      const image = el("img") as HTMLImageElement;
      image.src = src;
      image.alt = "";
      pic.append(image);
    }
    const content = el("div", "b-top-statistic__content");
    const text = el("div", "b-top-statistic__text");
    text.append(el("p", "g-truncated-text m-break-word", plain(post.rawText ?? post.text)));
    const row = el("div", "b-top-statistic__btns-row");
    const btns = el("div", "b-top-statistic__btns");
    btns.append(fullStat(doc, post, v3, p.tz));
    const icons = mediaCounts(doc, post, true);
    if (icons) row.append(icons);
    row.append(btns);
    content.append(text, row);
    sb.append(pic, content);
    stat.append(sb);
    body.append(stat);
    tr.append(date, views, metric, price, bought, body);
    add(doc, tr, tbody, "append");
  }
  const chart = by === "purchases" && data.postsChart && typeof data.postsChart === "object";
  display(doc, doc.querySelector<HTMLElement>("[data-oi-posts-summary]"), !!chart);
  display(doc, doc.querySelector<HTMLElement>("[data-oi-posts-chart]"), !!chart);
  const n = num(at(data.postsChart, "posts.total"));
  setText(doc, doc.querySelector("[data-oi-posts-word]"), n === 1 ? "post" : "posts");
}


export interface EngagementCtx {
  picks: Picks;
  v2: boolean;
  by: PostsBy;
  img?: (u: string) => string;
  pick: (name: "q", value: string) => void;
}

const messagesKey = (chart: unknown, key: string, field: "total" | "delta") => (isObj(chart) && isObj(chart[key]) ? `messagesChart:${key}.${field}` : null);
export const messagesRekey = (chart: unknown, t: string) => (el: Element, key: string) => {
  if (el.closest(".l-wrapper__sidebar")) return key;
  const map: Record<string, string | null> = {
    "messages:massMessages.count.total": messagesKey(chart, `${t}_messages`, "total"),
    "messages:massMessages.earnings.total": messagesKey(chart, `${t}_messages_purchases`, "total"),
    "messages:massMessages.count.delta": messagesKey(chart, `${t}_messages_purchases`, "delta"),
  };
  return map[key] ?? key;
};
export const postsRekey = (chart: unknown, by: PostsBy) => (_el: Element, key: string) =>
  key.startsWith("postsChart:purchases.") && isObj(chart) && isObj(chart[by]) ? `postsChart:${by}.${key.slice("postsChart:purchases.".length)}` : key;

const searchBound = new WeakMap<Document, EngagementCtx>();
function bindSearch(doc: Document, form: HTMLElement, x: EngagementCtx) {
  const bound = searchBound.has(doc);
  searchBound.set(doc, x);
  const input = form.querySelector<HTMLInputElement>("input[type='search']");
  const button = form.querySelector<HTMLButtonElement>("button[type='submit']");
  for (const el of [input, button]) {
    if (!el || !el.disabled) continue;
    el.disabled = false;
    el.removeAttribute("title");
    el.setAttribute("data-oi-wired", "");
  }
  const clear = form.querySelector<HTMLElement>(".b-search-form__clear-input");
  display(doc, clear, !!x.picks.q);
  if (bound || !input) return;
  let timer: ReturnType<typeof setTimeout> | undefined;
  const send = () => {
    const v = input.value.trim();
    if (v.length >= 3 || !v) searchBound.get(doc)?.pick("q", v);
  };
  input.addEventListener("input", () => {
    clearTimeout(timer);
    timer = setTimeout(send, 500);
  });
  form.addEventListener("submit", (ev) => {
    ev.preventDefault();
    clearTimeout(timer);
    send();
  });
  clear?.addEventListener("click", () => {
    input.value = "";
    searchBound.get(doc)?.pick("q", "");
  });
}

interface Row {
  id?: unknown;
  isFree?: boolean;
  purchasedCount?: unknown;
}

function messagesPage(doc: Document, data: StatsData, p: Period, x: EngagementCtx) {
  const t = x.picks.msg === "direct" ? "direct" : "group";
  if (x.v2) {
    for (const b of doc.querySelectorAll("[data-oi-pick^='msg:'][data-oi-enable]")) enable(doc, b);
    pickTabs(doc, "msg", t);
    const form = doc.querySelector<HTMLElement>("[data-oi-search]");
    if (form) bindSearch(doc, form, x);
  }
  const list = (data.massMessages as Partial<PagedBody> | undefined)?.list as Row[] | undefined;
  const rows = [...doc.querySelectorAll(".b-statements-table tbody > tr[data-oi-data]")];
  if (x.v2 && list)
    rows.forEach((tr, i) => {
      const m = list[i];
      const span = tr.querySelectorAll(":scope > td")[4]?.querySelector<HTMLElement>("span");
      const n = num(m?.purchasedCount);
      if (!span || !m || m.isFree || !n) return;
      const link = usersLink(doc, n.toLocaleString("en-US"), "buyers", m.id);
      link.className = "g-page__link g-blue";
      add(doc, link, span, "after");
      display(doc, span, false);
    });
  const chart = data.messagesChart;
  if (!isObj(chart)) return;
  const bought = seriesOf(chart, `${t}_messages_purchases`);
  const sent = seriesOf(chart, `${t}_messages`);
  if (bought?.chart) drawPair(doc, doc.querySelector(".b-statistics-page-content__wrapper > .b-chart"), [bought.chart, "Purchases", "money"], sent?.chart ? [sent.chart, "Messages", "count"] : null, p.key === "24h" ? "UTC" : p.tz);
}

const METRIC: Record<string, [title: string, money: boolean, plural: string]> = {
  purchases: ["Purchases", true, "purchases"], tips: ["Tips", true, "tips"], views: ["Viewers", false, "viewers"],
  likes: ["Likes", false, "likes"], comments: ["Comments", false, "comments"],
};
const POSTS_TITLE: Record<string, string> = { purchases: "Purchases", tips: "Tips", views: "Views", likes: "Likes", comments: "Comments" };

function postsPage(doc: Document, data: StatsData, p: Period, x: EngagementCtx) {
  const body = data.postsTop as Partial<PagedBody> | undefined;
  const tbody = doc.querySelector("[data-oi-table='posts'] tbody");
  if (tbody && body?.more) moreAt(doc, tbody.lastElementChild, body.more);
  const s = seriesOf(data.postsChart, x.by);
  if (!x.v2 || !s || x.by === "purchases" || !body?.list?.length) return;
  const summary = doc.querySelector<HTMLElement>("[data-oi-posts-summary]");
  display(doc, summary, true);
  display(doc, doc.querySelector<HTMLElement>("[data-oi-posts-chart]"), true);
  const [, isMoney, plural] = METRIC[x.by === "views" ? "views" : x.by] ?? ["", false, ""];
  const value = summary?.querySelector("[data-oi-stat^='postsChart:']:not([data-oi-stat='postsChart:posts.total'])");
  if (value && !isMoney) {
    setText(doc, value, ` ${(s.total ?? 0).toLocaleString("en-US")} ${x.by === "views" ? "views" : plural} `);
    setClass(doc, value, "m-zero-value", false);
  }
  const posts = seriesOf(data.postsChart, "posts");
  drawPair(doc, doc.querySelector("[data-oi-posts-chart]"), [s.chart, POSTS_TITLE[x.by], isMoney ? "money" : "count"], posts?.chart ? [posts.chart, "Posts", "count"] : null, p.key === "24h" ? "UTC" : p.tz);
}

function summaryCard(doc: Document, kind: "streams" | "stories", data: StatsData) {
  const o = at(kind === "streams" ? data.streams : data.story, kind);
  const span = [...doc.querySelectorAll<HTMLElement>(".l-wrapper__sidebar .b-useful-data > .empty-message [data-oi-empty]")][0];
  if (!isObj(o) || !span) return;
  const total = at(o, "count.total");
  const none = total == null || o.hasStatistic === false || /^0(\D|$)/.test(String(total));
  if (none) return;
  const el = elOf(doc);
  const row = (label: string, value: string) => {
    const r = el("div", "b-elements-determinant");
    const unit = el("div", "b-elements-determinant__unit");
    unit.append(el("div", "b-elements-determinant__label", ` ${label} `), el("div", "b-elements-determinant__value", ` ${value} `));
    r.append(unit);
    return r;
  };
  const moneyOf = (v: unknown) => (num(v) === null ? DASH : usd(num(v)!));
  const item = el("div", "b-statistics-item");
  item.append(
    row(kind === "streams" ? "Streams" : "Stories", kind === "streams" ? String(total) : ofCount(total)),
    row(kind === "streams" ? "Viewers" : "Views", at(o, "views.total") == null ? "—" : ofCount(at(o, "views.total"))),
    kind === "streams" ? row("Stream earnings", moneyOf(at(o, "earnings.total"))) : row("Tips", moneyOf(at(o, "tips.total"))),
  );
  const cols = el("div", "b-statistics-columns m-separate-block");
  cols.setAttribute("data-oi-summary-card", kind);
  cols.append(item);
  const msg = span.closest<HTMLElement>(".empty-message")!;
  add(doc, cols, msg, "after");
  display(doc, msg, false);
  const header = msg.parentElement?.querySelector(":scope > .b-useful-data__header");
  if (header) setClass(doc, header, "m-without-content", false);
}

function listPage(doc: Document, kind: "streams" | "stories", data: StatsData, p: Period, x: EngagementCtx) {
  const by = x.picks[kind];
  if (x.v2) {
    for (const b of doc.querySelectorAll(`[data-oi-pick^='${kind}:'][data-oi-enable]`)) enable(doc, b);
    pickTabs(doc, kind, by);
  }
  summaryCard(doc, kind, data);
  const body = data[kind === "streams" ? "streamsTop" : "storiesTop"] as Partial<PagedBody> | undefined;
  const box = doc.querySelector<HTMLElement>(`[data-oi-list='${kind}']`);
  const empty = doc.querySelector(".b-statistics-page-content__wrapper > .empty-message [data-oi-empty]");
  if (!body?.list || !box) return;
  const items = body.list as Record<string, unknown>[];
  if (!items.length) {
    if (!body.hasMore && empty) setText(doc, empty, empty.getAttribute("data-oi-empty")!);
    return;
  }
  const el = elOf(doc);
  for (const it of items) {
    const card = el("div", "b-top-statistic b-statistics-item");
    card.append(...(kind === "streams" ? streamBody : storyBody)(doc, it, by, p.tz, x.img, true));
    add(doc, card, box);
  }
  display(doc, box, true);
  display(doc, empty?.closest<HTMLElement>(".empty-message"), false);
  const wrapper = box.closest(".b-statistics-page-content__wrapper");
  if (wrapper) setClass(doc, wrapper, "m-empty-wrapper", false);
  moreAt(doc, box.lastElementChild, body.more);
  const chart = data[kind === "streams" ? "streamsChart" : "storiesChart"];
  const s = seriesOf(chart, by);
  if (!s) return;
  const other = seriesOf(chart, kind === "streams" ? "duration" : "stories");
  const [title, isMoney, plural] = METRIC[by] ?? ["", false, ""];
  const summary = doc.querySelector<HTMLElement>(`[data-oi-summary='${kind}']`);
  display(doc, summary, true);
  setText(doc, summary?.querySelector("[data-oi-summary-a]"), kind === "streams" ? ` ${viewDuration(other?.total ?? 0)} ` : ` ${(other?.total ?? 0).toLocaleString("en-US")} ${other?.total === 1 ? "story" : "stories"} `);
  setText(doc, summary?.querySelector("[data-oi-summary-b]"), isMoney ? ` ${usd(s.total ?? 0)} ` : ` ${(s.total ?? 0).toLocaleString("en-US")} ${plural} `);
  const chartBox = doc.querySelector<HTMLElement>(`[data-oi-chart='${kind}']`);
  display(doc, chartBox, true);
  drawPair(doc, chartBox, [s.chart, title, isMoney ? "money" : "count"], other?.chart ? [other.chart, kind === "streams" ? "Duration" : "Stories", kind === "streams" ? "duration" : "count"] : null, p.key === "24h" ? "UTC" : p.tz);
}

export function applyEngagement(doc: Document, sub: string, data: StatsData, p: Period, x: EngagementCtx) {
  if (sub === "engagement/messages") messagesPage(doc, data, p, x);
  if (sub === "engagement/posts") postsPage(doc, data, p, x);
  if (sub === "engagement/streaming") listPage(doc, "streams", data, p, x);
  if (sub === "engagement/stories") listPage(doc, "stories", data, p, x);
}
