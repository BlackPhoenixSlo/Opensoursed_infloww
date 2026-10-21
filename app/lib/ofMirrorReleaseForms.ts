"use client";

/**
 * Release forms (release-forms/index; OF's ReleaseFormsStorage, /my/release-forms): the tag dialog's lists as a page, its
 * view in the app URL (ofMirrorPost's TagView: ?tab= ?q= ?sort= ?order= ?filter=). The rows are the Relay's list for the
 * tab (tagsRoute: Tag user is OF's tagged-friend-users, Release form OF's release-forms, the same module the dialog reads)
 * with a model, else none (the captured example never shows); an empty Release form tab shows OF's placeholder. OF's tools:
 * - Tag user / Release form: the page on that tab;
 * - the sidebar search ("Search release form or user..."): typing stops for 400 ms (or Enter), the page with ?q=; the
 *   filter's Search icon focuses it;
 * - Sort: OF's menu (All / Pending, Recent / Name, Ascending / Descending), the filter's title naming the sort;
 * - a row's More: Hide from list / Show in list (OF's toggle-show), then OF's toast (ofMirrorPost's tagRowMenu).
 * The tabs and Sort are the tag dialog's (ofMirrorPost's markTagTabs, tagViewClick). A row's checkbox picks nothing (no
 * post to tag here). All models: the first model shows (useStandIn); with none, each tool says "Select a model". Mentions
 * (Notifications' Tags tab), and Create new release form and Create new invitation link (disabled: the page's own
 * requests were never captured), are the generator's.
 */

import { useEffect, type RefObject } from "react";
import { useQuery } from "@tanstack/react-query";
import { useRouter, useSearchParams } from "next/navigation";
import { useScope } from "@/contexts/ScopeContext";
import { proxyImage } from "@/lib/mediaUrl";
import { mirrorQuery, own, rowsOf } from "@/lib/ofMirrorData";
import { closeMenu } from "@/lib/ofMirrorMenu";
import { applyFormsEmpty, applyTagRows, LIST_ROW, markTagTabs, TAG_SORT_LABELS, tagHref, tagRowMenu, tagsRoute, tagViewClick, tagViewOf, type TagView } from "@/lib/ofMirrorPost";
import { note, SELECT_MODEL } from "@/lib/ofMirrorWrites";
import { relay, type TaggedFriendUser, type TaggedFriendUsersResp } from "@/lib/relay";

export const RELEASE_FORMS_PAGE = "release-forms/index";
const SECTION = "release-forms";

export interface ReleaseFormsHandlers {
  navigate(href: string): void;
  /** PATCH /api/of/v2/release-forms/toggle-show {entity_id, entity_type}. */
  toggleTag(body: { entity_id: number; entity_type: string }): Promise<unknown>;
}

/** `handlers` null: no model (nothing is sent). `items`: the tab's Relay rows; undefined while loading or after a failure. */
export interface ReleaseFormsContext {
  handlers: ReleaseFormsHandlers | null;
  items?: TaggedFriendUser[];
  view: TagView;
  accountId?: string | null;
}

/** Wire the Release forms page in `doc` for `ctx`. Returns an unbind, which puts the example back. */
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
  // A rebind after typing (the app URL took ?q=) leaves the field as the operator has it.
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
    // A row's checkbox: nothing to pick on this page (no post to tag).
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

/** On Release forms: the model's rows for the view in the app URL (a selected model, or All's stand-in), bound on every frame load. */
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
