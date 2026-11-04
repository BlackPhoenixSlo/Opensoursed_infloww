"use client";

/** The queue and Home's Scheduled events widget: the calendar, the agenda, the saved-for-later cards. */

import { localIso, NOT_YET, parseDate } from "@/lib/ofMirrorWrites";
import { clock, dayOf, dropClass, fill, make, plain, stamp, track, valid } from "@/lib/ofMirrorDom";
import { isSavedForLater, QUEUE, queueActions, SCHEDULES, wallClock, type Month, type QueueItem, type QueueKind } from "@/lib/ofMirrorFeedsShared";

/** OF's "more" icon (its sprite symbol: the queue pages' cut-down sprite lacks it). */
const SVG = "http://www.w3.org/2000/svg";
const MORE_ICON = "M6 10a2 2 0 1 0 2 2 2 2 0 0 0-2-2zm12 0a2 2 0 1 0 2 2 2 2 0 0 0-2-2zm-6 0a2 2 0 1 0 2 2 2 2 0 0 0-2-2z";

/** Home's Scheduled events widget reads the next 30 days' queue, by the queue pages' /schedules route. */
export const upcoming = (now: Date): Month => {
  const end = new Date(now.getFullYear(), now.getMonth(), now.getDate() + 30);
  return { start: localIso(now).slice(0, 10), end: localIso(end).slice(0, 10) };
};
export const eventsRoute = (now: Date) => SCHEDULES.route(upcoming(now))!;
const EVENT_KIND: Record<string, string> = { post: "Post", chat: "Message", stream: "Stream" };

/**
 * Home's Scheduled events widget: the three soonest items still ahead of `now`, in place of "You have no scheduled
 * events." (kept when there is none), each its date and time, then its kind and text (or "Media"), as plain rows.
 */
export function applyEvents(doc: Document, items: QueueItem[], now: Date) {
  const empty = doc.querySelector<HTMLElement>(".b-widget .b-widget__body > .empty-message");
  const rows = items
    .map((i) => ({ at: valid(SCHEDULES.at(i)), kind: EVENT_KIND[i.type ?? ""], body: i.entity ?? i }))
    .filter((r): r is typeof r & { at: Date } => !!r.at && r.at.getTime() >= now.getTime())
    .sort((a, b) => a.at.getTime() - b.at.getTime())
    .slice(0, 3);
  if (!empty || !rows.length) return;
  const list = doc.createElement("div");
  list.dataset.oiData = "";
  list.className = "b-widget__events";
  list.style.cssText = "padding:8px 0";
  for (const r of rows) {
    const row = doc.createElement("div");
    row.style.cssText = "display:flex;gap:8px;padding:4px 0;font-size:14px;line-height:20px;min-width:0";
    const when = doc.createElement("span");
    when.className = "g-gray-text";
    when.style.whiteSpace = "nowrap";
    when.textContent = stamp(r.at);
    const what = doc.createElement("span");
    what.className = "g-text-ellipsis";
    const text = plain(r.body.text) || ((r.body.mediaCount ?? 0) > 0 ? "Media" : "");
    what.textContent = [r.kind, text].filter(Boolean).join(" · ");
    row.append(when, what);
    list.appendChild(row);
  }
  fill(doc, [empty], []);
  empty.after(list);
  // OF drops the widget's "+" (Add to queue) once it lists events.
  const plus = empty.parentElement!.querySelector<HTMLElement>(":scope > .b-new-event-btn");
  const style = plus?.getAttribute("style") ?? null;
  plus?.style.setProperty("display", "none");
  track(doc, () => {
    list.remove();
    if (!plus) return;
    if (style === null) plus.removeAttribute("style");
    else plus.setAttribute("style", style);
  });
}


/** The item types the calendar's event bars count (OF's /schedules/counters keys). */
const DAY_TYPES = ["post", "chat", "stream"];

/**
 * Items per local day of `zone` and type, in OF's /schedules/counters shape ({"2026-11-26": {"post": 1}}; a
 * saved-for-later post or message counts as `saved_for_later_post` / `saved_for_later_chat`, as OF's counters do): what a
 * month page's calendar marks. Items with no time or another type are not counted.
 */
export function dayCounts(items: QueueItem[], zone?: string): Record<string, Record<string, number>> {
  const out: Record<string, Record<string, number>> = {};
  for (const i of items) {
    const at = valid(i.publishDateTime || i.createdDateTime);
    if (!at || !i.type || !DAY_TYPES.includes(i.type)) continue;
    const day = (out[localIso(wallClock(at, zone)).slice(0, 10)] ??= {});
    const key = isSavedForLater(i) ? `saved_for_later_${i.type}` : i.type;
    day[key] = (day[key] ?? 0) + 1;
  }
  return out;
}

/** One calendar event bar: OF's type class, its name (the count) and, for a half-tinted bar, the scheduled part in %. */
export interface DayBar {
  type: string;
  name: string;
  value?: string;
}

/**
 * A day's counters as OF's queue store turns them into calendar events (app.js schedule module `R`): a day with both
 * scheduled and saved-for-later posts gets one "posts" bar named by their sum, its `value` the scheduled share in percent
 * (OF's stylesheet paints the bar half-tinted and the `v-event-summary__level` part of that width full); the same for
 * "chats"; any other count is its own bar ("post", "chat", "stream", or "sfl-post" / "sfl-chat" for saved for later
 * alone), named by the count.
 */
export function dayBars(counts: Record<string, number>): DayBar[] {
  const left = { ...counts };
  const bars: DayBar[] = [];
  for (const [type, merged] of [["post", "posts"], ["chat", "chats"]] as const) {
    const n = left[type];
    const later = left[`saved_for_later_${type}`];
    if (!n || !later) continue;
    const sum = n + later;
    bars.push({ type: merged, name: String(sum), value: String(Math.round((n / sum) * 100)) });
    delete left[type];
    delete left[`saved_for_later_${type}`];
  }
  for (const [key, n] of Object.entries(left)) if (n) bars.push({ type: key.replace("saved_for_later_", "sfl-"), name: String(n) });
  return bars;
}

/**
 * Mark a month page's day cells with OF's calendar event bars (`v-event` and the bar's type, painted by its queue
 * stylesheet: `.v-event.post|chat|stream|posts|chats|sfl-post|sfl-chat`), each a `v-event-summary` with the bar's name
 * and, for a half-tinted bar, a `v-event-summary__level` of `value`% width: the queue chunk's v-calendar event slot.
 */
function markDays(doc: Document, counts: Record<string, Record<string, number>>) {
  for (const [day, types] of Object.entries(counts)) {
    const cell = doc.querySelector(`.v-calendar-monthly .b-month-day-cell__value[at-attr='date:${day}']`)?.closest(".v-calendar-weekly__day");
    if (!cell) continue;
    for (const { type, name, value } of dayBars(types)) {
      const bar = doc.createElement("div");
      // white--text: Vuetify's event colour class, as OF's calendar renders its events.
      bar.className = `v-event v-event-start v-event-end ${type} white--text`;
      bar.dataset.oiData = "";
      bar.dataset.date = day;
      const summary = bar.appendChild(doc.createElement("div"));
      summary.className = "v-event-summary pl-1";
      summary.textContent = name;
      if (value) {
        const level = summary.appendChild(doc.createElement("div"));
        level.className = "v-event-summary__level";
        level.style.width = `${value}%`;
      }
      cell.appendChild(bar);
      track(doc, () => bar.remove());
    }
  }
}

/** The month the queue's calendar shows ("October 2026" in its header): its first and last day, yyyy-mm-dd. */
export function queueMonth(doc: Document): Month | null {
  for (const el of doc.querySelectorAll(".b-queue-header__date")) {
    const m = /^([a-z]+) (\d{4})$/i.exec(el.textContent?.trim() ?? "");
    const first = m && parseDate(`${m[1]} 1, ${m[2]}`);
    if (first) return { start: localIso(new Date(first[0], first[1] - 1, 1)).slice(0, 10), end: localIso(new Date(first[0], first[1], 0)).slice(0, 10) };
  }
  return null;
}

/** The event ofMirrorQueue sends on the frame's document when the queue's month, day or tabs change in place. */
export const QUEUE_CHANGE = "oi-queue-change";

/** The month pages' tabs (OF's multiple-choice type filter: none selected shows every type), by their text -> the item type. */
export const QUEUE_TABS: Record<string, string> = { Posts: "post", Messages: "chat", Streams: "stream" };

/** The item types of the queue tabs selected (OF's `m-current`); none: every type. */
export function queueTypes(doc: Document): string[] {
  return [...doc.querySelectorAll(".g-page__subheader .b-tabs__nav__link.m-current")].flatMap((t) => QUEUE_TABS[t.textContent?.trim() ?? ""] ?? []);
}

/** The day the queue's right column shows ("October 12, 2026" in its header), yyyy-mm-dd. */
export function queueDay(doc: Document): string | null {
  const d = parseDate(doc.querySelector(".l-wrapper__sidebar .b-queue-header__date")?.textContent ?? "");
  return d && localIso(new Date(d[0], d[1] - 1, d[2])).slice(0, 10);
}

/**
 * A queue page's items, one OF agenda section per day (soonest first; undated items, as saved for later, in one
 * section with no date), each its time, its text (a stream's description, or "Media") and its source's colour mark,
 * the days and times those of `zone` (wallClock). OF captured no item, so they are built from its agenda classes in
 * the page's agenda scope. A post or message with an id (queueActions) also gets OF's round "More" button and its
 * actions in data-oi-queue-* (ofMirrorQueue opens the menu). The list view fills its own agenda block, the
 * saved-for-later pages a copy of the borrowed one in place of their empty state, only when there is an item. A month
 * page keeps the shown month's items of the selected tabs: its calendar marks their days with OF's event bars and
 * counts (markDays), and the right column lists the shown day's in place of its "no scheduled events for this day"
 * (OF's day view); the borrowed block only lends its agenda scope there, as OF lists nothing under its calendar.
 */
export function applyQueue(doc: Document, page: string, items: QueueItem[], tpl: Element | undefined, zone?: string) {
  const src = QUEUE[page];
  const month = src.month ? queueMonth(doc) : null;
  const types = src.month ? queueTypes(doc) : [];
  const dayOfRow = (at: Date | null) => (at ? localIso(at).slice(0, 10) : "");
  const rows = items
    .filter((i) => !types.length || types.includes(i.type ?? ""))
    .map((i) => {
      const at = valid(src.at?.(i));
      return { item: i, at: at && wallClock(at, zone), mark: src.mark(i), body: i.entity ?? i, actions: queueActions(page, i) };
    })
    .filter((r) => !src.month || (month && r.at && dayOfRow(r.at) >= month.start && dayOfRow(r.at) <= month.end))
    .sort((a, b) => (a.at?.getTime() ?? Infinity) - (b.at?.getTime() ?? Infinity));
  if (!rows.length) return;
  const calendar = doc.querySelector(".v-calendar-monthly");
  if (calendar) markDays(doc, dayCounts(rows.map((r) => r.item), zone));
  // The saved-for-later pages: OF's own cards (ScheduleEventDayView), not agenda rows.
  const sflEmpty = !src.month ? doc.querySelector<HTMLElement>(".saved-for-later > .empty-message") : null;
  if (sflEmpty && src.kind) {
    for (let el = sflEmpty.closest(".m-empty-content"); el; el = sflEmpty.closest(".m-empty-content")) dropClass(doc, el, "m-empty-content");
    fill(doc, [sflEmpty], items.map((i) => sflCard(doc, page, i, src.kind!, zone)));
    return;
  }
  let agenda = doc.querySelector<HTMLElement>(".b-agenda.m-main-block");
  if (!agenda) {
    const empty = doc.querySelector<HTMLElement>(".saved-for-later > .empty-message");
    if (!tpl || !(calendar || empty)) return;
    const copy = make(doc.importNode(tpl, true));
    agenda = copy.querySelector<HTMLElement>(".b-agenda")!;
    if (!calendar) fill(doc, [empty!], [copy]);
  }
  const scope = [...agenda.attributes].filter((a) => a.name.startsWith("data-v-"));
  const built = (tag: string, cls: string, parent?: Element) => {
    const el = doc.createElement(tag);
    for (const a of scope) el.setAttribute(a.name, a.value);
    el.className = cls;
    parent?.appendChild(el);
    return el;
  };
  const addItem = (r: (typeof rows)[number], parent: Element) => {
    const item = built("a", "b-agenda__area-events__item d-flex", parent);
    if (r.mark) item.classList.add(r.mark);
    const content = built("div", "b-agenda__area-events__item-content", item);
    // OF's agenda time; "h:mm* a" for an item saved for later (app.js schedule module `D`).
    built("div", "b-agenda__area-events__item-details", content).textContent = r.at ? (isSavedForLater(r.item) ? clock(r.at).replace(/\s/, "* ") : clock(r.at)) : "";
    built("div", "b-agenda__area-events__item-inward", content).textContent = plain(r.body.text) || plain(r.body.description) || ((r.body.mediaCount ?? 0) > 0 ? "Media" : "");
    if (r.actions) {
      const a = r.actions;
      Object.assign(item.dataset, { oiQueueKind: a.kind, oiQueueTarget: a.target, oiQueueSchedule: a.schedule, oiQueueReady: String(a.ready), oiQueuePinned: String(a.pinned) });
      // OF's ScheduleEventDropdown activator (round dots); data-oi-wired: ofMirrorQueue owns its click, not the read-only fallback.
      const more = built("button", "btn dropdown-toggle m-post-btn m-btn-round-dots", built("div", "b-post__tools__more b-dropdown-wrapper m-dropdown-v2", item));
      const attrs = { type: "button", "aria-label": "More", "aria-haspopup": "true", "aria-expanded": "false", "at-attr": "more_menu", "data-oi-wired": "" };
      for (const [k, v] of Object.entries(attrs)) more.setAttribute(k, v);
      const svg = more.appendChild(doc.createElementNS(SVG, "svg"));
      for (const [k, v] of Object.entries({ class: "g-icon", "data-icon-name": "icon-more", viewBox: "0 0 24 24", "aria-hidden": "true" })) svg.setAttribute(k, v);
      svg.appendChild(doc.createElementNS(SVG, "path")).setAttribute("d", MORE_ICON);
    }
  };
  if (!calendar) {
    // OF's empty-page layout centres the block.
    for (let el = agenda.closest(".m-empty-content"); el; el = agenda.closest(".m-empty-content")) dropClass(doc, el, "m-empty-content");
    const sections: HTMLElement[] = [];
    let day: string | undefined;
    for (const r of rows) {
      const key = r.at?.toDateString() ?? "";
      if (key !== day) {
        day = key;
        const section = built("div", "b-agenda__section d-flex");
        section.dataset.oiData = "";
        built("div", "b-agenda__section-date", section).textContent = r.at ? dayOf(r.at) : "";
        built("div", "b-agenda__area-events", section);
        sections.push(section);
      }
      addItem(r, sections[sections.length - 1].lastElementChild!);
    }
    const empty = agenda.querySelector<HTMLElement>(":scope > .empty-message");
    fill(doc, empty ? [empty] : [], sections, [agenda]);
  }
  // The right column: the day it shows.
  const side = src.month ? doc.querySelector<HTMLElement>(".l-wrapper__sidebar") : null;
  const sideEmpty = side?.querySelector<HTMLElement>(":scope > .empty-message");
  const shown = src.month ? queueDay(doc) : null;
  const ofDay = rows.filter((r) => shown && dayOfRow(r.at) === shown);
  if (!side || !sideEmpty || !ofDay.length) return;
  const list = built("div", "b-agenda");
  list.dataset.oiData = "";
  for (const r of ofDay) addItem(r, list);
  fill(doc, [sideEmpty], [list], [side]);
  dropClass(doc, side, "m-empty-section");
}

/** OF's card scopes (ScheduleEventDayView and its queue rows), linked on the queue pages by the generator. */
const CARD = "data-v-48bf68d0";
const CARD_ROW = "data-v-48f703ce";
const SVG_NS = "http://www.w3.org/2000/svg";

/**
 * One saved-for-later item as OF's saved-for-later pages show it (ScheduleEventDayView, captured live 2026-10-17): its
 * kind's icon, the day it was saved ("Oct 17, 2026"), "Later" and, for a message, who it goes to ("to <username>"), the
 * More button, the time with OF's star ("7:26* pm"), a post's disabled "Add labels" and the text. Its ids go on the card
 * (data-oi-queue-*) for ofMirrorQueue's row menu.
 */
export function sflCard(doc: Document, page: string, i: QueueItem, kind: QueueKind, zone?: string): HTMLElement {
  const body = i.entity ?? i;
  const at = valid(i.publishDateTime || i.createdDateTime);
  const wall = at && wallClock(at, zone);
  const el = (tag: string, cls: string, scope: string, parent?: Element) => {
    const e = doc.createElement(tag);
    e.setAttribute(scope, "");
    e.className = cls;
    parent?.appendChild(e);
    return e;
  };
  const icon = (parent: Element, name: string, cls = "g-icon") => {
    const svg = parent.appendChild(doc.createElementNS(SVG_NS, "svg"));
    for (const [k, v] of Object.entries({ class: cls, "data-icon-name": name, "aria-hidden": "true" })) svg.setAttribute(k, v);
    svg.appendChild(doc.createElementNS(SVG_NS, "use")).setAttribute("href", `#${name}`);
    return svg;
  };
  const post = kind === "post";
  const card = el("div", `b-post is-not-post-page m-queue-post m-appearance-message m-save-later ${post ? "sfl-post" : "sfl-message"}`, CARD);
  card.dataset.oiData = "";
  const head = el("div", "b-post__header", CARD, card);
  icon(el("span", "b-post__queue-icon", CARD, head), post ? "icon-saved-for-later-posts" : "icon-saved-for-later-message", `${post ? "m-post-color" : "m-chat-color"} g-icon`);
  const row1 = el("div", "b-post__queue-row", CARD_ROW, head);
  row1.setAttribute(CARD, "");
  el("div", "b-post__queue-cell m-date-case", CARD_ROW, row1).textContent = wall ? ` ${wall.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })} ` : "";
  const cell = el("div", "b-post__queue-cell", CARD_ROW, row1);
  el("span", "b-queue-post-info m-mr-5", CARD_ROW, cell).textContent = " Later ";
  if (!post && body.sentRulesExtra) el("span", "b-post__queue-cell__item g-text-ellipsis", CARD_ROW, cell).textContent = ` to ${body.sentRulesExtra} `;
  const a = queueActions(page, i);
  if (a) {
    Object.assign(card.dataset, { oiQueueKind: a.kind, oiQueueTarget: a.target, oiQueueSchedule: a.schedule, oiQueueReady: String(a.ready), oiQueuePinned: String(a.pinned) });
    const more = el("div", "b-post__tools__more", CARD_ROW, cell);
    const wrap = more.appendChild(doc.createElement("div"));
    wrap.className = "b-dropdown-wrapper m-dropdown-v2";
    const btn = wrap.appendChild(doc.createElement("button"));
    for (const [k, v] of Object.entries({ type: "button", "aria-haspopup": "true", "aria-expanded": "false", "aria-label": "More", "at-attr": "more_menu", "data-oi-wired": "" })) btn.setAttribute(k, v);
    btn.className = "btn dropdown-toggle m-post-btn m-btn-horizontal-dots m-with-hover-highlight";
    icon(btn, "icon-more");
  }
  const row2 = el("div", "b-post__queue-row", CARD_ROW, head);
  row2.setAttribute(CARD, "");
  el("div", "b-post__queue-cell m-time-passed", CARD_ROW, row2).textContent = wall ? ` ${clock(wall).replace(/\s/, "* ")} ` : "";
  if (post) {
    const labels = el("div", "b-post__labels-controls", CARD, card);
    const list = labels.appendChild(doc.createElement("div"));
    list.setAttribute("data-v-74f8aaf2", "");
    list.className = "b-list-titles m-right-together b-post__queue_labels g-gray-text";
    const add = list.appendChild(doc.createElement("button"));
    add.type = "button";
    add.disabled = true;
    add.title = NOT_YET;
    add.className = "g-btn m-flat m-link m-default-font-weight m-no-uppercase m-reset-width b-dot-item";
    add.innerHTML = '<span class="b-list-titles__item__text"> Add labels </span>';
  }
  const content = el("div", `b-post__content ${post ? "m-type-post" : "m-type-message"}`, CARD, card);
  const text = el("div", "b-post__text m-break-word", CARD, content);
  const inner = el("div", "b-post__text-el m-possible-markdown", CARD, text);
  const truncated = inner.appendChild(doc.createElement("div"));
  truncated.className = "g-truncated-text m-break-word";
  truncated.appendChild(doc.createElement("div")).textContent = plain(body.text) || ((body.mediaCount ?? 0) > 0 ? "Media" : "");
  return card;
}
