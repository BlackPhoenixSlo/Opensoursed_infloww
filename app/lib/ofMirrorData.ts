"use client";


import { useEffect, useMemo, useRef, useState, type RefObject } from "react";
import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { useSearchParams } from "next/navigation";
import { useScope } from "@/contexts/ScopeContext";
import type { OFChatItem, OFUserMini } from "@/lib/relay";
import { proxyImage } from "@/lib/mediaUrl";
import { basePage, CHAT_VAULT, HOME_VAULT, homeDraft, MASS_VAULT, VAULT_DIALOG } from "@/lib/ofMirrorRow";
import { loadDraft } from "@/lib/ofMirrorPost";
import { loadVaultPick, vaultPickKey } from "@/lib/ofMirrorPick";
import { ofMeQuery } from "@/lib/ofMirrorIdentity";
import { vaultListsPath, viewOf } from "@/lib/ofMirrorVault";
import { message } from "@/lib/ofMirrorWrites";
import { nextFeedOffset, pageRows, POSTS_PAGE, rowsOf, uniqueRows } from "@/lib/ofMirrorPaging";
import { chatsQuery, chatsRequest, chatsView } from "@/lib/ofMirrorChats";
import { fanIdFromParam } from "@/lib/fanId";
import { useChatList } from "@/hooks/useChatList";
import { INTENT_EVENTS, scrollGesture, type IntentEvent, type ListCaller } from "@/hooks/chatListLoadMore";
import { UNREAD_PREFETCH_TIERS, useUnreadMessagesPrefetch } from "@/hooks/useUnreadMessagesPrefetch";
import { useChatMessages } from "@/hooks/useChatMessages";
import { useChatPinned } from "@/hooks/useChatPinned";
import { useFanChatMedia } from "@/hooks/useFanChatMedia";
import { applyGallery, galleryRequest, galleryTab, useThreadFind } from "@/lib/ofMirrorThread";
import { applyProfile, applyProfileStatus, applyRecent, mediaKind, ofKind, PROFILE_CHANGE } from "@/lib/ofMirrorProfile";
import { restore, sameId, setText, toggleTile, type Part } from "@/lib/ofMirrorDom";
import { applyChatLinks, applyChats, applyChatsMore, applyChatsStatus, applyThread, keepThreadScroll, OLDER_PX, THREAD_BOX, threadScroll } from "@/lib/ofMirrorDataChats";
import { applyListSort, applyVaultAll, applyVaultLists, applyVaultMedia, applyVaultStatus } from "@/lib/ofMirrorDataVault";
import { applyColumnStatus, applyFansTabs, applyLabels, applyListTabs, applyListUsers, applyUserLists, hideEmpty, LABELS_COLUMN, LIST_POSTS, listPostsPath, LISTS_COLUMN, postTypeOf, subscribersPath, USERS_COLUMN, type UserList } from "@/lib/ofMirrorDataLists";
import { CHATS_MORE_PX, CHATS_PAGE, chatPath, feedStatus, galleryStalled, isVaultPage, markerPagesQuery, mirrorQuery, MORE_PX, offsetPagesQuery, pendingPartners, STORIES_FEED, STREAMS_FEED, TRANSACTIONS, TRANSACTIONS_PAGE, usePageUsers, USER_LISTS, useRevalidate, vaultMediaOf, vaultPagesQuery } from "@/lib/ofMirrorDataQueries";
import { mirrorDataOf, type MirrorData } from "@/lib/ofMirrorDataOf";
import { QUEUE, TEMPLATES, useAgencyZone, type MirrorPost, type Month, type Template } from "@/lib/ofMirrorFeedsShared";
import { applyColumnPosts, applyFeedStatus, applyHome, applyPosts, applyProfileMedia, COLUMN_FEED } from "@/lib/ofMirrorFeedsPosts";
import { applyPromotions, applyStories } from "@/lib/ofMirrorFeedsStrip";
import { applyEvents, applyQueue, eventsRoute, QUEUE_CHANGE, queueMonth } from "@/lib/ofMirrorFeedsSchedule";
import { applyNotificationCounts, applyNotifications, applyNotificationsStatus, NOTIFICATION_COUNTS, NOTIFICATIONS, notificationsRoute, relatedUserOf } from "@/lib/ofMirrorFeedsNotifications";
import { useMarkNotifsReadOnOpen } from "@/lib/ofMirrorNotifsRead";
import { applyPastStreams, applyPayouts, applyStatementsStatus, applyTransactions } from "@/lib/ofMirrorFeedsStatements";
export { nextFeedOffset, nextMarker, nextOffset, pageRows, POSTS_PAGE, rowsOf, uniqueRows } from "@/lib/ofMirrorPaging";
export { plain } from "@/lib/ofMirrorDom";
export { mirrorQuery } from "@/lib/ofMirrorDataQueries";

export const DATA_PAGES: Record<string, Part[]> = {
  "messages/index": ["chats"],
  messages: ["chats"],
  "messages/chat": ["chats", "thread"],
  "vault/index": ["vaultLists", "vaultMedia"],
  vault: ["vaultLists", "vaultMedia"],
  "vault/list": ["vaultLists", "vaultMedia"],
  "new-post/index": ["promotions", "events"],
  "new-post": ["promotions", "events"],
  [VAULT_DIALOG]: ["promotions", "events", "vaultLists", "vaultMedia"],
  [CHAT_VAULT]: ["chats", "thread", "vaultLists", "vaultMedia"],
  [MASS_VAULT]: ["vaultLists", "vaultMedia"],
  "messages/chat/gallery": ["chats", "chatList", "gallery"],
  "messages/chat/pinned": ["chats", "thread"],
  "collections/index": ["userLists", "listUsers"],
  "collections/user-lists/list": ["userLists", "listUsers"],
  [LIST_POSTS]: ["userLists", "listPosts"],
  "collections/user-lists/subscribers/active": ["userLists", "subscribers"],
  "collections/user-lists/subscriptions": ["userLists", "listRow"],
  "collections/user-lists/subscriptions/active": ["userLists", "listRow"],
  "collections/user-lists/subscriptions/expired": ["userLists", "listRow"],
  "collections/user-lists/subscriptions/attention": ["userLists", "listRow"],
  "collections/user-lists/subscriptions/posts": ["userLists", "listRow"],
  "collections/post-labels/archived": ["labels"],
  "profile/index": ["posts", "profileMedia", "profile", "promotions"],
  profile: ["posts", "profileMedia", "profile", "promotions"],
  "profile/media": ["profileMedia", "profile", "promotions"],
  "collections/bookmarks/all": ["bookmarks"],
  ...Object.fromEntries(Object.keys(QUEUE).map((p) => [p, ["queue"] as Part[]])),
  ...Object.fromEntries(Object.keys(NOTIFICATIONS).map((p) => [p, ["notifications", "notificationCounts", "promotions", "events"] as Part[]])),
  "streaming/dashboard": ["pastStreams"],
  "streaming/dashboard/create": ["promotions", "events"],
  "statements/earnings": ["transactions"],
  "statements/index": ["transactions"],
  "statements/payouts": ["payouts"],
  "statements/referrals": ["referrals"],
  "home/index": ["home", "stories", "promotions", "events"],
  home: ["home", "stories", "promotions", "events"],
  [HOME_VAULT]: ["home", "stories", "promotions", "events", "vaultLists", "vaultMedia"],
};

export const partsOf = (page: string): Part[] => {
  const key = Object.hasOwn(DATA_PAGES, page) ? page : basePage(page);
  return Object.hasOwn(DATA_PAGES, key) ? DATA_PAGES[key] : [];
};

export function applyData(doc: Document, page: string, data: MirrorData, img: (u: string) => string = (u) => u): void {
  restore(doc);
  const parts = partsOf(page);
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
  if (parts.includes("subscribers")) applyFansTabs(doc, data.fansType ?? null);
  if ((parts.includes("listUsers") || parts.includes("listPosts")) && data.list) applyListTabs(doc, data.list, data.postType ?? null);
  if (parts.includes("listPosts") && data.listPostsStatus !== undefined) applyFeedStatus(doc, data.listPostsStatus, COLUMN_FEED);
  if (parts.includes("listPosts") && data.listPosts && data.templates?.post)
    applyColumnPosts(doc, { posts: data.listPosts, tpl: data.templates.post, me: data.me && String(data.me.id), authors: data.authors, more: data.listPostsMore }, img);
  if (parts.includes("labels") && data.labelsStatus !== undefined) applyColumnStatus(doc, LABELS_COLUMN, data.labelsStatus);
  if (parts.includes("labels") && data.labels) applyLabels(doc, data.labels, data.label ?? null);
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

export function useOfData(frameRef: RefObject<HTMLIFrameElement | null>, src: string): void {
  const { accountId } = useScope();
  const params = useSearchParams();
  const chat = params.get("chat");
  const label = params.get("label");
  const page = /^\/of-mirror\/pages\/(.+)\.html$/.exec(src)?.[1] ?? "";
  const parts = partsOf(page);
  const q = (part: Part, path: string | null) => mirrorQuery(accountId, path, parts.includes(part));
  const enc = (v: string | null) => (v ? encodeURIComponent(v) : null);
  const isChats = parts.includes("chats");
  const view = chatsView(params);
  const listQuery = chatsQuery(view);
  // Nothing here marks a chat read.
  const chatList = useChatList({ ...chatsRequest(view), limit: CHATS_PAGE, enabled: isChats && !!accountId });
  useUnreadMessagesPrefetch(chatList.data, chatList.fetchedLive, UNREAD_PREFETCH_TIERS.slice(0, 1));
  const loadMoreChats = useRef(chatList.loadMore);
  loadMoreChats.current = chatList.loadMore;
  const { ids: pageIds, reads: partners, key: partnersKey } = usePageUsers(accountId, chatList.pages ?? [], (c: OFChatItem) => c?.withUser?.id, isChats);
  const known = useRef<{ view: string; users: Record<string, OFUserMini> }>({ view: listQuery, users: {} });
  if (known.current.view !== listQuery) known.current = { view: listQuery, users: {} };
  for (const p of partners) if (p.data && typeof p.data === "object" && !Array.isArray(p.data)) Object.assign(known.current.users, p.data);
  const partnersPending = pendingPartners(pageIds, partners);
  const isGallery = parts.includes("gallery");
  const detail = useQuery(mirrorQuery(accountId, chat && chatPath(chat), parts.includes("thread") || isGallery));
  const fanId = chat ? fanIdFromParam(chat) : null;
  const isPinnedPage = page === "messages/chat/pinned";
  const pinned = useChatPinned(accountId, fanId, isPinnedPage);
  const thread = useChatMessages({ accountId, fanId, enabled: parts.includes("thread") && !isPinnedPage && !!chat && !!accountId });
  const gTab = galleryTab(params);
  const gallery = useFanChatMedia(accountId, fanId, { ...galleryRequest(gTab), enabled: isGallery && !!chat });
  const vaultSearch = viewOf(params).slist;
  const vaultLists = vaultListsPath({ slist: vaultSearch });
  const vault = useQuery(q("vaultLists", vaultLists));
  useRevalidate(accountId, parts.includes("vaultLists") ? vaultLists : null, vault);
  const vaultPage = isVaultPage(page) && parts.includes("vaultMedia");
  const dialogMedia = !vaultPage && parts.includes("vaultMedia") ? vaultMediaOf(params) : null;
  const vaultMedia = useQuery(q("vaultMedia", dialogMedia));
  useRevalidate(accountId, dialogMedia, vaultMedia);
  const vaultPages = useInfiniteQuery(vaultPagesQuery(accountId, vaultPage ? vaultMediaOf(params) : null));
  const vaultRead = vaultPage ? vaultPages : vaultMedia;
  const lists = useQuery(q("userLists", USER_LISTS));
  const first = rowsOf<UserList>(lists.data)?.[0]?.id;
  const list = params.get("list") ?? ((parts.includes("listUsers") || parts.includes("listPosts")) && first != null ? String(first) : null);
  const usersQuery = params.get("query");
  const members = useQuery(q("listUsers", list && `/api/of/v2/lists/${enc(list)}/users?limit=50${usersQuery ? `&query=${enc(usersQuery)}` : ""}`));
  const postType = postTypeOf(params.get("postType"));
  const listPostsRoute = list && listPostsPath(list, postType);
  const listPosts = useInfiniteQuery(offsetPagesQuery(accountId, listPostsRoute, parts.includes("listPosts")));
  const listPostRows = useMemo(() => uniqueRows(pageRows<MirrorPost>(listPosts.data?.pages)), [listPosts.data]);
  const fansType = params.get("type");
  const subscribers = useQuery(q("subscribers", subscribersPath(fansType)));
  const labels = useQuery(mirrorQuery(accountId, "/api/of/v2/labels", parts.includes("labels") || parts.includes("profile")));
  const ofMeQ = useQuery(ofMeQuery(accountId));
  const ofMe = ofMeQ.data;
  const ofMeStatus = ofMeQ.isError ? message(ofMeQ.error) : ofMeQ.isPending ? null : undefined;
  const meId = ofMe?.id;
  const me = meId != null ? `/api/of/v2/users/${enc(String(meId))}` : null;
  const posts = useInfiniteQuery(markerPagesQuery(accountId, me && `${me}/posts?limit=${POSTS_PAGE}&format=infinite`, parts.includes("posts")));
  const postRows = useMemo(() => uniqueRows(pageRows<MirrorPost>(posts.data?.pages)), [posts.data]);
  const photos = useQuery(q("profileMedia", me && `${me}/posts/photos?limit=24`));
  const videos = useQuery(q("profileMedia", me && `${me}/posts/videos?limit=24`));
  const highlights = useQuery(q("profile", me && `${me}/stories/highlights`));
  const myStories = useQuery(q("stories", me && `${me}/stories`));
  const bookmarks = useQuery(q("bookmarks", "/api/of/v2/posts/bookmarks/all?limit=20"));
  const [month, setMonth] = useState<Month | null>(null);
  const zone = useAgencyZone();
  const queue = useQuery(q("queue", Object.hasOwn(QUEUE, page) ? QUEUE[page].route(month, zone) : null));
  const relatedUser = Object.hasOwn(NOTIFICATIONS, page) ? relatedUserOf(params) : null;
  const notifications = useQuery(q("notifications", notificationsRoute(page, relatedUser)));
  const notificationCounts = useQuery(q("notificationCounts", NOTIFICATION_COUNTS));
  useMarkNotifsReadOnOpen(accountId, page, notifications);
  const newTags = ofMe?.newTagsCount;
  const pastStreams = useQuery(q("pastStreams", me && `${me}/streams?limit=8`));
  const transactions = useInfiniteQuery(offsetPagesQuery(accountId, `${TRANSACTIONS}?limit=${TRANSACTIONS_PAGE}`, parts.includes("transactions")));
  const payouts = useQuery(q("payouts", "/api/of/v2/payouts/requests?limit=20"));
  const referrals = useQuery(q("referrals", "/api/of/v2/payouts/requests/referral?limit=20"));
  const home = useInfiniteQuery(offsetPagesQuery(accountId, `/api/of/v2/posts?limit=${POSTS_PAGE}`, parts.includes("home"), nextFeedOffset));
  const homeRows = useMemo(() => uniqueRows(pageRows<MirrorPost>(home.data?.pages)), [home.data]);
  const stories = useQuery(q("stories", STORIES_FEED));
  const streams = useQuery(q("stories", STREAMS_FEED));
  const feedPages = parts.includes("listPosts") ? (listPosts.data?.pages ?? []).map((p) => rowsOf<MirrorPost>(p) ?? []) : (home.data?.pages ?? []).map((p) => rowsOf<MirrorPost>(p) ?? []);
  const { reads: authorPages, key: authorsKey } = usePageUsers(accountId, feedPages, (p: MirrorPost) => p.author?.id, parts.includes("home") || parts.includes("listPosts"));
  const promotions = useQuery(q("promotions", "/api/of/v2/promotions"));
  const events = useQuery(q("events", eventsRoute(new Date())));
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

  const stmt = parts.includes("transactions") ? transactions : parts.includes("payouts") ? payouts : parts.includes("referrals") ? referrals : null;
  const statementsStatus = stmt ? feedStatus(stmt, need ? template : null) : undefined;
  const data = useMemo<MirrorData>(() => {
    // eslint-disable-next-line react-hooks/refs -- by design, as before mirrorDataOf: known's users are read as the memo runs; the loader reads its ref only when the chat list asks for more
    return mirrorDataOf({ chat, list, label, parts, listQuery, chatList, loadMoreChats: () => void loadMoreChats.current("auto"), pageIds, partners, knownUsers: known.current.users, detail, isPinnedPage, pinned, thread, isGallery, gTab, gallery, vault, vaultSearch, vaultPage, vaultMedia, vaultPages, vaultRead, lists, members, listPostRows, listPosts, need, template, postType, subscribers, fansType, labels, postRows, me, posts, ofMeStatus, photos, videos, ofMe, highlights, bookmarks, queue, zone, notifications, relatedUser, notificationCounts, newTags, pastStreams, transactions, payouts, referrals, statementsStatus, homeRows, home, meId, myStories, stories, streams, authorPages, promotions, events });
    // eslint-disable-next-line react-hooks/exhaustive-deps -- partnersKey and authorsKey stand for partners and authorPages (new arrays each render)
  }, [chat, list, label, postType, listPosts.data, listPosts.error, listPosts.isPending, listPosts.isFetchingNextPage, listPosts.isFetchNextPageError, listPosts.hasNextPage, listPosts.fetchNextPage, parts, chatList.pages, chatList.isPending, chatList.isPlaceholderData, chatList.isError, chatList.error, chatList.isFetchingMore, chatList.hasMore, partnersKey, listQuery, detail.data, thread.data, isPinnedPage, pinned.data, isGallery, gTab, gallery.data, gallery.isPlaceholderData, gallery.isError, gallery.error, gallery.isPending, gallery.isFetchingNextPage, gallery.hasNextPage, gallery.isFetchNextPageError, vault.data, vaultSearch, vaultPage, vaultMedia.data, vaultPages.data, vaultRead.error, vaultRead.isPending, lists.data, lists.error, lists.isPending, members.data, members.error, members.isPending, subscribers.data, subscribers.error, subscribers.isPending, fansType, labels.data, labels.error, labels.isPending, postRows, posts.error, posts.isPending, posts.isFetchingNextPage, posts.isFetchNextPageError, posts.hasNextPage, posts.fetchNextPage, photos.data, photos.error, photos.isPending, videos.data, videos.error, videos.isPending, highlights.data, ofMeStatus, bookmarks.data, queue.data, zone, notifications.data, notifications.error, relatedUser, notificationCounts.data, newTags, pastStreams.data, transactions.data, transactions.isFetchingNextPage, transactions.isFetchNextPageError, transactions.error, transactions.hasNextPage, transactions.fetchNextPage, payouts.data, referrals.data, statementsStatus, homeRows, home.error, home.isPending, home.isFetchingNextPage, home.isFetchNextPageError, home.hasNextPage, home.fetchNextPage, stories.data, streams.data, myStories.data, authorsKey, promotions.data, ofMe, meId, events.data, need, template.data, template.error]);

  useEffect(() => {
    const frame = frameRef.current;
    if (!frame || !partsOf(page).length) return;
    const apply = () => {
      const doc = frame.contentDocument;
      if (!doc?.body) return;
      const m = queueMonth(doc);
      setMonth((was) => (was?.start === m?.start && was?.end === m?.end ? was : m));
      const draft = !accountId ? null : page === VAULT_DIALOG ? accountId : page === HOME_VAULT ? homeDraft(accountId) : null;
      const picked = draft ? loadDraft(window.sessionStorage, draft).media_files.filter((m) => typeof m === "number") : undefined;
      const chatPicked = accountId && chat && page === CHAT_VAULT ? loadVaultPick(window.sessionStorage, vaultPickKey(accountId, CHAT_VAULT, chat)).ids : undefined;
      const massPicked = accountId && page === MASS_VAULT ? loadVaultPick(window.sessionStorage, vaultPickKey(accountId, MASS_VAULT)).ids : undefined;
      const dialog = page === VAULT_DIALOG || page === HOME_VAULT || page === CHAT_VAULT || page === MASS_VAULT;
      const real: MirrorData = accountId ? data : {};
      const shown: MirrorData = dialog ? { ...real, vaultLists: real.vaultLists ?? [], vaultAll: real.vaultAll ?? {}, vaultMedia: real.vaultMedia ?? [] } : real;
      const held = isVaultPage(page) ? [...doc.querySelectorAll<HTMLElement>("[data-oi-media].selected")].map((t) => t.dataset.oiMedia) : [];
      const was = threadScroll(doc, chat);
      const noted = doc.getElementById("oi-note");
      const notedMsg = noted?.previousElementSibling?.getAttribute("data-oi-msg");
      const list = doc.querySelector<HTMLElement>(".b-chats__scroller");
      if (list && list.dataset.oiView !== listQuery) {
        list.dataset.oiView = listQuery;
        list.scrollTop = 0;
      }
      applyData(doc, page, accountId ? { ...shown, picked: picked ?? chatPicked ?? massPicked } : shown, (u) => proxyImage(u, accountId));
      if (shown.thread && chat && partsOf(page).includes("thread")) keepThreadScroll(doc, chat, was);
      if (noted && notedMsg && !noted.isConnected) doc.querySelector(`[data-oi-msg="${CSS.escape(notedMsg)}"]`)?.after(noted);
      for (const id of held) {
        const tile = doc.querySelector(`[data-oi-media="${id}"]`);
        if (tile) toggleTile(tile, true);
      }
    };
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

  const { hasNextPage, isFetchingNextPage, fetchNextPage } = vaultPages;
  useEffect(() => {
    const frame = frameRef.current;
    if (!frame || !vaultPage || !hasNextPage || isFetchingNextPage) return;
    const near = (el: Element | null | undefined) => !!el && el.scrollHeight > 0 && el.scrollTop + el.clientHeight >= el.scrollHeight - MORE_PX;
    const check = (el?: Element | null) => {
      const d = frame.contentDocument;
      if (d?.querySelector("[data-oi-media]") && near(el ?? d.scrollingElement)) void fetchNextPage({ cancelRefetch: false });
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

  const chatGesture = useRef<{ doc: Document | null; view: string; fresh: ReturnType<typeof scrollGesture>; armed: boolean } | null>(null);
  const gestureView = JSON.stringify([src, accountId, listQuery]);
  const chatsNext = isChats && !!accountId && chatList.hasMore && !chatList.isFetchingMore && !partnersPending;
  useEffect(() => {
    const frame = frameRef.current;
    if (!frame || !isChats || !accountId) return;
    const check = (caller: ListCaller): boolean => {
      const d = frame.contentDocument;
      const win = d?.defaultView;
      const box = d?.querySelector<HTMLElement>(".b-chats__scroller");
      const rows = box?.querySelectorAll<HTMLElement>("[data-oi-chat]");
      const last = rows?.[rows.length - 1];
      if (!win || !box || !last || !box.checkVisibility?.()) return false;
      const clips = /(auto|scroll)/.test(win.getComputedStyle(box).overflowY);
      const end = Math.min(win.innerHeight, clips ? box.getBoundingClientRect().bottom : win.innerHeight);
      if (last.getBoundingClientRect().bottom - end > CHATS_MORE_PX) return false;
      void loadMoreChats.current(caller);
      return true;
    };
    const onScroll = () => {
      const gesture = chatGesture.current;
      if (chatsNext && gesture?.armed && check("scroll")) gesture.armed = false;
    };
    const onIntent = (e: Event) => {
      const target = e.target as Element | null;
      if (!target?.closest?.(".b-chats__scroller")) return;
      const gesture = chatGesture.current;
      if (gesture?.fresh(e as IntentEvent, performance.now())) gesture.armed = true;
      onScroll();
    };
    const onPointerDown = (e: Event) => {
      const target = e.target as Element | null;
      const gesture = chatGesture.current;
      if (gesture && target?.matches?.(".b-chats__scroller")) gesture.armed = true;
    };
    let doc: Document | null = null;
    const listen = (d: Document | null, on: boolean) => {
      const f = on ? "addEventListener" : "removeEventListener";
      d?.[f]("scroll", onScroll, true);
      d?.[f]("pointerdown", onPointerDown, true);
      for (const k of INTENT_EVENTS) d?.[f](k, onIntent, true);
    };
    const attach = () => {
      listen(doc, false);
      doc = frame.contentDocument;
      if (chatGesture.current?.doc !== doc || chatGesture.current.view !== gestureView) {
        chatGesture.current = { doc, view: gestureView, fresh: scrollGesture(), armed: false };
      }
      listen(doc, true);
      if (chatsNext) check("autofill");
    };
    if (frame.contentDocument?.readyState === "complete") attach();
    frame.addEventListener("load", attach);
    return () => {
      frame.removeEventListener("load", attach);
      listen(doc, false);
    };
  }, [frameRef, isChats, accountId, gestureView, chatsNext, data]);

  const { hasOlder, isLoadingOlder, loadOlder, olderFailed } = thread;
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
      // No auto-check on attach after a failed page: it would re-fire the failure each time loading settles.
      if (!olderFailed) check();
    };
    if (frame.contentDocument?.readyState === "complete") attach();
    frame.addEventListener("load", attach);
    return () => {
      frame.removeEventListener("load", attach);
      doc?.removeEventListener("scroll", check, true);
    };
  }, [frameRef, src, olderNext, olderFailed, loadOlder, data]);

  const galleryNext = isGallery && !!gallery.hasNextPage && !gallery.isFetchingNextPage && !gallery.isPlaceholderData && !gallery.isFetchNextPageError && !galleryStalled(gallery.data?.pages ?? []);
  const fetchGallery = gallery.fetchNextPage;
  const refetchGallery = gallery.refetch;
  const galleryMoreFailed = gallery.isFetchNextPageError;
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

  useThreadFind(frameRef, src, (page === "messages/chat" || page === "messages/chat/state-header-menu" || isPinnedPage) && !!accountId, accountId, chat, isPinnedPage ? null : params.get("firstId"), isPinnedPage ? NO_PAGING : thread, data, isPinnedPage);
}

const NO_PAGING = { hasOlder: false, loadOlder: async () => ({ added: 0, hasMore: false }) };
