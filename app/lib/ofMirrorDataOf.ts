"use client";


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
  chat?: string | null;
  list?: string | null;
  chats?: OFChatItem[];
  chatsStatus?: string | null;
  listQuery?: string;
  chatsMore?: MorePages;
  thread?: { fan: OFUserMini | null; messages: OFMessage[] };
  chatFan?: OFUserMini | null;
  pinnedCount?: number;
  gallery?: GalleryData;
  vaultLists?: VaultList[];
  vaultAll?: Partial<VaultList>;
  vaultSort?: string;
  vaultSearch?: string | null;
  vaultStatus?: string | null;
  vaultMedia?: (VaultMedia & { _ai?: VaultAiFields })[];
  picked?: (number | string)[];
  userLists?: UserList[];
  userListsStatus?: string | null;
  listUsers?: OFUserMini[];
  listPosts?: MirrorPost[];
  listPostsStatus?: string | null;
  listPostsMore?: MorePages;
  postType?: string | null;
  subscribers?: OFUserMini[];
  fansType?: string | null;
  usersStatus?: string | null;
  labels?: PostLabel[];
  labelsStatus?: string | null;
  label?: string | null;
  posts?: MirrorPost[];
  postsStatus?: string | null;
  postsMore?: MorePages;
  profileMedia?: MediaPost[];
  profileMediaStatus?: string | null;
  profile?: MirrorProfile;
  bookmarks?: MirrorPost[];
  queue?: QueueItem[];
  zone?: string;
  notifications?: MirrorNotification[];
  notificationsStatus?: string | null;
  notificationCounts?: { counts: NotificationCounts; tags?: number | null };
  pastStreams?: PastStream[];
  transactions?: Transaction[];
  transactionsMore?: MorePages;
  payouts?: Payout[];
  referrals?: Payout[];
  statementsStatus?: string | null;
  home?: MirrorPost[];
  authors?: Record<string, OFUserMini>;
  homeStatus?: string | null;
  homeMore?: MorePages;
  stories?: StoryUser[];
  streams?: FeedStream[];
  promotions?: Promotion[];
  subscribePrice?: number | null;
  me?: OFUserMini;
  events?: QueueItem[];
  now?: Date;
  templates?: Partial<Record<Template, Element>>;
}

type Read = ReadState & { data?: unknown };
type Paged = ReadState & PagesState;

export interface MirrorDataInputs {
  chat: string | null;
  list: string | null;
  label: string | null;
  parts: Part[];
  listQuery: string;
  chatList: { pages?: OFChatItem[][]; isPending: boolean; isPlaceholderData: boolean; isError: boolean; error: unknown; isFetchingMore: boolean; hasMore: boolean };
  loadMoreChats: () => void;
  pageIds: string[][];
  partners: readonly PartnersRead[];
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
  fansType: string | null;
  labels: Read;
  postRows: MirrorPost[] | undefined;
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

export function mirrorDataOf(inputs: MirrorDataInputs): MirrorData {
  const { chat, list, label, parts, listQuery, chatList, loadMoreChats, pageIds, partners, knownUsers, detail, isPinnedPage, pinned, thread, isGallery, gTab, gallery, vault, vaultSearch, vaultPage, vaultMedia, vaultPages, vaultRead, lists, members, listPostRows, listPosts, need, template, postType, subscribers, fansType, labels, postRows, me, posts, ofMeStatus, photos, videos, ofMe, highlights, bookmarks, queue, zone, notifications, relatedUser, notificationCounts, newTags, pastStreams, transactions, payouts, referrals, statementsStatus, homeRows, home, meId, myStories, stories, streams, authorPages, promotions, events } = inputs;
  const pages = chatList.isPending || chatList.isPlaceholderData ? undefined : chatList.pages;
  const chatRows = pages && chatRowsOf(pages, pageIds, partners, knownUsers);
  const messages = isPinnedPage ? pinned.data : thread.data;
  const [photoPosts, videoPosts] = [rowsOf<MirrorPost>(photos.data), rowsOf<MirrorPost>(videos.data)];
  const opened = (detail.data as OFChatItem | undefined)?.withUser;
  const fan = (opened && chatUser(opened)) ?? chatRows?.find((c) => sameId(c.withUser.id, chat))?.withUser ?? null;
  const status = (r: { isError: boolean; error: unknown; isPending: boolean }) => (r.isError ? message(r.error) : r.isPending ? null : undefined);
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
    listPostsStatus: list ? feedStatus(listPosts, need ? template : null) : feedStatus(lists, null),
    listPostsMore: morePages(listPosts),
    postType,
    subscribers: rowsOf<OFUserMini>(subscribers.data),
    fansType,
    usersStatus: status(people),
    labels: rowsOf<PostLabel>(labels.data),
    labelsStatus: status(labels),
    posts: postRows,
    postsStatus: me ? feedStatus(posts, null) : ofMeStatus,
    postsMore: morePages(posts),
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
    authors: authorPages.some((a) => a.data) ? Object.assign({}, ...authorPages.map((a) => (a.data && typeof a.data === "object" && !Array.isArray(a.data) ? a.data : {}))) : undefined,
    promotions: rowsOf<Promotion>(promotions.data) ?? (Array.isArray((promotions.data as { items?: unknown } | undefined)?.items) ? (promotions.data as { items: Promotion[] }).items : undefined),
    subscribePrice: ofMe?.subscribePrice,
    me: meId != null ? { id: meId, name: ofMe?.name ?? undefined, username: ofMe?.username ?? undefined, avatar: ofMe?.avatar } : undefined,
    events: rowsOf<QueueItem>(events.data),
    templates: need && template.data ? { [need]: template.data } : undefined,
  };
}
