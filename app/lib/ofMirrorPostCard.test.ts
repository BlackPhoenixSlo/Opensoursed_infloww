/** OF's post card extras on the mirror's post rows (drawPostCard through applyData): price, locked block, counter, poll, viewer files. */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { applyData } from "./ofMirrorData";
import { TEMPLATES, type MirrorPost } from "./ofMirrorFeeds";
import { bindPostActions, type PostHandlers } from "./ofMirrorHome";
import { MEDIA, mediaOf, ofDuration, ofPrice, votingBlock, votingTotal } from "./ofMirrorPostCard";
import { closeViewer, VIEWER } from "./ofMirrorVault";
import { NOT_YET } from "./ofMirrorWrites";

const load = (p: string) => {
  document.documentElement.innerHTML = readFileSync(resolve(__dirname, `../public/of-mirror/pages/${p}.html`), "utf8");
  return document;
};
const img = (u: string) => `/img?u=${u}`;
const visible = (el: Element) => !el.closest("[style*='display:none']");
const HOME_ROWS = ".b-feed-content .user_posts .vue-recycle-scroller__item-view";
const WALL_ROWS = ".user_posts .vue-recycle-scroller__item-view";
const rows = (doc: Document, sel: string) => [...doc.querySelectorAll<HTMLElement>(sel)].filter(visible).filter((r) => r.querySelector("div.b-post"));
const POST_TPL = TEMPLATES.post!.pick(new DOMParser().parseFromString(readFileSync(resolve(__dirname, `../public/of-mirror/pages/${TEMPLATES.post!.page}.html`), "utf8"), "text/html"))!;
const ME = { id: 4242, name: "Synthetic Creator", username: "synthcreator" };
const AUTHORS = { "515": { id: 515, name: "Delta Four", username: "deltafour", subscribedBy: true }, "616": { id: 616, name: "Echo Five", username: "echofive" } } as never;
const photo = (id: number, canView = true) => ({ id, type: "photo", canView, files: canView ? { full: { url: `https://cdn.example/f${id}.jpg` }, preview: { url: `https://cdn.example/p${id}.jpg` } } : null });
const video = (id: number) => ({ id, type: "video", canView: false, files: null });
const DAY = 86_400_000;

const home = (posts: MirrorPost[]) => {
  const doc = load("home/index");
  applyData(doc, "home/index", { home: posts, authors: AUTHORS, templates: { post: POST_TPL }, me: ME }, img);
  return rows(doc, HOME_ROWS);
};
const wall = (posts: MirrorPost[]) => {
  const doc = load("profile/index");
  applyData(doc, "profile/index", { posts }, img);
  return rows(doc, WALL_ROWS);
};
const text = (el: Element | null | undefined) => el?.textContent?.replace(/\s+/g, " ").trim();

afterEach(() => closeViewer(document));

describe("ofPrice: OF's formatPrice", () => {
  it("keeps the cents and drops only .00, as OF's QM", () => {
    expect([ofPrice(12.5), ofPrice(28), ofPrice(9.99), ofPrice("3"), ofPrice(0)]).toEqual(["$12.50", "$28", "$9.99", "$3", "$0"]);
  });
});

describe("a priced post (U8, OF's PostPrice and PostPurchase)", () => {
  it("another creator's locked post: the price by the pin, only its viewable files, then OF's locked block with the unlock button disabled", () => {
    const [r] = home([{ id: 1, postedAt: "2026-10-10T10:05:00", price: 28, isOpened: false, author: { id: 515 }, media: [photo(1, false), photo(2, false), video(3)] }]);
    const details = r.querySelectorAll(".b-post__header .b-username-row .b-post__profile-details")[1];
    expect(text(details.querySelector(".b-price"))).toBe("$28");
    expect(details.querySelector(".b-price use")?.getAttribute("href")).toBe("#icon-locked");
    // No file it can view: no picture, never the template's.
    expect(r.querySelector(".post_media")).toBeNull();
    const block = r.querySelector(".b-post__content > .b-post__unknown.m-default-bg")!;
    expect([...block.querySelectorAll(".b-purchase__list-item")].map((li) => [li.querySelector("use")?.getAttribute("href"), text(li)])).toEqual([
      ["#icon-media", "2"],
      ["#icon-video", "1"],
      ["#icon-locked", "$28"],
    ]);
    const unlock = block.querySelector<HTMLButtonElement>("button.post-subscribe-btn")!;
    expect(text(unlock)).toBe("Unlock post for $28");
    expect([unlock.disabled, unlock.title]).toEqual([true, NOT_YET]);
    // OF's scope ids, as the live capture's, so its stylesheet lays the block out.
    expect(block.hasAttribute("data-v-99afd7e6") && block.querySelector(".b-subscribe-block")!.hasAttribute("data-v-752dbaa6")).toBe(true);
  });

  it("a locked post's free preview file shows, the locked one is counted; cents stay", () => {
    const [r] = home([{ id: 1, price: 12.5, isOpened: false, author: { id: 515 }, media: [photo(1), photo(2, false)] }]);
    expect(r.querySelector(".post_media img.b-post__media__img")?.getAttribute("src")).toBe(img("https://cdn.example/p1.jpg"));
    expect(text(r.querySelector(".b-purchase__list-item__count"))).toBe("1");
    expect(text(r.querySelector(".post-subscribe-btn"))).toBe("Unlock post for $12.50");
  });

  it("another creator's opened post says Purchased for, with no locked block; the Creator's own priced post its price only", () => {
    const [bought, own] = home([
      { id: 1, price: 5, isOpened: true, author: { id: 515 }, media: [photo(1)] },
      { id: 2, price: 9.99, author: { id: 4242 }, media: [photo(2)] },
    ]);
    expect(text(bought.querySelector(".b-price"))).toBe("Purchased for $5");
    expect(bought.querySelector(".b-post__unknown")).toBeNull();
    expect(text(own.querySelector(".b-price"))).toBe("$9.99");
    expect(own.querySelector(".b-post__unknown")).toBeNull();
  });

  it("My profile's wall: the Creator's own priced post shows its price, a free post none", () => {
    const [priced, free] = wall([
      { id: 1, price: 15, media: [photo(1)] },
      { id: 2, media: [photo(2)] },
    ]);
    expect(text(priced.querySelector(".b-price"))).toBe("$15");
    expect(priced.querySelector(".b-post__unknown")).toBeNull();
    expect(free.querySelector(".b-price")).toBeNull();
  });
});

describe("a post with several files (U9) and the viewer (U3)", () => {
  const h = (): PostHandlers => ({ me: "4242", write: () => Promise.resolve({}), read: () => Promise.resolve({}), refresh: () => {}, likes: () => {}, stats: null });

  it("shows OF's 1/N counter on its picture; one file shows none", () => {
    const [many, one] = wall([
      { id: 1, media: [photo(1), photo(2), photo(3)] },
      { id: 2, media: [photo(4)] },
    ]);
    const media = many.querySelector(".post_media")!;
    expect(media.classList.contains("m-with-counter")).toBe(true);
    expect(text(media.querySelector(".b-post-media-size-area > .switcher-media-content"))).toBe("1/ 3");
    expect(one.querySelector(".switcher-media-content")).toBeNull();
  });

  it("a click on a post's picture opens all its files in the viewer, previous and next through them", () => {
    const [r] = wall([{ id: 1, media: [photo(1), { ...photo(2), type: "video", videoSources: { "720": "https://cdn.example/v2.mp4" } } as never] }]);
    expect(mediaOf(r.querySelector(`[${MEDIA}]`)!)).toEqual([
      { src: img("https://cdn.example/f1.jpg"), type: "photo" },
      { src: img("https://cdn.example/v2.mp4"), type: "video" },
    ]);
    const unbind = bindPostActions(document, h());
    r.querySelector(".post_media img.b-post__media__img")!.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
    const viewer = document.getElementById(VIEWER)!;
    expect(viewer.querySelector("img")?.getAttribute("src")).toBe(img("https://cdn.example/f1.jpg"));
    viewer.querySelector<HTMLButtonElement>("[aria-label=Next]")!.click();
    expect(viewer.querySelector("video")?.getAttribute("src")).toBe(img("https://cdn.example/v2.mp4"));
    unbind();
  });

  it("My profile's Media tab: a tile opens its post's files, enabled (the generator's tile is disabled)", () => {
    const doc = load("profile/media");
    applyData(doc, "profile/media", { profileMedia: [{ id: 9, postedAt: "2026-10-10T10:05:00", mediaCount: 2, media: [photo(1), photo(2)], _kind: "photo" } as never] }, img);
    const tile = [...doc.querySelectorAll<HTMLElement>("a.b-photos__item")].find((t) => visible(t) && t.hasAttribute(MEDIA))!;
    expect([tile.getAttribute("aria-disabled"), tile.title]).toEqual([null, ""]);
    const unbind = bindPostActions(doc, h());
    const ev = new MouseEvent("click", { bubbles: true, cancelable: true });
    tile.dispatchEvent(ev);
    expect(ev.defaultPrevented).toBe(true);
    expect(doc.getElementById(VIEWER)?.querySelector("img")?.getAttribute("src")).toBe(img("https://cdn.example/f1.jpg"));
    unbind();
  });
});

describe("a poll or quiz (G1, OF's PostVotingWrapper, read-only)", () => {
  const NOW = new Date("2026-10-10T12:00:00Z");
  const poll = { votingType: 1, voting: { finishedAt: new Date(NOW.getTime() + 2 * DAY).toISOString(), options: [{ id: 1, name: "Red <b>one</b>", count: 3 }, { id: 2, name: "Blue", count: 1, isVoted: true }] } };

  it("the Creator's own poll: each option's bar, label and count, then Poll, the votes and the time left", () => {
    const block = votingBlock(document, poll, { own: true, subscribed: false }, NOW)!;
    const options = [...block.querySelectorAll(".vote-button-wrapper")];
    expect(options.map((o) => o.classList.contains("m-owner"))).toEqual([true, true]);
    expect(options.map((o) => [text(o.querySelector("[at-attr=vote_label]")), text(o.querySelector(".post-vote-button__count")), (o.querySelector(".post_voting_percent") as HTMLElement).style.width])).toEqual([
      ["Red <b>one</b>", "3", "75%"],
      ["Blue", "1", "25%"],
    ]);
    expect(options.map((o) => o.querySelector(".post-vote-button")!.className)).toEqual(["post-vote-button m-break-word m-unvoted", "post-vote-button m-break-word m-voted"]);
    expect([...block.querySelectorAll(".post_voting_due__item")].map(text)).toEqual(["Poll", "4 Votes", "2 days left"]);
    expect(block.querySelector(".post_voting_due use")?.getAttribute("href")).toBe("#icon-poll");
    // Every element (but the icons' <use>) carries the voting stylesheet's scope.
    expect([block, ...block.querySelectorAll("*:not(use)")].every((e) => e.hasAttribute("data-v-7e8caff8"))).toBe(true);
  });

  it("another creator's poll, subscribed and not voted: OF's vote buttons, disabled with the tooltip (no vote route)", () => {
    const block = votingBlock(document, { ...poll, voting: { ...poll.voting, options: poll.voting.options.map((o) => ({ ...o, isVoted: false })) } }, { own: false, subscribed: true }, NOW)!;
    const buttons = [...block.querySelectorAll<HTMLButtonElement>("button.post-vote-button")];
    expect(buttons.map((b) => [text(b), b.disabled, b.title])).toEqual([
      ["Red <b>one</b>", true, NOT_YET],
      ["Blue", true, NOT_YET],
    ]);
  });

  it("not subscribed: the tallies with no bar or count and Subscribe to vote; a finished one no time left", () => {
    const block = votingBlock(document, { ...poll, voting: { ...poll.voting, finishedAt: "2026-10-01T00:00:00Z" } }, { own: false, subscribed: false }, NOW)!;
    expect(block.querySelector("button, .post_voting_percent, .post-vote-button__count")).toBeNull();
    expect([...block.querySelectorAll(".post_voting_due__item")].map(text)).toEqual(["Poll", "Subscribe to vote", "4 Votes"]);
  });

  it("a quiz: the right answer's done mark, the others' cross, Answers", () => {
    const quiz = { votingType: 2, voting: { finishedAt: null, options: [{ id: 1, name: "A", count: 1, isCorrect: true }, { id: 2, name: "B", count: 0, isCorrect: false }] } };
    const block = votingBlock(document, quiz, { own: true, subscribed: false }, NOW)!;
    expect([...block.querySelectorAll(".post-vote-button__icon")].map((i) => [i.className, i.querySelector("use")?.getAttribute("href")])).toEqual([
      ["post-vote-button__icon m-correct", "#icon-done"],
      ["post-vote-button__icon m-incorrect", "#icon-close"],
    ]);
    expect([...block.querySelectorAll(".post_voting_due__item")].map(text)).toEqual(["Quiz", "1 Answer"]);
  });

  it("drawn after the picture on the wall; a locked post's poll only when OF shows it free", () => {
    const [own] = wall([{ id: 1, media: [photo(1)], ...poll }]);
    expect(own.querySelector(".post_media + .post_voting")).not.toBeNull();
    const [locked, free] = home([
      { id: 2, price: 5, isOpened: false, author: { id: 515 }, ...poll },
      { id: 3, price: 5, isOpened: false, author: { id: 515 }, preview: ["poll"], ...poll },
    ]);
    expect(locked.querySelector(".post_voting")).toBeNull();
    expect(free.querySelector(".post_voting + .b-post__unknown")).not.toBeNull();
  });

  it("OF's total and words: counts summed else the total; dayjs' relative thresholds", () => {
    expect([votingTotal({ options: [{ count: 2 }, { count: 3 }] }), votingTotal({ options: [{ count: 0 }], total: 7 })]).toEqual([5, 7]);
    expect([30e3, 60e3, 30 * 60e3, 60 * 60e3, 5 * 3600e3, 30 * 3600e3, 3 * DAY, 40 * DAY, 100 * DAY, 400 * DAY, 800 * DAY].map(ofDuration)).toEqual([
      "seconds", "1 minute", "30 minutes", "1 hour", "5 hours", "a day", "3 days", "a month", "3 months", "a year", "2 years",
    ]);
  });
});

describe("My profile wall's post date (U14)", () => {
  it("links the post on onlyfans.com in a new tab once the Creator's handle is known; else stays disabled", () => {
    let doc = load("profile/index");
    applyData(doc, "profile/index", { posts: [{ id: 77, postedAt: "2026-10-10T10:05:00" }], me: ME }, img);
    const date = rows(doc, WALL_ROWS)[0].querySelector(".b-post__date")!;
    expect([date.getAttribute("href"), date.getAttribute("target"), date.getAttribute("aria-disabled"), date.getAttribute("title")]).toEqual(["https://onlyfans.com/77/synthcreator", "_blank", null, null]);
    doc = load("profile/index");
    applyData(doc, "profile/index", { posts: [{ id: 77, postedAt: "2026-10-10T10:05:00" }] }, img);
    expect(rows(doc, WALL_ROWS)[0].querySelector(".b-post__date")!.getAttribute("title")).toBe(NOT_YET);
  });
});
