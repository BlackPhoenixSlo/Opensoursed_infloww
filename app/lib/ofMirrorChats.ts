"use client";


import { useEffect, type RefObject } from "react";
import { useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { useRouter, useSearchParams } from "next/navigation";
import { useScope } from "@/contexts/ScopeContext";
import { relay } from "@/lib/relay";
import { own } from "@/lib/ofMirrorDom";
import { applyListRows, folderSortOf, showListSort, sortFolders, withListSort, type FolderSort } from "@/lib/ofMirrorDataLists";
import { ofMeQuery, type OfMe } from "@/lib/ofMirrorIdentity";
import { message, note, SELECT_MODEL } from "@/lib/ofMirrorWrites";
import { useAllChatFolders, type ChatFolder } from "@/hooks/useChatFolders";
import type { ChatListFilter, ChatListOrder } from "@/hooks/useChatList";

export const LIST_PAGE = "/of-manager/messages";
export const CHAT_PAGE = "/of-manager/messages/chat";
export const DROPDOWN_PAGE = "/of-manager/messages/state-filter-dropdown";
export const FOLDERS_PAGE = "/of-manager/messages/state-folders";
// The confirm text (message.confirm_delete_chat_desc) is not in OF's bundle: assumed.
export const CLEAR_CONFIRM = "Clear messages? This cannot be undone.";
export const SEARCH_MS = 500;
// The fewest characters OF's search lists on its own (below it waits for Enter).
export const SEARCH_MIN = 3;

export const TABS = ["pinned", "priority", "unread", "who_tipped"] as const;
export type ChatsTab = (typeof TABS)[number];
export const DROP_FILTERS = ["priority", "unread", "unread_tips"] as const;
export type ChatsDropFilter = (typeof DROP_FILTERS)[number];

export interface ChatsView {
  tab: ChatsTab | null;
  folder: string | null;
  filter: ChatsDropFilter | null;
  order: ChatListOrder;
  q: string | null;
}

const isOf = <T extends string>(list: readonly T[], v: string | null): v is T => v !== null && (list as readonly string[]).includes(v);

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

export const filterGroupShown = (v: ChatsView) => !v.tab || v.tab === "who_tipped";
export const orderGroupShown = (v: ChatsView) => v.tab !== "pinned";

export function chatsRequest(v: ChatsView): { filter: ChatListFilter | null; listId: string | null; order: ChatListOrder; query: string | null } {
  const dd = filterGroupShown(v) && !(v.tab === "who_tipped" && v.filter === "unread_tips") ? v.filter : null;
  const filter: ChatListFilter | null = v.tab === "who_tipped" && dd === "unread" ? "unread_tips" : (v.tab ?? dd);
  return { filter, listId: v.tab ? null : v.folder, order: v.order, query: v.q };
}

export function chatsQuery(v: ChatsView): string {
  const q = new URLSearchParams();
  if (v.tab) q.set("tab", v.tab);
  if (v.folder) q.set("folder", v.folder);
  if (v.filter) q.set("filter", v.filter);
  if (v.order === "old") q.set("order", "old");
  if (v.q) q.set("q", v.q);
  return q.toString();
}

export function chatsHref(path: string, chat: string | null, v: ChatsView): string {
  const parts = [chat ? `chat=${encodeURIComponent(chat)}` : "", chatsQuery(v)].filter(Boolean);
  return parts.length ? `${path}?${parts.join("&")}` : path;
}

export const listHref = (chat: string | null, v: ChatsView) => chatsHref(chat ? CHAT_PAGE : LIST_PAGE, chat, v);


export const SELECT_ITEM = "[data-oi-select]";
const HEADER = ".b-chats__header";
const ROW = ".b-chats__item[data-oi-chat]";
const ROWS = ".b-chats__list-dialogues";

export function selectHref(chat: string | null, v: ChatsView, on: boolean): string {
  const href = listHref(chat, v);
  return on ? `${href}${href.includes("?") ? "&" : "?"}select=1` : href;
}

export function pickAll(picked: ReadonlySet<string>, ids: readonly string[]): Set<string> {
  return ids.every((id) => picked.has(id)) ? new Set() : new Set(ids);
}

export function selectMode(doc: Document, leave: () => void): () => void {
  const header = doc.querySelector<HTMLElement>(HEADER);
  if (!header) return () => {};
  const picked = new Set<string>();
  const ids = () => [...doc.querySelectorAll<HTMLElement>(ROW)].map((r) => r.dataset.oiChat!);
  const hidden = [...header.children].filter((c): c is HTMLElement => c instanceof HTMLElement).map((c) => [c, c.style.display] as const);
  for (const [c] of hidden) c.style.display = "none";

  const back = header.querySelector("a[aria-label='Back']");
  const bar = doc.createElement("div");
  bar.dataset.oiSelectBar = "";
  bar.style.cssText = "display:flex;align-items:center;flex:1 1 auto;min-width:0";
  const cancel = doc.createElement("button");
  cancel.type = "button";
  cancel.className = back?.className ?? "g-page__header__btn g-btn m-with-round-hover m-icon m-icon-only m-sm-size m-default-color";
  cancel.setAttribute("aria-label", "Cancel");
  cancel.setAttribute("data-oi-wired", "");
  for (const icon of back?.querySelectorAll("svg") ?? []) cancel.append(icon.cloneNode(true));
  const group = doc.createElement("div");
  group.className = "b-btns-group m-move-right";
  const text = (label: string, wired: boolean) => {
    const b = doc.createElement("button");
    b.type = "button";
    b.className = "g-btn m-flat m-sm-size m-no-uppercase";
    b.textContent = label;
    if (wired) b.setAttribute("data-oi-wired", "");
    return b;
  };
  const all = text("Select all", true);
  const del = text("Delete", false);
  del.dataset.oiSelectDelete = "";
  group.append(all, del);
  bar.append(cancel, group);
  header.append(bar);

  const mark = () => {
    for (const row of doc.querySelectorAll<HTMLElement>(ROW)) {
      let box = row.querySelector<HTMLInputElement>("[data-oi-select-box]");
      if (!box) {
        box = doc.createElement("input");
        box.type = "checkbox";
        box.dataset.oiSelectBox = "";
        box.setAttribute("data-oi-wired", "");
        box.tabIndex = -1;
        box.style.cssText = "flex:0 0 auto;margin:0 12px 0 0;width:18px;height:18px;accent-color:#00aff0;pointer-events:none";
        row.prepend(box);
      }
      box.checked = picked.has(row.dataset.oiChat!);
    }
    const label = ids().length > 0 && ids().every((id) => picked.has(id)) ? "Deselect" : "Select all";
    if (all.textContent !== label) all.textContent = label;
  };
  mark();
  const list = doc.querySelector(ROWS) ?? doc.querySelector(".b-chats__conversations-list");
  const win = doc.defaultView;
  const watch = list && win ? new win.MutationObserver(mark) : null;
  if (watch && list) watch.observe(list, { childList: true, subtree: true });

  const onClick = (ev: MouseEvent) => {
    const t = ev.target as Element | null;
    if (!t?.closest) return;
    if (t.closest("[data-oi-select-bar] button[aria-label='Cancel']")) {
      ev.preventDefault();
      return leave();
    }
    if (t.closest("[data-oi-select-bar] button") === all) {
      ev.preventDefault();
      const next = pickAll(picked, ids());
      picked.clear();
      for (const id of next) picked.add(id);
      return mark();
    }
    const row = t.closest<HTMLElement>(ROW);
    if (!row) return;
    ev.preventDefault();
    ev.stopImmediatePropagation();
    const id = row.dataset.oiChat!;
    if (!picked.delete(id)) picked.add(id);
    mark();
  };
  doc.addEventListener("click", onClick, true);
  return () => {
    doc.removeEventListener("click", onClick, true);
    watch?.disconnect();
    bar.remove();
    for (const box of doc.querySelectorAll("[data-oi-select-box]")) box.remove();
    for (const [c, was] of hidden) c.style.display = was;
  };
}

export function folderSortHref(chat: string | null, v: ChatsView, sorted: FolderSort): string {
  return withListSort(chatsHref(FOLDERS_PAGE, chat, v), sorted);
}

export const counter = (n: number | null | undefined) => (!n || n < 0 ? "" : n > 999 ? "999+" : String(n));

export type ChatsMe = Pick<OfMe, "chatMessagesCount"> & { countPinnedChat?: number | null; countPriorityChat?: number | null; unreadTips?: number | null; tipsEnabled?: boolean | null };

export interface ChatsWrites {
  clear(chat: string): Promise<unknown>;
  markAllRead(): Promise<unknown>;
  pinFolder(id: string, pinned: boolean): Promise<unknown>;
  markRead(chat: string, read: boolean): Promise<unknown>;
}

export interface ChatsContext {
  view: ChatsView;
  chat: string | null;
  me?: ChatsMe;
  folders?: ChatFolder[];
  navigate(href: string, replace?: boolean): void;
  select: boolean;
  folderSort: FolderSort;
  writes: ChatsWrites | null;
  confirm(text: string): boolean;
}

const BAR = ".b-chats__conversations-list .b-tabs__nav";
const TAB = "button[data-oi-tab]";
const DROP_ITEM = "[data-oi-chats]";
const SORT_MORE = "[at-attr='sort_dropdown'] > button";
const SEARCH_BTN = ".b-chats__header button[at-attr='search_header_btn']";
const SEARCH_FORM = ".b-chats__header .b-chat__search-form";
const CLEAR_BTN = ".b-chats__item__btn-clear";
const FOLDER_ROW = ".modal .b-rows-lists label.b-rows-lists__item.m-collection-item";
const SWIPE_ROW = ".swipeout";
export const SWIPE_PX = 100;

const show = (el: HTMLElement | null | undefined, on: boolean) => {
  if (el) el.style.display = on ? "" : "none";
};

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
    btn.disabled = !f.usersCount;
    markTab(doc, btn, !view.tab && view.folder === String(f.id), "");
    at ? at.before(item) : li.parentElement?.appendChild(item);
  }
}

function carryView(doc: Document, ctx: ChatsContext) {
  const query = [ctx.chat ? `chat=${encodeURIComponent(ctx.chat)}` : "", chatsQuery(ctx.view)].filter(Boolean).join("&");
  const onState = !!doc.querySelector(`${DROP_ITEM}, ${FOLDER_ROW}`);
  for (const a of doc.querySelectorAll<HTMLAnchorElement>("a[href^='/of-manager/messages']")) {
    const href = a.dataset.oiHref ?? a.getAttribute("href") ?? "";
    if (a.closest(DROP_ITEM)) continue;
    const to = href === DROPDOWN_PAGE || href === FOLDERS_PAGE ? (query ? `${href}?${query}` : href) : onState && href === LIST_PAGE ? listHref(ctx.chat, ctx.view) : null;
    if (to === null) continue;
    a.dataset.oiHref = href;
    a.setAttribute("href", to);
  }
}

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
      const off = !((me?.chatMessagesCount ?? 0) > 0);
      item.classList.toggle("v-list-item--disabled", off);
      item.setAttribute("aria-disabled", String(off));
      item.toggleAttribute("data-oi-wired", !off);
      link?.remove();
    }
  }
}

function applyTitle(doc: Document, v: ChatsView) {
  const title = doc.querySelector<HTMLElement>(".b-chats__conversations-list .b-content-filter__title");
  if (title) title.textContent = v.order === "old" ? "Oldest First" : "Newest First";
}

function applySearch(doc: Document, v: ChatsView, open: boolean) {
  const form = doc.querySelector<HTMLFormElement>(SEARCH_FORM);
  if (!form) return;
  const input = form.querySelector<HTMLInputElement>("input[type='search']");
  doc.querySelector(".b-chats__header")?.classList.toggle("m-search-form-visible", open);
  if (input && doc.activeElement !== input) input.value = v.q ?? "";
  const submit = form.querySelector<HTMLButtonElement>("button[type='submit']");
  if (submit) submit.disabled = !(input?.value.trim());
}

export function bindChatList(doc: Document, ctx: ChatsContext): () => void {
  const { view, writes } = ctx;
  applyTabs(doc, ctx);
  applyTitle(doc, view);
  applyDropdown(doc, ctx);
  carryView(doc, ctx);
  applySearch(doc, view, !!view.q);
  for (const el of doc.querySelectorAll(`${TAB}, ${SEARCH_BTN}, ${SEARCH_FORM} button`)) el.setAttribute("data-oi-wired", "");
  doc.querySelector(SORT_MORE)?.setAttribute("data-oi-wired", "");
  doc.querySelector(SELECT_ITEM)?.setAttribute("data-oi-wired", "");
  const undoSelect = ctx.select ? selectMode(doc, () => ctx.navigate(selectHref(ctx.chat, view, false))) : null;

  const pinnable = ctx.folders?.filter((f) => f.canPinnedToChat !== false);
  const sorted = ctx.folderSort;
  const sortBtn = doc.querySelector(FOLDER_ROW) ? doc.querySelector<HTMLButtonElement>(".modal button[aria-label='Sort']") : null;
  sortBtn?.setAttribute("data-oi-wired", "");
  const undoRows = pinnable && doc.querySelector(FOLDER_ROW)
    ? own(() => applyListRows(doc, sortFolders(pinnable, sorted.sort, sorted.order).map((f) => ({ id: f.id, name: f.name, usersCount: f.usersCount })), pinnable.filter((f) => f.isPinnedToChat).map((f) => String(f.id)), { rows: FOLDER_ROW, empty: ".modal [data-oi-empty]" }))
    : null;

  let timer: ReturnType<typeof setTimeout> | undefined;
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
  // No capture on pointerdown: it retargets a plain click to the .swipeout box, so the row's link would not open the chat. Taken once the drag moves.
  const onDown = (ev: PointerEvent) => {
    const t = ev.target as Element | null;
    if (ev.button !== 0 || !t?.closest || t.closest(`${CLEAR_BTN}, .g-avatar`)) return;
    const box = t.closest<HTMLElement>(SWIPE_ROW);
    const row = box?.querySelector<HTMLElement>("[data-oi-chat]");
    if (!box || !row) return;
    drag = { x: ev.clientX, y: ev.clientY, dx: 0, moving: false, box, row, id: row.dataset.oiChat! };
  };
  const reset = () => {
    const d = drag;
    drag = null;
    if (d?.moving) slide(d.box, 0, true);
  };
  const onMove = (ev: PointerEvent) => {
    if (!drag) return;
    if (ev.buttons === 0) return reset();
    const dx = Math.min(0, ev.clientX - drag.x);
    if (!drag.moving) {
      if (Math.abs(ev.clientY - drag.y) > Math.abs(ev.clientX - drag.x) && Math.abs(ev.clientY - drag.y) > 6) return void (drag = null);
      if (dx > -6) return;
      drag.moving = true;
      try {
        drag.box.setPointerCapture?.(ev.pointerId);
      } catch {
      }
    }
    drag.dx = dx;
    slide(drag.box, dx, false);
  };
  const onUp = () => {
    const d = drag;
    drag = null;
    if (!d?.moving) return;
    swallow = true;
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
          if (ctx.chat === id) ctx.navigate(listHref(null, view), true);
        },
        (e) => note(doc, x, `Could not clear messages: ${message(e)}`, true),
      );
      return;
    }
    if (t.closest(SELECT_ITEM)) {
      ev.preventDefault();
      return ctx.navigate(selectHref(ctx.chat, view, true));
    }
    if (sortBtn && t.closest("button") === sortBtn) {
      ev.preventDefault();
      showListSort(doc, sortBtn, sorted, (s) => ctx.navigate(folderSortHref(ctx.chat, view, s)));
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
    undoSelect?.();
  };
}

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

const pageOf = (src: string) => /^\/of-mirror\/pages\/(messages\/(?:index|state-[^/]+|chat(?:\/[^/]+)?))\.html$/.exec(src)?.[1] ?? "";

export function useOfChats(frameRef: RefObject<HTMLIFrameElement | null>, src: string): void {
  const { accountId } = useScope();
  const router = useRouter();
  const qc = useQueryClient();
  const params = useSearchParams();
  const page = pageOf(src);
  const chat = page ? params.get("chat") : null;
  const view = chatsView(params);
  const viewKey = chatsQuery(view);
  const select = !!page && params.get("select") === "1";
  const { sort: fsort, order: forder } = folderSortOf(params);
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
        select,
        folderSort: { sort: fsort, order: forder },
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
  }, [frameRef, src, page, accountId, chat, viewKey, select, fsort, forder, me, folders, qc, router]);
}
