"use client";


import { useEffect, type RefObject } from "react";
import { useQuery } from "@tanstack/react-query";
import { useRouter, useSearchParams } from "next/navigation";
import { useScope } from "@/contexts/ScopeContext";
import { proxyImage } from "@/lib/mediaUrl";
import { mirrorQuery, rowsOf } from "@/lib/ofMirrorData";
import { own } from "@/lib/ofMirrorDom";
import { closeMenu } from "@/lib/ofMirrorMenu";
import { applyFormsEmpty, applyTagRows, LIST_ROW, markTagTabs, TAG_SORT_LABELS, tagHref, tagRowMenu, tagsRoute, tagViewClick, tagViewOf, type TagView } from "@/lib/ofMirrorPost";
import { note, SELECT_MODEL } from "@/lib/ofMirrorWrites";
import { relay, type TaggedFriendUser, type TaggedFriendUsersResp } from "@/lib/relay";

export const RELEASE_FORMS_PAGE = "release-forms/index";
const SECTION = "release-forms";

export interface ReleaseFormsHandlers {
  navigate(href: string): void;
  toggleTag(body: { entity_id: number; entity_type: string }): Promise<unknown>;
}

export interface ReleaseFormsContext {
  handlers: ReleaseFormsHandlers | null;
  items?: TaggedFriendUser[];
  view: TagView;
  accountId?: string | null;
}

export function bindReleaseForms(doc: Document, ctx: ReleaseFormsContext): () => void {
  const { handlers, items, view } = ctx;
  const root = doc.querySelector<HTMLElement>(".b-release-form");
  if (!root) return () => {};
  const undo = own(() => applyTagRows(doc, (handlers && items) || [], [], (u) => proxyImage(u, ctx.accountId ?? null)));
  const undoEmpty = view.tab === "forms" && handlers && items && !items.length ? applyFormsEmpty(doc, !!view.q) : () => {};
  const tabs = [...root.querySelectorAll<HTMLButtonElement>("button.b-tabs__nav__link")];
  markTagTabs(tabs, view);
  const title = root.querySelector<HTMLElement>(".b-content-filter__title");
  const wasTitle = title?.textContent ?? "";
  if (title) title.textContent = ` ${TAG_SORT_LABELS[view.sort]} `;
  const sortBtn = root.querySelector<HTMLButtonElement>(".b-content-filter button[aria-label='Sort']");
  const searchBtn = root.querySelector<HTMLButtonElement>(".b-content-filter button[aria-label='Search']");
  const field = root.querySelector<HTMLInputElement>(".b-release-form__side-bar input[type='search']");
  if (field && doc.activeElement !== field) field.value = view.q ?? "";
  for (const el of [sortBtn, searchBtn, field, ...root.querySelectorAll(`${LIST_ROW} .m-btn-vertical-dots`)]) el?.setAttribute("data-oi-wired", "");
  const go = (next: TagView) => handlers?.navigate(tagHref(next, SECTION));
  const search = () => go({ ...view, q: field?.value.trim() || null });

  let timer = 0;
  const onInput = (ev: Event) => {
    if (!field || ev.target !== field) return;
    doc.defaultView?.clearTimeout(timer);
    if (!handlers) return note(doc, field, SELECT_MODEL);
    timer = doc.defaultView?.setTimeout(search, 400) ?? 0;
  };
  const onSubmit = (ev: Event) => {
    if (!field || !(ev.target as Element | null)?.contains?.(field)) return;
    ev.preventDefault();
    doc.defaultView?.clearTimeout(timer);
    if (handlers) search();
  };
  const onClick = (ev: MouseEvent) => {
    const t = ev.target as Element | null;
    if (!t?.closest) return;
    if (tagViewClick(doc, ev, { tabs, sortBtn, view, on: !!handlers, go })) return;
    if (searchBtn && t.closest("button") === searchBtn) {
      ev.preventDefault();
      return field?.focus();
    }
    const dots = t.closest<HTMLButtonElement>(`${LIST_ROW} .m-btn-vertical-dots`);
    if (dots) {
      ev.preventDefault();
      ev.stopPropagation();
      return tagRowMenu(doc, dots, handlers);
    }
    if (t.closest(LIST_ROW)) ev.preventDefault();
  };
  doc.addEventListener("click", onClick);
  doc.addEventListener("input", onInput);
  doc.addEventListener("submit", onSubmit);
  return () => {
    doc.defaultView?.clearTimeout(timer);
    doc.removeEventListener("click", onClick);
    doc.removeEventListener("input", onInput);
    doc.removeEventListener("submit", onSubmit);
    if (title) title.textContent = wasTitle;
    closeMenu(doc);
    undoEmpty();
    undo();
  };
}

export function useOfReleaseForms(frameRef: RefObject<HTMLIFrameElement | null>, src: string): void {
  const { accountId } = useScope();
  const router = useRouter();
  const params = useSearchParams();
  const on = src === `/of-mirror/pages/${RELEASE_FORMS_PAGE}.html`;
  const query = on ? params.toString() : "";
  const data = useQuery(mirrorQuery<TaggedFriendUsersResp>(accountId, tagsRoute(tagViewOf(new URLSearchParams(query))), on)).data;
  const items = accountId ? (data?.items ?? rowsOf<TaggedFriendUser>(data)) : undefined;

  useEffect(() => {
    const frame = frameRef.current;
    if (!frame || !on) return;
    let unbind: (() => void) | undefined;
    const bind = () => {
      unbind?.();
      const doc = frame.contentDocument;
      const handlers: ReleaseFormsHandlers | null = accountId
        ? {
            navigate: (href) => router.push(href),
            toggleTag: (body) => relay.patch("/api/of/v2/release-forms/toggle-show", body, { accountId }),
          }
        : null;
      unbind = doc?.body ? bindReleaseForms(doc, { handlers, items, view: tagViewOf(new URLSearchParams(query)), accountId }) : undefined;
    };
    if (frame.contentDocument?.readyState === "complete") bind();
    frame.addEventListener("load", bind);
    return () => {
      frame.removeEventListener("load", bind);
      unbind?.();
    };
  }, [frameRef, src, on, accountId, router, items, query]);
}
