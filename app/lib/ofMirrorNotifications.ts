"use client";


import { useEffect, type RefObject } from "react";
import { useQuery } from "@tanstack/react-query";
import { useRouter, useSearchParams } from "next/navigation";
import { useScope } from "@/contexts/ScopeContext";
import { plain } from "@/lib/ofMirrorDom";
import { NOTIFICATIONS, notificationsHref, relatedUserOf } from "@/lib/ofMirrorFeedsNotifications";
import { ofMeQuery } from "@/lib/ofMirrorIdentity";
import { bindFeedSearch, type FeedSearchHandlers, feedSearchHandlers, rowsIn } from "@/lib/ofMirrorPost";
import type { SearchUser } from "@/lib/ofMirrorPostDraft";
import { message, note, SELECT_MODEL } from "@/lib/ofMirrorWrites";

const SEARCH_USERS = ".m-notifications-user-search button[aria-label='Search users']";
const USER_FORM = "data-oi-notif-search";
const USER_RESULTS = "oi-notif-users";
const NEW_EVENT = "button[at-attr='add_event_widget']";
const SCHEDULE_POST = "/of-manager/home/state-schedule";
const SEARCH_ICON = (name: string) =>
  `<svg class="m-default-size g-icon" data-icon-name="${name}" aria-hidden="true"><use href="#${name}" xlink:href="#${name}"></use></svg>`;

export interface NotificationsContext {
  page: string;
  relatedUser: string | null;
  handlers: FeedSearchHandlers | null;
  meId?: number | string;
  navigate(href: string): void;
}

export function bindNotifications(doc: Document, ctx: NotificationsContext): () => void {
  const button = doc.querySelector<HTMLElement>(SEARCH_USERS);
  for (const el of [button, doc.querySelector(NEW_EVENT)]) el?.setAttribute("data-oi-wired", "");
  const unbindAside = bindFeedSearch(doc, ctx);
  const win = doc.defaultView;
  let timer = 0;
  let asked = "";
  let form: HTMLFormElement | null = null;
  const input = () => form?.querySelector<HTMLInputElement>("input[type='search']") ?? null;
  const results = () => doc.getElementById(USER_RESULTS);
  const go = (id: string | null) => ctx.navigate(notificationsHref(ctx.page, id));
  const open = (value: string) => {
    if (form) return input()?.focus();
    const header = button?.closest(".g-page__header");
    if (!header) return;
    form = doc.createElement("form");
    form.className = "b-search-form b-form m-default-form m-with-bg";
    form.setAttribute(USER_FORM, "");
    form.setAttribute("data-oi-wired", "");
    form.style.cssText = "display:flex;align-items:center";
    form.innerHTML =
      `<button type="button" class="g-btn m-with-round-hover m-icon m-icon-only m-sm-size m-back-btn" aria-label="Clear">${SEARCH_ICON("icon-close")}</button>` +
      `<input type="search" maxlength="30" spellcheck="false" autocomplete="off" placeholder="Search users" class="b-search-form__input form-control">` +
      `<button type="submit" class="m-with-round-hover g-btn m-icon m-icon-only m-sm-size m-gray" aria-label="Search">${SEARCH_ICON("icon-search")}</button>`;
    input()!.value = value;
    header.after(form);
    if (!value) input()!.focus();
  };
  const draw = (users: SearchUser[]) => {
    results()?.remove();
    const box = doc.createElement("div");
    box.id = USER_RESULTS;
    box.setAttribute("data-oi-wired", "");
    box.className = "b-rows-lists";
    box.style.cssText = "padding:0 0 8px;font-size:14px;line-height:20px";
    if (!users.length) {
      const none = doc.createElement("div");
      none.className = "g-gray-text";
      none.style.cssText = "padding:6px 16px";
      none.textContent = "Nothing found";
      box.append(none);
    }
    for (const u of users) {
      const row = doc.createElement("button");
      row.type = "button";
      row.className = "b-rows-lists__item__text m-with-rectangle-hover g-text-ellipsis";
      row.style.cssText = "display:block;width:100%;padding:6px 16px;text-align:left;background:none;border:0";
      row.setAttribute("data-oi-notif-user", String(u.id));
      row.textContent = `${plain(u.name)}${u.username ? ` @${u.username}` : ""}`.trim() || String(u.id);
      box.append(row);
    }
    form?.after(box);
  };
  const run = (q: string) => {
    const { handlers } = ctx;
    if (!q) return results()?.remove();
    if (!handlers) return note(doc, form ?? button ?? doc.body, SELECT_MODEL);
    asked = q;
    handlers.searchUsers(q).then(
      (r) => asked === q && draw(rowsIn<SearchUser>(r)),
      (e) => asked === q && note(doc, form ?? doc.body, `Could not search: ${message(e)}`, true),
    );
  };
  const onClick = (ev: Event) => {
    const t = ev.target as Element | null;
    if (!t?.closest) return;
    const hit = (sel: string) => t.closest<HTMLElement>(sel);
    let el: HTMLElement | null;
    if ((el = hit(SEARCH_USERS))) return ctx.handlers ? open("") : note(doc, el, SELECT_MODEL);
    if ((el = hit(NEW_EVENT))) return ctx.handlers ? ctx.navigate(SCHEDULE_POST) : note(doc, el, SELECT_MODEL);
    if ((el = hit(`#${USER_RESULTS} [data-oi-notif-user]`))) return go(el.getAttribute("data-oi-notif-user"));
    if (hit(`[${USER_FORM}] button[aria-label='Clear']`)) {
      if (ctx.relatedUser) return go(null);
      win?.clearTimeout(timer);
      asked = "";
      results()?.remove();
      form?.remove();
      form = null;
    }
  };
  const onInput = (ev: Event) => {
    if (!form || ev.target !== input()) return;
    win?.clearTimeout(timer);
    const q = input()!.value.trim();
    timer = win?.setTimeout(() => run(q), 400) ?? 0;
  };
  const onSubmit = (ev: Event) => {
    if (!form || ev.target !== form) return;
    ev.preventDefault();
    win?.clearTimeout(timer);
    const q = input()!.value.trim();
    if (!ctx.handlers) return note(doc, form, SELECT_MODEL);
    if (/^\d+$/.test(q)) return go(q);
    run(q);
  };
  doc.addEventListener("click", onClick);
  doc.addEventListener("input", onInput);
  doc.addEventListener("submit", onSubmit);
  if (ctx.relatedUser) open(ctx.relatedUser);
  return () => {
    win?.clearTimeout(timer);
    doc.removeEventListener("click", onClick);
    doc.removeEventListener("input", onInput);
    doc.removeEventListener("submit", onSubmit);
    results()?.remove();
    form?.remove();
    unbindAside();
  };
}

export function useOfNotifications(frameRef: RefObject<HTMLIFrameElement | null>, src: string): void {
  const { accountId } = useScope();
  const router = useRouter();
  const params = useSearchParams();
  const page = /^\/of-mirror\/pages\/(notifications\/[^/]+)\.html$/.exec(src)?.[1] ?? "";
  const on = Object.hasOwn(NOTIFICATIONS, page);
  const relatedUser = on ? relatedUserOf(params) : null;
  const meId = useQuery(ofMeQuery(on ? accountId : null)).data?.id ?? undefined;

  useEffect(() => {
    const frame = frameRef.current;
    if (!frame || !on) return;
    let unbind: (() => void) | undefined;
    const handlers: NotificationsContext["handlers"] = accountId ? feedSearchHandlers(accountId) : null;
    const bind = () => {
      unbind?.();
      const doc = frame.contentDocument;
      unbind = doc?.body ? bindNotifications(doc, { page, relatedUser, handlers, meId, navigate: (href) => router.push(href) }) : undefined;
    };
    if (frame.contentDocument?.readyState === "complete") bind();
    frame.addEventListener("load", bind);
    return () => {
      frame.removeEventListener("load", bind);
      unbind?.();
    };
  }, [frameRef, src, page, on, accountId, relatedUser, meId, router]);
}
