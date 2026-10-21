"use client";

/**
 * The OF mirror's chat list controls (messages/index, a chat's pages, the sort dropdown and the folders dialog), as OF's
 * own chats list does them (its web bundle's chats-list chunk; ledger .scratch/omf-messages-full/ledger.md). All wiring
 * is runtime DOM; the rows themselves are ofMirrorData's (applyChats, read through Messages Pro's useChatList).
 *
 * The list's state lives in the app URL, so every tab, sort option and folder is a plain navigation and Back works:
 * `?tab=pinned|priority|unread|who_tipped` (absent: All), `?folder=<list id>` (a list pinned to chats), `?filter=` the
 * dropdown's priority|unread|unread_tips, `?order=old` (Oldest First; absent: Newest First) and `?q=` the header search.
 * chatsRequest turns it into OF's own GET /chats params: a tab's filter wins over the dropdown's (whose group OF hides
 * on Unread, Pinned and Priority), With Tips with the dropdown's Unread is `unread_tips`, a folder is `list_id`.
 *
 * - Tabs: All, Pinned, Priority, Unread and With Tips, shown by OF's rules from /users/me (Pinned while countPinnedChat,
 *   Priority while countPriorityChat, Unread while chatMessagesCount, With Tips while tipsEnabled; the open tab always),
 *   each with OF's count; then one tab per list pinned to chats (/chats/folders, disabled while it has no users); the
 *   pencil opens the folders dialog (messages/state-folders): each pinnable list a checkbox, PATCH /lists/{id}/pin-chat.
 * - The sort dropdown (messages/state-filter-dropdown): its filter and order radios link to the list with that change,
 *   the current ones checked, the groups OF hides hidden; the title shows the order. "Mark all as read" sends
 *   POST /chats/mark-as-read (no confirm, as OF) and is disabled while /users/me has no unread chats.
 * - Header search: the magnifier opens OF's search form; typing (500 ms after the last key) or Enter lists `?q=`, Clear
 *   closes it.
 * - A row's "x" (Clear messages) asks first, then DELETE /chats/{id}; the open chat's row goes back to the list.
 * - A row swiped left past OF's threshold (its SwipeOut, 100 px; with a finger or the mouse) shows OF's "Mark as Read" /
 *   "Mark as Unread" behind it and then sends it: POST or DELETE /chats/{id}/mark-as-read (OF offers read state only
 *   there and on its own scroll to the end, which the mirror never does).
 * Nothing here marks a chat read: opening or scrolling a chat sends no mark-as-read.
 * All models with no model: navigation works; Mark all as read, a row's "x" and a folder checkbox send nothing and show
 * "Select a model to save changes".
 */

import { useEffect, type RefObject } from "react";
import { useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { useRouter, useSearchParams } from "next/navigation";
import { useScope } from "@/contexts/ScopeContext";
import { relay } from "@/lib/relay";
import { own } from "@/lib/ofMirrorData";
import { applyListRows } from "@/lib/ofMirrorChat";
import { ofMeQuery, type OfMe } from "@/lib/ofMirrorIdentity";
import { message, note, SELECT_MODEL } from "@/lib/ofMirrorWrites";
import { useAllChatFolders, type ChatFolder } from "@/hooks/useChatFolders";
import type { ChatListFilter, ChatListOrder } from "@/hooks/useChatList";

export const LIST_PAGE = "/of-manager/messages";
export const CHAT_PAGE = "/of-manager/messages/chat";
export const DROPDOWN_PAGE = "/of-manager/messages/state-filter-dropdown";
export const FOLDERS_PAGE = "/of-manager/messages/state-folders";
/** OF's tooltip on the row's "x" is "Clear messages"; its confirm text (message.confirm_delete_chat_desc) is not in the bundle: assumed. */
export const CLEAR_CONFIRM = "Clear messages? This cannot be undone.";
/** The header search waits this long after the last key, as OF's (debounced) chats search. */
export const SEARCH_MS = 500;
/** The fewest characters OF's search lists on its own (its ChatsSearch watcher: `length < 3` waits for Enter). */
export const SEARCH_MIN = 3;

export const TABS = ["pinned", "priority", "unread", "who_tipped"] as const;
export type ChatsTab = (typeof TABS)[number];
export const DROP_FILTERS = ["priority", "unread", "unread_tips"] as const;
export type ChatsDropFilter = (typeof DROP_FILTERS)[number];

/** The chat list's view, as the app URL carries it. */
export interface ChatsView {
  tab: ChatsTab | null;
  folder: string | null;
  filter: ChatsDropFilter | null;
  order: ChatListOrder;
  q: string | null;
}

const isOf = <T extends string>(list: readonly T[], v: string | null): v is T => v !== null && (list as readonly string[]).includes(v);

/** The view in `params` (anything unknown is dropped; a tab wins over a folder). */
export function chatsView(params: { get(key: string): string | null }): ChatsView {
  const tab = params.get("tab");
  const filter = params.get("filter");
  const t = isOf(TABS, tab) ? tab : null;
  return {
    tab: t,
    folder: t ? null : params.get("folder") || null,
    filter: isOf(DROP_FILTERS, filter) ? filter : null,
    order: params.get("order") === "old" ? "old" : "recent",
    q: params.get("q")?.trim() || null,
  };
}

/** OF shows the dropdown's filter group on All, With Tips and a folder (not on Unread, Pinned or Priority). */
export const filterGroupShown = (v: ChatsView) => !v.tab || v.tab === "who_tipped";
/** And its order group everywhere but Pinned (OF sends no order there). */
export const orderGroupShown = (v: ChatsView) => v.tab !== "pinned";

/** OF's GET /chats params for the view (its chats-list fetch): filter, list_id, order and query. */
export function chatsRequest(v: ChatsView): { filter: ChatListFilter | null; listId: string | null; order: ChatListOrder; query: string | null } {
  // "Unread with tips" is hidden on With Tips, so it does not apply there.
  const dd = filterGroupShown(v) && !(v.tab === "who_tipped" && v.filter === "unread_tips") ? v.filter : null;
  const filter: ChatListFilter | null = v.tab === "who_tipped" && dd === "unread" ? "unread_tips" : (v.tab ?? dd);
  return { filter, listId: v.tab ? null : v.folder, order: v.order, query: v.q };
}

/** The view as a query string, in a fixed order, without "?" ("" for the default view). */
export function chatsQuery(v: ChatsView): string {
  const q = new URLSearchParams();
  if (v.tab) q.set("tab", v.tab);
  if (v.folder) q.set("folder", v.folder);
  if (v.filter) q.set("filter", v.filter);
  if (v.order === "old") q.set("order", "old");
  if (v.q) q.set("q", v.q);
  return q.toString();
}

/** `path` with the open chat (when given) and the view. */
export function chatsHref(path: string, chat: string | null, v: ChatsView): string {
  const parts = [chat ? `chat=${encodeURIComponent(chat)}` : "", chatsQuery(v)].filter(Boolean);
  return parts.length ? `${path}?${parts.join("&")}` : path;
}

/** The list (the open chat's page while one is open) showing `v`. */
export const listHref = (chat: string | null, v: ChatsView) => chatsHref(chat ? CHAT_PAGE : LIST_PAGE, chat, v);

/** OF's tab counter: none for 0, "999+" past 999 (its unreadTips cap). */
export const counter = (n: number | null | undefined) => (!n || n < 0 ? "" : n > 999 ? "999+" : String(n));

/** The /users/me fields OF's tab bar and dropdown read. */
export type ChatsMe = Pick<OfMe, "chatMessagesCount"> & { countPinnedChat?: number | null; countPriorityChat?: number | null; unreadTips?: number | null; tipsEnabled?: boolean | null };

export interface ChatsWrites {
  /** DELETE /chats/{id} (Clear messages). */
  clear(chat: string): Promise<unknown>;
  /** POST /chats/mark-as-read. */
  markAllRead(): Promise<unknown>;
  /** PATCH /lists/{id}/pin-chat {pinned}. */
  pinFolder(id: string, pinned: boolean): Promise<unknown>;
  /** POST (read) or DELETE (unread) /chats/{id}/mark-as-read: a row's swipe. */
  markRead(chat: string, read: boolean): Promise<unknown>;
}

export interface ChatsContext {
  view: ChatsView;
  /** ?chat=: the open chat's fan id. */
  chat: string | null;
  /** /users/me, once read. */
  me?: ChatsMe;
  /** /chats/folders' lists (pinned and pinnable), once read. */
  folders?: ChatFolder[];
  navigate(href: string, replace?: boolean): void;
  /** null: All models with no model (nothing is sent). */
  writes: ChatsWrites | null;
  confirm(text: string): boolean;
}

const BAR = ".b-chats__conversations-list .b-tabs__nav";
const TAB = "button[data-oi-tab]";
const DROP_ITEM = "[data-oi-chats]";
const SEARCH_BTN = ".b-chats__header button[at-attr='search_header_btn']";
const SEARCH_FORM = ".b-chats__header .b-chat__search-form";
const CLEAR_BTN = ".b-chats__item__btn-clear";
// OF's collection rows only: a chat's tag dialog (its m-release-item rows) is another modal list on a chat page.
const FOLDER_ROW = ".modal .b-rows-lists label.b-rows-lists__item.m-collection-item";
/** OF's row SwipeOut and its threshold (chats-list: `threshold: 100`). */
const SWIPE_ROW = ".swipeout";
export const SWIPE_PX = 100;

/** Show or hide `el` (inline display, nothing else touched). */
const show = (el: HTMLElement | null | undefined, on: boolean) => {
  if (el) el.style.display = on ? "" : "none";
};

/** The tab a button stands for, as the view it opens. */
function tabView(btn: HTMLElement, v: ChatsView): ChatsView | null {
  const t = btn.dataset.oiTab;
  if (t === "all") return { ...v, tab: null, folder: null };
  if (t === "folder") return { ...v, tab: null, folder: btn.dataset.oiFolder ?? null };
  if (isOf(TABS, t ?? null)) return { ...v, tab: t as ChatsTab, folder: null };
  return null;
}

const isCurrent = (btn: HTMLElement, v: ChatsView) => {
  const t = btn.dataset.oiTab;
  if (t === "all") return !v.tab && !v.folder;
  if (t === "folder") return !v.tab && v.folder === btn.dataset.oiFolder;
  return v.tab === t;
};

/** OF's rule for a special tab's visibility (null: no /users/me yet, shown as captured). */
function tabShown(t: string | undefined, me: ChatsMe | undefined): boolean {
  if (!me) return true;
  if (t === "pinned") return (me.countPinnedChat ?? 0) > 0;
  if (t === "priority") return (me.countPriorityChat ?? 0) > 0;
  if (t === "unread") return (me.chatMessagesCount ?? 0) > 0;
  if (t === "who_tipped") return me.tipsEnabled === true;
  return true;
}

function tabCount(t: string | undefined, me: ChatsMe | undefined): string {
  if (!me) return "";
  if (t === "pinned") return counter(me.countPinnedChat);
  if (t === "priority") return counter(me.countPriorityChat);
  if (t === "unread") return counter(me.chatMessagesCount);
  if (t === "who_tipped") return counter(me.unreadTips);
  return "";
}

/** One tab's current mark (OF's m-current m-no-pointer) and counter. */
function markTab(doc: Document, btn: HTMLElement, current: boolean, count: string) {
  btn.classList.toggle("m-current", current);
  btn.classList.toggle("m-no-pointer", current);
  btn.querySelector(".b-tabs__nav__count")?.remove();
  if (!count) return;
  const text = btn.querySelector(".b-tabs__nav__text");
  const span = doc.createElement("span");
  for (const a of [...(text?.attributes ?? [])]) if (a.name.startsWith("data-v-")) span.setAttribute(a.name, a.value);
  span.className = "b-tabs__nav__count";
  span.textContent = count;
  (text ?? btn).after(span);
}

/** The tab bar: the special tabs by OF's rules, the folder tabs, the current one marked. */
export function applyTabs(doc: Document, ctx: ChatsContext): void {
  const bar = doc.querySelector(BAR);
  if (!bar) return;
  const { view, me, folders } = ctx;
  for (const old of bar.querySelectorAll("[data-oi-folder-tab]")) old.remove();
  const tabs = [...bar.querySelectorAll<HTMLButtonElement>(TAB)];
  for (const btn of tabs) {
    const t = btn.dataset.oiTab;
    if (t === "folders") continue;
    const current = isCurrent(btn, view);
    show(btn.closest<HTMLElement>("li"), current || tabShown(t, me));
    markTab(doc, btn, current, tabCount(t, me));
  }
  // OF's loader between the tabs and the pencil: the folder tabs are being read.
  const loader = bar.querySelector<HTMLElement>(".b-posts_preloader");
  show(loader, folders === undefined);
  const textTab = tabs.find((b) => b.dataset.oiTab === "who_tipped") ?? tabs.find((b) => b.dataset.oiTab === "all");
  const li = textTab?.closest("li");
  if (!li || !folders) return;
  const at = loader ?? bar.querySelector(`${TAB}[data-oi-tab='folders']`)?.closest("li") ?? null;
  for (const f of folders.filter((f) => f.isPinnedToChat)) {
    const item = li.cloneNode(true) as HTMLElement;
    item.style.removeProperty("display");
    item.setAttribute("data-oi-folder-tab", "");
    const btn = item.querySelector<HTMLButtonElement>("button")!;
    btn.dataset.oiTab = "folder";
    btn.dataset.oiFolder = String(f.id);
    const text = btn.querySelector(".b-tabs__nav__text");
    if (text) {
      text.classList.remove("m-capitalize");
      text.textContent = ` ${f.name ?? ""} `;
    }
    btn.disabled = !f.usersCount; // OF: a list with no users is a disabled tab
    markTab(doc, btn, !view.tab && view.folder === String(f.id), "");
    at ? at.before(item) : li.parentElement?.appendChild(item);
  }
}

/**
 * Links to the dropdown and the folders dialog carry the open chat and the view; on those two pages the links back to the
 * list (backdrop, toggle, Close) go to the same list (or chat) again. Their original href is kept as keepQuery does.
 */
function carryView(doc: Document, ctx: ChatsContext) {
  const query = [ctx.chat ? `chat=${encodeURIComponent(ctx.chat)}` : "", chatsQuery(ctx.view)].filter(Boolean).join("&");
  const onState = !!doc.querySelector(`${DROP_ITEM}, ${FOLDER_ROW}`);
  for (const a of doc.querySelectorAll<HTMLAnchorElement>("a[href^='/of-manager/messages']")) {
    const href = a.dataset.oiHref ?? a.getAttribute("href") ?? "";
    if (a.closest(DROP_ITEM)) continue; // applyDropdown's
    const to = href === DROPDOWN_PAGE || href === FOLDERS_PAGE ? (query ? `${href}?${query}` : href) : onState && href === LIST_PAGE ? listHref(ctx.chat, ctx.view) : null;
    if (to === null) continue;
    a.dataset.oiHref = href;
    a.setAttribute("href", to);
  }
}

/** The sort dropdown's items (generator marks: data-oi-chats="filter:<v>|order:<v>|mark-all"): links, checks and OF's hidden groups. */
export function applyDropdown(doc: Document, ctx: ChatsContext): void {
  const { view, me } = ctx;
  const items = [...doc.querySelectorAll<HTMLElement>(DROP_ITEM)];
  const groupEnd = (el: HTMLElement) => (el.nextElementSibling?.matches("hr") ? (el.nextElementSibling as HTMLElement) : null);
  for (const item of items) {
    const [kind, value = ""] = (item.dataset.oiChats ?? "").split(":");
    const link = item.querySelector<HTMLAnchorElement>("a.of-state-link");
    const radio = item.querySelector<HTMLInputElement>("input[type='radio']");
    if (kind === "filter") {
      const next: ChatsView = { ...view, filter: (value || null) as ChatsDropFilter | null };
      link?.setAttribute("href", listHref(ctx.chat, next));
      const on = (view.filter ?? "") === value;
      if (radio) {
        radio.checked = on;
        radio.toggleAttribute("checked", on);
      }
      // OF's filter group: Priority and Unread with tips are not offered on With Tips; Unread with tips needs tipsEnabled.
      const hidden = !filterGroupShown(view) || ((value === "priority" || value === "unread_tips") && view.tab === "who_tipped") || (value === "unread_tips" && !!me && me.tipsEnabled !== true);
      show(item, !hidden);
      show(groupEnd(item), filterGroupShown(view));
    } else if (kind === "order") {
      link?.setAttribute("href", listHref(ctx.chat, { ...view, order: value === "old" ? "old" : "recent" }));
      const on = view.order === (value === "old" ? "old" : "recent");
      if (radio) {
        radio.checked = on;
        radio.toggleAttribute("checked", on);
      }
      show(item, orderGroupShown(view));
      show(groupEnd(item), orderGroupShown(view));
    } else if (kind === "mark-all") {
      // OF: disabled while the Creator has no unread chat (authUser.chatMessagesCount); unknown counts as none.
      const off = !((me?.chatMessagesCount ?? 0) > 0);
      item.classList.toggle("v-list-item--disabled", off);
      item.setAttribute("aria-disabled", String(off));
      item.toggleAttribute("data-oi-wired", !off);
      link?.remove(); // its click is the binder's, never a navigation
    }
  }
}

/** The list header's title: the order's label, as OF's. */
function applyTitle(doc: Document, v: ChatsView) {
  const title = doc.querySelector<HTMLElement>(".b-chats__conversations-list .b-content-filter__title");
  if (title) title.textContent = v.order === "old" ? "Oldest First" : "Newest First";
}

/** The header search form: open (OF's m-search-form-visible on the header) with the query while there is one. */
function applySearch(doc: Document, v: ChatsView, open: boolean) {
  const form = doc.querySelector<HTMLFormElement>(SEARCH_FORM);
  if (!form) return;
  const input = form.querySelector<HTMLInputElement>("input[type='search']");
  doc.querySelector(".b-chats__header")?.classList.toggle("m-search-form-visible", open);
  if (input && doc.activeElement !== input) input.value = v.q ?? "";
  const submit = form.querySelector<HTMLButtonElement>("button[type='submit']");
  if (submit) submit.disabled = !(input?.value.trim());
}

/** Wire the chat list's controls in `doc` (any page with the list, the dropdown or the folders dialog). Returns an unbind. */
export function bindChatList(doc: Document, ctx: ChatsContext): () => void {
  const { view, writes } = ctx;
  applyTabs(doc, ctx);
  applyTitle(doc, view);
  applyDropdown(doc, ctx);
  carryView(doc, ctx);
  applySearch(doc, view, !!view.q);
  for (const el of doc.querySelectorAll(`${TAB}, ${SEARCH_BTN}, ${SEARCH_FORM} button`)) el.setAttribute("data-oi-wired", "");

  // The folders dialog: each pinnable list a checkbox, ticked when pinned to chats.
  const pinnable = ctx.folders?.filter((f) => f.canPinnedToChat !== false);
  const undoRows = pinnable && doc.querySelector(FOLDER_ROW)
    ? own(() => applyListRows(doc, pinnable.map((f) => ({ id: f.id, name: f.name, usersCount: f.usersCount })), pinnable.filter((f) => f.isPinnedToChat).map((f) => String(f.id)), { rows: FOLDER_ROW, empty: ".modal [data-oi-empty]" }))
    : null;

  let timer: ReturnType<typeof setTimeout> | undefined;
  // A row's swipe (OF's SwipeOut): dragged left, its label shows; let go past the threshold, read state flips.
  let drag: { x: number; y: number; dx: number; moving: boolean; box: HTMLElement; row: HTMLElement; id: string } | null = null;
  let swallow = false;
  const slide = (box: HTMLElement, dx: number, animate: boolean) => {
    box.classList.toggle("swipeout--no-transition", !animate);
    box.classList.toggle("swipeout-non-selectable", dx !== 0);
    const content = box.querySelector<HTMLElement>(":scope > .swipeout-content");
    const right = box.querySelector<HTMLElement>(":scope > .swipeout-right");
    if (content) content.style.transform = dx ? `translateX(${dx}px)` : "";
    if (right) right.style.transform = dx ? `translateX(calc(100% + ${dx}px))` : "";
  };
  const onDown = (ev: PointerEvent) => {
    const t = ev.target as Element | null;
    if (ev.button !== 0 || !t?.closest || t.closest(`${CLEAR_BTN}, .g-avatar`)) return;
    const box = t.closest<HTMLElement>(SWIPE_ROW);
    const row = box?.querySelector<HTMLElement>("[data-oi-chat]");
    if (!box || !row) return;
    drag = { x: ev.clientX, y: ev.clientY, dx: 0, moving: false, box, row, id: row.dataset.oiChat! };
    // No capture yet: a capture on pointerdown retargets a plain click to the .swipeout box, so the row's link would
    // not open the chat. It is taken once the drag really moves (onMove).
  };
  /** A drag that ends without a deliberate release (no button held any more, the browser took the gesture): no write. */
  const reset = () => {
    const d = drag;
    drag = null;
    if (d?.moving) slide(d.box, 0, true);
  };
  const onMove = (ev: PointerEvent) => {
    if (!drag) return;
    if (ev.buttons === 0) return reset(); // the button was let go where no pointerup reached us
    const dx = Math.min(0, ev.clientX - drag.x);
    if (!drag.moving) {
      if (Math.abs(ev.clientY - drag.y) > Math.abs(ev.clientX - drag.x) && Math.abs(ev.clientY - drag.y) > 6) return void (drag = null); // a scroll
      if (dx > -6) return;
      drag.moving = true;
      // From here on the release comes back to this row even if the pointer leaves it (or the frame).
      try {
        drag.box.setPointerCapture?.(ev.pointerId);
      } catch {
        /* a synthetic pointer has no capture */
      }
    }
    drag.dx = dx;
    slide(drag.box, dx, false);
  };
  const onUp = () => {
    const d = drag;
    drag = null;
    if (!d?.moving) return;
    swallow = true; // the click that ends a drag opens no chat
    setTimeout(() => (swallow = false), 0);
    slide(d.box, 0, true);
    if (-d.dx < SWIPE_PX) return;
    const read = d.row.hasAttribute("data-oi-unread");
    if (!writes) return note(doc, d.row, SELECT_MODEL);
    writes.markRead(d.id, read).then(
      () => d.row.toggleAttribute("data-oi-unread", !read),
      (e) => note(doc, d.row, `Could not mark as ${read ? "read" : "unread"}: ${message(e)}`, true),
    );
  };
  const onDragStart = (ev: DragEvent) => {
    if ((ev.target as Element | null)?.closest?.(SWIPE_ROW)) ev.preventDefault(); // a link's drag would end the swipe
  };
  const search = (q: string, replace: boolean) => ctx.navigate(listHref(ctx.chat, { ...view, q: q.trim() || null }), replace);

  const onClick = (ev: MouseEvent) => {
    const t = ev.target as Element | null;
    if (!t?.closest) return;
    if (swallow && t.closest(SWIPE_ROW)) {
      ev.preventDefault();
      ev.stopPropagation();
      swallow = false;
      return;
    }
    const tab = t.closest<HTMLButtonElement>(`${BAR} ${TAB}`);
    if (tab) {
      ev.preventDefault();
      if (tab.disabled) return;
      if (tab.dataset.oiTab === "folders") return ctx.navigate(chatsHref(FOLDERS_PAGE, ctx.chat, view));
      const next = tabView(tab, view);
      if (next && !isCurrent(tab, view)) ctx.navigate(listHref(ctx.chat, next));
      return;
    }
    if (t.closest(SEARCH_BTN)) {
      ev.preventDefault();
      applySearch(doc, view, true);
      doc.querySelector<HTMLInputElement>(`${SEARCH_FORM} input[type='search']`)?.focus();
      return;
    }
    const back = t.closest(`${SEARCH_FORM} button[aria-label='Clear']`);
    if (back) {
      ev.preventDefault();
      clearTimeout(timer);
      applySearch(doc, { ...view, q: null }, false);
      if (view.q) search("", false);
      return;
    }
    const x = t.closest<HTMLElement>(CLEAR_BTN);
    const row = x?.closest<HTMLElement>("[data-oi-chat]");
    if (x && row) {
      ev.preventDefault();
      ev.stopPropagation();
      const id = row.dataset.oiChat!;
      if (!writes) return note(doc, x, SELECT_MODEL);
      if (!ctx.confirm(CLEAR_CONFIRM)) return;
      writes.clear(id).then(
        () => {
          if (ctx.chat === id) ctx.navigate(listHref(null, view), true); // the cleared chat is no page to go Back to
        },
        (e) => note(doc, x, `Could not clear messages: ${message(e)}`, true),
      );
      return;
    }
    const markAll = t.closest<HTMLElement>(`${DROP_ITEM}[data-oi-chats='mark-all']`);
    if (markAll) {
      ev.preventDefault();
      ev.stopPropagation();
      if (markAll.classList.contains("v-list-item--disabled")) return;
      if (!writes) return note(doc, markAll, SELECT_MODEL);
      writes.markAllRead().then(
        () => ctx.navigate(listHref(ctx.chat, view)),
        (e) => note(doc, markAll, `Could not mark all as read: ${message(e)}`, true),
      );
    }
  };
  const onInput = (ev: Event) => {
    const input = (ev.target as Element | null)?.closest?.<HTMLInputElement>(`${SEARCH_FORM} input[type='search']`);
    if (!input) return;
    const submit = doc.querySelector<HTMLButtonElement>(`${SEARCH_FORM} button[type='submit']`);
    if (submit) submit.disabled = !input.value.trim();
    clearTimeout(timer);
    // OF's watcher: an emptied input lists every chat again, 1-2 characters wait (Enter still searches), 3+ search.
    timer = setTimeout(() => {
      const q = input.value.trim();
      if (q.length > 0 && q.length < SEARCH_MIN) return;
      if ((q || null) !== view.q) search(input.value, true);
    }, SEARCH_MS);
  };
  const onSubmit = (ev: Event) => {
    const form = (ev.target as Element | null)?.closest?.(SEARCH_FORM);
    if (!form) return;
    ev.preventDefault();
    ev.stopPropagation();
    clearTimeout(timer);
    const input = form.querySelector<HTMLInputElement>("input[type='search']");
    if (input && (input.value.trim() || null) !== view.q) search(input.value, false);
  };
  const onChange = (ev: Event) => {
    const box = ev.target as HTMLInputElement | null;
    const row = box?.closest?.<HTMLElement>(`${FOLDER_ROW}[data-oi-list]`);
    if (!box || !row || box.type !== "checkbox") return;
    const on = box.checked;
    if (!writes) {
      box.checked = !on;
      return note(doc, row, SELECT_MODEL);
    }
    writes.pinFolder(row.dataset.oiList!, on).catch((e) => {
      box.checked = !on;
      note(doc, row, `Could not ${on ? "pin" : "unpin"} the list: ${message(e)}`, true);
    });
  };
  doc.addEventListener("click", onClick, true);
  doc.addEventListener("input", onInput, true);
  doc.addEventListener("submit", onSubmit, true);
  doc.addEventListener("change", onChange, true);
  doc.addEventListener("pointerdown", onDown, true);
  doc.addEventListener("pointermove", onMove, true);
  doc.addEventListener("pointerup", onUp, true);
  doc.addEventListener("pointercancel", reset, true);
  doc.addEventListener("dragstart", onDragStart, true);
  // A finger's horizontal drag is the swipe's; a vertical one still scrolls the list (OF's SwipeOut).
  const touch = doc.createElement("style");
  touch.id = "oi-swipe-touch";
  touch.textContent = ".swipeout { touch-action: pan-y; }";
  doc.getElementById(touch.id)?.remove();
  doc.head?.append(touch);
  return () => {
    touch.remove();
    clearTimeout(timer);
    doc.removeEventListener("pointerdown", onDown, true);
    doc.removeEventListener("pointermove", onMove, true);
    doc.removeEventListener("pointerup", onUp, true);
    doc.removeEventListener("pointercancel", reset, true);
    doc.removeEventListener("dragstart", onDragStart, true);
    doc.removeEventListener("click", onClick, true);
    doc.removeEventListener("input", onInput, true);
    doc.removeEventListener("submit", onSubmit, true);
    doc.removeEventListener("change", onChange, true);
    undoRows?.();
  };
}

/**
 * The chat list's writes for `accountId` (its X-Account-Id), each refreshing what it changed: the chat lists (Messages
 * Pro's useChatList cache), /users/me's unread count, the folders.
 */
export function chatsWrites(accountId: string, qc: QueryClient): ChatsWrites {
  const refresh = () => qc.invalidateQueries({ queryKey: ["chats"] });
  return {
    clear: (id) => relay.delete(`/api/of/v2/chats/${encodeURIComponent(id)}`, { accountId }).then((r) => (void refresh(), r)),
    markAllRead: () =>
      relay.post("/api/of/v2/chats/mark-as-read", undefined, { accountId }).then((r) => {
        void refresh();
        void qc.invalidateQueries({ queryKey: ["of-me", accountId] });
        return r;
      }),
    markRead: (id, read) =>
      (read ? relay.post(`/api/of/v2/chats/${encodeURIComponent(id)}/mark-as-read`, undefined, { accountId }) : relay.delete(`/api/of/v2/chats/${encodeURIComponent(id)}/mark-as-read`, { accountId })).then((r) => {
        void refresh();
        void qc.invalidateQueries({ queryKey: ["of-me", accountId] });
        return r;
      }),
    pinFolder: (id, pinned) =>
      relay.patch(`/api/of/v2/lists/${encodeURIComponent(id)}/pin-chat`, { pinned }, { accountId }).then((r) => {
        void qc.invalidateQueries({ queryKey: ["chat-folders", accountId] });
        return r;
      }),
  };
}

/** A Messages page with the chat list, its dropdown or its folders dialog (not New message): its mirror path, else "". */
const pageOf = (src: string) => /^\/of-mirror\/pages\/(messages\/(?:index|state-[^/]+|chat(?:\/[^/]+)?))\.html$/.exec(src)?.[1] ?? "";

/** The chat list's controls: bind on every frame load and view or data change. */
export function useOfChats(frameRef: RefObject<HTMLIFrameElement | null>, src: string): void {
  const { accountId } = useScope();
  const router = useRouter();
  const qc = useQueryClient();
  const params = useSearchParams();
  const page = pageOf(src);
  const chat = page ? params.get("chat") : null;
  const view = chatsView(params);
  const viewKey = chatsQuery(view);
  const me = useQuery(ofMeQuery(page ? accountId : null)).data as ChatsMe | undefined;
  const folders = useAllChatFolders(page ? accountId : null).data;

  useEffect(() => {
    const frame = frameRef.current;
    if (!frame || !page) return;
    const v = chatsView(new URLSearchParams(viewKey));
    let unbind: (() => void) | undefined;
    const writes = accountId ? chatsWrites(accountId, qc) : null;
    const bind = () => {
      unbind?.();
      const doc = frame.contentDocument;
      if (!doc?.body) return void (unbind = undefined);
      unbind = bindChatList(doc, {
        view: v,
        chat,
        me,
        folders,
        writes,
        confirm: (text) => window.confirm(text),
        navigate: (href, replace) => (replace ? router.replace(href) : router.push(href)),
      });
    };
    if (frame.contentDocument?.readyState === "complete") bind();
    frame.addEventListener("load", bind);
    return () => {
      frame.removeEventListener("load", bind);
      unbind?.();
    };
  }, [frameRef, src, page, accountId, chat, viewKey, me, folders, qc, router]);
}
