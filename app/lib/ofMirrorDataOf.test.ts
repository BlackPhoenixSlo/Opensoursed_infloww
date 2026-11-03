import { describe, expect, it } from "vitest";
import { mirrorDataOf, type MirrorData, type MirrorDataInputs } from "./ofMirrorDataOf";
import { feedStatus } from "./ofMirrorDataQueries";
import type { OFChatItem } from "./relay";

/** A settled read with nothing in it; `paged` adds an infinite read's next-page state. */
const idle = { data: undefined, isError: false, error: null, isPending: false };
const paged = { ...idle, isFetchingNextPage: false, isFetchNextPageError: false, hasNextPage: false, fetchNextPage: () => undefined };
const pending = { ...idle, isPending: true };
const failed = (text: string) => ({ ...idle, isError: true, error: new Error(text) });

/** useOfData's reads on a page with nothing asked for yet, `over` replacing some. */
function inputs(over: Partial<MirrorDataInputs> = {}): MirrorDataInputs {
  return {
    chat: null,
    list: null,
    label: null,
    parts: [],
    listQuery: "",
    chatList: { pages: undefined, isPending: false, isPlaceholderData: false, isError: false, error: null, isFetchingMore: false, hasMore: false },
    loadMoreChats: () => undefined,
    pageIds: [],
    partners: [],
    knownUsers: {},
    detail: {},
    isPinnedPage: false,
    pinned: {},
    thread: {},
    isGallery: false,
    gTab: "all",
    gallery: { ...idle, isPlaceholderData: false, isFetchingNextPage: false, hasNextPage: false, isFetchNextPageError: false },
    vault: {},
    vaultSearch: null,
    vaultPage: false,
    vaultMedia: {},
    vaultPages: {},
    vaultRead: idle,
    lists: idle,
    members: idle,
    listPostRows: undefined,
    listPosts: paged,
    need: undefined,
    template: idle,
    postType: null,
    subscribers: idle,
    labels: idle,
    postRows: undefined,
    me: null,
    posts: paged,
    ofMeStatus: undefined,
    photos: idle,
    videos: idle,
    ofMe: undefined,
    highlights: {},
    bookmarks: {},
    queue: {},
    zone: "UTC",
    notifications: idle,
    relatedUser: null,
    notificationCounts: {},
    newTags: undefined,
    pastStreams: {},
    transactions: paged,
    payouts: {},
    referrals: {},
    statementsStatus: undefined,
    homeRows: undefined,
    home: paged,
    meId: undefined,
    myStories: {},
    stories: {},
    streams: {},
    authorPages: [],
    promotions: {},
    events: {},
    ...over,
  };
}

/** Only the keys `want` names, so undefined vs null is checked and nothing else. */
const pick = (d: MirrorData, want: Partial<MirrorData>) => Object.fromEntries(Object.keys(want).map((k) => [k, d[k as keyof MirrorData]]));

const CHAT = { withUser: { id: 7, name: "Fan Seven" }, lastMessage: { id: 1, text: "hi" } } as OFChatItem;
const chats = (over: Partial<MirrorDataInputs["chatList"]>) => ({ chatList: { ...inputs().chatList, ...over } });
const TPL = document.createElement("div");

describe("mirrorDataOf: each part's rows, or its status while they are not here", () => {
  it.each<[string, Partial<MirrorDataInputs>, Partial<MirrorData>]>([
    // chats
    ["chats pending", chats({ isPending: true }), { chats: undefined, chatsStatus: null }],
    ["chats error", chats({ isError: true, error: new Error("relay down") }), { chats: undefined, chatsStatus: "relay down" }],
    ["chats empty (a page with no partner ids is never waited on)", { ...chats({ pages: [[]] }), pageIds: [[]], partners: [{ isPending: true }] }, { chats: [], chatsStatus: undefined }],
    ["chat rows named from their page's /users/list", { ...chats({ pages: [[CHAT]] }), pageIds: [["7"]], partners: [{ isPending: false, data: { 7: { id: 7, name: "Seven", username: "seven" } } }] }, { chats: [{ ...CHAT, withUser: { id: 7, name: "Seven", username: "seven" } }], chatsStatus: undefined }],
    // vault
    ["vault pending", { vaultRead: pending }, { vaultMedia: undefined, vaultStatus: null }],
    ["vault error", { vaultRead: failed("no vault") }, { vaultMedia: undefined, vaultStatus: "no vault" }],
    ["vault dialog empty", { vaultMedia: { data: { list: [] } } }, { vaultMedia: [], vaultStatus: undefined }],
    ["Vault page empty (its pages)", { vaultPage: true, vaultPages: { data: { pages: [{ list: [], hasMore: false }] } } }, { vaultMedia: [], vaultStatus: undefined }],
    // lists (no ?list=: the users column and the Posts tab follow the lists)
    ["lists pending", { lists: pending }, { userLists: undefined, userListsStatus: null, usersStatus: null, listPostsStatus: null }],
    ["lists error", { lists: failed("lists down") }, { userLists: undefined, userListsStatus: "lists down", usersStatus: "lists down", listPostsStatus: "lists down" }],
    ["lists empty", { lists: { ...idle, data: { list: [] } } }, { userLists: [], userListsStatus: undefined, usersStatus: undefined, listPostsStatus: undefined }],
    ["an open list: its users and posts, not the lists", { list: "5", lists: pending, members: failed("members down"), listPosts: { ...paged, isPending: true } }, { usersStatus: "members down", listPostsStatus: null }],
    // queue (no status of its own: no data, whether pending or failed, keeps the examples)
    ["queue with no data yet: none, the examples stay", { queue: {} }, { queue: undefined }],
    ["queue empty", { queue: { data: { list: [] } } }, { queue: [] }],
    // notifications
    ["notifications pending", { notifications: pending }, { notifications: undefined, notificationsStatus: null }],
    ["notifications error", { notifications: failed("notes down") }, { notifications: undefined, notificationsStatus: "notes down" }],
    ["notifications empty", { notifications: { ...idle, data: { list: [] } } }, { notifications: [], notificationsStatus: undefined }],
    ["notifications for one user only", { relatedUser: "9", notifications: { ...idle, data: { list: [{ user: { id: 9 } }, { user: { id: 8 } }] } } }, { notifications: [{ user: { id: 9 } }] }],
    // transactions (their status is useOfData's statementsStatus, feedStatus below, passed through as is)
    ["statementsStatus loading (null) passed through, no rows", { statementsStatus: null }, { transactions: undefined, statementsStatus: null }],
    ["statementsStatus error passed through, no rows", { statementsStatus: "earnings down" }, { transactions: undefined, statementsStatus: "earnings down" }],
    ["transactions empty", { transactions: { ...paged, data: { pages: [{ list: [] }] } } }, { transactions: [], transactionsMore: { loading: false, error: null, next: null } }],
    ["transactions' next page failed", { transactions: { ...paged, isFetchNextPageError: true, error: new Error("page 2"), data: { pages: [{ list: [] }] } } }, { transactionsMore: { loading: false, error: "page 2", next: null } }],
    // home
    ["home pending", { home: { ...paged, isPending: true } }, { home: undefined, homeStatus: null }],
    ["home error", { home: { ...paged, isError: true, error: new Error("feed down") } }, { home: undefined, homeStatus: "feed down" }],
    ["home empty", { homeRows: [] }, { home: [], homeStatus: undefined }],
    ["home's next page failing is its own prompt, not the feed's status", { homeRows: [], home: { ...paged, isError: true, isFetchNextPageError: true, error: new Error("p2") } }, { homeStatus: undefined, homeMore: { loading: false, error: "p2", next: null } }],
  ])("%s", (_, over, want) => {
    const d = mirrorDataOf(inputs(over));
    expect(pick(d, want)).toEqual(want);
  });

  it.each<[string, Partial<MirrorDataInputs>, Partial<MirrorData>]>([
    ["a tab switch's placeholder pages are not shown: the loading line", chats({ pages: [[CHAT]], isPlaceholderData: true }), { chats: undefined, chatsStatus: null }],
    ["the first read (no pages yet)", chats({ pages: [[CHAT]], isPending: true }), { chats: undefined, chatsStatus: null }],
    ["a page whose partners are still asked for, none known: waits", { ...chats({ pages: [[CHAT]] }), pageIds: [["7"]], partners: [{ isPending: true }] }, { chats: undefined, chatsStatus: null }],
    ["a page whose partners are still asked for, some known: those show", { ...chats({ pages: [[CHAT]] }), pageIds: [["7"]], partners: [{ isPending: true }], knownUsers: { 7: { id: 7, name: "Known" } } }, { chats: [{ ...CHAT, withUser: { id: 7, name: "Known" } }] }],
  ])("chat list: %s", (_, over, want) => {
    expect(pick(mirrorDataOf(inputs(over)), want)).toEqual(want);
  });

  const loaded = { homeRows: [], listPostRows: [], list: "5" };
  it.each<[string, Partial<MirrorDataInputs>, Partial<MirrorData>]>([
    ["no borrowed row needed: its read is ignored", { ...loaded, template: failed("tpl") }, { homeStatus: undefined, listPostsStatus: undefined, templates: undefined }],
    ["needed and loading: the feeds wait for it", { ...loaded, need: "post", template: pending }, { homeStatus: null, listPostsStatus: null, templates: undefined }],
    ["needed and failed: its error is the feeds'", { ...loaded, need: "post", template: failed("tpl 404") }, { homeStatus: "tpl 404", listPostsStatus: "tpl 404", templates: undefined }],
    ["needed and here: the feeds show, the row is passed on", { ...loaded, need: "post", template: { ...idle, data: TPL } }, { homeStatus: undefined, listPostsStatus: undefined, templates: { post: TPL } }],
    ["here but not needed: not passed on", { ...loaded, template: { ...idle, data: TPL } }, { templates: undefined }],
  ])("`need` gating: %s", (_, over, want) => {
    expect(pick(mirrorDataOf(inputs(over)), want)).toEqual(want);
  });

  it("the chat list's loader calls useOfData's callback when asked, so its ref's current loadMore, not the one at build time", () => {
    const calls: string[] = [];
    const ref = { current: () => calls.push("first") };
    const d = mirrorDataOf(inputs({ ...chats({ hasMore: true }), loadMoreChats: () => void ref.current() }));
    ref.current = () => calls.push("second");
    d.chatsMore!.next!();
    expect(calls).toEqual(["second"]);
  });
});

describe("feedStatus: a paged read's status (Statements' statementsStatus), with or without its borrowed row", () => {
  it.each<[string, Parameters<typeof feedStatus>[0], Parameters<typeof feedStatus>[1], string | null | undefined]>([
    // no borrowed row
    ["pending", pending, null, null],
    ["error", failed("earnings down"), null, "earnings down"],
    ["empty (settled)", idle, null, undefined],
    ["a next page's failure is not the read's", { ...failed("page 2"), isFetchNextPageError: true }, null, undefined],
    // with a borrowed row (Referrals')
    ["read here, row loading: loading", idle, pending, null],
    ["read loading, row here: loading", pending, idle, null],
    ["row failed: its error", idle, failed("tpl 404"), "tpl 404"],
    ["both failed: the read's error", failed("referrals down"), failed("tpl 404"), "referrals down"],
    ["both here (empty): shown", idle, idle, undefined],
  ])("%s", (_, q, tpl, want) => {
    expect(feedStatus(q, tpl)).toBe(want);
  });
});
