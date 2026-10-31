"use client";

/**
 * Real rows on the OF mirror's list pages. With a single model selected (on Messages and My profile also in All
 * models: the first model, see standInModel), the messages list (its partners named from /users/list), the chat page,
 * the vault's folder list and the collections user lists show that model's rows (via the relay) instead of the captured
 * examples: each example row node is hidden and the template row is cloned
 * per real row, keeping OF's markup and classes. Rows link with the real id:
 * a chat to /of-manager/messages/chat?chat=<fanId> (its header, title and
 * thread then show that chat; links to its state/modal pages keep the query),
 * a vault folder to /of-manager/vault?list=<id> (the media grid then shows that
 * folder's media; with no ?list= the vault's ALL MEDIA; the Vault page's grid loads OF's next 24 as it is scrolled to its
 * end: vaultPagesQuery), a user list to
 * /of-manager/collections/user-lists/list?list=<id> (title and user cards; its Posts tab, list/posts?list=<id>, the list's
 * users' posts, ?postType= its type chip, as OF's).
 * New post's vault dialog (new-post/state-vault) shows the same vault media grid, the Post draft's
 * picks marked (ofMirrorPost handles the tile clicks).
 * A chat message's media shows in OF's own media bubble markup.
 * The feed pages (Home, My profile, its Media tab, All bookmarks, the queue, the notifications, Statements' Earnings, Payouts and Referrals, Streaming's dashboard and the schedule form's right column) are drawn by ofMirrorFeeds;
 * a real post row's like, comments and (the Creator's own post) More menu are ofMirrorHome's; another creator's post's
 * More button is disabled with the "Not available in Inflowwww yet" tooltip; collections' writes are ofMirrorCollections'.
 * Home and the notifications tabs keep no example (the generator drops Home's example post, fan stories, alerts and
 * promo cards, and every tab's example rows and counts; the story tiles are the Creator's own active stories, GET /users/{id}/stories, then the creators GET /stories lists: stripUsers, with GET /streams/feed's live and scheduled streams and the watched creators after the promotion tile: applyStories): with no data they show OF's own empty states. Elsewhere, all models, no data yet or a relay error: the examples stay (and their
 * ?row= links still work, see useOfRow). The query is read from the app URL;
 * the frame's src never carries it.
 */

import { useEffect, useMemo, useRef, useState, type RefObject } from "react";
import { infiniteQueryOptions, useInfiniteQuery, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "next/navigation";
import { useScope } from "@/contexts/ScopeContext";
import { relay, type OFChatItem, type OFMedia, type OFMessage, type OFUserMini, type VaultAiFields, type VaultList, type VaultMedia, type VaultMediaResp } from "@/lib/relay";
import { clockTime } from "@/lib/format";
import { proxyImage } from "@/lib/mediaUrl";
import { stillUrl } from "@/lib/ofMedia";
import { basePage, CHAT_VAULT, HOME_VAULT, homeDraft, keepQuery, MASS_VAULT, VAULT_DIALOG } from "@/lib/ofMirrorRow";
import { loadDraft } from "@/lib/ofMirrorPost";
import { loadVaultPick, MASS_SEND, vaultPickKey } from "@/lib/ofMirrorChat";
import { formatCount, ofMeQuery } from "@/lib/ofMirrorIdentity";
import { LIST_SORTS, vaultListsPath, vaultMediaPath, viewOf } from "@/lib/ofMirrorVault";
import { message, NOT_YET } from "@/lib/ofMirrorWrites";
import { undoList } from "@/lib/ofMirrorUndo";
import { nextFeedOffset, nextMarker, nextOffset, pageRows, POSTS_PAGE, rowsOf, uniqueRows } from "@/lib/ofMirrorPaging";
// Re-exported: their importers still read them from here.
export { nextFeedOffset, nextMarker, nextOffset, pageRows, POSTS_PAGE, rowsOf, uniqueRows } from "@/lib/ofMirrorPaging";
import { avatarOf, initials } from "@/lib/ofMirrorAvatar";
import { chatsQuery, chatsRequest, chatsView } from "@/lib/ofMirrorChats";
import { fanIdFromParam } from "@/lib/fanId";
import { useChatList } from "@/hooks/useChatList";
import { UNREAD_PREFETCH_TIERS, useUnreadMessagesPrefetch } from "@/hooks/useUnreadMessagesPrefetch";
import { useChatMessages } from "@/hooks/useChatMessages";
import { useChatPinned } from "@/hooks/useChatPinned";
import { useFanChatMedia } from "@/hooks/useFanChatMedia";
import { applyGallery, applyWith, attachmentIcons, chatHref, dollars, fillIcons, galleryRequest, galleryTab, icon, setIconName, useThreadFind, GALLERY_PAGE, PINNED_PAGE, type GalleryData, type ThreadMessage } from "@/lib/ofMirrorThread";
import { applyProfile, applyProfileStatus, applyRecent, mediaKind, ofKind, PROFILE_CHANGE, type Highlight, type MediaPost, type MirrorProfile, type ProfileUser } from "@/lib/ofMirrorProfile";
import {
  applyColumnPosts,
  applyEvents,
  applyHome,
  applyFeedStatus,
  applyNotificationCounts,
  applyNotifications,
  applyNotificationsStatus,
  applyPastStreams,
  applyPayouts,
  applyPosts,
  applyProfileMedia,
  applyPromotions,
  applyQueue,
  applyStatementsStatus,
  applyStories,
  applyTransactions,
  eventsRoute,
  COLUMN_FEED,
  NOTIFICATION_COUNTS,
  NOTIFICATIONS,
  QUEUE,
  QUEUE_CHANGE,
  queueMonth,
  TEMPLATES,
  useAgencyZone,
  type MirrorNotification,
  type MirrorPost,
  type Month,
  type NotificationCounts,
  type PastStream,
  type Payout,
  type Promotion,
  type QueueItem,
  stripUsers,
  type FeedStream,
  type StoryEntry,
  type StoryUser,
  type MorePages,
  type Template,
  type Transaction,
} from "@/lib/ofMirrorFeeds";

export type Part = "chats" | "chatList" | "thread" | "gallery" | "vaultLists" | "vaultMedia" | "userLists" | "listRow" | "listUsers" | "listPosts" | "subscribers" | "labels" | "posts" | "profileMedia" | "bookmarks" | "queue" | "notifications" | "transactions" | "payouts" | "referrals"
  | "home" | "stories" | "notificationCounts" | "pastStreams" | "promotions" | "events" | "profile";

/** A list's Posts tab (OF's /my/collections/user-lists/<id>/posts). */
export const LIST_POSTS = "collections/user-lists/list/posts";

/** Page (path under of-mirror/pages, or the page its state-* / modal-* subpage belongs to) -> the data it shows. */
export const DATA_PAGES: Record<string, Part[]> = {
  "messages/index": ["chats"],
  messages: ["chats"], // messages/state-*
  "messages/chat": ["chats", "thread"],
  "vault/index": ["vaultLists", "vaultMedia"],
  vault: ["vaultLists", "vaultMedia"], // vault/state-*
  "vault/list": ["vaultLists", "vaultMedia"],
  // New post: the right column's promotions and Scheduled events widget (as Home's).
  "new-post/index": ["promotions", "events"],
  "new-post": ["promotions", "events"], // new-post/state-*
  [VAULT_DIALOG]: ["promotions", "events", "vaultLists", "vaultMedia"], // its picks read from the Post draft
  [CHAT_VAULT]: ["chats", "thread", "vaultLists", "vaultMedia"], // its picks read from the Chat draft
  [MASS_VAULT]: ["vaultLists", "vaultMedia"], // New message's: its picks read from the Mass draft
  // A chat's Gallery: the chat list (its markup borrowed, TEMPLATES' chatList) and the chat's media.
  "messages/chat/gallery": ["chats", "chatList", "gallery"],
  // A chat's pinned messages: OF's chat page (the generator builds it from the chat capture), its thread the pins.
  "messages/chat/pinned": ["chats", "thread"],
  // Collections: the user lists column on every user-lists page; the index shows its first list's users, as OF does.
  "collections/index": ["userLists", "listUsers"],
  "collections/user-lists/list": ["userLists", "listUsers"],
  // A list's Posts tab: its users' posts (their row borrowed, TEMPLATES' post).
  [LIST_POSTS]: ["userLists", "listPosts"],
  "collections/user-lists/subscribers/active": ["userLists", "subscribers"],
  // Following and its tabs: the lists, their row borrowed (TEMPLATES' listRow).
  "collections/user-lists/subscriptions": ["userLists", "listRow"],
  "collections/user-lists/subscriptions/active": ["userLists", "listRow"],
  "collections/user-lists/subscriptions/expired": ["userLists", "listRow"],
  "collections/user-lists/subscriptions/attention": ["userLists", "listRow"],
  "collections/user-lists/subscriptions/posts": ["userLists", "listRow"],
  "collections/post-labels/archived": ["labels"],
  // My profile: its wall (or Media grid), its counts, label tabs and highlights, the Recent strip (the media posts) and
  // the right column's promotions.
  "profile/index": ["posts", "profileMedia", "profile", "promotions"],
  profile: ["posts", "profileMedia", "profile", "promotions"], // profile/state-*
  "profile/media": ["profileMedia", "profile", "promotions"],
  "collections/bookmarks/all": ["bookmarks"],
  // Every queue page: the month pages (calendar, list view and their tab states) and the saved-for-later pages.
  ...Object.fromEntries(Object.keys(QUEUE).map((p) => [p, ["queue"] as Part[]])),
  // Every notifications tab, with the tab bar's counts and the right column's promotions and Scheduled events widget (as Home's).
  ...Object.fromEntries(Object.keys(NOTIFICATIONS).map((p) => [p, ["notifications", "notificationCounts", "promotions", "events"] as Part[]])),
  "streaming/dashboard": ["pastStreams"],
  // The stream schedule form: the right column's promotions and Scheduled events widget (as Home's).
  "streaming/dashboard/create": ["promotions", "events"],
  "statements/earnings": ["transactions"],
  "statements/index": ["transactions"], // its default tab is Earnings
  "statements/payouts": ["payouts"],
  "statements/referrals": ["referrals"],
  // Home: its feed, its story strip, the right column's promotions and its Scheduled events widget.
  "home/index": ["home", "stories", "promotions", "events"],
  home: ["home", "stories", "promotions", "events"], // home/state-*
  [HOME_VAULT]: ["home", "stories", "promotions", "events", "vaultLists", "vaultMedia"], // its picks read from Home's Post draft
};

/** A list's Users and Posts tabs (`?list=<id>` on both, the Posts tab's type chip `?postType=`, as OF's). */
export const LIST_TABS: readonly string[] = ["collections/user-lists/list", LIST_POSTS];
/** A list's Posts tab's type chips, by their text: OF's `postType` (its page) and `type` (GET /lists/<id>/posts). */
export const POST_TYPES: Record<string, string> = { All: "", Photos: "photos", Videos: "videos", Audio: "audios", Other: "other", Locked: "locked" };
/** The type chip `?postType=` asks for (null: All, or none OF has). */
export const postTypeOf = (v: string | null) => (v && Object.values(POST_TYPES).includes(v) ? v : null);
/** A list's Posts tab's feed, one of OF's pages of 10 (`offset` appended per page). */
export const listPostsPath = (list: string, type: string | null) => `/api/of/v2/lists/${encodeURIComponent(list)}/posts?limit=10${type ? `&type=${type}` : ""}`;

export const partsOf = (page: string): Part[] => {
  const key = Object.hasOwn(DATA_PAGES, page) ? page : basePage(page);
  return Object.hasOwn(DATA_PAGES, key) ? DATA_PAGES[key] : [];
};

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

export interface MirrorData {
  /** ?chat=: the open chat's fan id. */
  chat?: string | null;
  /** ?list=: the open vault folder or user list. */
  list?: string | null;
  chats?: OFChatItem[];
  /** The chat list while `chats` is not here: still loading (null), or the Relay's error text. */
  chatsStatus?: string | null;
  /** The chat list's view as a query string (ofMirrorChats' chatsQuery): its rows' and the chat's links carry it. */
  listQuery?: string;
  /** The chat list's next page: OF's loader shows while it is read. */
  chatsMore?: MorePages;
  /** The open chat: its partner (null: unknown) and messages. */
  thread?: { fan: OFUserMini | null; messages: OFMessage[] };
  /** The open chat's partner, wherever it is known from (its detail, else its chat list row). */
  chatFan?: OFUserMini | null;
  /** The open chat's pinned messages count (its detail's countPinnedMessages): the header's pin lights while it is > 0. */
  pinnedCount?: number;
  /** The open chat's Gallery tab and tiles (messages/chat/gallery). */
  gallery?: GalleryData;
  vaultLists?: VaultList[];
  /** The vault's "All media" row: its counts (the folder list's `all`). */
  vaultAll?: Partial<VaultList>;
  /** The folders' sort (the folder list's `sort`), their column's title. */
  vaultSort?: string;
  /** The folder column's search (?slist=): OF shows "All media" then only if its name starts with it. */
  vaultSearch?: string | null;
  /** The vault media read before it is here: null while loading, the Relay's text after a failure, undefined once here. */
  vaultStatus?: string | null;
  /** The open vault folder's media (all media with no ?list=), newest first; the Relay's AI overlay on its mirror path. */
  vaultMedia?: (VaultMedia & { _ai?: VaultAiFields })[];
  /** New post's vault dialog: the vault ids in the Post draft (their tiles are marked selected). Absent: not a picker. */
  picked?: (number | string)[];
  userLists?: UserList[];
  /** The user lists column while `userLists` is not here: still loading (null), or the Relay's error text. */
  userListsStatus?: string | null;
  /** The open list's users (?list=, the index's first list). */
  listUsers?: OFUserMini[];
  /** A list's Posts tab: the open list's users' posts of the `postType` chip (null: All), their authors in `authors`. */
  listPosts?: MirrorPost[];
  /** The Posts tab's feed while `listPosts` is not here: still loading (null), or the Relay's error text. */
  listPostsStatus?: string | null;
  /** The Posts tab's next page (OF's infinite loader). */
  listPostsMore?: MorePages;
  /** A list's Posts tab's type chip: OF's `?postType=` (postTypeOf: photos, videos, …; null: All), its feed's `type`. */
  postType?: string | null;
  /** Collections' Fans: the Creator's active subscribers (GET /subscribers?type=active). */
  subscribers?: OFUserMini[];
  /** The users column (a list's users, the Fans) while they are not here: still loading (null), or the Relay's error text. */
  usersStatus?: string | null;
  /** Collections' Post Labels: the Creator's post labels, and the open one (?label=, else the first). */
  labels?: PostLabel[];
  labelsStatus?: string | null;
  label?: string | null;
  /** My profile: the Creator's wall posts, in the Relay's order. */
  posts?: MirrorPost[];
  /** The wall while `posts` is not here: still loading (null), or the Relay's error text. */
  postsStatus?: string | null;
  /** The wall's pages after the first (OF's infinite scroll: applyPosts). */
  postsMore?: MorePages;
  /** My profile's Media tab and Recent strip: the Creator's photo posts then video posts, as the Relay sends them (merged when shown). */
  profileMedia?: MediaPost[];
  /** The Media grid while `profileMedia` is not here: still loading (null), or the Relay's error text. */
  profileMediaStatus?: string | null;
  /** My profile's counts (the Creator's /users/me), post labels and highlights. */
  profile?: MirrorProfile;
  /** All bookmarks: the Creator's bookmarked posts, in the Relay's order. */
  bookmarks?: MirrorPost[];
  /** A queue page's items, as its route (QUEUE) sends them. */
  queue?: QueueItem[];
  /** The Agency's time zone (IANA): the queue's and Statements' Earnings' days and times are that zone's (default: the browser's). */
  zone?: string;
  /** A notifications tab's items (its route: NOTIFICATIONS), in the Relay's order. */
  notifications?: MirrorNotification[];
  /** A notifications tab while `notifications` is not here: still loading (null), or the Relay's error text. */
  notificationsStatus?: string | null;
  /** The notifications tab bar's counts: per type, and Tags' (the Creator's newTagsCount). */
  notificationCounts?: { counts: NotificationCounts; tags?: number | null };
  /** Streaming's dashboard: the Creator's past live streams, in the Relay's order. */
  pastStreams?: PastStream[];
  /** Statements' Earnings: the Creator's earning transactions, in the Relay's order (the pages read so far), and the next page's state. */
  transactions?: Transaction[];
  transactionsMore?: MorePages;
  /** Statements' Payouts: the Creator's payout requests, in the Relay's order. */
  payouts?: Payout[];
  /** Statements' Referrals: the Creator's referral payouts, in the Relay's order. */
  referrals?: Payout[];
  /** The Statements table's rows while they are not here: still loading (null), or the Relay's error text. */
  statementsStatus?: string | null;
  /** Home: the home feed's posts, in the Relay's order, and their authors by id (the Relay's /users/list). */
  home?: MirrorPost[];
  authors?: Record<string, OFUserMini>;
  /** Home's feed while `home` is not here: still loading (null), or the Relay's error text. */
  homeStatus?: string | null;
  /** Home's feed's pages after the first (OF's infinite scroll: applyHome). */
  homeMore?: MorePages;
  /** Home's story strip: the creators with stories (the Relay's GET /stories), and the live and scheduled streams (GET /streams/feed). */
  stories?: StoryUser[];
  streams?: FeedStream[];
  /** Home's right column: the Creator's promotions (the Relay's `/promotions` items), its subscription price and itself (the bubble's avatar). */
  promotions?: Promotion[];
  subscribePrice?: number | null;
  me?: OFUserMini;
  /** Home's Scheduled events widget: the next 30 days' queue items, and the time they are compared with (default: now). */
  events?: QueueItem[];
  now?: Date;
  /** Rows borrowed from other captures (see TEMPLATES), from another document: adopted when used. */
  templates?: Partial<Record<Template, Element>>;
}

// Every change to the page's own nodes registers its undo (ofMirrorUndo); clones are just removed. Text is tracked even
// when it is the same (restore puts it back over a later change). `own`: a binder's rows on a page whose data
// restore re-runs, e.g. Home's tag dialog over the Home feed.
export const { track, own, setAttr, setClass, setText, restore } = undoList({ attrMode: "single", classUndo: "snapshot", skipEqualText: false });
/** Drop the classes `cls` from `el`. */
export function dropClass(doc: Document, el: Element, ...cls: string[]) {
  setAttr(doc, el, "class", [...el.classList].filter((c) => !cls.includes(c)).join(" "));
}

/** A copy of `tpl` without the markers useOfRow leaves on the page's own nodes. */
export function make(tpl: Element): HTMLElement {
  const c = tpl.cloneNode(true) as HTMLElement;
  for (const el of [c, ...c.querySelectorAll<HTMLElement>("*")]) {
    for (const a of [...el.attributes]) if (a.name.startsWith("data-oi-")) el.removeAttribute(a.name);
  }
  c.dataset.oiData = "";
  return c;
}

/**
 * Hide `examples`; append `clones` to `parents` in turn (default: the first
 * example's parent: trailing built-in rows can sit outside the list's virtual
 * scroller). A virtual scroller's absolutely placed item views become plain
 * flow, and its wrapper loses the examples' fixed height.
 */
export function fill(doc: Document, examples: HTMLElement[], clones: HTMLElement[], parents?: Element[]) {
  for (const e of examples) setAttr(doc, e, "style", `${e.getAttribute("style") ?? ""};display:none`);
  const targets = parents?.length ? parents : [examples[0].parentElement!];
  clones.forEach((c, i) => {
    if (c.classList.contains("vue-recycle-scroller__item-view")) {
      c.style.position = "relative";
      c.style.transform = "none";
    }
    targets[i % targets.length].appendChild(c);
    track(doc, () => c.remove());
  });
  for (const p of targets) if (p.classList.contains("vue-recycle-scroller__item-wrapper")) setAttr(doc, p, "style", null);
}

const unit = (el: Element) => el.closest<HTMLElement>(".vue-recycle-scroller__item-view") ?? (el as HTMLElement);
export const nameOf = (u: OFUserMini | null | undefined) => u?.name?.trim() || u?.username || (u ? String(u.id) : "");
export const handleOf = (u: OFUserMini) => u.username || `u${u.id}`;
/**
 * Where a user's name and avatar go: the Creator's own (`me`, their id) My profile, anyone else's OF profile,
 * https://onlyfans.com/<handle> (by `u<id>` without one; the mirror has no other user's profile, as the chat list's
 * avatar); none for a user with neither id nor handle.
 */
export function userHref(u: { id?: unknown; username?: string | null } | null | undefined, me?: string | null): string | null {
  const id = u?.id == null || u.id === "" ? null : String(u.id);
  if (id == null && !u?.username) return null;
  if (me != null && id === me) return "/of-manager/profile";
  return `https://onlyfans.com/${encodeURIComponent(u?.username || `u${id}`)}`;
}
/** Point the cloned row's user links `links` at `href` (none: they stay as captured): My profile in the frame's top, an OF
 *  profile in a new tab. */
export function linkUser(links: Iterable<Element>, href: string | null) {
  if (!href) return;
  const away = href.startsWith("https://");
  for (const a of links) {
    a.setAttribute("href", href);
    a.setAttribute("target", away ? "_blank" : "_top");
    if (away) a.setAttribute("rel", "noopener noreferrer");
    else a.removeAttribute("rel");
  }
}
const sameId = (a: unknown, b: string | null | undefined) => b != null && String(a) === b;
/** OF message text (HTML) as plain text, parsed inertly. */
export const plain = (html: string | null | undefined) => (html ? (new DOMParser().parseFromString(html, "text/html").body.textContent ?? "").trim() : "");
/**
 * OF's text markup (a bio's `about`, a message's text; parsed inertly) as its plain lines: one per paragraph, a <br>
 * breaking a line; nl2br's "<br />\n" is one break, not two.
 */
export function htmlLines(html: string | null | undefined): string[] {
  if (!html) return [];
  const body = new DOMParser().parseFromString(html.replace(/(<br\s*\/?>)\r?\n/gi, "$1"), "text/html").body;
  for (const br of body.querySelectorAll("br")) br.replaceWith("\n");
  const ps = [...body.querySelectorAll("p")];
  return (ps.length > 1 ? ps.map((p) => p.textContent ?? "").join("\n") : (body.textContent ?? "")).split("\n");
}
/** A source's body once read as an object, else null (loading, or it failed). */
export const objectOf = <T extends object>(v: unknown): T | null => (v && typeof v === "object" ? (v as T) : null);
/** Put `el` in OF's empty v-if slot (an empty comment) after, before or last in `ref`, else there itself. */
export function fillSlot(ref: Element, where: "after" | "before" | "append", el: Node) {
  const slot = where === "after" ? ref.nextSibling : where === "before" ? ref.previousSibling : ref.lastChild;
  if (slot?.nodeType === 8) slot.replaceWith(el);
  else ref[where](el);
}

export const valid = (iso?: string) => {
  const d = iso ? new Date(iso) : null;
  return d && !Number.isNaN(d.getTime()) ? d : null;
};
/** "5:06 am", "Oct 11", "Oct 12, 5:06 am": OF's formats. */
export const clock = clockTime;
export const dayOf = (d: Date) => d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
export const stamp = (d: Date) => `${dayOf(d)}, ${clock(d)}`;

/** Show `img(avatar)` in an avatar link: its <img>, or the letter placeholder swapped for OF's image markup. */
export function setAvatar(el: Element | null, u: OFUserMini, img: (u: string) => string) {
  if (!el) return;
  el.classList.remove("has-story", "has-new-story"); // the example's story ring
  el.querySelector(".g-avatar__icon")?.remove(); // and its online dot
  const ph = el.querySelector<HTMLElement>(".g-avatar__placeholder");
  // OF's text avatar (the same avatar component as a list's member stack): its initials; a login-only name (none) keeps
  // its first letter, OF's profile icon not being in every page's sprite.
  if (ph) ph.textContent = ` ${initials(u) || ([...nameOf(u)][0] ?? "")} `;
  if (!u.avatar) return;
  const pic = el.querySelector("img");
  if (pic) pic.setAttribute("src", img(u.avatar));
  else if (ph) {
    // The placeholder's own ::after would cover a background image.
    const doc = ph.ownerDocument;
    const scope = [...ph.attributes].filter((a) => a.name.startsWith("data-v-"));
    const wrap = doc.createElement("div");
    for (const a of scope) wrap.setAttribute(a.name, a.value);
    wrap.className = "g-avatar__img-wrapper";
    const pic = doc.createElement("img");
    if (scope[0]) pic.setAttribute(scope[0].name, scope[0].value);
    pic.setAttribute("src", img(u.avatar));
    pic.setAttribute("alt", "");
    pic.setAttribute("loading", "lazy");
    wrap.appendChild(pic);
    ph.replaceWith(wrap);
  }
}

const CHAT_MARKS = ["current", "m-muted", "m-muted-by-me", "m-muted-notifications", "m-unread", "m-unread-muted"];
const ROW_MARKS = ["m-current", "router-link-active"];

/**
 * The chat rows: one copy of the template row per chat, its link to the chat carrying the list's view (`listQuery`, see
 * ofMirrorChats), stamped `data-oi-chat="<fan id>"` (its "x", Clear messages, is ofMirrorChats'); its avatar links to the
 * fan's OnlyFans profile in a new tab, as OF's avatar goes to the profile (only while OF says canGoToProfile).
 */
function applyChats(doc: Document, chats: OFChatItem[], open: string | null, img: (u: string) => string, borrowed?: Element, listQuery = "") {
  let rows = [...doc.querySelectorAll<HTMLElement>(".b-chats__item")];
  // A list captured with no chat: the borrowed list (its hidden row) put in, and OF's empty-list layout dropped.
  const dialogues = doc.querySelector(".b-chats__list-dialogues");
  if (!rows.length && borrowed && dialogues) {
    const list = doc.importNode(borrowed, true) as HTMLElement;
    dialogues.prepend(list);
    track(doc, () => list.remove());
    const scroller = doc.querySelector(".b-chats__scroller.m-empty-section");
    if (scroller && chats.length) dropClass(doc, scroller, "m-empty-section");
    rows = [...doc.querySelectorAll<HTMLElement>(".b-chats__item")];
  }
  if (!rows.length) return;
  const tpl = unit(rows.find((r) => r.querySelector(".b-chats__item__last-message__text")) ?? rows[0]);
  const clones = chats.map((c, i) => {
    const el = make(tpl);
    el.style.removeProperty("display"); // the generator's hidden template
    const u = c.withUser;
    const row = el.matches(".b-chats__item") ? el : el.querySelector(".b-chats__item")!;
    const unread = c.unreadMessagesCount ?? (c.hasUnread ? 1 : 0);
    row.classList.remove(...CHAT_MARKS);
    row.classList.toggle("m-unread", unread > 0);
    row.classList.toggle("current", sameId(u.id, open));
    el.querySelector("[data-index]")?.setAttribute("data-index", String(i));
    row.setAttribute("data-oi-chat", String(u.id));
    row.toggleAttribute("data-oi-unread", unread > 0);
    // OF's swipe label (the row's SwipeOut): what a swipe left does to this chat.
    const swipe = el.querySelector(".b-chats__mark-as-read-label");
    if (swipe) swipe.textContent = unread > 0 ? " Mark as Read " : " Mark as Unread ";
    el.querySelector(".b-chats__item__btn-clear")?.setAttribute("data-oi-wired", "");
    // The example's state icons and verified mark (the Relay sends none).
    for (const x of el.querySelectorAll(".b-icon-state-dialog, .b-chats__item__last-message__icons, [data-icon-name='icon-verified']")) x.remove();
    for (const x of el.querySelectorAll(".g-user-name")) {
      x.classList.remove("m-verified");
      x.textContent = nameOf(u);
    }
    for (const x of el.querySelectorAll(".g-user-username")) x.textContent = ` @${handleOf(u)} `;
    el.querySelector(".b-chats__item__link")?.setAttribute("href", `/of-manager/messages/chat?chat=${encodeURIComponent(String(u.id))}${listQuery ? `&${listQuery}` : ""}`);
    const content = el.querySelector(".b-chats__item__last-message__content");
    if (content) {
      const span = (content.firstElementChild?.cloneNode(false) as HTMLElement | undefined) ?? doc.createElement("span");
      span.className = "b-chats__item__last-message__text";
      const m = c.lastMessage;
      span.textContent = plain(m?.text) || (m?.mediaCount ? "Media" : "");
      content.replaceChildren(span);
    }
    const time = el.querySelector(".b-chats__item__time span");
    const at = valid(c.lastMessage?.createdAt);
    if (time) {
      time.textContent = at ? ` ${at.toDateString() === new Date().toDateString() ? clock(at) : dayOf(at)} ` : "";
      if (at) time.setAttribute("title", stamp(at));
      else time.removeAttribute("title");
    }
    if (!unread) el.querySelector(".b-chats__item__uread-count")?.remove(); // the unread dot: only unread rows have it
    const avatar = el.querySelector<HTMLAnchorElement>(".b-available-users__round-img .g-avatar");
    setAvatar(avatar, u, img);
    if (avatar) {
      const profile = c.canGoToProfile === true && u.username ? `https://onlyfans.com/${encodeURIComponent(u.username)}` : null;
      avatar.classList.toggle("g-pointer-cursor", !!profile);
      if (profile) {
        avatar.setAttribute("href", profile);
        avatar.setAttribute("target", "_blank");
        avatar.setAttribute("rel", "noopener noreferrer");
      }
    }
    return el;
  });
  // OF's "Nothing found" (the generator's) only for an empty list.
  const empty = chats.length ? [...doc.querySelectorAll<HTMLElement>(".b-chats__scroller [data-oi-empty]")] : [];
  fill(doc, [...rows.map(unit), ...empty], clones);
}

/** OF's infinite loader under the chat list (its spinner prompt): shown while the next page is read. */
function applyChatsMore(doc: Document, more: MorePages) {
  const spinner = [...doc.querySelectorAll<HTMLElement>(".b-chats__scroller .infinite-status-prompt")].find((p) => p.querySelector(".b-posts_preloader"));
  if (spinner && more.loading) setAttr(doc, spinner, "style", "");
}

/**
 * The chat list before its chats are here: OF's "Nothing found" reads "Loading chats…" while the Relay answers (`error`
 * null), or the red "Could not load chats: <the Relay's text>" after it failed (as the notifications tabs).
 */
function applyChatsStatus(doc: Document, error: string | null) {
  const text = doc.querySelector<HTMLElement>(".b-chats__scroller [data-oi-empty] .empty-message > span");
  if (!text) return;
  const [was, style] = [text.textContent, text.getAttribute("style")];
  track(doc, () => {
    text.textContent = was;
    if (style === null) text.removeAttribute("style");
    else text.setAttribute("style", style);
  });
  text.textContent = error === null ? "Loading chats…" : `Could not load chats: ${error}`;
  if (error !== null) text.style.color = "#ff4545";
}

/**
 * A message's price line, in OF's payment-state words (its time bar, shown while `price > 0`): "$9 not paid yet" until
 * the fan opened or paid it (`isOpened || isPaid`, Messages Pro's rule), then "$9 paid"; a free message and a tip (OF
 * sends a tip with price 0, its amount in tipAmount) none.
 */
export function paymentState(m: Pick<OFMessage, "price" | "isTip" | "isOpened" | "isPaid">): string {
  if (m.isTip || !(typeof m.price === "number" && m.price > 0)) return "";
  return `${dollars(m.price)} ${m.isOpened || m.isPaid ? "paid" : "not paid yet"}`;
}

/** OF's tip bubble (its ItemTips, scoped data-v-364cdc78): the funds icon, the tip line, a heart, then the fan's note. */
export const isTipMessage = (m: ThreadMessage) => !!(m.isTip || m.isFundRaisingTip) && (m.tipAmount ?? 0) > 0;

/**
 * OF's purchase card on a message the Creator cannot open (isMessagePurchaseVisible: not the Creator's, not a tip, with
 * media or locked text, purchasable or "unsubscribed"): another creator's PPV in the Creator's chat with them.
 */
export const isPurchaseCard = (m: ThreadMessage, fromMe: boolean) =>
  !fromMe && !m.isTip && ((m.media?.length ?? 0) > 0 || !!m.lockedText) && (m.canPurchase === true || m.canPurchaseReason === "unsubscribed");

function tipBubble(doc: Document, m: ThreadMessage): HTMLElement {
  const scope = "data-v-364cdc78";
  const wrap = doc.createElement("div");
  wrap.className = "b-chat__message__text-wrapper";
  const box = doc.createElement("div");
  box.className = "b-chat__message__text m-message-content-bg m-possible-markdown m-break-word-default";
  box.setAttribute("at-attr", "message_text");
  box.setAttribute(scope, "");
  const line = doc.createElement("span");
  line.className = "b-chat__message__tip-text";
  line.setAttribute(scope, "");
  const words = doc.createElement("span");
  words.setAttribute("at-attr", "msg_tip");
  words.setAttribute(scope, "");
  words.textContent = plain(m.text) || `I sent you a ${dollars(m.tipAmount)} tip`;
  line.append(icon(doc, "icon-funds"), words, icon(doc, "icon-likes"));
  box.appendChild(line);
  const said = plain(m.tipText);
  if (said) {
    const note = doc.createElement("span");
    note.className = "b-chat__message__text-content";
    note.setAttribute(scope, "");
    note.textContent = said;
    box.appendChild(note);
  }
  wrap.appendChild(box);
  return wrap;
}

/**
 * The captured purchase card (`.m-purchase-chat`) for `m`: its media counts or length, the price with OF's lock, and
 * "Unlock for $X", disabled with the tooltip (unlocking is a payment from the Creator's balance; Inflowwww makes none).
 */
function purchaseCard(tpl: Element, m: ThreadMessage): HTMLElement {
  const card = make(tpl);
  delete card.dataset.oiData;
  const locked = (m.media ?? []).filter((x) => x.canView === false);
  fillIcons(card.querySelector(".b-purchase__list"), attachmentIcons(locked.length ? locked : (m.media ?? []), !!m.lockedText));
  const price = card.querySelector(".m-price-lock .b-purchase__list-item__count");
  if (price) price.textContent = ` ${dollars(m.price)} `;
  setIconName(card.querySelector(".m-price-lock svg"), "icon-locked");
  const btn = card.querySelector<HTMLButtonElement>("button.post-subscribe-btn");
  if (btn) {
    btn.textContent = ` Unlock for ${dollars(m.price)} `;
    btn.disabled = true;
    btn.setAttribute("title", NOT_YET);
  }
  return card;
}

/**
 * A chat page's links to the open chat's other pages: its header's Gallery and pin (lit, OF's `icon-pin-on`, "Open
 * pinned messages", while the chat has pinned messages), the gallery's and pinned page's Back, and their "with <name>".
 */
function applyChatLinks(doc: Document, page: string, chat: string, data: MirrorData, listQuery = "") {
  const q = `?chat=${encodeURIComponent(chat)}${listQuery ? `&${listQuery}` : ""}`;
  if (page !== "messages/chat") {
    keepQuery(doc, "messages/chat", q);
    track(doc, () => keepQuery(doc, "messages/chat", ""));
  }
  for (const a of doc.querySelectorAll<HTMLAnchorElement>("a[data-oi-chat-link]")) {
    setAttr(doc, a, "href", chatHref(a.dataset.oiChatLink === "pinned" ? PINNED_PAGE : GALLERY_PAGE, chat, listQuery));
    if (a.dataset.oiChatLink !== "pinned" || data.pinnedCount === undefined) continue;
    const on = data.pinnedCount > 0;
    const was = a.className;
    a.classList.toggle("m-active", on);
    a.classList.toggle("m-gray", !on);
    track(doc, () => (a.className = was));
    const svg = a.querySelector("svg");
    setIconName(svg, on ? "icon-pin-on" : "icon-pin");
    track(doc, () => setIconName(svg, "icon-pin"));
    setAttr(doc, a, "aria-label", on ? "Open pinned messages" : "No pinned messages");
    setAttr(doc, a, "title", on ? "Open pinned messages" : "No pinned messages");
  }
  applyWith(doc, data.chatFan ?? null);
}

/**
 * One media item in OF's chat bubble markup: a copy of the capture's single-photo media block (no
 * slideshow), else a bare one with OF's media classes. Its <img>s are left for chatMedia to fill.
 */
export function chatMediaTemplate(doc: Document, wrapper: Element | null): HTMLElement {
  const single = [...(wrapper?.querySelectorAll(".b-chat__message__media-wrapper") ?? [])].find(
    (w) => !w.querySelector(".swiper") && w.querySelectorAll(".b-post__media__item-inner").length === 1 && w.querySelector("img.b-post__media__img"),
  );
  if (single) {
    const tpl = make(single);
    delete tpl.dataset.oiData;
    tpl.querySelector(".b-post__media__item-inner")?.classList.remove("g-pointer-cursor");
    // The example's PPV lock, and OF's loading cover (its script drops it once the picture loads).
    for (const x of tpl.querySelectorAll(".m-purchase-chat, .post_media__loading")) x.remove();
    return tpl;
  }
  const tpl = doc.createElement("div");
  tpl.className = "b-chat__message__media-wrapper";
  const box = doc.createElement("div");
  box.className = "b-chat__message__media m-message-content-bg";
  const pic = doc.createElement("img");
  pic.className = "b-post__media__img img-responsive m-object-contain";
  pic.setAttribute("alt", "");
  pic.setAttribute("loading", "lazy");
  box.appendChild(pic);
  tpl.appendChild(box);
  return tpl;
}

/** `media`'s still (`src`) in a copy of `tpl`, sized to its aspect when known. */
export function chatMedia(tpl: HTMLElement, media: OFMedia, src: string): HTMLElement {
  const el = tpl.cloneNode(true) as HTMLElement;
  const ratio = media.width && media.height ? Math.min(1.5, Math.max(0.5, media.height / media.width)) : 1;
  const box = el.querySelector<HTMLElement>(".b-chat__message__media");
  if (box) box.style.width = "min(100%, 280px)";
  const area = el.querySelector<HTMLElement>(".b-post-media-size-area");
  if (area) area.style.paddingTop = `${(ratio * 100).toFixed(3)}%`;
  for (const pic of el.querySelectorAll("img")) {
    pic.setAttribute("src", src);
    pic.removeAttribute("width");
    pic.removeAttribute("height");
  }
  return el;
}

/** OF's chat message classes (82027): with media, a photo among it, text (or nothing else to show), the Creator's own, a tip. */
export const bubbleClass = (b: { media: boolean; photo: boolean; text: boolean; fromMe: boolean; tip?: boolean }) =>
  `b-chat__message${b.media ? " m-has-media" : ""}${b.photo ? " m-photo" : ""}${b.text ? " m-text" : ""}${b.fromMe ? " m-from-me" : ""}${b.tip ? " m-tip" : ""}`;

function applyThread(doc: Document, page: string, chat: string, thread: NonNullable<MirrorData["thread"]>, img: (u: string) => string, listQuery = "") {
  const { fan, messages } = thread;
  if (fan) {
    const name = nameOf(fan);
    for (const el of doc.querySelectorAll(".b-chat__header__title span.g-user-name")) setText(doc, el, name);
    const title = doc.querySelector("title");
    if (title) setText(doc, title, (title.textContent ?? "").replace(/[^:›]+$/, ` ${name}`));
  }
  keepQuery(doc, basePage(page), `?chat=${encodeURIComponent(chat)}${listQuery ? `&${listQuery}` : ""}`);
  track(doc, () => keepQuery(doc, basePage(page), ""));

  const wrapper = doc.querySelector(".b-chat__messages-wrapper");
  const groups = wrapper ? [...wrapper.querySelectorAll<HTMLElement>(":scope > .b-chat__item-message")] : [];
  const msgTpl = wrapper?.querySelector(".b-chat__message.m-media-less-text") ?? wrapper?.querySelector(".b-chat__message");
  if (!groups.length || !msgTpl) return;
  const groupTpl = make(groups[0]);
  groupTpl.style.removeProperty("display"); // the generator's hidden template
  for (const m of groupTpl.querySelectorAll(".b-chat__message")) m.remove();
  const mediaTpl = chatMediaTemplate(doc, wrapper!);
  const stateTpl = wrapper!.querySelector(".b-chat__message__payment-state");
  const purchaseTpl = wrapper!.querySelector(".m-purchase-chat");
  const menuTagged = !!msgTpl.querySelector("[data-oi-msg-menu]");

  const sorted = [...messages].sort((a, b) => (valid(a.createdAt)?.getTime() ?? 0) - (valid(b.createdAt)?.getTime() ?? 0) || Number(a.id) - Number(b.id));
  const clones: HTMLElement[] = [];
  let day = "";
  for (const m of sorted) {
    const at = valid(m.createdAt);
    const key = at ? at.toDateString() : "";
    if (!clones.length || key !== day) {
      day = key;
      const g = groupTpl.cloneNode(true) as HTMLElement;
      const label = g.querySelector(".b-chat__messages__time span");
      if (label) {
        label.textContent = at ? ` ${dayOf(at)} ` : "";
        if (at) label.setAttribute("title", stamp(at));
      }
      clones.push(g);
    }
    const fromMe = !sameId(m.fromUser?.id, chat);
    const tm = m as ThreadMessage;
    const el = make(msgTpl);
    delete el.dataset.oiData;
    el.dataset.oiMsg = String(m.id);
    if (menuTagged) el.querySelector(".m-btn-vertical-dots")?.setAttribute("data-oi-msg-menu", ""); // make() drops the generator's tag
    const tip = isTipMessage(tm);
    const purchase = !!purchaseTpl && isPurchaseCard(tm, fromMe);
    const notPaid = !m.isTip && (m.price ?? 0) > 0 && !m.isOpened && !m.isPaid; // OF's isNotPaidYet (!isFree && !isOpened)
    // OF hides a PPV's locked text until it is opened (another creator's, here); a tip's text is its tip line.
    const text = tip || (purchase && m.lockedText && notPaid) ? "" : plain(m.text);
    const stills = (m.media ?? []).filter((x) => x.canView !== false).map((x) => ({ x, url: stillUrl(x) })).filter((s) => s.url);
    el.className = bubbleClass({ media: !!stills.length || purchase, photo: !!stills.length, text: !!text || tip || (!stills.length && !purchase), fromMe, tip });
    for (const x of el.querySelectorAll(".b-chat__message__media-wrapper, .m-purchase-chat, .b-chat__message__payment-state")) x.remove();
    const body = el.querySelector(".b-chat__message__body");
    if (body && (stills.length || purchase)) {
      const shown = stills.map((s) => chatMedia(mediaTpl, s.x, img(s.url!)));
      if (purchase) {
        // OF's ItemMedia: the free previews, then the purchase card, in one media wrapper.
        const box = shown.at(-1) ?? doc.createElement("div");
        box.classList.add("b-chat__message__media-wrapper");
        box.appendChild(purchaseCard(purchaseTpl!, tm));
        if (!shown.length) shown.push(box);
      }
      body.prepend(...shown);
      if (!text) el.querySelector(".b-chat__message__text-wrapper")?.remove();
    }
    if (tip) {
      el.querySelector(".b-chat__message__text-wrapper")?.remove();
      body?.prepend(tipBubble(doc, tm));
    }
    const avatar = el.querySelector(".b-chat__message__content > .g-avatar");
    if (fromMe) avatar?.remove();
    else if (fan) setAvatar(avatar, fan, img);
    const holder = el.querySelector(".b-chat__message__text-holder");
    if (holder) {
      const p = doc.createElement("p");
      p.textContent = text || (!stills.length && !purchase && (m.mediaCount ?? m.media?.length ?? 0) > 0 ? "Media" : "");
      holder.replaceChildren(p);
    }
    const time = el.querySelector(".b-chat__message__time > span");
    if (time) time.textContent = at ? ` ${clock(at)} ` : "";
    const state = paymentState(m);
    if (state) {
      const span = (stateTpl?.cloneNode(false) as HTMLElement | undefined) ?? doc.createElement("span");
      span.className = "b-chat__message__payment-state";
      span.textContent = ` ${state} `;
      el.querySelector(".b-chat__message__time")?.appendChild(span);
    }
    // OF's classes (82027): m-purchase on a purchase card (never the Creator's own), m-not-paid-yet on any PPV not opened.
    if (purchase) el.classList.add("m-purchase");
    if (notPaid) el.classList.add("m-not-paid-yet");
    clones[clones.length - 1].appendChild(el);
  }
  fill(doc, groups, clones);
  // The pinned page with none: OF's empty placeholder ("pinned_messages_will_be_shown_here").
  if (!clones.length && wrapper!.classList.contains("m-pinned")) {
    const empty = doc.createElement("div");
    empty.className = "text-center m-mall-auto g-sides-gaps";
    empty.dataset.oiEmpty = "";
    empty.style.cssText = "padding:32px 16px;color:#8a96a3";
    empty.textContent = "Pinned messages will be shown here";
    wrapper!.before(empty);
    track(doc, () => empty.remove());
  }
  // The scroll position (the newest message on open, kept on a redraw) is useOfData's: keepThreadScroll.
}

/** The thread's scroller. */
export const THREAD_BOX = ".b-chat__messages";
/** How near the thread's top (px) its older messages are asked for, and how near its end counts as "at the newest". */
const OLDER_PX = 300;
const AT_END_PX = 40;

/** Where the thread was scrolled before a redraw (threadScroll), for keepThreadScroll. */
export interface ThreadScroll {
  /** The chat the box showed. */
  chat: string;
  /** Its oldest drawn message's id: another one after the redraw means older messages were put in above. */
  first: string | null;
  top: number;
  /** Its distance from the end (scrollHeight - scrollTop). */
  fromEnd: number;
}

const firstShown = (box: Element) => box.querySelector<HTMLElement>(".b-chat__item-message[data-oi-data] [data-oi-msg]")?.dataset.oiMsg ?? null;

/**
 * Where `chat`'s thread is scrolled before a redraw, or null when it shows no real message yet (a first draw), sits at
 * the newest message, or showed another chat (a switch opens the new one at its newest, never at the last one's
 * offset). Read before applyData's restore empties it.
 */
export function threadScroll(doc: Document, chat: string | null): ThreadScroll | null {
  const box = doc.querySelector<HTMLElement>(THREAD_BOX);
  if (!chat || !box?.querySelector(".b-chat__item-message[data-oi-data]") || box.dataset.oiChat !== chat) return null;
  const fromEnd = box.scrollHeight - box.scrollTop;
  return fromEnd - box.clientHeight <= AT_END_PX ? null : { chat, first: firstShown(box), top: box.scrollTop, fromEnd };
}

/**
 * After a redraw of `chat`: at the newest message as OF opens a chat (`was` null: a first draw, or it was at the end, so
 * a new message is followed); older messages put in above keep the same distance from the end (no jump); any other
 * redraw (a poll, a message arriving below while scrolled up) keeps the same scrollTop, so nothing in view moves.
 */
export function keepThreadScroll(doc: Document, chat: string, was: ThreadScroll | null) {
  const box = doc.querySelector<HTMLElement>(THREAD_BOX);
  if (!box) return;
  box.dataset.oiChat = chat;
  if (!was || was.chat !== chat) box.scrollTop = box.scrollHeight;
  else if (firstShown(box) !== was.first) box.scrollTop = box.scrollHeight - was.fromEnd;
  else box.scrollTop = was.top;
}

const VAULT_COUNTS: [keyof VaultList, string][] = [
  ["photosCount", "icon-image"],
  ["videosCount", "icon-video"],
  ["gifsCount", "icon-gif"],
  ["audiosCount", "icon-voice"],
];

/** Point the OF icon in `el` (its svg and <use>s) at `icon`. */
export function setIcon(el: Element, icon: string) {
  el.querySelector("svg")?.setAttribute("data-icon-name", icon);
  for (const use of el.querySelectorAll("use")) {
    use.setAttribute("href", `#${icon}`);
    use.setAttribute("xlink:href", `#${icon}`);
  }
}

/** Mark `a` (a list row's link) the open row, as OF does. */
function markOpen(a: Element | null) {
  if (!a) return;
  a.classList.add(...ROW_MARKS);
  a.setAttribute("aria-current", "page");
}

/** A folder row's counts line: one OF count per kind it has (photos, videos, GIFs, audio), else "empty". */
function setCounts(thumbs: Element, l: Partial<VaultList>) {
  const itemTpl = thumbs.querySelector(".b-content-inside-thumbs__item");
  if (!itemTpl) return;
  const items = VAULT_COUNTS.filter(([k]) => Number(l[k] ?? 0) > 0).map(([k, icon]) => {
    const it = itemTpl.cloneNode(true) as HTMLElement;
    it.style.removeProperty("display"); // the generator's hidden template
    setIcon(it, icon);
    while (it.lastChild?.nodeType === 3) it.lastChild.remove();
    it.append(` ${l[k]} `);
    return it;
  });
  if (!items.length) {
    const it = itemTpl.cloneNode(false) as HTMLElement;
    it.style.removeProperty("display");
    it.textContent = "empty";
    items.push(it);
  }
  thumbs.replaceChildren(...items);
}

/**
 * A folder row's covers (`set`, OF's .b-media-set): one copy of its hidden, pictureless cover per picture in `medias`
 * (OF's newest three, through `img`), the set shown; none: the set stays hidden. Returns how many.
 */
function setCovers(set: HTMLElement, medias: VaultList["medias"], img: (u: string) => string): number {
  const tpl = set.querySelector(".b-media-set__item");
  if (!tpl) return 0;
  const covers = (medias ?? []).filter((m) => m?.url).slice(0, 3).map((m) => {
    const it = tpl.cloneNode(true) as HTMLElement;
    it.querySelector("img")?.setAttribute("src", img(m.url!));
    return it;
  });
  if (!covers.length) return 0;
  set.replaceChildren(...covers);
  set.style.removeProperty("display");
  return covers.length;
}

/** The vault's "All media" row (the one linking to `base`, the page's own): the real counts and covers. */
function applyVaultAll(doc: Document, all: Partial<VaultList>, base: string, img: (u: string) => string, search?: string | null) {
  const row = [...doc.querySelectorAll<HTMLElement>(".b-rows-lists__item")].find((r) => r.querySelector(`a[href='${base}']`));
  const thumbs = row?.querySelector(".b-content-inside-thumbs");
  if (!row || !thumbs) return;
  // OF's showAllMedia: during a folder search the row shows only while its name starts with the query (both lowercased
  // and stripped of accents).
  const fold = (t: string) => t.trim().toLowerCase().normalize("NFD").replace(/\p{M}/gu, "");
  if (search && !fold(row.querySelector(".b-rows-lists__item__name")?.textContent ?? "All media").startsWith(fold(search))) {
    const display = row.style.display;
    track(doc, () => void (row.style.display = display));
    row.style.display = "none";
  }
  const set = row.querySelector<HTMLElement>(".b-media-set");
  if (set) {
    const [kids, style] = [[...set.childNodes], set.getAttribute("style")];
    track(doc, () => {
      set.replaceChildren(...kids);
      if (style === null) set.removeAttribute("style");
      else set.setAttribute("style", style);
    });
    // No covers: no picture shows, not even a captured example's (a composer's vault dialog keeps its row's).
    if (!setCovers(set, all.medias, img)) set.style.display = "none";
  }
  const was = [...thumbs.childNodes];
  track(doc, () => thumbs.replaceChildren(...was));
  setCounts(thumbs, all);
}

/**
 * The folder column's title (the Vault page's, a composer's vault dialog's: the column holding the "All media" row that
 * links to `base`) is the folders' sort, as OF's (the `sort` GET /vault/lists answers), not the capture's "custom".
 */
function applyListSort(doc: Document, sort: string, base: string) {
  const path = base.split("?")[0]; // a chat's dialog: its All media row's ?chat= or not
  const all = doc.querySelector(`.b-rows-lists__item a[href='${path}'], .b-rows-lists__item a[href^='${path}?']`);
  const title = all?.closest(".l-sidebar-column")?.querySelector(".b-content-filter__title");
  if (title) setText(doc, title, LIST_SORTS[sort] ?? sort);
}

/** The vault's folder rows, each linking to `base` with its ?list= (the Vault page, or a composer's vault dialog). */
function applyVaultLists(doc: Document, lists: VaultList[], open: string | null, base: string, img: (u: string) => string) {
  const rows = [...doc.querySelectorAll<HTMLElement>(".b-rows-lists__item")].filter((r) => r.querySelector("a[href^='/of-manager/vault/list']"));
  if (!rows.length) return;
  const tpl = rows.find((r) => r.querySelector(".b-content-inside-thumbs__icon")) ?? rows[0];
  const isOpen = lists.some((l) => sameId(l.id, open));
  const clones = lists.map((l) => {
    const el = make(tpl);
    el.style.removeProperty("display"); // the generator's hidden template
    const a = el.querySelector("a")!;
    a.setAttribute("href", `${base}${base.includes("?") ? "&" : "?"}list=${encodeURIComponent(String(l.id))}`);
    a.classList.remove(...ROW_MARKS, "m-current");
    a.removeAttribute("aria-current");
    if (sameId(l.id, open)) markOpen(a);
    el.querySelector(".b-rows-lists__item__name")!.textContent = l.name;
    // OF draws no set for a folder without media.
    const set = el.querySelector<HTMLElement>(".b-media-set");
    if (set && !setCovers(set, l.medias, img)) set.remove();
    const thumbs = el.querySelector(".b-content-inside-thumbs");
    if (thumbs) setCounts(thumbs, l);
    return el;
  });
  fill(doc, rows, clones);
  if (isOpen) {
    // "All media" (and any other row still shown) is no longer the open one.
    for (const a of doc.querySelectorAll(".b-rows-lists__item:not([data-oi-data]) a.b-rows-lists__item__text")) {
      dropClass(doc, a, ...ROW_MARKS);
      setAttr(doc, a, "aria-current", null);
    }
  }
}

/** "0:56", "1:02:03": OF's video duration label. */
export const duration = (sec: number) => {
  const s = Math.round(sec);
  const mmss = `${Math.floor((s % 3600) / 60)}:${String(s % 60).padStart(2, "0")}`;
  return s >= 3600 ? `${Math.floor(s / 3600)}:${mmss.padStart(5, "0")}` : mmss;
};

/** A vault tile's picture: the relay's stored square, else OF's thumb (through `img`). */
const tileThumb = (m: VaultMedia, img: (u: string) => string) => {
  const u = m.files?.thumb?.url || m.files?.squarePreview?.url || m.files?.preview?.url;
  return m._thumb || (u ? img(u) : "");
};

/** Flip OF's `selected` mark on a vault tile and its checkbox (set it to `force` when given); returns the new state. */
export function toggleTile(tile: Element, force?: boolean): boolean {
  const on = tile.classList.toggle("selected", force);
  tile.querySelector(".checkbox-item")?.classList.toggle("selected", on);
  return on;
}

/** The page's media grid (vault, My profile's Media tab): its example rows and tiles. */
export function photoGrid(doc: Document) {
  const grid = doc.querySelector(".b-photos .vue-recycle-scroller__item-wrapper");
  return {
    views: grid ? [...grid.querySelectorAll<HTMLElement>(":scope > .vue-recycle-scroller__item-view")] : [],
    tiles: grid ? [...grid.querySelectorAll<HTMLElement>(".b-photos__item")] : [],
  };
}

/** `tiles` three to a row, in copies of the grid's first row, in place of its example `views`. */
export function fillGrid(doc: Document, views: HTMLElement[], tiles: HTMLElement[]) {
  const rowTpl = make(views[0]);
  rowTpl.style.removeProperty("display"); // the generator's hidden template (the Vault page's)
  rowTpl.querySelector(".dynamic-scroller-item")?.replaceChildren();
  const rows: HTMLElement[] = [];
  tiles.forEach((t, i) => {
    if (i % 3 === 0) rows.push(rowTpl.cloneNode(true) as HTMLElement);
    const holder = rows[rows.length - 1];
    (holder.querySelector(".dynamic-scroller-item") ?? holder).appendChild(t);
  });
  fill(doc, views, rows);
}

/** The kinds whose tile carries OF's duration badge, and the badge's icon (OF's sprite; a video's as captured). */
const BADGE: Record<string, string> = { video: "icon-video", gif: "icon-gif", audio: "icon-voice" };

/**
 * The vault's right-hand grid (also New post's vault dialog): one OF tile per media (a video's with its
 * duration and play button; a GIF's and an audio's with the duration badge under their own icon; a media with no picture,
 * as an audio's, keeps the grey placeholder), three to a row, each stamped `data-oi-media="<vault id>"` and `data-oi-text` (what the
 * dialog's search matches: its date label, plus the AI description and tags when the Relay sends them), `data-oi-type` and
 * `data-oi-full` (the file the Vault page's viewer shows). With `picked` (a
 * picker: New post's dialog, whose clicks ofMirrorPost handles) every tile is wired and the picked ones selected.
 */
function applyVaultMedia(doc: Document, media: NonNullable<MirrorData["vaultMedia"]>, img: (u: string) => string, picked?: (number | string)[]) {
  const { views, tiles } = photoGrid(doc);
  const photoTpl = tiles.find((t) => !t.querySelector(".m-video-duration, .b-photos__item__play-btn"));
  if (!views.length || !photoTpl) return;
  const videoTpl = tiles.find((t) => t.querySelector(".m-video-duration"));
  const els = media.map((m) => {
    const badge = videoTpl && Object.hasOwn(BADGE, m.type) ? BADGE[m.type] : null;
    const el = make(badge ? videoTpl! : photoTpl);
    delete el.dataset.oiData;
    el.dataset.oiMedia = String(m.id); // the vault id a pick sends
    if (picked) {
      el.setAttribute("data-oi-wired", "");
      if (picked.some((p) => sameId(m.id, String(p)))) toggleTile(el, true);
    }
    el.querySelector(".b-media-purchased-icon")?.remove(); // the example's purchase state
    const at = valid(m.createdAt);
    el.dataset.oiText = [at && dayOf(at), m._ai?.description, ...(m._ai?.tags ?? [])].filter(Boolean).join(" ");
    const stampEl = el.querySelector(".b-element-label.m-timestamp:not(.m-video-duration)");
    if (stampEl && at) {
      stampEl.textContent = ` ${dayOf(at)} `;
      stampEl.setAttribute("title", stamp(at));
    } else stampEl?.remove();
    const label = el.querySelector(".m-video-duration");
    if (label && badge) setIcon(label, badge);
    const dur = label?.querySelector("span");
    if (dur) {
      if (m.duration) dur.textContent = duration(m.duration);
      else dur.remove();
    }
    if (m.type !== "video") el.querySelector(".b-photos__item__play-btn")?.remove();
    const thumb = tileThumb(m, img);
    if (thumb) el.querySelector(".b-photos__item__img")?.setAttribute("src", thumb);
    // What the Vault page's viewer shows (through `img`): a video's or GIF's 720p (else its source file), else the full file.
    const full = (m.type === "video" || m.type === "gif" ? m.videoSources?.["720"] : null) || m.files?.full?.url;
    if (full) el.dataset.oiFull = img(full);
    el.dataset.oiType = m.type;
    return el;
  });
  fillGrid(doc, views, els);
  // The Vault page's "Nothing found" (the generator's) only for no media.
  if (els.length) for (const e of doc.querySelectorAll(".b-photos [data-oi-empty]")) setAttr(doc, e, "style", "display:none");
}

/**
 * The Vault page's grid before its media are here: OF's "Nothing found" reads "Loading media…" while the Relay answers
 * (`error` null), or the red "Could not load media: <the Relay's text>" after it failed (as the chat list).
 */
function applyVaultStatus(doc: Document, error: string | null) {
  const text = doc.querySelector<HTMLElement>(".b-photos [data-oi-empty] .empty-message > span");
  if (!text) return;
  const [was, style] = [text.textContent, text.getAttribute("style")];
  track(doc, () => {
    text.textContent = was;
    if (style === null) text.removeAttribute("style");
    else text.setAttribute("style", style);
  });
  text.textContent = error === null ? "Loading media…" : `Could not load media: ${error}`;
  if (error !== null) text.style.color = "#ff4545";
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
const LISTS_COLUMN = ".b-user-lists__list";
const USERS_COLUMN = ".l-main-content.m-r-side";
const LABELS_COLUMN = ".b-post-labels__list";

/** Hide the generator's "Nothing found" under `scope` once it has rows. */
function hideEmpty(doc: Document, scope: string) {
  for (const e of doc.querySelectorAll<HTMLElement>(`${scope} [data-oi-empty]`)) setAttr(doc, e, "style", `${e.getAttribute("style") ?? ""};display:none`);
}

/** A column's "Nothing found" before its rows are here: "Loading…" (`error` null), or the red "Could not load: <the Relay's text>". */
function applyColumnStatus(doc: Document, scope: string, error: string | null) {
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

function applyUserLists(doc: Document, lists: UserList[], open: string | null, borrowed?: Element, img: (u: string) => string = (u) => u) {
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
function applyListUsers(doc: Document, page: string, list: string | null, people: OFUserMini[], listName: string | null, img: (u: string) => string) {
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
function applyListTabs(doc: Document, list: string, type: string | null) {
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
function applyLabels(doc: Document, labels: PostLabel[], open: string | null) {
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

/** Show `data` on `page` in `doc` (the examples again for parts it lacks; idempotent). */
export function applyData(doc: Document, page: string, data: MirrorData, img: (u: string) => string = (u) => u): void {
  restore(doc);
  const parts = partsOf(page);
  // A composer's vault dialog keeps its folder picks on its own page (a chat's: with its ?chat=).
  const vaultBase =
    page === VAULT_DIALOG || page === HOME_VAULT || page === MASS_VAULT
      ? `/of-manager/${page}`
      : page === CHAT_VAULT
        ? `/of-manager/${page}${data.chat ? `?chat=${encodeURIComponent(data.chat)}` : ""}`
        : "/of-manager/vault";
  if (parts.includes("chats") && data.chatsStatus !== undefined) applyChatsStatus(doc, data.chatsStatus);
  if (parts.includes("chats") && data.chats) applyChats(doc, data.chats, data.chat ?? null, img, data.templates?.chatList, data.listQuery);
  if (parts.includes("chats") && data.chatsMore) applyChatsMore(doc, data.chatsMore);
  if (parts.includes("thread") && data.thread && data.chat) applyThread(doc, page, data.chat, data.thread, img, data.listQuery);
  if ((parts.includes("thread") || parts.includes("gallery")) && data.chat) applyChatLinks(doc, page, data.chat, data, data.listQuery);
  if (parts.includes("gallery") && data.gallery && data.chat) applyGallery({ doc, img, fan: data.chatFan ?? null, me: data.me ?? null, listQuery: data.listQuery ?? "" }, data.chat, data.gallery);
  if (parts.includes("vaultLists") && data.vaultLists) applyVaultLists(doc, data.vaultLists, data.list ?? null, vaultBase, img);
  if (parts.includes("vaultLists") && data.vaultAll) applyVaultAll(doc, data.vaultAll, vaultBase, img, data.vaultSearch);
  if (parts.includes("vaultLists") && data.vaultSort) applyListSort(doc, data.vaultSort, vaultBase);
  if (parts.includes("vaultMedia") && data.vaultStatus !== undefined) applyVaultStatus(doc, data.vaultStatus);
  if (parts.includes("vaultMedia") && data.vaultMedia) {
    applyVaultMedia(doc, data.vaultMedia, img, data.picked);
    const name = data.vaultLists?.find((l) => sameId(l.id, data.list))?.name;
    const heading = doc.querySelector(".l-main-content.m-r-side .g-page-title > span");
    if (name && heading) setText(doc, heading, name);
  }
  if (parts.includes("userLists") && data.userListsStatus !== undefined) applyColumnStatus(doc, LISTS_COLUMN, data.userListsStatus);
  if (parts.includes("userLists") && data.userLists) applyUserLists(doc, data.userLists, data.list ?? null, data.templates?.listRow, img);
  if ((parts.includes("listUsers") || parts.includes("subscribers")) && data.usersStatus !== undefined) applyColumnStatus(doc, USERS_COLUMN, data.usersStatus);
  if (parts.includes("listUsers") && data.listUsers && data.list) {
    const name = data.userLists?.find((l) => sameId(l.id, data.list))?.name ?? null;
    applyListUsers(doc, page, data.list, data.listUsers, name, img);
  }
  if (parts.includes("subscribers") && data.subscribers) applyListUsers(doc, page, null, data.subscribers, null, img);
  if ((parts.includes("listUsers") || parts.includes("listPosts")) && data.list) applyListTabs(doc, data.list, data.postType ?? null);
  if (parts.includes("listPosts") && data.listPostsStatus !== undefined) applyFeedStatus(doc, data.listPostsStatus, COLUMN_FEED);
  if (parts.includes("listPosts") && data.listPosts && data.templates?.post)
    applyColumnPosts(doc, { posts: data.listPosts, tpl: data.templates.post, me: data.me && String(data.me.id), authors: data.authors, more: data.listPostsMore }, img);
  if (parts.includes("labels") && data.labelsStatus !== undefined) applyColumnStatus(doc, LABELS_COLUMN, data.labelsStatus);
  if (parts.includes("labels") && data.labels) applyLabels(doc, data.labels, data.label ?? null);
  // My profile: the wall (profile/index) or the Media grid (profile/media) has the page's "No posts yet".
  const grid = page === "profile/media";
  if (parts.includes("posts") && !grid && data.postsStatus !== undefined) applyProfileStatus(doc, data.postsStatus);
  if (parts.includes("posts") && !grid && data.posts) {
    applyPosts(doc, data.posts, img, data.me?.username, data.postsMore);
    if (data.posts.length) hideEmpty(doc, ".user_posts");
  }
  if (parts.includes("profileMedia") && grid && data.profileMediaStatus !== undefined) applyProfileStatus(doc, data.profileMediaStatus);
  if (parts.includes("profileMedia") && data.profileMedia) {
    const shown = ofKind(data.profileMedia, mediaKind(doc));
    if (grid) applyProfileMedia(doc, shown, img);
    if (grid && shown.length) hideEmpty(doc, ".user_posts");
    applyRecent(doc, data.profileMedia, img);
  }
  if (parts.includes("profile") && data.profile) applyProfile(doc, data.profile, img);
  if (parts.includes("bookmarks") && data.bookmarks && data.templates?.post) applyColumnPosts(doc, { posts: data.bookmarks, tpl: data.templates.post, me: data.me && String(data.me.id) }, img);
  if (parts.includes("queue") && data.queue) applyQueue(doc, page, data.queue, data.templates?.agenda, data.zone);
  if (parts.includes("notifications") && data.notificationsStatus !== undefined) applyNotificationsStatus(doc, data.notificationsStatus);
  if (parts.includes("notifications") && data.notifications) applyNotifications(doc, data.notifications, img);
  if (parts.includes("notificationCounts") && data.notificationCounts) applyNotificationCounts(doc, data.notificationCounts.counts, data.notificationCounts.tags);
  if (parts.includes("pastStreams") && data.pastStreams) applyPastStreams(doc, data.pastStreams, img);
  if (data.statementsStatus !== undefined && parts.some((p) => p === "transactions" || p === "payouts" || p === "referrals")) applyStatementsStatus(doc, data.statementsStatus);
  if (parts.includes("transactions") && data.transactions) applyTransactions(doc, data.transactions, data.zone, data.transactionsMore);
  if (parts.includes("payouts") && data.payouts) applyPayouts(doc, data.payouts);
  if (parts.includes("referrals") && data.referrals && data.templates?.payoutRow) applyPayouts(doc, data.referrals, data.templates.payoutRow);
  if (parts.includes("home") && data.homeStatus !== undefined) applyFeedStatus(doc, data.homeStatus);
  if (parts.includes("stories") && (data.stories || data.streams)) applyStories(doc, data.stories ?? [], img, { me: data.me, streams: data.streams, now: data.now });
  if (parts.includes("home") && data.home && data.templates?.post) applyHome(doc, data.home, data.authors ?? {}, data.templates.post, img, data.me && String(data.me.id), data.homeMore);
  if (parts.includes("promotions") && data.promotions) applyPromotions(doc, data.promotions, data.subscribePrice, data.me, img);
  if (parts.includes("events") && data.events) applyEvents(doc, data.events, data.now ?? new Date());
}

/** The Relay paths more than one mirror module reads: one spelling each, so their queries share one cache entry. */
export const USER_LISTS = "/api/of/v2/lists?limit=50";
/** Home's story strip: the creators the Creator follows with stories. */
export const STORIES_FEED = "/api/of/v2/stories";
/** Home's story strip: the live and scheduled streams (OF's streams/feed). */
export const STREAMS_FEED = "/api/of/v2/streams/feed";
export const VAULT_LISTS = "/api/of/v2/vault/lists?view=main&limit=50";
export const chatPath = (chat: string) => `/api/of/v2/chats/${encodeURIComponent(chat)}`;
/** The vault media the page's view (`?list ?type ?field ?sort ?q`) asks for: the Vault page's and the vault dialogs' tiles. */
export const vaultMediaOf = (params: { get(key: string): string | null }) => vaultMediaPath(viewOf(params));

/** The one mirror query for `path` (key `["of-mirror-data", accountId, path]`), fetched with the model's X-Account-Id. */
export function mirrorQuery<T = unknown>(accountId: string | null, path: string | null, enabled: boolean) {
  return {
    queryKey: ["of-mirror-data", accountId, path],
    queryFn: () => relay.get<T>(path!, { accountId }),
    enabled: !!accountId && !!path && enabled,
    staleTime: 60_000,
    retry: false,
  };
}

/**
 * Stale-while-revalidate for a mirrorQuery read the Relay serves from its day-long vault cache (the folder list, a vault
 * dialog's first 24): its cached answer (`cached`) shows at once; once it is in, the same path is read once more past
 * the cache (the Relay's `refresh=1`, which refills it) and that answer takes its place under the same key. Once per
 * model and path while mounted (a page open), never per render; a failed recheck leaves the cached answer.
 */
export function useRevalidate(accountId: string | null, path: string | null, cached: { isPending: boolean }) {
  const qc = useQueryClient();
  const done = useRef<string | null>(null);
  const ready = !!accountId && !!path && !cached.isPending;
  useEffect(() => {
    const at = `${accountId}|${path}`;
    if (!ready || done.current === at) return;
    done.current = at;
    relay.get(path!, { accountId }, undefined, { refresh: true }).then(
      (fresh) => qc.setQueryData(mirrorQuery(accountId, path, true).queryKey, fresh),
      () => {},
    );
  }, [ready, accountId, path, qc]);
}

/** Statements' Earnings' source and OF's page size (app.js `limit: Jg`, 10). */
export const TRANSACTIONS = "/api/of/v2/payouts/transactions";
export const TRANSACTIONS_PAGE = 10;

/** GET /users/list for `ids` (OF's batch user read, a dict by id). */
export const usersListPath = (ids: readonly string[]) => `/api/of/v2/users/list?${ids.map((id) => `ids=${encodeURIComponent(id)}`).join("&")}`;

/** A chat partner as OF's Messages page names it: its custom name (`displayName`, the Creator's rename of that user) over its name. */
export function chatUser<U extends OFUserMini>(u: U): U {
  const custom = u.displayName?.trim();
  return custom ? { ...u, name: custom } : u;
}

/**
 * The chat list's rows with their partners filled in: /chats sends each `withUser` bare (its id; OF's skip_users=all),
 * so, as on OF's page, the name, @handle and avatar come from /users/list by id (`users`; OF answers `[]` when it
 * resolves none). A partner it did not return keeps the bare id.
 */
export function withChatUsers(chats: OFChatItem[], users: unknown): OFChatItem[] {
  const byId = users && typeof users === "object" && !Array.isArray(users) ? (users as Record<string, OFUserMini>) : {};
  return chats.map((c) => {
    const u = byId[String(c.withUser.id)];
    return u ? { ...c, withUser: chatUser({ ...c.withUser, ...u, id: c.withUser.id }) } : c;
  });
}

/** A chat list page's /users/list read, as useQueries gives it. */
type PartnersRead = { isPending: boolean; data?: unknown };

/**
 * Each page's users, for rows that carry only their user's id (OF's skip_users=all: the chat list's partners, a feed's
 * authors): one /users/list call a page, its ids sorted for one key, so a next page asks only for its own. `ids` per
 * page, `reads` per page (a dict by id each), `key` standing for `reads` (a new array each render) in a memo's deps.
 */
function usePageUsers<T>(accountId: string | null, pages: readonly (readonly T[])[], idOf: (row: T) => unknown, enabled: boolean) {
  const ids = pages.map((rows) => [...new Set(rows.flatMap((r) => (idOf(r) != null ? [String(idOf(r))] : [])))].sort());
  const reads = useQueries({ queries: ids.map((page) => mirrorQuery(accountId, page.length ? usersListPath(page) : null, enabled)) });
  return { ids, reads, key: reads.map((r) => `${r.status}:${r.dataUpdatedAt}`).join(",") };
}

/** Whether a page's partners are still being asked for; a page with no partner ids asks nothing (its query is disabled, which TanStack reports as pending for ever). */
export const pendingPartners = (pageIds: readonly string[][], partners: readonly PartnersRead[]) =>
  partners.some((p, i) => !!pageIds[i]?.length && p.isPending);

/**
 * The chat list's rows from its pages, each partner named from its page's /users/list (withChatUsers), a chat on two
 * pages once. A page whose partners are still being asked for: when none of them is `known` (the partners this view
 * resolved so far; a first read) it and the pages after it wait (undefined when it is the first: "Loading chats…", no
 * bare ids); else its known partners' rows show and a new one (a chat that just came in) waits until it is named.
 */
export function chatRowsOf(pages: readonly OFChatItem[][], pageIds: readonly string[][], partners: readonly PartnersRead[], known: Record<string, OFUserMini>): OFChatItem[] | undefined {
  const seen = new Set<string>();
  const rows: OFChatItem[] = [];
  for (let i = 0; i < pages.length; i++) {
    const waiting = !!pageIds[i]?.length && !!partners[i]?.isPending;
    if (waiting && !pageIds[i].some((id) => Object.hasOwn(known, id))) return i === 0 ? undefined : rows;
    for (const c of withChatUsers(pages[i].filter((c) => c?.withUser), waiting ? known : partners[i]?.data)) {
      const id = String(c.withUser.id);
      if ((waiting && !Object.hasOwn(known, id)) || seen.has(id)) continue;
      seen.add(id);
      rows.push(c);
    }
  }
  return rows;
}

/** The Vault page's own pages (vault/index, vault/list, vault/state-*), whose grid loads more as it is scrolled. */
export const isVaultPage = (page: string) => page.startsWith("vault/");

/** OF's next offset after `pages`: the media so far while OF says it has more (its `hasMore`, the only marker it sends). */
export function nextVaultOffset(pages: readonly Partial<VaultMediaResp>[]): number | undefined {
  const last = pages.at(-1);
  return last?.hasMore && last.list?.length ? pages.reduce((n, p) => n + (p.list?.length ?? 0), 0) : undefined;
}

/** The pages' media in order, each media once: OF's offset pages overlap (read live: page 2 repeated two of page 1's). */
export const vaultPageMedia = (pages: readonly Partial<VaultMediaResp>[]): VaultMedia[] => uniqueRows(pages.flatMap((p) => p.list ?? []));

/**
 * The Vault page's media for `path` (vaultMediaOf: 24 a page), page by page with OF's `offset`. Its own key (a composer's
 * vault dialog reads `path` once, with mirrorQuery), still under `["of-mirror-data", accountId]`, so a write's refresh
 * reaches it. Each page is OF's own as it is now (the Relay's `refresh=1`: past its day-long vault cache, which it
 * refills), as OF's Vault reads every page it shows: no tab, folder or page a day older than the next.
 */
export function vaultPagesQuery(accountId: string | null, path: string | null) {
  return infiniteQueryOptions({
    queryKey: ["of-mirror-data", accountId, path, "pages"],
    queryFn: ({ pageParam }) => relay.get<VaultMediaResp>(`${path}&offset=${pageParam}`, { accountId }, undefined, { refresh: true }),
    initialPageParam: 0,
    getNextPageParam: (_last: VaultMediaResp, pages: VaultMediaResp[]) => nextVaultOffset(pages),
    enabled: !!accountId && !!path,
    staleTime: 60_000,
    retry: false,
  });
}

/** An offset-paged read: `route` (with its query: limit, filters) a page at a time from offset 0 (`next`: nextOffset). */
export function offsetPagesQuery(accountId: string | null, route: string | null, enabled: boolean, next: (last: unknown, pages: unknown[]) => number | undefined = nextOffset) {
  return infiniteQueryOptions({
    queryKey: ["of-mirror-data", accountId, route, "pages"],
    queryFn: ({ pageParam }) => relay.get<unknown>(`${route}&offset=${pageParam}`, { accountId }),
    initialPageParam: 0,
    getNextPageParam: next,
    enabled: !!accountId && !!route && enabled,
    staleTime: 60_000,
    retry: false,
  });
}

/** A marker-paged read (OF's format=infinite): `route` first, then each page before the last one's tailMarker (nextMarker). */
export function markerPagesQuery(accountId: string | null, route: string | null, enabled: boolean) {
  return infiniteQueryOptions({
    queryKey: ["of-mirror-data", accountId, route, "pages"],
    queryFn: ({ pageParam }) => relay.get<unknown>(pageParam ? `${route}&before_publish_time=${encodeURIComponent(pageParam)}` : route!, { accountId }),
    initialPageParam: null as string | null,
    getNextPageParam: nextMarker,
    enabled: !!accountId && !!route && enabled,
    staleTime: 60_000,
    retry: false,
  });
}

type PagesState = { isFetchingNextPage: boolean; isFetchNextPageError: boolean; error: unknown; hasNextPage: boolean; fetchNextPage: () => unknown };
/** An offset-paged read's next page as OF's infinite loading row shows it (MorePages). */
const morePages = (q: PagesState): MorePages => ({
  loading: q.isFetchingNextPage,
  error: q.isFetchNextPageError ? message(q.error) : null,
  next: q.hasNextPage ? () => void q.fetchNextPage() : null,
});

type ReadState = { isError: boolean; error: unknown; isPending: boolean; isFetchNextPageError?: boolean };
/**
 * A feed's or table's status: loading until its first page and its borrowed row (`tpl`, when it needs one) are both
 * here, either failing the error; a next page's failure is its own prompt (MorePages), not this.
 */
const feedStatus = (q: ReadState, tpl: ReadState | null): string | null | undefined =>
  q.isError && !q.isFetchNextPageError ? message(q.error) : tpl?.isError ? message(tpl.error) : q.isPending || tpl?.isPending ? null : undefined;

/** How near the end of the Vault page's (and the chat list's) scroll (px) its next page is asked for. */
const MORE_PX = 400;
/** The chat list's page size (the Relay assembles OF's pages of 10 up to it). */
export const CHATS_PAGE = 20;
/** How near the visible end (px) the chat list's last row brings its next page: vue-infinite-loading's default distance, OF's loader. */
const CHATS_MORE_PX = 100;

/** On a DATA_PAGES page with a single model selected, show the model's rows on every frame load and data or query change. */
export function useOfData(frameRef: RefObject<HTMLIFrameElement | null>, src: string): void {
  const { accountId } = useScope();
  const params = useSearchParams();
  const chat = params.get("chat");
  const label = params.get("label");
  const page = /^\/of-mirror\/pages\/(.+)\.html$/.exec(src)?.[1] ?? "";
  const parts = partsOf(page);
  const q = (part: Part, path: string | null) => mirrorQuery(accountId, path, parts.includes(part));
  const enc = (v: string | null) => (v ? encodeURIComponent(v) : null);
  // The chat list: Messages Pro's useChatList (offset pages, OF's filter / list_id / order / query from the URL's view,
  // its 90s head poll) under Messages Pro's key, though its page size (CHATS_PAGE) makes it its own entry. Nothing here marks a chat read.
  const isChats = parts.includes("chats");
  const view = chatsView(params);
  const listQuery = chatsQuery(view);
  const chatList = useChatList({ ...chatsRequest(view), limit: CHATS_PAGE, enabled: isChats && !!accountId });
  // The top unread threads, first tier only: activity inside the frame never reaches this window.
  useUnreadMessagesPrefetch(chatList.data, chatList.fetchedLive, UNREAD_PREFETCH_TIERS.slice(0, 1));
  const loadMoreChats = useRef(chatList.loadMore);
  loadMoreChats.current = chatList.loadMore;
  // Each page's partners (each /chats row carries only its partner's id).
  const { ids: pageIds, reads: partners, key: partnersKey } = usePageUsers(accountId, chatList.pages ?? [], (c: OFChatItem) => c?.withUser?.id, isChats);
  // The partners this view has resolved so far, by id: a page whose /users/list key changed (a new chat came in at the
  // top) keeps showing the partners already known while the new call runs, instead of the whole list going back to
  // "Loading chats…"; a new tab, sort, folder or search starts empty (its rows wait for their partners).
  const known = useRef<{ view: string; users: Record<string, OFUserMini> }>({ view: listQuery, users: {} });
  if (known.current.view !== listQuery) known.current = { view: listQuery, users: {} };
  for (const p of partners) if (p.data && typeof p.data === "object" && !Array.isArray(p.data)) Object.assign(known.current.users, p.data);
  // A page with no partner ids asks nothing (its query is disabled, so TanStack keeps it pending for ever): never waited on.
  const partnersPending = pendingPartners(pageIds, partners);
  const isGallery = parts.includes("gallery");
  const detail = useQuery(mirrorQuery(accountId, chat && chatPath(chat), parts.includes("thread") || isGallery));
  const fanId = chat ? fanIdFromParam(chat) : null;
  // The pinned page's thread is the chat's pinned messages (Messages Pro's useChatPinned: OF's messages?filter=pinned).
  const isPinnedPage = page === "messages/chat/pinned";
  const pinned = useChatPinned(accountId, fanId, isPinnedPage);
  // The open chat's messages: Messages Pro's useChatMessages (the newest 30, older ones by before_id as the thread is
  // scrolled up, its poll). It sends no mark-as-read.
  const thread = useChatMessages({ accountId, fanId, enabled: parts.includes("thread") && !isPinnedPage && !!chat && !!accountId });
  // The Gallery: Messages Pro's useFanChatMedia for the open tab (OF's last_id pages).
  const gTab = galleryTab(params);
  const gallery = useFanChatMedia(accountId, fanId, { ...galleryRequest(gTab), enabled: isGallery && !!chat });
  const vaultSearch = viewOf(params).slist;
  const vaultLists = vaultListsPath({ slist: vaultSearch }); // with the Vault page's folder search (?slist=)
  const vault = useQuery(q("vaultLists", vaultLists));
  useRevalidate(accountId, parts.includes("vaultLists") ? vaultLists : null, vault);
  // The Vault page pages its grid (each page past the cache); a composer's vault dialog reads the first 24 (the query
  // ofMirrorPost shares), cached first, then rechecked.
  const vaultPage = isVaultPage(page) && parts.includes("vaultMedia");
  const dialogMedia = !vaultPage && parts.includes("vaultMedia") ? vaultMediaOf(params) : null;
  const vaultMedia = useQuery(q("vaultMedia", dialogMedia));
  useRevalidate(accountId, dialogMedia, vaultMedia);
  const vaultPages = useInfiniteQuery(vaultPagesQuery(accountId, vaultPage ? vaultMediaOf(params) : null));
  const vaultRead = vaultPage ? vaultPages : vaultMedia;
  const lists = useQuery(q("userLists", USER_LISTS));
  // The open list: the page's ?list, else (as on OF) the first list.
  const first = rowsOf<UserList>(lists.data)?.[0]?.id;
  const list = params.get("list") ?? ((parts.includes("listUsers") || parts.includes("listPosts")) && first != null ? String(first) : null);
  // Search users (ofMirrorCollections): the page's ?query, OF's own `query` on the list's users.
  const usersQuery = params.get("query");
  const members = useQuery(q("listUsers", list && `/api/of/v2/lists/${enc(list)}/users?limit=50${usersQuery ? `&query=${enc(usersQuery)}` : ""}`));
  const postType = postTypeOf(params.get("postType"));
  // A list's Posts tab: OF's pages of 10, each next one when OF's loading row scrolls into view (MorePages).
  const listPostsRoute = list && listPostsPath(list, postType);
  const listPosts = useInfiniteQuery(offsetPagesQuery(accountId, listPostsRoute, parts.includes("listPosts")));
  const listPostRows = useMemo(() => uniqueRows(pageRows<MirrorPost>(listPosts.data?.pages)), [listPosts.data]);
  const subscribers = useQuery(q("subscribers", "/api/of/v2/subscribers?type=active&limit=50"));
  const labels = useQuery(mirrorQuery(accountId, "/api/of/v2/labels", parts.includes("labels") || parts.includes("profile")));
  const ofMeQ = useQuery(ofMeQuery(accountId));
  const ofMe = ofMeQ.data;
  // My profile's rows wait on the Creator's id: loading while it is read, its error if that failed.
  const ofMeStatus = ofMeQ.isError ? message(ofMeQ.error) : ofMeQ.isPending ? null : undefined;
  const meId = ofMe?.id;
  const me = meId != null ? `/api/of/v2/users/${enc(String(meId))}` : null;
  // My profile's wall: OF's pages of 20, each next one (before the last one's tailMarker) when OF's loading row scrolls into view.
  const posts = useInfiniteQuery(markerPagesQuery(accountId, me && `${me}/posts?limit=${POSTS_PAGE}&format=infinite`, parts.includes("posts")));
  const postRows = useMemo(() => uniqueRows(pageRows<MirrorPost>(posts.data?.pages)), [posts.data]);
  const photos = useQuery(q("profileMedia", me && `${me}/posts/photos?limit=24`));
  const videos = useQuery(q("profileMedia", me && `${me}/posts/videos?limit=24`));
  const highlights = useQuery(q("profile", me && `${me}/stories/highlights`));
  // Home's strip: the Creator's own active stories (OF's userStories tile).
  const myStories = useQuery(q("stories", me && `${me}/stories`));
  const bookmarks = useQuery(q("bookmarks", "/api/of/v2/posts/bookmarks/all?limit=20"));
  // The month the queue's calendar shows: read from the frame once it has loaded (see apply).
  const [month, setMonth] = useState<Month | null>(null);
  const zone = useAgencyZone();
  const queue = useQuery(q("queue", Object.hasOwn(QUEUE, page) ? QUEUE[page].route(month, zone) : null));
  // A chat menu's "View user's comments": the commented tab for one user (OF's ?related_user=).
  const relatedUser = page === "notifications/commented" ? params.get("related_user") : null;
  const notifications = useQuery(q("notifications", Object.hasOwn(NOTIFICATIONS, page) ? `${NOTIFICATIONS[page]}${relatedUser ? `&related_user=${encodeURIComponent(relatedUser)}` : ""}` : null));
  const notificationCounts = useQuery(q("notificationCounts", NOTIFICATION_COUNTS));
  const newTags = ofMe?.newTagsCount;
  const pastStreams = useQuery(q("pastStreams", me && `${me}/streams?limit=8`));
  // Statements' Earnings: OF's pages of 10 (app.js), each next one when OF's loading row scrolls into view (MorePages).
  const transactions = useInfiniteQuery(offsetPagesQuery(accountId, `${TRANSACTIONS}?limit=${TRANSACTIONS_PAGE}`, parts.includes("transactions")));
  const payouts = useQuery(q("payouts", "/api/of/v2/payouts/requests?limit=20"));
  const referrals = useQuery(q("referrals", "/api/of/v2/payouts/requests/referral?limit=20"));
  // Home's feed: OF's pages of 20 by offset, each next one when OF's loading row scrolls into view (MorePages).
  const home = useInfiniteQuery(offsetPagesQuery(accountId, `/api/of/v2/posts?limit=${POSTS_PAGE}`, parts.includes("home"), nextFeedOffset));
  const homeRows = useMemo(() => uniqueRows(pageRows<MirrorPost>(home.data?.pages)), [home.data]);
  const stories = useQuery(q("stories", STORIES_FEED));
  const streams = useQuery(q("stories", STREAMS_FEED));
  // The home feed's (or a list's Posts tab's) authors (its posts carry only their author's id), as the chat list's partners.
  const feedPages = parts.includes("listPosts") ? (listPosts.data?.pages ?? []).map((p) => rowsOf<MirrorPost>(p) ?? []) : (home.data?.pages ?? []).map((p) => rowsOf<MirrorPost>(p) ?? []);
  const { reads: authorPages, key: authorsKey } = usePageUsers(accountId, feedPages, (p: MirrorPost) => p.author?.id, parts.includes("home") || parts.includes("listPosts"));
  const promotions = useQuery(q("promotions", "/api/of/v2/promotions"));
  const events = useQuery(q("events", eventsRoute(new Date()))); // one key a day
  // A borrowed row: its committed capture, fetched same-origin (never the Relay) and parsed inertly, once per session.
  const need = (Object.keys(TEMPLATES) as Template[]).find((t) => TEMPLATES[t]!.parts.some((p) => parts.includes(p)) && TEMPLATES[t]!.page !== page);
  const from = need && TEMPLATES[need]!.page;
  const template = useQuery({
    queryKey: ["of-mirror-template", from],
    queryFn: async () => {
      const res = await fetch(`/of-mirror/pages/${from}.html`);
      if (!res.ok) throw new Error(`${from}: ${res.status}`);
      return TEMPLATES[need!]!.pick(new DOMParser().parseFromString(await res.text(), "text/html")) ?? null;
    },
    enabled: !!accountId && !!from,
    staleTime: Infinity,
    retry: false,
  });

  // The Statements table's rows: loading until they (Referrals: and their borrowed row) are here; either failing is the error.
  const stmt = parts.includes("transactions") ? transactions : parts.includes("payouts") ? payouts : parts.includes("referrals") ? referrals : null;
  const statementsStatus = stmt ? feedStatus(stmt, need ? template : null) : undefined;
  const data = useMemo<MirrorData>(() => {
    // A tab, sort or search switch shows the loading line, not the previous view's rows (useChatList keeps them meanwhile).
    const pages = chatList.isPending || chatList.isPlaceholderData ? undefined : chatList.pages;
    // A page's rows wait for its partners (no flash of bare ids); a failed /users/list shows them as they are.
    const chatRows = pages && chatRowsOf(pages, pageIds, partners, known.current.users);
    const messages = isPinnedPage ? pinned.data : thread.data;
    const [photoPosts, videoPosts] = [rowsOf<MirrorPost>(photos.data), rowsOf<MirrorPost>(videos.data)];
    const opened = (detail.data as OFChatItem | undefined)?.withUser;
    const fan = (opened && chatUser(opened)) ?? chatRows?.find((c) => sameId(c.withUser.id, chat))?.withUser ?? null;
    const status = (r: { isError: boolean; error: unknown; isPending: boolean }) => (r.isError ? message(r.error) : r.isPending ? null : undefined);
    // No open list (lists failed, are loading, or are none): the users column follows the lists.
    const people = parts.includes("subscribers") ? subscribers : list ? members : lists;
    return {
      chat,
      list,
      label,
      chats: chatRows,
      chatsStatus: chatList.isError ? message(chatList.error) : !chatRows ? null : undefined,
      listQuery,
      chatsMore: { loading: chatList.isFetchingMore, error: null, next: chatList.hasMore ? () => void loadMoreChats.current() : null },
      thread: messages ? { fan, messages } : undefined,
      chatFan: fan,
      pinnedCount: (detail.data as { countPinnedMessages?: number } | undefined)?.countPinnedMessages,
      gallery: isGallery
        ? {
            tab: gTab,
            // A tab switch shows the loading line, not the previous tab's tiles (useFanChatMedia keeps them meanwhile).
            items: gallery.data && !gallery.isPlaceholderData ? galleryItems(gallery.data.pages) : undefined,
            status: gallery.isError ? message(gallery.error) : gallery.isPending || gallery.isPlaceholderData ? null : undefined,
            more: gallery.isFetchingNextPage,
            next: !!gallery.hasNextPage && !galleryStalled(gallery.data?.pages ?? []),
            moreError: gallery.isFetchNextPageError ? message(gallery.error) : undefined,
          }
        : undefined,
      vaultLists: rowsOf<VaultList>(vault.data),
      vaultAll: (vault.data as { all?: Partial<VaultList> } | undefined)?.all,
      vaultSort: (vault.data as { sort?: string } | undefined)?.sort,
      vaultSearch,
      vaultMedia: vaultPage ? (vaultPages.data ? vaultPageMedia(vaultPages.data.pages) : undefined) : rowsOf<VaultMedia>(vaultMedia.data),
      vaultStatus: vaultRead.isError ? message(vaultRead.error) : vaultRead.isPending ? null : undefined,
      userLists: rowsOf<UserList>(lists.data),
      userListsStatus: status(lists),
      listUsers: rowsOf<OFUserMini>(members.data),
      listPosts: listPostRows,
      // No ?list= yet: the open list is the lists' first, so the tab follows the lists (loading, failed; none: its "No posts yet").
      listPostsStatus: list ? feedStatus(listPosts, need ? template : null) : feedStatus(lists, null),
      listPostsMore: morePages(listPosts),
      postType,
      subscribers: rowsOf<OFUserMini>(subscribers.data),
      usersStatus: status(people),
      labels: rowsOf<PostLabel>(labels.data),
      labelsStatus: status(labels),
      posts: postRows,
      postsStatus: me ? feedStatus(posts, null) : ofMeStatus,
      postsMore: morePages(posts),
      // Both lists or none: one missing (an error, or not here yet) leaves the empty grid.
      profileMedia: photoPosts && videoPosts ? [...photoPosts.map((p) => ({ ...p, _kind: "photo" as const })), ...videoPosts.map((p) => ({ ...p, _kind: "video" as const }))] : undefined,
      profileMediaStatus: !me ? ofMeStatus : photos.isError ? message(photos.error) : videos.isError ? message(videos.error) : photos.isPending || videos.isPending ? null : undefined,
      profile: ofMe ? { user: ofMe as ProfileUser, labels: rowsOf<PostLabel>(labels.data), highlights: rowsOf<Highlight>(highlights.data) } : undefined,
      bookmarks: rowsOf<MirrorPost>(bookmarks.data),
      queue: rowsOf<QueueItem>(queue.data),
      zone,
      notifications: relatedOnly(rowsOf<MirrorNotification>(notifications.data), relatedUser),
      notificationsStatus: notifications.isError ? message(notifications.error) : notifications.isPending ? null : undefined,
      notificationCounts: notificationCounts.data && typeof notificationCounts.data === "object" && !Array.isArray(notificationCounts.data) ? { counts: notificationCounts.data as NotificationCounts, tags: newTags } : undefined,
      pastStreams: rowsOf<PastStream>(pastStreams.data),
      transactions: pageRows<Transaction>(transactions.data?.pages),
      transactionsMore: morePages(transactions),
      payouts: rowsOf<Payout>(payouts.data),
      referrals: rowsOf<Payout>(referrals.data),
      statementsStatus,
      home: homeRows,
      homeStatus: feedStatus(home, need ? template : null),
      homeMore: morePages(home),
      stories: stripUsers(meId != null ? { id: meId, name: ofMe?.name, username: ofMe?.username, avatar: ofMe?.avatar, isVerified: ofMe?.isVerified } : undefined, rowsOf<StoryEntry>(myStories.data), rowsOf<StoryUser>(stories.data)),
      streams: rowsOf<FeedStream>(streams.data),
      // Keyed by id; OF sends [] when it resolves none.
      authors: authorPages.some((a) => a.data) ? Object.assign({}, ...authorPages.map((a) => (a.data && typeof a.data === "object" && !Array.isArray(a.data) ? a.data : {}))) : undefined,
      // OF's `{hasMore, items}` (service/of_promos.py).
      promotions: rowsOf<Promotion>(promotions.data) ?? (Array.isArray((promotions.data as { items?: unknown } | undefined)?.items) ? (promotions.data as { items: Promotion[] }).items : undefined),
      subscribePrice: ofMe?.subscribePrice,
      me: meId != null ? { id: meId, name: ofMe?.name ?? undefined, username: ofMe?.username ?? undefined, avatar: ofMe?.avatar } : undefined,
      events: rowsOf<QueueItem>(events.data),
      templates: need && template.data ? { [need]: template.data } : undefined,
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- partnersKey and authorsKey stand for partners and authorPages (new arrays each render)
  }, [chat, list, label, postType, listPosts.data, listPosts.error, listPosts.isPending, listPosts.isFetchingNextPage, listPosts.isFetchNextPageError, listPosts.hasNextPage, listPosts.fetchNextPage, parts, chatList.pages, chatList.isPending, chatList.isPlaceholderData, chatList.isError, chatList.error, chatList.isFetchingMore, chatList.hasMore, partnersKey, listQuery, detail.data, thread.data, isPinnedPage, pinned.data, isGallery, gTab, gallery.data, gallery.isPlaceholderData, gallery.isError, gallery.error, gallery.isPending, gallery.isFetchingNextPage, gallery.hasNextPage, gallery.isFetchNextPageError, vault.data, vaultSearch, vaultPage, vaultMedia.data, vaultPages.data, vaultRead.error, vaultRead.isPending, lists.data, lists.error, lists.isPending, members.data, members.error, members.isPending, subscribers.data, subscribers.error, subscribers.isPending, labels.data, labels.error, labels.isPending, postRows, posts.error, posts.isPending, posts.isFetchingNextPage, posts.isFetchNextPageError, posts.hasNextPage, posts.fetchNextPage, photos.data, photos.error, photos.isPending, videos.data, videos.error, videos.isPending, highlights.data, ofMeStatus, bookmarks.data, queue.data, zone, notifications.data, notifications.error, relatedUser, notificationCounts.data, newTags, pastStreams.data, transactions.data, transactions.isFetchingNextPage, transactions.isFetchNextPageError, transactions.error, transactions.hasNextPage, transactions.fetchNextPage, payouts.data, referrals.data, statementsStatus, homeRows, home.error, home.isPending, home.isFetchingNextPage, home.isFetchNextPageError, home.hasNextPage, home.fetchNextPage, stories.data, streams.data, myStories.data, authorsKey, promotions.data, ofMe, meId, events.data, need, template.data, template.error]);

  useEffect(() => {
    const frame = frameRef.current;
    if (!frame || !partsOf(page).length) return;
    const apply = () => {
      const doc = frame.contentDocument;
      if (!doc?.body) return;
      const m = queueMonth(doc);
      setMonth((was) => (was?.start === m?.start && was?.end === m?.end ? was : m));
      // The draft is the one copy of the picks: read on every apply, as a tile click changes it without a re-render.
      const draft = !accountId ? null : page === VAULT_DIALOG ? accountId : page === HOME_VAULT ? homeDraft(accountId) : null;
      const picked = draft ? loadDraft(window.sessionStorage, draft).media_files.filter((m) => typeof m === "number") : undefined;
      // A chat's or New message's vault dialog: its ticks (attached only by its Add), over its tabs and folders.
      const chatPicked = accountId && chat && page === CHAT_VAULT ? loadVaultPick(window.sessionStorage, vaultPickKey(accountId, CHAT_VAULT, chat)).ids : undefined;
      const massPicked = accountId && page === MASS_VAULT ? loadVaultPick(window.sessionStorage, vaultPickKey(accountId, MASS_VAULT)).ids : undefined;
      // A composer's vault dialog never shows the captured folders and media: the Creator's, else none (All-Creators, loading).
      const dialog = page === VAULT_DIALOG || page === HOME_VAULT || page === CHAT_VAULT || page === MASS_VAULT;
      const real: MirrorData = accountId ? data : {};
      const shown: MirrorData = dialog ? { ...real, vaultLists: real.vaultLists ?? [], vaultAll: real.vaultAll ?? {}, vaultMedia: real.vaultMedia ?? [] } : real;
      // The Vault page's selected tiles stay selected when its grid is drawn again (its next page arrived).
      const held = isVaultPage(page) ? [...doc.querySelectorAll<HTMLElement>("[data-oi-media].selected")].map((t) => t.dataset.oiMedia) : [];
      // The thread's scroll, read before the redraw empties it (older messages or a poll never move what is in view).
      const was = threadScroll(doc, chat);
      // Another tab, sort, folder or search starts the list at its top, as OF's.
      const list = doc.querySelector<HTMLElement>(".b-chats__scroller");
      if (list && list.dataset.oiView !== listQuery) {
        list.dataset.oiView = listQuery;
        list.scrollTop = 0;
      }
      applyData(doc, page, accountId ? { ...shown, picked: picked ?? chatPicked ?? massPicked } : shown, (u) => proxyImage(u, accountId));
      if (shown.thread && chat && partsOf(page).includes("thread")) keepThreadScroll(doc, chat, was);
      for (const id of held) {
        const tile = doc.querySelector(`[data-oi-media="${id}"]`);
        if (tile) toggleTile(tile, true);
      }
    };
    // The queue's month, day and tabs change in place (ofMirrorQueue): its rows follow, and a new month is asked for.
    let doc: Document | null = null;
    const onLoad = () => {
      doc?.removeEventListener(QUEUE_CHANGE, apply);
      doc?.removeEventListener(PROFILE_CHANGE, apply);
      doc = frame.contentDocument;
      doc?.addEventListener(QUEUE_CHANGE, apply);
      doc?.addEventListener(PROFILE_CHANGE, apply);
      apply();
    };
    if (frame.contentDocument?.readyState === "complete") onLoad();
    frame.addEventListener("load", onLoad);
    return () => {
      frame.removeEventListener("load", onLoad);
      doc?.removeEventListener(QUEUE_CHANGE, apply);
      doc?.removeEventListener(PROFILE_CHANGE, apply);
    };
  }, [frameRef, src, page, data, accountId, chat, listQuery]);

  // The Vault page's infinite scroll, as OF's: near the end of whatever scrolls the grid (the page, or its column), the
  // next 24; checked again once each page is drawn, so a grid shorter than the frame keeps loading.
  const { hasNextPage, isFetchingNextPage, fetchNextPage } = vaultPages;
  useEffect(() => {
    const frame = frameRef.current;
    if (!frame || !vaultPage || !hasNextPage || isFetchingNextPage) return;
    const near = (el: Element | null | undefined) => !!el && el.scrollHeight > 0 && el.scrollTop + el.clientHeight >= el.scrollHeight - MORE_PX;
    const check = (el?: Element | null) => {
      const d = frame.contentDocument;
      if (d?.querySelector("[data-oi-media]") && near(el ?? d.scrollingElement)) void fetchNextPage({ cancelRefetch: false }); // a page in flight is not asked again
    };
    const onScroll = (ev: Event) => {
      const t = ev.target as Document | Element;
      check("scrollingElement" in t ? t.scrollingElement : t.querySelector?.("[data-oi-media]") ? t : null);
    };
    let doc: Document | null = null;
    const attach = () => {
      doc?.removeEventListener("scroll", onScroll, true);
      doc = frame.contentDocument;
      doc?.addEventListener("scroll", onScroll, true);
      check();
    };
    if (frame.contentDocument?.readyState === "complete") attach();
    frame.addEventListener("load", attach);
    return () => {
      frame.removeEventListener("load", attach);
      doc?.removeEventListener("scroll", onScroll, true);
    };
  }, [frameRef, src, vaultPage, data, hasNextPage, isFetchingNextPage, fetchNextPage]);

  // The chat list's infinite scroll, as OF's: near the end of whatever scrolls the list (its column, or the page on a
  // phone), the next page; checked again once each page is drawn, so a list shorter than the frame keeps loading. Only
  // once the last page's rows are drawn (their partners are here), and never while the list is hidden (a chat on a phone).
  const chatsNext = isChats && !!accountId && chatList.hasMore && !chatList.isFetchingMore && !partnersPending;
  useEffect(() => {
    const frame = frameRef.current;
    if (!frame || !chatsNext) return;
    // OF's infinite loader sits under the last row: the next page once that row's end is within CHATS_MORE_PX of the visible
    // part of the list (the list's own scroll box, or the frame's viewport when the page scrolls).
    const check = () => {
      const d = frame.contentDocument;
      const win = d?.defaultView;
      const box = d?.querySelector<HTMLElement>(".b-chats__scroller");
      const rows = box?.querySelectorAll<HTMLElement>("[data-oi-chat]");
      const last = rows?.[rows.length - 1];
      if (!win || !box || !last || !box.checkVisibility?.()) return;
      const clips = /(auto|scroll)/.test(win.getComputedStyle(box).overflowY);
      const end = Math.min(win.innerHeight, clips ? box.getBoundingClientRect().bottom : win.innerHeight);
      if (last.getBoundingClientRect().bottom - end <= CHATS_MORE_PX) void loadMoreChats.current();
    };
    let doc: Document | null = null;
    const attach = () => {
      doc?.removeEventListener("scroll", check, true);
      doc = frame.contentDocument;
      doc?.addEventListener("scroll", check, true);
      check();
    };
    if (frame.contentDocument?.readyState === "complete") attach();
    frame.addEventListener("load", attach);
    return () => {
      frame.removeEventListener("load", attach);
      doc?.removeEventListener("scroll", check, true);
    };
  }, [frameRef, src, chatsNext, data]);

  // The thread's older messages, as OF's: near the top of the thread, the page before its oldest (before_id); checked
  // again once each page is drawn, so a thread shorter than its box keeps loading. keepThreadScroll holds the view.
  const { hasOlder, isLoadingOlder, loadOlder } = thread;
  const olderNext = parts.includes("thread") && !isPinnedPage && !!chat && !!accountId && hasOlder && !isLoadingOlder;
  useEffect(() => {
    const frame = frameRef.current;
    if (!frame || !olderNext) return;
    const check = () => {
      const box = frame.contentDocument?.querySelector<HTMLElement>(THREAD_BOX);
      if (box?.querySelector(".b-chat__item-message[data-oi-data]") && box.scrollTop <= OLDER_PX) void loadOlder().catch(() => {});
    };
    let doc: Document | null = null;
    const attach = () => {
      doc?.removeEventListener("scroll", check, true);
      doc = frame.contentDocument;
      doc?.addEventListener("scroll", check, true);
      check();
    };
    if (frame.contentDocument?.readyState === "complete") attach();
    frame.addEventListener("load", attach);
    return () => {
      frame.removeEventListener("load", attach);
      doc?.removeEventListener("scroll", check, true);
    };
  }, [frameRef, src, olderNext, loadOlder, data]);

  // The Gallery's next page, as OF's grid: near the end of whatever scrolls it (its column, or the page on a phone).
  const galleryNext = isGallery && !!gallery.hasNextPage && !gallery.isFetchingNextPage && !gallery.isPlaceholderData && !gallery.isFetchNextPageError && !galleryStalled(gallery.data?.pages ?? []);
  const fetchGallery = gallery.fetchNextPage;
  const refetchGallery = gallery.refetch;
  const galleryMoreFailed = gallery.isFetchNextPageError;
  // The gallery's Retry (after a failed page): that page again, or the first one.
  useEffect(() => {
    const frame = frameRef.current;
    if (!frame || !isGallery) return;
    const onClick = (ev: MouseEvent) => {
      if (!(ev.target as Element | null)?.closest?.("[data-oi-gallery-retry]")) return;
      ev.preventDefault();
      void (galleryMoreFailed ? fetchGallery() : refetchGallery());
    };
    let doc: Document | null = null;
    const attach = () => {
      doc?.removeEventListener("click", onClick, true);
      doc = frame.contentDocument;
      doc?.addEventListener("click", onClick, true);
    };
    attach();
    frame.addEventListener("load", attach);
    return () => {
      frame.removeEventListener("load", attach);
      doc?.removeEventListener("click", onClick, true);
    };
  }, [frameRef, src, isGallery, galleryMoreFailed, fetchGallery, refetchGallery]);
  useEffect(() => {
    const frame = frameRef.current;
    if (!frame || !galleryNext) return;
    const check = () => {
      const d = frame.contentDocument;
      const win = d?.defaultView;
      const tiles = d?.querySelectorAll<HTMLElement>(".b-gallery-wrapper .b-photos > [data-oi-data]");
      const last = tiles?.[tiles.length - 1];
      // Pages whose items all drew no tile: the next one at once (else the grid would wait under "Loading media…").
      if (win && !last && d?.querySelector(".b-gallery-wrapper .b-photos")) return void fetchGallery({ cancelRefetch: false });
      if (!win || !last || !last.checkVisibility?.()) return;
      const box = last.closest<HTMLElement>(".b-feed-content");
      const clips = !!box && /(auto|scroll)/.test(win.getComputedStyle(box).overflowY);
      const end = Math.min(win.innerHeight, clips ? box!.getBoundingClientRect().bottom : win.innerHeight);
      if (last.getBoundingClientRect().bottom - end <= MORE_PX) void fetchGallery({ cancelRefetch: false });
    };
    let doc: Document | null = null;
    const attach = () => {
      doc?.removeEventListener("scroll", check, true);
      doc = frame.contentDocument;
      doc?.addEventListener("scroll", check, true);
      check();
    };
    if (frame.contentDocument?.readyState === "complete") attach();
    frame.addEventListener("load", attach);
    return () => {
      frame.removeEventListener("load", attach);
      doc?.removeEventListener("scroll", check, true);
    };
  }, [frameRef, src, galleryNext, fetchGallery, data]);

  // The chat page's Find and a gallery tile's ?firstId= jump (ofMirrorThread), on the same thread paging.
  // The pinned page's Find: its pins, all drawn (no older pages to read).
  useThreadFind(frameRef, src, (page === "messages/chat" || isPinnedPage) && !!accountId, accountId, chat, isPinnedPage ? null : params.get("firstId"), isPinnedPage ? NO_PAGING : thread, data, isPinnedPage);
}

/** The pinned page's thread: one page, nothing older. */
const NO_PAGING = { hasOlder: false, loadOlder: async () => ({ added: 0, hasMore: false }) };

/** A notifications page for one user (`related_user`): only that user's items (OF filters them; a Relay that does not yet is followed here). */
export function relatedOnly(rows: MirrorNotification[] | undefined, user: string | null): MirrorNotification[] | undefined {
  if (!rows || !user) return rows;
  return rows.filter((n) => sameId((n.user ?? n.fromUser)?.id, user));
}

/** Consecutive pages with no new item after which the Gallery stops asking for more (OF's pages always carry media). */
export const GALLERY_EMPTY_CAP = 5;
/** The Gallery's last GALLERY_EMPTY_CAP pages all brought no new item: stop paging (it would page forever). */
export function galleryStalled(pages: readonly { list?: unknown[] }[]): boolean {
  const seen = new Set<string>();
  let empty = 0;
  for (const p of pages) {
    let added = 0;
    for (const m of (p.list ?? []) as ThreadMessage[]) {
      if (m?.id == null || seen.has(String(m.id))) continue;
      seen.add(String(m.id));
      added++;
    }
    empty = added ? 0 : empty + 1;
  }
  return empty >= GALLERY_EMPTY_CAP;
}

/** The Gallery's tiles from its pages, newest first, a message once. */
export function galleryItems(pages: readonly { list?: unknown[] }[]): ThreadMessage[] {
  const seen = new Set<string>();
  const out: ThreadMessage[] = [];
  for (const p of pages) for (const m of (p.list ?? []) as ThreadMessage[]) {
    if (m?.id == null || seen.has(String(m.id))) continue;
    seen.add(String(m.id));
    out.push(m);
  }
  return out;
}
