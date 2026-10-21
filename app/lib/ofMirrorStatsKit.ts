"use client";

/**
 * The pieces the Statistics tabs share (ofMirrorStats and its per-group modules): OF's double-line chart pair on the
 * captured canvases, its chart series, its summary ("<total> <level>"), its fan cell (Fans, Top fans, Referred) and
 * its empty state. Every change is tracked (ofMirrorStatsDom), so an apply undoes the last.
 */

import { BLUE, GREY, chartLabels, clearChart, drawChart, type ValueKind } from "@/lib/ofMirrorChart";
import { make, plain } from "@/lib/ofMirrorData";
import { add, at, display, elOf, iconOf, isObj, level, num, setClass, setText, track } from "@/lib/ofMirrorStatsDom";
import { usd } from "@/lib/ofMirrorMoney";
import { openModal } from "@/lib/ofMirrorWrites";
import { showMenu, type MenuGroup } from "@/lib/ofMirrorMenu";
import { relay } from "@/lib/relay";
import { avatarOf, type Fan } from "@/lib/ofMirrorAvatar";

/** A chart's points (`{date, count}`, OF's chart lists), else null. */
export const points = (list: unknown): { date?: string; count?: unknown }[] | null => (Array.isArray(list) ? (list as { date?: string; count?: unknown }[]) : null);
/** A line: [its points, its tooltip title, how its values read]. */
export type Line = [list: unknown, title: string, kind: ValueKind];

/** OF's points for a line (DoubleLineChart `J`): a lone point is drawn from 0 at its date. */
const linePoints = (pts: { date?: string; count?: unknown }[]) => (pts.length === 1 ? [{ count: 0, date: pts[0].date }, pts[0]] : pts);

/**
 * Draw `line` on `canvas` (OF's colour per position, its ticks); none when it has no points. `dates`: the pair's main
 * line's points, whose labels both lines share (OF's DoubleLineChart labels both from its main series).
 */
export function drawLine(doc: Document, c: HTMLCanvasElement | null | undefined, [list, title, kind]: Line, color: string, ticks: number, xLabels: boolean, tz: string | null, dates?: { date?: string }[]) {
  const raw = points(list);
  if (!c || !raw) return false;
  const pts = linePoints(raw);
  drawChart(c, { labels: chartLabels((dates ?? pts).map((x) => x.date), tz), series: { title, values: pts.map((x) => num(x.count) ?? 0), color, kind }, ticks, xLabels });
  track(doc, () => clearChart(c));
  return true;
}
/**
 * OF's DoubleLineChart under `root`: `main` on the upper canvas in blue, `aside` under it in grey with the dates, both on
 * the main's dates (a hover reads each line's point at the same index, as OF's tooltip does).
 */
export function drawPair(doc: Document, root: ParentNode | null | undefined, main: Line, aside: Line | null, tz: string | null) {
  if (!root) return;
  const mainPts = points(main[0]);
  drawLine(doc, root.querySelector<HTMLCanvasElement>("canvas.b-chart__double-line__main"), main, BLUE, 3, !aside, tz);
  if (aside) drawLine(doc, root.querySelector<HTMLCanvasElement>("canvas.b-chart__double-line__aside"), aside, GREY, 2, true, tz, mainPts ? linePoints(mainPts) : undefined);
}

/** OF's series (`{chart, total, delta}`, `gross` for a money one). */
export interface Series {
  chart: unknown[] | null;
  total: number | null;
  delta: number | null;
  gross?: number | null;
}
/** `body[key]` as a series (`{chart, total, delta}`, OF's reply per series); none: null. */
export function seriesOf(body: unknown, key: string): Series | null {
  const s = at(body, key);
  if (!isObj(s)) return null;
  const chart = points(s.chart);
  if (!chart && num(s.total) === null) return null;
  return { chart, total: num(s.total), delta: num(s.delta), gross: num(s.gross) };
}

/**
 * An earnings chart from `/earnings/chart` for OF's tab key `key` (total, subscribes, tips_chat, chat_messages, …): OF's
 * reply is keyed by it (`{chartAmount, chartCount, total, gross, delta}`; OF answers its `messages_*` filter as
 * `chat_messages`, statistics-earnings.js). Today's Relay answers `[]`: null.
 */
export function earningsSeries(body: unknown, key: string): { amount: unknown[] | null; count: unknown[] | null; total: number | null; gross: number | null; delta: number | null } | null {
  const own = at(body, key);
  if (!isObj(own)) return null;
  const amount = points(own.chartAmount);
  if (!amount && num(own.total) === null) return null;
  return { amount, count: points(own.chartCount), total: num(own.total), gross: num(own.gross), delta: num(own.delta) };
}

/**
 * OF's chart box (the generator's `data-oi-chartbox="<key>"`: its summary and its double-line chart, hidden): shown with
 * the series' total (money, or a count), its change and the pair drawn.
 */
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

/**
 * OF's fan cell (Fans, Top fans, Referred: avatar, name, @username), as captured on Fans › Subscriptions. OF links the
 * name to the fan's page, which the mirror does not have: the name alone.
 */
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

/**
 * The page's empty state (the generator's `data-oi-empty`) and its table: with rows, the table shows and the empty state
 * goes; none (and none to come), OF's own text; otherwise (still reading) as the generator drew it.
 */
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

/** A Top card's reply keyed by its tabs (`{purchases: item|null, …}`, as OF answers even for one tab). */
export function topItems(body: unknown, tabs: string[]): Record<string, Record<string, unknown> | null> | null {
  if (!isObj(body)) return null;
  return Object.fromEntries(tabs.map((t) => [t, isObj(body[t]) ? (body[t] as Record<string, unknown>) : null]));
}

/**
 * OF's Top card (TopPost, TopMassMessage, TopStream, TopStory, TopFan): wherever the generator drew the clean state titled
 * `title`, its section title, its tabs (a tab with nothing disabled, as OF's; each picks `<pick>:<key>` in place) and
 * `body` for the picked tab. Nothing for any tab: OF's own empty text (the clean state's data-oi-empty).
 */
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
        b.disabled = true; // OF's: nothing for that tab
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

/** A More menu row: its text (texts_en.json), what a pick does (none: disabled with `notYet`, or `disabledTitle` where another
 *  Inflowwww page does it), OF's row class. */
export interface MoreItem {
  label: string;
  onPick?: () => void;
  disabledTitle?: string;
  className?: string;
}

/**
 * OF's More button (the card's dots, DropdownWrapper "More"), opening its menu (`groups`, OF's dividers between them) in
 * OF's dropdown markup: a row OF's own action works in place, the rest are disabled with `notYet`. No rows: the button
 * is disabled with `notYet`.
 */
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

/** The user lists a count opens (OF's UserList modal, module 905016), by kind: [the Relay path and its id param, its titles]. */
const USER_LISTS: Record<string, [path: string, param: string, title: string, tipsTitle?: string]> = {
  buyers: ["messages/queue/buyers", "queue_id", "Message buyers"],
  streams: ["streams/viewers", "stream_id", "Stream viewers", "Stream tips"],
  stories: ["stories/viewers", "story_id", "Story viewers", "Story tips"],
  // The phase-1 Relay's (omf-statistics-relay-2): shown only when useOfStats' second probe finds it.
  "post-buyers": ["posts/buyers", "post_id", "Post Buyers"],
  "post-tips": ["posts/tips", "post_id", "Post tips"],
  "post-likes": ["posts/likes", "post_id", "Post likes"],
  "promo-claims": ["promotions/claims", "promo_id", "Offer claimed"],
  "trial-claims": ["trials/claims", "trial_id", "Offer claimed"],
  campaign: ["campaigns/claimers", "campaign_id", "Tracking Link Subscribers"],
};
export type UserListKind = keyof typeof USER_LISTS;
/** OF's user list page (its modal reads 10 at a time as the last row scrolls into view). */
const USERS_PAGE = 10;

/** A count OF links to its list (a stream's or story's viewers or tippers, a buyer list, an offer's claims): `data-oi-users`. */
export function usersLink(doc: Document, text: string, kind: UserListKind, id: unknown, tipsOnly = false) {
  const el = elOf(doc)("span", "g-page__link m-click-area g-blue", ` ${text} `);
  el.setAttribute("role", "button");
  el.tabIndex = 0;
  el.setAttribute("data-oi-users", `${kind}:${String(id)}:${tipsOnly ? 1 : 0}`);
  el.setAttribute("data-oi-wired", "");
  return el;
}
/** The Relay route of a `data-oi-users` list's page at `offset`. */
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
/** The account and image proxy the page's Relay reads use (bindUserLists keeps them per page). */
export const readsCtx = (doc: Document): UsersCtx => usersCtx.get(doc) ?? {};

/**
 * Open OF's user list (its modal: the fans with avatar, name and @username, then Close) for the `data-oi-users` mark
 * `mark`, read from the Relay page by page as its last row scrolls into view (OF's infinite loading); none: "Nothing
 * found"; an error: the Relay's.
 */
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
          // OF's: more while it says so (no flag: a full page may have more).
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
          wait.textContent = `Couldn't load the list: ${e instanceof Error ? e.message : String(e)}`;
        });
    };
    page();
  }, [{ text: "Close", className: "g-btn m-flat m-btn-gaps m-reset-width", onClick: () => close() }], opener);
}

/** A `data-oi-users` count opens its user list (openUsers). Bound once per page. */
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

/** A table's rows: a copy of `tpl(item)` per item, filled by `fill`, after the templates; OF's empty row hidden while rows show. */
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


/**
 * OF's media-count icons (QueuePostItem, notifications chunk module 785090, with is-hide-text-icon): photos (icon-media),
 * videos and GIFs (icon-video), audio (icon-voice), each with its count, then a poll or quiz and a fundraiser; none: null.
 * Markup as Engagement › Messages' captured row.
 */
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

/** A post OF's top post routes answer (`/users/me/stats/top/post`: one per metric, null when none). */
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
/** "$0" / "$1,234.50" / 12: OF's tipsAmount as a number. */
export const amount = (v: unknown) => (typeof v === "number" ? v : typeof v === "string" ? num(v.replace(/[^\d.-]/g, "")) : null);

