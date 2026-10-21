"use client";

/**
 * Post actions on the OF mirror's real post rows (Home's feed, My profile's wall, All bookmarks): ofMirrorFeeds marks
 * each with data-oi-post (the post's id) and, when known, data-oi-author. With a single model selected:
 * - Like (OF's heart): POST /api/of/v2/posts/{id}/like, with ?author_id= on another creator's post (OF likes with
 *   /posts/{id}/favorites/{authorId}); the same POST again unlikes, as on OF. The button shows m-active and the row's
 *   Likes count follows. A disabled heart (the Creator's own post) does nothing.
 * - Comments (OF's speech bubble, and the row's "N Comments", OF's "Show post comments"): a box under the post's tools
 *   with its comments (GET /posts/{id}/comments) and a field; Send (or Enter) posts {text} to /posts/{id}/comments, then
 *   reloads the list. A second click closes the box.
 * - On the Creator's own post: the row's "N Likes" (OF's "Show who liked this post") opens OF's user list of its likers
 *   (GET /posts/likes?post_id, ofMirrorStatsKit's "post-likes"). Its Post statistics (disabled by the generator: the
 *   popup shows the post's earnings) is enabled and opens OF's Post statistics popup (GET /posts/stats?post_id,
 *   ofMirrorStatsPostStat) only for a role with Statistics on a Relay that has the route (postStatsProbe).
 * - More, on the Creator's own post (no author, or the Creator's id): OF's dropdown with Pin to / Unpin from your
 *   profile page (POST /posts/{id}/pin, OF's toggle), Edit post (its text in place: PUT /posts/{id} {text}, the
 *   relay's sparse edit, so media and price stay), Archive post (POST /posts/{id}/archive) and Delete post (DELETE
 *   /posts/{id}, only on a second click, which the item asks for). Each success refetches the page's rows.
 *   Another creator's post's More has OF's "Copy link to post" only (https://onlyfans.com/<post id>/<author's handle>,
 *   to the clipboard; hide and report have no Relay route), disabled with the tooltip without the handle (ofMirrorFeeds).
 * A failure shows the status note in red. The clicks it owns never reach bindWrites' click fallback, and the boxes it
 * adds are data-oi-wired (their fields are not the read-only change path's).
 */

import { useEffect, type RefObject } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useScope } from "@/contexts/ScopeContext";
import { relay, type OFUserMini } from "@/lib/relay";
import { nameOf, plain } from "@/lib/ofMirrorData";
import { ofMeQuery } from "@/lib/ofMirrorIdentity";
import { message, note, NOT_YET } from "@/lib/ofMirrorWrites";
import { useAppliedSettings } from "@/lib/appliedSettings";
import { proxyImage } from "@/lib/mediaUrl";
import { bindUserLists, openUsers } from "@/lib/ofMirrorStatsKit";
import { openPostStats, postStatsProbe } from "@/lib/ofMirrorStatsPostStat";
import { useGrantedPages } from "@/components/shell/useGrantedPages";

export interface PostHandlers {
  /** The Creator's OnlyFans id: a row by another author is not the Creator's own. */
  me: string | null;
  write(method: "POST" | "PUT" | "DELETE", path: string, body?: object): Promise<unknown>;
  read(path: string): Promise<unknown>;
  /** Refetch the page's rows (a pin, edit, archive or delete changed them). */
  refresh(): void;
  /** Open the list of who liked the Creator's own post `id` (OF's UserList PostLikes). */
  likes(id: string, opener: Element): void;
  /** Open OF's Post statistics popup for the Creator's own post `id`; null: Post statistics stays disabled. */
  stats: ((id: string, opener: Element) => void) | null;
}

const ROW = "[data-oi-post]";
const LIKE = ".set-favorite-btn";
const COMMENT = ".send-comment-btn";
const MORE = ".b-post__tools__more button";
const MENU = "[data-oi-post-menu]";
const BOX = "[data-oi-comments]";
const EDIT = "[data-oi-edit]";
export const ARM = "Click again to delete";
const LIKES = "post-stat-likes";
const COMMENTS = "post-stat-comments";
const STAT = ".b-summary-list a[data-testid]";
/** The own-post text button: Post statistics (another creator's row has Send Tip there, ofMirrorFeeds' sendTip). */
const POST_STATS = ".b-post__tools__item.m-with-text-button button:not([at-attr='post_tip'])";

export const postPath = (id: string) => `/api/of/v2/posts/${encodeURIComponent(id)}`;

/** The More menu's items: action, label (pin's by the row's state), OF's danger mark; another creator's post: its link only. */
const items = (pinned: boolean, own = true): [string, string, boolean][] => own ? [
  ["pin", pinned ? "Unpin from your profile page" : "Pin to your profile page", false],
  ["edit", "Edit post", false],
  ["archive", "Archive post", false],
  ["delete", "Delete post", true],
] : [["copy", "Copy link to post", false]];

/** The row's Likes or Comments count (OF's test id `id`), plus `delta`; its word follows (a row with no such count is left alone). */
function bump(row: Element, id: string, word: string, delta: number) {
  const span = row.querySelector(`.b-summary-list a[data-testid='${id}'] > span`);
  if (!span) return;
  const n = Math.max(0, (Number(span.textContent) || 0) + delta);
  span.textContent = String(n);
  if (span.nextSibling?.nodeType === 3) span.nextSibling.textContent = ` ${word}${n === 1 ? "" : "s"}`;
}

const button = (doc: Document, text: string, mark: string) => {
  const b = doc.createElement("button");
  b.type = "button";
  b.className = "g-btn m-rounded m-sm-size";
  b.setAttribute(mark, "");
  b.textContent = text;
  return b;
};

/** Close every open More menu. */
function closeMenus(doc: Document) {
  for (const m of doc.querySelectorAll(MENU)) {
    const wrapper = m.closest(".b-dropdown-wrapper");
    wrapper?.classList.remove("m-show-dropdown");
    wrapper?.querySelector("button")?.setAttribute("aria-expanded", "false");
    m.remove();
  }
}

/** OF's dropdown markup (as the captured profile menu) under the post's More button. */
function openMenu(doc: Document, row: Element, more: Element, own = true) {
  const wrapper = more.closest(".b-dropdown-wrapper") ?? more.parentElement!;
  const scope = [...wrapper.attributes].filter((a) => a.name.startsWith("data-v-"));
  const menu = doc.createElement("div");
  menu.setAttribute("role", "menu");
  menu.setAttribute("data-oi-post-menu", "");
  menu.className = "of-state-menu v-menu__content theme--light menuable__content__active m-dropdown-list";
  menu.style.minWidth = "220px";
  const list = doc.createElement("div");
  list.className = "v-list m-dropdown-v-list v-sheet theme--light shown";
  for (const el of [menu, list]) for (const a of scope) el.setAttribute(a.name, a.value);
  for (const [action, label, danger] of items(!!row.querySelector("div.b-post.m-pinned"), own)) {
    const item = doc.createElement("div");
    item.setAttribute("role", "menuitem");
    item.tabIndex = 0;
    item.className = `v-list-item v-list-item--link theme--light m-with-rectangle-hover m-tb-sm${danger ? " m-danger" : ""}`;
    item.dataset.oiAction = action;
    item.textContent = ` ${label} `;
    list.appendChild(item);
  }
  menu.appendChild(list);
  wrapper.appendChild(menu);
  wrapper.classList.add("m-show-dropdown");
  more.setAttribute("aria-expanded", "true");
}

/** A comments list's rows: each comment's author name and plain text; or why there are none. */
function showComments(doc: Document, list: Element, r: unknown) {
  const o = r as { list?: unknown } | null | undefined;
  const rows = (Array.isArray(r) ? r : Array.isArray(o?.list) ? o.list : []) as { text?: string | null; author?: OFUserMini }[];
  if (!rows.length) {
    list.textContent = "No comments yet";
    return;
  }
  list.replaceChildren(
    ...rows.map((c) => {
      const item = doc.createElement("div");
      item.className = "b-comments__item";
      item.style.cssText = "padding:4px 0";
      const name = doc.createElement("span");
      name.className = "g-user-name g-semibold";
      name.textContent = nameOf(c.author);
      const text = doc.createElement("span");
      text.className = "b-comments__item__text";
      text.textContent = ` ${plain(c.text)}`;
      item.append(name, text);
      return item;
    }),
  );
}

function loadComments(doc: Document, list: Element, id: string, h: PostHandlers) {
  list.textContent = "Loading comments…";
  h.read(`${postPath(id)}/comments?limit=20`).then(
    (r) => showComments(doc, list, r),
    (e) => (list.textContent = `Could not load comments: ${message(e)}`),
  );
}

/** The comments box under the post's tools: its list, a field and Send. */
function openComments(doc: Document, row: Element, id: string, h: PostHandlers) {
  const box = doc.createElement("div");
  box.setAttribute("data-oi-comments", "");
  box.setAttribute("data-oi-wired", "");
  box.className = "b-comments";
  box.style.cssText = "padding:8px 0;font-size:14px";
  const list = doc.createElement("div");
  list.className = "b-comments__list";
  const form = doc.createElement("div");
  form.className = "b-comments__form d-flex align-items-center";
  form.style.cssText = "gap:8px;padding-top:8px";
  const input = doc.createElement("input");
  input.type = "text";
  input.className = "form-control";
  input.placeholder = "Add a comment...";
  form.append(input, button(doc, "Send", "data-oi-send"));
  box.append(list, form);
  const tools = row.querySelector(".b-post__tools");
  if (tools) tools.after(box);
  else row.querySelector("div.b-post")?.appendChild(box);
  loadComments(doc, list, id, h);
  input.focus();
}

function sendComment(doc: Document, row: Element, box: Element, id: string, h: PostHandlers) {
  const input = box.querySelector("input")!;
  const send = box.querySelector<HTMLButtonElement>("[data-oi-send]")!;
  if (send.disabled) return;
  const text = input.value.trim();
  if (!text) return note(doc, send, "Write a comment first", true);
  send.disabled = true;
  h.write("POST", `${postPath(id)}/comments`, { text }).then(
    () => {
      send.disabled = false;
      input.value = "";
      bump(row, COMMENTS, "Comment", 1);
      loadComments(doc, box.querySelector(".b-comments__list")!, id, h);
    },
    (e) => {
      send.disabled = false;
      note(doc, send, `Could not comment: ${message(e)}`, true);
    },
  );
}

/** Edit post: the post's text in a field at the top of its content, with Save and Cancel. */
function openEdit(doc: Document, row: Element) {
  if (row.querySelector(EDIT)) return;
  const text = row.querySelector<HTMLElement>(".b-post__text");
  const box = doc.createElement("div");
  box.setAttribute("data-oi-edit", "");
  box.setAttribute("data-oi-wired", "");
  box.className = "b-post__edit";
  box.style.cssText = "padding:8px 0";
  const area = doc.createElement("textarea");
  area.className = "form-control";
  area.rows = 4;
  area.value = text?.textContent?.trim() ?? "";
  const actions = doc.createElement("div");
  actions.className = "d-flex";
  actions.style.cssText = "gap:8px;padding-top:8px;justify-content:flex-end";
  actions.append(button(doc, "Cancel", "data-oi-cancel"), button(doc, "Save", "data-oi-save"));
  box.append(area, actions);
  if (text) text.style.display = "none";
  const content = row.querySelector(".b-post__content");
  if (content) content.prepend(box);
  else row.querySelector("div.b-post")?.appendChild(box);
  area.focus();
}

function closeEdit(row: Element) {
  row.querySelector(EDIT)?.remove();
  const text = row.querySelector<HTMLElement>(".b-post__text");
  if (text) text.style.display = "";
}

function saveEdit(doc: Document, row: Element, id: string, h: PostHandlers) {
  const box = row.querySelector(EDIT)!;
  const save = box.querySelector<HTMLButtonElement>("[data-oi-save]")!;
  if (save.disabled) return;
  const text = box.querySelector("textarea")!.value.trim();
  if (!text) return note(doc, save, "Enter the post's text", true);
  save.disabled = true;
  h.write("PUT", postPath(id), { text }).then(
    () => {
      const p = row.querySelector(".b-post__text .g-truncated-text > div > p");
      if (p) p.textContent = text;
      closeEdit(row);
      h.refresh();
    },
    (e) => {
      save.disabled = false;
      note(doc, save, `Could not save: ${message(e)}`, true);
    },
  );
}

const WRITES: Record<string, { method: "POST" | "DELETE"; path: (id: string) => string; fail: string }> = {
  pin: { method: "POST", path: (id) => `${postPath(id)}/pin`, fail: "Could not pin" },
  archive: { method: "POST", path: (id) => `${postPath(id)}/archive`, fail: "Could not archive" },
  delete: { method: "DELETE", path: postPath, fail: "Could not delete" },
};

const isOwn = (row: HTMLElement, me: string | null) => !row.dataset.oiAuthor || row.dataset.oiAuthor === me;
const STATS_ON = "data-oi-post-stats";

/**
 * With `h.stats`, the Creator's own rows' Post statistics enabled (the generator disables it), as rows come and go (the
 * page's data re-applies them). Returns its undo, which disables them again.
 */
function enablePostStats(doc: Document, h: PostHandlers): () => void {
  if (!h.stats) return () => {};
  const sweep = () => {
    for (const b of doc.querySelectorAll<HTMLButtonElement>(`${ROW} ${POST_STATS}[disabled]`)) {
      if (!isOwn(b.closest<HTMLElement>(ROW)!, h.me)) continue;
      b.disabled = false;
      b.removeAttribute("title");
      b.setAttribute(STATS_ON, "");
    }
  };
  sweep();
  const Observer = doc.defaultView?.MutationObserver ?? (typeof MutationObserver === "undefined" ? undefined : MutationObserver);
  const observer = Observer ? new Observer(sweep) : null;
  observer?.observe(doc.body, { childList: true, subtree: true });
  return () => {
    observer?.disconnect();
    for (const b of doc.querySelectorAll<HTMLButtonElement>(`[${STATS_ON}]`)) {
      b.disabled = true;
      b.title = NOT_YET;
      b.removeAttribute(STATS_ON);
    }
  };
}

/** Bind the post actions on `doc`'s real post rows. Returns an unbind. */
export function bindPostActions(doc: Document, h: PostHandlers): () => void {
  const undoStats = enablePostStats(doc, h);
  const onClick = (ev: MouseEvent) => {
    const t = ev.target as Element | null;
    if (!t?.closest) return;
    if (!t.closest(MENU) && !t.closest(MORE)) closeMenus(doc); // a click anywhere else closes an open menu
    const row = t.closest<HTMLElement>(ROW);
    if (!row) return;
    const id = row.dataset.oiPost!;
    const author = row.dataset.oiAuthor ?? null;
    const own = isOwn(row, h.me);
    const owned = () => {
      ev.preventDefault();
      ev.stopPropagation();
    };

    const like = t.closest<HTMLButtonElement>(LIKE);
    if (like) {
      owned();
      if (like.disabled || like.dataset.oiBusy) return;
      like.dataset.oiBusy = "";
      const query = own ? "" : `?author_id=${encodeURIComponent(author!)}`;
      h.write("POST", `${postPath(id)}/like${query}`).then(
        (r) => {
          delete like.dataset.oiBusy;
          const was = like.classList.contains("m-active");
          const now = typeof (r as { isFavorite?: unknown } | null)?.isFavorite === "boolean" ? !!(r as { isFavorite: boolean }).isFavorite : !was;
          like.classList.toggle("m-active", now);
          if (now !== was) bump(row, LIKES, "Like", now ? 1 : -1);
        },
        (e) => {
          delete like.dataset.oiBusy;
          note(doc, like, `Could not like: ${message(e)}`, true);
        },
      );
      return;
    }

    const stat = t.closest<HTMLElement>(STAT);
    if (stat?.dataset.testid === LIKES) {
      // Another creator's likers are not listed (OF's count there opens nothing).
      owned();
      if (own) h.likes(id, stat);
      return;
    }
    const stats = t.closest<HTMLButtonElement>(POST_STATS);
    if (stats && own && h.stats) {
      owned();
      if (!stats.disabled) h.stats(id, stats);
      return;
    }
    // The row's "N Comments" is the speech bubble's.
    const comment = stat?.dataset.testid === COMMENTS ? row.querySelector<HTMLButtonElement>(COMMENT) : t.closest<HTMLButtonElement>(COMMENT);
    if (comment) {
      owned();
      if (comment.disabled) return;
      const box = row.querySelector(BOX);
      if (box) box.remove();
      else openComments(doc, row, id, h);
      return;
    }
    const box = t.closest(BOX);
    if (box && t.closest("[data-oi-send]")) {
      owned();
      return sendComment(doc, row, box, id, h);
    }

    if (t.closest(EDIT)) {
      if (t.closest("[data-oi-cancel]")) {
        owned();
        closeEdit(row);
      } else if (t.closest("[data-oi-save]")) {
        owned();
        saveEdit(doc, row, id, h);
      }
      return;
    }

    const more = t.closest(MORE);
    if (more && (own || row.dataset.oiUsername)) {
      owned();
      const open = row.querySelector(MENU);
      closeMenus(doc);
      if (!open) openMenu(doc, row, more, own);
      return;
    }

    const item = t.closest<HTMLElement>(`${MENU} [data-oi-action]`);
    if (!item) return;
    owned();
    const action = item.dataset.oiAction!;
    const anchor = row.querySelector(MORE) ?? item;
    if (action === "edit") {
      closeMenus(doc);
      return openEdit(doc, row);
    }
    if (action === "copy") {
      closeMenus(doc);
      const clipboard = doc.defaultView?.navigator.clipboard;
      if (!clipboard) return note(doc, anchor, "Could not copy the link", true);
      clipboard.writeText(`https://onlyfans.com/${id}/${row.dataset.oiUsername}`).then(
        () => note(doc, anchor, "Link copied"),
        () => note(doc, anchor, "Could not copy the link", true),
      );
      return;
    }
    if (action === "delete" && !("oiArmed" in item.dataset)) {
      item.dataset.oiArmed = "";
      item.textContent = ` ${ARM} `;
      return;
    }
    if ("oiBusy" in item.dataset) return;
    item.dataset.oiBusy = "";
    const w = WRITES[action];
    h.write(w.method, w.path(id)).then(
      () => {
        closeMenus(doc);
        h.refresh();
      },
      (e) => {
        closeMenus(doc);
        note(doc, anchor, `${w.fail}: ${message(e)}`, true);
      },
    );
  };

  /** Enter in a comment field sends it. */
  const onKey = (ev: KeyboardEvent) => {
    const t = ev.target as Element | null;
    if (ev.key !== "Enter" || !t?.closest) return;
    const box = t.closest(BOX);
    const row = box?.closest<HTMLElement>(ROW);
    if (!box || !row || t.tagName !== "INPUT") return;
    ev.preventDefault();
    sendComment(doc, row, box, row.dataset.oiPost!, h);
  };

  doc.addEventListener("click", onClick, true);
  doc.addEventListener("keydown", onKey);
  return () => {
    undoStats();
    doc.removeEventListener("click", onClick, true);
    doc.removeEventListener("keydown", onKey);
  };
}

/** Every Mirror page, with a single model selected: bind the post actions on every frame load. */
export function useOfPostActions(frameRef: RefObject<HTMLIFrameElement | null>, src: string): void {
  const { accountId } = useScope();
  const qc = useQueryClient();
  const meId = useQuery(ofMeQuery(accountId)).data?.id;
  const me = meId != null ? String(meId) : null;
  const tz = useAppliedSettings().data?.preferences?.tz ?? null;
  // Post statistics shows the post's earnings: a role with Statistics only, on a Relay with the route.
  const granted = useGrantedPages();
  const statsPage = !granted || granted.has("/of-manager/statistics");
  const statsOn = useQuery({ ...postStatsProbe(accountId), enabled: !!accountId && statsPage, staleTime: Infinity, retry: false }).data === true && statsPage;

  useEffect(() => {
    const frame = frameRef.current;
    if (!frame || !accountId) return;
    const ctx = { accountId };
    let unbind: (() => void) | undefined;
    const bind = () => {
      unbind?.();
      const doc = frame.contentDocument;
      if (!doc?.body) return void (unbind = undefined);
      // The likers' list and the stats popup read with the model's account (ofMirrorStatsKit's readsCtx).
      bindUserLists(doc, { accountId, img: (u) => proxyImage(u, accountId) });
      unbind = bindPostActions(doc, {
        me,
        write: (method, path, body) => (method === "DELETE" ? relay.delete(path, ctx) : method === "PUT" ? relay.put(path, body, ctx) : relay.post(path, body, ctx)),
        read: (path) => relay.get(path, ctx),
        refresh: () => qc.invalidateQueries({ queryKey: ["of-mirror-data", accountId] }),
        likes: (id, opener) => openUsers(doc, `post-likes:${id}:0`, opener),
        stats: statsOn ? (id, opener) => openPostStats(doc, id, tz, opener) : null,
      });
    };
    if (frame.contentDocument?.readyState === "complete") bind();
    frame.addEventListener("load", bind);
    return () => {
      frame.removeEventListener("load", bind);
      unbind?.();
    };
  }, [frameRef, src, accountId, me, qc, tz, statsOn]);
}
