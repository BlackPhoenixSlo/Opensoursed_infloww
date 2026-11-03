"use client";

/**
 * What a mirror page shows (MirrorData), built from useOfData's reads: mirrorDataOf is the body of its memo, cut from
 * ofMirrorData (which re-exports MirrorData), a pure function of plain values (the memo reads its refs and passes their
 * values, and the chat list's next page as a callback that reads its ref when called), so a table test can feed it plain
 * reads.
 */

import type { OFChatItem, OFMessage, OFUserMini, VaultAiFields, VaultList, VaultMedia, VaultMediaResp } from "@/lib/relay";
import type { OfMe } from "@/lib/ofMe";
import { message } from "@/lib/ofMirrorWrites";
import { pageRows, rowsOf } from "@/lib/ofMirrorPaging";
import type { GalleryData, GalleryTab } from "@/lib/ofMirrorThread";
import type { Highlight, MediaPost, MirrorProfile, ProfileUser } from "@/lib/ofMirrorProfile";
import { sameId, type MorePages, type Part } from "@/lib/ofMirrorDom";
import { chatRowsOf, chatUser, feedStatus, galleryItems, galleryStalled, morePages, relatedOnly, vaultPageMedia, type PagesState, type PartnersRead, type ReadState } from "@/lib/ofMirrorDataQueries";
import type { PostLabel, UserList } from "@/lib/ofMirrorDataLists";
import type { MirrorPost, QueueItem, Template } from "@/lib/ofMirrorFeedsShared";
import { stripUsers, type FeedStream, type Promotion, type StoryEntry, type StoryUser } from "@/lib/ofMirrorFeedsStrip";
import type { MirrorNotification, NotificationCounts } from "@/lib/ofMirrorFeedsNotifications";
import type { PastStream, Payout, Transaction } from "@/lib/ofMirrorFeedsStatements";

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

/** A read as mirrorDataOf looks at it: TanStack's query result, or a test's plain object. */
type Read = ReadState & { data?: unknown };
/** An offset- or marker-paged read: its status, and its next page (morePages). */
type Paged = ReadState & PagesState;

/** useOfData's reads and the values it derives from the page and its URL: everything mirrorDataOf reads. */
export interface MirrorDataInputs {
  chat: string | null;
  list: string | null;
  label: string | null;
  parts: Part[];
  listQuery: string;
  chatList: { pages?: OFChatItem[][]; isPending: boolean; isPlaceholderData: boolean; isError: boolean; error: unknown; isFetchingMore: boolean; hasMore: boolean };
  /** Ask for the chat list's next page (useOfData's callback: it reads its ref when the loader asks, never at build time). */
  loadMoreChats: () => void;
  pageIds: string[][];
  partners: readonly PartnersRead[];
  /** The partners this view has resolved so far, by id (useOfData's ref's value, read when the memo runs). */
  knownUsers: Record<string, OFUserMini>;
  detail: { data?: unknown };
  isPinnedPage: boolean;
  pinned: { data?: OFMessage[] };
  thread: { data?: OFMessage[] };
  isGallery: boolean;
  gTab: GalleryTab;
  gallery: ReadState & { data?: { pages: { list?: unknown[] }[] }; isPlaceholderData: boolean; isFetchingNextPage: boolean; hasNextPage?: boolean; isFetchNextPageError: boolean };
  vault: { data?: unknown };
  vaultSearch: string | null;
  vaultPage: boolean;
  vaultMedia: { data?: unknown };
  vaultPages: { data?: { pages: VaultMediaResp[] } };
  vaultRead: ReadState;
  lists: Read;
  members: Read;
  listPostRows: MirrorPost[] | undefined;
  listPosts: Paged;
  need: Template | undefined;
  template: ReadState & { data?: Element | null };
  postType: string | null;
  subscribers: Read;
  labels: Read;
  postRows: MirrorPost[] | undefined;
  /** The Creator's /users/<id> path (null: their id is not in yet). */
  me: string | null;
  posts: Paged;
  ofMeStatus: string | null | undefined;
  photos: Read;
  videos: Read;
  ofMe: OfMe | undefined;
  highlights: { data?: unknown };
  bookmarks: { data?: unknown };
  queue: { data?: unknown };
  zone: string;
  notifications: Read;
  relatedUser: string | null;
  notificationCounts: { data?: unknown };
  newTags: number | null | undefined;
  pastStreams: { data?: unknown };
  transactions: PagesState & { data?: { pages: unknown[] } };
  payouts: { data?: unknown };
  referrals: { data?: unknown };
  statementsStatus: string | null | undefined;
  homeRows: MirrorPost[] | undefined;
  home: Paged;
  meId: OfMe["id"] | undefined;
  myStories: { data?: unknown };
  stories: { data?: unknown };
  streams: { data?: unknown };
  authorPages: readonly { data?: unknown }[];
  promotions: { data?: unknown };
  events: { data?: unknown };
}

/** The page's MirrorData from useOfData's reads (its memo's body): each part's rows, or its status while they are not here. */
export function mirrorDataOf(inputs: MirrorDataInputs): MirrorData {
  const { chat, list, label, parts, listQuery, chatList, loadMoreChats, pageIds, partners, knownUsers, detail, isPinnedPage, pinned, thread, isGallery, gTab, gallery, vault, vaultSearch, vaultPage, vaultMedia, vaultPages, vaultRead, lists, members, listPostRows, listPosts, need, template, postType, subscribers, labels, postRows, me, posts, ofMeStatus, photos, videos, ofMe, highlights, bookmarks, queue, zone, notifications, relatedUser, notificationCounts, newTags, pastStreams, transactions, payouts, referrals, statementsStatus, homeRows, home, meId, myStories, stories, streams, authorPages, promotions, events } = inputs;
  // A tab, sort or search switch shows the loading line, not the previous view's rows (useChatList keeps them meanwhile).
  const pages = chatList.isPending || chatList.isPlaceholderData ? undefined : chatList.pages;
  // A page's rows wait for its partners (no flash of bare ids); a failed /users/list shows them as they are.
  const chatRows = pages && chatRowsOf(pages, pageIds, partners, knownUsers);
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
    chatsMore: { loading: chatList.isFetchingMore, error: null, next: chatList.hasMore ? loadMoreChats : null },
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
}
