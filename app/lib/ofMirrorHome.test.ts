import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, describe, expect, it, onTestFinished, vi } from "vitest";
import { applyData, partsOf } from "./ofMirrorData";
import { promotionTitle, TEMPLATES, type MirrorPost, type Promotion, type QueueItem } from "./ofMirrorFeeds";
import { ARM, bindPostActions as bindActions, type PostHandlers } from "./ofMirrorHome";
import { bindWrites, localIso, NOT_YET, SELECT_MODEL } from "./ofMirrorWrites";
import { bindPost, POSTED_TOAST, type PostHandlers as ComposerHandlers } from "./ofMirrorPost";
import { applyIdentity } from "./ofMirrorIdentity";
import { HOME_VAULT } from "./ofMirrorRow";
import { bindUserLists, openUsers } from "./ofMirrorStatsKit";
import { openPostStats } from "./ofMirrorStatsPostStat";
import { relay } from "./relay";

const load = (p: string) => {
  document.documentElement.innerHTML = readFileSync(resolve(__dirname, `../public/of-mirror/pages/${p}.html`), "utf8");
  return document;
};
const visible = (el: Element) => !el.closest("[style*='display:none']");
const ROW = ".b-feed-content .user_posts .vue-recycle-scroller__item-view";
const rows = (doc: Document) => [...doc.querySelectorAll<HTMLElement>(ROW)].filter(visible);
const PLACEHOLDER = /Fan \d|@fan\d|Lorem/;
const flush = () => new Promise((r) => setTimeout(r, 0));
const ME = "4242";

// Newest first, as the relay sends them: another creator's post, then the Creator's own (pinned) post.
const FEED: MirrorPost[] = [
  {
    id: 11,
    text: "<p>Delta <b>Four</b> post</p>",
    postedAt: "2026-10-10T10:05:00",
    likesCount: 4,
    commentsCount: 1,
    isFavorite: false,
    canToggleFavorite: true,
    canComment: true,
    author: { id: 515 },
    media: [{ id: 1, type: "photo", files: { preview: { url: "https://cdn.example/p11.jpg" } } }],
  },
  { id: 12, text: "Own synthetic post", postedAt: "2026-10-09T21:30:00", likesCount: 0, commentsCount: 0, isPinned: true, canToggleFavorite: false, canComment: true, author: { id: 4242 }, media: [] },
];
const AUTHORS = {
  "515": { id: 515, name: "Delta Four", username: "deltafour", avatar: "https://cdn.example/d4.jpg" },
  "4242": { id: 4242, name: "Synthetic Creator", username: "synthcreator" },
};

// My profile's post row, borrowed as useOfData does (TEMPLATES).
const POST_TPL = TEMPLATES.post!.pick(new DOMParser().parseFromString(readFileSync(resolve(__dirname, `../public/of-mirror/pages/${TEMPLATES.post!.page}.html`), "utf8"), "text/html"))!;
const ME_MINI = { id: 4242, name: "Synthetic Creator", username: "synthcreator" };

const home = (p = "home/index") => {
  const doc = load(p);
  applyData(doc, p, { home: FEED, authors: AUTHORS, templates: { post: POST_TPL }, me: ME_MINI }, (u) => `/img?u=${u}`);
  return doc;
};
const handlers = (over: Partial<PostHandlers> = {}) => {
  const h = {
    me: ME,
    write: vi.fn((_m: string, _p: string, _b?: object) => Promise.resolve({ success: true }) as Promise<unknown>),
    read: vi.fn((_p: string) => Promise.resolve({ list: [{ id: 1, text: "<p>Nice one</p>", author: { id: 7, name: "Echo Five" } }], hasMore: false }) as Promise<unknown>),
    refresh: vi.fn(),
    likes: vi.fn((_id: string, _opener: Element) => {}),
    stats: null as PostHandlers["stats"],
  };
  return { ...h, ...over } as typeof h;
};
const click = (el: Element) => el.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
const row = (doc: Document, i: number) => rows(doc)[i];
const more = (r: Element) => r.querySelector(".b-post__tools__more button")!;
const menuItems = (r: Element) => [...r.querySelectorAll("[data-oi-post-menu] [role=menuitem]")];
const item = (r: Element, text: string) => menuItems(r).find((i) => i.textContent!.trim() === text)!;
const likes = (r: Element) => r.querySelector("a[data-testid='post-stat-likes'] > span")?.textContent;
// Every test loads into the one document: its listeners go after each test.
const unbinds: (() => void)[] = [];
const bindPostActions = (doc: Document, h: PostHandlers) => {
  const unbind = bindActions(doc, h);
  unbinds.push(unbind);
  return unbind;
};
afterEach(() => {
  while (unbinds.length) unbinds.pop()!();
});

describe("home: the home feed", () => {
  it("home and its state pages show the home feed", () => {
    expect(partsOf("home/index")).toEqual(["home", "stories", "promotions", "events"]);
    expect(partsOf("home/state-avatar-menu")).toEqual(["home", "stories", "promotions", "events"]);
  });

  it.each(["home/index", "home/state-feed-tabs-edit"])("%s: one feed row per post, with its author, post id and like state", (p) => {
    const doc = home(p);
    const rs = rows(doc);
    expect(rs).toHaveLength(2);
    expect(rs.map((r) => r.dataset.oiPost)).toEqual(["11", "12"]);
    expect(rs.map((r) => r.dataset.oiAuthor)).toEqual(["515", "4242"]);
    expect(rs.map((r) => r.querySelector(".b-username .g-user-name")!.firstChild!.textContent)).toEqual([" Delta Four ", " Synthetic Creator "]);
    expect(rs.map((r) => r.querySelector(".g-user-username")!.textContent)).toEqual(["@deltafour", "@synthcreator"]);
    expect(rs[0].querySelector(".b-post__avatar img")!.getAttribute("src")).toBe("/img?u=https://cdn.example/d4.jpg");
    expect(rs.map((r) => r.querySelector(".b-post__text")?.textContent?.trim())).toEqual(["Delta Four post", "Own synthetic post"]);
    expect(rs.map(likes)).toEqual(["4", "0"]);
    const stat = (id: string) => rs.map((r) => r.querySelector(`a[data-testid='${id}']`)!.textContent);
    expect([stat("post-stat-likes"), stat("post-stat-comments")]).toEqual([["4 Likes", "0 Likes"], ["1 Comment", "0 Comments"]]);
    expect(rs.map((r) => r.querySelector(".set-favorite-btn")!.classList.contains("m-active"))).toEqual([false, false]);
    expect(rs.map((r) => (r.querySelector(".set-favorite-btn") as HTMLButtonElement).disabled)).toEqual([false, true]);
    expect(rs.map((r) => r.querySelector("div.b-post")!.classList.contains("m-pinned"))).toEqual([false, true]);
    expect(rs.map((r) => r.querySelector(".b-post__date-remaining"))).toEqual([null, null]);
    for (const r of rs) expect(r.textContent).not.toMatch(PLACEHOLDER);
    for (const a of rs[0].querySelectorAll(".b-post__avatar a, a.b-username")) expect(a.getAttribute("href")).toBe("#");
    expect(visible(doc.querySelector(".b-feed-content .user_posts > .empty-message")!)).toBe(false);
    // Labels and Post statistics are the Creator's own-post controls: another creator's row has OF's Send Tip in
    // Post statistics' place instead, shown but never sending (disabled, with the tooltip).
    expect(rs.map((r) => !!r.querySelector(".b-post__labels-controls"))).toEqual([false, true]);
    const tool = rs.map((r) => r.querySelector<HTMLButtonElement>(".b-post__tools__item.m-with-text-button button")!);
    expect(tool.map((b) => b.getAttribute("at-attr"))).toEqual(["post_tip", null]);
    expect(tool[0].textContent!.trim()).toBe("Send Tip");
    expect(tool[0].querySelector("use")!.getAttribute("href")).toBe("#icon-funds");
    expect([tool[0].disabled, tool[0].title]).toEqual([true, NOT_YET]);
    expect(tool[1].textContent!.trim()).toBe("Post statistics");
    // Another creator's More keeps Copy link to post (its author's handle stamped); the Creator's own stays live.
    expect(rs.map((r) => (more(r) as HTMLButtonElement).disabled)).toEqual([false, false]);
    expect(rs.map((r) => r.dataset.oiUsername)).toEqual(["deltafour", undefined]);
  });

  it("the nav drawer: Dark mode, the language menu, Log out and Help and support are disabled with the tooltip; Release forms opens its page; the account switcher stays; Close still links", () => {
    const doc = load("home/state-avatar-menu");
    const nav = doc.querySelector("header.l-header")!;
    // The only live button: the account switcher (ofMirrorIdentity's bindSwitcher).
    expect([...nav.querySelectorAll("button:not([disabled])")]).toEqual([nav.querySelector("[data-oi-switcher] > button")]);
    for (const sel of ["[at-attr='theme_btn']", "[at-attr='logout']", "[data-name='FAQ']"]) expect(nav.querySelector(sel)!.getAttribute("title")).toBe(NOT_YET);
    expect(nav.querySelector("a[data-name='ReleaseForm']")!.getAttribute("href")).toBe("/of-manager/release-forms");
    expect(nav.querySelector("a[at-attr='close_btn']")!.getAttribute("href")).toBe("/of-manager/home");
  });

  it("Pin to home: no captured example list; an empty line instead, Sort disabled with the tooltip", () => {
    const doc = load("home/state-feed-tabs-edit");
    const dialog = doc.querySelector(".b-rows-lists__modal")!;
    expect(dialog.querySelectorAll(".b-rows-lists__item")).toHaveLength(0);
    expect(dialog.querySelector(".b-rows-lists .empty-message")!.textContent!.trim()).toBe("Pinning lists to Home is not available in Inflowwww yet");
    const sort = dialog.querySelector<HTMLButtonElement>("button[aria-label='Sort']")!;
    expect([sort.disabled, sort.title]).toEqual([true, NOT_YET]);
    expect(dialog.textContent).not.toMatch(/List \d+/);
  });

  it.each(["home/index", "home/state-avatar-menu", "home/state-feed-tabs-edit"])("%s: the capture keeps no example post, fan story, expired-subscription alert or promo card", (p) => {
    const doc = load(p);
    const feed = doc.querySelector(".b-feed-content .user_posts")!;
    expect(feed.querySelector(".vue-recycle-scroller__item-view")).toBeNull();
    expect(feed.querySelector(".infinite-loading-container, .infinite-status-prompt")).toBeNull();
    expect(feed.querySelector(":scope > .empty-message")!.textContent!.trim()).toBe("No posts yet");
    expect(doc.querySelector(".b-feed-alerts")).toBeNull();
    expect(doc.querySelector("[at-attr=story_item]")).toBeNull();
    expect(doc.querySelector(".banner_place")).toBeNull();
    expect(doc.body.textContent).not.toMatch(/Fan \d|@fan\d|Lorem|subscription bundles|has expired/);
    expect([...doc.querySelectorAll(".b-offer-join")].filter(visible)).toEqual([]);
  });

  it("no data leaves the empty feed as captured", () => {
    const doc = load("home/index");
    const html = doc.documentElement.innerHTML;
    applyData(doc, "home/index", { home: [], authors: {}, templates: { post: POST_TPL } });
    expect(doc.documentElement.innerHTML).toBe(html);
  });

  it("an author /users/list did not return: the post's own author, else empty; no data restores the capture", () => {
    const doc = load("home/index");
    const html = doc.documentElement.innerHTML;
    applyData(doc, "home/index", { home: [{ ...FEED[0], author: { id: 99, name: "Inline Name" } }, { ...FEED[1], author: undefined }], templates: { post: POST_TPL } });
    expect(rows(doc).map((r) => r.querySelector(".b-username .g-user-name")!.firstChild!.textContent)).toEqual([" Inline Name ", ""]);
    expect(rows(doc)[1].dataset.oiAuthor).toBeUndefined();
    applyData(doc, "home/index", {});
    expect(doc.documentElement.innerHTML).toBe(html);
  });
});

describe("home: the right column", () => {
  const PROMOS: Promotion[] = [
    { id: 1, message: "<p>Synthetic welcome</p>", price: 0, type: "new", claimsCount: 2, subscribeCounts: 10, subscribeDays: 7, isFinished: false, canClaim: true },
    { id: 2, message: "", price: 5, type: "expired", claimsCount: 0, subscribeCounts: 0, subscribeDays: 30, isFinished: false, canClaim: true },
    { id: 3, message: "Ended", price: 0, type: "all", isFinished: true, canClaim: false },
    { id: 4, message: "Spent", price: 0, type: "all", isFinished: false, canClaim: false },
  ];
  const cards = (doc: Document) => [...doc.querySelectorAll<HTMLElement>(".b-offer-join")].filter(visible);

  it("promotionTitle: a free trial, a discount off the subscription price, else the price", () => {
    expect(promotionTitle({ price: 0, subscribeDays: 30 })).toBe("Limited offer - Free trial for 30 days!");
    expect(promotionTitle({ price: 5, subscribeDays: 31 }, 10)).toBe("Limited offer - 50% off for 31 days");
    expect(promotionTitle({ price: 2.5, subscribeDays: 1 })).toBe("Limited offer - $2.50 for 1 day");
    expect(promotionTitle({ price: 12 }, 10)).toBe("Limited offer - $12.00");
  });

  it("one card per promotion on offer, with its title, who it is for, the claims left and its message; no data restores the capture", () => {
    const doc = load("home/index");
    const html = doc.documentElement.innerHTML;
    applyData(doc, "home/index", { promotions: PROMOS, subscribePrice: 10, me: { id: 4242, name: "Synthetic Creator", avatar: "https://cdn.example/me.jpg" } }, (u) => `/img?u=${u}`);
    const cs = cards(doc);
    expect(cs).toHaveLength(2);
    expect(cs.map((c) => c.querySelector(".b-menu-list__text")!.textContent!.trim())).toEqual(["Limited offer - Free trial for 7 days!", "Limited offer - 50% off for 30 days"]);
    expect(cs.map((c) => [...c.querySelectorAll(".b-offer-join__left-time__el")].map((e) => e.textContent!.trim()))).toEqual([["For new subscribers", "left 8"], ["For expired subscribers"]]);
    expect(cs[0].querySelector(".b-offer-join__bubble .g-truncated-text")!.textContent).toBe("Synthetic welcome");
    expect(cs[0].querySelector(".b-offer-join__bubble img")!.getAttribute("src")).toBe("/img?u=https://cdn.example/me.jpg");
    expect(cs[1].querySelector(".b-offer-join__bubble")).toBeNull();
    // OF's toggle chevron goes; Stop promotion stays for ofMirrorOffers (no username here: no Copy link to profile).
    for (const c of cs) expect(c.querySelector(".b-menu-list__icon")).toBeNull();
    expect(cs.map((c) => [...c.querySelectorAll(".b-offer-join__btn button")].map((b) => [b.textContent!.trim(), b.getAttribute("data-oi-finish")]))).toEqual([
      [["Stop promotion", String(PROMOS.filter((p) => !p.isFinished && p.canClaim !== false)[0].id)]],
      [["Stop promotion", String(PROMOS.filter((p) => !p.isFinished && p.canClaim !== false)[1].id)]],
    ]);
    applyData(doc, "home/index", {});
    expect(doc.documentElement.innerHTML).toBe(html);
  });

  it("none on offer: no card", () => {
    const doc = load("home/index");
    applyData(doc, "home/index", { promotions: PROMOS.slice(2) });
    expect(cards(doc)).toEqual([]);
  });

  it("Scheduled events: the three soonest still ahead, in place of the empty message; no data restores the capture", () => {
    const doc = load("home/index");
    const html = doc.documentElement.innerHTML;
    const now = new Date(2026, 9, 17, 12, 0);
    const items: QueueItem[] = [
      { id: 1, type: "post", publishDateTime: "2026-10-17T09:00:00", entity: { id: 10, text: "Gone" } },
      { id: 2, type: "chat", publishDateTime: "2026-10-22T09:00:00", entity: { id: 20, text: "", mediaCount: 2 } },
      { id: 3, type: "post", publishDateTime: "2026-10-20T18:30:00", entity: { id: 30, text: "<p>Soonest</p>" } },
      { id: 4, type: "stream", publishDateTime: "2026-10-25T20:00:00", entity: { id: 40, text: "Live" } },
      { id: 5, type: "post", publishDateTime: "2026-11-01T10:00:00", entity: { id: 50, text: "Fourth" } },
    ];
    applyData(doc, "home/index", { events: items, now });
    const empty = doc.querySelector<HTMLElement>(".b-widget .b-widget__body > .empty-message")!;
    expect(visible(empty)).toBe(false);
    const rs = [...doc.querySelectorAll(".b-widget__events > div")];
    expect(rs.map((r) => r.lastElementChild!.textContent)).toEqual(["Post · Soonest", "Message · Media", "Stream · Live"]);
    // OF drops the "+" once the widget lists events.
    expect(doc.querySelector<HTMLElement>("[at-attr='add_event_widget']")!.style.display).toBe("none");
    applyData(doc, "home/index", {});
    expect(doc.documentElement.innerHTML).toBe(html);
  });
});

describe("home: the composer", () => {
  const TOOL = (doc: Document, label: string) => doc.querySelector<HTMLElement>(`.b-make-post__actions [aria-label='${label}']`)!;
  /** An in-memory Storage, so a test never touches the real sessionStorage. */
  const memory = (): Storage => {
    const m = new Map<string, string>();
    return { get length() { return m.size; }, key: (i) => [...m.keys()][i] ?? null, getItem: (k) => m.get(k) ?? null, setItem: (k, v) => void m.set(k, String(v)), removeItem: (k) => void m.delete(k), clear: () => m.clear() };
  };
  const composer = (over: Partial<ComposerHandlers> = {}) => ({
    createPost: vi.fn((_body: unknown) => Promise.resolve({ id: 1 })),
    createLabel: vi.fn(),
    upload: vi.fn(),
    navigate: vi.fn(),
    posted: vi.fn(),
    ...over,
  });
  const EDITOR = "[contenteditable][aria-label='Textbox field']";
  const POST = "button[at-attr='submit_post']";
  const type = (doc: Document, text: string) => {
    doc.querySelector(EDITOR)!.innerHTML = `<p>${text}</p>`;
    doc.querySelector(EDITOR)!.dispatchEvent(new Event("input", { bubbles: true }));
  };

  /** Each composer tool and the Home State page it opens. */
  const HOME_TOOLS = {
    "Add media from vault": "state-vault",
    "Add poll": "state-poll",
    "Add quiz": "state-quiz",
    "Expiration period": "state-expiration",
    "Schedule post": "state-schedule",
    "Your target": "state-target",
    "Tag other creators": "state-tag-people",
    "Format Text": "state-format-text",
  };

  it("nothing in it leads to New post: every tool opens Home's own dialog or panel, Add media is OF's button, Record video/voice are disabled quietly", () => {
    const doc = load("home/index");
    const form = doc.querySelector("form.b-create-post-form")!;
    expect(form.querySelector("a[href^='/of-manager/new-post']")).toBeNull();
    for (const [label, state] of Object.entries(HOME_TOOLS)) expect(TOOL(doc, label).getAttribute("href"), label).toBe(`/of-manager/home/${state}`);
    expect(TOOL(doc, "Add media").tagName).toBe("BUTTON");
    for (const label of ["Record video", "Record voice"]) {
      const b = TOOL(doc, label) as HTMLButtonElement;
      expect(b.tagName, label).toBe("BUTTON");
      expect(b.disabled, label).toBe(true);
      expect(b.title, label).toBe("Not available in Inflowwww yet");
    }
    const post = doc.querySelector<HTMLButtonElement>(`.b-make-post__actions ${POST}`)!;
    expect(post.textContent!.trim()).toBe("Post");
    expect(post.disabled).toBe(true);
    const headerMore = doc.querySelector<HTMLButtonElement>(".g-page__header button[aria-label='More']")!;
    expect([headerMore.disabled, headerMore.title]).toEqual([true, "Not available in Inflowwww yet"]);
    // The Scheduled events widget's "+" opens Home's schedule dialog too.
    expect(doc.querySelector("[at-attr='add_event_widget']")!.getAttribute("href")).toBe("/of-manager/home/state-schedule");
  });

  it.each(["home/state-schedule", "home/state-vault", "home/state-tag-people", "home/state-expiration", "home/state-target"])("%s is Home with New post's dialog open; its closers go back to Home", (page) => {
    const doc = load(page);
    expect(doc.querySelector(".b-feed-content .user_posts")).not.toBeNull();
    const closers = [...doc.querySelectorAll("a.of-state-backdrop, a.vdatetime-overlay, .modal-footer a")];
    expect(closers.length).toBeGreaterThan(0);
    for (const a of closers) expect(a.getAttribute("href")).toBe("/of-manager/home");
  });

  it.each([
    ["home/state-poll", ".b-make-post__voting", "[aria-label='Delete']"],
    ["home/state-quiz", ".b-make-post__voting", "[aria-label='Delete']"],
    ["home/state-format-text", ".js-text-editor-toolbar", "[aria-label='Close Formatting Panel']"],
  ])("%s is Home with New post's panel in its composer; its close goes back to Home; the other tools stay Home's", (page, panel, close) => {
    const doc = load(page);
    expect(doc.querySelector(".b-feed-content .user_posts")).not.toBeNull();
    const form = doc.querySelector("form.b-create-post-form")!;
    expect(form.querySelector(panel)).not.toBeNull();
    expect(form.querySelector(`a${close}`)!.getAttribute("href")).toBe("/of-manager/home");
    expect(form.querySelector("a[href^='/of-manager/new-post']")).toBeNull();
    const own = `state-${page.split("state-")[1]}`;
    for (const [label, state] of Object.entries(HOME_TOOLS)) if (state !== own) expect(TOOL(doc, label).getAttribute("href"), label).toBe(`/of-manager/home/${state}`);
  });

  it("home/state-poll: typed options go on Home's draft, its duration opens Home's period dialog, whose Save returns to Home's poll; Post sends them", async () => {
    const s = memory();
    const h = composer();
    let doc = load("home/state-poll");
    let unbind = bindPost(doc, "home/state-poll", { handlers: h, storage: s, accountId: "1", draftId: "home:1" });
    const options = [...doc.querySelectorAll<HTMLInputElement>(".b-make-post__voting .vote-input input[at-attr='input']")];
    expect(options.length).toBeGreaterThanOrEqual(2);
    options.forEach((o, i) => {
      o.value = `Option ${i + 1}`;
      o.dispatchEvent(new Event("input", { bubbles: true }));
    });
    expect(JSON.parse(s.getItem("oi:new-post:home:1")!).voting).toMatchObject({ type: 1, options: options.map((_, i) => `Option ${i + 1}`) });
    expect(s.getItem("oi:new-post:1")).toBeNull();
    doc.querySelector<HTMLElement>(".b-make-post__voting .b-post-piece")!.click();
    expect(h.navigate).toHaveBeenCalledWith("/of-manager/home/state-expiration");
    unbind();

    doc = load("home/state-expiration");
    unbind = bindPost(doc, "home/state-expiration", { handlers: h, storage: s, accountId: "1", draftId: "home:1" });
    expect(doc.querySelector(".modal.show .modal-title")!.textContent?.trim()).toBe("POLL DURATION");
    for (const a of doc.querySelectorAll(".modal.show .modal-footer a, .modal.show .of-state-backdrop")) expect(a.getAttribute("href")).toBe("/of-manager/home/state-poll");
    const days = doc.querySelector<HTMLInputElement>(".modal.show input[name='periodValue']")!;
    days.value = "3";
    days.dispatchEvent(new Event("input", { bubbles: true }));
    doc.querySelector<HTMLButtonElement>(".modal.show .modal-footer button")!.click();
    expect(h.navigate).toHaveBeenLastCalledWith("/of-manager/home/state-poll");
    unbind();

    doc = load("home/index");
    unbind = bindPost(doc, "home/index", { handlers: h, storage: s, accountId: "1", draftId: "home:1" });
    type(doc, "Synthetic poll");
    doc.querySelector<HTMLButtonElement>(POST)!.click();
    await flush();
    expect(h.createPost).toHaveBeenCalledTimes(1);
    expect(h.createPost).toHaveBeenCalledWith(expect.objectContaining({ text: "Synthetic poll", voting_type: 1, voting_due: 3 }));
    expect(h.navigate).toHaveBeenCalledTimes(2); // the duration and its Save; Post stays on Home
    unbind();
  });

  it("home/state-target: Save keeps the target on Home's draft and returns to Home", () => {
    const s = memory();
    const h = composer();
    const doc = load("home/state-target");
    const unbind = bindPost(doc, "home/state-target", { handlers: h, storage: s, accountId: "1", draftId: "home:1" });
    const field = doc.querySelector<HTMLInputElement>(".modal.show input[at-attr='input']")!;
    field.value = "25";
    field.dispatchEvent(new Event("input", { bubbles: true }));
    doc.querySelector<HTMLButtonElement>(".modal.show .modal-footer button")!.click();
    expect(JSON.parse(s.getItem("oi:new-post:home:1")!).fund_raising_target).toBe(25);
    expect(h.navigate).toHaveBeenCalledWith("/of-manager/home");
    unbind();
  });

  it("the price line is hidden until the Creator's own price shows (no example price with all models)", () => {
    const doc = load("home/index");
    const line = doc.querySelector<HTMLElement>("[data-oi-price]")!;
    expect(visible(line)).toBe(false);
    applyIdentity(doc, { username: "synthcreator" });
    expect(visible(line)).toBe(false);
    applyIdentity(doc, { subscribePrice: 9.99 });
    expect(visible(line)).toBe(true);
    expect(line.querySelector(".b-amount-price")!.textContent).toBe("$9.99");
  });

  it("Post goes through in place: one POST, no navigation, the composer empties, the feed is refreshed and OF's toast shows", async () => {
    const doc = load("home/index");
    const s = memory();
    const h = composer();
    const unbind = bindPost(doc, "home/index", { handlers: h, storage: s, accountId: "1", draftId: "home:1" });
    const post = doc.querySelector<HTMLButtonElement>(POST)!;
    type(doc, "Synthetic post");
    expect(post.disabled).toBe(false);
    expect(s.getItem("oi:new-post:home:1")).not.toBeNull();
    expect(s.getItem("oi:new-post:1")).toBeNull(); // New post's draft is its own
    post.click();
    await flush();
    expect(h.createPost).toHaveBeenCalledTimes(1);
    expect(h.createPost).toHaveBeenCalledWith({ text: "Synthetic post", media_files: [], price: 0 });
    expect(h.navigate).not.toHaveBeenCalled();
    expect(h.posted).toHaveBeenCalledTimes(1);
    expect(doc.querySelector(EDITOR)!.textContent).toBe("");
    expect(post.disabled).toBe(true);
    expect(s.getItem("oi:new-post:home:1")).toBeNull();
    expect(doc.querySelector(".toasts-host .v-snack.m-alert .toast__text")!.textContent).toBe(POSTED_TOAST);
    unbind();
  });

  it("a scheduled post stays on Home too and names its moment; a failure keeps the draft and shows the red note", async () => {
    const doc = load("home/index");
    const s = memory();
    const at = new Date(Date.now() + 86_400_000);
    at.setSeconds(0, 0);
    s.setItem("oi:new-post:home:1", JSON.stringify({ text: "Later post", tagged_users: [], media_files: [], thumbs: [], posted_at: localIso(at) }));
    const h = composer();
    let unbind = bindPost(doc, "home/index", { handlers: h, storage: s, accountId: "1", draftId: "home:1" });
    doc.querySelector<HTMLButtonElement>(POST)!.click();
    await flush();
    expect(h.createPost).toHaveBeenCalledWith({ text: "Later post", media_files: [], price: 0, posted_at: localIso(at) });
    expect(h.navigate).not.toHaveBeenCalled();
    expect(doc.querySelector(".toast__text")!.textContent).toMatch(/^Your post is scheduled for \w{3}, /);
    unbind();
    const fail = composer({ createPost: vi.fn(() => Promise.reject(new Error("Please allow 10 seconds"))) });
    unbind = bindPost(doc, "home/index", { handlers: fail, storage: s, accountId: "1", draftId: "home:1" });
    type(doc, "Synthetic post");
    doc.querySelector<HTMLButtonElement>(POST)!.click();
    await flush();
    expect(doc.getElementById("oi-note")!.textContent).toBe("Could not post: Please allow 10 seconds");
    expect(JSON.parse(s.getItem("oi:new-post:home:1")!).text).toBe("Synthetic post");
    expect(fail.posted).not.toHaveBeenCalled();
    unbind();
  });

  it("Add media on Home is the upload button (marked wired); All Creators: Post gives the select-a-model note", () => {
    const doc = load("home/index");
    let unbind = bindPost(doc, "home/index", { handlers: composer(), storage: memory(), accountId: "1", draftId: "home:1" });
    expect(TOOL(doc, "Add media").hasAttribute("data-oi-wired")).toBe(true);
    unbind();
    unbind = bindPost(doc, "home/index", { handlers: null, storage: null, accountId: null });
    type(doc, "Synthetic post");
    doc.querySelector<HTMLButtonElement>(POST)!.click();
    expect(doc.getElementById("oi-note")!.textContent).toBe(SELECT_MODEL);
    unbind();
  });

  it("home/state-schedule: Next keeps the moment on Home's draft and returns to Home", () => {
    // Noon, pinned: after 23:00 the default time (now plus an hour) wraps past midnight onto today's date, a moment
    // already past, and Next refuses it.
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date(2026, 9, 17, 12, 0));
    onTestFinished(() => void vi.useRealTimers());
    const doc = load("home/state-schedule");
    const s = memory();
    const h = composer();
    const unbind = bindPost(doc, "home/state-schedule", { handlers: h, storage: s, accountId: "1", draftId: "home:1" });
    doc.querySelector<HTMLButtonElement>(".vdatetime-popup__actions__button--confirm button")!.click();
    expect(h.navigate).toHaveBeenCalledWith("/of-manager/home");
    expect(JSON.parse(s.getItem("oi:new-post:home:1")!).posted_at).toMatch(/^\d{4}-\d{2}-\d{2}T/);
    unbind();
  });

  it("home/state-tag-people: the Creator's taggable rows survive the feed's re-apply; a check goes on Home's draft; unbinding leaves the feed", () => {
    const doc = home("home/state-tag-people");
    const s = memory();
    const tagItems = [{ id: 901, name: "Alpha One", type: "user", user: { id: 901, name: "Alpha One", username: "alphaone" } }];
    const unbind = bindPost(doc, "home/state-tag-people", { handlers: composer(), storage: s, accountId: "1", draftId: "home:1", tagItems });
    const tagRows = () => [...doc.querySelectorAll<HTMLElement>("label.b-rows-lists__item[data-oi-user]")];
    expect(tagRows()).toHaveLength(1);
    // The feed's data arrives again (a refetch): restore and re-apply leave the dialog's rows alone.
    applyData(doc, "home/state-tag-people", { home: FEED, authors: AUTHORS, templates: { post: POST_TPL }, me: ME_MINI });
    expect(tagRows()).toHaveLength(1);
    expect(rows(doc)).toHaveLength(2);
    const box = tagRows()[0].querySelector<HTMLInputElement>("input[type='checkbox']")!;
    box.checked = true;
    box.dispatchEvent(new Event("change", { bubbles: true }));
    expect(JSON.parse(s.getItem("oi:new-post:home:1")!).tagged_users).toEqual([901]);
    unbind();
    expect(tagRows()).toHaveLength(0);
    expect(rows(doc)).toHaveLength(2);
  });

  it("home/state-vault: the Creator's vault media in the dialog over Home; a tile pick goes on Home's draft", () => {
    const doc = load(HOME_VAULT);
    expect(partsOf(HOME_VAULT)).toEqual(["home", "stories", "promotions", "events", "vaultLists", "vaultMedia"]);
    applyData(doc, HOME_VAULT, { vaultMedia: [{ id: 61, type: "photo", files: { thumb: { url: "https://cdn.example/61.jpg" } } }], picked: [] });
    const tile = doc.querySelector<HTMLElement>(".modal [data-oi-media='61']")!;
    expect(tile).not.toBeNull();
    const s = memory();
    const unbind = bindPost(doc, HOME_VAULT, { handlers: composer(), storage: s, accountId: "1", draftId: "home:1" });
    tile.click();
    expect(JSON.parse(s.getItem("oi:new-post:home:1")!).media_files).toEqual([61]);
    unbind();
  });
});

describe("home: the feed's loading and error states", () => {
  const text = (doc: Document) => doc.querySelector<HTMLElement>(".b-feed-content .user_posts > .empty-message > span")!;

  it("'Loading posts…' while the Relay answers, the red error after it failed, 'No posts yet' for an empty feed; then back as captured", () => {
    const doc = load("home/index");
    const html = doc.documentElement.innerHTML;
    applyData(doc, "home/index", { homeStatus: null });
    expect(text(doc).textContent).toBe("Loading posts…");
    applyData(doc, "home/index", { homeStatus: "Relay unreachable" });
    expect(text(doc).textContent).toBe("Could not load posts: Relay unreachable");
    expect(text(doc).style.color).toBe("rgb(255, 69, 69)");
    applyData(doc, "home/index", { home: [], templates: { post: POST_TPL } });
    expect(text(doc).textContent).toBe("No posts yet");
    applyData(doc, "home/index", {});
    expect(doc.documentElement.innerHTML).toBe(html);
  });
});

describe("bindPostActions: like", () => {
  it("another creator's post: POST like with its author id, the heart and the count follow; the same POST unlikes", async () => {
    const doc = home();
    const h = handlers();
    bindPostActions(doc, h);
    const heart = row(doc, 0).querySelector(".set-favorite-btn")!;
    click(heart);
    await flush();
    expect(h.write).toHaveBeenLastCalledWith("POST", "/api/of/v2/posts/11/like?author_id=515");
    expect(heart.classList.contains("m-active")).toBe(true);
    expect(likes(row(doc, 0))).toBe("5");
    click(heart);
    await flush();
    expect(h.write).toHaveBeenCalledTimes(2);
    expect(h.write).toHaveBeenLastCalledWith("POST", "/api/of/v2/posts/11/like?author_id=515");
    expect(heart.classList.contains("m-active")).toBe(false);
    expect(likes(row(doc, 0))).toBe("4");
  });

  it("follows OF's isFavorite when the response has it; a disabled heart sends nothing; a failure notes it", async () => {
    const doc = home();
    const h = handlers({ write: vi.fn(() => Promise.resolve({ success: true, isFavorite: false })) });
    bindPostActions(doc, h);
    const heart = row(doc, 0).querySelector(".set-favorite-btn")!;
    click(heart);
    await flush();
    expect(heart.classList.contains("m-active")).toBe(false);
    expect(likes(row(doc, 0))).toBe("4");
    click(row(doc, 1).querySelector(".set-favorite-btn")!);
    expect(h.write).toHaveBeenCalledTimes(1);
    h.write.mockImplementationOnce(() => Promise.reject(new Error("rate limited")));
    click(heart);
    await flush();
    expect(doc.getElementById("oi-note")!.textContent).toBe("Could not like: rate limited");
  });

  it("the Creator's own post (or one with no author) likes with no author id", async () => {
    const doc = load("profile/index");
    applyData(doc, "profile/index", { posts: [{ id: 21, text: "Wall", postedAt: "2026-10-10T10:05:00", canToggleFavorite: true, canComment: true, media: [] }] });
    const h = handlers();
    bindPostActions(doc, h);
    click(doc.querySelector("[data-oi-post='21'] .set-favorite-btn")!);
    await flush();
    expect(h.write).toHaveBeenCalledWith("POST", "/api/of/v2/posts/21/like");
  });
});

describe("bindPostActions: comments", () => {
  it("opens the post's comments under its tools, posts {text} on Send or Enter, reloads them; a second click closes", async () => {
    const doc = home();
    const h = handlers();
    bindPostActions(doc, h);
    const r = row(doc, 0);
    click(r.querySelector(".send-comment-btn")!);
    await flush();
    expect(h.read).toHaveBeenCalledWith("/api/of/v2/posts/11/comments?limit=20");
    const box = r.querySelector("[data-oi-comments]")!;
    expect(box.hasAttribute("data-oi-wired")).toBe(true);
    expect(box.previousElementSibling!.classList.contains("b-post__tools")).toBe(true);
    expect(box.querySelector(".b-comments__list")!.textContent).toBe("Echo Five Nice one");
    const input = box.querySelector("input")!;
    const send = box.querySelector("[data-oi-send]")!;
    click(send);
    expect(h.write).not.toHaveBeenCalled();
    expect(doc.getElementById("oi-note")!.textContent).toBe("Write a comment first");
    input.value = "  Synthetic comment ";
    click(send);
    await flush();
    expect(h.write).toHaveBeenCalledWith("POST", "/api/of/v2/posts/11/comments", { text: "Synthetic comment" });
    expect(input.value).toBe("");
    expect(r.querySelector("a[data-testid='post-stat-comments'] > span")!.textContent).toBe("2");
    expect(h.read).toHaveBeenCalledTimes(2);
    input.value = "Second";
    input.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true, cancelable: true }));
    await flush();
    expect(h.write).toHaveBeenLastCalledWith("POST", "/api/of/v2/posts/11/comments", { text: "Second" });
    click(r.querySelector(".send-comment-btn")!);
    expect(r.querySelector("[data-oi-comments]")).toBeNull();
  });

  it("a post without OF's canComment / canToggleFavorite (a list's stub) has Comment and Like off: a click reads and writes nothing", async () => {
    const doc = load("home/index");
    applyData(doc, "home/index", { home: [{ id: 13, postedAt: "2026-10-10T10:05:00", author: { id: 515 } }], authors: AUTHORS, templates: { post: POST_TPL }, me: ME_MINI });
    const h = handlers();
    bindPostActions(doc, h);
    const r = row(doc, 0);
    expect([".set-favorite-btn", ".send-comment-btn"].map((b) => r.querySelector<HTMLButtonElement>(b)!.disabled)).toEqual([true, true]);
    click(r.querySelector(".send-comment-btn")!);
    click(r.querySelector(".set-favorite-btn")!);
    await flush();
    expect(h.read).not.toHaveBeenCalled();
    expect(h.write).not.toHaveBeenCalled();
    expect(r.querySelector("[data-oi-comments]")).toBeNull();
  });

  it("no comments, or a failed load, says so", async () => {
    const doc = home();
    const unbind = bindPostActions(doc, handlers({ read: vi.fn(() => Promise.resolve({ list: [] })) }));
    click(row(doc, 0).querySelector(".send-comment-btn")!);
    await flush();
    expect(row(doc, 0).querySelector(".b-comments__list")!.textContent).toBe("No comments yet");
    unbind();
    bindPostActions(doc, handlers({ read: vi.fn(() => Promise.reject(new Error("404"))) }));
    click(row(doc, 1).querySelector(".send-comment-btn")!);
    await flush();
    expect(row(doc, 1).querySelector(".b-comments__list")!.textContent).toBe("Could not load comments: 404");
  });
});

describe("bindPostActions: the row's Likes, Comments and Post statistics", () => {
  it("the generator leaves My profile's N Likes and N Comments live; Post statistics (the post's earnings) is disabled with the tooltip", () => {
    const doc = load("profile/index");
    for (const sel of ["a[data-testid='post-stat-likes']", "a[data-testid='post-stat-comments']"]) expect(doc.querySelector(sel)!.hasAttribute("aria-disabled")).toBe(false);
    const stats = [...doc.querySelectorAll<HTMLButtonElement>(".b-post__tools__item.m-with-text-button button")].find((b) => b.textContent!.trim() === "Post statistics")!;
    expect([stats.disabled, stats.title]).toEqual([true, NOT_YET]);
  });

  it("no stats handler (a role without Statistics, or no probe): Post statistics stays disabled; N Likes still opens the likers", () => {
    const doc = home();
    const h = handlers();
    bindPostActions(doc, h);
    const stats = row(doc, 1).querySelector<HTMLButtonElement>(".b-post__tools__item.m-with-text-button button")!;
    expect([stats.disabled, stats.title]).toEqual([true, NOT_YET]);
    click(row(doc, 1).querySelector("a[data-testid='post-stat-likes']")!);
    expect(h.likes).toHaveBeenCalledTimes(1);
  });

  it("the Creator's own post: N Likes opens its likers, Post statistics (enabled, also on rows drawn later) its popup; N Comments opens the comments box", async () => {
    const doc = home();
    const h = { ...handlers(), stats: vi.fn() };
    const unbind = bindPostActions(doc, h);
    const own = row(doc, 1);
    const tool = (r: Element) => r.querySelector<HTMLButtonElement>(".b-post__tools__item.m-with-text-button button")!;
    expect([tool(own).disabled, tool(own).hasAttribute("title")]).toEqual([false, false]);
    // The feed's data re-applies (fresh rows): their Post statistics too.
    applyData(doc, "home/index", { home: FEED, authors: AUTHORS, templates: { post: POST_TPL }, me: ME_MINI }, (u) => `/img?u=${u}`);
    await flush();
    expect(tool(row(doc, 1)).disabled).toBe(false);
    expect(tool(row(doc, 0)).disabled).toBe(true); // another creator's Send Tip
    unbind();
    expect([tool(row(doc, 1)).disabled, tool(row(doc, 1)).title]).toEqual([true, NOT_YET]);
    bindPostActions(doc, h);
    const fresh = row(doc, 1);
    const likesLink = fresh.querySelector("a[data-testid='post-stat-likes']")!;
    const ev = new MouseEvent("click", { bubbles: true, cancelable: true });
    likesLink.dispatchEvent(ev);
    expect(ev.defaultPrevented).toBe(true);
    expect(h.likes).toHaveBeenCalledWith("12", likesLink);
    const stats = tool(fresh);
    click(stats);
    expect(h.stats).toHaveBeenCalledWith("12", stats);
    click(fresh.querySelector("a[data-testid='post-stat-comments']")!);
    await flush();
    expect(h.read).toHaveBeenCalledWith("/api/of/v2/posts/12/comments?limit=20");
    expect(fresh.querySelector("[data-oi-comments]")).not.toBeNull();
    click(fresh.querySelector("a[data-testid='post-stat-comments']")!);
    expect(fresh.querySelector("[data-oi-comments]")).toBeNull();
  });

  it("wired as useOfPostActions does: OF's Post likes list and Post statistics popup read the Relay with the model's account", async () => {
    const doc = home();
    bindUserLists(doc, { accountId: "acct-1" });
    const get = vi.spyOn(relay, "get").mockResolvedValue({ list: [], hasMore: false } as never);
    onTestFinished(() => get.mockRestore());
    bindPostActions(doc, { ...handlers(), likes: (id, el) => openUsers(doc, `post-likes:${id}:0`, el), stats: (id, el) => openPostStats(doc, id, null, el) });
    click(row(doc, 1).querySelector("a[data-testid='post-stat-likes']")!);
    await vi.waitFor(() => expect(doc.querySelector("#oi-users .modal-title")?.textContent?.trim()).toBe("Post likes"));
    click(row(doc, 1).querySelector(".b-post__tools__item.m-with-text-button button")!);
    await vi.waitFor(() => expect(doc.querySelector("#oi-post-stats .modal-title")?.textContent?.trim()).toBe("Post statistics"));
    expect(get.mock.calls.map((c) => [c[0], c[1]])).toEqual([
      ["/api/of/v2/posts/likes?post_id=12&limit=10&offset=0", { accountId: "acct-1" }],
      ["/api/of/v2/posts/stats?post_id=12", { accountId: "acct-1" }],
    ]);
    for (const id of ["oi-users", "oi-post-stats"]) doc.getElementById(id)?.remove();
  });

  it("another creator's post: N Likes opens nothing and its Send Tip stays off; N Comments still opens the box", async () => {
    const doc = home();
    const h = { ...handlers(), stats: vi.fn() };
    bindPostActions(doc, h);
    const other = row(doc, 0);
    click(other.querySelector("a[data-testid='post-stat-likes']")!);
    click(other.querySelector(".b-post__tools__item.m-with-text-button button")!);
    expect([h.likes, h.stats].map((f) => f.mock.calls.length)).toEqual([0, 0]);
    click(other.querySelector("a[data-testid='post-stat-comments']")!);
    await flush();
    expect(h.read).toHaveBeenCalledWith("/api/of/v2/posts/11/comments?limit=20");
  });
});

describe("bindPostActions: the Creator's own post's More menu", () => {
  it("opens OF's dropdown with pin (by the row's state), edit, archive and delete; a click elsewhere closes it", () => {
    const doc = home();
    bindPostActions(doc, handlers());
    const r = row(doc, 1);
    click(more(r));
    expect(menuItems(r).map((i) => i.textContent!.trim())).toEqual(["Unpin from your profile page", "Edit post", "Archive post", "Delete post"]);
    expect(item(r, "Delete post").classList.contains("m-danger")).toBe(true);
    expect(r.querySelector(".b-post__tools__more")!.classList.contains("m-show-dropdown")).toBe(true);
    click(doc.body);
    expect(menuItems(r)).toEqual([]);
    expect(r.querySelector(".b-post__tools__more")!.classList.contains("m-show-dropdown")).toBe(false);
  });

  it.each([
    ["Unpin from your profile page", "POST", "/api/of/v2/posts/12/pin"],
    ["Archive post", "POST", "/api/of/v2/posts/12/archive"],
  ])("%s: %s %s, then the rows refetch", async (label, method, path) => {
    const doc = home();
    const h = handlers();
    bindPostActions(doc, h);
    click(more(row(doc, 1)));
    click(item(row(doc, 1), label));
    await flush();
    expect(h.write.mock.calls).toEqual([[method, path]]);
    expect(h.refresh).toHaveBeenCalledTimes(1);
    expect(menuItems(row(doc, 1))).toEqual([]);
  });

  it("Delete post asks for a second click, then DELETE /posts/{id} and the rows refetch", async () => {
    const doc = home();
    const h = handlers();
    bindPostActions(doc, h);
    const r = row(doc, 1);
    click(more(r));
    click(item(r, "Delete post"));
    expect(h.write).not.toHaveBeenCalled();
    click(item(r, ARM));
    await flush();
    expect(h.write.mock.calls).toEqual([["DELETE", "/api/of/v2/posts/12"]]);
    expect(h.refresh).toHaveBeenCalledTimes(1);
  });

  it("a failed write notes it in red and refetches nothing", async () => {
    const doc = home();
    const h = handlers({ write: vi.fn(() => Promise.reject(new Error("Post not found"))) });
    bindPostActions(doc, h);
    click(more(row(doc, 1)));
    click(item(row(doc, 1), "Archive post"));
    await flush();
    const n = doc.getElementById("oi-note")!;
    expect(n.textContent).toBe("Could not archive: Post not found");
    expect(n.style.color).toBe("rgb(255, 69, 69)");
    expect(h.refresh).not.toHaveBeenCalled();
  });

  it("Edit post: its text in a field; Save sends PUT /posts/{id} {text}; Cancel puts the text back", async () => {
    const doc = home();
    const h = handlers();
    bindPostActions(doc, h);
    const r = row(doc, 1);
    click(more(r));
    click(item(r, "Edit post"));
    const area = r.querySelector<HTMLTextAreaElement>("[data-oi-edit] textarea")!;
    expect(area.value).toBe("Own synthetic post");
    expect(r.querySelector<HTMLElement>(".b-post__text")!.style.display).toBe("none");
    click(r.querySelector("[data-oi-cancel]")!);
    expect(r.querySelector("[data-oi-edit]")).toBeNull();
    expect(r.querySelector<HTMLElement>(".b-post__text")!.style.display).toBe("");
    click(more(r));
    click(item(r, "Edit post"));
    r.querySelector<HTMLTextAreaElement>("[data-oi-edit] textarea")!.value = "";
    click(r.querySelector("[data-oi-save]")!);
    expect(h.write).not.toHaveBeenCalled();
    r.querySelector<HTMLTextAreaElement>("[data-oi-edit] textarea")!.value = " Edited synthetic post ";
    click(r.querySelector("[data-oi-save]")!);
    await flush();
    expect(h.write.mock.calls).toEqual([["PUT", "/api/of/v2/posts/12", { text: "Edited synthetic post" }]]);
    expect(r.querySelector(".b-post__text")!.textContent!.trim()).toBe("Edited synthetic post");
    expect(r.querySelector("[data-oi-edit]")).toBeNull();
    expect(h.refresh).toHaveBeenCalledTimes(1);
  });
});

describe("bindPostActions with bindWrites", () => {
  it("its clicks never get the Read-only note; another creator's More has Copy link to post only; unbind stops it", async () => {
    const doc = home();
    const h = handlers();
    const unbindWrites = bindWrites(doc, "home/index", null);
    const unbind = bindPostActions(doc, h);
    click(row(doc, 0).querySelector(".set-favorite-btn")!);
    click(row(doc, 0).querySelector(".send-comment-btn")!);
    click(more(row(doc, 1)));
    await flush();
    expect(doc.getElementById("oi-note")).toBeNull();
    const input = row(doc, 0).querySelector<HTMLInputElement>("[data-oi-comments] input")!;
    input.value = "x";
    input.dispatchEvent(new Event("change", { bubbles: true }));
    expect(doc.getElementById("oi-note")).toBeNull();
    const writeText = vi.fn(async (_t: string) => {});
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    (more(row(doc, 0)) as HTMLButtonElement).click();
    expect(menuItems(row(doc, 0)).map((i) => i.textContent!.trim())).toEqual(["Copy link to post"]);
    click(item(row(doc, 0), "Copy link to post"));
    await flush();
    expect(writeText).toHaveBeenCalledWith("https://onlyfans.com/11/deltafour");
    expect(doc.getElementById("oi-note")!.textContent).toBe("Link copied");
    expect(h.write).not.toHaveBeenCalledWith(expect.anything(), expect.stringContaining("/posts/11/"), expect.anything());
    Reflect.deleteProperty(navigator, "clipboard");
    unbind();
    h.write.mockClear();
    click(row(doc, 0).querySelector(".set-favorite-btn")!);
    expect(h.write).not.toHaveBeenCalled();
    unbindWrites();
  });
});
