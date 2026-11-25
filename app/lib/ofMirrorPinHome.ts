"use client";


import { useEffect, type RefObject } from "react";
import { useQuery } from "@tanstack/react-query";
import { useRouter, useSearchParams } from "next/navigation";
import { useScope } from "@/contexts/ScopeContext";
import { mirrorQuery, USER_LISTS } from "@/lib/ofMirrorDataQueries";
import { folderSortOf, listSubline, showListSort, sortFolders, withListSort, type FolderSort, type UserList } from "@/lib/ofMirrorDataLists";
import { rowsOf } from "@/lib/ofMirrorPaging";
import { own, setAttr, setText, track } from "@/lib/ofMirrorDom";
import { message, note, SELECT_MODEL } from "@/lib/ofMirrorWrites";

export const PIN_PAGE = "/of-manager/home/state-feed-tabs-edit";
export const PIN_EMPTY_ALL = "Select a model to see its lists";
const SORT = ".modal button[aria-label='Sort']";
const ROWS = ".modal .b-rows-lists";

export type PinList = UserList & { canPinnedToFeed?: boolean; isPinnedToFeed?: boolean };

export interface PinHomeContext {
  scoped: boolean;
  lists: PinList[] | undefined;
  error: string | null;
  sort: FolderSort;
  navigate(href: string): void;
}

export function pinHomeRows(lists: readonly PinList[] | undefined, sorted: FolderSort): PinList[] | undefined {
  return lists && sortFolders(lists.filter((l) => l.canPinnedToFeed !== false), sorted.sort, sorted.order);
}

export const pinHomeHref = (sorted: FolderSort) => withListSort(PIN_PAGE, sorted);

export function pinHomeStatus(s: { scoped: boolean; rows: readonly unknown[] | undefined; error: string | null }): string | null {
  if (!s.scoped) return PIN_EMPTY_ALL;
  if (s.error !== null) return `Could not load: ${s.error}`;
  if (!s.rows) return "Loading…";
  return s.rows.length ? null : "Nothing found";
}

const ROW =
  '<label data-v-e201f478="" data-v-50dfc750="" class="b-rows-lists__item m-checkbox-row m-collection-item g-radio-container m-sm-height" data-v-62b39f36="">' +
  '<input type="checkbox" role="checkbox" tabindex="0" name="" class="b-input-radio" value="false"><span class="b-input-radio__label">' +
  '<svg data-icon-name="icon-done" aria-hidden="true" class="g-icon"><use href="#icon-done" xlink:href="#icon-done"></use></svg><span class="b-input-ripple"></span></span>' +
  '<div data-v-50dfc750="" class="b-rows-lists__item__text m-reset-wcag-link-focus m-complex-structure"><div at-attr="lists_item" class="b-rows-lists__item__name g-text-ellipsis pb-0"></div>' +
  '<div class="b-rows-lists__item__subline"><div data-v-47d1c884="" class="b-content-inside-thumbs mw-100 g-text-ellipsis m-exception-not-last g-gray-text" at-attr="user_count"></div></div></div></label>';
const DOT = "b-content-inside-thumbs__item m-collection-item b-dot-item m-point-order-exception";

function row(doc: Document, l: PinList): HTMLElement {
  const holder = doc.createElement("div");
  holder.innerHTML = ROW;
  const el = holder.firstElementChild as HTMLElement;
  el.setAttribute("data-oi-list", String(l.id));
  el.querySelector<HTMLInputElement>("input")!.checked = !!l.isPinnedToFeed;
  el.querySelector(".b-rows-lists__item__name")!.textContent = ` ${l.name ?? ""} `;
  const sub = el.querySelector(".b-content-inside-thumbs")!;
  for (const part of listSubline(l)) {
    const s = doc.createElement("span");
    s.setAttribute("data-v-47d1c884", "");
    s.className = DOT;
    s.textContent = ` ${part} `;
    sub.append(s);
  }
  return el;
}

export function bindPinHome(doc: Document, ctx: PinHomeContext): () => void {
  const list = doc.querySelector(ROWS);
  const btn = doc.querySelector<HTMLButtonElement>(SORT);
  if (!list || !btn) return () => {};
  const empty = list.querySelector<HTMLElement>(":scope > [data-oi-empty]");
  const rows = ctx.scoped ? pinHomeRows(ctx.lists, ctx.sort) : undefined;
  const status = pinHomeStatus({ scoped: ctx.scoped, rows, error: ctx.error });
  const undo = own(() => {
    setAttr(doc, btn, "data-oi-wired", "");
    for (const l of rows ?? []) {
      const el = row(doc, l);
      list.insertBefore(el, empty ?? list.firstChild);
      track(doc, () => el.remove());
    }
    const text = empty?.querySelector(":scope > span");
    if (!empty || !text) return;
    if (status === null) setAttr(doc, empty, "style", `${empty.getAttribute("style") ?? ""};display:none`);
    else setText(doc, text, status);
  });
  const onClick = (ev: MouseEvent) => {
    const t = ev.target as Element | null;
    if (!t?.closest || t.closest("button") !== btn) return;
    ev.preventDefault();
    if (!ctx.scoped) return note(doc, btn, SELECT_MODEL);
    const sorted = ctx.sort;
    showListSort(doc, btn, sorted, (s) => ctx.navigate(pinHomeHref(s)));
  };
  doc.addEventListener("click", onClick);
  return () => {
    doc.removeEventListener("click", onClick);
    undo();
  };
}

const isPage = (src: string) => src === "/of-mirror/pages/home/state-feed-tabs-edit.html";

export function useOfPinHome(frameRef: RefObject<HTMLIFrameElement | null>, src: string): void {
  const { accountId } = useScope();
  const router = useRouter();
  const params = useSearchParams();
  const page = isPage(src);
  const { sort: fsort, order: forder } = folderSortOf(params);
  const lists = useQuery(mirrorQuery(accountId, USER_LISTS, page));
  const rows = rowsOf<PinList>(lists.data);
  const error = lists.error ? message(lists.error) : null;

  useEffect(() => {
    const frame = frameRef.current;
    if (!frame || !page) return;
    let unbind: (() => void) | undefined;
    const bind = () => {
      unbind?.();
      const doc = frame.contentDocument;
      if (!doc?.body) return void (unbind = undefined);
      unbind = bindPinHome(doc, { scoped: !!accountId, lists: rows, error, sort: { sort: fsort, order: forder }, navigate: (href) => router.push(href) });
    };
    if (frame.contentDocument?.readyState === "complete") bind();
    frame.addEventListener("load", bind);
    return () => {
      frame.removeEventListener("load", bind);
      unbind?.();
    };
  }, [frameRef, page, accountId, rows, error, fsort, forder, router]);
}
