import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it, vi } from "vitest";
import { applyData, chatRowsOf, chatUser, DATA_PAGES, LIST_POSTS, listPostsPath, listSubline, pendingPartners, isVaultPage, markerPagesQuery, mirrorQuery, postTypeOf, nextFeedOffset, nextMarker, nextOffset, nextVaultOffset, partsOf, rowsOf, toggleTile, pageRows, uniqueRows, usersListPath, vaultMediaOf, vaultPageMedia, vaultPagesQuery, withChatUsers, type MirrorData } from "./ofMirrorData";
import { feedTime, notificationText, NOTIFICATIONS, ofMoney, queueDay, queueMonth, queueTypes, TEMPLATES, zoneNote, type MirrorNotification, type MirrorPost, type PastStream, type Payout, type QueueItem, type Transaction } from "./ofMirrorFeeds";
import { relay, type OFChatItem, type OFMessage, type OFUserMini, type VaultList, type VaultMedia, type VaultMediaResp } from "./relay";
import { bindWrites, NOT_YET, READ_ONLY } from "./ofMirrorWrites";
import { applyIdentity } from "./ofMirrorIdentity";
import type { MediaPost } from "./ofMirrorProfile";

const capture = (p: string) => readFileSync(resolve(__dirname, `../public/of-mirror/pages/${p}.html`), "utf8");
const load = (p: string) => {
  document.documentElement.innerHTML = capture(p);
  return document;
};
/** Not inside a hidden example. */
const visible = (el: Element) => !el.closest("[style*='display:none']");
const shown = (doc: Document, sel: string) => [...doc.querySelectorAll(sel)].filter(visible);
const texts = (doc: Document, sel: string) => shown(doc, sel).map((e) => e.textContent?.trim());
/** Run `fn` at the fixtures' "now", 2026-10-10 14:05 local: OF's feed times (feedTime) then read as the expectations say. */
const atFixtureNow = (fn: () => void) => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-10-10T14:05:00"));
  try {
    fn();
  } finally {
    vi.useRealTimers();
  }
};
const PLACEHOLDER = /Fan \d|@fan\d|Lorem|List \d/;

const fan = (id: number, name: string, username: string) => ({ id, name, username, avatar: `https://cdn.example/${username}.jpg` });
const CHATS: OFChatItem[] = [
  { withUser: fan(101, "Alpha One", "alpha"), lastMessage: { id: 1, text: "<p>hey there</p>", createdAt: "2026-10-10T10:00:00Z" }, unreadMessagesCount: 2 },
  { withUser: fan(102, "Beta Two", "beta"), lastMessage: { id: 2, text: "see you", createdAt: "2026-10-09T10:00:00Z" } },
  { withUser: fan(103, "Gamma Three", "gamma"), lastMessage: { id: 3, text: "", mediaCount: 1, createdAt: "2026-10-08T10:00:00Z" } },
];
const msg = (id: number, from: number, text: string, at: string) => ({ id, text, fromUser: { id: from }, createdAt: at, media: [] }) as OFMessage;
// Newest first, as the relay sends them.
const MESSAGES = [
  msg(4, 1, "fourth from me", "2026-10-10T09:03:00Z"),
  msg(3, 102, "third from fan", "2026-10-10T09:02:00Z"),
  msg(2, 1, "<p>second from me</p>", "2026-10-09T09:01:00Z"),
  msg(1, 102, "first from fan", "2026-10-09T09:00:00Z"),
];
const CHAT: MirrorData = { chat: "102", chats: CHATS, thread: { fan: CHATS[1].withUser, messages: MESSAGES } };

describe("the shared mirror query", () => {
  it("one key per model and path; off without a model, a path or the caller's page", () => {
    expect(mirrorQuery("1", "/api/of/v2/lists?limit=50", true)).toMatchObject({ queryKey: ["of-mirror-data", "1", "/api/of/v2/lists?limit=50"], enabled: true });
    expect(mirrorQuery(null, "/x", true).enabled).toBe(false);
    expect(mirrorQuery("1", null, true).enabled).toBe(false);
    expect(mirrorQuery("1", "/x", false).enabled).toBe(false);
  });

  it("vault media follows the page's view, as the tiles' request does", () => {
    expect(vaultMediaOf(new URLSearchParams())).toBe("/api/of/v2/vault/media?limit=24");
    expect(vaultMediaOf(new URLSearchParams("type=video&q=beach"))).toBe("/api/of/v2/vault/media?limit=24&type=video&query=beach");
  });

  it("rowsOf reads {list}, {chats} or a bare array", () => {
    expect(rowsOf([1])).toEqual([1]);
    expect(rowsOf({ list: [2] })).toEqual([2]);
    expect(rowsOf({ chats: [3] })).toEqual([3]);
    expect(rowsOf({})).toBeUndefined();
  });
});

/** OF's own /api2/v2 responses for Messages, captured through the Relay and scrubbed (app/lib/__fixtures__/of). */
const msgFixture = <T,>(name: string): T => JSON.parse(readFileSync(resolve(__dirname, `__fixtures__/of/messages-${name}.json`), "utf8")) as T;

describe("Messages from OF's captured responses (app/lib/__fixtures__/of)", () => {
  const listed = rowsOf<OFChatItem>(msgFixture("chats"))!;
  const users = msgFixture<Record<string, OFUserMini & { displayName?: string }>>("users-list");
  const MODEL = 1001; // the Creator's id in the fixtures
  const img = (u: string) => `/img?u=${u}`;

  it("/chats sends each partner bare (an id); withChatUsers fills in its name, handle and avatar from /users/list", () => {
    expect(listed).toHaveLength(20);
    for (const c of listed) expect(Object.keys(c.withUser).sort()).toEqual(["_view", "id"]);
    const rows = withChatUsers(listed, users);
    for (const c of rows) {
      const u = users[String(c.withUser.id)];
      expect(c.withUser).toMatchObject({ id: c.withUser.id, username: u.username, avatar: u.avatar, name: u.displayName || u.name });
    }
    // OF answers [] when it resolves none; a partner it did not return keeps its id.
    expect(withChatUsers(listed, [])).toEqual(listed);
    const { [String(listed[0].withUser.id)]: _dropped, ...rest } = users;
    expect(withChatUsers(listed, rest)[0]).toBe(listed[0]);
  });

  it("usersListPath: one ids= per partner", () => {
    expect(usersListPath(["2001", "2002"])).toBe("/api/of/v2/users/list?ids=2001&ids=2002");
  });

  it("chatUser: the Creator's rename (displayName) wins over the name; a blank one keeps it", () => {
    const opened = msgFixture<OFChatItem>("chat").withUser as OFUserMini;
    expect(opened.displayName).toBeTruthy();
    expect(chatUser(opened).name).toBe(opened.displayName);
    expect(chatUser({ ...opened, displayName: " " }).name).toBe(opened.name);
  });

  it("messages/index: one row per captured chat, its partner's name, @handle, avatar and last message; no example left", () => {
    const doc = load("messages/index");
    const rows = withChatUsers(listed, users);
    applyData(doc, "messages/index", { chats: rows }, img);
    expect(texts(doc, ".b-chats__item .g-user-name")).toEqual(rows.map((c) => c.withUser.name));
    expect(texts(doc, ".b-chats__item .g-user-username")).toEqual(rows.map((c) => `@${c.withUser.username}`));
    expect(shown(doc, ".b-chats__item__link").map((a) => a.getAttribute("href"))).toEqual(rows.map((c) => `/of-manager/messages/chat?chat=${c.withUser.id}`));
    expect(shown(doc, ".b-chats__item .g-avatar img").map((i) => i.getAttribute("src"))).toEqual(rows.map((c) => img(c.withUser.avatar!)));
    expect(texts(doc, ".b-chats__item__last-message__content")).toEqual(rows.map((c) => (c.lastMessage?.text ?? "").replace(/<[^>]+>/g, "") || (c.lastMessage?.mediaCount ? "Media" : "")));
    expect(shown(doc, ".b-chats__item.m-unread")).toEqual([]); // every captured chat is read
    for (const r of shown(doc, ".b-chats__item")) expect(r.textContent).not.toMatch(PLACEHOLDER);
    expect(shown(doc, ".b-chats__scroller [data-oi-empty]").filter((e) => !(e as HTMLElement).style.display.includes("none"))).toEqual([]);
  });

  it("the Pinned and oldest-first reads list the same rows; Priority and Unread with none show OF's Nothing found", () => {
    for (const name of ["chats-pinned", "chats-oldest"]) {
      const doc = load("messages/index");
      const rows = rowsOf<OFChatItem>(msgFixture(name))!;
      expect(rows.length, name).toBeGreaterThan(0);
      applyData(doc, "messages/index", { chats: rows });
      expect(shown(doc, ".b-chats__item"), name).toHaveLength(rows.length);
    }
    for (const name of ["chats-priority", "chats-unread"]) {
      const doc = load("messages/index");
      expect(msgFixture(name), name).toEqual({ list: [], hasMore: false });
      applyData(doc, "messages/index", { chats: rowsOf<OFChatItem>(msgFixture(name))! });
      expect(texts(doc, ".b-chats__scroller [data-oi-empty] .empty-message"), name).toEqual(["Nothing found"]);
    }
    // OF has no "tips" filter (the page's With Tips tab stays disabled): the Relay passes on its 400.
    expect(JSON.stringify(msgFixture("chats-with-tips"))).toContain("Invalid filter");
  });

  it("messages/chat: the captured thread, oldest first, the Creator's own messages on its side, media in OF's bubble and PPV prices", () => {
    const doc = load("messages/chat");
    const detail = msgFixture<OFChatItem>("chat");
    const messages = rowsOf<OFMessage>(msgFixture("thread"))!;
    const chat = String(detail.withUser.id);
    applyData(doc, "messages/chat", { chat, chats: withChatUsers(listed, users), thread: { fan: chatUser(detail.withUser), messages } }, img);
    expect(texts(doc, ".b-chat__header__title span.g-user-name")).toEqual([detail.withUser.displayName]);
    const sorted = [...messages].sort((a, b) => Date.parse(a.createdAt!) - Date.parse(b.createdAt!));
    const bubbles = shown(doc, ".b-chat__messages-wrapper .b-chat__message");
    expect(bubbles).toHaveLength(messages.length);
    expect(bubbles.map((b) => b.classList.contains("m-from-me"))).toEqual(sorted.map((m) => m.fromUser?.id === MODEL));
    expect(bubbles.map((b) => b.querySelectorAll(".b-chat__message__media").length > 0)).toEqual(sorted.map((m) => (m.media ?? []).some((x) => x.canView !== false && !!x.files)));
    const ppv = sorted.filter((m) => (m.price ?? 0) > 0 && !m.isTip);
    expect(ppv.length).toBeGreaterThan(0);
    expect(bubbles.filter((b) => b.querySelector(".b-chat__message__payment-state"))).toHaveLength(ppv.length);
    for (const b of bubbles) expect(b.textContent).not.toMatch(PLACEHOLDER);
    expect(texts(doc, ".b-chats__item.current .g-user-name")).toEqual([detail.withUser.displayName]);
  });
});

describe("the chat list's rows and their partners (chatRowsOf, pendingPartners)", () => {
  const bare = (id: number) => ({ withUser: { id } }) as OFChatItem;
  const named = (id: number) => ({ id, name: `Name ${id}`, username: `u${id}` });
  const users = (...ids: number[]) => Object.fromEntries(ids.map((id) => [String(id), named(id)]));
  it("a first read waits for its partners (no bare ids): the list is loading", () => {
    expect(chatRowsOf([[bare(1), bare(2)]], [["1", "2"]], [{ isPending: true }], {})).toBeUndefined();
    expect(chatRowsOf([[bare(1), bare(2)]], [["1", "2"]], [{ isPending: false, data: users(1, 2) }], {})!.map((c) => c.withUser.name)).toEqual(["Name 1", "Name 2"]);
  });
  it("a new chat at the top (a new /users/list key) keeps the known rows instead of the whole list loading again", () => {
    const rows = chatRowsOf([[bare(3), bare(1), bare(2)]], [["1", "2", "3"]], [{ isPending: true }], users(1, 2))!;
    expect(rows.map((c) => c.withUser.name)).toEqual(["Name 1", "Name 2"]); // 3 shows once it is named
  });
  it("a later page still asking stops the list there; a chat on two pages shows once", () => {
    const rows = chatRowsOf([[bare(1)], [bare(1), bare(4)]], [["1"], ["1", "4"]], [{ isPending: false, data: users(1) }, { isPending: false, data: users(1, 4) }], {})!;
    expect(rows.map((c) => c.withUser.id)).toEqual([1, 4]);
    expect(chatRowsOf([[bare(1)], [bare(5)]], [["1"], ["5"]], [{ isPending: false, data: users(1) }, { isPending: true }], users(1))!.map((c) => c.withUser.id)).toEqual([1]);
  });
  it("a page with no partner ids (its read disabled, pending for ever in TanStack) never holds the paging", () => {
    expect(pendingPartners([[]], [{ isPending: true }])).toBe(false);
    expect(pendingPartners([["1"], []], [{ isPending: false }, { isPending: true }])).toBe(false);
    expect(pendingPartners([["1"]], [{ isPending: true }])).toBe(true);
    expect(chatRowsOf([[], [bare(1)]], [[], ["1"]], [{ isPending: true }, { isPending: false, data: users(1) }], {})!.map((c) => c.withUser.id)).toEqual([1]);
  });
});

describe("partsOf", () => {
  it("maps pages and their state pages", () => {
    expect(partsOf("messages/index")).toEqual(["chats"]);
    expect(partsOf("messages/state-filter-dropdown")).toEqual(["chats"]);
    expect(partsOf("messages/chat/state-price")).toEqual(["chats", "thread"]);
    expect(partsOf("vault/state-sort-dropdown")).toEqual(["vaultLists", "vaultMedia"]);
    expect(partsOf("vault/list")).toEqual(["vaultLists", "vaultMedia"]);
    expect(partsOf("messages/chat/gallery")).toEqual(["chats", "chatList", "gallery"]);
    expect(partsOf("messages/chat/state-vault")).toEqual(["chats", "thread", "vaultLists", "vaultMedia"]);
    expect(partsOf("messages/send/state-vault")).toEqual(["vaultLists", "vaultMedia"]);
    expect(partsOf("settings/profile")).toEqual([]);
  });

  it("gives My profile and its More-menu state page the posts, its Media tab the media grid, and all three the counts, Recent strip and promotions", () => {
    expect(partsOf("profile/index")).toEqual(["posts", "profileMedia", "profile", "promotions"]);
    expect(partsOf("profile/state-more-menu")).toEqual(["posts", "profileMedia", "profile", "promotions"]);
    expect(partsOf("profile/media")).toEqual(["profileMedia", "profile", "promotions"]);
  });

  it("gives All bookmarks the bookmarks, and the collections page still its user lists", () => {
    expect(partsOf("collections/bookmarks/all")).toEqual(["bookmarks"]);
    expect(partsOf("collections/index")).toEqual(["userLists", "listUsers"]);
    expect(partsOf("collections/user-lists/list/posts")).toEqual(["userLists", "listPosts"]);
  });

  it("gives the six queue pages the queue", () => {
    for (const p of ["queue/index", "queue/state-list-view", "queue/state-tab-messages", "queue/state-tab-streams", "queue/saved-for-later-posts", "queue/saved-for-later-messages"]) {
      expect(partsOf(p)).toEqual(["queue"]);
    }
  });

  it("gives New post its right column, and its vault dialog the vault folders and media too", () => {
    expect(partsOf("new-post/state-vault")).toEqual(["promotions", "events", "vaultLists", "vaultMedia"]);
    expect(partsOf("new-post/index")).toEqual(["promotions", "events"]);
    expect(partsOf("new-post/state-labels")).toEqual(["promotions", "events"]);
  });
});

describe("applyData", () => {
  it.each(Object.keys(DATA_PAGES).filter((p) => p.includes("/")))("%s: no data leaves the page as captured", (p) => {
    const doc = load(p);
    const html = doc.documentElement.innerHTML;
    applyData(doc, p, {});
    expect(doc.documentElement.innerHTML).toBe(html);
  });

  it("messages: one row per chat, linked by fan id, no example text left", () => {
    const doc = load("messages/index");
    const html = doc.documentElement.innerHTML;
    applyData(doc, "messages/index", { chats: CHATS }, (u) => `/img?u=${u}`);
    expect(texts(doc, ".b-chats__item .g-user-name")).toEqual(["Alpha One", "Beta Two", "Gamma Three"]);
    expect(texts(doc, ".b-chats__item .g-user-username")).toEqual(["@alpha", "@beta", "@gamma"]);
    expect(shown(doc, ".b-chats__item__link").map((a) => a.getAttribute("href"))).toEqual([101, 102, 103].map((id) => `/of-manager/messages/chat?chat=${id}`));
    expect(texts(doc, ".b-chats__item__last-message__content")).toEqual(["hey there", "see you", "Media"]);
    expect(shown(doc, ".b-chats__item").map((r) => !!r.querySelector(".b-chats__item__uread-count"))).toEqual([true, false, false]);
    expect(shown(doc, ".b-chats__item").map((r) => r.classList.contains("m-unread"))).toEqual([true, false, false]);
    expect(shown(doc, ".b-chats__item .g-avatar img")[0].getAttribute("src")).toBe("/img?u=https://cdn.example/alpha.jpg");
    for (const r of shown(doc, ".b-chats__item")) expect(r.textContent).not.toMatch(PLACEHOLDER);
    applyData(doc, "messages/index", { chats: CHATS }); // idempotent
    expect(shown(doc, ".b-chats__item")).toHaveLength(3);
    applyData(doc, "messages/index", {});
    expect(doc.documentElement.innerHTML).toBe(html);
  });

  it.each(["messages/chat", "messages/chat/state-price"])("%s: the open chat's header, thread in order on the right sides, and the query on its links", (p) => {
    const doc = load(p);
    applyData(doc, p, CHAT);
    expect(texts(doc, ".b-chat__header__title span.g-user-name")).toEqual(["Beta Two"]);
    expect(doc.title).toMatch(/ Beta Two$/);
    const bubbles = shown(doc, ".b-chat__messages-wrapper .b-chat__message");
    expect(bubbles.map((b) => b.querySelector(".b-chat__message__text-holder")?.textContent)).toEqual(["first from fan", "second from me", "third from fan", "fourth from me"]);
    expect(bubbles.map((b) => b.classList.contains("m-from-me"))).toEqual([false, true, false, true]);
    expect(bubbles.map((b) => !!b.querySelector(".g-avatar"))).toEqual([true, false, true, false]);
    expect(shown(doc, ".b-chat__messages-wrapper .b-chat__item-message")).toHaveLength(2); // two days
    for (const b of bubbles) expect(b.textContent).not.toMatch(PLACEHOLDER);
    expect(texts(doc, ".b-chats__item.current .g-user-name")).toEqual(["Beta Two"]);
    const hrefs = [...doc.querySelectorAll("a[href^='/of-manager/messages/chat/state-price'], a[href='/of-manager/messages/chat?chat=102']")].map((a) => a.getAttribute("href"));
    expect(hrefs.length).toBeGreaterThan(0);
    expect(hrefs.filter((h) => h!.includes("/state-price")).every((h) => h!.endsWith("?chat=102"))).toBe(true);
    applyData(doc, p, {});
    expect(texts(doc, ".b-chat__header__title span.g-user-name")).not.toEqual(["Beta Two"]);
    expect(doc.querySelector("a[href*='?chat=']")).toBeNull();
  });

  it("chat: a media message shows its still in OF's media bubble; no usable URL keeps the Media text", () => {
    const doc = load("messages/chat");
    const photo = { id: 9, type: "photo", width: 600, height: 800, files: { thumb: { url: "https://cdn.example/t.jpg" }, preview: { url: "https://cdn.example/p.jpg" } } };
    const clip = { id: 10, type: "video", files: { full: { url: "https://cdn.example/v.mp4" } } };
    const messages = [
      { ...msg(6, 102, "", "2026-10-10T09:05:00Z"), media: [photo] },
      { ...msg(5, 1, "with a caption", "2026-10-10T09:04:00Z"), media: [photo] },
      { ...msg(7, 102, "", "2026-10-10T09:06:00Z"), media: [clip], mediaCount: 1 },
      ...MESSAGES,
    ] as OFMessage[];
    applyData(doc, "messages/chat", { ...CHAT, thread: { fan: CHATS[1].withUser, messages } }, (u) => `/img?u=${u}`);
    const bubbles = shown(doc, ".b-chat__messages-wrapper .b-chat__message");
    expect(bubbles).toHaveLength(7);
    const [caption, mediaOnly, noUrl] = bubbles.slice(-3);
    for (const b of [caption, mediaOnly]) {
      expect(b.classList.contains("m-has-media")).toBe(true);
      const media = b.querySelectorAll(".b-chat__message__body > .b-chat__message__media-wrapper .b-chat__message__media");
      expect(media).toHaveLength(1);
      const pics = [...media[0].querySelectorAll("img")];
      expect(pics.length).toBeGreaterThan(0);
      for (const pic of pics) expect(pic.getAttribute("src")).toBe("/img?u=https://cdn.example/p.jpg");
      expect(media[0].querySelector("img.b-post__media__img")).not.toBeNull();
      expect(b.querySelector(".m-purchase-chat, .swiper, .post_media__loading")).toBeNull();
    }
    expect(caption.querySelector(".b-chat__message__text-holder")?.textContent).toBe("with a caption");
    expect(mediaOnly.querySelector(".b-chat__message__text-wrapper")).toBeNull();
    expect(noUrl.querySelector(".b-chat__message__media-wrapper")).toBeNull();
    expect(noUrl.querySelector(".b-chat__message__text-holder")?.textContent).toBe("Media");
    for (const b of bubbles) expect(b.textContent).not.toMatch(PLACEHOLDER);
  });

  it("messages: the capture keeps no example chat or message in view; an empty list shows OF's Nothing found", () => {
    for (const p of ["messages/index", "messages/chat", "messages/chat/state-price", "messages/chat/gallery", "messages/chat/pinned"]) {
      const doc = load(p);
      expect(shown(doc, ".b-chats__item"), p).toEqual([]);
      expect(shown(doc, ".b-chat__messages-wrapper .b-chat__message"), p).toEqual([]);
      expect(texts(doc, ".b-chat__header__title span.g-user-name").filter(Boolean), p).toEqual([]);
      applyData(doc, p, { chats: [] });
      expect(texts(doc, ".b-chats__scroller [data-oi-empty] .empty-message"), p).toEqual(["Nothing found"]);
    }
    const doc = load("messages/index");
    applyData(doc, "messages/index", { chats: CHATS });
    expect(shown(doc, ".b-chats__scroller [data-oi-empty]").filter((e) => !(e as HTMLElement).style.display.includes("none"))).toEqual([]);
  });

  it("messages: the chat list reads Loading chats… while the Relay answers, and its error after a failure", () => {
    const doc = load("messages/index");
    const empty = () => doc.querySelector<HTMLElement>(".b-chats__scroller [data-oi-empty] .empty-message > span")!;
    applyData(doc, "messages/index", { chatsStatus: null });
    expect(empty().textContent).toBe("Loading chats…");
    applyData(doc, "messages/index", { chatsStatus: "relay down" });
    expect(empty().textContent).toBe("Could not load chats: relay down");
    expect(empty().style.color).toBe("rgb(255, 69, 69)");
    applyData(doc, "messages/index", { chats: [] });
    expect(empty().textContent).toBe("Nothing found");
  });

  it("chat: a PPV shows OF's payment state (not paid yet, paid); a tip (its own bubble) and a free message none", () => {
    const doc = load("messages/chat");
    const messages = [
      { ...msg(11, 1, "ppv unpaid", "2026-10-10T09:10:00Z"), price: 9, isOpened: false },
      { ...msg(12, 1, "ppv opened", "2026-10-10T09:11:00Z"), price: 15, isOpened: true },
      { ...msg(13, 1, "ppv ledger paid", "2026-10-10T09:12:00Z"), price: 4.5, isPaid: true },
      { ...msg(14, 102, "a tip", "2026-10-10T09:13:00Z"), price: 5, isTip: true },
      msg(15, 1, "free", "2026-10-10T09:14:00Z"),
    ] as OFMessage[];
    applyData(doc, "messages/chat", { ...CHAT, thread: { fan: CHATS[1].withUser, messages } });
    const bubbles = shown(doc, ".b-chat__messages-wrapper .b-chat__message");
    expect(bubbles.map((b) => b.querySelector(".b-chat__message__time .b-chat__message__payment-state")?.textContent?.trim() ?? "")).toEqual([
      "$9 not paid yet",
      "$15 paid",
      "$4.50 paid",
      "",
      "",
    ]);
    expect(bubbles.map((b) => b.classList.contains("m-not-paid-yet"))).toEqual([true, false, false, false, false]);
  });

  it("chat's vault dialog: the Creator's folders link back to the dialog with the chat; none leaves no captured folder", () => {
    const doc = load("messages/chat/state-vault");
    const lists = [{ id: 7, type: "custom", name: "Folder A", hasMedia: true, photosCount: 2 }];
    applyData(doc, "messages/chat/state-vault", { ...CHAT, vaultLists: lists, vaultAll: { photosCount: 2 }, vaultMedia: [] });
    const folders = shown(doc, ".modal .b-rows-lists__item a[href*='list=']");
    expect(folders.map((a) => a.getAttribute("href"))).toEqual(["/of-manager/messages/chat/state-vault?chat=102&list=7"]);
    expect(texts(doc, ".modal .b-rows-lists__item__name")).toEqual(["All media", "Folder A"]);
    applyData(doc, "messages/chat/state-vault", { ...CHAT, vaultLists: [], vaultAll: {}, vaultMedia: [] });
    for (const r of shown(doc, ".modal .b-rows-lists__item")) expect(r.textContent).not.toMatch(PLACEHOLDER);
  });

  it("vault: every vault page shows no example folder or media, only All media and OF's Nothing found", () => {
    for (const page of ["vault/index", "vault/list", "vault/state-add-list", "vault/state-sort-dropdown", "vault/state-lists-sort-dropdown"]) {
      const doc = load(page);
      expect(texts(doc, ".b-rows-lists__item__name"), page).toEqual(["All media"]);
      expect(shown(doc, ".b-photos .b-photos__item"), page).toHaveLength(0);
      expect(texts(doc, ".b-photos .empty-message"), page).toEqual(["Nothing found"]);
      expect(texts(doc, ".l-main-content.m-r-side .g-page-title > span"), page).toEqual(["All media"]);
      expect(doc.body.textContent, page).not.toMatch(PLACEHOLDER);
    }
  });

  it("vault: the grid says Loading media… while the media are asked for, the relay's error after a failure, then goes back", () => {
    const doc = load("vault/index");
    const html = doc.documentElement.innerHTML;
    applyData(doc, "vault/index", { vaultLists: [], vaultStatus: null });
    expect(texts(doc, ".b-photos .empty-message")).toEqual(["Loading media…"]);
    applyData(doc, "vault/index", { vaultLists: [], vaultStatus: "boom" });
    expect(texts(doc, ".b-photos .empty-message")).toEqual(["Could not load media: boom"]);
    expect(doc.querySelector<HTMLElement>(".b-photos .empty-message > span")!.style.color).toBe("rgb(255, 69, 69)");
    applyData(doc, "vault/index", { vaultLists: [], vaultMedia: [] });
    expect(texts(doc, ".b-photos .empty-message")).toEqual(["Nothing found"]);
    applyData(doc, "vault/index", {});
    expect(doc.documentElement.innerHTML).toBe(html);
  });

  it("new post's vault dialog: one tile per media, stamped with its id and dated, and back to the examples", () => {
    const doc = load("new-post/state-vault");
    const html = doc.documentElement.innerHTML;
    const media: VaultMedia[] = [
      { id: 61, type: "photo", createdAt: "2026-10-10T10:00:00Z", files: { thumb: { url: "https://cdn.example/61.jpg" } } },
      { id: 62, type: "video", createdAt: "2026-10-09T10:00:00Z", files: { squarePreview: { url: "https://cdn.example/62.jpg" } } },
      { id: 63, type: "photo", createdAt: "2026-10-08T10:00:00Z", files: { preview: { url: "https://cdn.example/63.jpg" } } },
    ];
    applyData(doc, "new-post/state-vault", { vaultMedia: media }, (u) => `/img?u=${u}`);
    const tiles = shown(doc, ".b-photos .b-photos__item");
    expect(tiles.map((t) => t.getAttribute("data-oi-media"))).toEqual(["61", "62", "63"]);
    expect(tiles.map((t) => t.querySelector(".b-photos__item__img")!.getAttribute("src"))).toEqual([
      "/img?u=https://cdn.example/61.jpg",
      "/img?u=https://cdn.example/62.jpg",
      "/img?u=https://cdn.example/63.jpg",
    ]);
    expect(tiles.map((t) => t.querySelector(".b-element-label.m-timestamp")!.textContent!.trim())).toEqual(["Oct 10", "Oct 9", "Oct 8"]);
    applyData(doc, "new-post/state-vault", {});
    expect(doc.documentElement.innerHTML).toBe(html);
  });

  it("new post's vault dialog: a media with no picture keeps the placeholder; an empty vault leaves no tile", () => {
    const doc = load("new-post/state-vault");
    applyData(doc, "new-post/state-vault", { vaultMedia: [{ id: 64, type: "audio" }] }, (u) => `/img?u=${u}`);
    const tiles = shown(doc, ".b-photos .b-photos__item");
    expect(tiles.map((t) => t.getAttribute("data-oi-media"))).toEqual(["64"]);
    expect(tiles[0].querySelector(".b-photos__item__img")!.getAttribute("src")).toMatch(/^data:/);
    applyData(doc, "new-post/state-vault", { vaultMedia: [] });
    expect(shown(doc, ".b-photos .b-photos__item")).toEqual([]);
  });

  it("new post's vault dialog: the picked media's tile and its checkbox are selected, re-derived on every apply", () => {
    const doc = load("new-post/state-vault");
    const media: VaultMedia[] = [61, 62, 63].map((id) => ({ id, type: "photo" }));
    const selected = () => shown(doc, ".b-photos__item.selected").map((t) => t.getAttribute("data-oi-media"));
    const boxes = () => shown(doc, ".b-photos__item .checkbox-item.selected").map((b) => b.closest("[data-oi-media]")!.getAttribute("data-oi-media"));
    applyData(doc, "new-post/state-vault", { vaultMedia: media, picked: [62] });
    expect(selected()).toEqual(["62"]);
    expect(boxes()).toEqual(["62"]);
    applyData(doc, "new-post/state-vault", { vaultMedia: media, picked: [] });
    expect(selected()).toEqual([]);
    expect(boxes()).toEqual([]);
  });

  it("new post's vault dialog: a picker's tiles are wired; the Vault page's are not", () => {
    const media: VaultMedia[] = [{ id: 61, type: "photo" }];
    let doc = load("new-post/state-vault");
    applyData(doc, "new-post/state-vault", { vaultMedia: media, picked: [] });
    expect(shown(doc, ".b-photos__item[data-oi-media]").map((t) => t.hasAttribute("data-oi-wired"))).toEqual([true]);
    doc = load("vault/index");
    applyData(doc, "vault/index", { vaultMedia: media });
    expect(shown(doc, ".b-photos__item[data-oi-media]").map((t) => t.hasAttribute("data-oi-wired"))).toEqual([false]);
  });

  it("toggleTile marks an unselected tile and its checkbox (true), then unmarks both (false)", () => {
    const doc = load("new-post/state-vault");
    const tile = shown(doc, ".b-photos__item.m-checkbox-control")[0];
    const box = tile.querySelector(".checkbox-item")!;
    expect(toggleTile(tile)).toBe(true);
    expect([tile.classList.contains("selected"), box.classList.contains("selected")]).toEqual([true, true]);
    expect(toggleTile(tile)).toBe(false);
    expect([tile.classList.contains("selected"), box.classList.contains("selected")]).toEqual([false, false]);
  });

  it("collections: one row per list; the list page shows its users", () => {
    const lists = [
      { id: 31, name: "Whales", usersCount: 2 },
      { id: 32, name: "New", usersCount: 1 },
    ];
    let doc = load("collections/index");
    applyData(doc, "collections/index", { userLists: lists });
    expect(texts(doc, ".b-user-lists__list .b-rows-lists__item__name")).toEqual(["Whales", "New"]);
    expect(shown(doc, ".b-user-lists__list a.b-rows-lists__item__text").map((a) => a.getAttribute("href"))).toEqual([
      "/of-manager/collections/user-lists/list?list=31",
      "/of-manager/collections/user-lists/list?list=32",
    ]);
    expect(texts(doc, ".b-user-lists__list .b-content-inside-thumbs")).toEqual(["2 users", "1 user"]);

    doc = load("collections/user-lists/list");
    const people = [fan(201, "Delta Four", "delta"), { id: 202, name: "Echo Five", username: "echo", avatar: null }];
    applyData(doc, "collections/user-lists/list", { list: "31", userLists: lists, listUsers: people });
    expect(texts(doc, ".l-main-content .g-page-title > span")).toEqual(["Whales"]);
    expect(texts(doc, "a.m-current .b-rows-lists__item__name")).toEqual(["Whales"]);
    const cards = shown(doc, ".b-users__item");
    expect(cards.map((c) => c.querySelector(".g-user-name")!.textContent)).toEqual(["Delta Four", "Echo Five"]);
    expect(cards.map((c) => c.querySelector(".g-user-username")!.textContent)).toEqual(["@delta", "@echo"]);
    expect(cards[1].querySelector(".g-avatar__placeholder")!.textContent).toBe(" EF "); // OF's initials: two words, their first letters
    expect(cards[0].querySelector(".g-avatar .g-avatar__placeholder")).toBeNull();
    expect(cards[0].querySelector(".g-avatar .g-avatar__img-wrapper > img")!.getAttribute("src")).toBe("https://cdn.example/delta.jpg");
    for (const c of cards) expect(c.textContent).not.toMatch(PLACEHOLDER);
    expect(cards.map((c) => c.querySelector(".b-list-titles a")?.getAttribute("href"))).toEqual(Array(2).fill("/of-manager/collections/user-lists/list?list=31"));
    // OF's profile links (avatar, name, handle): the user's OF profile, in a new tab.
    expect(cards.map((c) => [...c.querySelectorAll(".b-fans__item__header > a.g-avatar, a.b-username, a.g-user-realname__wrapper")].map((a) => `${a.getAttribute("href")} ${a.getAttribute("target")} ${a.getAttribute("rel")}`))).toEqual(
      ["delta", "echo"].map((h) => Array(3).fill(`https://onlyfans.com/${h} _blank noopener noreferrer`)),
    );
    expect(cards.flatMap((c) => [...c.querySelectorAll("a[href='#']")])).toEqual([]);
    // The header's Send message: New message with this list ticked.
    expect(doc.querySelector('a[aria-label="Send message"]')!.getAttribute("href")).toBe("/of-manager/messages/send?to=31");
  });

  it("collections: each list's subline and avatar stack as OF's UsersList (counts short, empty lists \"empty\")", () => {
    const img = (u: string) => `/img?u=${u}`;
    const lists = [
      {
        id: "tagged",
        name: "Tagged",
        usersCount: 3,
        postsCount: 14093,
        users: [
          { id: 1, name: "Paula", avatar: "https://cdn.example/a1.jpg", avatarThumbs: { c144: "https://cdn.example/a1-144.jpg" } },
          { id: 2, name: "user929", displayName: "" },
          { id: 3, name: "u3" },
        ],
      },
      { id: "purchased", name: "Purchased", usersCount: 1, postsCount: 16, users: [{ id: 4, name: "Marcus, 29, Austin" }] },
      { id: "recent", name: "Recent", usersCount: 0 },
      { id: 31, name: "Whales" },
      { id: 32, name: "One", usersCount: 1, postsCount: 1, users: [] },
    ];
    const doc = load("collections/index");
    applyData(doc, "collections/index", { userLists: lists }, img);
    const rows = shown(doc, ".b-user-lists__list a.b-rows-lists__item__text");
    expect(rows.map((r) => [...r.querySelectorAll(".b-content-inside-thumbs__item")].map((i) => i.textContent))).toEqual([
      [" 3 users ", " 14.1K posts "],
      [" 1 user ", " 16 purchases "],
      [" No new subscribers in the last 24 hours "],
      [" empty "],
      [" 1 user ", " 1 post "],
    ]);
    // At zero posts: Purchased says so, any other list shows its users alone.
    expect([{ id: "purchased", usersCount: 2, postsCount: 0 }, { id: 33, usersCount: 2, postsCount: 0 }].map(listSubline)).toEqual([["2 users", "No purchase"], ["2 users"]]);
    // The stack: between the name and the subline, one 50px avatar per member: picture, else initials, else OF's profile icon.
    const sets = rows.map((r) => r.querySelector(".b-media-set.m-avatars-media-set.ml-2"));
    expect(sets.map((s) => s?.querySelectorAll(":scope > span.g-avatar.m-border-line-theme.m-w50").length ?? 0)).toEqual([3, 1, 0, 0, 0]);
    expect(sets[0]!.previousElementSibling!.classList.contains("b-rows-lists__item__name")).toBe(true);
    expect(sets[0]!.nextElementSibling!.classList.contains("b-rows-lists__item__subline")).toBe(true);
    const [pic, text, none] = [...sets[0]!.children];
    expect(pic.querySelector(".g-avatar__img-wrapper > img")!.getAttribute("src")).toBe(img("https://cdn.example/a1-144.jpg"));
    expect(text.querySelector(".g-avatar__placeholder.m-text-avatar")!.textContent).toBe(" Us ");
    expect(none.querySelector(".g-avatar__placeholder:not(.m-text-avatar) use")!.getAttribute("href")).toBe("#icon-profile");
    expect(sets[1]!.querySelector(".m-text-avatar")!.textContent).toBe(" M2 ");
    expect(doc.querySelector("#of-svg-sprite symbol#icon-profile")).not.toBeNull();
    applyData(doc, "collections/index", {});
    expect(doc.querySelectorAll(".m-avatars-media-set")).toHaveLength(0);
  });

  it("collections as generated: no example list, card or post; OF's Nothing found / No posts yet", () => {
    for (const p of ["collections/index", "collections/user-lists/list", "collections/user-lists/subscribers/active"]) {
      const doc = load(p);
      expect(shown(doc, ".b-user-lists__list .b-rows-lists__item"), p).toHaveLength(0);
      expect(shown(doc, ".b-users__item"), p).toHaveLength(0);
      expect(texts(doc, "[data-oi-empty]"), p).toEqual(["Nothing found", "Nothing found"]);
      expect(doc.body.textContent, p).not.toMatch(PLACEHOLDER);
    }
    const labels = load("collections/post-labels/archived");
    expect(shown(labels, ".b-post-labels__list .b-rows-lists__item")).toHaveLength(0);
    expect(shown(labels, ".b-post")).toHaveLength(0);
    expect(texts(labels, "[data-oi-empty]")).toEqual(["Nothing found", "No posts yet"]);
  });

  it("collections: Loading… and the red error in the columns' Nothing found, then the rows hide it", () => {
    const doc = load("collections/user-lists/list");
    const empties = () => shown(doc, "[data-oi-empty]").map((e) => e.textContent?.trim());
    applyData(doc, "collections/user-lists/list", { userListsStatus: null, usersStatus: null });
    expect(empties()).toEqual(["Loading…", "Loading…"]);
    applyData(doc, "collections/user-lists/list", { userListsStatus: "boom", usersStatus: "boom" });
    expect(empties()).toEqual(["Could not load: boom", "Could not load: boom"]);
    expect(doc.querySelector<HTMLElement>("[data-oi-empty] > span")!.style.color).toBe("rgb(255, 69, 69)");
    applyData(doc, "collections/user-lists/list", { userLists: [], listUsers: [] });
    expect(empties()).toEqual(["Nothing found", "Nothing found"]);
    applyData(doc, "collections/user-lists/list", { list: "31", userLists: [{ id: 31, name: "Whales", usersCount: 1 }], listUsers: [fan(201, "Delta Four", "delta")] });
    expect(empties()).toEqual([]);
    applyData(doc, "collections/user-lists/list", {});
    expect(empties()).toEqual(["Nothing found", "Nothing found"]);
  });

  it("Following (captured with no list row): the lists in Collections' borrowed row, gone again on restore", () => {
    const page = "collections/user-lists/subscriptions";
    const row = TEMPLATES.listRow!.pick(new DOMParser().parseFromString(capture(TEMPLATES.listRow!.page), "text/html"))!;
    const doc = load(page);
    expect(doc.querySelectorAll(".b-user-lists__list .b-rows-lists__item")).toHaveLength(0);
    applyData(doc, page, { userLists: [{ id: 31, name: "Whales", usersCount: 2 }], templates: { listRow: row } });
    expect(texts(doc, ".b-user-lists__list .b-rows-lists__item__name")).toEqual(["Whales"]);
    expect(texts(doc, ".b-user-lists__list .b-content-inside-thumbs")).toEqual(["2 users"]);
    expect(shown(doc, ".b-user-lists__list [data-oi-empty]")).toHaveLength(0);
    applyData(doc, page, {});
    expect(doc.querySelectorAll(".b-user-lists__list .b-rows-lists__item")).toHaveLength(0);
  });

  it("collections/index: the open (first) list's name and users", () => {
    const doc = load("collections/index");
    applyData(doc, "collections/index", { list: "31", userLists: [{ id: 31, name: "Whales", usersCount: 1 }, { id: 32, name: "New" }], listUsers: [fan(201, "Delta Four", "delta")] });
    expect(texts(doc, ".l-main-content .g-page-title > span")).toEqual(["Whales"]);
    expect(texts(doc, "a.m-current .b-rows-lists__item__name")).toEqual(["Whales"]);
    const cards = shown(doc, ".b-users__item");
    expect(cards.map((c) => c.querySelector(".g-user-name")!.textContent)).toEqual(["Delta Four"]);
    expect(cards[0].closest("[data-oi-user]")?.getAttribute("data-oi-user")).toBe("201");
    expect(cards.map((c) => c.querySelector(".b-list-titles a")?.textContent?.trim())).toEqual(["Whales"]);
  });

  it("Fans: the active subscribers as cards, with no list link", () => {
    const doc = load("collections/user-lists/subscribers/active");
    applyData(doc, "collections/user-lists/subscribers/active", { userLists: [], subscribers: [fan(201, "Delta Four", "delta"), fan(202, "Echo Five", "echo")] });
    const cards = shown(doc, ".b-users__item");
    expect(cards.map((c) => c.querySelector(".g-user-username")!.textContent)).toEqual(["@delta", "@echo"]);
    expect(cards.flatMap((c) => [...c.querySelectorAll(".b-list-titles a")])).toHaveLength(0);
    expect(cards[0].querySelector("a[href^='/of-manager/messages/chat']")!.getAttribute("href")).toBe("/of-manager/messages/chat?chat=201");
  });

  it("Post Labels: the Creator's labels (name, posts), the open one marked and titled; its posts stay OF's empty state", () => {
    const doc = load("collections/post-labels/archived");
    const labels = [{ id: 7, name: "Beach", postsCount: 3 }, { id: 8, name: "Gym", postsCount: 0 }];
    applyData(doc, "collections/post-labels/archived", { labels, label: "8" });
    expect(texts(doc, ".b-post-labels__list .b-rows-lists__item__name")).toEqual(["Beach", "Gym"]);
    expect(texts(doc, ".b-post-labels__list .b-content-inside-thumbs__item")).toEqual(["3 posts", "0 posts"]);
    expect(shown(doc, ".b-post-labels__list a.b-rows-lists__item__text").map((a) => a.getAttribute("href"))).toEqual([
      "/of-manager/collections/post-labels/archived?label=7",
      "/of-manager/collections/post-labels/archived?label=8",
    ]);
    expect(texts(doc, ".b-post-labels__list a.m-current .b-rows-lists__item__name")).toEqual(["Gym"]);
    expect(texts(doc, ".l-main-content .g-page-title > span")).toEqual(["Gym"]);
    expect(texts(doc, "[data-oi-empty]")).toEqual(["No posts yet"]);
    applyData(doc, "collections/post-labels/archived", { labels: [] });
    expect(texts(doc, "[data-oi-empty]")).toEqual(["Nothing found", "No posts yet"]);
  });
});

// Local times (no Z), so the dates read the same in every time zone.
const POSTS: MirrorPost[] = [
  {
    id: 901,
    text: "<p>Alpha <b>One</b> wall post</p>",
    postedAt: "2026-10-10T10:05:00",
    isPinned: true,
    likesCount: 7,
    commentsCount: 2,
    media: [{ id: 1, type: "photo", files: { thumb: { url: "https://cdn.example/t901.jpg" }, preview: { url: "https://cdn.example/p901.jpg" } } }],
  },
  { id: 902, text: "Second synthetic post", postedAt: "2026-10-09T21:30:00", isPinned: false, favoritesCount: 3, commentsCount: 0, media: [] },
];
const POST_ROW = ".user_posts .vue-recycle-scroller__item-view";
const posts = (doc: Document) => shown(doc, POST_ROW);

describe.each(["profile/index", "profile/state-more-menu"])("%s: the Creator's wall posts", (p) => {
  it("clones the page's own post row per post, in order, with exactly the mapped values", () => {
    const doc = load(p);
    atFixtureNow(() => applyData(doc, p, { posts: POSTS }, (u) => `/img?u=${u}`));
    const rows = posts(doc);
    expect(rows).toHaveLength(2);
    // OF's feed time: today's relative, then "Yesterday".
    expect(rows.map((r) => r.querySelector(".b-post__date > span")!.textContent)).toEqual([" 4 hours ago ", " Yesterday "]);
    expect(rows.map((r) => r.querySelector(".b-post__date > span")!.getAttribute("title"))).toEqual(["Oct 10, 10:05 am", "Oct 9, 9:30 pm"]);
    expect(rows.map((r) => r.querySelector("div.b-post")!.classList.contains("m-pinned"))).toEqual([true, false]);
    expect(rows.map((r) => !!r.querySelector(".b-post__pinned"))).toEqual([true, false]);
    expect(rows.map((r) => r.querySelector(".b-post__text .g-truncated-text > div")!.innerHTML.replace(/ data-v-[\w-]+=""/g, ""))).toEqual([
      "<p>Alpha One wall post</p>",
      "<p>Second synthetic post</p>",
    ]);
    const first = rows[0];
    expect([...first.querySelectorAll(".post_media img")].map((i) => i.getAttribute("src"))).toEqual([
      "/img?u=https://cdn.example/p901.jpg",
      "/img?u=https://cdn.example/p901.jpg",
    ]);
    expect(first.querySelector(".post_media__loading")).toBeNull();
    expect(first.querySelector(".b-post__content")!.classList.contains("m-post-has-media")).toBe(true);
    expect(rows.map((r) => r.querySelector("a[aria-label='Show who liked this post'] > span")?.textContent)).toEqual(["7", "3"]);
    expect(rows.map((r) => r.querySelector("a[aria-label='Show post comments'] > span")?.textContent)).toEqual(["2", "0"]);
    expect(rows.map((r) => r.querySelectorAll(".b-post__labels-controls .b-list-titles a").length)).toEqual([0, 0]);
    expect(rows.map((r) => r.querySelector("[scroll-item-index]")!.getAttribute("scroll-item-index"))).toEqual(["0", "1"]);
    for (const r of rows) expect(r.textContent).not.toMatch(PLACEHOLDER);
    expect(shown(doc, ".user_posts *").filter((e) => !e.children.length && /Lorem/.test(e.textContent ?? ""))).toEqual([]);
  });

  it("a post with no text drops its text block, no still keeps no captured picture, absent counts drop their links", () => {
    const doc = load(p);
    applyData(doc, p, { posts: [{ id: 903, text: "", postedAt: undefined, media: [{ id: 2, type: "video", files: { full: { url: "https://cdn.example/v.mp4" } } }] }] });
    const [row] = posts(doc);
    expect(row.querySelector(".b-post__text")).toBeNull();
    expect(row.querySelector(".post_media")).toBeNull();
    expect(row.querySelector("img[src^='data:']")).toBeNull();
    const content = row.querySelector(".b-post__content")!;
    expect([content.classList.contains("m-post-has-text"), content.classList.contains("m-post-has-media")]).toEqual([false, false]);
    expect(row.querySelector("a[aria-label='Show who liked this post']")).toBeNull();
    expect(row.querySelector("a[aria-label='Show post comments']")).toBeNull();
    expect(row.querySelector(".b-post__date > span")).toBeNull();
  });

  it("an empty list hides the examples; Creator A's rows then Creator B's leave only B's; no data restores the capture", () => {
    const doc = load(p);
    const html = doc.documentElement.innerHTML;
    applyData(doc, p, { posts: [] });
    expect(posts(doc)).toEqual([]);
    applyData(doc, p, { posts: POSTS });
    applyData(doc, p, { posts: [{ id: 990, text: "Beta Two post", postedAt: "2026-10-01T08:00:00", media: [] }] });
    expect(posts(doc).map((r) => r.querySelector(".b-post__text")!.textContent!.trim())).toEqual(["Beta Two post"]);
    expect(doc.querySelectorAll("[data-oi-data]")).toHaveLength(1);
    applyData(doc, p, {});
    expect(doc.documentElement.innerHTML).toBe(html);
  });

  it("a post's More click notes Read-only, calls nothing and is not marked wired", () => {
    const doc = load(p);
    applyData(doc, p, { posts: POSTS });
    const unbind = bindWrites(doc, p, null); // its click fallback, in either scope
    const fetch = vi.spyOn(globalThis, "fetch");
    const more = posts(doc)[1].querySelector<HTMLButtonElement>(".b-post__tools__more button[aria-label='More']")!;
    more.click();
    expect(doc.getElementById("oi-note")?.textContent).toBe(READ_ONLY);
    expect(fetch).not.toHaveBeenCalled();
    expect(more.hasAttribute("data-oi-wired")).toBe(false);
    expect(posts(doc).flatMap((r) => [...r.querySelectorAll("[data-oi-wired]")])).toHaveLength(0);
    unbind();
    doc.getElementById("oi-note")!.remove();
    more.click();
    expect(doc.getElementById("oi-note")).toBeNull();
    fetch.mockRestore();
  });
});


const still = (name: string) => ({ id: 1, type: "photo", files: { preview: { url: `https://cdn.example/${name}.jpg` } } });
// Photos then videos, as useOfData concatenates the two lists; post 33 is in both.
const MEDIA_POSTS: MirrorPost[] = [
  { id: 31, postedAt: "2026-10-08T10:00:00", mediaCount: 2, media: [still("p31")] },
  { id: 33, postedAt: "2026-10-10T10:00:00", media: [still("p33"), still("p33b")] },
  { id: 35, postedAt: "2026-10-05T10:00:00", mediaCount: 0, media: [still("p35")] },
  { id: 33, postedAt: "2026-10-10T10:00:00", media: [still("p33"), still("p33b")] },
  { id: 34, postedAt: "2026-10-09T10:00:00", mediaCount: 1, media: [{ id: 2, type: "video", files: { full: { url: "https://cdn.example/v34.mp4" } } }] },
];
const GRID = ".b-photos.vue-recycle-scroller";
const STRIP = ".b-photos.m-recent-list";

describe("profile/media: the Creator's media grid", () => {
  it("one tile per post, de-duplicated by id, newest first, three to a row, picture and count from the post", () => {
    const doc = load("profile/media");
    const tabs = texts(doc, ".b-tabs__nav__text");
    applyData(doc, "profile/media", { profileMedia: MEDIA_POSTS }, (u) => `/img?u=${u}`);
    const tiles = shown(doc, `${GRID} .b-photos__item`);
    expect(tiles.map((t) => t.querySelector("img.b-photos__item__img")?.getAttribute("src") ?? null)).toEqual([
      "/img?u=https://cdn.example/p33.jpg",
      null,
      "/img?u=https://cdn.example/p31.jpg",
      "/img?u=https://cdn.example/p35.jpg",
    ]);
    expect(tiles.map((t) => t.querySelector(".b-purchase__list-item__count")?.textContent?.trim() ?? null)).toEqual(["2", "1", "2", null]);
    expect(tiles.map((t) => !!t.querySelector(".b-subscribe-block"))).toEqual([true, true, true, false]);
    expect(shown(doc, `${GRID} .vue-recycle-scroller__item-view`).map((r) => r.querySelectorAll(".b-photos__item").length)).toEqual([3, 1]);
    expect(tiles.every((t) => t.matches("a.b-photos__item[at-attr='photo_item']"))).toBe(true);
    expect(texts(doc, ".b-tabs__nav__text")).toEqual(tabs);
    expect(texts(doc, ".user_posts [data-oi-empty]")).toEqual([]);
    // The Recent strip: the three newest posts with a picture (34 has none).
    expect(shown(doc, `${STRIP} .b-photos__item img`).map((i) => i.getAttribute("src"))).toEqual([
      "/img?u=https://cdn.example/p33.jpg",
      "/img?u=https://cdn.example/p31.jpg",
      "/img?u=https://cdn.example/p35.jpg",
    ]);
  });

  it("the Media tab's Photo and Video show only the posts their route sent", () => {
    const doc = load("profile/media");
    const kinds: MediaPost[] = [
      { id: 31, postedAt: "2026-10-08T10:00:00", media: [still("p31")], _kind: "photo" },
      { id: 34, postedAt: "2026-10-09T10:00:00", media: [still("v34")], _kind: "video" },
    ];
    const srcs = () => shown(doc, `${GRID} .b-photos__item img`).map((i) => i.getAttribute("src"));
    applyData(doc, "profile/media", { profileMedia: kinds });
    expect(srcs()).toEqual(["https://cdn.example/v34.jpg", "https://cdn.example/p31.jpg"]);
    doc.documentElement.dataset.oiMediaType = "video";
    applyData(doc, "profile/media", { profileMedia: kinds });
    expect(srcs()).toEqual(["https://cdn.example/v34.jpg"]);
    doc.documentElement.dataset.oiMediaType = "photo";
    applyData(doc, "profile/media", { profileMedia: kinds });
    expect(srcs()).toEqual(["https://cdn.example/p31.jpg"]);
    delete doc.documentElement.dataset.oiMediaType;
  });

  it("an empty merge hides the example tiles; Creator A's tiles then Creator B's leave only B's; no data restores the capture", () => {
    const doc = load("profile/media");
    const html = doc.documentElement.innerHTML;
    expect(shown(doc, `${GRID} .b-photos__item`)).toEqual([]); // the generator's hidden template only
    expect(shown(doc, `${STRIP} .b-photos__item`)).toEqual([]);
    expect(texts(doc, ".user_posts [data-oi-empty]")).toEqual(["No posts yet"]);
    applyData(doc, "profile/media", { profileMedia: [] });
    expect(shown(doc, `${GRID} .b-photos__item`)).toEqual([]);
    expect(shown(doc, `${STRIP} .b-photos__item`)).toEqual([]);
    expect(texts(doc, ".user_posts [data-oi-empty]")).toEqual(["No posts yet"]);
    applyData(doc, "profile/media", { profileMedia: MEDIA_POSTS }, (u) => `/img?u=${u}`);
    applyData(doc, "profile/media", { profileMedia: [{ id: 41, postedAt: "2026-10-01T10:00:00", mediaCount: 3, media: [still("b41")] }] }, (u) => `/img?u=${u}`);
    const tiles = shown(doc, `${GRID} .b-photos__item`);
    expect(tiles.map((t) => t.querySelector("img")?.getAttribute("src"))).toEqual(["/img?u=https://cdn.example/b41.jpg"]);
    expect(doc.querySelectorAll(`${GRID} [data-oi-data]`)).toHaveLength(1);
    applyData(doc, "profile/media", {});
    expect(doc.documentElement.innerHTML).toBe(html);
  });
});

// The `post` template as useOfData borrows it: My profile's capture, parsed inertly.
const POST_TPL = TEMPLATES.post!.pick(new DOMParser().parseFromString(capture(TEMPLATES.post!.page), "text/html"))!;
const author = (id: number, name: string, username: string, avatar: string | null) => ({ id, name, username, avatar });
const BOOKMARKS: MirrorPost[] = [
  { ...POSTS[0], id: 801, author: author(51, "Alpha One", "alphaone", "https://cdn.example/a51.jpg") },
  { id: 802, text: "Beta bookmarked post", postedAt: "2026-10-09T21:30:00", likesCount: 1, commentsCount: 4, media: [], author: author(52, "Beta Two", "betatwo", null) },
  { id: 803, text: "No author post", postedAt: "2026-10-08T08:00:00", media: [] },
];
const BOOKMARKS_PAGE = "collections/bookmarks/all";
const BODY = ".l-main-content.m-r-side .g-page-content__body";
const marks = (doc: Document) => shown(doc, `${BODY} .vue-recycle-scroller__item-wrapper > [data-oi-data]`);
const EMPTY = `${BODY} > .empty-message`;

describe("collections/bookmarks/all: the Creator's bookmarked posts", () => {
  it("the post template is My profile's first post row", () => {
    expect(TEMPLATES.post!.page).toBe("profile/index");
    expect(POST_TPL.matches(".vue-recycle-scroller__item-view")).toBe(true);
    expect(POST_TPL.querySelector("div.b-post .b-post__text")?.textContent).toMatch(/Lorem/);
  });

  it("clones the post template per bookmark, in order, each with its own author, linking to the author's OF profile", () => {
    const doc = load(BOOKMARKS_PAGE);
    atFixtureNow(() => applyData(doc, BOOKMARKS_PAGE, { bookmarks: BOOKMARKS, templates: { post: POST_TPL }, me: { id: 9 } }, (u) => `/img?u=${u}`));
    const rows = marks(doc);
    expect(rows).toHaveLength(3);
    expect(rows.map((r) => r.querySelector(".b-username .g-user-name")!.firstChild!.textContent)).toEqual([" Alpha One ", " Beta Two ", ""]);
    expect(rows.map((r) => !!r.querySelector(".b-username .g-user-name svg.m-verified"))).toEqual([true, true, true]);
    expect(rows.map((r) => r.querySelector(".g-user-username")!.textContent)).toEqual(["@alphaone", "@betatwo", ""]);
    expect(rows.map((r) => [...r.querySelectorAll(".b-post__avatar img")].map((i) => i.getAttribute("src")))).toEqual([["/img?u=https://cdn.example/a51.jpg"], [], []]);
    expect(rows.map((r) => r.querySelector(".b-post__avatar .g-avatar__placeholder")?.textContent ?? null)).toEqual([null, " BT ", "  "]);
    // OF's profile links: the author's OF profile in a new tab (no author: inert); the date the post on onlyfans.com.
    const profile = (h: string) => [`https://onlyfans.com/${h}`, "_blank", "noopener noreferrer"];
    expect(rows.map((r) => [...r.querySelectorAll(".b-post__avatar a, a.b-username")].map((a) => [a.getAttribute("href"), a.getAttribute("target"), a.getAttribute("rel")]))).toEqual([
      [profile("alphaone"), profile("alphaone")],
      [profile("betatwo"), profile("betatwo")],
      [["#", "_top", null], ["#", "_top", null]],
    ]);
    expect(rows.map((r) => { const a = r.querySelector(".b-post__date")!; return [a.getAttribute("href"), a.getAttribute("target"), a.getAttribute("aria-disabled")]; })).toEqual([
      ["https://onlyfans.com/801/alphaone", "_blank", null],
      ["https://onlyfans.com/802/betatwo", "_blank", null],
      ["#", null, "true"],
    ]);
    expect(rows.map((r) => r.querySelector(".b-post__text")!.textContent!.trim())).toEqual(["Alpha One wall post", "Beta bookmarked post", "No author post"]);
    expect(rows.map((r) => r.querySelector(".b-post__date > span")!.textContent)).toEqual([" 4 hours ago ", " Yesterday ", " Oct 8 "]);
    expect(rows.map((r) => r.querySelector("div.b-post")!.classList.contains("m-pinned"))).toEqual([true, false, false]);
    expect([...rows[0].querySelectorAll(".post_media img")].map((i) => i.getAttribute("src"))).toEqual(["/img?u=https://cdn.example/p901.jpg", "/img?u=https://cdn.example/p901.jpg"]);
    expect(rows.map((r) => !!r.querySelector(".post_media"))).toEqual([true, false, false]);
    expect(rows.map((r) => r.querySelector("a[aria-label='Show post comments'] > span")?.textContent ?? null)).toEqual(["2", "4", null]);
    for (const r of rows) expect(r.textContent).not.toMatch(/Fan \d|@fan\d|Lorem|List \d|Your Model|@yourmodel/);
    expect(shown(doc, EMPTY)).toEqual([]);
    expect(rows.every((r) => r.ownerDocument === doc)).toBe(true);
  });

  it("the Creator's identity, applied after, leaves an avatar-less author's placeholder alone", () => {
    const doc = load(BOOKMARKS_PAGE);
    applyData(doc, BOOKMARKS_PAGE, { bookmarks: BOOKMARKS, templates: { post: POST_TPL } });
    applyIdentity(doc, { name: "Live Model", username: "livemodel", avatar: "https://cdn.example/me.jpg" });
    const rows = marks(doc);
    expect(rows.map((r) => r.querySelector<HTMLElement>(".b-post__avatar .g-avatar__placeholder")?.style.backgroundImage ?? null)).toEqual([null, "", ""]);
    expect(rows.map((r) => r.querySelector(".b-post__avatar .g-avatar__placeholder")?.textContent ?? null)).toEqual([null, " BT ", "  "]);
  });

  it("an empty list keeps the captured empty state; no template keeps the page as captured", () => {
    const doc = load(BOOKMARKS_PAGE);
    const html = doc.documentElement.innerHTML;
    applyData(doc, BOOKMARKS_PAGE, { bookmarks: [], templates: { post: POST_TPL } });
    expect(marks(doc)).toEqual([]);
    expect(texts(doc, EMPTY)).toEqual(["No bookmarks yet"]);
    applyData(doc, BOOKMARKS_PAGE, { bookmarks: BOOKMARKS });
    expect(doc.documentElement.innerHTML).toBe(html);
  });

  it("the sidebar's Recent list keeps its captured empty state", () => {
    const doc = load(BOOKMARKS_PAGE);
    const recent = doc.querySelector(".b-bookmarks__list")!.outerHTML;
    applyData(doc, BOOKMARKS_PAGE, { bookmarks: BOOKMARKS, templates: { post: POST_TPL } });
    expect(doc.querySelector(".b-bookmarks__list")!.outerHTML).toBe(recent);
  });

  it("Creator A's bookmarks then Creator B's leave only B's; no data restores the capture byte for byte", () => {
    const doc = load(BOOKMARKS_PAGE);
    const html = doc.documentElement.innerHTML;
    applyData(doc, BOOKMARKS_PAGE, { bookmarks: BOOKMARKS, templates: { post: POST_TPL } });
    applyData(doc, BOOKMARKS_PAGE, { bookmarks: [{ id: 990, text: "Gamma post", postedAt: "2026-10-01T08:00:00", media: [] }], templates: { post: POST_TPL } });
    expect(marks(doc).map((r) => r.querySelector(".b-post__text")!.textContent!.trim())).toEqual(["Gamma post"]);
    expect(doc.querySelectorAll("[data-oi-data]")).toHaveLength(1);
    applyData(doc, BOOKMARKS_PAGE, {});
    expect(doc.documentElement.innerHTML).toBe(html);
  });

  it("a row is the Creator's own only when proven: an unknown `me` (loading, failed) gives every row another's tools", () => {
    const tools = (me?: { id: number }) => {
      const doc = load(BOOKMARKS_PAGE);
      applyData(doc, BOOKMARKS_PAGE, { bookmarks: BOOKMARKS, templates: { post: POST_TPL }, me });
      return marks(doc).map((r) => [!!r.querySelector("button[at-attr='post_tip']"), !!r.querySelector<HTMLButtonElement>(".b-post__tools__more button")?.disabled]);
    };
    expect(tools()).toEqual([[true, true], [true, true], [true, true]]);
    expect(tools({ id: 51 })).toEqual([[false, false], [true, true], [true, true]]);
  });

  it("author links wait for the Creator's id: inert while `me` is unknown, then My profile for the own post, OF's profile for another's", () => {
    const links = (me?: { id: number }) => {
      const doc = load(BOOKMARKS_PAGE);
      applyData(doc, BOOKMARKS_PAGE, { bookmarks: BOOKMARKS, templates: { post: POST_TPL }, me });
      return marks(doc).map((r) => [...r.querySelectorAll(".b-post__avatar a, a.b-username")].map((a) => `${a.getAttribute("href")} ${a.getAttribute("target")}`));
    };
    expect(links()).toEqual(Array(3).fill(Array(2).fill("# _top")));
    expect(links({ id: 51 })).toEqual([
      Array(2).fill("/of-manager/profile _top"),
      Array(2).fill("https://onlyfans.com/betatwo _blank"),
      Array(2).fill("# _top"),
    ]);
  });

  it("a bookmark's More click notes Read-only, calls nothing and is not marked wired", () => {
    const doc = load(BOOKMARKS_PAGE);
    // The Creator's own bookmarked post (its More is OF's own-post menu; another's, or an unproven one's, is disabled).
    applyData(doc, BOOKMARKS_PAGE, { bookmarks: BOOKMARKS, templates: { post: POST_TPL }, me: { id: 51 } });
    const unbind = bindWrites(doc, BOOKMARKS_PAGE, null);
    const fetch = vi.spyOn(globalThis, "fetch");
    const more = marks(doc)[0].querySelector<HTMLButtonElement>(".b-post__tools__more button[aria-label='More']")!;
    more.click();
    expect(doc.getElementById("oi-note")?.textContent).toBe(READ_ONLY);
    expect(fetch).not.toHaveBeenCalled();
    expect(doc.querySelectorAll("[data-oi-wired]")).toHaveLength(0);
    unbind();
    fetch.mockRestore();
  });
});

describe("collections/index: Create new list", () => {
  it("notes Read-only, calls nothing, carries no data-oi-wired, and stops with the unbind", () => {
    const doc = load("collections/index");
    const unbind = bindWrites(doc, "collections/index", null);
    const fetch = vi.spyOn(globalThis, "fetch");
    const create = doc.querySelector<HTMLButtonElement>("button[aria-label='Create new list']")!;
    create.click();
    expect(doc.getElementById("oi-note")?.textContent).toBe(READ_ONLY);
    expect(fetch).not.toHaveBeenCalled();
    expect(create.hasAttribute("data-oi-wired")).toBe(false);
    expect(doc.querySelectorAll("[data-oi-wired]")).toHaveLength(0);
    unbind();
    doc.getElementById("oi-note")!.remove();
    create.click();
    expect(doc.getElementById("oi-note")).toBeNull();
    fetch.mockRestore();
  });
});

describe("queueMonth", () => {
  it("reads the month the calendar shows from the captured header", () => {
    expect(queueMonth(load("queue/index"))).toEqual({ start: "2026-10-01", end: "2026-10-31" });
    expect(queueMonth(load("queue/state-list-view"))).toEqual({ start: "2026-10-01", end: "2026-10-31" });
  });

  it("a page with no month header gives none", () => {
    expect(queueMonth(load("queue/saved-for-later-posts"))).toBeNull();
  });
});

describe("queueTypes and queueDay", () => {
  it("the selected tabs' item types: none on the calendar, chat on Messages, chat and stream on Streams", () => {
    expect(queueTypes(load("queue/index"))).toEqual([]);
    expect(queueTypes(load("queue/state-list-view"))).toEqual([]);
    expect(queueTypes(load("queue/state-tab-messages"))).toEqual(["chat"]);
    expect(queueTypes(load("queue/state-tab-streams"))).toEqual(["chat", "stream"]);
  });

  it("the right column's day, and none without one", () => {
    expect(queueDay(load("queue/index"))).toBe("2026-10-12");
    expect(queueDay(load("queue/saved-for-later-posts"))).toBeNull();
  });
});

// The `agenda` template as useOfData borrows it: the list view's capture, parsed inertly.
const AGENDA_TPL = TEMPLATES.agenda!.pick(new DOMParser().parseFromString(capture(TEMPLATES.agenda!.page), "text/html"))!;
// OF's own /schedules item (app/lib/__fixtures__/of, captured through the Relay and scrubbed): the others take its shape.
const REAL = (JSON.parse(readFileSync(resolve(__dirname, "__fixtures__/of/queue-schedules-2026-11.json"), "utf8")) as { list: QueueItem[] }).list[0];
/**
 * OF's item with another type, time (local, no offset: the days and times read the same in every time zone) and entity.
 * A scheduled message's entity has its send time (`scheduledAt`; one without is saved for later, OF's isSFLMessage).
 */
const scheduled = (type: string, publishDateTime: string, entity: QueueItem["entity"]): QueueItem => ({
  ...REAL,
  type,
  publishDateTime,
  entity: { ...REAL.entity, text: null, ...(type === "chat" ? { scheduledAt: publishDateTime } : {}), ...entity },
});
// Not in order, as no order is promised.
const SCHEDULES: QueueItem[] = [
  scheduled("chat", "2026-10-14T18:30:00", { text: "<p>Alpha One chat</p>" }),
  scheduled("post", "2026-10-12T09:05:00", { text: "Alpha Two <b>post</b>" }),
  scheduled("post", "2026-10-14T08:00:00", { text: "", mediaCount: 2 }),
  scheduled("chat", "2026-10-12T21:00:00", {}),
];
// [day label, [[indicator, time, text] per item]] per section, soonest first.
const WANT_SCHEDULES = [
  ["Oct 12", [["post-indicator", "9:05 am", "Alpha Two post"], ["chat-indicator", "9:00 pm", ""]]],
  ["Oct 14", [["post-indicator", "8:00 am", "Media"], ["chat-indicator", "6:30 pm", "Alpha One chat"]]],
];
const AGENDA = ".b-agenda";
const sections = (doc: Document) =>
  shown(doc, ".b-agenda__section").map((s) => [
    s.querySelector(".b-agenda__section-date")!.textContent,
    [...s.querySelectorAll("a.b-agenda__area-events__item")].map((a) => [
      [...a.classList].filter((c) => c.endsWith("-indicator")).join(" "),
      a.querySelector(".b-agenda__area-events__item-details")!.textContent,
      a.querySelector(".b-agenda__area-events__item-inward")!.textContent,
    ]),
  ]);
// [day, type, text] per event bar on the calendar's days.
const bars = (doc: Document) =>
  [...doc.querySelectorAll<HTMLElement>(".v-calendar-monthly .v-event[data-oi-data]")].map((b) => [b.dataset.date, [...b.classList].find((c) => ["post", "chat", "stream"].includes(c)), b.textContent]);
const WANT_BARS = [
  ["2026-10-12", "post", "1"],
  ["2026-10-12", "chat", "1"],
  ["2026-10-14", "post", "1"],
  ["2026-10-14", "chat", "1"],
];
const scopeOf = (el: Element) => el.getAttributeNames().filter((n) => n.startsWith("data-v-")).sort();
const QUEUE_PAGES = ["queue/index", "queue/state-list-view", "queue/state-tab-messages", "queue/state-tab-streams", "queue/saved-for-later-posts", "queue/saved-for-later-messages"];

describe("queue: the Creator's scheduled and saved-for-later items", () => {
  it("the agenda template is the list view's agenda block, its empty state removed", () => {
    expect(TEMPLATES.agenda!.page).toBe("queue/state-list-view");
    expect(AGENDA_TPL.matches(".b-queue-scroll-wrapper")).toBe(true);
    expect(AGENDA_TPL.querySelector(".b-agenda.m-main-block")).not.toBeNull();
    expect(AGENDA_TPL.querySelector(".empty-message")).toBeNull();
  });

  it("list view: the month's items in its own agenda block, by local day soonest first, in OF's agenda classes and scope", () => {
    const doc = load("queue/state-list-view");
    applyData(doc, "queue/state-list-view", { queue: SCHEDULES });
    expect(sections(doc)).toEqual(WANT_SCHEDULES);
    expect(texts(doc, `${AGENDA} > .empty-message`)).toEqual([]);
    // One outside the right column (whose day's list is its own block).
    expect([...doc.querySelectorAll(".b-agenda")].filter((a) => !a.closest(".l-wrapper__sidebar"))).toHaveLength(1);
    const agenda = doc.querySelector(".b-agenda")!;
    // The More buttons' icons are SVG, outside the scope.
    const built = [...agenda.querySelectorAll(".b-agenda__section, .b-agenda__section *")].filter((el) => !el.closest("svg"));
    expect(built.every((el) => scopeOf(el).join() === scopeOf(agenda).join())).toBe(true);
    expect(scopeOf(agenda)).toEqual(["data-v-13609a39", "data-v-f602563e"]);
    expect(doc.querySelector(".b-queue-scroll-wrapper")!.classList.contains("m-empty-content")).toBe(false);
    // OF's items carry their ids: each row its More menu.
    expect(agenda.querySelectorAll(".b-post__tools__more [aria-label='More']")).toHaveLength(4);
  });

  it.each(["queue/index", "queue/state-tab-messages"])("%s: the calendar marks the days with OF's event bars and counts; nothing under it", (p) => {
    const doc = load(p);
    const html = doc.documentElement.innerHTML;
    applyData(doc, p, { queue: [] });
    expect(doc.documentElement.innerHTML).toBe(html);
    const items: QueueItem[] = p === "queue/index" ? SCHEDULES : [scheduled("chat", "2026-10-20T07:15:00", { text: "Queued hello" }), scheduled("chat", "2026-10-20T09:15:00", { text: "Queued again" })];
    applyData(doc, p, { queue: items, templates: { agenda: AGENDA_TPL } });
    expect(bars(doc)).toEqual(p === "queue/index" ? WANT_BARS : [["2026-10-20", "chat", "2"]]);
    // OF's month view lists nothing under its calendar.
    expect(doc.querySelector(".v-calendar")!.nextElementSibling).toBeNull();
    expect(doc.querySelector(".b-queue-scroll-wrapper")).toBeNull();
    // The bars sit in their day's cell, after its label, in OF's calendar scope.
    const bar = doc.querySelector(".v-event[data-oi-data]")!;
    expect(bar.previousElementSibling!.matches(".v-calendar-weekly__day-label")).toBe(true);
    expect(bar.closest(".v-calendar[data-v-13609a39]")).not.toBeNull();
    applyData(doc, p, {});
    expect(doc.documentElement.innerHTML).toBe(html);
  });

  it("Messages tab: only the month's messages are counted; a post, one outside the month or undated is not", () => {
    const doc = load("queue/state-tab-messages");
    const queue: QueueItem[] = [
      scheduled("chat", "2026-11-01T00:30:00", { text: "November" }),
      scheduled("chat", "2026-10-31T23:30:00", { text: "Last evening" }),
      scheduled("chat", "2026-09-30T23:59:00", { text: "September" }),
      { ...scheduled("chat", "", { text: "Undated" }), publishDateTime: undefined },
      scheduled("post", "2026-10-15T10:00:00", { text: "A post" }),
      scheduled("chat", "2026-10-01T00:10:00", { text: "", mediaCount: 1 }),
    ];
    applyData(doc, "queue/state-tab-messages", { queue, templates: { agenda: AGENDA_TPL } });
    expect(bars(doc)).toEqual([
      ["2026-10-01", "chat", "1"],
      ["2026-10-31", "chat", "1"],
    ]);
  });

  it("Messages tab: no item in the month marks no day", () => {
    const doc = load("queue/state-tab-messages");
    const html = doc.documentElement.innerHTML;
    applyData(doc, "queue/state-tab-messages", { queue: [scheduled("chat", "2026-11-02T10:00:00", { text: "November" }), SCHEDULES[1]], templates: { agenda: AGENDA_TPL } });
    expect(doc.documentElement.innerHTML).toBe(html);
  });

  it.each([
    ["queue/saved-for-later-posts", "sfl-post-indicator", "There are no saved for later posts"],
    ["queue/saved-for-later-messages", "sfl-chat-indicator", "There are no saved for later messages"],
  ])("%s: saved items as OF's cards in place of the empty state; an empty list keeps it", (p, mark, empty) => {
    const doc = load(p);
    applyData(doc, p, { queue: [], templates: { agenda: AGENDA_TPL } });
    expect(texts(doc, ".saved-for-later > .empty-message")).toEqual([empty]);
    expect(shown(doc, ".b-post.m-queue-post")).toEqual([]);
    applyData(doc, p, { queue: [{ text: "<p>Saved Alpha</p>" }, { text: null, mediaCount: 3 }, { text: "" }], templates: { agenda: AGENDA_TPL } });
    // OF's card classes per kind (sfl-post / sfl-message), the item's text, "Media", or nothing.
    const kind = mark === "sfl-post-indicator" ? "sfl-post" : "sfl-message";
    expect(shown(doc, ".saved-for-later > .b-post.m-queue-post").map((c) => [c.classList.contains(kind), c.querySelector(".b-post__text")!.textContent])).toEqual([
      [true, "Saved Alpha"],
      [true, "Media"],
      [true, ""],
    ]);
    expect(texts(doc, ".saved-for-later > .empty-message")).toEqual([]);
    expect(doc.querySelector(".saved-for-later > .g-page__header")!.nextElementSibling!.matches(".empty-message")).toBe(true);
    expect(doc.querySelector(".saved-for-later")!.classList.contains("m-empty-content")).toBe(false);
  });

  it("a stream gets OF's stream mark and its description; an unknown /schedules type no colour mark", () => {
    const doc = load("queue/state-list-view");
    applyData(doc, "queue/state-list-view", {
      queue: [
        { type: "stream", publishDateTime: "2026-10-03T10:00:00", entity: { id: 9, description: "Live" } },
        { type: "story", publishDateTime: "2026-10-03T11:00:00", entity: { text: "Other" } },
      ],
    });
    expect(sections(doc)).toEqual([["Oct 3", [["stream-indicator", "10:00 am", "Live"], ["", "11:00 am", "Other"]]]]);
    // No stream edit or delete in the Relay: no More menu.
    expect(doc.querySelectorAll(".b-agenda [aria-label='More']")).toHaveLength(0);
  });

  it("the right column lists the shown day's items in place of its empty state; another day keeps it", () => {
    const doc = load("queue/index");
    const html = doc.documentElement.innerHTML;
    applyData(doc, "queue/index", { queue: SCHEDULES, templates: { agenda: AGENDA_TPL } });
    const side = doc.querySelector(".l-wrapper__sidebar")!;
    expect(shown(doc, ".l-wrapper__sidebar > .empty-message")).toEqual([]);
    expect(side.classList.contains("m-empty-section")).toBe(false);
    expect([...side.querySelectorAll(".b-agenda[data-oi-data] .b-agenda__area-events__item-inward")].map((e) => e.textContent)).toEqual(["Alpha Two post", ""]);
    applyData(doc, "queue/index", { queue: [SCHEDULES[0]], templates: { agenda: AGENDA_TPL } });
    expect(texts(doc, ".l-wrapper__sidebar > .empty-message")).toEqual(["There are no scheduled events for this day"]);
    expect(side.querySelector(".b-agenda")).toBeNull();
    applyData(doc, "queue/index", {});
    expect(doc.documentElement.innerHTML).toBe(html);
  });

  it("the month pages with no template (no agenda scope yet): the days marked, the right column as captured", () => {
    const doc = load("queue/index");
    const side = doc.querySelector(".l-wrapper__sidebar")!.outerHTML;
    applyData(doc, "queue/index", { queue: SCHEDULES });
    expect(bars(doc)).toEqual(WANT_BARS);
    expect(doc.querySelector(".l-wrapper__sidebar")!.outerHTML).toBe(side);
  });

  it.each(QUEUE_PAGES)("%s: Creator A's items then Creator B's leave only B's; no data restores the capture byte for byte", (p) => {
    const doc = load(p);
    const html = doc.documentElement.innerHTML;
    // The calendar pages: on the right column's day (Oct 12), so their rows show there; the list view another.
    const at = p.includes("saved-for-later") ? {} : { type: p.includes("state-tab") ? "chat" : "post", publishDateTime: p.includes("list-view") ? "2026-10-05T10:00:00" : "2026-10-12T10:00:00" };
    const item = (text: string): QueueItem => ({ ...at, text, entity: { text } });
    applyData(doc, p, { queue: [item("Alpha item"), item("Alpha other")], templates: { agenda: AGENDA_TPL } });
    applyData(doc, p, { queue: [item("Beta item")], templates: { agenda: AGENDA_TPL } });
    expect(shown(doc, ".b-agenda__area-events__item-inward, .b-post.m-queue-post .b-post__text").map((e) => e.textContent)).toEqual(["Beta item"]);
    expect(doc.querySelectorAll(".b-agenda__area-events__item, .b-post.m-queue-post")).toHaveLength(1);
    applyData(doc, p, {});
    expect(doc.documentElement.innerHTML).toBe(html);
  });

  it("the Streams tab (Messages and Streams selected): the month's messages and streams marked, no post", () => {
    const doc = load("queue/state-tab-streams");
    const stream = scheduled("stream", "2026-10-20T19:00:00", { id: 4, description: "Synthetic live" });
    applyData(doc, "queue/state-tab-streams", { queue: [...SCHEDULES, stream], templates: { agenda: AGENDA_TPL } });
    expect(bars(doc)).toEqual([
      ["2026-10-12", "chat", "1"],
      ["2026-10-14", "chat", "1"],
      ["2026-10-20", "stream", "1"],
    ]);
    // The right column: Oct 12's message only.
    expect(shown(doc, ".l-wrapper__sidebar .b-agenda__area-events__item").map((a) => a.className.includes("chat-indicator"))).toEqual([true]);
  });
});

// Local times (no Z): the dates read the same in every time zone. In the Relay's order.
const NOTIFS: MirrorNotification[] = [
  { type: "subscribed", isRead: false, createdAt: "2026-10-10T10:05:00", text: "subscribed to your profile", user: fan(201, "Alpha One", "alphaone") },
  {
    type: "tip",
    isRead: true,
    createdAt: "2026-10-09T21:30:00",
    text: "<p>tipped you <b>{AMOUNT}</b> on {POST}</p>",
    replacePairs: { "{AMOUNT}": "$5.00", "{POST}": '<a href="https://onlyfans.com/1/alpha">your post</a>' },
    fromUser: { id: 202, name: " ", username: "alphatwo", avatar: null },
  },
  { type: "commented", text: "commented: nice", user: { id: 203 } },
];
const NOTIF_TABS = ["index", "subscribed", "commented", "mentioned", "tip", "purchases", "favorited", "message", "deactivated_media", "tags"].map((t) => `notifications/${t}`);
const notifs = (doc: Document) => shown(doc, ".b-notifications__list .vue-recycle-scroller__item-view");
// [name, @handle, text, date, its hover stamp, unread, icon, avatar src] per row shown.
const notifRows = (doc: Document) =>
  notifs(doc).map((r) => [
    r.querySelector(".b-username .g-user-name")!.textContent,
    r.querySelector(".g-user-username")!.textContent,
    r.querySelector(".b-notifications__list__item__text .g-truncated-text")!.innerHTML,
    r.querySelector(".g-date > span")?.textContent ?? null,
    r.querySelector(".g-date > span")?.getAttribute("title") ?? null,
    r.querySelector(".b-notifications__list__item")!.classList.contains("m-unread"),
    r.querySelector(".b-notifications__avatar__icon svg")?.getAttribute("data-icon-name") ?? null,
    [...r.querySelectorAll(".g-avatar img")].map((i) => i.getAttribute("src")),
  ]);
const WANT_NOTIFS = [
  [" Alpha One ", " @alphaone ", "subscribed to your profile", " Oct 10 ", "Oct 10, 10:05 am", true, "icon-follow", ["/img?u=https://cdn.example/alphaone.jpg"]],
  [" alphatwo ", " @alphatwo ", 'tipped you $5.00 on <a href="https://onlyfans.com/1/alpha" target="_blank" rel="noopener noreferrer">your post</a>', " Oct 9 ", "Oct 9, 9:30 pm", false, "icon-price", []],
  [" 203 ", " @u203 ", "commented: nice", null, null, false, null, []],
];

describe("notifications: the Creator's notifications", () => {
  it("gives every tab the notifications, the tab bar's counts and Home's right column, each tab the type OF's own tab sends (Tags: its mentions)", () => {
    for (const p of NOTIF_TABS) expect(partsOf(p)).toEqual(["notifications", "notificationCounts", "promotions", "events"]);
    const types = Object.fromEntries(Object.entries(NOTIFICATIONS).map(([p, r]) => [p, new URL(r, "http://x").searchParams.get("type")]));
    expect(types).toEqual({
      "notifications/index": null,
      "notifications/subscribed": "subscribed",
      "notifications/commented": "commented",
      "notifications/mentioned": "mentioned",
      "notifications/tip": "tip",
      "notifications/purchases": "purchases",
      "notifications/favorited": "favorited",
      "notifications/message": "message",
      "notifications/deactivated_media": "deactivated_media",
      "notifications/tags": null,
    });
    expect(NOTIFICATIONS["notifications/tags"]).toBe("/api/of/v2/release-forms/mentions?limit=20");
  });

  it.each(NOTIF_TABS)("%s: clones the plain row per notification, in order, with exactly the mapped values", (p) => {
    const doc = load(p);
    applyData(doc, p, { notifications: NOTIFS }, (u) => `/img?u=${u}`);
    expect(notifRows(doc)).toEqual(WANT_NOTIFS);
    const rows = notifs(doc);
    expect(rows.map((r) => r.querySelector("[data-index]")!.getAttribute("data-index"))).toEqual(["0", "1", "2"]);
    expect(rows.map((r) => r.querySelectorAll(".b-list-titles a, .g-avatar__icon, .g-user-name svg, .g-avatar img[src^='data:']").length)).toEqual([0, 0, 0]);
    // The tab's own row: Likes, Promotions and OnlyFans capture rows with no "Add to favorites" button.
    const add = ["notifications/favorited", "notifications/message", "notifications/deactivated_media"].includes(p) ? undefined : " Add to favorites and other lists ";
    expect(rows.map((r) => r.querySelector(".b-list-titles__item__text")?.textContent)).toEqual(Array(3).fill(add));
    // Its list buttons (no Relay write behind them) stay disabled with the tooltip.
    for (const b of rows.flatMap((r) => [...r.querySelectorAll("button[at-attr='add_to_list']")])) expect([b.hasAttribute("disabled"), b.getAttribute("title")]).toEqual([true, NOT_YET]);
    for (const r of rows) expect(r.textContent).not.toMatch(PLACEHOLDER);
    // OF's profile links (the user's avatar, name and handle): their OF profile, in a new tab (those tabs' rows have none).
    expect(rows.map((r) => [...new Set([...r.querySelectorAll("a.g-avatar, a.b-username, a.g-user-username")].map((a) => `${a.getAttribute("href")} ${a.getAttribute("target")} ${a.getAttribute("rel")}`))])).toEqual(
      ["alphaone", "alphatwo", "u203"].map((h) => (add ? [`https://onlyfans.com/${h} _blank noopener noreferrer`] : [])),
    );
  });

  it("a notification's text keeps its OF links (an OF chat opens here) and nothing else of its markup", () => {
    const html = (s: string) => {
      const box = document.createElement("div");
      box.replaceChildren(...notificationText(document, s));
      return box.innerHTML;
    };
    expect(html(" <p>bought your <a href='https://onlyfans.com/my/chats/chat/4242?firstId=9'>message</a> for <b>$6.00</b></p> ")).toBe(
      'bought your <a href="/of-manager/messages/chat?chat=4242" target="_top">message</a> for $6.00',
    );
    expect(html('<a href="/123/alpha">post</a>')).toBe('<a href="https://onlyfans.com/123/alpha" target="_blank" rel="noopener noreferrer">post</a>');
    expect(html('<a href="javascript:alert(1)">x</a> <a href="https://evil.example/">y</a> <img src=x onerror="alert(1)"><script>alert(1)</script>z')).toBe("x y z");
  });

  it("no example row; Creator A's rows then Creator B's leave only B's; no data restores the page byte for byte", () => {
    const p = "notifications/index";
    const doc = load(p);
    const html = doc.documentElement.innerHTML;
    expect(notifs(doc)).toEqual([]);
    applyData(doc, p, { notifications: [] });
    expect(notifs(doc)).toEqual([]);
    applyData(doc, p, { notifications: NOTIFS });
    applyData(doc, p, { notifications: [{ type: "mentioned", text: "Beta mention", user: fan(301, "Beta Two", "betatwo") }] });
    expect(notifRows(doc).map((r) => r.slice(0, 3))).toEqual([[" Beta Two ", " @betatwo ", "Beta mention"]]);
    expect(doc.querySelectorAll("[data-oi-data]")).toHaveLength(1);
    applyData(doc, p, {});
    expect(doc.documentElement.innerHTML).toBe(html);
  });

  it.each(NOTIF_TABS)("%s: rows hide OF's empty tab (its message and centring); an empty list keeps it; no data restores it byte for byte", (p) => {
    const doc = load(p);
    const html = doc.documentElement.innerHTML;
    // OF's own status prompts are hidden with "display: none" (ours with "display:none").
    const emptyTab = () => shown(doc, ".b-notifications__list .empty-message").filter((e) => !e.closest("[style*='display: none']")).map((e) => e.textContent?.trim());
    expect(emptyTab()).toEqual(["No notifications currently!"]);
    applyData(doc, p, { notifications: [] });
    expect(emptyTab()).toEqual(["No notifications currently!"]);
    expect(doc.querySelector(".b-notifications")!.classList.contains("m-empty-page")).toBe(true);
    applyData(doc, p, { notifications: NOTIFS });
    expect(emptyTab()).toEqual([]);
    expect(doc.querySelector(".b-notifications")!.classList.contains("m-empty-page")).toBe(false);
    applyData(doc, p, {});
    expect(doc.documentElement.innerHTML).toBe(html);
  });

  it.each(NOTIF_TABS)("%s: OF's empty tab with no example, count or live control; loading and a Relay error say so in its message", (p) => {
    const doc = load(p);
    const html = doc.documentElement.innerHTML;
    const emptyTab = () => shown(doc, ".b-notifications__list .empty-message").filter((e) => !e.closest("[style*='display: none']")).map((e) => e.textContent?.trim());
    expect(emptyTab()).toEqual(["No notifications currently!"]);
    expect(doc.querySelector(".b-notifications")!.classList.contains("m-empty-page")).toBe(true);
    expect(shown(doc, ".b-notifications__list *, .b-tabs__nav *").filter((e) => !e.children.length).map((e) => e.textContent).join(" ")).not.toMatch(PLACEHOLDER);
    expect(doc.querySelectorAll(".b-tabs__nav .b-tabs__nav__count")).toHaveLength(0);
    // Search users, the tab bar's rearrange button, the row's list buttons and the right column's search: no source.
    const off = [...doc.querySelectorAll<HTMLButtonElement | HTMLInputElement>("[aria-label='Search users'], .b-tabs__nav button, [at-attr='add_to_list'], input[name='feed-search-input']")];
    expect(off.length).toBeGreaterThanOrEqual(3);
    for (const b of off) expect([b.disabled, b.title]).toEqual([true, NOT_YET]);
    // OF's own settings link stays.
    expect(doc.querySelector("a[aria-label='Settings']")?.getAttribute("href")).toBe("/of-manager/settings/notifications");
    applyData(doc, p, { notificationsStatus: null });
    expect(emptyTab()).toEqual(["Loading notifications…"]);
    applyData(doc, p, { notificationsStatus: "Relay down" });
    expect(emptyTab()).toEqual(["Could not load notifications: Relay down"]);
    applyData(doc, p, { notifications: [] });
    expect(emptyTab()).toEqual(["No notifications currently!"]);
    applyData(doc, p, {});
    expect(doc.documentElement.innerHTML).toBe(html);
  });

  // [href, count text or null] per tab shown.
  const tabCounts = (doc: Document) =>
    shown(doc, "a.b-tabs__nav__link[href^='/of-manager/notifications']").map((a) => [
      a.getAttribute("href"),
      shown(doc, ".b-tabs__nav__count").find((c) => a.contains(c))?.textContent ?? null,
    ]);

  it.each(NOTIF_TABS)("%s: the tab bar shows the Creator's counts (All capped at 99, Tags its newTagsCount), none at zero; no data restores it", (p) => {
    const doc = load(p);
    const html = doc.documentElement.innerHTML;
    const counts = { all: 120, subscribed: 3, purchases: 0, tip: 12000, commented: 1 };
    applyData(doc, p, { notificationCounts: { counts, tags: 2 } });
    const want: Record<string, string | null> = {
      "/of-manager/notifications": " 99+ ",
      "/of-manager/notifications/subscribed": " 3 ",
      "/of-manager/notifications/purchases": null,
      "/of-manager/notifications/tip": " 9999+ ",
      "/of-manager/notifications/tags": " 2 ",
      "/of-manager/notifications/commented": " 1 ",
    };
    const got = tabCounts(doc);
    expect(got.length).toBeGreaterThanOrEqual(10);
    for (const [href, text] of got) expect(text).toBe(want[href!] ?? null);
    applyData(doc, p, { notificationCounts: { counts: {} } });
    expect(tabCounts(doc).every(([, t]) => t === null)).toBe(true);
    applyData(doc, p, {});
    expect(doc.documentElement.innerHTML).toBe(html);
  });
});

const STREAMS: PastStream[] = [
  { id: 1, media: { files: { thumb: { url: "https://cdn.example/s1.jpg" } } }, viewsCount: 7, startedAt: "2026-10-09T21:30:00" },
  { id: 2, media: null, viewsCount: 1, startedAt: "2026-10-08T10:00:00" },
  { id: 3, media: { files: {} }, startedAt: "bad" },
];

describe("streaming dashboard: the Creator's past live streams", () => {
  const P = "streaming/dashboard";
  // [img src, button, viewers, date, its hover stamp] per thumb shown.
  const thumbs = (doc: Document) =>
    shown(doc, ".b-s-dashboard__thumbs > .b-s-dashboard__thumb-holder").map((t) => [
      t.querySelector("img")?.getAttribute("src") ?? null,
      t.querySelector(".b-s-dashboard__btn button")?.textContent,
      t.querySelector(".b-s-dashboard__thumb-content__viewers")?.textContent,
      t.querySelector(".b-s-dashboard__thumb-content__time span")?.textContent ?? null,
      t.querySelector(".b-s-dashboard__thumb-content__time span")?.getAttribute("title") ?? null,
    ]);

  it("gives the dashboard the past streams, the schedule form Home's right column and Go live nothing", () => {
    expect(partsOf(P)).toEqual(["pastStreams"]);
    expect(partsOf("streaming/index")).toEqual([]);
    expect(partsOf("streaming/dashboard/create")).toEqual(["promotions", "events"]);
  });

  it("one thumb per stream with media, in OF's markup; the empty-list centring goes; no data restores the capture byte for byte", () => {
    const doc = load(P);
    const html = doc.documentElement.innerHTML;
    applyData(doc, P, { pastStreams: STREAMS }, (u) => `/img?u=${u}`);
    expect(thumbs(doc)).toEqual([
      ["/img?u=https://cdn.example/s1.jpg", " View stats ", " Viewers: 7", " Oct 9 ", "Oct 9, 9:30 pm"],
      [null, " View stats ", " Viewers: 0", null, null],
    ]);
    const scope = doc.querySelector(".b-s-dashboard__thumbs")!.getAttributeNames().filter((a) => a.startsWith("data-v-"));
    expect(scope.length).toBe(1);
    expect(doc.querySelector(".b-s-dashboard__thumb-holder")!.hasAttribute(scope[0])).toBe(true);
    expect(doc.querySelector(".g-sides-gaps")!.classList.contains("d-flex")).toBe(false);
    expect(doc.querySelector(".infinite-loading-container")!.classList.contains("mt-auto")).toBe(false);
    applyData(doc, P, {});
    expect(doc.documentElement.innerHTML).toBe(html);
  });

  it("no stream with media keeps the capture", () => {
    const doc = load(P);
    const html = doc.documentElement.innerHTML;
    applyData(doc, P, { pastStreams: [STREAMS[1]] });
    expect(doc.documentElement.innerHTML).toBe(html);
  });

  it("View stats (OF's stats modal, never captured) is disabled with the tooltip and sends nothing", () => {
    const doc = load(P);
    applyData(doc, P, { pastStreams: STREAMS });
    const handlers = { saveProfile: vi.fn(), setReplyOnSubscribe: vi.fn(), submit: vi.fn(), navigate: vi.fn() };
    const unbind = bindWrites(doc, P, handlers);
    const stats = shown(doc, ".b-s-dashboard__btn button") as HTMLButtonElement[];
    expect(stats.map((b) => [b.disabled, b.title])).toEqual([
      [true, NOT_YET],
      [true, NOT_YET],
    ]);
    stats[0].click();
    expect(doc.getElementById("oi-note")).toBeNull();
    expect(handlers.submit).not.toHaveBeenCalled();
    unbind();
  });

  it("shows no captured example: the dashboard's list is OF's empty one", () => {
    const doc = load(P);
    expect(doc.querySelectorAll(".b-s-dashboard__thumb-holder")).toHaveLength(0);
  });
});

describe("Go live: Inflowwww cannot stream, so every control is quietly disabled", () => {
  const P = "streaming/index";

  it("Start Live Video shows, disabled with the tooltip; the option rows, switches and description are disabled too", () => {
    const doc = load(P);
    const start = doc.querySelector<HTMLButtonElement>(".b-streaming__btn-start")!;
    expect([start.disabled, start.title, start.style.display, start.textContent!.trim()]).toEqual([true, NOT_YET, "", "Start Live Video"]);
    const rows = [...doc.querySelectorAll<HTMLElement>(".b-streaming-details__row")];
    expect(rows.length).toBe(6);
    for (const r of rows) expect([r.title, r.getAttribute("aria-disabled"), r.classList.contains("g-pointer-cursor")]).toEqual([NOT_YET, "true", false]);
    const fields = [...doc.querySelectorAll<HTMLInputElement | HTMLTextAreaElement>(".b-streaming-details input, .b-streaming-details textarea")];
    expect(fields.map((f) => [f.tagName, f.disabled])).toEqual([
      ["INPUT", true],
      ["INPUT", true],
      ["TEXTAREA", true],
    ]);
  });

  it("the camera's endless loading says it is not available instead", () => {
    const doc = load(P);
    expect(doc.querySelector(".b-stream-status-connect")!.textContent!.trim()).toBe(NOT_YET);
    expect(doc.querySelector(".b-text-progress__dots")).toBeNull();
  });

  it("no enabled button: a click anywhere sends nothing and shows no Read-only note", () => {
    const doc = load(P);
    const handlers = { saveProfile: vi.fn(), setReplyOnSubscribe: vi.fn(), submit: vi.fn(), navigate: vi.fn() };
    const unbind = bindWrites(doc, P, handlers);
    expect([...doc.querySelectorAll<HTMLButtonElement>(".l-streaming-container button")].filter((b) => !b.disabled)).toEqual([]);
    for (const r of doc.querySelectorAll<HTMLElement>(".b-streaming-details__row")) r.click();
    expect(doc.getElementById("oi-note")).toBeNull();
    expect(handlers.submit).not.toHaveBeenCalled();
    unbind();
  });
});

describe("the stream schedule form: no captured example in its right column", () => {
  const P = "streaming/dashboard/create";

  it("no example price, bundle count, promotion or banner; the price line waits for the Creator's own", () => {
    const doc = load(P);
    expect(shown(doc, ".b-feed__aside .b-offer-join")).toEqual([]); // only OF's card, kept hidden as applyPromotions' template
    expect(doc.querySelectorAll(".b-feed__aside .b-offer-join")).toHaveLength(1);
    expect(doc.querySelector(".b-feed__aside")!.textContent).not.toMatch(/subscription bundles/);
    expect(doc.querySelector(".banner_place")).toBeNull();
    const price = doc.querySelector<HTMLElement>("[data-oi-price]")!;
    expect(price.style.display).toBe("none");
    applyIdentity(doc, { id: 4242, username: "synthcreator", name: "Synthetic Creator", subscribePrice: 9.99 });
    expect(price.style.display).toBe("");
    expect(price.textContent).toContain("$9.99");
  });

  it("the Creator's promotions and Scheduled events, as on Home; no data restores the capture", () => {
    const doc = load(P);
    const html = doc.documentElement.innerHTML;
    const now = new Date(2026, 9, 17, 12, 0);
    applyData(doc, P, {
      promotions: [{ id: 1, message: "Synthetic welcome", price: 0, type: "new", subscribeDays: 7, isFinished: false, canClaim: true }],
      events: [{ id: 4, type: "stream", publishDateTime: "2026-10-25T20:00:00", entity: { id: 40, text: "Live" } }],
      now,
    });
    expect(texts(doc, ".b-offer-join .b-menu-list__text")).toEqual(["Limited offer - Free trial for 7 days!"]);
    expect([...doc.querySelectorAll(".b-widget__events > div")].map((r) => r.lastElementChild!.textContent)).toEqual(["Stream · Live"]);
    applyData(doc, P, {});
    expect(doc.documentElement.innerHTML).toBe(html);
  });

  it("search, Add cover and the editor's format button (no source) are disabled with the tooltip; SCHEDULE and Scheduled events' + (Add to queue) are not", () => {
    const doc = load(P);
    const off = [
      doc.querySelector<HTMLInputElement>("input[name='feed-search-input']")!,
      doc.querySelector<HTMLButtonElement>(".post_media__controls button")!,
      doc.querySelector<HTMLButtonElement>(".b-icon-text-container button")!,
    ];
    expect(off.map((e) => [e.disabled, e.title])).toEqual(off.map(() => [true, NOT_YET]));
    const plus = doc.querySelector<HTMLButtonElement>("[at-attr='add_event_widget']")!;
    expect([plus.disabled, plus.title, plus.hasAttribute("data-oi-wired")]).toEqual([false, "", true]);
    expect(doc.querySelector<HTMLButtonElement>(".g-page__header > button.g-btn")!.disabled).toBe(false);
    expect(doc.querySelector(".b-widget__footer a")!.getAttribute("href")).toBe("/of-manager/queue"); // View queue: OF's link
  });
});

/** OF's own /payouts/transactions pages, captured through the Relay and scrubbed (app/lib/__fixtures__/of). */
const fixture = <T,>(name: string): T => JSON.parse(readFileSync(resolve(__dirname, `__fixtures__/of/statements-${name}.json`), "utf8")) as T;
type TxnPage = { list: Transaction[]; hasMore: boolean; nextMarker: number | null; marker: number };
const PAGE = fixture<TxnPage>("transactions"); // six rows, no more
const MORE = fixture<TxnPage>("transactions-more"); // OF's limit=2: two rows and hasMore
const EMPTY_PAGE = fixture<TxnPage>("transactions-empty"); // a page past the end: no rows
const TXNS = PAGE.list;
// The Agency's time zone (Settings): the dates read the same wherever the tests run.
const TZ = "Europe/Ljubljana";
const EARNINGS = "statements/earnings";
const txns = (doc: Document) => shown(doc, ".b-table tbody > tr").filter((r) => r.querySelector(".b-table__date"));
// [date, time, amount, fee, net, description HTML, [[tip label, icon] per status tip]] per row shown.
const txnRows = (doc: Document) =>
  txns(doc).map((r) => [
    r.querySelector(".b-table__date__date > span")!.textContent,
    r.querySelector(".b-table__date__time > span")!.textContent,
    r.querySelector(".b-table__amount > span")!.textContent,
    r.querySelector(".b-table__fee > span")!.textContent,
    r.querySelector(".b-table__net strong > span")!.textContent,
    r.querySelector(".b-table__desc .b-field-subscription")!.innerHTML,
    [...r.querySelectorAll(".b-table__status-tip")].map((t) => [t.getAttribute("aria-label"), t.querySelector("svg")!.getAttribute("data-icon-name")]),
  ]);
const COMPLETE = ["Complete", "icon-done"];
const DONE = [COMPLETE, COMPLETE];
const MESSAGE = "Payment for message from Synth Fan Two";
const WANT_TXNS = [
  [" Oct 12, 2026 ", " 11:41 am ", " $5.00 ", " $1.00 ", " $4.00 ", "Subscription from Synth Fan One", DONE],
  [" Aug 3, 2026 ", " 8:22 pm ", " $4.00 ", " $0.80 ", " $3.20 ", MESSAGE, DONE],
  [" Aug 3, 2026 ", " 7:05 pm ", " $25.00 ", " $5.00 ", " $20.00 ", MESSAGE, DONE],
  [" Aug 3, 2026 ", " 6:47 pm ", " $4.00 ", " $0.80 ", " $3.20 ", MESSAGE, DONE],
  [" Aug 3, 2026 ", " 6:12 pm ", " $30.00 ", " $6.00 ", " $24.00 ", MESSAGE, DONE],
  [" Aug 3, 2026 ", " 5:58 pm ", " $15.00 ", " $3.00 ", " $12.00 ", MESSAGE, DONE],
];
const EMPTY_ROW = ".b-table tbody .empty-message";
const NOTE_TZ = ".b-statements__head-timezone";
/** The page as captured outside the table's rows and its time zone note (Earnings): the balance boxes and the tabs. */
const outsideRows = (doc: Document) => {
  const c = doc.documentElement.cloneNode(true) as Element;
  c.querySelector(".b-table tbody")!.remove();
  c.querySelector(NOTE_TZ)?.remove();
  return c.outerHTML;
};
/** OF's infinite loading row's prompts shown: spinner, no more, no results, error. */
const prompts = (doc: Document) => [...doc.querySelectorAll<HTMLElement>(".infinite-loading-container > .infinite-status-prompt")].map((p) => p.style.display !== "none");

describe("statements/earnings: the Creator's earning transactions (OF's captured pages)", () => {
  it("gives Earnings the transactions", () => {
    expect(partsOf(EARNINGS)).toEqual(["transactions"]);
  });

  it("one row per transaction, in order, before the loading row: OF's money, dates in the Agency's zone, descriptions as text, a deleted fan greyed", () => {
    const doc = load(EARNINGS);
    const outside = outsideRows(doc);
    // At the fixtures' "now" (summer time), so the zone note does not follow today's date.
    atFixtureNow(() => applyData(doc, EARNINGS, { transactions: TXNS, zone: TZ }));
    expect(txnRows(doc)).toEqual(WANT_TXNS);
    const rows = txns(doc);
    expect(rows.every((r) => r.hasAttribute("data-oi-data"))).toBe(true);
    expect(rows.map((r) => r.querySelectorAll(".b-table__desc a").length)).toEqual([0, 0, 0, 0, 0, 0]);
    // The capture's fan is active; the second fan is deleted (OF: isDeleted || !isActive).
    expect(rows.map((r) => r.querySelector(".b-field-subscription")!.classList.contains("m-disabled-username"))).toEqual([false, true, true, true, true, true]);
    for (const r of rows) expect(r.textContent).not.toMatch(PLACEHOLDER);
    expect(texts(doc, NOTE_TZ)).toEqual(["Date/Time shown in local time (UTC +02:00)"]);
    const tbody = doc.querySelector(".b-table tbody")!;
    expect(rows.at(-1)!.nextElementSibling).toBe(tbody.lastElementChild);
    expect(tbody.lastElementChild!.querySelector(".infinite-loading-container")).not.toBeNull();
    expect(outsideRows(doc)).toBe(outside);
  });

  it("OF's UtilsMoney: thousands commas, its m-zero-value on a figure that rounds to 0, the currency's symbol; a pending row's tip; an absent fee empty", () => {
    const doc = load(EARNINGS);
    const [sub] = TXNS;
    applyData(doc, EARNINGS, {
      zone: TZ,
      transactions: [
        { ...sub, amount: 1234.5, fee: 246.9, net: 987.6 },
        { ...sub, amount: 0.4, fee: 0.08, net: 0.32, status: "loading", payoutPendingDays: 5 },
        { ...sub, currency: "EUR", fee: null, status: "loading" },
      ],
    });
    const rows = txnRows(doc);
    expect(rows.map((r) => r.slice(2, 5))).toEqual([
      [" $1,234.50 ", " $246.90 ", " $987.60 "],
      [" $0.40 ", " $0.08 ", " $0.32 "],
      [" €5.00 ", "", " €4.00 "],
    ]);
    expect(rows.map((r) => r[6])).toEqual([DONE, Array(2).fill(["Earning will become available in 5 days", "icon-loading"]), Array(2).fill([null, "icon-loading"])]);
    const zero = txns(doc).map((r) => [".b-table__amount > span", ".b-table__fee > span"].map((s) => r.querySelector(s)!.classList.contains("m-zero-value")));
    expect(zero).toEqual([[false, false], [true, true], [false, false]]);
    expect(ofMoney(12, "cad")).toBe("12.00 CAD");
    expect(ofMoney(1000000, "gbp")).toBe("£1,000,000.00");
  });

  it("the time zone note follows the zone (none: the browser's), as OF's dayjs().format('Z')", () => {
    const summer = new Date("2026-08-03T12:00:00Z");
    expect(zoneNote("Europe/Ljubljana", summer)).toBe("UTC +02:00");
    expect(zoneNote("America/New_York", new Date("2026-01-15T12:00:00Z"))).toBe("UTC -05:00");
    expect(zoneNote("Asia/Kolkata", summer)).toBe("UTC +05:30");
    expect(zoneNote("Not/AZone", summer)).toBe(zoneNote(null, summer));
  });

  it("an empty period (OF's page past the end) keeps OF's empty row; no example row; Creator A's rows then Creator B's leave only B's; no data restores the capture byte for byte", () => {
    const doc = load(EARNINGS);
    const html = doc.documentElement.innerHTML;
    expect(txns(doc)).toEqual([]);
    expect(texts(doc, EMPTY_ROW)).toEqual(["No earnings for this period"]);
    applyData(doc, EARNINGS, { transactions: pageRows([EMPTY_PAGE]), zone: TZ });
    expect(txns(doc)).toEqual([]);
    expect(texts(doc, EMPTY_ROW)).toEqual(["No earnings for this period"]);
    expect(shown(doc, ".infinite-loading-container")).toHaveLength(1);
    applyData(doc, EARNINGS, { transactions: TXNS, zone: TZ });
    applyData(doc, EARNINGS, { transactions: MORE.list.slice(1), zone: TZ });
    expect(txnRows(doc)).toEqual([WANT_TXNS[1]]);
    expect(texts(doc, EMPTY_ROW)).toEqual([]);
    expect(doc.querySelectorAll("[data-oi-data]")).toHaveLength(1);
    applyData(doc, EARNINGS, {});
    expect(doc.documentElement.innerHTML).toBe(html);
  });

  it("OF's pages: the next offset after a page with more, none after the last or an empty one; the pages' rows in order", () => {
    expect(nextOffset(MORE, [MORE])).toBe(2);
    expect(nextOffset(MORE, [MORE, MORE])).toBe(4);
    expect(nextOffset(PAGE, [PAGE])).toBeUndefined();
    expect(nextOffset(EMPTY_PAGE, [MORE, EMPTY_PAGE])).toBeUndefined();
    expect(pageRows([MORE, { ...PAGE, list: PAGE.list.slice(2) }])).toEqual(TXNS);
    expect(pageRows(undefined)).toBeUndefined();
    expect(pageRows([{ error: "502" }])).toBeUndefined();
  });

  it("the loading row: its spinner while the next page is read, Retry after that failed, otherwise the next page once it is in view; no data restores byte for byte", () => {
    const doc = load(EARNINGS);
    const html = doc.documentElement.innerHTML;
    const next = vi.fn();
    applyData(doc, EARNINGS, { transactions: MORE.list, zone: TZ, transactionsMore: { loading: true, error: null, next } });
    expect(prompts(doc)).toEqual([true, false, false, false]);
    applyData(doc, EARNINGS, { transactions: MORE.list, zone: TZ, transactionsMore: { loading: false, error: "502 Bad Gateway", next } });
    expect(prompts(doc)).toEqual([false, false, false, true]);
    doc.querySelector<HTMLButtonElement>(".infinite-loading-container .btn-try-infinite")!.click();
    expect(next).toHaveBeenCalledTimes(1);
    // In view: an IntersectionObserver on OF's loading row asks once, and stops watching. Its root is the frame's own
    // document, so its 300px margin reaches below the frame (the top page's viewport clips a row just under the frame's end).
    const seen: Element[] = [];
    const stop = vi.fn();
    let fire: (e: { isIntersecting: boolean }[]) => void = () => {};
    let options: IntersectionObserverInit | undefined;
    vi.stubGlobal("IntersectionObserver", class {
      constructor(cb: typeof fire, init?: IntersectionObserverInit) {
        fire = cb;
        options = init;
      }
      observe(el: Element) {
        seen.push(el);
      }
      disconnect = stop;
    });
    try {
      applyData(doc, EARNINGS, { transactions: MORE.list, zone: TZ, transactionsMore: { loading: false, error: null, next } });
      expect(prompts(doc)).toEqual([false, false, false, false]);
      expect(seen).toEqual([doc.querySelector(".infinite-loading-container")]);
      expect(options).toEqual({ root: doc, rootMargin: "0px 0px 300px 0px" });
      fire([{ isIntersecting: false }]);
      expect(next).toHaveBeenCalledTimes(1);
      fire([{ isIntersecting: true }]);
      expect(next).toHaveBeenCalledTimes(2);
      // The last page: nothing to ask for.
      seen.length = 0;
      applyData(doc, EARNINGS, { transactions: TXNS, zone: TZ, transactionsMore: { loading: false, error: null, next: null } });
      expect(seen).toEqual([]);
    } finally {
      vi.unstubAllGlobals();
    }
    applyData(doc, EARNINGS, {});
    expect(doc.documentElement.innerHTML).toBe(html);
    doc.querySelector<HTMLButtonElement>(".infinite-loading-container .btn-try-infinite")!.click();
    expect(next).toHaveBeenCalledTimes(2);
  });

  it("while the rows load the empty row says so, and on a Relay error shows it; rows replace it; no data restores byte for byte", () => {
    for (const page of [EARNINGS, "statements/index", PAYOUTS_PAGE, REFERRALS]) {
      const doc = load(page);
      const html = doc.documentElement.innerHTML;
      applyData(doc, page, { statementsStatus: null });
      expect(texts(doc, EMPTY_ROW)).toEqual(["Loading…"]);
      applyData(doc, page, { statementsStatus: "502 Bad Gateway" });
      expect(texts(doc, EMPTY_ROW)).toEqual(["Could not load: 502 Bad Gateway"]);
      applyData(doc, page, {});
      expect(doc.documentElement.innerHTML).toBe(html);
    }
  });
});

// Local times (no Z). In the Relay's order, OF's states (statements-payout.js getDescription): approved twice, rejected
// with and without a reason, pending, new, and a state OF does not know.
const PAYOUTS: Payout[] = [
  { createdAt: "2026-10-10T10:05:00", invoiceId: "INV-1001", amount: 120, state: "approved" },
  { createdAt: "2026-10-09T21:30:00", invoiceId: 1002, amount: 45.5, state: "approved" },
  { createdAt: "2026-10-08T08:00:00", invoiceId: "INV-1003", amount: 300, state: "rejected", rejectReason: "Alpha One's bank details are wrong" },
  { createdAt: "2026-10-07T12:00:00", invoiceId: "INV-1004", amount: 10, state: "rejected" },
  { createdAt: "2026-10-06T12:00:00", invoiceId: "INV-1005", amount: 20, state: "pending" },
  { state: "new" },
  { state: "done" },
];
const PAYOUTS_PAGE = "statements/payouts";
const REFERRALS = "statements/referrals";
// The `payoutRow` template as useOfData borrows it: the payouts capture, parsed inertly.
const PAYOUT_TPL = TEMPLATES.payoutRow!.pick(new DOMParser().parseFromString(capture(TEMPLATES.payoutRow!.page), "text/html"))!;
// [date, time, invoice, amount, status cell HTML] per payout row shown.
const payoutRows = (doc: Document) =>
  txns(doc).map((r) => [
    r.querySelector(".b-table__date__date > span")!.textContent,
    r.querySelector(".b-table__date__time > span")!.textContent,
    r.querySelector(".b-table__invoice")!.textContent,
    r.querySelector(".b-table__amount strong > span")!.textContent,
    r.querySelector(".b-table__desc")!.innerHTML,
  ]);
const APPROVED = '<span class="approved">Payout has been processed<svg aria-hidden="true" class="g-icon"><use href="#icon-done"></use></svg></span>';
const REJECTED = "Payout request could not be processed and this amount was returned to your Current Balance.";
const ALERT = '<svg aria-hidden="true" class="g-icon"><use href="#icon-alert"></use></svg>';
// OF's pending mark without its text (OF's wording was never captured).
const PENDING = '<span class="pending"><svg aria-hidden="true" class="g-icon"><use href="#icon-loading"></use></svg></span>';
const WANT_PAYOUTS = [
  [" Oct 10, 2026 ", " 10:05 am ", " INV-1001 ", " $120.00 ", APPROVED],
  [" Oct 9, 2026 ", " 9:30 pm ", " 1002 ", " $45.50 ", APPROVED],
  [" Oct 8, 2026 ", " 8:00 am ", " INV-1003 ", " $300.00 ", `<span class="rejected">${REJECTED}<br>Reason: Alpha One's bank details are wrong${ALERT}</span>`],
  [" Oct 7, 2026 ", " 12:00 pm ", " INV-1004 ", " $10.00 ", `<span class="rejected">${REJECTED}${ALERT}</span>`],
  [" Oct 6, 2026 ", " 12:00 pm ", " INV-1005 ", " $20.00 ", PENDING],
  ["", "", "", "", PENDING],
  ["", "", "", "", ""],
];
const ONE_PAYOUT: Payout[] = [{ createdAt: "2026-10-01T12:00:00", invoiceId: "INV-2001", amount: 7, state: "approved" }];
const WANT_ONE = [[" Oct 1, 2026 ", " 12:00 pm ", " INV-2001 ", " $7.00 ", APPROVED]];
const REFERRAL_EMPTY = ".b-table tbody .empty-message";

describe("statements/payouts and statements/referrals: the Creator's payout requests", () => {
  it("gives Payouts the payouts and Referrals the referrals", () => {
    expect(partsOf(PAYOUTS_PAGE)).toEqual(["payouts"]);
    expect(partsOf(REFERRALS)).toEqual(["referrals"]);
  });

  it("the payoutRow template is the payouts page's first approved row", () => {
    expect(TEMPLATES.payoutRow!.page).toBe(PAYOUTS_PAGE);
    expect(PAYOUT_TPL.matches(".b-table tbody tr")).toBe(true);
    expect(PAYOUT_TPL.querySelector(".b-table__date__date > span")?.textContent).toBe(" Aug 19, 2026 ");
    expect(PAYOUT_TPL.querySelector(".b-table__desc")?.innerHTML).toBe(APPROVED);
  });

  it("payouts: one row per request, in order, before the loading row: approved, rejected with and without a reason, other states, absent fields as mapped", () => {
    const doc = load(PAYOUTS_PAGE);
    const outside = outsideRows(doc);
    applyData(doc, PAYOUTS_PAGE, { payouts: PAYOUTS });
    expect(payoutRows(doc)).toEqual(WANT_PAYOUTS);
    const rows = txns(doc);
    expect(rows.every((r) => r.hasAttribute("data-oi-data"))).toBe(true);
    const tbody = doc.querySelector(".b-table tbody")!;
    expect(rows.at(-1)!.nextElementSibling).toBe(tbody.lastElementChild);
    expect(tbody.lastElementChild!.querySelector(".infinite-loading-container")).not.toBeNull();
    // "Request withdrawal" stays disabled and the balance as captured.
    expect(outsideRows(doc)).toBe(outside);
    expect(doc.querySelector<HTMLButtonElement>("button.g-btn.m-rounded[disabled]")?.textContent?.trim()).toBe("Request withdrawal");
  });

  it("payouts: no example row, OF's empty row; an empty list keeps it; Creator A's rows then Creator B's leave only B's; no data restores the capture byte for byte", () => {
    const doc = load(PAYOUTS_PAGE);
    const html = doc.documentElement.innerHTML;
    expect(txns(doc)).toEqual([]);
    expect(texts(doc, EMPTY_ROW)).toEqual(["This list is empty"]);
    applyData(doc, PAYOUTS_PAGE, { payouts: [] });
    expect(txns(doc)).toEqual([]);
    expect(texts(doc, EMPTY_ROW)).toEqual(["This list is empty"]);
    expect(shown(doc, ".infinite-loading-container")).toHaveLength(1);
    applyData(doc, PAYOUTS_PAGE, { payouts: PAYOUTS });
    applyData(doc, PAYOUTS_PAGE, { payouts: ONE_PAYOUT });
    expect(payoutRows(doc)).toEqual(WANT_ONE);
    expect(doc.querySelectorAll("[data-oi-data]")).toHaveLength(1);
    applyData(doc, PAYOUTS_PAGE, {});
    expect(doc.documentElement.innerHTML).toBe(html);
  });

  it("referrals: the borrowed row per referral payout, in order, as payouts map them; the empty-message row hidden while rows show", () => {
    const doc = load(REFERRALS);
    const outside = outsideRows(doc);
    applyData(doc, REFERRALS, { referrals: PAYOUTS, templates: { payoutRow: PAYOUT_TPL } });
    expect(payoutRows(doc)).toEqual(WANT_PAYOUTS);
    expect(txns(doc).every((r) => r.hasAttribute("data-oi-data") && r.ownerDocument === doc)).toBe(true);
    expect(shown(doc, REFERRAL_EMPTY)).toEqual([]);
    // The referral balance and "Request withdrawal" stay as captured.
    expect(outsideRows(doc)).toBe(outside);
  });

  it("referrals: an empty list keeps \"This list is empty\"; no template keeps the page as captured", () => {
    const doc = load(REFERRALS);
    const html = doc.documentElement.innerHTML;
    applyData(doc, REFERRALS, { referrals: [], templates: { payoutRow: PAYOUT_TPL } });
    expect(texts(doc, REFERRAL_EMPTY)).toEqual(["This list is empty"]);
    expect(txns(doc)).toEqual([]);
    applyData(doc, REFERRALS, { referrals: PAYOUTS });
    expect(doc.documentElement.innerHTML).toBe(html);
  });

  it("referrals: Creator A's rows then Creator B's leave only B's; no data restores the capture byte for byte", () => {
    const doc = load(REFERRALS);
    const html = doc.documentElement.innerHTML;
    applyData(doc, REFERRALS, { referrals: PAYOUTS, templates: { payoutRow: PAYOUT_TPL } });
    applyData(doc, REFERRALS, { referrals: ONE_PAYOUT, templates: { payoutRow: PAYOUT_TPL } });
    expect(payoutRows(doc)).toEqual(WANT_ONE);
    expect(doc.querySelectorAll("[data-oi-data]")).toHaveLength(1);
    applyData(doc, REFERRALS, {});
    expect(doc.documentElement.innerHTML).toBe(html);
  });
});

/** OF's own /api2/v2 vault responses, captured through the Relay and scrubbed (app/lib/__fixtures__/of/vault-*.json). */
const vaultFixture = <T,>(name: string): T => JSON.parse(readFileSync(resolve(__dirname, `__fixtures__/of/vault-${name}.json`), "utf8")) as T;
const LISTS = vaultFixture<{ list: VaultList[]; all: Partial<VaultList>; sort: string; order: string }>("lists");
const MEDIA = (name: string) => vaultFixture<VaultMediaResp>(`media-${name}`);
const IMG = (u: string) => `/img?u=${u}`;

describe("the Vault page from OF's captured responses (app/lib/__fixtures__/of)", () => {
  const folderRow = (doc: Document, name: string) => shown(doc, ".b-rows-lists__item").find((r) => r.querySelector(".b-rows-lists__item__name")?.textContent?.trim() === name)!;
  const covers = (row: Element) => shown(row.ownerDocument, ".b-media-set img").filter((i) => row.contains(i)).map((i) => i.getAttribute("src"));
  const counts = (row: Element) => row.querySelector(".b-content-inside-thumbs")!.textContent!.replace(/\s+/g, " ").trim();

  it("All media, then every folder in OF's order, with OF's counts and covers; the open one marked; then back", () => {
    const doc = load("vault/index");
    const html = doc.documentElement.innerHTML;
    // Before any data: All media alone, its cover set hidden and pictureless.
    expect(texts(doc, ".b-rows-lists__item__name")).toEqual(["All media"]);
    expect(shown(doc, ".b-media-set")).toEqual([]);
    applyData(doc, "vault/index", { vaultLists: LISTS.list, vaultAll: LISTS.all }, IMG);
    expect(texts(doc, ".b-rows-lists__item__name")).toEqual(["All media", ...LISTS.list.map((l) => l.name)]);
    expect(LISTS.list.map((l) => l.type)).toEqual(expect.arrayContaining(["stories", "messages", "posts", "streams", "custom", "media_stickers"]));
    const all = folderRow(doc, "All media");
    expect(counts(all)).toBe(`${LISTS.all.photosCount} ${LISTS.all.videosCount} ${LISTS.all.gifsCount} ${LISTS.all.audiosCount}`);
    expect(covers(all)).toEqual(LISTS.all.medias!.slice(0, 3).map((m) => IMG(m.url!)));
    for (const l of LISTS.list) {
      const row = folderRow(doc, l.name);
      expect(covers(row)).toEqual((l.medias ?? []).slice(0, 3).map((m) => IMG(m.url!)));
      // OF draws no set at all for a folder without media.
      if (!l.medias?.length) expect(row.querySelector(".b-media-set")).toBeNull();
      expect(row.querySelector("a")!.getAttribute("href")).toBe(`/of-manager/vault?list=${l.id}`);
    }
    const empty = LISTS.list.find((l) => !l.hasMedia)!;
    expect(counts(folderRow(doc, empty.name))).toBe("empty");
    const posts = LISTS.list.find((l) => l.type === "posts")!;
    expect(counts(folderRow(doc, "Posts"))).toBe(`${posts.photosCount} ${posts.videosCount}`);
    expect(texts(doc, "a.m-current .b-rows-lists__item__name")).toEqual(["All media"]);
    applyData(doc, "vault/index", {});
    expect(doc.documentElement.innerHTML).toBe(html);
    applyData(doc, "vault/index", { vaultLists: LISTS.list, vaultAll: LISTS.all, list: String(posts.id) }, IMG);
    expect(texts(doc, "a.m-current .b-rows-lists__item__name")).toEqual(["Posts"]);
    expect(shown(doc, "a[aria-current='page'].b-rows-lists__item__text")).toHaveLength(1);
  });

  it("All media's grid: OF's 24 newest, three to a row, each its thumb, date, and a video's duration and play button", () => {
    const doc = load("vault/index");
    const media = MEDIA("all").list;
    applyData(doc, "vault/index", { vaultMedia: media }, IMG);
    const tiles = shown(doc, ".b-photos .b-photos__item");
    expect(tiles.map((t) => (t as HTMLElement).dataset.oiMedia)).toEqual(media.map((m) => String(m.id)));
    expect(shown(doc, ".b-photos .vue-recycle-scroller__item-view")).toHaveLength(8);
    expect(tiles.map((t) => t.querySelector(".b-photos__item__img")?.getAttribute("src"))).toEqual(media.map((m) => IMG(m.files!.thumb!.url!)));
    media.forEach((m, i) => {
      expect(!!tiles[i].querySelector(".b-photos__item__play-btn")).toBe(m.type === "video");
      if (m.type === "video") expect(tiles[i].querySelector(".m-video-duration span")?.textContent).toMatch(/^\d+:\d\d$/);
      expect(tiles[i].querySelector(".b-element-label.m-timestamp")?.getAttribute("title")).toBeTruthy();
    });
    expect(media.some((m) => m.type === "video")).toBe(true);
    expect(texts(doc, ".b-photos .empty-message")).toEqual([]);
    expect(texts(doc, ".l-main-content.m-r-side .g-page-title > span")).toEqual(["All media"]);
  });

  it("a video's duration as OF writes it; a GIF's and an audio's tile carry the badge under their own icon; an audio keeps the placeholder", () => {
    const doc = load("vault/index");
    const video = MEDIA("video").list[0];
    const [gif, audio] = [MEDIA("gif").list[0], MEDIA("audio").list[0]];
    applyData(doc, "vault/index", { vaultMedia: [video, gif, audio] }, IMG);
    const [v, g, a] = shown(doc, ".b-photos .b-photos__item");
    const badge = (t: Element) => [t.querySelector(".m-video-duration svg")?.getAttribute("data-icon-name"), t.querySelector(".m-video-duration span")?.textContent];
    const pad = (s: number) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
    expect(badge(v)).toEqual(["icon-video", pad(video.duration!)]);
    expect(badge(g)).toEqual(["icon-gif", pad(gif.duration!)]);
    expect(badge(a)).toEqual(["icon-voice", pad(audio.duration!)]);
    expect([v, g, a].map((t) => !!t.querySelector(".b-photos__item__play-btn"))).toEqual([true, false, false]);
    expect(g.querySelector(".b-photos__item__img")?.getAttribute("src")).toBe(IMG(gif.files!.thumb!.url!));
    expect(audio.files?.thumb).toBeNull();
    expect(a.querySelector(".b-photos__item__img")?.getAttribute("src")).toMatch(/^data:/);
  });

  it("each type tab's capture holds only that type, and an open custom folder heads the grid with its name", () => {
    for (const t of ["photo", "gif", "video", "audio"]) expect(new Set(MEDIA(t).list.map((m) => m.type))).toEqual(new Set([t]));
    const doc = load("vault/index");
    const custom = LISTS.list.find((l) => l.type === "custom" && l.hasMedia && (l.videosCount ?? 0) > 0)!;
    const media = MEDIA("list").list;
    applyData(doc, "vault/index", { vaultLists: LISTS.list, vaultAll: LISTS.all, vaultMedia: media, list: String(custom.id) }, IMG);
    expect(texts(doc, ".l-main-content.m-r-side .g-page-title > span")).toEqual([custom.name]);
    expect(shown(doc, ".b-photos .b-photos__item")).toHaveLength(media.length);
    expect(texts(doc, "a.m-current .b-rows-lists__item__name")).toEqual([custom.name]);
  });

  it("search with no match: OF's empty page, and the grid's Nothing found", () => {
    const doc = load("vault/index");
    expect(MEDIA("search")).toEqual({ list: [], hasMore: false });
    applyData(doc, "vault/index", { vaultLists: LISTS.list, vaultAll: LISTS.all, vaultMedia: MEDIA("search").list }, IMG);
    expect(texts(doc, ".b-photos .empty-message")).toEqual(["Nothing found"]);
  });
});

describe("the Vault page's infinite scroll (OF's offset pages)", () => {
  it("asks for the next 24 at the media so far while OF says hasMore, and stops when it does not", () => {
    expect(nextVaultOffset([MEDIA("all")])).toBe(24);
    expect(MEDIA("all").hasMore).toBe(true);
    for (const done of ["gif", "audio", "search"]) expect(nextVaultOffset([MEDIA(done)])).toBeUndefined();
    expect(nextVaultOffset([])).toBeUndefined();
  });

  it("lists each media once: OF's page 2 repeated two of page 1's", () => {
    const [one, two] = [MEDIA("all").list, MEDIA("page2").list];
    const repeated = two.filter((m) => one.some((o) => o.id === m.id));
    expect(repeated.length).toBeGreaterThan(0);
    const merged = vaultPageMedia([MEDIA("all"), MEDIA("page2")]);
    expect(merged.map((m) => m.id)).toEqual([...one, ...two.filter((m) => !repeated.includes(m))].map((m) => m.id));
  });

  it("its own key under the model's mirror data, OF's offset on the path, off without a model or a path", async () => {
    const path = "/api/of/v2/vault/media?limit=24&type=video";
    const q = vaultPagesQuery("1", path);
    expect(q.queryKey).toEqual(["of-mirror-data", "1", path, "pages"]);
    expect([q.enabled, vaultPagesQuery(null, path).enabled, vaultPagesQuery("1", null).enabled]).toEqual([true, false, false]);
    const relay = await import("./relay");
    const get = vi.spyOn(relay.relay, "get").mockResolvedValue(MEDIA("video"));
    await (q.queryFn as (c: { pageParam: number }) => Promise<unknown>)({ pageParam: 24 });
    // Past the Relay's day-long vault cache, as OF's own Vault reads every page fresh.
    expect(get).toHaveBeenCalledWith(`${path}&offset=24`, { accountId: "1" }, undefined, { refresh: true });
    get.mockRestore();
  });

  it("pages only on the Vault page itself, not a composer's vault dialog", () => {
    expect(["vault/index", "vault/list", "vault/state-sort-dropdown"].every(isVaultPage)).toBe(true);
    expect(["new-post/state-vault", "messages/chat/state-vault", "home/state-vault"].some(isVaultPage)).toBe(false);
  });
});

describe("collections/user-lists/list/posts: a list's Posts tab", () => {
  const LISTS = [{ id: 31, name: "Whales", usersCount: 2 }, { id: 32, name: "New", usersCount: 1 }];
  const AUTHORS = { "51": author(51, "Alpha Live", "alphalive", "https://cdn.example/live51.jpg") };
  const tabs = (doc: Document) => shown(doc, ".l-main-content.m-r-side a").filter((a) => /^(Users|Posts)$/.test(a.textContent!.trim()));
  const chips = (doc: Document) => shown(doc, ".g-page-content__header a.b-tabs__nav__link");

  it("asks OF's /lists/{id}/posts, with the chip's type; an unknown postType is All", () => {
    expect(LIST_POSTS).toBe("collections/user-lists/list/posts");
    expect(listPostsPath("tagged", null)).toBe("/api/of/v2/lists/tagged/posts?limit=10");
    expect(listPostsPath("31", "videos")).toBe("/api/of/v2/lists/31/posts?limit=10&type=videos");
    expect([postTypeOf("audios"), postTypeOf("bogus"), postTypeOf(null)]).toEqual(["audios", null, null]);
  });

  it("as generated: the list page with Posts current, OF's No posts yet and its six chips", () => {
    const doc = load(LIST_POSTS);
    expect(tabs(doc).map((a) => [a.textContent!.trim(), a.classList.contains("m-current")])).toEqual([["Users", false], ["Posts", true]]);
    expect(chips(doc).map((a) => a.textContent!.trim())).toEqual(["All", "Photos", "Videos", "Audio", "Other", "Locked"]);
    expect(texts(doc, EMPTY)).toEqual(["No posts yet"]);
    expect(marks(doc)).toEqual([]);
    expect(doc.body.textContent).not.toMatch(PLACEHOLDER);
  });

  it("this page and Bookmarks keep the borrowed post row's icons (Like, Comment, Bookmark, More) in their sprite", () => {
    const icons = [...new Set([...POST_TPL.querySelectorAll("use")].map((u) => u.getAttribute("href")!))];
    expect(icons).toEqual(expect.arrayContaining(["#icon-like", "#icon-comment", "#icon-bookmark", "#icon-more"]));
    for (const p of [LIST_POSTS, BOOKMARKS_PAGE]) {
      const doc = load(p);
      expect(icons.filter((i) => !doc.querySelector(`#of-svg-sprite symbol${i}`)), p).toEqual([]);
    }
  });

  it("the list's posts in the borrowed post row, authors from /users/list; tabs and chips keep the list, the chip's type marked", () => {
    const doc = load(LIST_POSTS);
    applyData(doc, LIST_POSTS, { list: "31", postType: "videos", userLists: LISTS, listPosts: BOOKMARKS, authors: AUTHORS, templates: { post: POST_TPL } }, (u) => `/img?u=${u}`);
    const rows = marks(doc);
    expect(rows.map((r) => r.querySelector(".b-username .g-user-name")!.firstChild!.textContent)).toEqual([" Alpha Live ", " Beta Two ", ""]);
    expect(rows.map((r) => r.querySelector(".b-post__text")!.textContent!.trim())).toEqual(["Alpha One wall post", "Beta bookmarked post", "No author post"]);
    expect(rows[0].querySelector(".b-post__avatar img")!.getAttribute("src")).toBe("/img?u=https://cdn.example/live51.jpg");
    expect(shown(doc, EMPTY)).toEqual([]);
    expect(texts(doc, "a.m-current .b-rows-lists__item__name")).toEqual(["Whales"]);
    expect(tabs(doc).map((a) => a.getAttribute("href"))).toEqual(["/of-manager/collections/user-lists/list?list=31", "/of-manager/collections/user-lists/list/posts?list=31"]);
    expect(chips(doc).map((a) => a.getAttribute("href"))).toEqual(
      ["", "&postType=photos", "&postType=videos", "&postType=audios", "&postType=other", "&postType=locked"].map((t) => `/of-manager/collections/user-lists/list/posts?list=31${t}`),
    );
    expect(chips(doc).filter((a) => a.classList.contains("m-current")).map((a) => a.textContent!.trim())).toEqual(["Videos"]);
  });

  it("rows as OF's: the display name bold over name and @handle, Send Tip shown but never sending, a stub post just its header, Like and Comment off", () => {
    const doc = load(LIST_POSTS);
    const authors = { "51": { ...AUTHORS["51"], displayName: "Johnny Sinsr", name: "Johnny Sins", username: "johnnysins" }, "52": author(52, "Beta Two", "betatwo", null) };
    const stub = { id: 803, postedAt: "2026-10-08T09:00:00", author: { id: 52 } } as MirrorPost;
    applyData(doc, LIST_POSTS, { list: "tagged", userLists: LISTS, listPosts: [{ ...BOOKMARKS[0], author: { id: 51 }, canToggleFavorite: true, canComment: true }, stub], authors, me: { id: 4242 }, templates: { post: POST_TPL } }, (u) => `/img?u=${u}`);
    const rows = marks(doc);
    expect(rows.map((r) => r.querySelector(".b-username .g-user-name")!.firstChild!.textContent)).toEqual([" Johnny Sinsr ", " Beta Two "]);
    expect(rows.map((r) => r.querySelector(".g-user-realname")?.textContent ?? null)).toEqual([" Johnny Sins ", null]);
    expect(rows.map((r) => r.querySelector(".g-user-username")!.textContent)).toEqual(["@johnnysins", "@betatwo"]);
    expect(rows[0].querySelector(".g-user-realname")!.nextElementSibling!.classList.contains("g-user-username")).toBe(true);
    const tips = rows.map((r) => r.querySelector<HTMLButtonElement>(".b-post__tools__item.m-with-text-button button[at-attr='post_tip']")!);
    expect(tips.map((b) => [b.textContent!.trim(), b.disabled, b.title, b.querySelector("use")!.getAttribute("href")])).toEqual(Array(2).fill(["Send Tip", true, NOT_YET, "#icon-funds"]));
    expect(rows[1].querySelector(".b-post__text")?.textContent?.trim() ?? "").toBe("");
    expect(rows.map((r) => [".set-favorite-btn", ".send-comment-btn"].map((b) => r.querySelector<HTMLButtonElement>(b)!.disabled))).toEqual([[false, false], [true, true]]);
    expect(doc.querySelector("#of-svg-sprite symbol#icon-funds")).not.toBeNull();
  });

  it("OF's pages of 10: its nextOffset when sent; the loading row trails the rows and asks for the next page in view", () => {
    expect(nextOffset({ list: [{}], hasMore: true, nextOffset: 10 }, [{ list: [{}] }])).toBe(10);
    expect(nextOffset({ list: [{}], hasMore: false, nextOffset: 20 }, [])).toBeUndefined();
    // Overlapping pages: each post once, where it first came; id-less rows all stay.
    expect(uniqueRows(pageRows<{ id?: number }>([{ list: [{ id: 1 }, { id: 2 }] }, { list: [{ id: 2 }, { id: 3 }, {}, {}] }]))).toEqual([{ id: 1 }, { id: 2 }, { id: 3 }, {}, {}]);
    expect(uniqueRows(undefined)).toBeUndefined();
    const doc = load(LIST_POSTS);
    const next = vi.fn();
    let fire: (e: { isIntersecting: boolean }[]) => void = () => {};
    const seen: Element[] = [];
    vi.stubGlobal("IntersectionObserver", class {
      constructor(cb: typeof fire) {
        fire = cb;
      }
      observe(el: Element) {
        seen.push(el);
      }
      disconnect() {}
    });
    try {
      applyData(doc, LIST_POSTS, { list: "31", userLists: LISTS, listPosts: BOOKMARKS, listPostsMore: { loading: false, error: null, next }, templates: { post: POST_TPL } });
      const box = doc.querySelector(`${BODY} .infinite-loading-container`)!;
      expect(seen).toEqual([box]);
      expect(marks(doc).every((r) => r.compareDocumentPosition(box) & Node.DOCUMENT_POSITION_FOLLOWING)).toBe(true);
      fire([{ isIntersecting: true }]);
      expect(next).toHaveBeenCalledTimes(1);
    } finally {
      vi.unstubAllGlobals();
    }
    applyData(doc, LIST_POSTS, { list: "31", userLists: LISTS, listPosts: BOOKMARKS, listPostsMore: { loading: true, error: null, next }, templates: { post: POST_TPL } });
    expect([...doc.querySelectorAll<HTMLElement>(`${BODY} .infinite-loading-container > .infinite-status-prompt`)].map((p) => p.style.display !== "none")).toEqual([true, false, false, false]);
  });

  it("Loading posts… and the red error in No posts yet; no data restores the capture (but keepQuery's kept hrefs)", () => {
    const doc = load(LIST_POSTS);
    const html = doc.documentElement.innerHTML;
    applyData(doc, LIST_POSTS, { list: "31", listPostsStatus: null });
    expect(texts(doc, EMPTY)).toEqual(["Loading posts…"]);
    applyData(doc, LIST_POSTS, { list: "31", listPostsStatus: "boom" });
    expect(texts(doc, EMPTY)).toEqual(["Could not load posts: boom"]);
    applyData(doc, LIST_POSTS, { list: "31", userLists: LISTS, listPosts: [], templates: { post: POST_TPL } });
    expect(texts(doc, EMPTY)).toEqual(["No posts yet"]);
    applyData(doc, LIST_POSTS, { list: "31", postType: "photos", userLists: LISTS, listPosts: BOOKMARKS, templates: { post: POST_TPL } });
    applyData(doc, LIST_POSTS, {});
    expect(doc.documentElement.innerHTML.replace(/ data-oi-href="[^"]*"/g, "")).toBe(html);
  });

  it("the list page's Posts tab opens it, keeping the list", () => {
    const doc = load("collections/user-lists/list");
    applyData(doc, "collections/user-lists/list", { list: "31", userLists: LISTS, listUsers: [] });
    expect(tabs(doc).map((a) => a.getAttribute("href"))).toEqual(["/of-manager/collections/user-lists/list?list=31", "/of-manager/collections/user-lists/list/posts?list=31"]);
  });
});

describe("feedTime: OF's post time (UtilsTime, type feed)", () => {
  const now = new Date("2026-10-18T15:00:00");
  const at = (iso: string) => feedTime(new Date(iso), now);
  it("today relative as dayjs's fromNow, then Yesterday, this year's day, an older year's date; a scheduled one ahead", () => {
    expect(["2026-10-18T14:59:30", "2026-10-18T14:59:00", "2026-10-18T14:58:00", "2026-10-18T14:16:00", "2026-10-18T14:00:00", "2026-10-18T11:00:00", "2026-10-18T00:30:00"].map(at)).toEqual([
      "seconds ago", "1 minute ago", "2 minutes ago", "44 minutes ago", "1 hour ago", "4 hours ago", "15 hours ago",
    ]);
    expect(["2026-10-17T23:59:00", "2026-10-16T12:00:00", "2026-01-02T08:00:00", "2025-12-31T08:00:00"].map(at)).toEqual(["Yesterday", "Oct 16", "Jan 2", "Dec 31, 2025"]);
    expect(["2026-10-18T18:00:00", "2026-10-19T09:05:00", "2026-11-02T21:30:00", "2027-01-03T08:00:00"].map(at)).toEqual(["in 3 hours", "Tomorrow, 9:05 am", "Nov 2, 9:30 pm", "Jan 3 2027, 8:00 am"]);
  });
});

describe("Home's feed and My profile's wall: OF's infinite scroll (U4)", () => {
  const P = (n: number, from = 1) => Array.from({ length: n }, (_, i) => ({ id: from + i }));
  const io = () => {
    const seen: Element[] = [];
    let fire: (e: { isIntersecting: boolean }[]) => void = () => {};
    vi.stubGlobal("IntersectionObserver", class {
      constructor(cb: typeof fire) {
        fire = cb;
      }
      observe(el: Element) {
        seen.push(el);
      }
      disconnect() {}
    });
    return { seen, fire: (v: boolean) => fire([{ isIntersecting: v }]) };
  };

  it("the wall's next page is OF's tailMarker while it says hasMore with rows and a marker that moved", () => {
    expect(nextMarker({ list: P(20), hasMore: true, tailMarker: "1760000000.000000" }, [], null)).toBe("1760000000.000000");
    expect(nextMarker({ list: P(20), hasMore: true, tailMarker: 1760000000 }, [], null)).toBe("1760000000");
    expect(nextMarker({ list: P(20), hasMore: false, tailMarker: "1" }, [], null)).toBeUndefined();
    expect(nextMarker({ list: [], hasMore: true, tailMarker: "1" }, [], null)).toBeUndefined();
    expect(nextMarker({ list: P(20), hasMore: true }, [], null)).toBeUndefined();
    expect(nextMarker({ list: P(20), hasMore: true, tailMarker: "7" }, [], "7")).toBeUndefined();
    expect(nextMarker(P(20), [], null)).toBeUndefined();
  });

  it("the wall reads its first page, then each before the last one's marker", async () => {
    const get = vi.spyOn(relay, "get").mockResolvedValue({ list: [] });
    try {
      const o = markerPagesQuery("a1", "/api/of/v2/users/9/posts?limit=20&format=infinite", true);
      expect(o.queryKey).toEqual(["of-mirror-data", "a1", "/api/of/v2/users/9/posts?limit=20&format=infinite", "pages"]);
      const fn = o.queryFn as unknown as (c: { pageParam: string | null }) => Promise<unknown>;
      await fn({ pageParam: null });
      await fn({ pageParam: "1760000000.5" });
      expect(get.mock.calls.map((c) => c[0])).toEqual(["/api/of/v2/users/9/posts?limit=20&format=infinite", "/api/of/v2/users/9/posts?limit=20&format=infinite&before_publish_time=1760000000.5"]);
      expect(markerPagesQuery("a1", null, true).enabled).toBe(false);
    } finally {
      get.mockRestore();
    }
  });

  it("Home's next offset: OF's hasMore/nextOffset when it sends a list; a bare array has more when it is a full page", () => {
    expect(nextFeedOffset(P(20), [P(20)])).toBe(20);
    expect(nextFeedOffset(P(20, 21), [P(20), P(20, 21)])).toBe(40);
    expect(nextFeedOffset(P(7), [P(20), P(7)])).toBeUndefined();
    expect(nextFeedOffset([], [[]])).toBeUndefined();
    expect(nextFeedOffset({ list: P(20), hasMore: true }, [{ list: P(20) }])).toBe(20);
    expect(nextFeedOffset({ list: P(20), hasMore: false }, [{ list: P(20) }])).toBeUndefined();
  });

  it("Home: OF's loading row trails the feed, asks for the next page in view, spins while it loads, and offers Retry on an error", () => {
    const doc = load("home/index");
    const box = doc.querySelector(".b-feed-content > .infinite-loading-container")!;
    expect(box).not.toBeNull();
    const prompts = () => [...box.querySelectorAll<HTMLElement>(":scope > .infinite-status-prompt")].map((p) => p.style.display !== "none");
    expect(prompts()).toEqual([false, false, false, false]);
    const next = vi.fn();
    const posts = [{ id: 11, author: { id: 515 } }, { id: 12, author: { id: 4242 } }] as MirrorPost[];
    const w = io();
    try {
      applyData(doc, "home/index", { home: posts, templates: { post: POST_TPL }, homeMore: { loading: false, error: null, next } });
      expect(w.seen).toEqual([box]);
      const rows = [...doc.querySelectorAll(".b-feed-content .user_posts [data-oi-post]")];
      expect(rows).toHaveLength(2);
      expect(rows.every((r) => r.compareDocumentPosition(box) & Node.DOCUMENT_POSITION_FOLLOWING)).toBe(true);
      w.fire(false);
      expect(next).not.toHaveBeenCalled();
      w.fire(true);
      expect(next).toHaveBeenCalledTimes(1);
    } finally {
      vi.unstubAllGlobals();
    }
    applyData(doc, "home/index", { home: posts, templates: { post: POST_TPL }, homeMore: { loading: true, error: null, next } });
    expect(prompts()).toEqual([true, false, false, false]);
    applyData(doc, "home/index", { home: posts, templates: { post: POST_TPL }, homeMore: { loading: false, error: "boom", next } });
    expect(prompts()).toEqual([false, false, false, true]);
    box.querySelector<HTMLButtonElement>(".infinite-status-prompt:last-child button")!.click();
    expect(next).toHaveBeenCalledTimes(2);
    applyData(doc, "home/index", {});
    expect(prompts()).toEqual([false, false, false, false]);
  });

  it("My profile: OF's loading row stays under the wall's rows and asks for the next page in view; none when the wall is empty", () => {
    const doc = load("profile/index");
    const box = doc.querySelector(".user_posts .infinite-loading-container")!;
    expect(box).not.toBeNull();
    const next = vi.fn();
    const w = io();
    try {
      applyData(doc, "profile/index", { posts: [{ id: 1 }, { id: 2 }, { id: 3 }] as MirrorPost[], postsMore: { loading: false, error: null, next } });
      const rows = [...doc.querySelectorAll(".user_posts .vue-recycle-scroller__item-view")].filter((r) => !r.closest("[style*='display:none']") && r.querySelector("div.b-post"));
      expect(rows).toHaveLength(3);
      expect(rows.every((r) => r.compareDocumentPosition(box) & Node.DOCUMENT_POSITION_FOLLOWING)).toBe(true);
      expect(w.seen).toEqual([box]);
      w.fire(true);
      expect(next).toHaveBeenCalledTimes(1);
      applyData(doc, "profile/index", { posts: [], postsMore: { loading: false, error: null, next } });
      expect(w.seen).toEqual([box]);
    } finally {
      vi.unstubAllGlobals();
    }
  });
});
