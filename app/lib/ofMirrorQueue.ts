"use client";

/**
 * The queue rows' "More" menu (OF's ScheduleEventDropdown, queue chunk `queue-page`, build 202610091632). applyQueue
 * gives each real post or message row the round "More" button and its ids (data-oi-queue-*); a click opens OF's
 * dropdown list beside it:
 * - a post: Pin to / Unpin from your profile (POST /posts/{id}/pin, OF's toggle), Edit post, Post now, Delete post;
 * - a message: Edit message, Message now, Delete message.
 * The saved-for-later pages' rows have the same menu (OF's SavedForLater page uses the same ScheduleEventDropdown).
 * "Post now" / "Message now" sends PUT /schedules/{scheduleId}/publish (the schedule item's own id), greyed out while
 * OF says the media is not ready or the row has no schedule id. Delete asks first (OF's confirm) and then sends
 * DELETE /posts/{id} or DELETE /messages/queue/{id}. Edit opens the existing composer filled from the item, as OF's
 * (PostsEdit, and ChatsSend with ?scheduleMessageId= or ?SFLMessageId=): Edit post reads GET /posts/{id} onto the Post
 * draft (postEditDraft) and opens New post, Edit message reads GET /messages/queue/{id} onto the Mass draft
 * (messageEditDraft) and opens New message; their Post / Send then save the same item (PUT /api/of/v2/queue/posts/{id},
 * PUT /api/of/v2/messages/queue/{id}), and a new date there is
 * OF's reschedule.
 * A success refreshes the page's rows (useOfData refetches); a failure shows the relay error under the row.
 * With no single model selected every action sends nothing and says "Select a model to save changes".
 *
 * "Add to queue" (the queue pages' "+", the saved-for-later pages' "+" and the Scheduled events widget's "+" on New post
 * and Go live) opens OF's NEW_SCHEDULED_EVENT modal (chunk 24564, module 536492): "Add to queue", two tabs (Scheduled,
 * Save for later; a saved-for-later page opens on the second), the date and time (the shown day at the Agency zone's time
 * ten minutes from now, OF's default) and one button per type, which opens that type's composer on that moment
 * (createHref) or saving for later (laterHref); Cancel closes it.
 *
 * bindCalendar makes the month pages' own controls act in place, as OF's queue page does (its queue chunk): the month
 * arrows (back greyed out on the current month), a day cell of today or later, the right column's day arrows (back
 * greyed out on today) and the Posts / Messages / Streams tabs (several at once; none shows every type). It draws the
 * calendar weeks, the header's month, the right column's day and the view switch's ?date= link, and sends QUEUE_CHANGE
 * so useOfData shows that month's (and day's) items of those tabs, asking the Relay for a new month. Today (the month
 * and day it opens on, what is past) is the Agency's time zone's (the top bar's), not the browser's.
 */

import { useEffect, type RefObject } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import { useScope } from "@/contexts/ScopeContext";
import { relay, type OFMedia } from "@/lib/relay";
import { proxyImage } from "@/lib/mediaUrl";
import { stillUrl } from "@/lib/ofMedia";
import { plain, valid } from "@/lib/ofMirrorData";
import { fromWallClock, QUEUE, QUEUE_CHANGE, queueDay, useAgencyZone, wallClock, type QueueActions, type QueueKind } from "@/lib/ofMirrorFeeds";
import { dateTimeFields, localIso, message, minuteAhead, modalButton, note, NOT_YET, openModal, parseDate, SELECT_MODEL, TOO_SOON } from "@/lib/ofMirrorWrites";
import { loadDraft, saveDraft, type PostDraft } from "@/lib/ofMirrorPost";
import { loadMassDraft, massDraftKey, type MassDraft } from "@/lib/ofMirrorChat";

export { fromWallClock } from "@/lib/ofMirrorFeeds";

export interface QueueHandlers {
  publish(schedule: string): Promise<unknown>;
  remove(kind: QueueKind, target: string): Promise<unknown>;
  pin(target: string): Promise<unknown>;
  confirm(text: string): boolean;
  /** Add to queue > Scheduled > a type: open `kind`'s composer scheduled at `at` (createHref). */
  create(kind: CreateKind, at: Date): void;
  /** Add to queue > Save for later > a type: open `kind`'s composer saving for later (laterHref). */
  later(kind: LaterKind): void;
  /** Edit post / Edit message: load the item, fill its composer's draft and open it. */
  edit(kind: QueueKind, target: string): Promise<unknown>;
}

type Action = "pin" | "edit" | "now" | "delete";
/** What Add to queue schedules: a post (New post), a mass message (New message) or a stream (Go live's schedule form). */
export type CreateKind = "post" | "message" | "stream";
/** What Add to queue saves for later (OF's Save for later tab has no stream). */
export type LaterKind = "post" | "message";

const MENU_ID = "oi-queue-menu";
const MODAL_ID = "newScheduleEventModal";
/** A queue row (an agenda item on the month pages, OF's card on the saved-for-later pages) with its ids, and its More button. */
const ROWS = [".b-agenda__area-events__item[data-oi-queue-kind]", ".b-post.m-queue-post[data-oi-queue-kind]"];
const ROW = ROWS.join(", ");
const MORE = "[at-attr='more_menu']";
const ROW_MORE = ROWS.map((r) => `${r} ${MORE}`).join(", ");
/**
 * OF's "Add to queue" buttons: the queue pages' header, list view and right column ones, the saved-for-later pages' two
 * (data-oi-add) and the Scheduled events widget's (the generator marks them all Wired).
 */
const ADD = "[at-attr='add_event_header'], [at-attr='add_event_page'], [at-attr='add_event_sidebar'], [at-attr='add_event_widget'], [data-oi-add]";

/**
 * OF's Add to queue modal (NEW_SCHEDULED_EVENT, chunk 24564): its title, tabs, help lines and the buttons per tab with
 * OF's icons and routes (PostsCreate, ChatsSend, StreamingCreateEditSchedule), the words as the live modal shows them
 * (captured 2026-10-17; OF's CSS sets the title, tabs and buttons in capitals).
 */
export const ADD_TITLE = "Add to queue";
export const ADD_TABS: { key: "scheduled" | "later"; text: string }[] = [
  { key: "scheduled", text: "Scheduled" },
  { key: "later", text: "Save for Later" },
];
export const ADD_HELP = {
  scheduled: "Please choose a date and time for your action to be executed.",
  later: "Once the post or mass message is created, it will go to the end of the Saved for Later queue, and be published automatically, if this feature is turned on.",
};
export const ADD_MENU: { atAttr: string; title: string; kind: CreateKind; icon: string }[] = [
  { atAttr: "add_post", title: "Post", kind: "post", icon: "post2" },
  { atAttr: "add_message", title: "Mass message", kind: "message", icon: "message" },
  { atAttr: "add_stream", title: "Stream", kind: "stream", icon: "live" },
];
export const LATER_MENU: { atAttr: string; title: string; kind: LaterKind; icon: string }[] = [
  { atAttr: "later_post", title: "Post", kind: "post", icon: "saved-for-later-posts" },
  { atAttr: "later_message", title: "Mass message", kind: "message", icon: "saved-for-later-message" },
];

/**
 * OF's menu entries per kind: its at-attr, title and action, the titles as the live menus show them (captured
 * 2026-10-17; "Unpin from your profile page" is OF's other pin key, not seen live). ASSUMPTION: the confirm texts.
 */
export function queueMenu(a: QueueActions): { atAttr: string; title: string; action: Action; disabled?: boolean; tooltip?: string; danger?: boolean }[] {
  const now = !a.ready || !a.schedule;
  if (a.kind === "post")
    return [
      { atAttr: "pin_to_profile", title: a.pinned ? "Unpin from your profile page" : "Pin to your profile page", action: "pin" },
      { atAttr: "edit_post", title: "Edit post", action: "edit" },
      { atAttr: "publish_now", title: "Publish now", action: "now", disabled: now, tooltip: a.schedule ? undefined : NOT_YET },
      { atAttr: "delete_post", title: "Delete post", action: "delete", danger: true },
    ];
  return [
    { atAttr: "edit_message", title: "Edit message", action: "edit" },
    { atAttr: "message_now", title: "Send message right now", action: "now", disabled: now, tooltip: a.schedule ? undefined : NOT_YET },
    { atAttr: "delete_message", title: "Delete message", action: "delete", danger: true },
  ];
}

export const CONFIRM_DELETE: Record<QueueKind, string> = {
  post: "Are you sure you want to delete this scheduled post?",
  chat: "Are you sure you want to delete this scheduled message?",
};

/** Post now / Message now sends at once (a queued mass or paid message goes out to fans), so it asks first. */
export const CONFIRM_PUBLISH: Record<QueueKind, string> = {
  post: "Publish this post now?",
  chat: "Send this message now?",
};

/** A row's actions, as applyQueue stored them. */
export function actionsOf(row: HTMLElement): QueueActions {
  const d = row.dataset;
  return { kind: d.oiQueueKind as QueueKind, target: d.oiQueueTarget ?? "", schedule: d.oiQueueSchedule ?? "", ready: d.oiQueueReady !== "false", pinned: d.oiQueuePinned === "true" };
}

/**
 * Open OF's Add to queue modal in `doc` (on its Save for later tab with `later`), its date and time `wall` (a wall clock
 * of `zone`); a type's button hands `handlers` the picked moment (at least a minute ahead of `now`, else the note) or
 * the type to save for later. Returns the modal.
 */
export function openAddModal(doc: Document, handlers: QueueHandlers, opts: { later: boolean; wall: Date; zone?: string; now: () => Date; opener?: Element }): HTMLElement {
  let tab: "scheduled" | "later" = opts.later ? "later" : "scheduled";
  let fields = dateTimeFields(doc, opts.wall, wallClock(opts.now(), opts.zone));
  const { modal, close } = openModal(doc, MODAL_ID, ADD_TITLE, () => {}, [{ text: "Cancel", className: "g-btn m-flat m-btn-gaps m-reset-width", onClick: () => close() }], opts.opener);
  const body = modal.querySelector<HTMLElement>(".modal-body")!;
  const item = "g-btn m-rounded m-border m-block m-lg m-icon-absolute";
  const draw = () => {
    const nav = doc.createElement("div");
    nav.className = "b-tabs__nav m-nv m-tabs-default m-reset-sides-gaps m-size-md m-flex-width";
    const list = nav.appendChild(doc.createElement("ul"));
    list.className = "b-tabs__nav__list";
    list.style.cssText = "display:flex;padding:0;margin:0 0 12px;list-style:none";
    for (const t of ADD_TABS) {
      const li = list.appendChild(doc.createElement("li"));
      li.className = "b-tabs__nav__item";
      li.style.flex = "1 1 0";
      li.append(
        modalButton(doc, {
          text: t.text,
          className: `b-tabs__nav__link m-with-rectangle-hover m-tb-sm${t.key === tab ? " m-current" : ""}`,
          attrs: { "data-oi-tab": t.key },
          onClick: () => {
            tab = t.key;
            draw();
          },
        }),
      );
    }
    const help = doc.createElement("p");
    help.className = `g-input__help m-text m-reset-gaps ${tab === "scheduled" ? "m-mb-12" : "m-mb-24"}`;
    help.textContent = ` ${ADD_HELP[tab]} `;
    const parts: Node[] = [nav, help];
    if (tab === "scheduled") {
      const keep = fields.read();
      fields = dateTimeFields(doc, keep ?? opts.wall, wallClock(opts.now(), opts.zone));
      parts.push(fields.row);
      ADD_MENU.forEach((e, i) =>
        parts.push(
          modalButton(doc, {
            text: e.title,
            icon: e.icon,
            className: `${item}${i < ADD_MENU.length - 1 ? " m-mb-10" : ""}`,
            attrs: { "at-attr": e.atAttr },
            onClick: () => {
              const wall = fields.read();
              const at = wall && fromWallClock(wall, opts.zone);
              if (!at || !minuteAhead(at, opts.now())) return note(doc, fields.row, TOO_SOON, true);
              close();
              handlers.create(e.kind, at);
            },
          }),
        ),
      );
    } else
      LATER_MENU.forEach((e, i) =>
        parts.push(
          modalButton(doc, {
            text: e.title,
            icon: e.icon,
            className: `${item}${i < LATER_MENU.length - 1 ? " m-mb-10" : ""}`,
            attrs: { "at-attr": e.atAttr },
            onClick: () => {
              close();
              handlers.later(e.kind);
            },
          }),
        ),
      );
    body.replaceChildren(...parts);
  };
  draw();
  return modal;
}

/**
 * Bind the queue rows' "More" menus and the "Add to queue" buttons in `doc` (handlers null: no single model). The Add
 * to queue modal opens on the shown day (the right column's, else today in `zone`) at `zone`'s time ten minutes from
 * now (createAt). Returns an unbind.
 */
export function bindQueue(doc: Document, handlers: QueueHandlers | null, zone?: string, now: () => Date = () => new Date()): () => void {
  let busy = false;
  // The open menu -> the row it acts on.
  const rowOf = new WeakMap<Element, HTMLElement>();
  const close = () => {
    const menu = doc.getElementById(MENU_ID);
    if (!menu) return;
    menu.remove();
    for (const b of doc.querySelectorAll(ROWS.map((r) => `${r} ${MORE}[aria-expanded='true']`).join(", "))) b.setAttribute("aria-expanded", "false");
  };

  const open = (row: HTMLElement, more: HTMLElement) => {
    close();
    more.setAttribute("aria-expanded", "true");
    const menu = doc.createElement("div");
    menu.id = MENU_ID;
    menu.setAttribute("role", "menu");
    menu.className = "v-menu__content theme--light menuable__content__active m-dropdown-list m-show-dividers pt-0 pb-0";
    const at = more.getBoundingClientRect();
    menu.style.cssText = `position:fixed;min-width:220px;max-width:256px;z-index:8;top:${Math.round(at.bottom)}px;right:${Math.max(0, Math.round((doc.documentElement.clientWidth || at.right) - at.right))}px`;
    const list = menu.appendChild(doc.createElement("div"));
    list.className = "v-list m-dropdown-v-list v-sheet theme--light";
    const entries = queueMenu(actionsOf(row));
    for (const entry of entries) {
      if (entry.danger) {
        const hr = list.appendChild(doc.createElement("hr"));
        hr.setAttribute("role", "separator");
        hr.className = "m-divider-item v-divider theme--light";
      }
      const b = list.appendChild(doc.createElement("button"));
      b.type = "button";
      b.setAttribute("role", "menuitem");
      b.setAttribute("at-attr", entry.atAttr);
      b.setAttribute("data-oi-wired", "");
      b.dataset.oiQueueAction = entry.action;
      b.className = `m-with-rectangle-hover m-tb-sm v-list-item v-list-item--link theme--light${entry.danger ? " m-danger" : ""}${entry.disabled ? " v-list-item--disabled" : ""}`;
      b.disabled = !!entry.disabled;
      if (entry.tooltip) b.title = entry.tooltip;
      b.textContent = ` ${entry.title} `;
    }
    doc.body.appendChild(menu);
    rowOf.set(menu, row);
  };

  /** Send one row action; a failure notes `<fail>: <relay error>` under the row. */
  const run = (row: HTMLElement, send: () => Promise<unknown>, fail: string, done?: string) => {
    busy = true;
    send().then(
      () => {
        busy = false;
        if (done) note(doc, row, done, false, 2000);
      },
      (e) => {
        busy = false;
        note(doc, row, `${fail}: ${message(e)}`, true);
      },
    );
  };

  const act = (row: HTMLElement, action: Action) => {
    const a = actionsOf(row);
    if (!handlers) return note(doc, row, SELECT_MODEL);
    if (busy) return;
    if (action === "edit") return run(row, () => handlers.edit(a.kind, a.target), "Could not open");
    if (action === "pin") return run(row, () => handlers.pin(a.target), "Could not save", "Saved");
    if (action === "now") {
      if (a.schedule && handlers.confirm(CONFIRM_PUBLISH[a.kind])) run(row, () => handlers.publish(a.schedule), "Could not publish");
      return;
    }
    if (handlers.confirm(CONFIRM_DELETE[a.kind])) run(row, () => handlers.remove(a.kind, a.target), "Could not delete");
  };

  /** "+": OF's Add to queue modal, on the right column's day (today on a page with none); Save for later on its pages. */
  const add = (plus: HTMLElement) => {
    if (!handlers) return note(doc, plus, SELECT_MODEL);
    const t = now();
    const at = createAt(queueDay(doc) ?? ymd(wallClock(t, zone)), zone, t);
    openAddModal(doc, handlers, { later: !!doc.querySelector(".saved-for-later"), wall: wallClock(at, zone), zone, now, opener: plus });
  };

  const onClick = (ev: MouseEvent) => {
    const t = ev.target as Element | null;
    if (!t?.closest) return;
    const item = t.closest<HTMLButtonElement>(`#${MENU_ID} button[data-oi-queue-action]`);
    if (item) {
      ev.preventDefault();
      const row = rowOf.get(item.closest(`#${MENU_ID}`)!);
      close();
      if (!row || item.disabled) return;
      act(row, item.dataset.oiQueueAction as Action);
      return;
    }
    const plus = t.closest<HTMLElement>(ADD);
    if (plus) {
      ev.preventDefault();
      close();
      return add(plus);
    }
    const more = t.closest<HTMLElement>(ROW_MORE);
    if (more) {
      ev.preventDefault();
      const wasOpen = more.getAttribute("aria-expanded") === "true";
      close();
      if (!wasOpen) open(more.closest<HTMLElement>(ROW)!, more);
      return;
    }
    if (!t.closest(`#${MENU_ID}`)) close();
  };
  const onKey = (ev: KeyboardEvent) => {
    if (ev.key === "Escape") close();
  };
  // The menu is placed in the viewport: it closes when anything scrolls.
  const onScroll = () => close();

  doc.addEventListener("click", onClick);
  doc.addEventListener("keydown", onKey);
  doc.addEventListener("scroll", onScroll, true);
  return () => {
    close();
    doc.getElementById(MODAL_ID)?.remove();
    doc.removeEventListener("click", onClick);
    doc.removeEventListener("keydown", onKey);
    doc.removeEventListener("scroll", onScroll, true);
  };
}

const pad2 = (n: number) => String(n).padStart(2, "0");
/** A local day as yyyy-mm-dd (OF's route date). */
export const ymd = (d: Date) => `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`;
const dayStart = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate());
const addDays = (d: Date, n: number) => new Date(d.getFullYear(), d.getMonth(), d.getDate() + n);

/** OF's changeMonth: a month on or back (the day kept, or the month's last); today if that is not after today, else the month's first day. */
export function shiftMonth(date: Date, by: 1 | -1, today: Date): Date {
  const m = date.getMonth() + by;
  const s = new Date(date.getFullYear(), m, Math.min(date.getDate(), new Date(date.getFullYear(), m + 1, 0).getDate()));
  return s.getTime() <= dayStart(today).getTime() ? dayStart(today) : new Date(s.getFullYear(), s.getMonth(), 1);
}

/** The day a queue page opens on: its ?date= (yyyy-mm-dd), else today. */
export function queueStart(date: string | null, today: Date): Date {
  const d = date && /^\d{4}-\d{2}-\d{2}$/.test(date) ? parseDate(date) : null;
  return d ? new Date(d[0], d[1] - 1, d[2]) : dayStart(today);
}

// Not `instanceof`: the frame's elements are of the frame's window.
const setDisabled = (b: Element | null, off: boolean) => b?.toggleAttribute("disabled", off);

/**
 * A month page as OF draws it for `date`: the header's month, the back arrow greyed out on today's month, the
 * calendar's weeks (Sunday first; each cell OF's v-past / v-present / v-future, v-outside off the month, `date`
 * selected, its value "Nov 1" on a month's first day), the right column's day with its back arrow greyed out on
 * today, and the view switch's link carrying ?date=. The cells (and weeks) shown are kept and redrawn, a longer month
 * adding copies of the first.
 */
export function drawQueue(doc: Document, date: Date, today: Date): void {
  const t0 = dayStart(today);
  for (const el of doc.querySelectorAll(".g-page__subheader .b-queue-header__date")) el.textContent = ` ${date.toLocaleDateString("en-US", { month: "long", year: "numeric" })} `;
  const side = doc.querySelector(".l-wrapper__sidebar .b-queue-header__date");
  if (side) side.textContent = date.toLocaleDateString("en-US", { month: "long", day: "numeric", year: "numeric" });
  setDisabled(doc.querySelector("[at-attr='prev_month']"), date.getFullYear() === t0.getFullYear() && date.getMonth() === t0.getMonth());
  setDisabled(doc.querySelector("[at-attr='prev_day_sidebar']"), ymd(date) === ymd(t0));
  const view = doc.querySelector(".g-page__subheader .b-content-filter__group-btns a[href]");
  view?.setAttribute("href", `${view.getAttribute("href")!.split("?")[0]}?date=${ymd(date)}`);
  const calendar = doc.querySelector(".v-calendar-monthly");
  const weeks = calendar ? [...calendar.querySelectorAll(":scope > .v-calendar-weekly__week")] : [];
  const tpl = weeks[0]?.querySelector(".v-calendar-weekly__day");
  if (!calendar || !tpl) return;
  const first = new Date(date.getFullYear(), date.getMonth(), 1);
  const last = new Date(date.getFullYear(), date.getMonth() + 1, 0);
  const old = weeks.flatMap((w) => [...w.querySelectorAll(":scope > .v-calendar-weekly__day")]);
  const shown: Element[] = [];
  let n = 0;
  for (let d = addDays(first, -first.getDay()); d <= addDays(last, 6 - last.getDay()); d = addDays(d, 1), n++) {
    if (d.getDay() === 0) shown.push(weeks[shown.length] ?? (weeks[0].cloneNode(false) as Element));
    const cell = old[n] ?? (tpl.cloneNode(true) as Element);
    // A new cell copies the first's: not its event bars (applyQueue's, undone by the next apply).
    if (!old[n]) for (const bar of cell.querySelectorAll("[data-oi-data]")) bar.remove();
    const past = d < t0;
    cell.className = ["v-calendar-weekly__day", past ? "v-past" : ymd(d) === ymd(t0) ? "v-present" : "v-future", ...(d.getMonth() !== date.getMonth() ? ["v-outside"] : [])].join(" ");
    const button = cell.querySelector(".b-month-day-cell");
    button?.setAttribute("class", `b-month-day-cell${ymd(d) === ymd(date) ? " selected" : ""}`);
    button?.setAttribute("tabindex", past ? "-1" : "0");
    const value = cell.querySelector(".b-month-day-cell__value");
    value?.setAttribute("at-attr", `date:${ymd(d)}`);
    if (value) value.textContent = ` ${d.getDate() === 1 ? d.toLocaleDateString("en-US", { month: "short", day: "numeric" }) : d.getDate()} `;
    shown[shown.length - 1].appendChild(cell);
  }
  for (const c of old.slice(n)) c.remove();
  for (const w of weeks.slice(shown.length)) w.remove();
  calendar.append(...shown.slice(weeks.length));
}

const ARROWS = "[at-attr='prev_month'], [at-attr='next_month'], [at-attr='prev_day_sidebar'], [at-attr='next_day_sidebar']";
const TAB = ".g-page__subheader .b-tabs__nav__link";

/** Bind a month page's calendar, arrows and tabs in `doc`, opened on `start`; `now` is the clock. Returns an unbind. */
export function bindCalendar(doc: Document, start: Date, now: () => Date): () => void {
  let date = dayStart(start);
  // A selected tab's check mark, kept for the tabs selected later (none on a page captured with no tab selected).
  let check = doc.querySelector(`${TAB} .b-tabs__nav__icon`)?.cloneNode(true) as Element | undefined;
  const changed = () => doc.dispatchEvent(new Event(QUEUE_CHANGE));
  const go = (next: Date) => {
    date = dayStart(next);
    drawQueue(doc, date, now());
    changed();
  };
  const onClick = (ev: MouseEvent) => {
    const t = ev.target as Element | null;
    if (!t?.closest) return;
    const arrow = t.closest<HTMLButtonElement>(ARROWS);
    if (arrow) {
      ev.preventDefault();
      if (arrow.disabled) return;
      const at = arrow.getAttribute("at-attr")!;
      const by = at.startsWith("prev") ? -1 : 1;
      return go(at.endsWith("_month") ? shiftMonth(date, by, now()) : addDays(date, by));
    }
    const cell = t.closest<HTMLElement>(".v-calendar-monthly .v-calendar-weekly__day");
    if (cell) {
      ev.preventDefault();
      const d = parseDate(cell.querySelector(".b-month-day-cell__value")?.getAttribute("at-attr")?.replace(/^date:/, "") ?? "");
      if (d && !cell.classList.contains("v-past")) go(new Date(d[0], d[1] - 1, d[2]));
      return;
    }
    const tab = t.closest<HTMLElement>(TAB);
    if (tab) {
      ev.preventDefault();
      const on = !tab.classList.contains("m-current");
      tab.classList.toggle("m-current", on);
      const icon = tab.querySelector(":scope > .b-tabs__nav__icon");
      if (!on && icon) {
        check ??= icon.cloneNode(true) as Element;
        icon.remove();
      } else if (on && !icon && check) tab.prepend(check.cloneNode(true));
      changed();
    }
  };
  drawQueue(doc, date, now());
  changed();
  doc.addEventListener("click", onClick);
  return () => doc.removeEventListener("click", onClick);
}

/**
 * The moment Add to queue opens on for `day` (yyyy-mm-dd, a day of `zone`, the Agency's), as the live modal does: a
 * later day at its midnight (OF's queue passes the selected day), today (or a day already past) ten minutes from `now`,
 * OF's own default and minimum (the modal's `add(10, "minutes")`).
 */
export function createAt(day: string, zone: string | undefined, now: Date): Date {
  const d = parseDate(day);
  const soon = new Date(now.getTime() + 600_000);
  if (!d) return soon;
  const midnight = fromWallClock(new Date(d[0], d[1] - 1, d[2]), zone);
  return minuteAhead(midnight, soon) ? midnight : soon;
}

/**
 * Where Add to queue > Scheduled > `kind` goes for `accountId`, with its schedule (`at`) put on that composer's draft, as
 * OF's goToScheduleEvent(route, {scheduleDate}): New post with the Post draft's `posted_at` (named under its editor),
 * New message with the Mass draft's `scheduled_date`, the stream schedule form with its date and time filled in
 * (?date=, ?time=). The drafts' other fields are kept; a draft that was editing a queued item starts a new one.
 */
export function createHref(kind: CreateKind, at: Date, storage: Storage, accountId: string): string {
  if (kind === "post") {
    saveDraft(storage, accountId, { ...loadDraft(storage, accountId), posted_at: localIso(at), save_for_later: undefined, edit_id: undefined });
    return "/of-manager/new-post";
  }
  if (kind === "message") {
    storage.setItem(massDraftKey(accountId), JSON.stringify({ ...loadMassDraft(storage, accountId), scheduled_date: localIso(at), save_for_later: undefined, edit_id: undefined }));
    return "/of-manager/messages/send";
  }
  const time = at.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" }).toLowerCase();
  return `/of-manager/streaming/dashboard/create?date=${ymd(at)}&time=${encodeURIComponent(time)}`;
}

/** Where Add to queue > Save for later > `kind` goes for `accountId`: its composer, the draft saving for later (no date). */
export function laterHref(kind: LaterKind, storage: Storage, accountId: string): string {
  if (kind === "post") {
    saveDraft(storage, accountId, { ...loadDraft(storage, accountId), save_for_later: true, posted_at: undefined, edit_id: undefined });
    return "/of-manager/new-post";
  }
  storage.setItem(massDraftKey(accountId), JSON.stringify({ ...loadMassDraft(storage, accountId), save_for_later: true, scheduled_date: undefined, edit_id: undefined }));
  return "/of-manager/messages/send";
}

/** GET /api/of/v2/posts/{id}: what Edit post reads (OF's post; only the fields the composer keeps). */
export interface EditablePost {
  id: number | string;
  rawText?: string | null;
  text?: string | null;
  price?: number | string | null;
  postedAt?: string | null;
  isPublishedWithPeriod?: boolean;
  media?: OFMedia[] | null;
  labelStates?: { id: number | string; isAdded?: boolean }[] | null;
  canEditSchedule?: boolean;
}

/**
 * The Post draft that edits `post`, as OF's PostsEdit fills MakeFeedPost: its text, media (their ids, OF's
 * uploadedFilesUrl for media already on the post), price, labels and its schedule (`postedAt`, or saved for later), and
 * `edit_id` so Post saves this post (PUT) instead of making a new one. `img` maps a picture's url for the thumbs row
 * (the Relay's image proxy); a media item with no picture gets "" (a plain square).
 */
export function postEditDraft(post: EditablePost, img: (url: string) => string = (u) => u): PostDraft {
  const media = (post.media ?? []).filter((m) => m.id != null);
  const price = Number(post.price) || 0;
  const labels = (post.labelStates ?? []).filter((l) => l.isAdded !== false && Number.isInteger(Number(l.id))).map((l) => Number(l.id));
  const at = valid(post.postedAt ?? undefined);
  return {
    text: post.rawText ?? plain(post.text),
    tagged_users: [],
    media_files: media.map((m) => Number(m.id)),
    thumbs: media.map((m) => {
      const url = stillUrl(m);
      return url ? img(url) : "";
    }),
    ...(price ? { price } : {}),
    ...(labels.length ? { label_ids: labels } : {}),
    ...(post.isPublishedWithPeriod ? { save_for_later: true } : at ? { posted_at: localIso(at) } : {}),
    edit_id: String(post.id),
  };
}

/** GET /api/of/v2/messages/queue/{id}: what Edit message reads (OF's queued message, format=scheduled). */
export interface QueuedMessage {
  id: number | string;
  text?: string | null;
  rawText?: string | null;
  price?: number | string | null;
  /** Its send time; none: saved for later. */
  scheduledAt?: string | null;
  media?: OFMedia[] | null;
  userIds?: (number | string)[] | null;
  userLists?: (number | string)[] | null;
  excludedLists?: (number | string)[] | null;
}

/**
 * The Mass draft that edits `msg`, as OF's ChatsSend loads a queued message (setDataSchedule, setDataMessage): its text,
 * media, price, recipients (`userIds`), lists (`userLists`) and excluded lists, its schedule (`scheduledAt`, else saved
 * for later), and `edit_id` so Send saves this message (PUT) instead of sending a new one.
 */
export function messageEditDraft(msg: QueuedMessage): MassDraft {
  const media = (msg.media ?? []).filter((m) => m.id != null);
  const price = Number(msg.price) || 0;
  const at = valid(msg.scheduledAt ?? undefined);
  return {
    text: msg.rawText ?? plain(msg.text),
    user_lists: (msg.userLists ?? []).map(String),
    ...(msg.userIds?.length ? { user_ids: msg.userIds.map(Number) } : {}),
    ...(msg.excludedLists?.length ? { excluded_user_lists: msg.excludedLists.map(String) } : {}),
    ...(media.length ? { media_files: media.map((m) => Number(m.id)) } : {}),
    ...(price ? { price } : {}),
    ...(at ? { scheduled_date: localIso(at) } : { save_for_later: true }),
    edit_id: String(msg.id),
  };
}

/** The pages whose Scheduled events widget has OF's Add to queue "+" (New post's and Go live's schedule form). */
const WIDGET_PAGE = /^(?:new-post\/(?:index|state-[^/]+)|streaming\/dashboard\/create)$/;

/** The queue pages (QUEUE): bind the rows' menus (and a month page's calendar) on every frame load; a success refetches the page's rows. */
export function useOfQueue(frameRef: RefObject<HTMLIFrameElement | null>, src: string): void {
  const { accountId, setScope } = useScope();
  const qc = useQueryClient();
  const router = useRouter();
  const date = useSearchParams().get("date");
  const zone = useAgencyZone();
  const page = /^\/of-mirror\/pages\/(.+)\.html$/.exec(src)?.[1] ?? "";
  const queue = Object.hasOwn(QUEUE, page);
  const month = queue && !!QUEUE[page].month;
  // The Add to queue "+" also works on the Scheduled events widget's pages.
  const on = queue || WIDGET_PAGE.test(page);

  // The month pages' calendar, arrows and tabs: in either scope (they only change what is shown).
  useEffect(() => {
    const frame = frameRef.current;
    if (!frame || !month) return;
    let unbind: (() => void) | undefined;
    const bind = () => {
      unbind?.();
      const doc = frame.contentDocument;
      const now = () => wallClock(new Date(), zone);
      unbind = doc?.body ? bindCalendar(doc, queueStart(date, now()), now) : undefined;
    };
    if (frame.contentDocument?.readyState === "complete") bind();
    frame.addEventListener("load", bind);
    return () => {
      frame.removeEventListener("load", bind);
      unbind?.();
    };
  }, [frameRef, src, month, date, zone]);

  useEffect(() => {
    const frame = frameRef.current;
    if (!frame || !on) return;
    const ctx = { accountId };
    const done = (r: unknown) => {
      qc.invalidateQueries({ queryKey: ["of-mirror-data", accountId] });
      return r;
    };
    const enc = encodeURIComponent;
    const handlers: QueueHandlers | null = accountId
      ? {
          publish: (id) => relay.put(`/api/of/v2/schedules/${enc(id)}/publish`, undefined, ctx).then(done),
          remove: (kind, id) => relay.delete(kind === "post" ? `/api/of/v2/posts/${enc(id)}` : `/api/of/v2/messages/queue/${enc(id)}`, ctx).then(done),
          pin: (id) => relay.post(`/api/of/v2/posts/${enc(id)}/pin`, undefined, ctx).then(done),
          confirm: (text) => window.confirm(text),
          // In All models the composers act for the model the queue shows (standInModel): it becomes the scope.
          create: (kind, at) => open(createHref(kind, at, window.sessionStorage, accountId)),
          later: (kind) => open(laterHref(kind, window.sessionStorage, accountId)),
          edit: async (kind, id) => {
            const storage = window.sessionStorage;
            if (kind === "post") {
              const post = await relay.get<EditablePost>(`/api/of/v2/posts/${enc(id)}`, ctx);
              saveDraft(storage, accountId, postEditDraft(post, (u) => proxyImage(u, accountId)));
              return open("/of-manager/new-post");
            }
            storage.setItem(massDraftKey(accountId), JSON.stringify(messageEditDraft(await relay.get<QueuedMessage>(`/api/of/v2/messages/queue/${enc(id)}`, ctx))));
            open("/of-manager/messages/send");
          },
        }
      : null;
    function open(href: string) {
      setScope({ kind: "model", accountId: accountId! });
      router.push(href);
    }
    let unbind: (() => void) | undefined;
    const bind = () => {
      unbind?.();
      const doc = frame.contentDocument;
      unbind = doc?.body ? bindQueue(doc, handlers, zone) : undefined;
    };
    if (frame.contentDocument?.readyState === "complete") bind();
    frame.addEventListener("load", bind);
    return () => {
      frame.removeEventListener("load", bind);
      unbind?.();
    };
  }, [frameRef, src, on, accountId, qc, zone, setScope, router]);
}
