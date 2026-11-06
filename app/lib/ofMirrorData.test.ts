import { describe, expect, it, vi } from "vitest";
import { applyData, DATA_PAGES, mirrorQuery, nextOffset, partsOf, rowsOf, pageRows, uniqueRows } from "./ofMirrorData";
import { vaultMediaOf } from "./ofMirrorDataQueries";
import { LIST_POSTS, listPostsPath, listSubline, postTypeOf } from "./ofMirrorDataLists";
import { toggleTile } from "./ofMirrorDom";
import { TEMPLATES, type MirrorPost } from "./ofMirrorFeedsShared";
import type { OFMessage, VaultMedia } from "./relay";
import { bindWrites, NOT_YET, READ_ONLY } from "./ofMirrorWrites";
import { applyIdentity } from "./ofMirrorIdentity";
import type { MediaPost } from "./ofMirrorProfile";
import { capture, load, shown, texts, atFixtureNow, PLACEHOLDER, fan, CHATS, msg, MESSAGES, CHAT, POST_TPL } from "./ofMirrorData.fixtures";

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

describe("a wall post's OF rich text (New post's Format text)", () => {
  it.each([
    ["formatted: drawn formatted", '<p><span class="m-editor-fc__blue-1"><strong>Hey</strong></span> babe</p><p><span class="m-editor-fs__l">Large line</span></p>',
      '<p><span class="m-editor-fc__blue-1"><strong>Hey</strong></span> babe</p><p><span class="m-editor-fs__l">Large line</span></p>'],
    ["foreign tags: their text only", '<p><img src=x onerror="a()"><script>alert(1)</script><i>it</i> <font color=red>f</font></p>', "<p><em>it</em> f</p>"],
  ])("%s", (_name, text, html) => {
    const doc = load("profile/index");
    atFixtureNow(() => applyData(doc, "profile/index", { posts: [{ id: 903, text, postedAt: "2026-10-10T10:05:00", media: [] }] }, (u) => u));
    const holder = posts(doc)[0].querySelector(".b-post__text .g-truncated-text > div")!;
    expect(holder.innerHTML.replace(/ data-v-[\w-]+=""/g, "")).toBe(html);
    expect(posts(doc)[0].querySelector("script, img[onerror], font")).toBeNull();
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
      "<p>Alpha <strong>One</strong> wall post</p>", // OF draws the post's markup (b as OF's strong)
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
