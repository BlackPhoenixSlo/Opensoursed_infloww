"use client";


import type { OFUserMini } from "@/lib/relay";
import { stillUrl } from "@/lib/ofMedia";
import { NOT_YET } from "@/lib/ofMirrorWrites";
import { drawPostCard, stampMedia, viewerItems, visibleMedia, type CardViewer } from "@/lib/ofMirrorPostCard";
import { applyMore, clock, dayOf, fill, fillGrid, linkUser, make, otherAvatar, photoGrid, plain, setOfText, stamp, track, userHref, valid, type MorePages } from "@/lib/ofMirrorDom";
import { fullDay, type MirrorPost } from "@/lib/ofMirrorFeedsShared";

function fromNow(ms: number): string {
  const s = Math.round(Math.abs(ms) / 1000);
  const m = Math.round(Math.abs(ms) / 60_000);
  const h = Math.round(Math.abs(ms) / 3_600_000);
  const span = s <= 44 ? "seconds" : s <= 89 || m <= 1 ? "1 minute" : m <= 44 ? `${m} minutes` : m <= 89 || h <= 1 ? "1 hour" : h <= 21 ? `${h} hours` : "a day";
  return ms > 0 ? `in ${span}` : `${span} ago`;
}

const startOfDay = (d: Date, days = 0) => new Date(d.getFullYear(), d.getMonth(), d.getDate() + days);

export function feedTime(at: Date, now = new Date()): string {
  const day = startOfDay(at).getTime();
  if (day === startOfDay(now).getTime()) return fromNow(at.getTime() - now.getTime());
  if (day === startOfDay(now, 1).getTime()) return `Tomorrow, ${clock(at)}`;
  if (day === startOfDay(now, -1).getTime()) return "Yesterday";
  if (at.getFullYear() > now.getFullYear()) return `${dayOf(at)} ${at.getFullYear()}, ${clock(at)}`;
  if (day > startOfDay(now, 1).getTime()) return stamp(at);
  return at.getFullYear() === now.getFullYear() ? dayOf(at) : fullDay(at);
}

export function applyProfileMedia(doc: Document, posts: MirrorPost[], img: (u: string) => string) {
  const { views, tiles } = photoGrid(doc);
  const tpl = tiles.find((t) => t.matches("a.b-photos__item[at-attr='photo_item']"));
  if (!views.length || !tpl) return;
  const merged = [...new Map(posts.map((p) => [String(p.id), p])).values()];
  merged.sort((a, b) => (valid(b.postedAt)?.getTime() ?? 0) - (valid(a.postedAt)?.getTime() ?? 0));
  const els = merged.map((p) => {
    const el = make(tpl);
    delete el.dataset.oiData;
    const still = stillUrl(visibleMedia(p)[0]);
    const pic = el.querySelector("img.b-photos__item__img");
    if (still) pic?.setAttribute("src", img(still));
    else pic?.remove();
    stampMedia(el, viewerItems(visibleMedia(p), img));
    const n = p.mediaCount ?? p.media?.length ?? 0;
    const count = el.querySelector(".b-purchase__list-item__count");
    if (n > 0 && count) count.textContent = ` ${n} `;
    else el.querySelector(".b-subscribe-block")?.remove();
    return el;
  });
  fillGrid(doc, views, els);
}

function postRows(doc: Document, tpl: Element, posts: MirrorPost[], img: (u: string) => string, viewer: (p: MirrorPost) => CardViewer): HTMLElement[] {
  return posts.map((p, i) => {
    const el = make(tpl);
    el.style.removeProperty("display");
    el.dataset.oiPost = String(p.id);
    if (p.author?.id != null) el.dataset.oiAuthor = String(p.author.id);
    const like = el.querySelector<HTMLButtonElement>(".set-favorite-btn");
    like?.classList.toggle("m-active", !!p.isFavorite);
    if (like && !p.canToggleFavorite) like.disabled = true;
    const comment = el.querySelector<HTMLButtonElement>(".send-comment-btn");
    if (comment && !p.canComment) comment.disabled = true;
    el.querySelector("[scroll-item-index]")?.setAttribute("scroll-item-index", String(i));
    el.querySelector("div.b-post")?.classList.toggle("m-pinned", !!p.isPinned);
    if (!p.isPinned) el.querySelector(".b-post__pinned")?.remove();
    const date = el.querySelector(".b-post__date > span");
    const at = valid(p.postedAt);
    if (date && at) {
      date.textContent = ` ${feedTime(at)} `;
      date.setAttribute("title", stamp(at));
    } else date?.remove();
    const content = el.querySelector(".b-post__content");
    const text = plain(p.text);
    const holder = el.querySelector(".b-post__text .g-truncated-text > div");
    if (!text) {
      el.querySelector(".b-post__text")?.remove();
      content?.classList.remove("m-post-has-text");
    } else if (holder) {
      setOfText(holder, p.text ?? "", holder.querySelector("p"));
    }
    const still = stillUrl(visibleMedia(p)[0]);
    if (still) {
      for (const pic of el.querySelectorAll(".post_media img.b-post__media__img, .post_media .b-post__media-bg img")) pic.setAttribute("src", img(still));
      el.querySelector(".post_media__loading")?.remove();
    } else {
      el.querySelector(".post_media")?.remove();
      content?.classList.remove("m-post-has-media");
    }
    const counts: [string, string, number | null | undefined][] = [
      ["post-stat-likes", "Like", p.likesCount ?? p.favoritesCount],
      ["post-stat-comments", "Comment", p.commentsCount],
    ];
    for (const [id, word, n] of counts) {
      const link = el.querySelector(`.b-summary-list a[data-testid='${id}']`);
      const span = link?.querySelector(":scope > span");
      if (n == null) link?.remove();
      else if (span) {
        span.textContent = String(n);
        if (span.nextSibling?.nodeType === 3) span.nextSibling.textContent = ` ${word}${n === 1 ? "" : "s"}`;
      }
    }
    for (const a of el.querySelectorAll(".b-post__labels-controls .b-list-titles a")) a.remove();
    drawPostCard(doc, el, p, viewer(p), img);
    return el;
  });
}

function postDate(el: Element, id: unknown, username: string | null | undefined) {
  const a = el.querySelector(".b-post__date");
  if (!a || !username || id == null) return;
  a.setAttribute("href", `https://onlyfans.com/${encodeURIComponent(String(id))}/${encodeURIComponent(username)}`);
  a.setAttribute("target", "_blank");
  a.setAttribute("rel", "noopener noreferrer");
  a.removeAttribute("aria-disabled");
  a.removeAttribute("title");
}

export function applyPosts(doc: Document, posts: MirrorPost[], img: (u: string) => string, username?: string | null, more?: MorePages) {
  const rows = [...doc.querySelectorAll<HTMLElement>(".user_posts .vue-recycle-scroller__item-view")].filter((r) => r.querySelector("div.b-post"));
  if (!rows.length) return;
  const els = postRows(doc, rows[0], posts, img, () => ({ own: true, subscribed: false }));
  els.forEach((el, i) => postDate(el, posts[i].id, username));
  fill(doc, rows, els);
  const wall = rows[0].closest(".user_posts");
  if (more && wall && posts.length) applyMore(doc, wall, more);
}

function authoredRows(doc: Document, tpl: Element, posts: MirrorPost[], authors: Record<string, OFUserMini>, img: (u: string) => string, me?: string, copyLink = false) {
  const authorOf = (p: MirrorPost) => (p.author?.id != null && authors[String(p.author.id)]) || p.author;
  const ownPost = (p: MirrorPost) => me !== undefined && p.author?.id != null && String(p.author.id) === me;
  const els = postRows(doc, doc.importNode(tpl, true), posts, img, (p) => ({ own: ownPost(p), subscribed: !!(authorOf(p) as { subscribedBy?: unknown } | undefined)?.subscribedBy }));
  els.forEach((el, i) => {
    el.querySelector(".link-trunc")?.remove();
    const trunc = el.querySelector<HTMLElement>(".g-truncated-text");
    trunc?.classList.remove("m-over-limit", "m-collapsed");
    trunc?.style.removeProperty("max-height");
    const id = posts[i].author?.id;
    const a = authorOf(posts[i]);
    const shown = a?.displayName || a?.name;
    const name = el.querySelector(".b-username .g-user-name")?.firstChild;
    if (name?.nodeType === 3) name.textContent = shown ? ` ${shown} ` : "";
    const handle = el.querySelector(".g-user-username");
    if (handle) handle.textContent = a?.username ? `@${a.username}` : "";
    if (handle && a?.displayName && a.name) {
      const real = handle.cloneNode(false) as HTMLElement;
      real.className = "g-user-realname";
      real.textContent = ` ${a.name} `;
      handle.before(real);
    }
    otherAvatar(el.querySelector(".b-post__avatar .g-avatar"), a, img);
    const links = el.querySelectorAll(".b-post__avatar a, a.b-username, a.g-user-realname__wrapper");
    const href = me === undefined ? null : userHref({ id, username: a?.username }, me);
    if (href) linkUser(links, href);
    else for (const link of links) link.setAttribute("href", "#");
    postDate(el, posts[i].id, a?.username);
    el.querySelector(".b-post__date-remaining")?.remove();
    if (!ownPost(posts[i])) {
      el.querySelector(".b-post__labels-controls")?.remove();
      sendTip(el.querySelector(".b-post__tools__item.m-with-text-button button"));
      el.querySelector("div.b-post")?.classList.remove("m-from-me");
      const more = el.querySelector<HTMLButtonElement>(".b-post__tools__more button");
      if (copyLink && a?.username) el.dataset.oiUsername = a.username;
      else if (more) {
        more.disabled = true;
        more.title = NOT_YET;
      }
    }
  });
  return els;
}

function sendTip(btn: HTMLButtonElement | null) {
  if (!btn) return;
  btn.setAttribute("at-attr", "post_tip");
  btn.disabled = true;
  btn.title = NOT_YET;
  btn.querySelector("svg")?.setAttribute("data-icon-name", "icon-funds");
  for (const use of btn.querySelectorAll("use")) for (const at of ["href", "xlink:href"]) if (use.hasAttribute(at)) use.setAttribute(at, "#icon-funds");
  const words = btn.querySelector(".b-flexible-behavior__inside-text");
  if (words) words.textContent = " Send Tip ";
}

const HOME_FEED = ".b-feed-content .user_posts";
export const COLUMN_FEED = ".l-main-content.m-r-side .g-page-content__body";

export function applyFeedStatus(doc: Document, error: string | null, feed = HOME_FEED) {
  const text = doc.querySelector<HTMLElement>(`${feed} > .empty-message > span`);
  if (!text) return;
  const [was, style] = [text.textContent, text.getAttribute("style")];
  track(doc, () => {
    text.textContent = was;
    if (style === null) text.removeAttribute("style");
    else text.setAttribute("style", style);
  });
  text.textContent = error === null ? "Loading posts…" : `Could not load posts: ${error}`;
  if (error !== null) text.style.color = "#ff4545";
}

export function applyHome(doc: Document, posts: MirrorPost[], authors: Record<string, OFUserMini>, tpl: Element, img: (u: string) => string, me?: string, more?: MorePages) {
  const feed = doc.querySelector(HOME_FEED);
  const empty = feed?.querySelector<HTMLElement>(":scope > .empty-message");
  if (!feed || !empty || !posts.length) return;
  fill(doc, [empty], authoredRows(doc, tpl, posts, authors, img, me, true), [feed]);
  if (more && feed.parentElement) applyMore(doc, feed.parentElement, more);
}

export interface ColumnPosts {
  posts: MirrorPost[];
  tpl: Element;
  me?: string;
  authors?: Record<string, OFUserMini>;
  more?: MorePages;
}

export function applyColumnPosts(doc: Document, { posts, tpl, me, authors = {}, more }: ColumnPosts, img: (u: string) => string) {
  const body = doc.querySelector(COLUMN_FEED);
  const empty = body?.querySelector<HTMLElement>(":scope > .empty-message");
  const scroller = body?.querySelector(":scope > .vue-recycle-scroller > .vue-recycle-scroller__item-wrapper");
  if (!body || !empty || !scroller || !posts.length) return;
  fill(doc, [empty], authoredRows(doc, tpl, posts, authors, img, me), [scroller]);
  if (more) applyMore(doc, body, more);
}
