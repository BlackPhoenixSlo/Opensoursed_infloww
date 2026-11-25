"use client";


import { useEffect, type RefObject } from "react";
import { useSearchParams } from "next/navigation";

export interface RowTarget {
  name: string;
  handle?: string;
  current?: { rows: string; name: string; cls: string[]; aria?: boolean };
}

export const ROW_TARGETS: Record<string, RowTarget> = {
  "messages/chat": {
    name: ".b-chat__header__title span.g-user-name",
    handle: ".b-chat__message__text-holder a[data-fan]",
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

export function parseRow(value: string | null): Row | null {
  const [name, handle] = (value ?? "").split("|").map((s) => s.trim());
  if (!name) return null;
  return handle ? { name, handle } : { name };
}

export const basePage = (page: string) => page.replace(/\/(?:state|modal)-[^/]+$/, "");

// Here, not in ofMirrorData/ofMirrorPost: they import each other and both read these while loading.
export const VAULT_DIALOG = "new-post/state-vault";
export const HOME_VAULT = "home/state-vault";
export const homeDraft = (accountId: string) => `home:${accountId}`;
export const CHAT_VAULT = "messages/chat/state-vault";
export const MASS_VAULT = "messages/send/state-vault";

const example = (el: HTMLElement) => (el.dataset.oiRow ??= el.textContent ?? "");

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

export function keepQuery(doc: Document, base: string, query: string) {
  const self = `/of-manager/${base}`;
  for (const a of doc.querySelectorAll<HTMLAnchorElement>("a[href^='/of-manager/']")) {
    const href = a.dataset.oiHref ?? a.getAttribute("href") ?? "";
    if (href !== self && !href.startsWith(`${self}/state-`) && !href.startsWith(`${self}/modal-`)) continue;
    a.dataset.oiHref = href;
    a.setAttribute("href", href + query);
  }
}

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
