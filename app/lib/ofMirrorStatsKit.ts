"use client";


import { BLUE, GREY, chartLabels, clearChart, drawChart, type ValueKind } from "@/lib/ofMirrorChart";
import { plain } from "@/lib/ofMirrorData";
import { make } from "@/lib/ofMirrorDom";
import { add, at, display, elOf, iconOf, isObj, level, num, setClass, setText, track } from "@/lib/ofMirrorStatsDom";
import { usd } from "@/lib/ofMirrorMoney";
import { openModal } from "@/lib/ofMirrorWrites";
import { showMenu, type MenuGroup } from "@/lib/ofMirrorMenu";
import { relay } from "@/lib/relay";
import { avatarOf, type Fan } from "@/lib/ofMirrorAvatar";
import { errText } from "@/lib/errText";

export const points = (list: unknown): { date?: string; count?: unknown }[] | null => (Array.isArray(list) ? (list as { date?: string; count?: unknown }[]) : null);
export type Line = [list: unknown, title: string, kind: ValueKind];

const linePoints = (pts: { date?: string; count?: unknown }[]) => (pts.length === 1 ? [{ count: 0, date: pts[0].date }, pts[0]] : pts);

export function drawLine(doc: Document, c: HTMLCanvasElement | null | undefined, [list, title, kind]: Line, color: string, ticks: number, xLabels: boolean, tz: string | null, dates?: { date?: string }[]) {
  const raw = points(list);
  if (!c || !raw) return false;
  const pts = linePoints(raw);
  drawChart(c, { labels: chartLabels((dates ?? pts).map((x) => x.date), tz), series: { title, values: pts.map((x) => num(x.count) ?? 0), color, kind }, ticks, xLabels });
  track(doc, () => clearChart(c));
  return true;
}
export function drawPair(doc: Document, root: ParentNode | null | undefined, main: Line, aside: Line | null, tz: string | null) {
  if (!root) return;
  const mainPts = points(main[0]);
  drawLine(doc, root.querySelector<HTMLCanvasElement>("canvas.b-chart__double-line__main"), main, BLUE, 3, !aside, tz);
  if (aside) drawLine(doc, root.querySelector<HTMLCanvasElement>("canvas.b-chart__double-line__aside"), aside, GREY, 2, true, tz, mainPts ? linePoints(mainPts) : undefined);
}

export interface Series {
  chart: unknown[] | null;
  total: number | null;
  delta: number | null;
  gross?: number | null;
}
export function seriesOf(body: unknown, key: string): Series | null {
  const s = at(body, key);
  if (!isObj(s)) return null;
  const chart = points(s.chart);
  if (!chart && num(s.total) === null) return null;
  return { chart, total: num(s.total), delta: num(s.delta), gross: num(s.gross) };
}

export function earningsSeries(body: unknown, key: string): { amount: unknown[] | null; count: unknown[] | null; total: number | null; gross: number | null; delta: number | null } | null {
  const own = at(body, key);
  if (!isObj(own)) return null;
  const amount = points(own.chartAmount);
  if (!amount && num(own.total) === null) return null;
  return { amount, count: points(own.chartCount), total: num(own.total), gross: num(own.gross), delta: num(own.delta) };
}

export function fillChartBox(doc: Document, key: string, total: number | null, delta: number | null, isMoney: boolean, main: Line, aside: Line | null, tz: string | null, showDelta = true) {
  const box = doc.querySelector<HTMLElement>(`[data-oi-chartbox='${key}']`);
  if (!box) return;
  display(doc, box, true);
  const value = box.querySelector("[data-oi-chart-total]");
  setText(doc, value, total === null ? " — " : isMoney ? ` ${usd(total)} ` : ` ${total.toLocaleString("en-US")} `);
  if (value && isMoney) setClass(doc, value, "m-zero-value", total !== null && Math.round(total) === 0);
  const holder = box.querySelector("[data-oi-chart-delta]");
  if (holder && showDelta && delta) add(doc, level(doc, delta, true), holder, "append");
  drawPair(doc, box, main, aside, tz);
}

export function fanCell(doc: Document, u: Fan, img: ((u: string) => string) | undefined) {
  const el = elOf(doc);
  const td = el("td", "m-responsive__equal-width_float m-fans-table-cell m-fans-cell-long");
  const head = el("div", "b-user-header m-reset-mb m-size-avatar-36");
  head.append(avatarOf(doc, u, 36, img));
  const r1 = el("div", "b-username-row m-reset-mt m-absolute-limit");
  const a1 = el("span", "b-username");
  a1.append(el("div", "g-user-name m-md-size", ` ${plain(u.name) || u.username || ""} `));
  r1.append(a1);
  const r2 = el("div", "b-username-row m-absolute-limit");
  const a2 = el("span", "d-flex align-items-center m-full-name");
  a2.append(el("span", "g-user-username", ` @${u.username ?? ""} `));
  r2.append(a2);
  head.append(r1, r2);
  td.append(head);
  return td;
}

export function rowsOrEmpty(doc: Document, table: HTMLElement | null | undefined, empty: Element | null | undefined, rows: number, done: boolean) {
  const holder = empty?.closest<HTMLElement>(".empty-message") ?? (empty as HTMLElement | null | undefined);
  if (rows) {
    display(doc, table, true);
    display(doc, holder, false);
    const wrapper = table?.closest(".b-statistics-page-content__wrapper");
    if (wrapper) setClass(doc, wrapper, "m-empty-wrapper", false);
    return;
  }
  const text = empty?.getAttribute("data-oi-empty");
  if (done && empty && text) setText(doc, empty, text);
}

export function topItems(body: unknown, tabs: string[]): Record<string, Record<string, unknown> | null> | null {
  if (!isObj(body)) return null;
  return Object.fromEntries(tabs.map((t) => [t, isObj(body[t]) ? (body[t] as Record<string, unknown>) : null]));
}

export function topCard(doc: Document, title: string, tabs: [key: string, text: string][], items: Record<string, unknown> | null, picked: string, pick: string, body: (key: string) => Node[]): string | null {
  const enabled = tabs.filter(([k]) => items?.[k]);
  const cur = enabled.find(([k]) => k === picked)?.[0] ?? enabled[0]?.[0] ?? null;
  const el = elOf(doc);
  for (const t of doc.querySelectorAll(".b-clean-state__title")) {
    if (t.textContent?.trim() !== title || !items) continue;
    const clean = t.closest<HTMLElement>(".b-clean-state");
    const box = clean?.parentElement;
    if (!clean || !box) continue;
    if (!cur) {
      const empty = clean.querySelector("[data-oi-empty]");
      if (empty) setText(doc, empty, empty.getAttribute("data-oi-empty")!);
      continue;
    }
    const card = el("div");
    card.setAttribute("data-oi-top", title);
    card.append(el("div", "b-section-title m-simple-text", ` ${title} `));
    const nav = el("div", "b-tabs__nav m-nv m-tab-rounded m-single-current");
    const ul = el("ul", "b-dragscroll m-native-custom-scrollbar m-scrollbar-x m-invisible-scrollbar b-tabs__nav__list m-scroll-behavior m-reset-overscroll m-gaps-inside m-gaps-outside");
    ul.setAttribute("data-v-7dac08ac", "");
    for (const [key, text] of tabs) {
      const li = el("li", "b-tabs__nav__item");
      const on = key === cur;
      const b = el("button", `b-tabs__nav__link m-reset-wcag-link-focus${on ? " m-current m-no-pointer" : ""}`) as HTMLButtonElement;
      b.type = "button";
      b.tabIndex = on ? -1 : 0;
      if (!items[key]) {
        b.disabled = true;
        b.classList.add("m-disabled");
      } else {
        b.setAttribute("data-oi-pick", `${pick}:${key}`);
        b.setAttribute("data-oi-wired", "");
      }
      b.append(el("span", "b-tabs__nav__text", ` ${text} `));
      li.append(b);
      ul.append(li);
    }
    nav.append(ul);
    card.append(nav, ...body(cur));
    display(doc, clean, false);
    add(doc, card, box, "append");
  }
  return cur;
}

export interface MoreItem {
  label: string;
  onPick?: () => void;
  disabledTitle?: string;
  className?: string;
}

export function moreButton(doc: Document, notYet: string, groups: MoreItem[][] = []) {
  const b = elOf(doc)("button", "btn dropdown-toggle m-post-btn m-btn-horizontal-dots has-tooltip") as HTMLButtonElement;
  b.type = "button";
  b.setAttribute("aria-label", "More");
  const rows = groups.filter((g) => g.length);
  if (!rows.length) {
    b.disabled = true;
    b.title = notYet;
  } else {
    b.title = "More";
    b.setAttribute("aria-haspopup", "menu");
    b.setAttribute("data-oi-wired", "");
    b.addEventListener("click", (ev) => {
      ev.preventDefault();
      const picks = new Map<string, () => void>();
      const menu: MenuGroup[] = rows.map((g, gi) => ({
        name: String(gi),
        radio: false,
        options: g.map((it, i) => {
          if (it.onPick) picks.set(`${gi}:${i}`, it.onPick);
          return { value: String(i), label: it.label, className: it.className, disabled: it.onPick ? undefined : it.disabledTitle ?? notYet };
        }),
      }));
      showMenu(doc, b, menu, (g, v) => picks.get(`${g}:${v}`)?.());
    });
  }
  const dots = elOf(doc)("span", "b-dropdown-dots-wrapper");
  dots.append(iconOf(doc, "more"));
  b.append(dots);
  const w = elOf(doc)("div", "b-dropdown-wrapper m-dropdown-v2");
  w.append(b);
  return w;
}

const USER_LISTS: Record<string, [path: string, param: string, title: string, tipsTitle?: string]> = {
  buyers: ["messages/queue/buyers", "queue_id", "Message buyers"],
  streams: ["streams/viewers", "stream_id", "Stream viewers", "Stream tips"],
  stories: ["stories/viewers", "story_id", "Story viewers", "Story tips"],
  "post-buyers": ["posts/buyers", "post_id", "Post Buyers"],
  "post-tips": ["posts/tips", "post_id", "Post tips"],
  "post-likes": ["posts/likes", "post_id", "Post likes"],
  "promo-claims": ["promotions/claims", "promo_id", "Offer claimed"],
  "trial-claims": ["trials/claims", "trial_id", "Offer claimed"],
  campaign: ["campaigns/claimers", "campaign_id", "Tracking Link Subscribers"],
};
export type UserListKind = keyof typeof USER_LISTS;
const USERS_PAGE = 10;

export function usersLink(doc: Document, text: string, kind: UserListKind, id: unknown, tipsOnly = false) {
  const el = elOf(doc)("span", "g-page__link m-click-area g-blue", ` ${text} `);
  el.setAttribute("role", "button");
  el.tabIndex = 0;
  el.setAttribute("data-oi-users", `${kind}:${String(id)}:${tipsOnly ? 1 : 0}`);
  el.setAttribute("data-oi-wired", "");
  return el;
}
export function usersRoute(mark: string, offset = 0): string | null {
  const [kind, id, tips] = mark.split(":");
  const list = USER_LISTS[kind];
  if (!list || !/^\d+$/.test(id ?? "")) return null;
  const q = new URLSearchParams({ [list[1]]: id, limit: String(USERS_PAGE), offset: String(offset) });
  if (kind === "streams" || kind === "stories") q.set("tips_only", tips === "1" ? "1" : "0");
  return `/api/of/v2/${list[0]}?${q}`;
}

type UsersCtx = { accountId?: string | null; img?: (u: string) => string };
const usersCtx = new WeakMap<Document, UsersCtx>();
export const readsCtx = (doc: Document): UsersCtx => usersCtx.get(doc) ?? {};

export function openUsers(doc: Document, mark: string, opener?: Element) {
  if (!usersRoute(mark)) return;
  const [kind, , tips] = mark.split(":");
  const list = USER_LISTS[kind];
  const { accountId, img } = readsCtx(doc);
  const { close } = openModal(doc, "oi-users", (tips === "1" ? list[3] : null) ?? list[2], (body) => {
    const el = elOf(doc);
    const t = el("table", "b-table m-responsive m-default-table");
    const tb = el("tbody");
    t.append(tb);
    body.append(t);
    let read = 0;
    const page = () => {
      const wait = el("div", "empty-message", "Loading…");
      body.append(wait);
      relay
        .get<unknown>(usersRoute(mark, read)!, { accountId })
        .then((res) => {
          const b = res as { list?: unknown; users?: unknown; items?: unknown; hasMore?: unknown } | null;
          const users = (Array.isArray(b?.list) ? b.list : Array.isArray(b?.users) ? b.users : Array.isArray(b?.items) ? b.items : []) as Fan[];
          wait.remove();
          if (!read && !users.length) {
            body.append(el("div", "empty-message", "Nothing found"));
            return;
          }
          read += users.length;
          for (const u of users) {
            const tr = el("tr", "m-responsive__reset-pb");
            tr.append(fanCell(doc, u, img));
            tb.append(tr);
          }
          const more = b?.hasMore === true || (b?.hasMore === undefined && users.length >= USERS_PAGE);
          const IO = doc.defaultView?.IntersectionObserver;
          if (!more || !users.length || !IO || !tb.lastElementChild) return;
          const io = new IO((entries) => {
            if (!entries.some((e) => e.isIntersecting) || !body.isConnected) return;
            io.disconnect();
            page();
          });
          io.observe(tb.lastElementChild);
        })
        .catch((e: unknown) => {
          wait.textContent = `Couldn't load the list: ${errText(e)}`;
        });
    };
    page();
  }, [{ text: "Close", className: "g-btn m-flat m-btn-gaps m-reset-width", onClick: () => close() }], opener);
}

export function bindUserLists(doc: Document, ctx: UsersCtx) {
  const bound = usersCtx.has(doc);
  usersCtx.set(doc, ctx);
  if (bound) return;
  doc.addEventListener("click", (ev) => {
    const link = (ev.target as Element | null)?.closest?.<HTMLElement>("[data-oi-users]");
    if (!link) return;
    ev.preventDefault();
    openUsers(doc, link.getAttribute("data-oi-users")!, link);
  });
}

export function intoRows<T>(doc: Document, body: Element | null | undefined, items: T[], tpl: (item: T) => HTMLElement | null, fill: (el: HTMLElement, item: T) => void) {
  if (!body) return;
  for (const item of items) {
    const t = tpl(item);
    if (!t) continue;
    const el = make(t);
    el.style.removeProperty("display");
    if (!el.getAttribute("style")) el.removeAttribute("style");
    fill(el, item);
    add(doc, el, body, "append");
  }
  if (items.length) for (const r of body.querySelectorAll<HTMLElement>(":scope > tr")) if (r.querySelector(".empty-message")) display(doc, r, false);
}


export function mediaCounts(doc: Document, item: { media?: unknown; hasVoting?: unknown; votingType?: unknown; fundRaising?: unknown }, notLast: boolean) {
  const media = Array.isArray(item.media) ? (item.media as { type?: string }[]) : [];
  const icons: [icon: string, n?: number][] = [];
  for (const [types, icon] of [[["photo"], "media"], [["video", "gif"], "video"], [["audio"], "voice"]] as [string[], string][]) {
    const n = media.filter((m) => types.includes(m?.type ?? "")).length;
    if (n) icons.push([icon, n]);
  }
  if (item.hasVoting) icons.push([item.votingType === 2 ? "quiz" : "poll"]);
  if (item.fundRaising) icons.push(["fundraising"]);
  if (!icons.length) return null;
  const el = elOf(doc);
  const box = el("div", `b-content-inside-thumbs mw-100 d-flex align-items-center${notLast ? " m-exception-not-last" : ""} g-gray-text`);
  for (const [icon, n] of icons) {
    const it = el("span", "b-content-inside-thumbs__item b-dot-item d-flex align-items-start flex-wrap");
    it.append(iconOf(doc, icon, "m-icon-extra-sm g-icon"));
    if (n) it.append(el("span", "b-content-inside-thumbs__count", String(n)));
    box.append(it);
  }
  return box;
}

export interface TopPostItem {
  id?: number | string;
  postedAt?: string;
  rawText?: string | null;
  text?: string | null;
  price?: number | null;
  tipsAmount?: string | number | null;
  commentsCount?: number | null;
  stats?: { purchasedSumm?: number | null; lookCount?: number | null; likeCount?: number | null } | null;
  media?: { files?: { thumb?: { url?: string | null } | null } | null }[] | null;
}
export const amount = (v: unknown) => (typeof v === "number" ? v : typeof v === "string" ? num(v.replace(/[^\d.-]/g, "")) : null);

