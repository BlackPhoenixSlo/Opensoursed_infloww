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
 * The code lives in leaves (ofMirrorDom, ofMirrorData{Chats,Vault,Lists,Queries,Of}); this module keeps the page map,
 * applyData and useOfData, and re-exports the rest, so its importers read every name from here as before.
 */

import { useEffect, useMemo, useRef, useState, type RefObject } from "react";
import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { useSearchParams } from "next/navigation";
import { useScope } from "@/contexts/ScopeContext";
import type { OFChatItem, OFUserMini } from "@/lib/relay";
import { proxyImage } from "@/lib/mediaUrl";
import { basePage, CHAT_VAULT, HOME_VAULT, homeDraft, MASS_VAULT, VAULT_DIALOG } from "@/lib/ofMirrorRow";
import { loadDraft } from "@/lib/ofMirrorPost";
import { loadVaultPick, vaultPickKey } from "@/lib/ofMirrorChat";
import { ofMeQuery } from "@/lib/ofMirrorIdentity";
import { vaultListsPath, viewOf } from "@/lib/ofMirrorVault";
import { message } from "@/lib/ofMirrorWrites";
import { nextFeedOffset, pageRows, POSTS_PAGE, rowsOf, uniqueRows } from "@/lib/ofMirrorPaging";
import { chatsQuery, chatsRequest, chatsView } from "@/lib/ofMirrorChats";
import { fanIdFromParam } from "@/lib/fanId";
import { useChatList } from "@/hooks/useChatList";
import { UNREAD_PREFETCH_TIERS, useUnreadMessagesPrefetch } from "@/hooks/useUnreadMessagesPrefetch";
import { useChatMessages } from "@/hooks/useChatMessages";
import { useChatPinned } from "@/hooks/useChatPinned";
import { useFanChatMedia } from "@/hooks/useFanChatMedia";
import { applyGallery, galleryRequest, galleryTab, useThreadFind } from "@/lib/ofMirrorThread";
import { applyProfile, applyProfileStatus, applyRecent, mediaKind, ofKind, PROFILE_CHANGE } from "@/lib/ofMirrorProfile";
// The leaves this module's code was cut into, and ofMirrorFeeds' (read directly, never through the ofMirrorFeeds barrel).
import { restore, sameId, setText, toggleTile, type Part } from "@/lib/ofMirrorDom";
import { applyChatLinks, applyChats, applyChatsMore, applyChatsStatus, applyThread, keepThreadScroll, OLDER_PX, THREAD_BOX, threadScroll } from "@/lib/ofMirrorDataChats";
import { applyListSort, applyVaultAll, applyVaultLists, applyVaultMedia, applyVaultStatus } from "@/lib/ofMirrorDataVault";
import { applyColumnStatus, applyLabels, applyListTabs, applyListUsers, applyUserLists, hideEmpty, LABELS_COLUMN, LIST_POSTS, listPostsPath, LISTS_COLUMN, postTypeOf, USERS_COLUMN, type UserList } from "@/lib/ofMirrorDataLists";
import { CHATS_MORE_PX, CHATS_PAGE, chatPath, feedStatus, galleryStalled, isVaultPage, markerPagesQuery, mirrorQuery, MORE_PX, offsetPagesQuery, pendingPartners, STORIES_FEED, STREAMS_FEED, TRANSACTIONS, TRANSACTIONS_PAGE, usePageUsers, USER_LISTS, useRevalidate, vaultMediaOf, vaultPagesQuery } from "@/lib/ofMirrorDataQueries";
import { mirrorDataOf, type MirrorData } from "@/lib/ofMirrorDataOf";
import { QUEUE, TEMPLATES, useAgencyZone, type MirrorPost, type Month, type Template } from "@/lib/ofMirrorFeedsShared";
import { applyColumnPosts, applyFeedStatus, applyHome, applyPosts, applyProfileMedia, COLUMN_FEED } from "@/lib/ofMirrorFeedsPosts";
import { applyPromotions, applyStories } from "@/lib/ofMirrorFeedsStrip";
import { applyEvents, applyQueue, eventsRoute, QUEUE_CHANGE, queueMonth } from "@/lib/ofMirrorFeedsSchedule";
import { applyNotificationCounts, applyNotifications, applyNotificationsStatus, NOTIFICATION_COUNTS, NOTIFICATIONS } from "@/lib/ofMirrorFeedsNotifications";
import { applyPastStreams, applyPayouts, applyStatementsStatus, applyTransactions } from "@/lib/ofMirrorFeedsStatements";
// Re-exported: what was cut from here (into ofMirrorPaging and the leaves), so its importers still read it from here.
export { nextFeedOffset, nextMarker, nextOffset, pageRows, POSTS_PAGE, rowsOf, uniqueRows } from "@/lib/ofMirrorPaging";
export type { Part } from "@/lib/ofMirrorDom";
export { clock, dayOf, dropClass, duration, fill, fillGrid, fillSlot, handleOf, htmlLines, linkUser, make, nameOf, objectOf, own, photoGrid, plain, restore, setAttr, setAvatar, setClass, setIcon, setText, stamp, toggleTile, track, userHref, valid } from "@/lib/ofMirrorDom";
export { bubbleClass, chatMedia, chatMediaTemplate, isPurchaseCard, isTipMessage, keepThreadScroll, paymentState, THREAD_BOX, threadScroll, type ThreadScroll } from "@/lib/ofMirrorDataChats";
export { LIST_POSTS, LIST_TABS, listPostsPath, listSubline, POST_TYPES, postTypeOf, type PostLabel, type UserList } from "@/lib/ofMirrorDataLists";
export { CHATS_PAGE, chatPath, chatRowsOf, chatUser, GALLERY_EMPTY_CAP, galleryItems, galleryStalled, isVaultPage, markerPagesQuery, mirrorQuery, nextVaultOffset, offsetPagesQuery, pendingPartners, relatedOnly, STORIES_FEED, STREAMS_FEED, TRANSACTIONS, TRANSACTIONS_PAGE, USER_LISTS, usersListPath, useRevalidate, VAULT_LISTS, vaultMediaOf, vaultPageMedia, vaultPagesQuery, withChatUsers } from "@/lib/ofMirrorDataQueries";
export type { MirrorData } from "@/lib/ofMirrorDataOf";

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

export const partsOf = (page: string): Part[] => {
  const key = Object.hasOwn(DATA_PAGES, page) ? page : basePage(page);
  return Object.hasOwn(DATA_PAGES, key) ? DATA_PAGES[key] : [];
};

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
    // eslint-disable-next-line react-hooks/refs -- by design, as before mirrorDataOf: known's users are read as the memo runs; the loader reads its ref only when the chat list asks for more
    return mirrorDataOf({ chat, list, label, parts, listQuery, chatList, loadMoreChats: () => void loadMoreChats.current(), pageIds, partners, knownUsers: known.current.users, detail, isPinnedPage, pinned, thread, isGallery, gTab, gallery, vault, vaultSearch, vaultPage, vaultMedia, vaultPages, vaultRead, lists, members, listPostRows, listPosts, need, template, postType, subscribers, labels, postRows, me, posts, ofMeStatus, photos, videos, ofMe, highlights, bookmarks, queue, zone, notifications, relatedUser, notificationCounts, newTags, pastStreams, transactions, payouts, referrals, statementsStatus, homeRows, home, meId, myStories, stories, streams, authorPages, promotions, events });
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
