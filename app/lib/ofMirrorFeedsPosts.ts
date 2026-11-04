"use client";

/** The post feeds: My profile's wall and Media tab, Home's feed, the right column's (bookmarks, a list's Posts tab). */

import type { OFUserMini } from "@/lib/relay";
import { stillUrl } from "@/lib/ofMedia";
import { NOT_YET } from "@/lib/ofMirrorWrites";
import { drawPostCard, stampMedia, viewerItems, visibleMedia, type CardViewer } from "@/lib/ofMirrorPostCard";
import { applyMore, clock, dayOf, fill, fillGrid, linkUser, make, otherAvatar, photoGrid, plain, stamp, track, userHref, valid, type MorePages } from "@/lib/ofMirrorDom";
import { fullDay, type MirrorPost } from "@/lib/ofMirrorFeedsShared";

/** dayjs's fromNow with OF's words (its UtilsTime's relativeTime: "seconds", "1 minute", "%d hours", ...) and thresholds. */
function fromNow(ms: number): string {
  const s = Math.round(Math.abs(ms) / 1000);
  const m = Math.round(Math.abs(ms) / 60_000);
  const h = Math.round(Math.abs(ms) / 3_600_000);
  const span = s <= 44 ? "seconds" : s <= 89 || m <= 1 ? "1 minute" : m <= 44 ? `${m} minutes` : m <= 89 || h <= 1 ? "1 hour" : h <= 21 ? `${h} hours` : "a day";
  return ms > 0 ? `in ${span}` : `${span} ago`;
}

const startOfDay = (d: Date, days = 0) => new Date(d.getFullYear(), d.getMonth(), d.getDate() + days);

/**
 * OF's post date (UtilsTime, type "feed", in English): today relative ("seconds ago", "1 minute ago", "4 hours ago",
 * "a day ago"), "Yesterday", "Tomorrow, 9:05 am", a later day "Oct 20, 9:05 am" (next year "Jan 2 2027, 9:05 am"),
 * an earlier day this year "Oct 16", before it "Oct 16, 2025". The hover title is `stamp`.
 */
export function feedTime(at: Date, now = new Date()): string {
  const day = startOfDay(at).getTime();
  if (day === startOfDay(now).getTime()) return fromNow(at.getTime() - now.getTime());
  if (day === startOfDay(now, 1).getTime()) return `Tomorrow, ${clock(at)}`;
  if (day === startOfDay(now, -1).getTime()) return "Yesterday";
  if (at.getFullYear() > now.getFullYear()) return `${dayOf(at)} ${at.getFullYear()}, ${clock(at)}`;
  if (day > startOfDay(now, 1).getTime()) return stamp(at);
  return at.getFullYear() === now.getFullYear() ? dayOf(at) : fullDay(at);
}

/**
 * My profile's Media tab: one copy of the grid's first tile per photo or video post (the two lists merged by post id,
 * newest first), three to a row. Its picture is the post's first still (none: no picture, never the example's) and its
 * badge the post's media count (none or 0: no badge). The grid's hidden example row is the template (the generator's);
 * the Recent strip and the counts are ofMirrorProfile's.
 */
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
    stampMedia(el, viewerItems(visibleMedia(p), img)); // its files, for the viewer (ofMirrorHome)
    const n = p.mediaCount ?? p.media?.length ?? 0;
    const count = el.querySelector(".b-purchase__list-item__count");
    if (n > 0 && count) count.textContent = ` ${n} `;
    else el.querySelector(".b-subscribe-block")?.remove();
    return el;
  });
  fillGrid(doc, views, els);
}

/**
 * One copy of the post row `tpl` per post, in order. Pinned mark, date (its hover stamp), text, first picture and like
 * and comment counts are the post's; a field it lacks drops its element. The example's list label goes (the Relay
 * returns no post lists); the author is left as in `tpl`. Its price, files, poll and locked block are OF's post card's
 * (drawPostCard), as `viewer(post)` sees it: the Creator's own post, or another creator's (subscribed or not).
 */
function postRows(doc: Document, tpl: Element, posts: MirrorPost[], img: (u: string) => string, viewer: (p: MirrorPost) => CardViewer): HTMLElement[] {
  return posts.map((p, i) => {
    const el = make(tpl);
    el.style.removeProperty("display"); // the generator's hidden example row
    // The post and its author, for the post actions (ofMirrorHome).
    el.dataset.oiPost = String(p.id);
    if (p.author?.id != null) el.dataset.oiAuthor = String(p.author.id);
    const like = el.querySelector<HTMLButtonElement>(".set-favorite-btn");
    like?.classList.toggle("m-active", !!p.isFavorite);
    // OF's rule (its post tools: `!post.canToggleFavorite`, `!post.canComment`): a post without the flag (a list's stub
    // posts: only their author's id, date and id) has Like and Comment off.
    if (like && !p.canToggleFavorite) like.disabled = true;
    const comment = el.querySelector<HTMLButtonElement>(".send-comment-btn");
    if (comment && !p.canComment) comment.disabled = true;
    // The capture numbers its post rows with scroll-item-index (it has no data-index on them).
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
      const para = (holder.querySelector("p")?.cloneNode(false) as HTMLElement | undefined) ?? doc.createElement("p");
      para.textContent = text;
      holder.replaceChildren(para);
    }
    // OF's visible media: another creator's locked post shows only the files it can view (none: no picture).
    const still = stillUrl(visibleMedia(p)[0]);
    if (still) {
      for (const pic of el.querySelectorAll(".post_media img.b-post__media__img, .post_media .b-post__media-bg img")) pic.setAttribute("src", img(still));
      el.querySelector(".post_media__loading")?.remove(); // OF's loading cover (its script drops it once the picture loads)
    } else {
      el.querySelector(".post_media")?.remove();
      content?.classList.remove("m-post-has-media");
    }
    // By OF's test id: another creator's post (Home) has no aria-label on them. The word follows the count.
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

/**
 * A post row's date: OF's link to the post's page, `https://onlyfans.com/<post id>/<author's handle>` in a new tab (the
 * mirror has no post page; Copy link to post gives the same URL), enabled once the handle is known (else as captured:
 * disabled with the tooltip).
 */
function postDate(el: Element, id: unknown, username: string | null | undefined) {
  const a = el.querySelector(".b-post__date");
  if (!a || !username || id == null) return;
  a.setAttribute("href", `https://onlyfans.com/${encodeURIComponent(String(id))}/${encodeURIComponent(username)}`);
  a.setAttribute("target", "_blank");
  a.setAttribute("rel", "noopener noreferrer");
  a.removeAttribute("aria-disabled");
  a.removeAttribute("title");
}

/**
 * My profile's wall: its own first post row per post, each date linked by the Creator's handle (`username`); the
 * author is left to useOfIdentity. Its next page when OF's loading row (under the rows) nears the view (`more`).
 */
export function applyPosts(doc: Document, posts: MirrorPost[], img: (u: string) => string, username?: string | null, more?: MorePages) {
  const rows = [...doc.querySelectorAll<HTMLElement>(".user_posts .vue-recycle-scroller__item-view")].filter((r) => r.querySelector("div.b-post"));
  if (!rows.length) return;
  const els = postRows(doc, rows[0], posts, img, () => ({ own: true, subscribed: false }));
  els.forEach((el, i) => postDate(el, posts[i].id, username));
  fill(doc, rows, els);
  const wall = rows[0].closest(".user_posts");
  if (more && wall && posts.length) applyMore(doc, wall, more);
}

/**
 * A copy of the borrowed post row `tpl` per post (postRows), each showing its own author: `authors[id]` (the Relay's
 * /users/list by id), else the post's own author, else empty, and no picture then. Author links go to the author's OF
 * profile in a new tab (another creator's profile is not mirrored; userHref), the Creator's own to My profile (until `me` is in, the
 * author links stay inert), and the date to the post on
 * onlyfans.com (postDate); the row's collapsed long text, its "show more" and expiry countdown go. The bold
 * name is the author's displayName (the Creator's rename) else name; with a rename the author's name goes by the handle,
 * as OF's. A post not proven the Creator's own (its author's id is not `me`, the Creator's id, or either is unknown yet)
 * loses the row's Labels and its Post statistics becomes OF's Send Tip (sendTip), disabled with the "Not available in
 * Inflowwww yet" tooltip; its More keeps only OF's "Copy link to post" (ofMirrorHome, the author's handle stamped
 * `data-oi-username`, Home only), disabled with the tooltip when the handle is unknown or on Bookmarks.
 */
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
    // OF's username block: the Creator's rename of the author (displayName) bold, then the author's own name by the handle.
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
    // OF's links to the author's profile: the Creator's own My profile, another creator's OF profile (userHref); neither
    // id nor handle, or the Creator's id not in yet (an own post would link the Creator's own OF profile): inert.
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
      // OF's menu for another creator's post: only Copy link to post needs no Relay route (hide and report have none);
      // Home binds it (ofMirrorHome), Bookmarks is read-only.
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

/**
 * OF's Send Tip on another creator's post, made from the borrowed row's own-post text button (Post statistics: the same
 * OF button, its icon and words changed). It stays disabled with the tooltip, as the row's More: the mirror sends no tip.
 */
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

/** Home's feed; the right-sided main column's body (All bookmarks', a list's Posts tab's): each holds its empty message. */
const HOME_FEED = ".b-feed-content .user_posts";
export const COLUMN_FEED = ".l-main-content.m-r-side .g-page-content__body";

/**
 * Home's feed (or `feed`'s) before its posts are here: the feed's empty message reads "Loading posts…" while the Relay
 * answers (`error` null), or the red "Could not load posts: <the Relay's text>" after it failed, instead of "No posts yet".
 */
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

/**
 * Home: the home feed's posts (OF's GET /posts: the Creator's and the followed creators'), in place of the feed's
 * "No posts yet" (the generator's: Home keeps no example post; kept for an empty feed), in My profile's post row
 * borrowed from its capture (TEMPLATES). Its next page when OF's loading row (after the feed) nears the view (`more`).
 */
export function applyHome(doc: Document, posts: MirrorPost[], authors: Record<string, OFUserMini>, tpl: Element, img: (u: string) => string, me?: string, more?: MorePages) {
  const feed = doc.querySelector(HOME_FEED);
  const empty = feed?.querySelector<HTMLElement>(":scope > .empty-message");
  if (!feed || !empty || !posts.length) return;
  fill(doc, [empty], authoredRows(doc, tpl, posts, authors, img, me, true), [feed]);
  if (more && feed.parentElement) applyMore(doc, feed.parentElement, more);
}

/** A right-column feed: its posts, the borrowed post row `tpl`, the Creator's id, its authors by id, its next pages. */
export interface ColumnPosts {
  posts: MirrorPost[];
  tpl: Element;
  me?: string;
  /** Authors by id, for posts that carry only their author's id (a list's Posts tab: OF's skip_users=all). */
  authors?: Record<string, OFUserMini>;
  /** Its pages after the first, as Statements' (applyMore). */
  more?: MorePages;
}

/**
 * The right column's feed (COLUMN_FEED): the borrowed post row per post, in place of its empty message (kept for an
 * empty feed), each with its author (authoredRows: on the post, else `authors`). All bookmarks ("No bookmarks yet";
 * the sidebar's Recent list stays as captured) and a list's Posts tab ("No posts yet", OF's pages of 10 as `more`).
 */
export function applyColumnPosts(doc: Document, { posts, tpl, me, authors = {}, more }: ColumnPosts, img: (u: string) => string) {
  const body = doc.querySelector(COLUMN_FEED);
  const empty = body?.querySelector<HTMLElement>(":scope > .empty-message");
  // OF's scroller (the generator keeps it on both pages): the rows go in it, above its loading row, as OF's.
  const scroller = body?.querySelector(":scope > .vue-recycle-scroller > .vue-recycle-scroller__item-wrapper");
  if (!body || !empty || !scroller || !posts.length) return;
  fill(doc, [empty], authoredRows(doc, tpl, posts, authors, img, me), [scroller]);
  // OF's next page when its loading row nears the view (applyMore), as OF's infinite feed.
  if (more) applyMore(doc, body, more);
}
