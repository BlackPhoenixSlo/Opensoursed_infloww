"use client";

/**
 * A chat's thread tools on the OF mirror, as OF's own web app has them (its chats module 204607 and the chat header,
 * chunk 42549; the message item, 82027; the gallery grid item; ledger `.scratch/omf-messages-full/ledger.md`):
 *
 * - Find (the header's "Find"): OF's find bar (`m-search-form-visible` on the header). 3+ characters search 500 ms after
 *   the last key, Enter at once: GET /api/of/v2/chats/<fanId>/messages/search?query= (OF's flat list of message ids,
 *   newest first). The bar counts "1/3"; its up arrow walks to an older hit, the down arrow to a newer one. A hit not drawn
 *   yet is reached by loading the thread's older pages (before_id; the Relay has no `firstId` window, so up to
 *   FIND_PAGES pages, as Messages Pro's ChatSearch), then centred, the query marked in it
 *   (`b-chat__message__text-highlighted`). Closing the bar clears it. A gallery tile's `?firstId=<message>` opens the
 *   chat at that message the same way.
 * - Gallery (messages/chat/gallery): the chat's media messages, a tile each (OF's grid item: the sender's avatar, the
 *   first picture, a play button on a video or GIF, the price label on a PPV, its media counts or length), a locked tile
 *   (OF's lock card with the price) for a PPV the Creator cannot view, a tile linking to the chat at that message. Its
 *   tabs are OF's: All, Unlocked (`opened=1`), Purchased (`purchased=1&from_user=<Creator>`), Photos, Videos, Audio (the
 *   type is a path segment, /media/photos). Read through Messages Pro's useFanChatMedia, 20 a page by OF's `last_id`
 *   cursor as the grid is scrolled to its end.
 * Nothing here writes or marks a chat read.
 */

import { useCallback, useEffect, useRef, type RefObject } from "react";
import { relay, type OFMedia, type OFMessage, type OFUserMini } from "@/lib/relay";
import { duration, fill, make, nameOf, setAttr, setAvatar, setText, THREAD_BOX, track } from "@/lib/ofMirrorData";
import { message, note } from "@/lib/ofMirrorWrites";
import { fanIdFromParam } from "@/lib/fanId";
import type { ChatMediaKind } from "@/hooks/useFanChatMedia";

/** OF's fields on a chat message the shared type does not name (OFW 82027: tips, purchases, media readiness). */
export type ThreadMessage = OFMessage & {
  tipAmount?: number | null;
  tipText?: string | null;
  isFundRaisingTip?: boolean;
  canPurchase?: boolean;
  canPurchaseReason?: string;
};

// ---------------------------------------------------------------- shared

const CHAT = "/of-manager/messages/chat";
export const GALLERY_PAGE = `${CHAT}/gallery`;
export const PINNED_PAGE = `${CHAT}/pinned`;

/** A chat page's link: the open chat, the chat list's view kept, `extra` after it. */
export function chatHref(path: string, chat: string, listQuery = "", extra = ""): string {
  return `${path}?chat=${encodeURIComponent(chat)}${listQuery ? `&${listQuery}` : ""}${extra ? `&${extra}` : ""}`;
}

/** OF's price words: "$5", "$15.99". */
export const dollars = (n: number | null | undefined) => `$${Number.isInteger(n ?? 0) ? n ?? 0 : (n ?? 0).toFixed(2)}`;

/** An SVG sprite icon as OF draws it (the page's own sprite has every icon the Messages pages draw: MESSAGES_ICONS). */
export function icon(doc: Document, name: string, cls = "g-icon"): SVGSVGElement {
  const svg = doc.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("class", cls);
  svg.setAttribute("data-icon-name", name);
  svg.setAttribute("aria-hidden", "true");
  const use = doc.createElementNS("http://www.w3.org/2000/svg", "use");
  use.setAttribute("href", `#${name}`);
  use.setAttribute("xlink:href", `#${name}`);
  svg.appendChild(use);
  return svg;
}

/** Point an existing sprite icon at `name`. */
export function setIconName(svg: Element | null | undefined, name: string) {
  if (!svg) return;
  svg.setAttribute("data-icon-name", name);
  for (const use of svg.querySelectorAll("use")) {
    use.setAttribute("href", `#${name}`);
    use.setAttribute("xlink:href", `#${name}`);
  }
}

const KIND_ICON: Record<string, string> = { photo: "icon-media", video: "icon-video", audio: "icon-voice", gif: "icon-gif" };

/**
 * OF's attachment icons for a message's media (its `listOfAttachmentIcons`): photos with their count; videos, audio and
 * GIFs with their count when more than one, else the length; then a text frame when the message has words.
 */
export function attachmentIcons(media: readonly OFMedia[], hasText = false): { icon: string; content: string | null }[] {
  const out: { icon: string; content: string | null }[] = [];
  for (const kind of ["photo", "video", "audio", "gif"]) {
    const of = media.filter((m) => m.type === kind);
    if (!of.length) continue;
    const secs = of[0].duration ?? 0;
    out.push({ icon: KIND_ICON[kind], content: kind === "photo" || of.length > 1 ? String(of.length) : secs > 0 ? duration(secs) : null });
  }
  if (hasText) out.push({ icon: "icon-text-frame-off", content: null });
  return out;
}

/** Fill OF's `ul.b-purchase__list` with `icons`, each a copy of its first item (its icon and count re-pointed). */
export function fillIcons(list: Element | null, icons: { icon: string; content: string | null }[]) {
  if (!list) return;
  const tpl = list.querySelector("li");
  if (!tpl) return;
  const items = icons.map(({ icon: name, content }) => {
    const li = tpl.cloneNode(true) as HTMLElement;
    setIconName(li.querySelector("svg"), name);
    const count = li.querySelector(".b-purchase__list-item__count");
    if (content === null) count?.remove();
    else if (count) count.textContent = ` ${content} `;
    else {
      const span = list.ownerDocument.createElement("span");
      span.className = "b-purchase__list-item__count";
      span.textContent = ` ${content} `;
      li.appendChild(span);
    }
    return li;
  });
  list.replaceChildren(...items);
}

// ---------------------------------------------------------------- gallery

/** The gallery's tabs: OF's media path segment (photos, videos, audios), its Unlocked or Purchased filter, or All. */
export type GalleryTab = "all" | "opened" | "purchased" | ChatMediaKind;
const GALLERY_TABS: readonly GalleryTab[] = ["all", "opened", "purchased", "photos", "videos", "audios"];

/** The open tab from the app URL's `?media=` (All without one). */
export function galleryTab(params: { get(key: string): string | null }): GalleryTab {
  const v = params.get("media");
  return (GALLERY_TABS as readonly string[]).includes(v ?? "") ? (v as GalleryTab) : "all";
}

/**
 * useFanChatMedia's options for a tab: every message both ways (All, a type), the fan's viewed ones (Unlocked:
 * `opened=1`), or the Creator's PPVs the fan paid for (Purchased: `purchased=1&from_user=<Creator>`, OF's call).
 */
export function galleryRequest(tab: GalleryTab): { purchased: boolean; creatorOnly: boolean; opened?: boolean; kind?: ChatMediaKind } {
  if (tab === "purchased") return { purchased: true, creatorOnly: true };
  if (tab === "opened") return { purchased: false, creatorOnly: false, opened: true };
  if (tab === "all") return { purchased: false, creatorOnly: false };
  return { purchased: false, creatorOnly: false, kind: tab };
}

export interface GalleryData {
  tab: GalleryTab;
  /** The tiles so far, newest first; undefined while the first page is read (or after it failed). */
  items?: ThreadMessage[];
  /** null: the first page is being read; a string: it failed. */
  status?: string | null;
  /** The next page is being read. */
  more?: boolean;
  /** OF has more pages (a page whose items all drew no tile still has its next one asked for). */
  next?: boolean;
  /** The next page failed: its error, shown under the grid (no more pages are asked for). */
  moreError?: string;
}

const GRID = ".b-gallery-wrapper .b-photos";
const PROMPT = ".b-gallery-wrapper [data-oi-empty]";
const PRELOADER = "oi-gallery-more";

/** The picture a tile shows: its first photo, video or GIF's thumb (OF's grid item), else any still. */
const thumbOf = (media: readonly OFMedia[]) => {
  const m = media.find((x) => ["photo", "video", "gif"].includes(x.type ?? "") && x.canView !== false);
  return (m?.files?.thumb?.url as string | undefined) ?? (m?.files?.squarePreview?.url as string | undefined) ?? (m?.files?.preview?.url as string | undefined) ?? null;
};

function galleryTile(tpls: Record<string, Element>, m: ThreadMessage, chat: string, ctx: GalleryContext): HTMLElement | null {
  const doc = ctx.doc;
  const media = m.media ?? [];
  const mine = String(m.fromUser?.id ?? "") !== chat;
  const pic = thumbOf(media);
  const href = chatHref(CHAT, chat, ctx.listQuery, `firstId=${encodeURIComponent(String(m.id))}`);
  // A PPV the Creator cannot view (another creator's, in OF's own words "chat-purchase"): OF's lock card with its price.
  if (!pic && (m.price ?? 0) > 0 && media.some((x) => x.canView === false)) {
    const el = make(tpls.locked);
    el.removeAttribute("style");
    const a = el.querySelector("a");
    a?.setAttribute("href", href);
    a?.setAttribute("target", "_top");
    const price = el.querySelector(".b-post__unknown__price");
    if (price) price.textContent = ` ${dollars(m.price)} `;
    fillIcons(el.querySelector(".b-purchase__list"), attachmentIcons(media));
    return el;
  }
  const visible = media.filter((x) => x.canView !== false);
  // Nothing viewable at all: no tile. A viewable item with no picture (a voice note, an audio file) is OF's tile with its
  // kind's icon in place of the picture.
  if (!pic && !visible.length) return null;
  const moving = visible.some((x) => x.type === "video" || x.type === "gif");
  const el = make(moving ? tpls.video : tpls.photo);
  el.removeAttribute("style");
  el.setAttribute("href", href);
  el.setAttribute("target", "_top");
  const img = el.querySelector<HTMLImageElement>("img.b-photos__item__img");
  if (pic) img?.setAttribute("src", ctx.img(pic));
  else if (img) {
    const ph = doc.createElement("div");
    ph.className = img.className;
    ph.dataset.oiNoThumb = "";
    ph.style.cssText = "display:flex;align-items:center;justify-content:center;background:rgba(138,150,163,.12);color:#8a96a3";
    ph.appendChild(icon(doc, KIND_ICON[visible[0]?.type ?? ""] ?? "icon-media", "g-icon"));
    img.replaceWith(ph);
  }
  const who = mine ? ctx.me : ctx.fan;
  const avatar = el.querySelector(".g-avatar");
  if (who) setAvatar(avatar, who, ctx.img);
  else avatar?.remove();
  // OF's play button only when the first visible media moves.
  if (!["gif", "video", "audio"].includes(visible[0]?.type ?? "")) el.querySelector(".b-photos__item__play-btn")?.remove();
  // A PPV's price label: unlocked once the fan opened it, locked while the Creator's own is unpaid (OF's paidStatus).
  if (!m.isFree && (m.price ?? 0) > 0 && (m.isOpened || mine)) {
    const label = doc.createElement("span");
    label.className = "b-element-label m-payment-label m-position-compact";
    label.append(` ${dollars(m.price)} `, icon(doc, m.isOpened ? "icon-unlocked" : "icon-locked", "m-icon-extra-sm g-icon"));
    el.querySelector(".b-subscribe-block")?.before(label);
  }
  fillIcons(el.querySelector(".b-purchase__list"), attachmentIcons(media, !!(m.text && m.text.replace(/<[^>]+>/g, "").trim())));
  return el;
}

export interface GalleryContext {
  doc: Document;
  img: (u: string) => string;
  fan: OFUserMini | null;
  me: OFUserMini | null;
  listQuery: string;
}

/**
 * The gallery page for `chat`: its tabs link to that chat's views (the open one current), and its grid shows `g`'s
 * tiles (OF's "Nothing found" when there are none; "Loading media…" or the red error before the first page).
 */
export function applyGallery(ctx: GalleryContext, chat: string, g: GalleryData) {
  const { doc } = ctx;
  for (const a of doc.querySelectorAll<HTMLAnchorElement>("a[data-oi-gallery]")) {
    const tab = a.dataset.oiGallery as GalleryTab;
    setAttr(doc, a, "href", chatHref(GALLERY_PAGE, chat, ctx.listQuery, tab === "all" ? "" : `media=${tab}`));
    const on = tab === g.tab;
    for (const c of ["router-link-active", "m-current", "m-no-pointer"]) if (a.classList.contains(c) !== on) {
      a.classList.toggle(c, on);
      track(doc, () => a.classList.toggle(c, !on));
    }
    setAttr(doc, a, "aria-current", on ? "page" : null);
    setAttr(doc, a, "tabindex", on ? "-1" : "0");
  }
  const grid = doc.querySelector(GRID);
  const prompt = doc.querySelector<HTMLElement>(PROMPT);
  const text = prompt?.querySelector<HTMLElement>(".empty-message > span");
  if (!grid) return;
  const tpls = Object.fromEntries([...grid.querySelectorAll<HTMLElement>("[data-oi-tile]")].map((t) => [t.dataset.oiTile!, t]));
  if (!tpls.photo || !tpls.video || !tpls.locked) return;
  const tiles = (g.items ?? []).flatMap((m) => galleryTile(tpls, m, chat, ctx) ?? []);
  if (tiles.length) fill(doc, [tpls.photo, tpls.video, tpls.locked], tiles, [grid]);
  if (prompt && text) {
    const was = text.textContent;
    track(doc, () => {
      text.textContent = was;
      text.style.removeProperty("color");
      prompt.style.removeProperty("display");
    });
    if (tiles.length) prompt.style.display = "none";
    else if (g.status === null || !g.items || ((g.next || g.more) && !g.moreError)) {
      // Before the first page, or while pages with no tile are followed by their next one: still loading.
      text.textContent = typeof g.status === "string" ? `Could not load media: ${g.status}` : "Loading media…";
      if (typeof g.status === "string") text.style.color = "#ff4545";
    } else if (g.moreError) {
      text.textContent = `Could not load media: ${g.moreError}`;
      text.style.color = "#ff4545";
    }
    if (!tiles.length && (typeof g.status === "string" || g.moreError)) {
      const retry = retryButton(doc);
      text.after(retry);
      track(doc, () => retry.remove());
    }
  }
  // The next page's error under the grid (the grid keeps its tiles).
  if (g.moreError && tiles.length) {
    const box = doc.createElement("div");
    box.id = PRELOADER;
    box.className = "empty-message";
    box.style.cssText = "padding:10px 16px;font-size:14px;color:#ff4545;text-align:center";
    box.textContent = `Could not load more media: ${g.moreError}`;
    box.append(retryButton(doc));
    grid.after(box);
    track(doc, () => box.remove());
  }
  // OF's loader under the grid while the next page is read.
  if (g.more && tiles.length) {
    const box = doc.createElement("div");
    box.id = PRELOADER;
    box.className = "b-posts_preloader m-gaps";
    box.appendChild(icon(doc, "icon-loading"));
    grid.after(box);
    track(doc, () => box.remove());
  }
}

/** The gallery's Retry after a failed page (ofMirrorData reads its click). */
function retryButton(doc: Document): HTMLButtonElement {
  const b = doc.createElement("button");
  b.type = "button";
  b.className = "g-btn m-flat m-btn-gaps m-reset-width";
  b.setAttribute("data-oi-gallery-retry", "");
  b.style.cssText = "display:block;margin:8px auto 0";
  b.textContent = "Retry";
  return b;
}

/** The gallery header's "with <name>" (and the pinned page's): OF's `message.pretext_with`. */
export function applyWith(doc: Document, fan: OFUserMini | null) {
  if (!fan) return;
  for (const el of doc.querySelectorAll(".b-gallery-wrapper .b-chat__user-status, [data-oi-with]")) setText(doc, el, `with ${nameOf(fan)}`);
}

// ---------------------------------------------------------------- find

/** OF's find: the fewest characters it searches by itself, and its debounce. */
export const FIND_MIN = 3;
export const FIND_MS = 500;
/** How many older pages a hit not drawn yet is looked for in (Messages Pro's ChatSearch: 12). */
export const FIND_PAGES = 12;
/** A hit older than FIND_PAGES pages back (the Relay has no `firstId` window to open the thread at it). */
export const TOO_FAR = "This message is too far back to show";
const HIGHLIGHT = "b-chat__message__text-highlighted";

// The chat header's find bar (the chat list's header has its own, `m-with-bg`, ofMirrorChats').
const findForm = (doc: Document) => doc.querySelector<HTMLFormElement>(".b-chat__header form.b-chat__search-form.m-absolute");
const header = (doc: Document) => findForm(doc)?.closest<HTMLElement>(".b-chat__header") ?? null;
const findInput = (doc: Document) => findForm(doc)?.querySelector<HTMLInputElement>("input[name='query']") ?? null;
const findBtn = (doc: Document) => doc.querySelector<HTMLButtonElement>("button[at-attr='search_btn']");

export interface FindContext {
  /** OF's message search: the matching message ids, newest first. */
  search(query: string): Promise<string[]>;
  /** Draw message `id` if it is not yet (older pages), true once it is drawn; `stale()` true: give up (a newer search). */
  reveal(id: string, stale: () => boolean): Promise<boolean>;
}

/** The thread's message `id` (its bubble), if drawn. */
export const bubbleOf = (doc: Document, id: string) => doc.querySelector<HTMLElement>(`${THREAD_BOX} .b-chat__item-message[data-oi-data] [data-oi-msg="${CSS.escape(id)}"]`);

/** Unwrap every highlighted match. */
function clearHighlight(doc: Document) {
  for (const h of [...doc.querySelectorAll(`.${HIGHLIGHT}`)]) h.replaceWith(...h.childNodes);
}

/** Mark `query` in message `id`'s text (case-insensitive, as OF's), and centre the message when `center`. */
export function highlight(doc: Document, id: string, query: string, center: boolean) {
  clearHighlight(doc);
  const el = bubbleOf(doc, id);
  if (!el) return;
  const q = query.trim().toLowerCase();
  const holder = el.querySelector(".b-chat__message__text-holder");
  if (holder && q) {
    const walk = doc.createTreeWalker(holder, NodeFilter.SHOW_TEXT);
    const nodes: Text[] = [];
    for (let n = walk.nextNode(); n; n = walk.nextNode()) nodes.push(n as Text);
    for (const node of nodes) {
      const text = node.data;
      const lower = text.toLowerCase();
      if (!lower.includes(q)) continue;
      const frag = doc.createDocumentFragment();
      let at = 0;
      for (let i = lower.indexOf(q); i >= 0; i = lower.indexOf(q, i + q.length)) {
        frag.append(text.slice(at, i));
        const mark = doc.createElement("span");
        mark.className = HIGHLIGHT;
        mark.textContent = text.slice(i, i + q.length);
        frag.append(mark);
        at = i + q.length;
      }
      frag.append(text.slice(at));
      node.replaceWith(frag);
    }
  }
  if (center) centre(doc, el);
}

/** Scroll the thread so `el` sits in its middle (OF's verticallyCenterMessage). */
export function centre(doc: Document, el: HTMLElement) {
  const box = doc.querySelector<HTMLElement>(THREAD_BOX);
  if (!box) return;
  const top = el.getBoundingClientRect().top - box.getBoundingClientRect().top + box.scrollTop;
  box.scrollTop = Math.max(0, top - (box.clientHeight - el.offsetHeight) / 2);
}

/**
 * Wire the chat header's Find in `doc`. Returns its teardown and `redrawn` (call after every thread redraw: the
 * current hit's mark is put back, the view left where it is).
 */
export function bindFind(doc: Document, ctx: FindContext): { dispose: () => void; redrawn: () => void } {
  const state = { ids: [] as string[], index: null as number | null, query: "", searching: false, searched: false, gen: 0 };
  let timer: ReturnType<typeof setTimeout> | undefined;
  const btn = findBtn(doc);
  const form = findForm(doc);
  const input = findInput(doc);
  const submit = form?.querySelector<HTMLButtonElement>("button[type='submit']");
  // Its controls are this binder's: never the read-only note (ofMirrorWrites).
  for (const el of [btn, input, submit, form?.querySelector("button[at-attr='close_search']")]) el?.setAttribute("data-oi-wired", "");

  const nav = () => {
    const wrap = form?.querySelector(".b-search-form__wrapper");
    if (!wrap) return;
    let box = wrap.querySelector<HTMLElement>(".b-chat__search__results-nav");
    if (!state.searched) return box?.remove();
    if (!box) {
      box = doc.createElement("div");
      box.className = "b-chat__search__results-nav";
      const count = doc.createElement("span");
      count.className = "b-chat__search__results-count";
      count.setAttribute("at-attr", "search_results_count");
      box.appendChild(count);
      for (const [dir, name, title] of [["prev", "icon-arrow-up", "Previous"], ["next", "icon-arrow-down", "Next"]] as const) {
        const b = doc.createElement("button");
        b.type = "button";
        b.className = `b-chat__search__results-nav-btn g-btn m-with-round-hover m-icon m-icon-only m-sm-size ml-0 m-${dir}`;
        b.dataset.oiFind = dir;
        b.setAttribute("aria-label", title);
        b.setAttribute("data-oi-wired", "");
        b.appendChild(icon(doc, name, "m-default-size g-icon"));
        box.appendChild(b);
      }
      wrap.appendChild(box);
    }
    const n = state.ids.length;
    box.querySelector(".b-chat__search__results-count")!.textContent = ` ${n ? (state.index ?? 0) + 1 : 0}/${n} `;
    // OF: up (older) is off at the oldest hit, down (newer) at the newest.
    const off = { prev: (state.index ?? 0) + 1 >= n, next: (state.index ?? 0) <= 0 };
    for (const b of box.querySelectorAll<HTMLButtonElement>("[data-oi-find]")) {
      const d = off[b.dataset.oiFind as "prev" | "next"];
      b.disabled = d;
      b.classList.toggle("m-gray", d);
    }
  };
  const busy = (on: boolean) => {
    if (!on && !state.searching) return;
    state.searching = on;
    if (submit) {
      submit.disabled = on;
      submit.classList.toggle("m-gray", on);
    }
    const wrap = form?.querySelector(".b-search-form__wrapper");
    let line = wrap?.querySelector<HTMLElement>(".b-preloader-line");
    if (on && wrap && !line) {
      line = doc.createElement("div");
      line.className = "b-preloader-line";
      wrap.appendChild(line);
    } else if (!on) line?.remove();
  };
  const go = async (index: number) => {
    const gen = state.gen;
    state.index = index;
    nav();
    const id = state.ids[index];
    if (id === undefined) return;
    const stale = () => gen !== state.gen || state.index !== index;
    const shown = await ctx.reveal(id, stale);
    if (stale()) return;
    if (shown) highlight(doc, id, state.query, true);
    else if (form) note(doc, form, TOO_FAR, true);
  };
  /** A new query supersedes the one running (its search, or its older pages being read for a hit). */
  const run = async (q: string) => {
    if (!q.length) return;
    const gen = ++state.gen;
    clearHighlight(doc);
    state.index = null;
    busy(true);
    try {
      const ids = await ctx.search(q);
      if (gen !== state.gen) return;
      state.ids = ids;
      state.query = q;
      state.searched = true;
      nav();
      if (ids.length) await go(0);
    } catch (e) {
      if (gen === state.gen && form) note(doc, form, `Could not search this chat: ${message(e)}`, true);
    } finally {
      if (gen === state.gen) busy(false);
    }
  };
  const reset = () => {
    state.gen++;
    state.ids = [];
    state.index = null;
    state.query = "";
    state.searched = false;
    clearHighlight(doc);
    busy(false);
    nav();
  };
  const show = (on: boolean) => {
    const h = header(doc);
    h?.classList.toggle("m-search-form-visible", on);
    h?.classList.toggle("m-reset-bottom-line", on);
    btn?.classList.toggle("m-active", on);
    if (on) input?.focus();
    else {
      clearTimeout(timer);
      if (input) input.value = "";
      reset();
    }
  };

  const onClick = (ev: MouseEvent) => {
    const t = ev.target as Element | null;
    if (!t?.closest) return;
    if (btn && t.closest("button[at-attr='search_btn']") === btn) {
      ev.preventDefault();
      return show(!header(doc)?.classList.contains("m-search-form-visible"));
    }
    if (form && t.closest("button[at-attr='close_search']") && form.contains(t)) {
      ev.preventDefault();
      return show(false);
    }
    const step = t.closest<HTMLButtonElement>("[data-oi-find]");
    if (step && form?.contains(step)) {
      ev.preventDefault();
      if (step.disabled || state.index === null) return;
      void go(Math.max(0, state.index + (step.dataset.oiFind === "prev" ? 1 : -1)));
    }
  };
  const onInput = (ev: Event) => {
    if (!input || ev.target !== input) return;
    clearTimeout(timer);
    timer = setTimeout(() => {
      const v = input.value;
      if (!v.length) return state.searched ? reset() : undefined;
      if (v.trim().length >= FIND_MIN) void run(v.trim());
    }, FIND_MS);
  };
  const onSubmit = (ev: Event) => {
    if (!form || ev.target !== form) return;
    ev.preventDefault();
    ev.stopPropagation();
    clearTimeout(timer);
    void run((input?.value ?? "").trim());
  };
  doc.addEventListener("click", onClick, true);
  doc.addEventListener("input", onInput, true);
  doc.addEventListener("submit", onSubmit, true);
  return {
    dispose: () => {
      // The bar closes with the binding (another chat opens with no query, count or mark from this one).
      show(false);
      btn?.blur();
      doc.removeEventListener("click", onClick, true);
      doc.removeEventListener("input", onInput, true);
      doc.removeEventListener("submit", onSubmit, true);
    },
    redrawn: () => {
      const id = state.index !== null ? state.ids[state.index] : undefined;
      if (id !== undefined) highlight(doc, id, state.query, false);
    },
  };
}

/** OF's search answer: a flat id list (or `{list}`), as strings. */
export const searchIds = (r: unknown): string[] => (Array.isArray(r) ? r : Array.isArray((r as { list?: unknown })?.list) ? (r as { list: unknown[] }).list : []).map((v) => String(typeof v === "object" && v !== null && "id" in v ? (v as { id: unknown }).id : v));

const settle = (doc: Document, id: string, ms: number) =>
  new Promise<boolean>((resolve) => {
    const win = doc.defaultView;
    const end = Date.now() + ms;
    const tick = () => {
      if (bubbleOf(doc, id)) return resolve(true);
      if (Date.now() > end || !win) return resolve(false);
      win.setTimeout(tick, 50);
    };
    tick();
  });

interface ThreadPaging {
  hasOlder: boolean;
  loadOlder: () => Promise<{ added: number; hasMore: boolean }>;
}

/**
 * The chat page's Find and `?firstId=` jump (see the module comment), for useOfData: `thread` is its useChatMessages
 * (older pages by before_id, shared with the scroll-up loader), `drawn` changes with every redraw.
 */
export function useThreadFind(frameRef: RefObject<HTMLIFrameElement | null>, src: string, on: boolean, accountId: string | null, chat: string | null, firstId: string | null, thread: ThreadPaging, drawn: unknown, pinned = false) {
  const paging = useRef(thread);
  paging.current = thread;
  const bound = useRef<{ doc: Document; redrawn: () => void } | null>(null);
  const jumped = useRef<string | null>(null);
  const want = useRef({ chat, firstId });
  want.current = { chat, firstId };

  /** Older pages until `id` is drawn: at most FIND_PAGES reads (one still in flight is waited for, not counted). */
  const reveal = useCallback(async (doc: Document, id: string, stale: () => boolean = () => false) => {
    let reads = 0;
    for (let tries = 0; tries <= FIND_PAGES * 3; tries++) {
      if (await settle(doc, id, tries === 0 ? 0 : 3000)) return true;
      if (stale() || reads >= FIND_PAGES || !paging.current.hasOlder) return false;
      const r = await paging.current.loadOlder().catch(() => ({ added: 0, hasMore: false }));
      if (r.added) reads++;
      else if (!r.hasMore) return settle(doc, id, 3000);
    }
    return false;
  }, []);

  /** A gallery tile's ?firstId=: once per page load, as soon as the thread has drawn. */
  const jump = useCallback(() => {
    const b = bound.current;
    const { chat: c, firstId: id } = want.current;
    if (!id) jumped.current = null;
    const key = id && c ? `${c}:${id}` : null;
    if (!b || !key || jumped.current === key || !b.doc.querySelector(`${THREAD_BOX} [data-oi-msg]`)) return;
    jumped.current = key;
    const doc = b.doc;
    // Another chat or firstId, or another frame document: stop paging (it would page the new chat) and stay quiet.
    const stale = () => want.current.chat !== c || want.current.firstId !== id || bound.current?.doc !== doc;
    void reveal(doc, id!, stale).then((shown) => {
      if (stale()) return;
      const el = bubbleOf(doc, id!);
      if (shown && el) centre(doc, el);
      else if (!el) {
        const form = findForm(doc);
        if (form) note(doc, form, TOO_FAR, true);
      }
    });
  }, [reveal]);

  useEffect(() => {
    const frame = frameRef.current;
    if (!frame || !on || !chat || !accountId) return;
    const fanId = fanIdFromParam(chat);
    let undo: (() => void) | null = null;
    const attach = () => {
      undo?.();
      const doc = frame.contentDocument;
      if (!doc?.body) return;
      const find = bindFind(doc, {
        // The pinned page searches its pins (OF's filter=pinned); its hits are the pins drawn (a Relay that drops the
        // filter answers every message's).
        search: async (q) => {
          const ids = searchIds(await relay.get<unknown>(`/api/of/v2/chats/${encodeURIComponent(String(fanId))}/messages/search?query=${encodeURIComponent(q)}${pinned ? "&filter=pinned" : ""}`, { accountId }));
          return pinned ? ids.filter((id) => bubbleOf(doc, id)) : ids;
        },
        reveal: (id, stale) => reveal(doc, id, stale),
      });
      bound.current = { doc, redrawn: find.redrawn };
      // A new page load (the same gallery tile clicked again) jumps again, at once if the thread is already drawn.
      jumped.current = null;
      jump();
      undo = () => {
        find.dispose();
        bound.current = null;
      };
    };
    if (frame.contentDocument?.readyState === "complete") attach();
    frame.addEventListener("load", attach);
    return () => {
      frame.removeEventListener("load", attach);
      undo?.();
    };
  }, [frameRef, src, on, accountId, chat, reveal, jump, pinned]);

  // Every redraw: the current hit's mark back; the ?firstId= jump once its message can be drawn.
  useEffect(() => {
    const b = bound.current;
    if (!b || !on || !chat) return;
    b.redrawn();
    jump();
  }, [drawn, on, chat, firstId, jump]);
}
