"use client";

/**
 * Real rows on the OF mirror's feed pages (ofMirrorData's Parts home, promotions, events, posts, profileMedia, bookmarks,
 * listPosts, queue and notifications; its applyData draws them, useOfData fetches them). Home shows the home feed's posts, the
 * Creator's promotions on offer and the next scheduled events. My profile (and its state pages) shows the Creator's own wall posts in
 * OF's captured post row, read by the Creator's OnlyFans id from the "who am I" query. Its Media tab shows one grid
 * tile per photo or video post. All bookmarks shows the bookmarked posts, each with its own author, in My profile's
 * post row borrowed from its capture (TEMPLATES); a list's Posts tab its users' posts the same way. The queue's month pages mark the shown month's scheduled posts,
 * messages and streams of the tabs selected (none: all) on the calendar's days, and list the selected day's in the right
 * column (the list view: the month's, by day); its saved-for-later pages the saved-for-later posts and messages, all in
 * OF's agenda markup and the Agency's time zone. Every notifications tab lists the Creator's notifications of its
 * type in the tab's own plain row, and its tab bar shows the Creator's unread counts. Streaming's dashboard lists the
 * Creator's past live streams. Home's story strip gets a tile per creator with stories after its own "Add to story" (applyStories). Statements' Earnings tab lists the Creator's
 * earning transactions in its own table rows, its Payouts tab the payout requests in its own rows, and its Referrals
 * tab the referral payouts in the Payouts tab's rows borrowed from its capture.
 * Loaded through ofMirrorData, which reads QUEUE and NOTIFICATIONS while loading (the two modules import each other).
 */

import { TZ } from "@/hooks/useScheduledMessages";
import { useAppliedSettings } from "@/lib/appliedSettings";
import type { OFPost } from "@/hooks/usePosts";
import type { OFMedia, OFUserMini } from "@/lib/relay";
import { stillUrl } from "@/lib/ofMedia";
import { clock, dayOf, dropClass, fill, fillGrid, handleOf, make, nameOf, photoGrid, plain, setAvatar, setIcon, stamp, track, valid, type Part } from "@/lib/ofMirrorData";
import { localIso, NOT_YET, parseDate } from "@/lib/ofMirrorWrites";
import { avatarOf, iconOf, type AvatarUser } from "@/lib/ofMirrorAvatar";

/** A queue item's post, message or stream: what it shows, and its id and state for the row's actions (ofMirrorQueue). */
interface QueueEntity {
  id?: number | string;
  text?: string | null;
  /** A stream's text (OF's schedule form sends `description`). */
  description?: string | null;
  mediaCount?: number;
  isMediaReady?: boolean;
  isPinned?: boolean;
  /** A message's send time; a queued message with none is saved for later (OF's isSFLMessage). */
  scheduledAt?: string | null;
  /** A post saved for later (OF's isSFLPost). */
  isPublishedWithPeriod?: boolean;
  /** A queued message's audience as OF names it on its card: "user" and the fan's username, or a list's name. */
  sentRulesType?: string;
  sentRulesExtra?: string | null;
}

/**
 * A queue item as its route sends it: `/schedules` and `/schedules/later/*` wrap the post, message or stream (`type`,
 * `publishDateTime`, `entity`), their own `id` the schedule's; a flat item (no `entity`) is its own target.
 */
export interface QueueItem extends QueueEntity {
  type?: string;
  publishDateTime?: string;
  createdDateTime?: string;
  entity?: QueueEntity;
}

/**
 * A /schedules item saved for later, as OF's queue store marks it (app.js schedule module: isSFLMessage, a chat whose
 * entity has no `scheduledAt`; isSFLPost, a post whose entity `isPublishedWithPeriod`).
 */
export function isSavedForLater(i: QueueItem): boolean {
  return (i.type === "chat" && !!i.entity && !i.entity.scheduledAt) || (i.type === "post" && !!i.entity?.isPublishedWithPeriod);
}

export type Month = { start: string; end: string };

/**
 * The month pages' route: the shown month's posts, messages and streams, its days those of `zone` (the Agency's time
 * zone; default the browser's). OF's own tabs add `filter[type]` (read from its queue chunk); the Relay passes no type,
 * so the tabs filter the month's items here (QUEUE_TABS).
 */
const SCHEDULES = {
  route: (m: Month | null, zone = TZ) => m && `/api/of/v2/schedules?publish_date=${m.start}&publish_date_end=${m.end}&time_zone=${encodeURIComponent(zone)}&limit=50`,
  // A saved-for-later item takes OF's half-tinted sfl- mark (QueueAgenda's itemType, its stylesheet's sfl-*-indicator).
  mark: (i: QueueItem) => (isSavedForLater(i) ? `sfl-${i.type}-indicator` : (({ post: "post-indicator", chat: "chat-indicator", stream: "stream-indicator" })[i.type ?? ""] ?? "")),
  // OF's agenda date: publishDateTime, else createdDateTime.
  at: (i: QueueItem) => i.publishDateTime || i.createdDateTime,
  month: true as const,
};

/**
 * Queue page -> its Relay route (null while the shown month is unknown), its items' colour mark and time (none: saved
 * for later), whether it is a month page (only the shown month's items, of the selected tabs; the selected day's in
 * the right column), and every item's kind when the route sends no `type`.
 */
export const QUEUE: Record<string, { route: (m: Month | null, zone?: string) => string | null; mark: (i: QueueItem) => string; at?: (i: QueueItem) => string | undefined; month?: true; kind?: QueueKind }> = {
  "queue/index": SCHEDULES,
  "queue/state-list-view": SCHEDULES,
  // The Messages tab, and the Messages and Streams tabs, selected: the same month, filtered in place.
  "queue/state-tab-messages": SCHEDULES,
  "queue/state-tab-streams": SCHEDULES,
  "queue/saved-for-later-posts": { route: () => "/api/of/v2/schedules/later/post?limit=50", mark: () => "sfl-post-indicator", kind: "post" },
  "queue/saved-for-later-messages": { route: () => "/api/of/v2/schedules/later/chat?limit=50", mark: () => "sfl-chat-indicator", kind: "chat" },
};

export type QueueKind = "post" | "chat";

/** A queue row's actions, as ofMirrorQueue reads them back from the row's data-oi-queue-* attributes. */
export interface QueueActions {
  kind: QueueKind;
  /** The post or message id: pin, delete. */
  target: string;
  /** The schedule id: "Post now" / "Message now" (empty: a flat item has none). */
  schedule: string;
  /** OF greys "Post now" / "Message now" out until the media is ready. */
  ready: boolean;
  pinned: boolean;
}

/** A queue item's row actions, as OF's ScheduleEventDropdown reads them; null (no menu) unless a post or message with an id. */
export function queueActions(page: string, i: QueueItem): QueueActions | null {
  const kind = i.type ?? QUEUE[page]?.kind;
  const target = i.entity ? i.entity.id : i.id;
  if ((kind !== "post" && kind !== "chat") || target == null) return null;
  const body = i.entity ?? i;
  return { kind, target: String(target), schedule: i.entity && i.id != null ? String(i.id) : "", ready: body.isMediaReady !== false, pinned: !!body.isPinned };
}

/** OF's "more" icon (its sprite symbol: the queue pages' cut-down sprite lacks it). */
const SVG = "http://www.w3.org/2000/svg";
const MORE_ICON = "M6 10a2 2 0 1 0 2 2 2 2 0 0 0-2-2zm12 0a2 2 0 1 0 2 2 2 2 0 0 0-2-2zm-6 0a2 2 0 1 0 2 2 2 2 0 0 0-2-2z";

/** A `/users/{id}/posts` item; its media in the Relay's media shape (what `stillUrl` reads). */
export type MirrorPost = Omit<OFPost, "media"> & {
  media?: OFMedia[];
  /** A bookmarked or home feed post's own author (only `id` when the Relay skips users). */
  author?: OFUserMini;
  /** The Creator has liked it; OF's like button can toggle it (false on the Creator's own posts). */
  isFavorite?: boolean;
  canToggleFavorite?: boolean;
  /** OF's Comment is enabled only with it (a list's stub posts lack it). */
  canComment?: boolean;
};

export type Template = "post" | "agenda" | "payoutRow" | "chatList" | "listRow";

/**
 * Rows borrowed from another captured page, for a Part whose page captures none: the page (under of-mirror/pages) and
 * how to pick the row there. useOfData fetches the page same-origin and passes the row in `MirrorData.templates`.
 */
export const TEMPLATES: Partial<Record<Template, { parts: Part[]; page: string; pick: (doc: Document) => Element | undefined }>> = {
  post: {
    parts: ["bookmarks", "home", "listPosts"],
    page: "profile/index",
    pick: (d) => [...d.querySelectorAll(".vue-recycle-scroller__item-view")].find((v) => v.querySelector("div.b-post")),
  },
  agenda: {
    parts: ["queue"],
    page: "queue/state-list-view",
    pick: (d) => {
      const block = d.querySelector(".b-queue-scroll-wrapper");
      block?.querySelector(".empty-message")?.remove();
      return block ?? undefined;
    },
  },
  // A chat's Gallery and Pinned tabs were captured with no chat in their list: the Messages page's list (its hidden row).
  chatList: {
    parts: ["chatList"],
    page: "messages/index",
    pick: (d) => d.querySelector(".b-chats__list-dialogues > .vue-recycle-scroller") ?? undefined,
  },
  // Following and its tabs were captured with no user list row: Collections' (its hidden list row).
  listRow: {
    parts: ["listRow"],
    page: "collections/index",
    pick: (d) => [...d.querySelectorAll(".b-user-lists__list .vue-recycle-scroller__item-view")].find((v) => v.querySelector(".b-rows-lists__item")),
  },
  payoutRow: {
    parts: ["referrals"],
    page: "statements/payouts",
    pick: (d) => [...d.querySelectorAll(".b-table tbody tr")].find((r) => r.querySelector(".b-table__date") && r.querySelector("span.approved")),
  },
};

/** "May 20, 2025": OF's date of a post before this year. */
const fullDay = (d: Date) => d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });

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
    const still = stillUrl(p.media?.[0]);
    const pic = el.querySelector("img.b-photos__item__img");
    if (still) pic?.setAttribute("src", img(still));
    else pic?.remove();
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
 * returns no post lists); the author is left as in `tpl`.
 */
function postRows(doc: Document, tpl: Element, posts: MirrorPost[], img: (u: string) => string): HTMLElement[] {
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
    const still = stillUrl(p.media?.[0]);
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
    return el;
  });
}

/** My profile's wall: its own first post row per post; the author is left to useOfIdentity. */
export function applyPosts(doc: Document, posts: MirrorPost[], img: (u: string) => string) {
  const rows = [...doc.querySelectorAll<HTMLElement>(".user_posts .vue-recycle-scroller__item-view")].filter((r) => r.querySelector("div.b-post"));
  if (!rows.length) return;
  fill(doc, rows, postRows(doc, rows[0], posts, img));
}

/**
 * A copy of the borrowed post row `tpl` per post (postRows), each showing its own author: `authors[id]` (the Relay's
 * /users/list by id), else the post's own author, else empty, and no picture then. Author links go nowhere (another
 * creator's profile is not mirrored); the row's collapsed long text, its "show more" and expiry countdown go. The bold
 * name is the author's displayName (the Creator's rename) else name; with a rename the author's name goes by the handle,
 * as OF's. A post not proven the Creator's own (its author's id is not `me`, the Creator's id, or either is unknown yet)
 * loses the row's Labels and its Post statistics becomes OF's Send Tip (sendTip), disabled with the "Not available in
 * Inflowwww yet" tooltip; its More keeps only OF's "Copy link to post" (ofMirrorHome, the author's handle stamped
 * `data-oi-username`, Home only), disabled with the tooltip when the handle is unknown or on Bookmarks.
 */
function authoredRows(doc: Document, tpl: Element, posts: MirrorPost[], authors: Record<string, OFUserMini>, img: (u: string) => string, me?: string, copyLink = false) {
  const els = postRows(doc, doc.importNode(tpl, true), posts, img);
  els.forEach((el, i) => {
    el.querySelector(".link-trunc")?.remove();
    const trunc = el.querySelector<HTMLElement>(".g-truncated-text");
    trunc?.classList.remove("m-over-limit", "m-collapsed");
    trunc?.style.removeProperty("max-height");
    const id = posts[i].author?.id;
    const a = (id != null && authors[String(id)]) || posts[i].author;
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
    for (const link of el.querySelectorAll(".b-post__avatar a, a.b-username, a.g-user-realname__wrapper")) link.setAttribute("href", "#");
    el.querySelector(".b-post__date-remaining")?.remove();
    const own = me !== undefined && id != null && String(id) === me;
    if (!own) {
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
 * borrowed from its capture (TEMPLATES).
 */
export function applyHome(doc: Document, posts: MirrorPost[], authors: Record<string, OFUserMini>, tpl: Element, img: (u: string) => string, me?: string) {
  const feed = doc.querySelector(HOME_FEED);
  const empty = feed?.querySelector<HTMLElement>(":scope > .empty-message");
  if (!feed || !empty || !posts.length) return;
  fill(doc, [empty], authoredRows(doc, tpl, posts, authors, img, me, true), [feed]);
}

/** One story as OF lists it (GET /stories, GET /users/{id}/stories): its media. */
export interface StoryEntry {
  id?: number | string;
  media?: OFMedia[] | null;
}

/** A creator in Home's story strip, as GET /stories lists them (the Creator's feed of followed creators' stories). */
export interface StoryUser extends AvatarUser {
  isVerified?: boolean;
  stories?: StoryEntry[] | null;
}

/** A media's file for the viewer, through `img`: a video's or GIF's 720p, else its full file, else its still. */
function viewerSrc(m: OFMedia & { videoSources?: Record<string, string | null> | null }, img: (u: string) => string): string | null {
  const url = ((m.type === "video" || m.type === "gif") && m.videoSources?.["720"]) || m.files?.full?.url || stillUrl(m);
  return url ? img(url) : null;
}

/** The viewer's items for `stories` (every story's media, in order), each `{src, type}`. */
export function storyItems(stories: StoryEntry[], img: (u: string) => string): { src: string; type: string }[] {
  return stories.flatMap((s) => s.media ?? []).flatMap((m) => {
    const src = viewerSrc(m, img);
    return src ? [{ src, type: m.type ?? "photo" }] : [];
  });
}

/** OF's horizontal step between two story tiles (its recycle scroller's item size). */
const STORY_STEP = 136;

/**
 * Home's story strip: after "Add to story", one tile per creator in `users` (OF's at-attr="story_item" tile, as
 * captured: the 36px avatar in its ring, the name with the verified mark, the first story's still behind), the strip's
 * tiles laid out again from the left. Each tile is stamped `data-oi-story-user` (the creator's id, which ofMirrorPost's
 * bindStory reads on a click) and, when the feed carries the stories' media, `data-oi-story` (their viewer items). No
 * users (or no strip): the strip stays as captured.
 */
export function applyStories(doc: Document, users: StoryUser[], img: (u: string) => string) {
  const own = doc.querySelector<HTMLElement>(".stories-list .b-story-item.m-story-item-own");
  const view = own?.closest<HTMLElement>(".vue-recycle-scroller__item-view");
  const wrapper = view?.parentElement;
  const shown = users.filter((u) => u.id != null && u.id !== "");
  if (!own || !view || !wrapper || !shown.length) return;
  const vAttrs = (el: Element) => [...own.attributes].filter((a) => a.name.startsWith("data-v-")).forEach((a) => el.setAttribute(a.name, ""));
  const tiles = shown.map((u) => {
    const v = doc.createElement("div");
    v.className = "vue-recycle-scroller__item-view";
    const b = doc.createElement("button");
    b.type = "button";
    vAttrs(b);
    b.className = "b-story-item m-gradient-overlay";
    b.setAttribute("at-attr", "story_item");
    b.dataset.oiStoryUser = String(u.id);
    const name = (u.name || u.username || "").trim();
    b.title = name;
    const items = storyItems(u.stories ?? [], img);
    if (items.length) b.dataset.oiStory = JSON.stringify(items);
    const inside = doc.createElement("div");
    inside.className = "b-story-item__inside m-default-bg";
    inside.setAttribute("data-v-298a5704", "");
    const icon = doc.createElement("span");
    icon.className = "b-story-item__icon m-avatar";
    icon.setAttribute("data-v-298a5704", "");
    const avatar = avatarOf(doc, u, 36, img, "m-border-line");
    avatar.setAttribute("data-v-298a5704", "");
    icon.append(avatar);
    const text = doc.createElement("span");
    text.className = `b-story-item__text g-text-ellipsis user-select-none g-user-name${u.isVerified ? " m-verified" : ""} align-self-start mw-100`;
    text.setAttribute("data-v-298a5704", "");
    text.append(` ${name} `);
    if (u.isVerified) {
      const mark = iconOf(doc, "verified", "m-verified g-icon");
      mark.setAttribute("data-v-298a5704", "");
      text.append(mark);
    }
    inside.append(icon, text);
    const still = (u.stories ?? []).flatMap((st) => st.media ?? []).map((m) => m.files?.thumb?.url || stillUrl(m)).find(Boolean);
    if (still) {
      const pic = doc.createElement("img");
      pic.setAttribute("data-v-298a5704", "");
      pic.src = img(still);
      pic.alt = "thumb";
      pic.draggable = false;
      pic.className = "img-responsive";
      inside.append(pic);
    }
    b.append(inside);
    v.append(b);
    return v;
  });
  view.after(...tiles);
  const views = [...wrapper.querySelectorAll<HTMLElement>(":scope > .vue-recycle-scroller__item-view")];
  const before = views.map((el) => el.style.transform);
  const width = wrapper.style.minWidth;
  views.forEach((el, i) => (el.style.transform = `translateX(${i * STORY_STEP}px)`));
  wrapper.style.minWidth = `${views.length * STORY_STEP}px`;
  track(doc, () => {
    for (const t of tiles) t.remove();
    views.forEach((el, i) => !(tiles as HTMLElement[]).includes(el) && (el.style.transform = before[i]));
    wrapper.style.minWidth = width;
  });
}

/**
 * Someone else's avatar in a cloned row's avatar link `el`: `u`'s picture, else no picture at all (setAvatar would keep
 * the template's), and its letter placeholder marked .of-fan: not the Creator's avatar, so useOfIdentity leaves it.
 */
function otherAvatar(el: Element | null, u: OFUserMini | undefined, img: (u: string) => string) {
  setAvatar(el, u ?? { id: "" }, img);
  if (!u?.avatar) {
    const pic = el?.querySelector("img");
    (pic?.closest(".g-avatar__img-wrapper") ?? pic)?.remove();
  }
  el?.querySelector(".g-avatar__placeholder")?.classList.add("of-fan");
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

/** A `/promotions` item, as OF sends it (service/of_promos.py has the live-captured contract). */
export interface Promotion {
  id?: number | string;
  message?: string | null;
  /** The promotion's price: 0 is a free trial. OF sends no discount on read. */
  price?: number | null;
  /** Who can claim it: "new", "expired" or "all" subscribers. */
  type?: string | null;
  claimsCount?: number | null;
  /** The claim cap (0: no cap). */
  subscribeCounts?: number | null;
  subscribeDays?: number | null;
  isFinished?: boolean | null;
  canClaim?: boolean | null;
}

/** On offer: OF leaves isFinished false on a spent promotion, so canClaim must not be false either. */
export const onOffer = (p: Promotion) => !p.isFinished && p.canClaim !== false;

const PROMO_FOR: Record<string, string> = { new: "For new subscribers", expired: "For expired subscribers", all: "For new and expired subscribers" };

/** OF's card title: "Limited offer - Free trial for 30 days!", "... - 50% off for 31 days" (from the subscription price), else "... - $2.50". */
export function promotionTitle(p: Promotion, subscribePrice?: number | null): string {
  const n = p.subscribeDays ?? 0;
  const days = n > 0 ? ` for ${n} day${n === 1 ? "" : "s"}` : "";
  const price = typeof p.price === "number" ? p.price : null;
  if (price === 0) return `Limited offer - Free trial${days}!`;
  if (price !== null && subscribePrice && subscribePrice > price) return `Limited offer - ${Math.round((1 - price / subscribePrice) * 100)}% off${days}`;
  return `Limited offer${price !== null ? ` - $${price.toFixed(2)}` : ""}${days}`;
}

/**
 * Home's right column: one copy of the generator's hidden promotion card per promotion on offer (onOffer), in the
 * Relay's order: its title (promotionTitle), who it is for and the claims left (a capped one), and its message in the
 * Creator's bubble (`me`'s avatar; no message: no bubble). OF's toggle is plain text there; its Stop promotion
 * (data-oi-finish) and Copy link to profile (data-oi-copy, the profile link) stay for ofMirrorOffers. None on offer: the
 * column shows no card.
 */
export function applyPromotions(doc: Document, promos: Promotion[], subscribePrice: number | null | undefined, me: OFUserMini | undefined, img: (u: string) => string) {
  // My profile has two copies of the column's cards (the wall's column shows them on a phone).
  for (const tpl of doc.querySelectorAll<HTMLElement>("[data-oi-template='promotion']")) promotionCards(doc, tpl, promos, subscribePrice, me, img);
}

function promotionCards(doc: Document, tpl: HTMLElement, promos: Promotion[], subscribePrice: number | null | undefined, me: OFUserMini | undefined, img: (u: string) => string) {
  const wrapper = tpl.parentElement;
  const on = promos.filter(onOffer);
  if (!wrapper || !on.length) return;
  const cards = on.map((p) => {
    const el = make(tpl);
    el.style.removeProperty("display");
    const head = el.querySelector("button.b-menu-list__el");
    if (head) {
      const div = doc.createElement("div");
      for (const a of head.attributes) if (a.name !== "type") div.setAttribute(a.name, a.value);
      div.append(...head.childNodes);
      head.replaceWith(div);
    }
    el.querySelector(".b-menu-list__icon")?.remove(); // the toggle's chevron
    const title = el.querySelector(".b-menu-list__text");
    if (title) title.textContent = ` ${promotionTitle(p, subscribePrice)} `;
    const sub = el.querySelector(".b-offer-join__left-time");
    const proto = sub?.querySelector(".b-offer-join__left-time__el");
    if (sub && proto) {
      const bits = [PROMO_FOR[p.type ?? "all"] ?? PROMO_FOR.all];
      if (p.subscribeCounts) bits.push(`left ${Math.max(0, p.subscribeCounts - (p.claimsCount ?? 0))}`);
      sub.replaceChildren(
        ...bits.map((b) => {
          const x = proto.cloneNode(false);
          x.textContent = ` ${b} `;
          return x;
        }),
      );
    }
    const bubble = el.querySelector(".b-offer-join__bubble");
    const text = plain(p.message);
    const holder = bubble?.querySelector(".b-offer-join__bubble__text .g-truncated-text");
    if (!text || !holder) bubble?.remove();
    else {
      holder.textContent = text;
      setAvatar(bubble!.querySelector(".g-avatar"), me ?? { id: "" }, img);
    }
    // OF's own card buttons: Stop promotion and Copy link to profile (ofMirrorOffers binds both).
    const btns = [...el.querySelectorAll<HTMLButtonElement>(".b-offer-join__btn button")];
    const stop = btns.find((b) => b.textContent?.trim() === "Stop promotion");
    const copy = btns.find((b) => b.textContent?.trim() === "Copy link to profile");
    if (stop && p.id != null) stop.setAttribute("data-oi-finish", String(p.id));
    else stop?.remove();
    if (copy && me?.username) copy.setAttribute("data-oi-copy", `https://onlyfans.com/${me.username}`);
    else copy?.remove();
    for (const b of el.querySelectorAll(".b-offer-join__btn button")) b.setAttribute("data-oi-wired", "");
    if (!el.querySelector(".b-offer-join__btn button")) el.querySelector(".b-offer-join__btn")?.remove();
    return el;
  });
  fill(doc, [tpl], cards, [wrapper]);
  const was = wrapper.getAttribute("style");
  wrapper.removeAttribute("style");
  track(doc, () => (was === null ? wrapper.removeAttribute("style") : wrapper.setAttribute("style", was)));
}

/** Home's Scheduled events widget reads the next 30 days' queue, by the queue pages' /schedules route. */
export const upcoming = (now: Date): Month => {
  const end = new Date(now.getFullYear(), now.getMonth(), now.getDate() + 30);
  return { start: localIso(now).slice(0, 10), end: localIso(end).slice(0, 10) };
};
export const eventsRoute = (now: Date) => SCHEDULES.route(upcoming(now))!;
const EVENT_KIND: Record<string, string> = { post: "Post", chat: "Message", stream: "Stream" };

/**
 * Home's Scheduled events widget: the three soonest items still ahead of `now`, in place of "You have no scheduled
 * events." (kept when there is none), each its date and time, then its kind and text (or "Media"), as plain rows.
 */
export function applyEvents(doc: Document, items: QueueItem[], now: Date) {
  const empty = doc.querySelector<HTMLElement>(".b-widget .b-widget__body > .empty-message");
  const rows = items
    .map((i) => ({ at: valid(SCHEDULES.at(i)), kind: EVENT_KIND[i.type ?? ""], body: i.entity ?? i }))
    .filter((r): r is typeof r & { at: Date } => !!r.at && r.at.getTime() >= now.getTime())
    .sort((a, b) => a.at.getTime() - b.at.getTime())
    .slice(0, 3);
  if (!empty || !rows.length) return;
  const list = doc.createElement("div");
  list.dataset.oiData = "";
  list.className = "b-widget__events";
  list.style.cssText = "padding:8px 0";
  for (const r of rows) {
    const row = doc.createElement("div");
    row.style.cssText = "display:flex;gap:8px;padding:4px 0;font-size:14px;line-height:20px;min-width:0";
    const when = doc.createElement("span");
    when.className = "g-gray-text";
    when.style.whiteSpace = "nowrap";
    when.textContent = stamp(r.at);
    const what = doc.createElement("span");
    what.className = "g-text-ellipsis";
    const text = plain(r.body.text) || ((r.body.mediaCount ?? 0) > 0 ? "Media" : "");
    what.textContent = [r.kind, text].filter(Boolean).join(" · ");
    row.append(when, what);
    list.appendChild(row);
  }
  fill(doc, [empty], []);
  empty.after(list);
  // OF drops the widget's "+" (Add to queue) once it lists events.
  const plus = empty.parentElement!.querySelector<HTMLElement>(":scope > .b-new-event-btn");
  const style = plus?.getAttribute("style") ?? null;
  plus?.style.setProperty("display", "none");
  track(doc, () => {
    list.remove();
    if (!plus) return;
    if (style === null) plus.removeAttribute("style");
    else plus.setAttribute("style", style);
  });
}

/** The Agency's time zone (the top bar's, `preferences.tz`), else the browser's: the queue's days and today, Statements' Earnings' dates. */
export const useAgencyZone = (): string => useAppliedSettings().data?.preferences?.tz || TZ;

/**
 * `at` as the wall clock of `zone` reads it, as a local Date (its getDate, getHours and so on are the zone's): the
 * queue's days, times and today follow the Agency's time zone, not the browser's. No zone, or one Intl does not know:
 * `at` as is.
 */
export function wallClock(at: Date, zone?: string): Date {
  if (!zone) return at;
  try {
    const opts = { timeZone: zone, hourCycle: "h23", year: "numeric", month: "numeric", day: "numeric", hour: "numeric", minute: "numeric", second: "numeric" } as const;
    const p = Object.fromEntries(new Intl.DateTimeFormat("en-US", opts).formatToParts(at).map((x) => [x.type, Number(x.value)]));
    return new Date(p.year, p.month - 1, p.day, p.hour % 24, p.minute, p.second);
  } catch {
    return at;
  }
}

/** The instant whose wall clock in `zone` is `wall`'s local fields (wallClock's inverse; two steps settle a DST edge). */
export function fromWallClock(wall: Date, zone?: string): Date {
  let at = wall;
  for (let i = 0; i < 2; i++) at = new Date(at.getTime() - (wallClock(at, zone).getTime() - wall.getTime()));
  return at;
}

/** The item types the calendar's event bars count (OF's /schedules/counters keys). */
const DAY_TYPES = ["post", "chat", "stream"];

/**
 * Items per local day of `zone` and type, in OF's /schedules/counters shape ({"2026-11-26": {"post": 1}}; a
 * saved-for-later post or message counts as `saved_for_later_post` / `saved_for_later_chat`, as OF's counters do): what a
 * month page's calendar marks. Items with no time or another type are not counted.
 */
export function dayCounts(items: QueueItem[], zone?: string): Record<string, Record<string, number>> {
  const out: Record<string, Record<string, number>> = {};
  for (const i of items) {
    const at = valid(i.publishDateTime || i.createdDateTime);
    if (!at || !i.type || !DAY_TYPES.includes(i.type)) continue;
    const day = (out[localIso(wallClock(at, zone)).slice(0, 10)] ??= {});
    const key = isSavedForLater(i) ? `saved_for_later_${i.type}` : i.type;
    day[key] = (day[key] ?? 0) + 1;
  }
  return out;
}

/** One calendar event bar: OF's type class, its name (the count) and, for a half-tinted bar, the scheduled part in %. */
export interface DayBar {
  type: string;
  name: string;
  value?: string;
}

/**
 * A day's counters as OF's queue store turns them into calendar events (app.js schedule module `R`): a day with both
 * scheduled and saved-for-later posts gets one "posts" bar named by their sum, its `value` the scheduled share in percent
 * (OF's stylesheet paints the bar half-tinted and the `v-event-summary__level` part of that width full); the same for
 * "chats"; any other count is its own bar ("post", "chat", "stream", or "sfl-post" / "sfl-chat" for saved for later
 * alone), named by the count.
 */
export function dayBars(counts: Record<string, number>): DayBar[] {
  const left = { ...counts };
  const bars: DayBar[] = [];
  for (const [type, merged] of [["post", "posts"], ["chat", "chats"]] as const) {
    const n = left[type];
    const later = left[`saved_for_later_${type}`];
    if (!n || !later) continue;
    const sum = n + later;
    bars.push({ type: merged, name: String(sum), value: String(Math.round((n / sum) * 100)) });
    delete left[type];
    delete left[`saved_for_later_${type}`];
  }
  for (const [key, n] of Object.entries(left)) if (n) bars.push({ type: key.replace("saved_for_later_", "sfl-"), name: String(n) });
  return bars;
}

/**
 * Mark a month page's day cells with OF's calendar event bars (`v-event` and the bar's type, painted by its queue
 * stylesheet: `.v-event.post|chat|stream|posts|chats|sfl-post|sfl-chat`), each a `v-event-summary` with the bar's name
 * and, for a half-tinted bar, a `v-event-summary__level` of `value`% width: the queue chunk's v-calendar event slot.
 */
function markDays(doc: Document, counts: Record<string, Record<string, number>>) {
  for (const [day, types] of Object.entries(counts)) {
    const cell = doc.querySelector(`.v-calendar-monthly .b-month-day-cell__value[at-attr='date:${day}']`)?.closest(".v-calendar-weekly__day");
    if (!cell) continue;
    for (const { type, name, value } of dayBars(types)) {
      const bar = doc.createElement("div");
      // white--text: Vuetify's event colour class, as OF's calendar renders its events.
      bar.className = `v-event v-event-start v-event-end ${type} white--text`;
      bar.dataset.oiData = "";
      bar.dataset.date = day;
      const summary = bar.appendChild(doc.createElement("div"));
      summary.className = "v-event-summary pl-1";
      summary.textContent = name;
      if (value) {
        const level = summary.appendChild(doc.createElement("div"));
        level.className = "v-event-summary__level";
        level.style.width = `${value}%`;
      }
      cell.appendChild(bar);
      track(doc, () => bar.remove());
    }
  }
}

/** The month the queue's calendar shows ("October 2026" in its header): its first and last day, yyyy-mm-dd. */
export function queueMonth(doc: Document): Month | null {
  for (const el of doc.querySelectorAll(".b-queue-header__date")) {
    const m = /^([a-z]+) (\d{4})$/i.exec(el.textContent?.trim() ?? "");
    const first = m && parseDate(`${m[1]} 1, ${m[2]}`);
    if (first) return { start: localIso(new Date(first[0], first[1] - 1, 1)).slice(0, 10), end: localIso(new Date(first[0], first[1], 0)).slice(0, 10) };
  }
  return null;
}

/** The event ofMirrorQueue sends on the frame's document when the queue's month, day or tabs change in place. */
export const QUEUE_CHANGE = "oi-queue-change";

/** The month pages' tabs (OF's multiple-choice type filter: none selected shows every type), by their text -> the item type. */
export const QUEUE_TABS: Record<string, string> = { Posts: "post", Messages: "chat", Streams: "stream" };

/** The item types of the queue tabs selected (OF's `m-current`); none: every type. */
export function queueTypes(doc: Document): string[] {
  return [...doc.querySelectorAll(".g-page__subheader .b-tabs__nav__link.m-current")].flatMap((t) => QUEUE_TABS[t.textContent?.trim() ?? ""] ?? []);
}

/** The day the queue's right column shows ("October 12, 2026" in its header), yyyy-mm-dd. */
export function queueDay(doc: Document): string | null {
  const d = parseDate(doc.querySelector(".l-wrapper__sidebar .b-queue-header__date")?.textContent ?? "");
  return d && localIso(new Date(d[0], d[1] - 1, d[2])).slice(0, 10);
}

/**
 * A queue page's items, one OF agenda section per day (soonest first; undated items, as saved for later, in one
 * section with no date), each its time, its text (a stream's description, or "Media") and its source's colour mark,
 * the days and times those of `zone` (wallClock). OF captured no item, so they are built from its agenda classes in
 * the page's agenda scope. A post or message with an id (queueActions) also gets OF's round "More" button and its
 * actions in data-oi-queue-* (ofMirrorQueue opens the menu). The list view fills its own agenda block, the
 * saved-for-later pages a copy of the borrowed one in place of their empty state, only when there is an item. A month
 * page keeps the shown month's items of the selected tabs: its calendar marks their days with OF's event bars and
 * counts (markDays), and the right column lists the shown day's in place of its "no scheduled events for this day"
 * (OF's day view); the borrowed block only lends its agenda scope there, as OF lists nothing under its calendar.
 */
export function applyQueue(doc: Document, page: string, items: QueueItem[], tpl: Element | undefined, zone?: string) {
  const src = QUEUE[page];
  const month = src.month ? queueMonth(doc) : null;
  const types = src.month ? queueTypes(doc) : [];
  const dayOfRow = (at: Date | null) => (at ? localIso(at).slice(0, 10) : "");
  const rows = items
    .filter((i) => !types.length || types.includes(i.type ?? ""))
    .map((i) => {
      const at = valid(src.at?.(i));
      return { item: i, at: at && wallClock(at, zone), mark: src.mark(i), body: i.entity ?? i, actions: queueActions(page, i) };
    })
    .filter((r) => !src.month || (month && r.at && dayOfRow(r.at) >= month.start && dayOfRow(r.at) <= month.end))
    .sort((a, b) => (a.at?.getTime() ?? Infinity) - (b.at?.getTime() ?? Infinity));
  if (!rows.length) return;
  const calendar = doc.querySelector(".v-calendar-monthly");
  if (calendar) markDays(doc, dayCounts(rows.map((r) => r.item), zone));
  // The saved-for-later pages: OF's own cards (ScheduleEventDayView), not agenda rows.
  const sflEmpty = !src.month ? doc.querySelector<HTMLElement>(".saved-for-later > .empty-message") : null;
  if (sflEmpty && src.kind) {
    for (let el = sflEmpty.closest(".m-empty-content"); el; el = sflEmpty.closest(".m-empty-content")) dropClass(doc, el, "m-empty-content");
    fill(doc, [sflEmpty], items.map((i) => sflCard(doc, page, i, src.kind!, zone)));
    return;
  }
  let agenda = doc.querySelector<HTMLElement>(".b-agenda.m-main-block");
  if (!agenda) {
    const empty = doc.querySelector<HTMLElement>(".saved-for-later > .empty-message");
    if (!tpl || !(calendar || empty)) return;
    const copy = make(doc.importNode(tpl, true));
    agenda = copy.querySelector<HTMLElement>(".b-agenda")!;
    if (!calendar) fill(doc, [empty!], [copy]);
  }
  const scope = [...agenda.attributes].filter((a) => a.name.startsWith("data-v-"));
  const built = (tag: string, cls: string, parent?: Element) => {
    const el = doc.createElement(tag);
    for (const a of scope) el.setAttribute(a.name, a.value);
    el.className = cls;
    parent?.appendChild(el);
    return el;
  };
  const addItem = (r: (typeof rows)[number], parent: Element) => {
    const item = built("a", "b-agenda__area-events__item d-flex", parent);
    if (r.mark) item.classList.add(r.mark);
    const content = built("div", "b-agenda__area-events__item-content", item);
    // OF's agenda time; "h:mm* a" for an item saved for later (app.js schedule module `D`).
    built("div", "b-agenda__area-events__item-details", content).textContent = r.at ? (isSavedForLater(r.item) ? clock(r.at).replace(/\s/, "* ") : clock(r.at)) : "";
    built("div", "b-agenda__area-events__item-inward", content).textContent = plain(r.body.text) || plain(r.body.description) || ((r.body.mediaCount ?? 0) > 0 ? "Media" : "");
    if (r.actions) {
      const a = r.actions;
      Object.assign(item.dataset, { oiQueueKind: a.kind, oiQueueTarget: a.target, oiQueueSchedule: a.schedule, oiQueueReady: String(a.ready), oiQueuePinned: String(a.pinned) });
      // OF's ScheduleEventDropdown activator (round dots); data-oi-wired: ofMirrorQueue owns its click, not the read-only fallback.
      const more = built("button", "btn dropdown-toggle m-post-btn m-btn-round-dots", built("div", "b-post__tools__more b-dropdown-wrapper m-dropdown-v2", item));
      const attrs = { type: "button", "aria-label": "More", "aria-haspopup": "true", "aria-expanded": "false", "at-attr": "more_menu", "data-oi-wired": "" };
      for (const [k, v] of Object.entries(attrs)) more.setAttribute(k, v);
      const svg = more.appendChild(doc.createElementNS(SVG, "svg"));
      for (const [k, v] of Object.entries({ class: "g-icon", "data-icon-name": "icon-more", viewBox: "0 0 24 24", "aria-hidden": "true" })) svg.setAttribute(k, v);
      svg.appendChild(doc.createElementNS(SVG, "path")).setAttribute("d", MORE_ICON);
    }
  };
  if (!calendar) {
    // OF's empty-page layout centres the block.
    for (let el = agenda.closest(".m-empty-content"); el; el = agenda.closest(".m-empty-content")) dropClass(doc, el, "m-empty-content");
    const sections: HTMLElement[] = [];
    let day: string | undefined;
    for (const r of rows) {
      const key = r.at?.toDateString() ?? "";
      if (key !== day) {
        day = key;
        const section = built("div", "b-agenda__section d-flex");
        section.dataset.oiData = "";
        built("div", "b-agenda__section-date", section).textContent = r.at ? dayOf(r.at) : "";
        built("div", "b-agenda__area-events", section);
        sections.push(section);
      }
      addItem(r, sections[sections.length - 1].lastElementChild!);
    }
    const empty = agenda.querySelector<HTMLElement>(":scope > .empty-message");
    fill(doc, empty ? [empty] : [], sections, [agenda]);
  }
  // The right column: the day it shows.
  const side = src.month ? doc.querySelector<HTMLElement>(".l-wrapper__sidebar") : null;
  const sideEmpty = side?.querySelector<HTMLElement>(":scope > .empty-message");
  const shown = src.month ? queueDay(doc) : null;
  const ofDay = rows.filter((r) => shown && dayOfRow(r.at) === shown);
  if (!side || !sideEmpty || !ofDay.length) return;
  const list = built("div", "b-agenda");
  list.dataset.oiData = "";
  for (const r of ofDay) addItem(r, list);
  fill(doc, [sideEmpty], [list], [side]);
  dropClass(doc, side, "m-empty-section");
}

/** OF's card scopes (ScheduleEventDayView and its queue rows), linked on the queue pages by the generator. */
const CARD = "data-v-48bf68d0";
const CARD_ROW = "data-v-48f703ce";
const SVG_NS = "http://www.w3.org/2000/svg";

/**
 * One saved-for-later item as OF's saved-for-later pages show it (ScheduleEventDayView, captured live 2026-10-17): its
 * kind's icon, the day it was saved ("Oct 17, 2026"), "Later" and, for a message, who it goes to ("to <username>"), the
 * More button, the time with OF's star ("7:26* pm"), a post's disabled "Add labels" and the text. Its ids go on the card
 * (data-oi-queue-*) for ofMirrorQueue's row menu.
 */
export function sflCard(doc: Document, page: string, i: QueueItem, kind: QueueKind, zone?: string): HTMLElement {
  const body = i.entity ?? i;
  const at = valid(i.publishDateTime || i.createdDateTime);
  const wall = at && wallClock(at, zone);
  const el = (tag: string, cls: string, scope: string, parent?: Element) => {
    const e = doc.createElement(tag);
    e.setAttribute(scope, "");
    e.className = cls;
    parent?.appendChild(e);
    return e;
  };
  const icon = (parent: Element, name: string, cls = "g-icon") => {
    const svg = parent.appendChild(doc.createElementNS(SVG_NS, "svg"));
    for (const [k, v] of Object.entries({ class: cls, "data-icon-name": name, "aria-hidden": "true" })) svg.setAttribute(k, v);
    svg.appendChild(doc.createElementNS(SVG_NS, "use")).setAttribute("href", `#${name}`);
    return svg;
  };
  const post = kind === "post";
  const card = el("div", `b-post is-not-post-page m-queue-post m-appearance-message m-save-later ${post ? "sfl-post" : "sfl-message"}`, CARD);
  card.dataset.oiData = "";
  const head = el("div", "b-post__header", CARD, card);
  icon(el("span", "b-post__queue-icon", CARD, head), post ? "icon-saved-for-later-posts" : "icon-saved-for-later-message", `${post ? "m-post-color" : "m-chat-color"} g-icon`);
  const row1 = el("div", "b-post__queue-row", CARD_ROW, head);
  row1.setAttribute(CARD, "");
  el("div", "b-post__queue-cell m-date-case", CARD_ROW, row1).textContent = wall ? ` ${wall.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })} ` : "";
  const cell = el("div", "b-post__queue-cell", CARD_ROW, row1);
  el("span", "b-queue-post-info m-mr-5", CARD_ROW, cell).textContent = " Later ";
  if (!post && body.sentRulesExtra) el("span", "b-post__queue-cell__item g-text-ellipsis", CARD_ROW, cell).textContent = ` to ${body.sentRulesExtra} `;
  const a = queueActions(page, i);
  if (a) {
    Object.assign(card.dataset, { oiQueueKind: a.kind, oiQueueTarget: a.target, oiQueueSchedule: a.schedule, oiQueueReady: String(a.ready), oiQueuePinned: String(a.pinned) });
    const more = el("div", "b-post__tools__more", CARD_ROW, cell);
    const wrap = more.appendChild(doc.createElement("div"));
    wrap.className = "b-dropdown-wrapper m-dropdown-v2";
    const btn = wrap.appendChild(doc.createElement("button"));
    for (const [k, v] of Object.entries({ type: "button", "aria-haspopup": "true", "aria-expanded": "false", "aria-label": "More", "at-attr": "more_menu", "data-oi-wired": "" })) btn.setAttribute(k, v);
    btn.className = "btn dropdown-toggle m-post-btn m-btn-horizontal-dots m-with-hover-highlight";
    icon(btn, "icon-more");
  }
  const row2 = el("div", "b-post__queue-row", CARD_ROW, head);
  row2.setAttribute(CARD, "");
  el("div", "b-post__queue-cell m-time-passed", CARD_ROW, row2).textContent = wall ? ` ${clock(wall).replace(/\s/, "* ")} ` : "";
  if (post) {
    const labels = el("div", "b-post__labels-controls", CARD, card);
    const list = labels.appendChild(doc.createElement("div"));
    list.setAttribute("data-v-74f8aaf2", "");
    list.className = "b-list-titles m-right-together b-post__queue_labels g-gray-text";
    const add = list.appendChild(doc.createElement("button"));
    add.type = "button";
    add.disabled = true;
    add.title = NOT_YET;
    add.className = "g-btn m-flat m-link m-default-font-weight m-no-uppercase m-reset-width b-dot-item";
    add.innerHTML = '<span class="b-list-titles__item__text"> Add labels </span>';
  }
  const content = el("div", `b-post__content ${post ? "m-type-post" : "m-type-message"}`, CARD, card);
  const text = el("div", "b-post__text m-break-word", CARD, content);
  const inner = el("div", "b-post__text-el m-possible-markdown", CARD, text);
  const truncated = inner.appendChild(doc.createElement("div"));
  truncated.className = "g-truncated-text m-break-word";
  truncated.appendChild(doc.createElement("div")).textContent = plain(body.text) || ((body.mediaCount ?? 0) > 0 ? "Media" : "");
  return card;
}

/** A `/users/notifications` item (its fan in `user`, else `fromUser`). */
export interface MirrorNotification {
  type?: string;
  text?: string | null;
  /** OF's placeholders in `text` and what each stands for. */
  replacePairs?: Record<string, string>;
  createdAt?: string;
  isRead?: boolean;
  user?: OFUserMini;
  fromUser?: OFUserMini;
}

/**
 * Notifications tab -> its Relay route: All with no type, the others their type, the value OF's own tab sends (its route
 * name, read from OF's bundle: Tips `tip`, Likes `favorited`, Promotions `message`, OnlyFans `deactivated_media`). Tags
 * reads OF's own source for that tab, `/release-forms/mentions`, whose items are notification-shaped.
 */
export const NOTIFICATIONS: Record<string, string> = {
  "notifications/index": "/api/of/v2/users/notifications?limit=20",
  "notifications/subscribed": "/api/of/v2/users/notifications?limit=20&type=subscribed",
  "notifications/commented": "/api/of/v2/users/notifications?limit=20&type=commented",
  "notifications/mentioned": "/api/of/v2/users/notifications?limit=20&type=mentioned",
  "notifications/tip": "/api/of/v2/users/notifications?limit=20&type=tip",
  "notifications/purchases": "/api/of/v2/users/notifications?limit=20&type=purchases",
  "notifications/favorited": "/api/of/v2/users/notifications?limit=20&type=favorited",
  "notifications/message": "/api/of/v2/users/notifications?limit=20&type=message",
  "notifications/deactivated_media": "/api/of/v2/users/notifications?limit=20&type=deactivated_media",
  "notifications/tags": "/api/of/v2/release-forms/mentions?limit=20",
};

/** `/users/notifications/count`: the unread count per tab type (`all`, `subscribed`, `tip`, ...). */
export type NotificationCounts = Record<string, number | null | undefined>;
export const NOTIFICATION_COUNTS = "/api/of/v2/users/notifications/count";

/** OF's tab count formatter: nothing at zero, else the number, capped at `max` ("99+"). */
const tabCount = (n: unknown, max = 9999) => {
  const v = Number(n);
  return !v || v <= 0 ? "" : v > max ? `${max}+` : `${v}`;
};

/**
 * The notifications tab bar: each tab shows its type's count from `counts` (All capped at 99, as OF), Tags the
 * Creator's `newTagsCount` (from "who am I", as OF); a tab with none shows no count. The captured counts are hidden.
 */
export function applyNotificationCounts(doc: Document, counts: NotificationCounts, newTags?: number | null) {
  for (const a of doc.querySelectorAll("a.b-tabs__nav__link[href^='/of-manager/notifications']")) {
    const label = a.querySelector(".b-tabs__nav__text");
    if (!label) continue;
    const type = (a.getAttribute("href") ?? "").slice("/of-manager/notifications/".length) || "all";
    const text = type === "tags" ? tabCount(newTags) : tabCount(counts[type], type === "all" ? 99 : undefined);
    const span = doc.createElement("span");
    span.className = "b-tabs__nav__count";
    span.textContent = ` ${text} `;
    fill(doc, [...label.querySelectorAll<HTMLElement>(".b-tabs__nav__count")], text ? [span] : [], [label]);
  }
}

/** A notification type -> its avatar badge icon: the two measured on the captured tabs (no badge for the others). */
const NOTIFICATION_ICONS: Record<string, string> = { subscribed: "icon-follow", tip: "icon-price", tipped: "icon-price" };

/**
 * A notifications tab: one copy of its plain row (the first with no list link, "Add to favorites and other lists") per
 * notification, in order: the fan's name, @handle and avatar (none: no picture, never the example's), its text with OF's
 * replace pairs as plain text, its date with the hover stamp (none: no date), the unread mark only when unread, and the
 * type's measured badge icon (other types: no badge). With a row, a tab OF captured empty loses its "No notifications
 * currently!" and its centring layout; an empty list keeps them.
 */
export function applyNotifications(doc: Document, items: MirrorNotification[], img: (u: string) => string) {
  const views = [...doc.querySelectorAll<HTMLElement>(".b-notifications__list .vue-recycle-scroller__item-view")];
  const tpl = views.find((v) => v.querySelector(".b-notifications__list__item") && !v.querySelector(".b-list-titles a"));
  if (!tpl) return;
  const clones = items.map((n, i) => {
    const el = make(tpl);
    el.style.removeProperty("display"); // the generator's hidden template
    const u = n.user ?? n.fromUser;
    el.querySelector("[data-index]")?.setAttribute("data-index", String(i));
    el.querySelector(".b-notifications__list__item")?.classList.toggle("m-unread", n.isRead === false);
    const name = el.querySelector(".b-username .g-user-name");
    if (name) {
      name.classList.remove("m-verified"); // the example's verified mark (the Relay sends none)
      name.textContent = u ? ` ${nameOf(u)} ` : "";
    }
    const handle = el.querySelector(".g-user-username");
    if (handle) handle.textContent = u ? ` @${handleOf(u)} ` : "";
    otherAvatar(el.querySelector(".b-available-users__round-img .g-avatar"), u, img);
    const icon = NOTIFICATION_ICONS[n.type ?? ""];
    const badge = el.querySelector(".b-notifications__avatar__icon");
    if (icon && badge) setIcon(badge, icon);
    else badge?.remove();
    const text = el.querySelector(".b-notifications__list__item__text .g-truncated-text");
    if (text) text.textContent = plain(Object.entries(n.replacePairs ?? {}).reduce((t, [k, v]) => t.split(k).join(v), n.text ?? ""));
    const date = el.querySelector(".g-date > span");
    const at = valid(n.createdAt);
    if (date && at) {
      date.textContent = ` ${dayOf(at)} `;
      date.setAttribute("title", stamp(at));
    } else date?.remove();
    return el;
  });
  const empty = items.length ? [...doc.querySelectorAll<HTMLElement>(".b-notifications__list .empty-message")] : [];
  const tab = items.length && doc.querySelector(".b-notifications.m-empty-page");
  if (tab) dropClass(doc, tab, "m-empty-page");
  fill(doc, [...views, ...empty], clones);
}

/**
 * A notifications tab before its notifications are here: OF's "No notifications currently!" reads "Loading
 * notifications…" while the Relay answers (`error` null), or the red "Could not load notifications: <the Relay's text>"
 * after it failed (as Home's feed, applyFeedStatus).
 */
export function applyNotificationsStatus(doc: Document, error: string | null) {
  const text = doc.querySelector<HTMLElement>(".b-notifications__list .infinite-status-prompt:not([style*='none']) > .empty-message > span");
  if (!text) return;
  const [was, style] = [text.textContent, text.getAttribute("style")];
  track(doc, () => {
    text.textContent = was;
    if (style === null) text.removeAttribute("style");
    else text.setAttribute("style", style);
  });
  text.textContent = error === null ? "Loading notifications…" : `Could not load notifications: ${error}`;
  if (error !== null) text.style.color = "#ff4545";
}

/**
 * Statements' Earnings, Payouts and Referrals tables while their rows load (`null`) or after they failed: OF's empty row
 * says so (as Home's feed, applyFeedStatus).
 */
export function applyStatementsStatus(doc: Document, error: string | null) {
  const text = [...doc.querySelectorAll<HTMLElement>(".b-table tbody > tr .empty-message > span")].find((s) => !s.closest("[style*='none']"));
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

/**
 * A `/payouts/transactions` item: OF's own fields (fixtures app/lib/__fixtures__/of/statements-transactions*.json; build
 * 202610091632: statements-earnings.js's StatementsEarningsList, Description and StatusTip).
 */
export interface Transaction {
  createdAt?: string;
  amount?: number | null;
  fee?: number | null;
  net?: number | null;
  /** "USD": UtilsMoney's symbol ($, € or £; another code follows the figure). */
  currency?: string | null;
  /** HTML: its fan link becomes text. */
  description?: string | null;
  /** `done`: Complete; `loading`: pending, `payoutPendingDays` until it is available. */
  status?: string;
  payoutPendingDays?: number | null;
  /** The fan: a deleted or inactive one is OF's greyed name (m-disabled-username). */
  user?: { isDeleted?: boolean | null; isActive?: boolean | null } | null;
}

/** An infinite list's next page (Statements' Earnings, a list's Posts tab), OF's infinite loading row: being read, its error, or `next` asks for it (null: no more). */
export interface MorePages {
  loading: boolean;
  error: string | null;
  next: (() => void) | null;
}

/** OF's UtilsMoney: the currency's symbol and the figure with two decimals and thousands commas ("$1,234.50"). */
export function ofMoney(v: number, currency?: string | null): string {
  const figure = v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const code = (currency || "usd").toLowerCase();
  const symbol = ({ usd: "$", eur: "€", gbp: "£" } as Record<string, string>)[code];
  return symbol ? `${symbol}${figure}` : `${figure} ${code.toUpperCase()}`;
}

/** A transaction's money cell: ` $5.00 ` (none: empty), with OF's m-zero-value when it rounds to 0. */
function moneyCell(span: Element | null, v: number | null | undefined, currency?: string | null) {
  if (!span) return;
  const n = typeof v === "number" && Number.isFinite(v) ? v : null;
  span.textContent = n === null ? "" : ` ${ofMoney(n, currency)} `;
  span.classList.toggle("m-zero-value", n !== null && Math.round(n) === 0);
  if (!span.getAttribute("class")) span.setAttribute("class", "");
}

/** "UTC +02:00": `zone`'s offset at `now` (none or unknown: the browser's), as OF's dayjs().format("Z"). */
export function zoneNote(zone?: string | null, now: Date = new Date()): string {
  const at = new Date(Math.floor(now.getTime() / 60_000) * 60_000);
  const mins = -at.getTimezoneOffset() + Math.round((wallClock(at, zone ?? undefined).getTime() - at.getTime()) / 60_000);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `UTC ${mins < 0 ? "-" : "+"}${pad(Math.floor(Math.abs(mins) / 60))}:${pad(Math.abs(mins) % 60)}`;
}

/** "$5.00": OF's statements money (none: empty). */
const dollars = (v: number | null | undefined) => (typeof v === "number" && Number.isFinite(v) ? ` $${v.toFixed(2)} ` : "");

/**
 * A statements table's rows: hide `examples` (and, while `clones` show, OF's empty row), put `clones` (shown: their
 * template is the generator's hidden row) before the table's loading row (none: at the table's end).
 */
function intoTable(doc: Document, body: Element, examples: HTMLElement[], clones: HTMLElement[]) {
  const empty = clones.length ? [...body.querySelectorAll<HTMLElement>(":scope > tr")].filter((r) => r.querySelector(".empty-message")) : [];
  const hide = [...examples, ...empty].filter((r) => !/display:\s*none/.test(r.getAttribute("style") ?? ""));
  if (hide.length) fill(doc, hide, [], [body]);
  const end = body.querySelector(".infinite-loading-container")?.closest("tr");
  for (const c of clones) {
    c.style.removeProperty("display");
    if (!c.getAttribute("style")) c.removeAttribute("style");
    if (end) end.before(c);
    else body.append(c);
    track(doc, () => c.remove());
  }
}

/** Set a cloned statements row's date and time from `createdAt` as `zone`'s wall clock reads it (none: empty; no zone: the browser's), then each [selector, text] cell. */
function setCells(el: Element, createdAt: string | undefined, cells: [string, string][], zone?: string) {
  const v = valid(createdAt);
  const at = v && wallClock(v, zone);
  const all: [string, string][] = [
    [".b-table__date__date > span", at ? ` ${fullDay(at)} ` : ""],
    [".b-table__date__time > span", at ? ` ${clock(at)} ` : ""],
    ...cells,
  ];
  for (const [sel, text] of all) {
    const cell = el.querySelector(sel);
    if (cell) cell.textContent = text;
  }
}

/**
 * Statements' Earnings: one copy of a captured row per transaction, in order, before the table's loading row. Its date
 * and time in `zone` (the Agency's time zone; none: the browser's, as the "Date/Time shown in local time (UTC ±hh:mm)"
 * note above the table then says), amount, fee and net in OF's money format (none: empty) and its description as plain
 * text, greyed for a deleted or inactive fan; a done item is the "Complete" row, a pending one ("loading") the pending
 * row, its tip "Earning will become available in N days" (no N: no tip text), any other status no status tips. `more`:
 * OF's infinite loading row shows its spinner while the next page is read, its "Opps, something went wrong" with Retry
 * after that failed, and otherwise asks for the next page once it scrolls into view. The balance boxes and the other
 * tabs stay as captured.
 */
export function applyTransactions(doc: Document, items: Transaction[], zone?: string, more?: MorePages) {
  const rows = [...doc.querySelectorAll<HTMLElement>(".b-table tbody > tr")].filter((r) => r.querySelector(".b-table__date"));
  const row = (icon: string) => rows.find((r) => r.querySelector(`.b-table__status svg[data-icon-name='${icon}']`));
  const done = row("icon-done");
  const pending = row("icon-loading"); // Statements' index captures none: a pending item there shows no status tips
  const body = doc.querySelector(".b-table tbody");
  if (!done || !body) return;
  const note = doc.querySelector(".b-statements__head-timezone");
  if (note) {
    const was = note.textContent;
    const text = ` Date/Time shown in local time (${zoneNote(zone)}) `;
    if (was !== text) {
      track(doc, () => (note.textContent = was));
      note.textContent = text;
    }
  }
  const clones = items.map((t) => {
    const asPending = t.status === "loading" && pending;
    const el = make(asPending || done);
    setCells(el, t.createdAt, [], zone);
    moneyCell(el.querySelector(".b-table__amount > span"), t.amount, t.currency);
    moneyCell(el.querySelector(".b-table__fee > span"), t.fee, t.currency);
    moneyCell(el.querySelector(".b-table__net strong > span"), t.net, t.currency);
    const desc = el.querySelector(".b-table__desc .b-field-subscription");
    if (desc) {
      desc.classList.toggle("m-disabled-username", !!t.user && (!!t.user.isDeleted || t.user.isActive === false));
      desc.textContent = plain(t.description);
    }
    // Both copies: the status column's tip and the one inside the description (OF's narrow layout).
    if (t.status !== "done") {
      for (const tip of el.querySelectorAll(".b-table__status-tip")) {
        if (!asPending) tip.remove();
        else if (t.payoutPendingDays == null) tip.removeAttribute("aria-label");
        else tip.setAttribute("aria-label", `Earning will become available in ${t.payoutPendingDays} days`);
      }
    }
    return el;
  });
  intoTable(doc, body, rows, clones);
  if (more) applyMore(doc, body, more);
}

/** OF's infinite loading row (vue-infinite-loading's prompts: spinner, no more, no results, error): see applyTransactions. */
function applyMore(doc: Document, body: Element, more: MorePages) {
  const box = body.querySelector<HTMLElement>(".infinite-loading-container");
  if (!box) return;
  const [spinner, , , failed] = box.querySelectorAll<HTMLElement>(":scope > .infinite-status-prompt");
  const show = (el: HTMLElement | undefined) => {
    if (!el) return;
    const was = el.getAttribute("style");
    track(doc, () => (was === null ? el.removeAttribute("style") : el.setAttribute("style", was)));
    el.style.removeProperty("display");
  };
  if (more.loading) return show(spinner);
  if (more.error !== null) {
    show(failed);
    const retry = failed?.querySelector("button");
    const next = more.next;
    if (retry && next) {
      retry.addEventListener("click", next);
      track(doc, () => retry.removeEventListener("click", next));
    }
    return;
  }
  const next = more.next;
  const IO = doc.defaultView?.IntersectionObserver;
  if (!next || !IO) return;
  const io = new IO((entries) => {
    if (!entries.some((e) => e.isIntersecting)) return;
    io.disconnect();
    next();
  }, { rootMargin: "0px 0px 300px 0px" });
  io.observe(box);
  track(doc, () => io.disconnect());
}

/**
 * A `/payouts/requests` or `/payouts/requests/referral` item. Field names and states are OF's own (build 202610091632:
 * statements-payout.js's StatementsPayoutRequestsList and the referrals table's StatePayout read `invoiceId`, `state`,
 * `rejectReason`).
 */
export interface Payout {
  createdAt?: string;
  invoiceId?: string | number | null;
  amount?: number | null;
  /** `approved`: processed; `new` or `pending`: pending; `rejected`: returned, with its `rejectReason`. */
  state?: string;
  rejectReason?: string | null;
}

/**
 * Statements' Payouts (its own rows, `tpl` absent) or Referrals (`tpl`: the Payouts tab's approved row, borrowed, with
 * the rejected row beside it in its capture): one copy per payout, in order, before the table's loading row (Referrals:
 * at its end, its "This list is empty" row hidden while rows show). Its date, time, invoice and amount (none: empty);
 * an approved payout is the row "Payout has been processed", a rejected one the rejected row with its "Reason:" line
 * the payout's reason (none: no line), a new or pending one OF's pending mark (its loading icon: OF's wording for it
 * was never captured), any other state an empty status cell, as OF's getDescription.
 */
export function applyPayouts(doc: Document, items: Payout[], tpl?: Element) {
  const body = doc.querySelector(".b-table tbody");
  if (!body) return;
  const trs = [...body.querySelectorAll<HTMLElement>(":scope > tr")];
  const own = trs.filter((r) => r.querySelector(".b-table__date"));
  const pool = tpl ? [...(tpl.parentElement?.children ?? [tpl])] : own;
  const row = (state: string) => {
    const r = pool.find((p) => p.querySelector(".b-table__date") && p.querySelector(`.b-table__desc > span.${state}`));
    return r && tpl ? doc.importNode(r, true) : r;
  };
  const approved = row("approved");
  const rejected = row("rejected");
  if (!approved || !rejected) return;
  const clones = items.map((p) => {
    const el = make(p.state === "rejected" ? rejected : approved);
    setCells(el, p.createdAt, [
      [".b-table__invoice", p.invoiceId == null || p.invoiceId === "" ? "" : ` ${p.invoiceId} `],
      [".b-table__amount strong > span", dollars(p.amount)],
    ]);
    const desc = el.querySelector(".b-table__desc");
    if (p.state === "rejected") {
      const br = desc?.querySelector(":scope > span.rejected > br");
      const line = br?.nextSibling?.nodeType === 3 ? br.nextSibling : null; // "Reason: …"
      const reason = plain(p.rejectReason);
      if (line && reason) line.textContent = `Reason: ${reason}`;
      else {
        line?.remove();
        br?.remove();
      }
    } else if (p.state === "new" || p.state === "pending") {
      const mark = desc?.querySelector(":scope > span.approved");
      if (mark) {
        mark.className = "pending";
        for (const n of [...mark.childNodes]) if (n.nodeType === 3) n.remove();
        mark.querySelector("use")?.setAttribute("href", "#icon-loading");
      }
    } else if (p.state !== "approved") desc?.replaceChildren();
    return el;
  });
  intoTable(doc, body, own, clones);
}

/** A `/users/{id}/streams` item: a past live stream. */
export interface PastStream {
  id?: number | string;
  media?: { files?: { thumb?: { url?: string | null } } } | null;
  viewsCount?: number | null;
  startedAt?: string;
}

/**
 * Streaming's dashboard, "Past live streams": one thumb per stream with media (as OF lists them), in OF's markup: its
 * thumb picture (none: no picture), "View stats" (disabled with the tooltip), "Viewers: n" and the start date with its hover
 * stamp. With a thumb, the page and the list lose OF's empty-list centring; an empty list keeps the capture.
 */
export function applyPastStreams(doc: Document, streams: PastStream[], img: (u: string) => string) {
  const thumbs = doc.querySelector(".b-s-dashboard__thumbs");
  const shown = streams.filter((s) => s.media);
  if (!thumbs || !shown.length) return;
  const scope = [...thumbs.attributes].filter((a) => a.name.startsWith("data-v-"));
  const built = (tag: string, cls: string, parent?: Element, text?: string) => {
    const el = doc.createElement(tag);
    for (const a of scope) el.setAttribute(a.name, a.value);
    if (cls) el.className = cls;
    if (text != null) el.textContent = text;
    parent?.appendChild(el);
    return el;
  };
  const clones = shown.map((s) => {
    const holder = built("div", "b-s-dashboard__thumb-holder g-position-relative");
    holder.dataset.oiData = "";
    const preview = built("div", "b-s-dashboard__thumb-holder_preview m-default-bg", holder);
    const thumb = s.media?.files?.thumb?.url;
    if (thumb) built("img", "", preview).setAttribute("src", img(thumb));
    // OF's stats modal was never captured: View stats is disabled with the tooltip.
    const stats = built("button", "g-btn m-rounded", built("div", "b-s-dashboard__btn w-100 text-center", preview), " View stats ");
    stats.setAttribute("type", "button");
    stats.setAttribute("disabled", "disabled");
    stats.setAttribute("title", NOT_YET);
    const content = built("div", "b-s-dashboard__thumb-content g-md-text", holder);
    built("span", "b-viewers-counter", built("div", "b-s-dashboard__thumb-content__viewers", content, " Viewers: "), String(s.viewsCount ?? 0));
    const time = built("div", "b-s-dashboard__thumb-content__time", content);
    const at = valid(s.startedAt);
    if (at) built("span", "", time, ` ${dayOf(at)} `).setAttribute("title", stamp(at));
    return holder;
  });
  fill(doc, [], clones, [thumbs]);
  const page = thumbs.closest(".g-sides-gaps");
  if (page) dropClass(doc, page, "d-flex", "flex-column");
  const loader = thumbs.parentElement?.querySelector(":scope > .infinite-loading-container");
  if (loader) dropClass(doc, loader, "mt-auto", "mb-auto");
}
