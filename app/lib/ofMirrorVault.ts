"use client";

/**
 * The Vault page of the OF mirror (vault/index and its state-* pages) against the relay.
 *
 * The page's view lives in the app URL: ?list= (the open folder, see ofMirrorData), ?type= (the All / Photo / GIF /
 * Video / Audio tabs), ?field= and ?sort= (the media sort dropdown: OF's `field` recent | most-liked | highest-tips |
 * buyers and `sort` asc | desc), ?date= (its "Go to date": OF's `beforePublishDate`, YYYY-MM-DD), ?q= (OF's own vault
 * search, sent as `query`) and ?slist= (the folder column's Search, OF's own ?slist=, sent to GET /vault/lists as
 * `query`). ofMirrorData asks for the media with all of them but slist (vaultMediaPath), for the folders with slist
 * (vaultListsPath). Links to the page itself and to its state pages keep the view; a folder row starts a
 * fresh one, and the rail, the side menu and Back go to the bare Vault (its folder list on a phone), as OF's. The folders and media are the model's only (no example in any scope); with all models the page is the
 * first model's (OfMirrorFrame's stand-in, "Showing <model>, pick a model to switch"), its writes too. vault/list (OF's
 * custom folder page, which no row opens any more) gets the view too.
 *
 * Writes, for the model shown (no model at all: "Select a model to save changes"), through the relay's existing vault
 * routes (/admin/vault-ai/of-folders*, /admin/vault-ai/items/{id}/hide, /api/of/v2/vault/upload/*):
 * - "Create new category" (state-add-list): Save creates the folder (POST /vault/lists {name}) and opens it. The same
 *   modal with ?edit=1 renames the open folder (PATCH /vault/lists/{id} {name}).
 * - The folder sort dropdown (state-lists-sort-dropdown): a pick sends POST /vault/lists/sort {sort, order}.
 * - The action row under the media tabs: UPLOAD (a batch vault import, filed into the open folder), RENAME and DELETE
 *   for an open custom folder (delete keeps its media in the vault; confirmed), and for the selected tiles (a tile's
 *   checkbox selects it; a click elsewhere on it opens the media in the viewer, see bindActions): ADD TO / MOVE TO a folder, REMOVE FROM FOLDER and REMOVE FROM VAULT (OF's hide; it has no
 *   undo, so it is confirmed), and for one selected tile EDIT TAGS: Infloww's tag editor, the media's Inflowwww tags
 *   (read from the Relay's vault copy, GET /admin/vault-ai/items; saved with PATCH /admin/vault-ai/items/{id} {tags}).
 * - The folder sort's "Customize order" (?customize=1, as OF's: off while a folder search is open): the folder column
 *   turns into OF's custom order (title "Customize order", X cancels, the check saves), every folder with a drag handle
 *   and All media pinned; the check sends POST /vault/lists/sort {customOrder, sort: "custom"} (the Relay's
 *   /admin/vault-ai/of-folders/sort {custom_order}).
 */

import { useEffect, type RefObject } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter, useSearchParams } from "next/navigation";
import { useScope } from "@/contexts/ScopeContext";
import { ofMeQuery } from "@/lib/ofMirrorIdentity";
import { relay, type VaultList } from "@/lib/relay";
import { addToOfFolder, createOfFolder, deleteOfFolder, invalidateVaultGrid, removeFromOfFolder, renameOfFolder, sortOfFolders } from "@/hooks/useVaultCache";
import { floatLabel } from "@/lib/ofMirrorSettings";
import { GREY, message, note, NOTE_STYLE, SELECT_MODEL } from "@/lib/ofMirrorWrites";
import { mirrorQuery, toggleTile, VAULT_LISTS } from "@/lib/ofMirrorData";
import { isoDay, openDatepicker, parseDay, type Day } from "@/lib/ofMirrorDatepicker";

export const VAULT = "/of-manager/vault";
const VIEW_KEYS = ["list", "type", "field", "sort", "date", "q", "slist"] as const;
export type VaultView = Record<(typeof VIEW_KEYS)[number], string | null>;
/** The keys that open a media view (a phone shows the media alone): all but the folder search. */
const MEDIA_KEYS = VIEW_KEYS.filter((k) => k !== "slist");
const DAY = /^\d{4}-\d{2}-\d{2}$/;
/** The media tabs, in OF's order (All sends no type). */
export const TYPES = [null, "photo", "gif", "video", "audio"] as const;
/** The media sort dropdown's fields and their titles (OF's own words; recent is the default). */
export const FIELDS: Record<string, string> = { recent: "Recent", "most-liked": "Most liked", "highest-tips": "Highest tips", buyers: "Buyers" };

/** The view in `params` (unknown values dropped). */
export function viewOf(params: { get(key: string): string | null }): VaultView {
  const type = params.get("type");
  const field = params.get("field");
  const sort = params.get("sort");
  return {
    list: params.get("list") || null,
    type: TYPES.includes(type as (typeof TYPES)[number]) ? type : null,
    field: field && Object.hasOwn(FIELDS, field) && field !== "recent" ? field : null,
    sort: sort === "asc" ? sort : null,
    date: DAY.test(params.get("date") ?? "") ? params.get("date") : null,
    q: params.get("q")?.trim() || null,
    slist: params.get("slist")?.trim() || null,
  };
}

/** `base` with the view's set values as its query ("" for none). */
export function vaultHref(view: Partial<VaultView>, base = VAULT): string {
  const q = new URLSearchParams();
  for (const k of VIEW_KEYS) if (view[k]) q.set(k, view[k]!);
  const s = q.toString();
  return s ? `${base}?${s}` : base;
}

/** The relay read for the view's media: GET /api/of/v2/vault/media (its `list_id`, `type`, `field`, `sort`, `query`). */
export function vaultMediaPath(view: VaultView): string {
  const q = [
    ["list_id", view.list],
    ["type", view.type],
    ["field", view.field],
    ["sort", view.sort],
    ["query", view.q],
    ["before_publish_date", view.date],
  ].filter(([, v]) => v);
  return `/api/of/v2/vault/media?limit=24${q.map(([k, v]) => `&${k}=${encodeURIComponent(v!)}`).join("")}`;
}

/** The relay read for the view's folders: GET /api/of/v2/vault/lists (VAULT_LISTS), with the folder search as `query`. */
export const vaultListsPath = (view: Pick<VaultView, "slist">) => (view.slist ? `${VAULT_LISTS}&query=${encodeURIComponent(view.slist)}` : VAULT_LISTS);

/** GET /api/of/v2/vault/lists: the folders, OF's folder sort and the "All media" counts. */
export interface VaultLists {
  list?: VaultList[];
  all?: Partial<VaultList>;
  sort?: string;
  order?: string;
}

/** An import run's end state (GET /api/of/v2/vault/upload/status). */
export interface UploadRun {
  status?: string;
  error?: string | null;
  total?: number;
  done?: number;
}

export interface VaultHandlers {
  createFolder(name: string): Promise<{ id?: number | string }>;
  renameFolder(id: string, name: string): Promise<unknown>;
  deleteFolder(id: string): Promise<unknown>;
  sortFolders(sort: string, order: string): Promise<unknown>;
  /** OF's Customize order: the folders' ids in their new order. */
  customOrder(ids: (number | string)[]): Promise<unknown>;
  addToFolder(id: string, mediaIds: number[]): Promise<unknown>;
  removeFromFolder(id: string, mediaIds: number[]): Promise<unknown>;
  /** OF's "Remove from vault" (a hide; no undo). */
  hide(mediaIds: number[]): Promise<unknown>;
  /** A batch vault import of `files` (filed into `listId`), settled when the run ends. */
  upload(files: File[], listId: string | null): Promise<UploadRun>;
  /** The media's Inflowwww tags; null when the Relay's vault copy does not hold it (it cannot be tagged yet). */
  tags(mediaId: number): Promise<string[] | null>;
  /** Save the media's tags (the Relay lower-cases and dedupes them); the tags as saved. */
  saveTags(mediaId: number, tags: string[]): Promise<string[]>;
  confirm(text: string): boolean;
}

export interface VaultContext {
  view: VaultView;
  /** ?edit=1: the add-list modal renames the open folder. */
  edit: boolean;
  /** ?customize=1: the folder column is in OF's Customize order. */
  customize?: boolean;
  /** "Go to date"'s first day: the model's first published post or join day (OF's), when the app has it. */
  minDate?: string | null;
  lists?: VaultLists;
  navigate(href: string): void;
  /** null: no single model selected. */
  handlers: VaultHandlers | null;
}

const RIGHT = ".l-main-content.m-r-side";
const SEARCH = "input[name='media_vault_search']";
const OPEN_SEARCH = "button[aria-label='Search media']";
const CLOSE_SEARCH = "[at-attr='close_search']";
const SEARCH_OPEN = "m-search-form-visible";
const ROW = "a.b-rows-lists__item__text";
const SELECT = ".of-state-menu .v-list-item";
const NAME = ".modal input[at-attr='input']";
const SAVE = ".modal-footer button[type='submit']";
export const BAR = "oi-vault-bar";
const TILE = "[data-oi-media]";

/** The open folder, when it is a custom one (only those can be renamed, deleted or emptied). */
const customFolder = (ctx: VaultContext) => ctx.lists?.list?.find((l) => String(l.id) === ctx.view.list && l.type === "custom") ?? null;
const selected = (doc: Document) => [...doc.querySelectorAll<HTMLElement>(`${TILE}.selected`)].map((t) => Number(t.dataset.oiMedia)).filter(Boolean);
const wire = (el: Element | null | undefined) => el?.setAttribute("data-oi-wired", "");

/** Point `a` at `href`, remembering its captured href (so a rebind starts from it). */
function setHref(a: HTMLAnchorElement, href: string) {
  a.dataset.oiHref ??= a.getAttribute("href") ?? "";
  a.setAttribute("href", href);
}
const capturedHref = (a: HTMLAnchorElement) => a.dataset.oiHref ?? a.getAttribute("href") ?? "";

/** The links that leave the view, as OF's: the rail (the phone's bottom bar), the side menu and the column's Back. */
const LEAVE = "a.l-header__menu__item, a.l-sidebar__menu__item, a.g-page__header__btn[aria-label='Back']:not([at-attr='close_search'])";

/** Links to the Vault page and its state pages keep the view (a folder row, a dropdown pick and LEAVE are set apart). */
function keepView(doc: Document, view: VaultView) {
  for (const a of doc.querySelectorAll<HTMLAnchorElement>("a[href^='/of-manager/vault']")) {
    if (a.matches(ROW) || a.matches(LEAVE)) continue;
    const href = capturedHref(a);
    if (href === VAULT || href.startsWith(`${VAULT}/state-`)) setHref(a, vaultHref(view, href));
  }
  const close = doc.querySelector<HTMLAnchorElement>(`${RIGHT} ${CLOSE_SEARCH}`);
  if (close) setHref(close, vaultHref({ ...view, q: null }));
}

/** OF's one-column width (its CSS stacks the two columns below 1004px). */
const NARROW = "(max-width: 1003.98px)";
export const VIEW_OPEN = "data-oi-vault-view";

export const PHONE_BACK = "oi-vault-back";

/**
 * A phone, as OF's own: an open view (a folder, a type, a sort or a search: OF's /my/vault/list/<id> screen) shows
 * the media alone, under a Back (the folder column's own, copied before the media's title) to the folder list; the
 * bare Vault shows the folders, then All media's grid under them (never the folder column stuck over the grid, as
 * OF's desktop column is). Returns its undo.
 */
function phoneColumns(doc: Document, view: VaultView): () => void {
  const style = doc.createElement("style");
  style.textContent =
    `#${PHONE_BACK}{display:none!important}` +
    `@media ${NARROW}{.l-sidebar-column.m-l-side.m-sticky-column{position:static!important}` +
    `html[${VIEW_OPEN}] .l-sidebar-column.m-l-side{display:none!important}` +
    `html[${VIEW_OPEN}] #${PHONE_BACK}{display:inline-flex!important;flex:none}}`;
  doc.head.append(style);
  const open = MEDIA_KEYS.some((k) => view[k]);
  doc.documentElement.toggleAttribute(VIEW_OPEN, open);
  const back = doc.querySelector(".l-sidebar-column .g-page__header__btn[aria-label='Back']")?.cloneNode(true) as HTMLAnchorElement | undefined;
  const title = doc.querySelector(`${RIGHT} .g-page__header > h1`);
  if (back && title) {
    back.id = PHONE_BACK;
    back.setAttribute("href", VAULT);
    title.before(back);
  }
  return () => {
    style.remove();
    doc.getElementById(PHONE_BACK)?.remove();
    doc.documentElement.removeAttribute(VIEW_OPEN);
  };
}

/** The media tabs and the sort title show the view. */
function showView(doc: Document, view: VaultView) {
  const tabs = [...doc.querySelectorAll<HTMLButtonElement>(`${RIGHT} .b-tabs__nav__link`)];
  tabs.forEach((t, i) => {
    const on = (TYPES[i] ?? null) === view.type;
    t.classList.toggle("m-current", on);
    t.classList.toggle("m-no-pointer", on);
    wire(t);
  });
  const title = doc.querySelector(`${RIGHT} .b-content-filter__title`);
  if (title) title.textContent = FIELDS[view.field ?? "recent"];
  const search = doc.querySelector<HTMLInputElement>(`${RIGHT} ${SEARCH}`);
  const header = search?.closest(".g-page__header");
  for (const el of [search, search?.form?.querySelector("button[type='submit']"), doc.querySelector(`${RIGHT} ${OPEN_SEARCH}`)]) wire(el);
  if (search && header && view.q) {
    header.classList.add(SEARCH_OPEN);
    search.value = view.q;
  }
}

/** The folder sorts (OF's `sort` on GET /vault/lists) and their titles, as the folder sort dropdown words them. */
export const LIST_SORTS: Record<string, string> = { default: "Default", name: "Name", recent: "Recent", media: "Media", custom: "Custom" };

/** Today in local time, as OF's date picker's last day. */
const today = (): Day => {
  const d = new Date();
  return { y: d.getFullYear(), m: d.getMonth() + 1, d: d.getDate() };
};

/**
 * The media sort's "Go to date", as OF's: its pick opens OF's day popup (ofMirrorDatepicker) from the model's first
 * published post or join day (`minDate`, when the app has it) to today; the day applied is the view's ?date= (OF's
 * `beforePublishDate`), and the item reads it. "All time" drops it.
 */
function bindGoToDate(doc: Document, item: Element, ctx: VaultContext) {
  const { view, minDate } = ctx;
  item.querySelector("a.of-state-link")?.remove();
  wire(item);
  const label = item.querySelector("label");
  if (label && view.date) label.textContent = view.date;
  item.addEventListener("click", (ev) => {
    ev.preventDefault();
    const now = today();
    const at = (view.date && parseDay(view.date)) || now;
    openDatepicker(doc, {
      start: at,
      end: at,
      today: now,
      userStart: (minDate && parseDay(minDate.slice(0, 10))) || null,
      single: true,
      onApply: (d) => ctx.navigate(vaultHref({ ...view, date: isoDay(d) })),
    });
  });
}

/** The media sort dropdown: each pick links to the view with that field, order or date; the view's are checked. */
function bindMediaSort(doc: Document, ctx: VaultContext) {
  const { view } = ctx;
  for (const item of doc.querySelectorAll(SELECT)) {
    const radio = item.querySelector<HTMLInputElement>("input[type='radio']");
    const a = item.querySelector<HTMLAnchorElement>("a.of-state-link");
    if (!radio || !a) continue;
    if (radio.name === "vault-go-date-field") {
      radio.checked = radio.value === "date_all_time" ? !view.date : !!view.date;
      if (radio.value === "date_all_time") setHref(a, vaultHref({ ...view, date: null }));
      else bindGoToDate(doc, item, ctx);
    } else if (radio.name === "vault-filter-field") {
      setHref(a, vaultHref({ ...view, field: radio.value === "recent" ? null : radio.value }));
      radio.checked = radio.value === (view.field ?? "recent");
    } else if (radio.name === "ascending-field") {
      setHref(a, vaultHref({ ...view, sort: radio.value === "asc" ? "asc" : null }));
      radio.checked = radio.value === (view.sort ?? "desc");
    }
  }
}

/** The folder sort dropdown: the folders' sort and order are checked; a pick sends them (POST /vault/lists/sort) and closes it. */
function bindListSort(doc: Document, ctx: VaultContext): () => void {
  const sort = ctx.lists?.sort ?? "default";
  const order = ctx.lists?.order ?? "desc";
  const pick = (radio: HTMLInputElement) => (/-sort-/.test(radio.name) ? { sort: radio.value, order } : { sort, order: radio.value });
  // As OF's (its list sort's orderDisabled): the order is off for a custom order.
  const unordered = sort === "custom";
  // Customize order: off while a folder search is open, as OF's.
  for (const item of doc.querySelectorAll(SELECT)) {
    if (item.querySelector("input[type='radio']")) continue;
    wire(item);
    item.classList.toggle("v-list-item--disabled", !!ctx.view.slist);
    item.setAttribute("aria-disabled", String(!!ctx.view.slist));
  }
  for (const radio of doc.querySelectorAll<HTMLInputElement>(`${SELECT} input[type='radio']`)) {
    const isSort = /-sort-/.test(radio.name);
    wire(radio.closest(SELECT)); // its click is this handler's, not its State page link's
    radio.checked = isSort ? radio.value === sort : radio.value === order && !unordered;
    if (isSort) continue;
    const item = radio.closest(SELECT)!;
    item.classList.toggle("v-list-item--disabled", unordered);
    item.setAttribute("aria-disabled", String(unordered));
    radio.closest(".b-input-radio__container")?.classList.toggle("m-no-pointer", unordered);
  }
  const onClick = (ev: MouseEvent) => {
    const item = (ev.target as Element | null)?.closest?.(SELECT);
    if (!item) return;
    // Before the frame's own link handler: the dropdown closes once OF has the new order.
    ev.preventDefault();
    ev.stopPropagation();
    if (item.classList.contains("v-list-item--disabled")) return;
    const radio = item.querySelector<HTMLInputElement>("input[type='radio']");
    if (!ctx.handlers) return note(doc, item, SELECT_MODEL);
    if (!radio) return ctx.navigate(customizeHref(ctx.view));
    const { handlers } = ctx;
    const body = pick(radio);
    handlers.sortFolders(body.sort, body.order).then(
      () => ctx.navigate(vaultHref(ctx.view)),
      (e) => note(doc, item, `Could not sort: ${message(e)}`, true),
    );
  };
  doc.addEventListener("click", onClick, true);
  return () => doc.removeEventListener("click", onClick, true);
}

/** "Create new category" (or, with ?edit=1, the open folder's rename): Save is on while the name has text. */
function bindFolderForm(doc: Document, ctx: VaultContext): () => void {
  const input = doc.querySelector<HTMLInputElement>(NAME);
  const save = doc.querySelector<HTMLButtonElement>(SAVE);
  if (!input || !save) return () => {};
  wire(input);
  wire(save);
  const folder = ctx.edit ? customFolder(ctx) : null;
  const sync = () => {
    floatLabel(input, !!input.value);
    const counter = input.closest(".v-input")?.querySelector(".v-counter");
    if (counter) counter.textContent = counter.textContent!.replace(/^\s*\d+/, String([...input.value].length));
    save.disabled = !input.value.trim();
  };
  if (folder) {
    const title = doc.querySelector(".modal-title");
    if (title) title.textContent = " Rename category ";
    input.value = folder.name;
    sync();
  }
  const onInput = (ev: Event) => {
    if (ev.target !== input) return;
    doc.getElementById("oi-note")?.remove();
    sync();
  };
  const onSubmit = (ev: Event) => {
    if (ev.target !== input.form) return;
    ev.preventDefault();
    const name = input.value.trim();
    if (!name || save.disabled) return;
    const { handlers } = ctx;
    if (!handlers) return note(doc, save, SELECT_MODEL);
    save.disabled = true;
    const done = folder
      ? handlers.renameFolder(String(folder.id), name).then(() => vaultHref(ctx.view))
      : handlers.createFolder(name).then((r) => vaultHref({ list: r?.id != null ? String(r.id) : null }));
    done.then(ctx.navigate, (e) => {
      save.disabled = false;
      note(doc, save, `Could not ${folder ? "rename" : "create"}: ${message(e)}`, true);
    });
  };
  doc.addEventListener("input", onInput);
  doc.addEventListener("submit", onSubmit);
  return () => {
    doc.removeEventListener("input", onInput);
    doc.removeEventListener("submit", onSubmit);
  };
}

/** One of OF's flat text buttons (the modals' CANCEL / SAVE style), Wired. */
function flatButton(doc: Document, text: string, act: string): HTMLButtonElement {
  const b = doc.createElement("button");
  b.type = "button";
  b.className = "g-btn m-flat m-btn-gaps m-reset-width";
  b.textContent = text;
  b.dataset.oiAct = act;
  wire(b);
  return b;
}

export const VIEWER = "oi-vault-viewer";

/** One media the viewer shows: its file (already through `img`) and OF's type (photo, gif, video, audio). */
export interface ViewerItem { src: string; type?: string | null }

/** The open viewer's close, per document (it holds the viewer's key listener). */
const closers = new WeakMap<Document, () => void>();

/** Close the open viewer, if any. */
export function closeViewer(doc: Document) {
  closers.get(doc)?.();
  doc.getElementById(VIEWER)?.remove();
}

/** A tile's media for the viewer (`data-oi-full`, `data-oi-type`), or null for a tile with no file to show. */
export const viewerItem = (el: HTMLElement): ViewerItem | null => (el.dataset.oiFull ? { src: el.dataset.oiFull, type: el.dataset.oiType } : null);

const ROUND = "position:absolute;width:40px;height:40px;border:0;border-radius:50%;background:rgba(0,0,0,.5);color:#fff;font-size:28px;line-height:1;cursor:pointer";

/**
 * `items[start]` full size over the page, as OF's viewer (PhotoSwipe / video.js): a photo, a video with its player, a GIF
 * looping, an audio's player; with more than one item, previous and next buttons and the ← / → keys step through them
 * (stopping at either end). Closed by ×, the backdrop or Escape.
 */
export function openViewer(doc: Document, items: ViewerItem[], start = 0) {
  closeViewer(doc);
  if (!items.length) return;
  let at = Math.min(Math.max(start, 0), items.length - 1);
  const box = doc.createElement("div");
  box.id = VIEWER;
  box.setAttribute("role", "dialog");
  box.setAttribute("aria-modal", "true");
  box.style.cssText = "position:fixed;inset:0;z-index:1000;display:flex;align-items:center;justify-content:center;padding:56px 56px;background:rgba(0,0,0,.92)";
  const button = (label: string, text: string, place: string) => {
    const b = doc.createElement("button");
    b.type = "button";
    b.setAttribute("aria-label", label);
    b.textContent = text;
    b.style.cssText = `${ROUND};${place}`;
    wire(b);
    return b;
  };
  const close = button("Close", "×", "top:8px;right:8px");
  const prev = button("Previous", "‹", "left:8px;top:calc(50% - 20px)");
  const next = button("Next", "›", "right:8px;top:calc(50% - 20px)");
  const many = items.length > 1;
  const show = () => {
    const { src, type } = items[at];
    const media = doc.createElement(type === "photo" || !type ? "img" : type === "audio" ? "audio" : "video") as HTMLImageElement | HTMLMediaElement;
    media.src = src;
    media.style.cssText = "max-width:100%;max-height:100%;object-fit:contain";
    // (Not instanceof: the frame's elements are of its own window.)
    if ("autoplay" in media) {
      media.autoplay = true;
      media.controls = type !== "gif";
      media.loop = media.muted = type === "gif";
      media.setAttribute("playsinline", "");
    }
    wire(media);
    box.querySelector("[data-oi-viewer-media]")?.remove();
    media.setAttribute("data-oi-viewer-media", "");
    box.prepend(media);
    prev.disabled = at === 0;
    next.disabled = at === items.length - 1;
    prev.style.opacity = prev.disabled ? ".3" : "";
    next.style.opacity = next.disabled ? ".3" : "";
  };
  const step = (by: number) => {
    const to = at + by;
    if (to < 0 || to >= items.length) return;
    at = to;
    show();
  };
  const onKey = (ev: KeyboardEvent) => {
    if (ev.key === "Escape") shut();
    else if (many && ev.key === "ArrowLeft") step(-1);
    else if (many && ev.key === "ArrowRight") step(1);
    else return;
    ev.preventDefault();
  };
  const shut = () => {
    doc.removeEventListener("keydown", onKey);
    closers.delete(doc);
    box.remove();
  };
  box.append(close);
  if (many) box.append(prev, next);
  box.addEventListener("click", (ev) => {
    if (ev.target === box || ev.target === close) shut();
    else if (ev.target === prev) step(-1);
    else if (ev.target === next) step(1);
  });
  show();
  doc.addEventListener("keydown", onKey);
  closers.set(doc, shut);
  doc.body.append(box);
}

/**
 * The action row under the media tabs (a single model only): rebuilt from the selected tiles on every change.
 * A tile, as OF's: its checkbox selects it, and so does a click anywhere on it while any is selected; otherwise the
 * click opens it in the viewer (a media without a file to show is selected). Returns an unbind, which removes both.
 */
function bindActions(doc: Document, ctx: VaultContext, handlers: VaultHandlers): () => void {
  const tabs = doc.querySelector(`${RIGHT} .b-tabs__nav`);
  if (!tabs) return () => {};
  const bar = doc.createElement("div");
  bar.id = BAR;
  bar.style.cssText = `${NOTE_STYLE};display:flex;flex-wrap:wrap;align-items:center;gap:4px;color:${GREY}`;
  tabs.after(bar);
  const file = doc.createElement("input");
  file.type = "file";
  file.multiple = true;
  file.accept = "image/*,video/*,audio/*";
  file.hidden = true;
  wire(file);
  doc.body.append(file);
  const folder = customFolder(ctx);
  const others = (ctx.lists?.list ?? []).filter((l) => l.type === "custom" && String(l.id) !== ctx.view.list);
  /** The tag editor's media and its field, while it is open. */
  let editor: { id: number; input: HTMLInputElement } | null = null;

  const draw = () => {
    editor = null;
    const ids = selected(doc);
    const parts: (Node | string)[] = [];
    if (!ids.length) {
      parts.push(flatButton(doc, "Upload", "upload"));
      if (folder) parts.push(flatButton(doc, "Rename", "rename"), flatButton(doc, "Delete", "delete"));
    } else {
      parts.push(`${ids.length} selected`);
      if (others.length) {
        const pick = doc.createElement("select");
        pick.className = "form-control";
        pick.style.cssText = "width:auto;height:32px;padding:0 8px;font-size:13px";
        pick.dataset.oiAct = folder ? "move" : "add";
        wire(pick);
        pick.append(new Option(folder ? "Move to…" : "Add to folder…", ""), ...others.map((l) => new Option(l.name, String(l.id))));
        parts.push(pick);
      }
      if (folder) parts.push(flatButton(doc, "Remove from folder", "remove"));
      if (ids.length === 1) parts.push(flatButton(doc, "Edit tags", "tags"));
      parts.push(flatButton(doc, "Remove from vault", "hide"), flatButton(doc, "Clear", "clear"));
    }
    bar.replaceChildren(...parts);
  };

  /** Run `job`, then say `done` (or the error) under the row; the row is off while it runs. */
  const run = (job: () => Promise<unknown>, done: string, fail: string) => {
    bar.style.pointerEvents = "none";
    bar.style.opacity = "0.5";
    job()
      .then(
        () => note(doc, bar, done),
        (e) => note(doc, bar, `${fail}: ${message(e)}`, true),
      )
      .finally(() => {
        bar.style.pointerEvents = "";
        bar.style.opacity = "";
        draw();
      });
  };
  const clear = () => {
    for (const t of doc.querySelectorAll(`${TILE}.selected`)) toggleTile(t, false);
  };

  /** Infloww's tag editor for one media: its tags, comma-separated, in one field; Save (or Enter) writes them. */
  const editTags = (id: number) => {
    const input = doc.createElement("input");
    input.type = "text";
    input.name = "oi-vault-tags";
    input.className = "form-control";
    input.placeholder = "Tags, comma-separated";
    input.style.cssText = "flex:1 1 200px;width:auto;height:32px;padding:0 8px;font-size:13px";
    input.disabled = true;
    wire(input);
    const save = flatButton(doc, "Save", "tags-save");
    save.disabled = true;
    bar.replaceChildren("Tags", input, save, flatButton(doc, "Cancel", "tags-cancel"));
    const mine = { id, input };
    editor = mine;
    input.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter" && !save.disabled) save.click();
    });
    handlers.tags(id).then(
      (tags) => {
        if (editor !== mine) return;
        if (tags === null) return note(doc, bar, "Not in Inflowwww's vault copy yet: collect the vault in Vault Pro first", true);
        input.value = tags.join(", ");
        input.disabled = save.disabled = false;
        input.focus();
      },
      (e) => editor === mine && note(doc, bar, `Could not load tags: ${message(e)}`, true),
    );
  };

  const onClick = (ev: MouseEvent) => {
    const target = ev.target as Element | null;
    if (!target?.closest) return;
    const tile = target.closest<HTMLElement>(`${RIGHT} ${TILE}`);
    if (tile) {
      if (!target.closest(".checkbox-item") && !selected(doc).length && tile.dataset.oiFull) {
        // The folder's loaded tiles, in grid order, for the viewer's previous / next.
        const tiles = [...doc.querySelectorAll<HTMLElement>(`${RIGHT} ${TILE}`)].filter((t) => t.dataset.oiFull);
        return openViewer(doc, tiles.map((t) => viewerItem(t)!), tiles.indexOf(tile));
      }
      toggleTile(tile);
      return draw();
    }
    const act = target.closest<HTMLElement>(`#${BAR} button`)?.dataset.oiAct;
    if (!act) return;
    const ids = selected(doc);
    if (act === "upload") file.click();
    else if (act === "tags" && ids.length === 1) editTags(ids[0]);
    else if (act === "tags-cancel") draw();
    else if (act === "tags-save" && editor) {
      const { id, input } = editor;
      const tags = input.value.split(/[,\n]/).map((t) => t.trim()).filter(Boolean);
      run(() => handlers.saveTags(id, tags), "Tags saved", "Could not save tags");
    }
    else if (act === "rename") ctx.navigate(vaultHref(ctx.view, `${VAULT}/state-add-list`) + (ctx.view.list ? "&" : "?") + "edit=1");
    else if (act === "delete" && folder) {
      if (!handlers.confirm(`Delete the folder "${folder.name}"? Its media stay in the vault.`)) return;
      run(() => handlers.deleteFolder(String(folder.id)).then(() => ctx.navigate(VAULT)), "Deleted", "Could not delete");
    } else if (act === "remove" && folder) {
      run(() => handlers.removeFromFolder(String(folder.id), ids).then(clear), "Removed from the folder", "Could not remove");
    } else if (act === "hide") {
      if (!handlers.confirm(`Remove ${ids.length} media from the vault? OnlyFans has no undo.`)) return;
      run(() => handlers.hide(ids).then(clear), "Removed from the vault", "Could not remove");
    } else if (act === "clear") {
      clear();
      draw();
    }
  };
  const onChange = (ev: Event) => {
    const t = ev.target as HTMLElement;
    if (t === file) {
      const files = [...(file.files ?? [])];
      file.value = "";
      if (!files.length) return;
      note(doc, bar, `Uploading ${files.length} ${files.length === 1 ? "file" : "files"}…`, false, 600_000);
      bar.style.pointerEvents = "none";
      handlers
        .upload(files, folder ? String(folder.id) : null)
        .then(
          (r) =>
            r.status === "done"
              ? note(doc, bar, `Uploaded ${r.done ?? files.length} of ${r.total ?? files.length}`)
              : note(doc, bar, `Could not upload: ${r.error || r.status || "unknown"}`, true),
          (e) => note(doc, bar, `Could not upload: ${message(e)}`, true),
        )
        .finally(() => (bar.style.pointerEvents = ""));
      return;
    }
    const act = (t as HTMLSelectElement).dataset?.oiAct;
    const target = (t as HTMLSelectElement).value;
    if (!bar.contains(t) || !target || (act !== "add" && act !== "move")) return;
    const ids = selected(doc);
    const to = others.find((l) => String(l.id) === target)?.name ?? target;
    if (act === "add") run(() => handlers.addToFolder(target, ids).then(clear), `Added to ${to}`, "Could not add");
    else run(() => handlers.addToFolder(target, ids).then(() => handlers.removeFromFolder(String(folder!.id), ids)).then(clear), `Moved to ${to}`, "Could not move");
  };

  draw();
  doc.addEventListener("click", onClick);
  doc.addEventListener("change", onChange);
  return () => {
    doc.removeEventListener("click", onClick);
    doc.removeEventListener("change", onChange);
    bar.remove();
    file.remove();
    closeViewer(doc);
  };
}

export const LISTS_SEARCH = "oi-lists-search";

/**
 * The folder column's Search, as OF's: its button opens a search form in the column's header (a copy of the media
 * search's); a search is the view's ?slist= (GET /vault/lists `query`), and the form's Back drops it. Returns its undo.
 */
function bindFolderSearch(doc: Document, ctx: VaultContext): () => void {
  const header = doc.querySelector<HTMLElement>(".l-sidebar-column .g-page__header");
  const opener = header?.querySelector<HTMLButtonElement>("button[aria-label='Search']");
  const tpl = doc.querySelector<HTMLFormElement>(`${RIGHT} form.b-search-form`);
  if (!header || !opener || !tpl) return () => {};
  const form = tpl.cloneNode(true) as HTMLFormElement;
  form.id = LISTS_SEARCH;
  form.querySelector(".b-search-autocomplete")?.remove();
  const input = form.querySelector<HTMLInputElement>(SEARCH)!;
  input.name = "vault_lists_search";
  input.value = ctx.view.slist ?? "";
  form.querySelector(CLOSE_SEARCH)?.setAttribute("href", vaultHref({ ...ctx.view, slist: null }));
  for (const el of [input, form.querySelector("button[type='submit']"), opener]) wire(el);
  opener.closest(".b-btns-group")?.prepend(form);
  header.classList.toggle(SEARCH_OPEN, !!ctx.view.slist);
  const onClick = (ev: MouseEvent) => {
    if (!opener.contains(ev.target as Node | null)) return;
    header.classList.add(SEARCH_OPEN);
    input.focus();
  };
  const onSubmit = (ev: Event) => {
    if (ev.target !== form) return;
    ev.preventDefault();
    ctx.navigate(vaultHref({ ...ctx.view, slist: input.value.trim() || null }));
  };
  doc.addEventListener("click", onClick);
  doc.addEventListener("submit", onSubmit);
  return () => {
    doc.removeEventListener("click", onClick);
    doc.removeEventListener("submit", onSubmit);
    form.remove();
    header.classList.remove(SEARCH_OPEN);
  };
}

export const CUSTOMIZE = "data-oi-customize";
export const ORDER_BOX = "oi-custom-order";
/** The view in OF's Customize order. */
export const customizeHref = (view: VaultView) => {
  const href = vaultHref(view);
  return `${href}${href.includes("?") ? "&" : "?"}customize=1`;
};
/** OF's icon-drag (its sprite's, as on New post's poll), which the Vault pages' cut-down sprite does not carry. */
const ICON_DRAG =
  "M6 7a2 2 0 102 2 2 2 0 00-2-2zm12 4a2 2 0 10-2-2 2 2 0 002 2zm-6-4a2 2 0 102 2 2 2 0 00-2-2zm6 6a2 2 0 102 2 2 2 0 00-2-2zm-6 0a2 2 0 102 2 2 2 0 00-2-2zm-6 0a2 2 0 102 2 2 2 0 00-2-2z";

/** One of OF's icon buttons (`icon` from the page's sprite), Wired. */
function iconButton(doc: Document, cls: string, label: string, icon: string): HTMLButtonElement {
  const b = doc.createElement("button");
  b.type = "button";
  b.className = cls;
  b.setAttribute("aria-label", label);
  b.innerHTML = `<svg class="g-icon" aria-hidden="true"><use href="#${icon}" xlink:href="#${icon}"></use></svg>`;
  wire(b);
  return b;
}

/**
 * OF's Customize order of the folder column: its title "Customize order" with an X before it (cancel) and a check in
 * place of the sort (save); every folder, in OF's order, with a drag handle (by pointer, so a phone's touch drags too),
 * All media pinned first. The check sends the folders' ids in their new order and goes back to the view. Returns its undo.
 */
function bindCustomOrder(doc: Document, ctx: VaultContext, handlers: VaultHandlers): () => void {
  const column = doc.querySelector(".l-sidebar-column");
  const rows = column?.querySelector<HTMLElement>(".b-rows-lists");
  const filter = column?.querySelector<HTMLElement>(".b-content-filter");
  const title = filter?.querySelector<HTMLElement>(".b-content-filter__title");
  if (!rows || !filter || !title) return () => {};
  const style = doc.createElement("style");
  style.textContent =
    `html[${CUSTOMIZE}] .l-sidebar-column .b-rows-lists:not(#${ORDER_BOX}),` +
    `html[${CUSTOMIZE}] .l-sidebar-column .b-content-filter > :not([data-oi-order-ui]){display:none!important}`;
  doc.head.append(style);
  doc.documentElement.setAttribute(CUSTOMIZE, "");
  const back = () => ctx.navigate(vaultHref(ctx.view));

  const cancel = iconButton(doc, "g-btn m-icon m-icon-only m-sm-size m-with-round-hover b-content-filter__clear-filters", "Cancel", "icon-close");
  const heading = title.cloneNode(false) as HTMLElement;
  heading.textContent = "Customize order";
  const group = doc.createElement("div");
  group.className = "b-content-filter__group-btns b-btns-group d-inline-flex flex-row align-items-center justify-content-end";
  const save = iconButton(doc, "g-btn m-with-round-hover m-icon m-icon-only m-sm-size", "Save order", "icon-done");
  group.append(save);
  for (const el of [cancel, heading, group]) el.setAttribute("data-oi-order-ui", "");
  filter.prepend(cancel, heading);
  filter.append(group);

  const box = rows.cloneNode(false) as HTMLElement;
  box.id = ORDER_BOX;
  /** A row as shown, inert (no link): its own text and covers, from the folder list on the page. */
  const still = (row: Element) => {
    const el = row.cloneNode(true) as HTMLElement;
    for (const a of el.querySelectorAll("a")) {
      a.removeAttribute("href");
      a.removeAttribute("role");
      a.classList.remove("m-current", "router-link-active");
    }
    el.style.removeProperty("display");
    return el;
  };
  const all = rows.querySelector(`a[href='${VAULT}']`)?.closest(".b-rows-lists__item");
  if (all) box.append(still(all));
  const ids = new Map<string, number | string>();
  for (const l of ctx.lists?.list ?? []) {
    const row = rows.querySelector(`a[href='${VAULT}?list=${l.id}']`)?.closest(".b-rows-lists__item");
    const el = row ? still(row) : doc.createElement("div");
    if (!row) {
      el.className = "b-rows-lists__item";
      el.textContent = l.name;
    }
    el.dataset.oiOrder = String(l.id);
    el.style.cssText += ";display:flex;align-items:center";
    el.querySelector(".b-rows-lists__item__text")?.setAttribute("style", "flex:1 1 auto;min-width:0");
    const handle = doc.createElement("button");
    handle.type = "button";
    handle.className = "g-btn m-icon m-icon-only m-sm-size m-with-round-hover";
    handle.setAttribute("aria-label", `Drag ${l.name}`);
    handle.dataset.oiDrag = "";
    handle.style.cssText = "flex:none;touch-action:none;cursor:grab";
    handle.innerHTML = `<svg class="g-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="${ICON_DRAG}"></path></svg>`;
    wire(handle);
    el.append(handle);
    ids.set(String(l.id), l.id);
    box.append(el);
  }
  rows.after(box);

  let dragged: HTMLElement | null = null;
  const onDown = (ev: PointerEvent) => {
    const handle = (ev.target as Element | null)?.closest?.<HTMLElement>("[data-oi-drag]");
    if (!handle || !box.contains(handle)) return;
    ev.preventDefault();
    dragged = handle.closest<HTMLElement>("[data-oi-order]");
    handle.setPointerCapture?.(ev.pointerId);
    if (dragged) dragged.style.opacity = "0.6";
  };
  const onMove = (ev: PointerEvent) => {
    if (!dragged) return;
    const over = doc.elementFromPoint(ev.clientX, ev.clientY)?.closest<HTMLElement>("[data-oi-order]");
    if (!over || over === dragged || !box.contains(over)) return;
    const r = over.getBoundingClientRect();
    box.insertBefore(dragged, ev.clientY > r.top + r.height / 2 ? over.nextSibling : over);
  };
  const onUp = () => {
    if (dragged) dragged.style.opacity = "";
    dragged = null;
  };
  const onClick = (ev: MouseEvent) => {
    const t = ev.target as Element | null;
    if (cancel.contains(t)) return back();
    if (!save.contains(t) || save.disabled) return;
    save.disabled = true;
    const order = [...box.querySelectorAll<HTMLElement>("[data-oi-order]")].map((r) => ids.get(r.dataset.oiOrder!)!);
    handlers.customOrder(order).then(back, (e) => {
      save.disabled = false;
      note(doc, filter, `Could not save the order: ${message(e)}`, true);
    });
  };
  box.addEventListener("pointerdown", onDown);
  box.addEventListener("pointermove", onMove);
  box.addEventListener("pointerup", onUp);
  box.addEventListener("pointercancel", onUp);
  doc.addEventListener("click", onClick);
  return () => {
    doc.removeEventListener("click", onClick);
    for (const el of [cancel, heading, group, box, style]) el.remove();
    doc.documentElement.removeAttribute(CUSTOMIZE);
  };
}

/**
 * Wire the Vault page `page` (its path under of-mirror/pages: vault/index or vault/state-*) in `doc` for `ctx`.
 * Returns an unbind.
 */
export function bindVault(doc: Document, page: string, ctx: VaultContext): () => void {
  if (page !== "vault/index" && page !== "vault/list" && !page.startsWith("vault/state-")) return () => {};
  const { view, handlers, navigate } = ctx;
  keepView(doc, view);
  showView(doc, view);
  const unbinds: (() => void)[] = [bindFolderSearch(doc, ctx)];
  if (page === "vault/index" || page === "vault/list") {
    unbinds.push(phoneColumns(doc, view));
    if (ctx.customize && handlers && !view.slist) unbinds.push(bindCustomOrder(doc, ctx, handlers));
  }
  if (page === "vault/state-sort-dropdown") bindMediaSort(doc, ctx);
  if (page === "vault/state-lists-sort-dropdown") unbinds.push(bindListSort(doc, ctx));
  if (page === "vault/state-add-list") unbinds.push(bindFolderForm(doc, ctx));
  if (page === "vault/index" && handlers) unbinds.push(bindActions(doc, ctx, handlers));

  const search = doc.querySelector<HTMLInputElement>(`${RIGHT} ${SEARCH}`);
  const header = search?.closest(".g-page__header");
  const onClick = (ev: MouseEvent) => {
    const target = ev.target as Element | null;
    if (!target?.closest || !search || !header) return;
    const tab = target.closest(`${RIGHT} .b-tabs__nav__link`);
    if (tab) {
      const i = [...doc.querySelectorAll(`${RIGHT} .b-tabs__nav__link`)].indexOf(tab);
      return navigate(vaultHref({ ...view, type: TYPES[i] ?? null }));
    }
    // The opener sits in the filter row, not the header it opens: aria-expanded marks the open form on it too.
    const opener = target.closest(`${RIGHT} ${OPEN_SEARCH}`);
    if (opener) {
      header.classList.add(SEARCH_OPEN);
      opener.setAttribute("aria-expanded", "true");
      search.focus();
    } else if (target.closest(`${RIGHT} ${CLOSE_SEARCH}`)) {
      header.classList.remove(SEARCH_OPEN); // its link drops ?q=
      doc.querySelector(`${RIGHT} ${OPEN_SEARCH}`)?.setAttribute("aria-expanded", "false");
      search.value = "";
    }
  };
  const onSubmit = (ev: Event) => {
    if (!search || ev.target !== search.form) return;
    ev.preventDefault();
    navigate(vaultHref({ ...view, q: search.value.trim() || null }));
  };
  doc.addEventListener("click", onClick);
  doc.addEventListener("submit", onSubmit);
  return () => {
    doc.removeEventListener("click", onClick);
    doc.removeEventListener("submit", onSubmit);
    for (const u of unbinds) u();
  };
}

/** How many of the Relay's vault copy the tag editor looks through for a media's tags (the route's most). */
export const TAGS_SCAN = 1000;
const POLL_MS = 2000;
/** How long an upload's status is polled (as long as its "Uploading…" note shows) before the action bar comes back. */
export const UPLOAD_TIMEOUT_MS = 600_000;
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

/** Ask `status` every `pollMs` until the run stops; past `timeoutMs` give up (the import may still finish on the Relay). */
export async function pollUpload<T extends { running?: boolean }>(status: () => Promise<T>, pollMs = POLL_MS, timeoutMs = UPLOAD_TIMEOUT_MS): Promise<T> {
  const end = Date.now() + timeoutMs;
  while (Date.now() < end) {
    await sleep(pollMs);
    const s = await status();
    if (!s.running) return s;
  }
  throw new Error(`still importing after ${Math.round(timeoutMs / 60_000)} minutes, check the Vault later`);
}

/** The Vault page and its state pages: bind on every frame load and view change. */
export function useOfVault(frameRef: RefObject<HTMLIFrameElement | null>, src: string): void {
  const { accountId } = useScope();
  const params = useSearchParams();
  const router = useRouter();
  const qc = useQueryClient();
  const page = /^\/of-mirror\/pages\/(.+)\.html$/.exec(src)?.[1] ?? "";
  const isVault = page.startsWith("vault/");
  const query = params.toString();
  // The same query (key and path) as ofMirrorData's folder list: one fetch for both.
  const lists = useQuery(mirrorQuery<VaultLists>(accountId, vaultListsPath(viewOf(params)), isVault)).data;
  // "Go to date"'s first day, as OF's: the model's first published post, else its join day.
  const me = useQuery(ofMeQuery(accountId)).data as { firstPublishedPostDate?: string | null; joinDate?: string | null } | undefined;
  const minDate = me?.firstPublishedPostDate || me?.joinDate || null;

  useEffect(() => {
    const frame = frameRef.current;
    if (!frame || !isVault) return;
    const sp = new URLSearchParams(query);
    const view = viewOf(sp);
    const ctx = { accountId };
    const refresh = () => {
      void qc.invalidateQueries({ queryKey: ["of-mirror-data", accountId] });
      invalidateVaultGrid(qc, accountId);
    };
    const after = <T,>(p: Promise<T>) => p.then((r) => (refresh(), r));
    const handlers: VaultHandlers | null = accountId
      ? {
          createFolder: (name) => after(createOfFolder(accountId, name) as Promise<{ id?: number | string }>),
          renameFolder: (id, name) => after(renameOfFolder(accountId, id, name)),
          deleteFolder: (id) => after(deleteOfFolder(accountId, id)),
          sortFolders: (sort, order) => after(sortOfFolders(accountId, { sort, order })),
          customOrder: (ids) => after(sortOfFolders(accountId, { customOrder: ids })),
          addToFolder: (id, ids) => after(addToOfFolder(accountId, id, ids)),
          removeFromFolder: (id, ids) => after(removeFromOfFolder(accountId, id, ids)),
          hide: (ids) =>
            after(
              (async () => {
                for (const id of ids) await relay.post(`/admin/vault-ai/items/${id}/hide`, { account_id: accountId }, ctx);
              })(),
            ),
          upload: (files, listId) =>
            after(
              (async () => {
                const form = new FormData();
                for (const f of files) form.append("files", f, f.name);
                if (listId) form.append("list_id", listId);
                const { run_id } = await relay.uploadForm<{ run_id: string }>("/api/of/v2/vault/upload/batch", form, ctx);
                return pollUpload(() => relay.get<UploadRun & { running?: boolean }>(`/api/of/v2/vault/upload/status?run_id=${encodeURIComponent(run_id)}`, ctx));
              })(),
            ),
          tags: async (id) => {
            const r = await relay.get<{ list?: { id: number | string; _ai?: { tags?: string[] | null } }[] }>(`/admin/vault-ai/items?account_id=${encodeURIComponent(accountId)}&limit=${TAGS_SCAN}`, ctx);
            const item = r.list?.find((m) => Number(m.id) === id);
            return item ? (item._ai?.tags ?? []) : null;
          },
          saveTags: async (id, tags) => {
            const r = await relay.patch<{ item?: { tags?: string[] } }>(`/admin/vault-ai/items/${id}`, { account_id: accountId, fields: { tags } }, ctx);
            return r.item?.tags ?? tags;
          },
          confirm: (text) => window.confirm(text),
        }
      : null;
    let unbind: (() => void) | undefined;
    const bind = () => {
      unbind?.();
      const doc = frame.contentDocument;
      unbind = doc?.body ? bindVault(doc, page, { view, edit: sp.get("edit") === "1", customize: sp.get("customize") === "1", minDate, lists: accountId ? lists : undefined, navigate: (href) => router.push(href), handlers }) : undefined;
    };
    if (frame.contentDocument?.readyState === "complete") bind();
    frame.addEventListener("load", bind);
    return () => {
      frame.removeEventListener("load", bind);
      unbind?.();
    };
  }, [frameRef, src, page, isVault, query, accountId, lists, minDate, qc, router]);
}
