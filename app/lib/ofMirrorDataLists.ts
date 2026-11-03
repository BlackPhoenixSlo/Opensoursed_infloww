"use client";

/** Collections' rows, cut from ofMirrorData (applyData draws them): the user lists, a list's users and tabs, the Fans, the post labels. */

import type { OFUserMini } from "@/lib/relay";
import { basePage, keepQuery } from "@/lib/ofMirrorRow";
import { MASS_SEND } from "@/lib/ofMirrorChat";
import { formatCount } from "@/lib/ofMirrorIdentity";
import { avatarOf } from "@/lib/ofMirrorAvatar";
import { fill, handleOf, linkUser, make, markOpen, nameOf, ROW_MARKS, sameId, setAttr, setAvatar, setClass, setText, track, unit, userHref } from "@/lib/ofMirrorDom";

/** A list's Posts tab (OF's /my/collections/user-lists/<id>/posts). */
export const LIST_POSTS = "collections/user-lists/list/posts";

/** A list's Users and Posts tabs (`?list=<id>` on both, the Posts tab's type chip `?postType=`, as OF's). */
export const LIST_TABS: readonly string[] = ["collections/user-lists/list", LIST_POSTS];
/** A list's Posts tab's type chips, by their text: OF's `postType` (its page) and `type` (GET /lists/<id>/posts). */
export const POST_TYPES: Record<string, string> = { All: "", Photos: "photos", Videos: "videos", Audio: "audios", Other: "other", Locked: "locked" };
/** The type chip `?postType=` asks for (null: All, or none OF has). */
export const postTypeOf = (v: string | null) => (v && Object.values(POST_TYPES).includes(v) ? v : null);
/** A list's Posts tab's feed, one of OF's pages of 10 (`offset` appended per page). */
export const listPostsPath = (list: string, type: string | null) => `/api/of/v2/lists/${encodeURIComponent(list)}/posts?limit=10${type ? `&type=${type}` : ""}`;

export interface UserList {
  id: number | string;
  name?: string;
  usersCount?: number;
  postsCount?: number;
  /** OF's preview of its members (the avatar stack). */
  users?: (OFUserMini & { avatarThumbs?: { c50?: string | null; c144?: string | null } | null })[];
}

/** A post label, as GET /labels sends it (OF's `{list: [{id, name, postsCount}]}`). */
export interface PostLabel {
  id: number | string;
  name?: string;
  postsCount?: number;
}

const listHref = (id: number | string) => `/of-manager/collections/user-lists/list?list=${encodeURIComponent(String(id))}`;
const labelHref = (id: number | string) => `/of-manager/collections/post-labels/archived?label=${encodeURIComponent(String(id))}`;
/** OF's plural (vue-i18n $tc): "{COUNT} user | {COUNT} users". */
const plural = (n: number, one: string, many: string) => `${formatCount(n)} ${n === 1 ? one : many}`;
/** OF's UsersList wording a list's own: its line with no members, and what its second line counts (with its zero). */
const SUBLINE: Record<string, { empty?: string; counts?: [none: string, one: string, many: string] }> = {
  recent: { empty: "No new subscribers in the last 24 hours" },
  purchased: { counts: ["No purchase", "purchase", "purchases"] },
};
/** A list row's subline, as OF's UsersList: "empty" (or the list's own line) with no members, else its users, then its posts when it has any (or the list's own count). */
export function listSubline(l: UserList): string[] {
  const own = SUBLINE[String(l.id)];
  if (!l.usersCount) return [own?.empty ?? "empty"];
  const n = l.postsCount ?? 0;
  const second = own?.counts ? (n ? plural(n, own.counts[1], own.counts[2]) : own.counts[0]) : n ? plural(n, "post", "posts") : null;
  return [plural(l.usersCount, "user", "users"), ...(second ? [second] : [])];
}
/** Collections' columns: their "Nothing found" (the generator's data-oi-empty) is looked up under these. */
export const LISTS_COLUMN = ".b-user-lists__list";
export const USERS_COLUMN = ".l-main-content.m-r-side";
export const LABELS_COLUMN = ".b-post-labels__list";

/** Hide the generator's "Nothing found" under `scope` once it has rows. */
export function hideEmpty(doc: Document, scope: string) {
  for (const e of doc.querySelectorAll<HTMLElement>(`${scope} [data-oi-empty]`)) setAttr(doc, e, "style", `${e.getAttribute("style") ?? ""};display:none`);
}

/** A column's "Nothing found" before its rows are here: "Loading…" (`error` null), or the red "Could not load: <the Relay's text>". */
export function applyColumnStatus(doc: Document, scope: string, error: string | null) {
  const text = doc.querySelector<HTMLElement>(`${scope} [data-oi-empty] > span`);
  if (!text) return;
  const [was, style] = [text.textContent, text.getAttribute("style")];
  track(doc, () => {
    text.textContent = was;
    if (style === null) text.removeAttribute("style");
    else text.setAttribute("style", style);
  });
  text.textContent = error === null ? "Loading…" : `Could not load: ${error}`;
  if (error !== null) text.style.color = "#ff4545";
}

/** The right column's title (the open list's or label's name), and the page's <title> after its last ":" or "›". */
function setHeading(doc: Document, name: string) {
  const heading = doc.querySelector(".l-main-content .g-page-title > span");
  if (!heading) return;
  setText(doc, heading, name);
  const title = doc.querySelector("title");
  if (title) setText(doc, title, (title.textContent ?? "").replace(/[^:›]+$/, ` ${name}`));
}

/** A copy of a hidden template row (the generator's): shown. */
const shown = (tpl: Element) => {
  const el = make(tpl);
  el.style.removeProperty("display");
  return el;
};

export function applyUserLists(doc: Document, lists: UserList[], open: string | null, borrowed?: Element, img: (u: string) => string = (u) => u) {
  let rows = [...doc.querySelectorAll<HTMLElement>(`${LISTS_COLUMN} .b-rows-lists__item`)];
  // A column captured with no list row: the borrowed (hidden) one put in.
  const wrapper = doc.querySelector(`${LISTS_COLUMN} .vue-recycle-scroller__item-wrapper`);
  if (!rows.length && borrowed && wrapper) {
    const row = doc.importNode(borrowed, true) as HTMLElement;
    wrapper.append(row);
    track(doc, () => row.remove());
    rows = [...doc.querySelectorAll<HTMLElement>(`${LISTS_COLUMN} .b-rows-lists__item`)];
  }
  if (!rows.length) return;
  const tpl = unit(rows.find((r) => r.querySelector("a[href^='/of-manager/collections/user-lists/list']")) ?? rows[0]);
  const clones = lists.map((l, i) => {
    const el = shown(tpl);
    el.querySelector("[data-index]")?.setAttribute("data-index", String(i));
    const a = el.querySelector("a.b-rows-lists__item__text")!;
    a.setAttribute("href", listHref(l.id));
    a.classList.remove(...ROW_MARKS, "m-current");
    a.removeAttribute("aria-current");
    if (sameId(l.id, open)) markOpen(a);
    el.querySelector(".b-rows-lists__item__name")!.textContent = l.name ?? "";
    // OF's avatar stack (its members' preview) between the name and the subline, when the list has members.
    el.querySelector(".b-media-set")?.remove();
    if (l.usersCount && l.users?.length) {
      const set = doc.createElement("div");
      set.className = "b-media-set m-avatars-media-set ml-2";
      set.append(...l.users.map((u) => avatarOf(doc, u, 50, img, "m-border-line-theme")));
      el.querySelector(".b-rows-lists__item__name")!.after(set);
    }
    const items = [...el.querySelectorAll(".b-content-inside-thumbs__item")];
    for (const x of items.slice(1)) x.remove();
    if (items[0])
      for (const [i, text] of listSubline(l).entries()) {
        const item = i ? (items[0].cloneNode() as Element) : items[0];
        item.textContent = ` ${text} `;
        if (i) items[0].parentElement!.append(item);
      }
    return el;
  });
  fill(doc, [...new Set(rows.map(unit))], clones);
  if (lists.length) hideEmpty(doc, LISTS_COLUMN);
  const name = lists.find((l) => sameId(l.id, open))?.name;
  if (name) setHeading(doc, name);
}

/**
 * `people` as fan cards in the users column (copies of the generator's hidden card): `list` the open list (its id and
 * name on the card's list link, its query kept on the page's links), null on Fans.
 */
export function applyListUsers(doc: Document, page: string, list: string | null, people: OFUserMini[], listName: string | null, img: (u: string) => string) {
  if (list) {
    keepQuery(doc, basePage(page), `?list=${encodeURIComponent(list)}`);
    track(doc, () => keepQuery(doc, basePage(page), ""));
  }
  const wrappers = [...doc.querySelectorAll(".b-wrapper-recycle-scroller .vue-recycle-scroller__item-wrapper")];
  const cards = wrappers.flatMap((w) => [...w.querySelectorAll<HTMLElement>(":scope > .vue-recycle-scroller__item-view")]);
  if (!cards.length) return;
  const tpl = cards.find((c) => c.querySelector(".g-user-realname")) ?? cards[0];
  const clones = people.map((u) => {
    const el = shown(tpl);
    el.dataset.oiUser = String(u.id); // the card's user, for its Lists menu (ofMirrorCollections)
    for (const x of el.querySelectorAll(".g-user-name, .g-user-realname")) x.textContent = nameOf(u);
    for (const x of el.querySelectorAll(".g-user-username")) x.textContent = `@${handleOf(u)}`;
    setAvatar(el.querySelector(".b-fans__item__header > .g-avatar"), u, img);
    // The generator's one list link: the open list's (none on Fans).
    for (const [i, a] of [...el.querySelectorAll(".b-list-titles a")].entries()) {
      if (i > 0 || !listName || !list) a.remove();
      else {
        a.setAttribute("href", listHref(list));
        const t = a.querySelector(".b-list-titles__item__text");
        if (t) t.textContent = listName;
      }
    }
    for (const a of el.querySelectorAll("a[href='/of-manager/messages/chat']")) a.setAttribute("href", `/of-manager/messages/chat?chat=${encodeURIComponent(String(u.id))}`);
    // The card's avatar, name and handle (OF's profile links): the user's OF profile.
    linkUser(el.querySelectorAll(".b-fans__item__header > a.g-avatar, a.b-username, a.g-user-realname__wrapper"), userHref(u));
    for (const x of el.querySelectorAll(".b-fans__item__list, .b-btn-collapse")) x.remove(); // the example's subscription details
    return el;
  });
  fill(doc, cards, clones, wrappers);
  if (people.length) hideEmpty(doc, USERS_COLUMN);
}

/**
 * A list's Users and Posts tabs keep the open `list` (as its row's link); the Posts tab's type chips (OF's ?postType=)
 * each link their own type of it, `type`'s chip (null: All) marked current as OF marks it. The header's Send message opens
 * New message with the list ticked (`?to=`, OF's sendlist-<list>; useOfChat ticks it).
 */
export function applyListTabs(doc: Document, list: string, type: string | null) {
  const q = `?list=${encodeURIComponent(list)}`;
  for (const a of doc.querySelectorAll(`a[aria-label="Send message"][href^="${MASS_SEND}"]`)) setAttr(doc, a, "href", `${MASS_SEND}?to=${encodeURIComponent(list)}`);
  for (const p of LIST_TABS) keepQuery(doc, p, q);
  track(doc, () => LIST_TABS.forEach((p) => keepQuery(doc, p, "")));
  for (const a of doc.querySelectorAll(".g-page-content__header a.b-tabs__nav__link")) {
    const t = POST_TYPES[a.textContent?.trim() ?? ""];
    if (t === undefined) continue;
    const on = t === (type ?? "");
    setAttr(doc, a, "href", `/of-manager/${LIST_POSTS}${q}${t ? `&postType=${t}` : ""}`);
    for (const c of ["m-current", "m-no-pointer"]) setClass(doc, a, c, on);
    setAttr(doc, a, "tabindex", on ? "-1" : "0");
  }
}

/** Post Labels: the Creator's labels in copies of the generator's hidden label row (name, posts count), `open` marked and titled. */
export function applyLabels(doc: Document, labels: PostLabel[], open: string | null) {
  const rows = [...doc.querySelectorAll<HTMLElement>(`${LABELS_COLUMN} .b-rows-lists__item`)];
  if (!rows.length) return;
  const current = labels.find((l) => sameId(l.id, open)) ?? labels[0];
  const clones = labels.map((l) => {
    const el = shown(rows[0]);
    const a = el.querySelector("a.b-rows-lists__item__text")!;
    a.setAttribute("href", labelHref(l.id));
    a.setAttribute("target", "_top");
    a.classList.remove(...ROW_MARKS, "m-current");
    a.removeAttribute("aria-current");
    if (l === current) markOpen(a);
    el.querySelector(".b-rows-lists__item__name")!.textContent = l.name ?? "";
    const count = el.querySelector(".b-content-inside-thumbs__item");
    if (count) count.textContent = `${l.postsCount ?? 0} posts`; // OF's own wording, "1 posts" too
    return el;
  });
  fill(doc, rows, clones);
  if (labels.length) hideEmpty(doc, LABELS_COLUMN);
  if (current?.name) setHeading(doc, current.name);
}
