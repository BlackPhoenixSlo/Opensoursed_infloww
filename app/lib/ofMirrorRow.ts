"use client";

/**
 * Per-row targets. Every chat, vault list and collections user-list row opens
 * the one mirrored example page (messages/chat, vault/list,
 * collections/user-lists/list); scripts/of-mirror.mjs gives each row's link
 * `?row=<name>|<handle>` (what the row shows). On the target page, and on its
 * state-* and modal-* pages, this puts that row where the example is shown:
 * the header or list title, the frame's <title>, the chat partner's @handle
 * mentions, and the list's current-row mark. The page's links to itself and to
 * those subpages keep the query, so the row survives opening a dialog.
 * The query never reaches the page lookup: the route matches on the path alone,
 * and the frame's src has no query.
 * With a single model selected, useOfData replaces the example rows with real
 * ones (their links carry ?chat= / ?list= instead); this then covers the
 * all-models scope and a failed relay fetch, where the examples stay.
 */

import { useEffect, type RefObject } from "react";
import { useSearchParams } from "next/navigation";

export interface RowTarget {
  /** The elements that show the example's name. */
  name: string;
  /** Elements that show the example's @handle: only those with the name's (closest) data-fan. */
  handle?: string;
  /** The list's rows: `rows`, each named by its `name` element; the open one carries `cls` (and aria-current, with `aria`). */
  current?: { rows: string; name: string; cls: string[]; aria?: boolean };
}

/** Target page (path under of-mirror/pages, no ".html") -> where it shows the example. */
export const ROW_TARGETS: Record<string, RowTarget> = {
  "messages/chat": {
    name: ".b-chat__header__title span.g-user-name",
    handle: ".b-chat__message__text-holder a[data-fan]", // the partner's @mentions in the messages
    current: { rows: ".b-chats__item", name: ".g-user-name", cls: ["current"] },
  },
  "vault/list": {
    name: ".l-main-content .g-page-title > span",
    current: { rows: "a.b-rows-lists__item__text", name: ".b-rows-lists__item__name", cls: ["m-current", "router-link-active"], aria: true },
  },
  "collections/user-lists/list": {
    name: ".l-main-content .g-page-title > span, .l-main-content a[aria-current='page'] .b-list-titles__item__text",
    current: { rows: "a.b-rows-lists__item__text", name: ".b-rows-lists__item__name", cls: ["m-current", "router-link-active"], aria: true },
  },
};

export interface Row {
  name: string;
  handle?: string;
}

/** "Fan 3|fan3" -> { name: "Fan 3", handle: "fan3" }; null for a missing or empty value. */
export function parseRow(value: string | null): Row | null {
  const [name, handle] = (value ?? "").split("|").map((s) => s.trim());
  if (!name) return null;
  return handle ? { name, handle } : { name };
}

/** The target page a page belongs to: itself, or the page of a state-* / modal-* subpage. */
export const basePage = (page: string) => page.replace(/\/(?:state|modal)-[^/]+$/, "");

/**
 * New post's "Add media from vault" dialog page (ofMirrorData's vault data, ofMirrorPost's binder). Kept here, outside
 * those two modules' import cycle, because both read it while loading.
 */
export const VAULT_DIALOG = "new-post/state-vault";
/** The same dialog over Home (Home's composer posts in place): New post's data and binder, with Home's own Post draft. */
export const HOME_VAULT = "home/state-vault";
/** Home's Post draft id, in place of the account id in ofMirrorPost's draft key: Home's composer and New post's keep their own drafts. */
export const homeDraft = (accountId: string) => `home:${accountId}`;
/** A chat's "Add media from vault" dialog page (ofMirrorData's vault data, ofMirrorChat's binder); kept here for the same reason. */
export const CHAT_VAULT = "messages/chat/state-vault";
/** New message's "Add media from vault" dialog page: a chat's, its picks the Mass draft's. */
export const MASS_VAULT = "messages/send/state-vault";

/** `el`'s text as captured, remembered the first time it is changed. */
const example = (el: HTMLElement) => (el.dataset.oiRow ??= el.textContent ?? "");

/** Move the current-row mark to the rows named `name`; the example's rows keep it for null or no match. */
function markCurrent(doc: Document, cur: NonNullable<RowTarget["current"]>, name: string | null) {
  const rows = [...doc.querySelectorAll<HTMLElement>(cur.rows)];
  let own = rows.filter((r) => r.dataset.oiCurrent !== undefined);
  if (!own.length) {
    own = rows.filter((r) => r.classList.contains(cur.cls[0]));
    for (const r of own) r.dataset.oiCurrent = "";
  }
  const named = name ? rows.filter((r) => r.querySelector(cur.name)?.textContent?.trim() === name) : [];
  const target = named.length ? named : own;
  for (const r of rows) {
    const on = target.includes(r);
    for (const c of cur.cls) r.classList.toggle(c, on);
    if (cur.aria) {
      if (on) r.setAttribute("aria-current", "page");
      else r.removeAttribute("aria-current");
    }
  }
}

/** Links to the page itself and its state-* / modal-* subpages carry `query` ("" restores them). */
export function keepQuery(doc: Document, base: string, query: string) {
  const self = `/of-manager/${base}`;
  for (const a of doc.querySelectorAll<HTMLAnchorElement>("a[href^='/of-manager/']")) {
    const href = a.dataset.oiHref ?? a.getAttribute("href") ?? "";
    if (href !== self && !href.startsWith(`${self}/state-`) && !href.startsWith(`${self}/modal-`)) continue;
    a.dataset.oiHref = href;
    a.setAttribute("href", href + query);
  }
}

/** Show `row` on `page` (a target page or one of its subpages) in `doc`, or the example again for null (the frame stays loaded between rows). */
export function applyRow(doc: Document, page: string, row: Row | null): void {
  const base = basePage(page);
  if (!Object.hasOwn(ROW_TARGETS, base)) return;
  const t = ROW_TARGETS[base];
  const names = [...doc.querySelectorAll<HTMLElement>(t.name)];
  for (const el of names) {
    const was = example(el);
    el.textContent = row ? row.name : was;
  }
  const title = doc.querySelector("title");
  // The title keeps its section part: "Messages: Chat" -> "Messages: Fan 3".
  if (title) title.textContent = row ? example(title).replace(/[^:›]+$/, ` ${row.name}`) : example(title);
  const fan = names[0]?.closest("[data-fan]")?.getAttribute("data-fan");
  if (t.handle && fan) {
    for (const el of doc.querySelectorAll<HTMLElement>(t.handle)) {
      if (el.getAttribute("data-fan") !== fan || !example(el).trim().startsWith("@")) continue;
      el.textContent = row?.handle ? `@${row.handle}` : example(el);
    }
  }
  if (t.current) markCurrent(doc, t.current, row?.name ?? null);
  keepQuery(doc, base, row ? `?row=${[row.name, ...(row.handle ? [row.handle] : [])].map(encodeURIComponent).join("|")}` : "");
}

/** On a row target page (or its subpage), show the row of the URL's ?row= query, on every frame load and query change. */
export function useOfRow(frameRef: RefObject<HTMLIFrameElement | null>, src: string): void {
  const value = useSearchParams().get("row");
  const page = /^\/of-mirror\/pages\/(.+)\.html$/.exec(src)?.[1] ?? "";

  useEffect(() => {
    const frame = frameRef.current;
    if (!frame || !Object.hasOwn(ROW_TARGETS, basePage(page))) return;
    const row = parseRow(value);
    const apply = () => {
      const doc = frame.contentDocument;
      if (doc?.body) applyRow(doc, page, row);
    };
    if (frame.contentDocument?.readyState === "complete") apply();
    frame.addEventListener("load", apply);
    return () => frame.removeEventListener("load", apply);
  }, [frameRef, page, value]);
}
