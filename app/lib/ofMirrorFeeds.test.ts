/** Home's story strip from GET /stories and GET /streams/feed (applyStories) and its tiles' clicks (bindStory). */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import { applyData, partsOf } from "./ofMirrorData";
import { allWatched, storyItems, stripStreams, stripUsers, type FeedStream, type StoryEntry, type StoryUser } from "./ofMirrorFeeds";
import { READ_ONLY } from "./ofMirrorWrites";
import { bindStory } from "./ofMirrorPost";
import { VIEWER } from "./ofMirrorVault";

const load = (p: string) => {
  document.documentElement.innerHTML = readFileSync(resolve(__dirname, `../public/of-mirror/pages/${p}.html`), "utf8");
  return document;
};
const flush = () => new Promise((r) => setTimeout(r, 0));
const img = (u: string) => `/img?u=${u}`;
const TILE = ".stories-list .b-story-item";
const STORY_TILE = `${TILE}[at-attr='story_item']`;
const views = (doc: Document) => [...doc.querySelectorAll<HTMLElement>(".stories-list .vue-recycle-scroller__item-view")];

/** Synthetic GET /stories rows (no live capture of the feed yet): two creators, the first with its stories' media. */
const STORIES: StoryUser[] = [
  {
    id: 515,
    name: "Delta Four",
    username: "deltafour",
    avatar: "https://cdn.example/d4.jpg",
    isVerified: true,
    stories: [
      { id: 1, media: [{ id: 11, type: "photo", files: { full: { url: "https://cdn.example/s1.jpg" }, thumb: { url: "https://cdn.example/s1t.jpg" } } }] },
      { id: 2, media: [{ id: 12, type: "video", files: { full: { url: "https://cdn.example/s2.mp4" }, preview: { url: "https://cdn.example/s2p.jpg" } } }] },
    ],
  },
  { id: 616, name: "Echo Five", username: "echofive" },
];

afterEach(() => vi.restoreAllMocks());

describe("Home's story strip", () => {
  it("Home reads the stories feed", () => {
    expect(partsOf("home/index")).toContain("stories");
  });

  /** The Creator (users/me) and their own active stories (GET /users/{id}/stories). */
  const ME: StoryUser = { id: 77, name: "Model One", username: "modelone" };
  const MINE: StoryEntry[] = [{ id: 9, media: [{ id: 19, type: "photo", files: { full: { url: "https://cdn.example/m.jpg" } } }] }];

  it("stripUsers: the Creator's own stories make the first tile (OF's userStories), before the feed's creators, never twice", () => {
    expect(stripUsers(ME, MINE, STORIES)!.map((u) => u.id)).toEqual([77, 515, 616]);
    expect(stripUsers(ME, MINE, STORIES)![0].stories).toEqual(MINE);
    expect(stripUsers(ME, MINE, [{ id: "77", name: "Model One" }, ...STORIES])!.map((u) => u.id)).toEqual([77, 515, 616]);
    expect(stripUsers(ME, MINE, undefined)!.map((u) => u.id)).toEqual([77]); // the feed not read yet (or failed)
  });

  it("stripUsers: no own stories, or no Creator id, leaves the feed as it is", () => {
    expect(stripUsers(ME, [], STORIES)).toBe(STORIES);
    expect(stripUsers(ME, undefined, STORIES)).toBe(STORIES);
    expect(stripUsers(undefined, MINE, STORIES)).toBe(STORIES);
    expect(stripUsers({ name: "No id" }, MINE, undefined)).toBeUndefined();
  });

  it("the Creator's own tile opens their stories in the viewer", () => {
    const doc = load("home/index");
    applyData(doc, "home/index", { stories: stripUsers(ME, MINE, STORIES) }, img);
    const unbind = bindStory(doc, { addStory: vi.fn() });
    const own = doc.querySelector<HTMLElement>(`${STORY_TILE}[data-oi-story-user='77']`)!;
    expect(own.closest(".vue-recycle-scroller__item-view")!.previousElementSibling!.querySelector(".m-story-item-own")).not.toBeNull();
    own.click();
    expect(doc.getElementById(VIEWER)!.querySelector("img")!.getAttribute("src")).toBe(img("https://cdn.example/m.jpg"));
    unbind();
  });

  it("one tile per creator after Add to story: avatar, name, verified mark, the first story's still; laid out from the left", () => {
    const doc = load("home/index");
    const before = views(doc).length;
    applyData(doc, "home/index", { stories: STORIES }, img);
    const tiles = [...doc.querySelectorAll<HTMLElement>(STORY_TILE)];
    expect(tiles.map((t) => t.querySelector(".b-story-item__text")!.textContent!.trim())).toEqual(["Delta Four", "Echo Five"]);
    expect(tiles.map((t) => t.dataset.oiStoryUser)).toEqual(["515", "616"]);
    expect(tiles[0].querySelector(".g-avatar img")!.getAttribute("src")).toBe(img("https://cdn.example/d4.jpg"));
    expect(tiles[1].querySelector(".g-avatar img")).toBeNull(); // no picture: OF's initials
    expect(tiles[1].querySelector(".g-avatar__placeholder")!.textContent!.trim()).toBe("EF");
    expect(tiles.map((t) => !!t.querySelector("svg[data-icon-name='icon-verified']"))).toEqual([true, false]);
    expect(tiles[0].querySelector("img.img-responsive")!.getAttribute("src")).toBe(img("https://cdn.example/s1t.jpg"));
    expect(tiles[0].closest(".vue-recycle-scroller__item-view")!.previousElementSibling!.querySelector(".m-story-item-own")).not.toBeNull();
    const all = views(doc);
    expect(all).toHaveLength(before + 2);
    expect(all.map((v) => v.style.transform)).toEqual(all.map((_, i) => `translateX(${i * 136}px)`));
    expect(all[0].parentElement!.style.minWidth).toBe(`${all.length * 136}px`);
  });

  it("no tile for an empty feed; no data restores the strip", () => {
    const doc = load("home/index");
    const html = doc.documentElement.innerHTML;
    applyData(doc, "home/index", { stories: [] }, img);
    expect(doc.querySelectorAll(STORY_TILE)).toHaveLength(0);
    expect(doc.documentElement.innerHTML).toBe(html);
    applyData(doc, "home/index", { stories: STORIES }, img);
    applyData(doc, "home/index", {}, img);
    expect(doc.documentElement.innerHTML).toBe(html);
  });

  it("a tile with its stories opens them in the viewer, previous / next through them", () => {
    const doc = load("home/index");
    applyData(doc, "home/index", { stories: STORIES }, img);
    const unbind = bindStory(doc, { addStory: vi.fn() });
    doc.querySelector<HTMLElement>(STORY_TILE)!.click();
    const viewer = doc.getElementById(VIEWER)!;
    expect(viewer.querySelector("img")!.getAttribute("src")).toBe(img("https://cdn.example/s1.jpg"));
    viewer.querySelector<HTMLButtonElement>("button[aria-label='Next']")!.click();
    expect(viewer.querySelector("video")!.getAttribute("src")).toBe(img("https://cdn.example/s2.mp4"));
    expect(doc.getElementById("oi-note")).toBeNull(); // not the Read-only note
    unbind();
  });

  it("a tile without media reads the creator's stories; none or a failure is a note", async () => {
    const doc = load("home/index");
    applyData(doc, "home/index", { stories: STORIES }, img);
    const userStories = vi.fn(async (id: string) => (id === "616" ? [{ src: img("https://cdn.example/e5.jpg"), type: "photo" }] : []));
    const unbind = bindStory(doc, { addStory: vi.fn(), userStories });
    doc.querySelectorAll<HTMLElement>(STORY_TILE)[1].click();
    await flush();
    expect(userStories).toHaveBeenCalledWith("616");
    expect(doc.getElementById(VIEWER)!.querySelector("img")!.getAttribute("src")).toBe(img("https://cdn.example/e5.jpg"));
    doc.getElementById(VIEWER)!.querySelector<HTMLButtonElement>("button[aria-label='Close']")!.click();
    userStories.mockResolvedValueOnce([]);
    doc.querySelectorAll<HTMLElement>(STORY_TILE)[1].click();
    await flush();
    expect(doc.getElementById(VIEWER)).toBeNull();
    expect(doc.getElementById("oi-note")!.textContent).toBe("No story to show");
    userStories.mockRejectedValueOnce(new Error("boom"));
    doc.querySelectorAll<HTMLElement>(STORY_TILE)[1].click();
    await flush();
    expect(doc.getElementById("oi-note")!.textContent).toMatch(/^Could not load the story/);
    unbind();
  });

  it("storyItems: every story's media in order, a video's file, nothing for a media with no file", () => {
    expect(storyItems([...STORIES[0].stories!, { id: 3, media: [{ id: 13, type: "audio" }] }], img)).toEqual([
      { src: img("https://cdn.example/s1.jpg"), type: "photo" },
      { src: img("https://cdn.example/s2.mp4"), type: "video" },
    ]);
  });
});

/** The strip's order as OF's StoriesWidget `list` (app.js chunk 32036): addStoryBtn, liveStreams, userStories,
 *  newStories, promoteProfile, watchedStories, scheduledStreams. Synthetic rows (no live capture of either feed yet). */
describe("Home's story strip: new vs watched, live and scheduled streams (OF's StoriesWidget order)", () => {
  const ME: StoryUser = { id: 77, name: "Model One", username: "modelone" };
  const photo = (id: number, url: string, isWatched?: boolean): StoryEntry => ({ id, isWatched, media: [{ id: id * 10, type: "photo", files: { full: { url }, thumb: { url: `${url}?t` } } }] });
  const names = (doc: Document) => views(doc).map((v) => v.querySelector(".b-story-item__text")!.textContent!.trim());
  const NOW = new Date("2026-10-21T12:00:00Z");
  const inMs = (ms: number) => new Date(NOW.getTime() + ms).toISOString();

  it("all-watched creators sit after Start profile promotion, marked m-viewed; new ones before it; the Creator's own never moves", () => {
    const doc = load("home/index");
    const html = doc.documentElement.innerHTML;
    const feed: StoryUser[] = [
      { id: 515, name: "Delta Four", stories: [photo(1, "https://cdn.example/d1.jpg", true), photo(2, "https://cdn.example/d2.jpg", true)] },
      { id: 616, name: "Echo Five" }, // no stories in the feed row: not watched
      { id: 717, name: "Foxtrot Six", stories: [photo(3, "https://cdn.example/f1.jpg", true), photo(4, "https://cdn.example/f2.jpg")] },
    ];
    applyData(doc, "home/index", { stories: stripUsers(ME, [photo(9, "https://cdn.example/m.jpg", true)], feed), me: { id: 77 } }, img);
    expect(names(doc)).toEqual(["Add to story", "Model One", "Echo Five", "Foxtrot Six", "Start profile promotion", "Delta Four"]);
    const tiles = [...doc.querySelectorAll<HTMLElement>(STORY_TILE)];
    expect(tiles.map((t) => [t.dataset.oiStoryUser, t.classList.contains("m-viewed")])).toEqual([["77", false], ["616", false], ["717", false], ["515", true]]);
    // OF's preview: the first unwatched story's still, else the first's.
    expect(tiles[2].querySelector("img.img-responsive")!.getAttribute("src")).toBe(img("https://cdn.example/f2.jpg?t"));
    expect(tiles[3].querySelector("img.img-responsive")!.getAttribute("src")).toBe(img("https://cdn.example/d1.jpg?t"));
    const all = views(doc);
    expect(all.map((v) => v.style.transform)).toEqual(all.map((_, i) => `translateX(${i * 136}px)`));
    expect(all[0].parentElement!.style.minWidth).toBe(`${all.length * 136}px`);
    applyData(doc, "home/index", {}, img);
    expect(doc.documentElement.innerHTML).toBe(html);
  });

  it("no isWatched flag (as GET /stories may send): every creator stays before the promotion tile", () => {
    const doc = load("home/index");
    applyData(doc, "home/index", { stories: STORIES }, img);
    expect(names(doc)).toEqual(["Add to story", "Delta Four", "Echo Five", "Start profile promotion"]);
    expect(doc.querySelectorAll(".b-story-item.m-viewed")).toHaveLength(0);
  });

  const STREAMS: FeedStream[] = [
    { id: 1, user: { id: 515, name: "Delta Four", avatar: "https://cdn.example/d4.jpg", subscribedBy: true }, isScheduled: false, isActive: true, thumbUrl: "https://cdn.example/l1.jpg", price: 5 },
    { id: 2, user: { id: 999, name: "Not Subscribed" }, isScheduled: false, isActive: true, thumbUrl: "https://cdn.example/l2.jpg" },
    { id: 3, user: { id: 77 }, isScheduled: true, isActive: false, scheduledAt: inMs(3 * 3600_000) },
    { id: 4, user: { id: 616, name: "Echo Five", subscribedBy: true }, isScheduled: true, isActive: false, scheduledAt: inMs(2 * 86400_000), media: { id: 40, type: "photo", files: { thumb: { url: "https://cdn.example/c4.jpg" } } } },
    { id: 5, user: 717, isScheduled: true, isActive: false, scheduledAt: inMs(3600_000) }, // an id only, not the Creator's: no subscribedBy to go by
  ];

  it("live streams right after Add to story, scheduled ones last; only the Creator's own and subscribed creators'", () => {
    const doc = load("home/index");
    const html = doc.documentElement.innerHTML;
    applyData(doc, "home/index", { stories: STORIES, streams: STREAMS, me: { id: 77, name: "Model One" }, now: NOW }, img);
    expect(names(doc)).toEqual(["Add to story", "Delta Four", "Delta Four", "Echo Five", "Start profile promotion", "Model One", "Echo Five"]);
    const live = doc.querySelector<HTMLElement>("[data-oi-stream='live']")!;
    expect([live.tagName, live.className, live.dataset.oiStreamUser]).toEqual(["BUTTON", "b-story-item m-gradient-overlay m-gradient-backward", "515"]);
    expect(live.querySelector("img.m-stream-image")!.getAttribute("src")).toBe(img("https://cdn.example/l1.jpg"));
    expect(live.querySelector(".b-story-item__cost")!.textContent!.trim()).toBe("$5");
    const [mine, echo] = [...doc.querySelectorAll<HTMLElement>("[data-oi-stream='scheduled']")];
    expect(mine.className).toBe("b-story-item m-gradient-overlay m-gradient-backward m-scheduled-story");
    // The Creator's own scheduled stream: their name (the stream carries only their id), a link to the queue that lists it.
    expect([mine.tagName, mine.getAttribute("href"), mine.getAttribute("target")]).toEqual(["A", "/of-manager/queue", "_top"]);
    expect(mine.querySelector(".b-story-item__time-scheduled")!.textContent!.trim()).toBe("in 3 hours");
    expect(mine.querySelector(".b-story-item__text-near-avatar")!.classList.contains("m-over-light-bg")).toBe(true); // no cover
    expect(mine.querySelectorAll(".b-story-item__text-near-avatar .datetime > span")).toHaveLength(2);
    expect([echo.tagName, echo.querySelector(".b-story-item__time-scheduled")!.textContent!.trim()]).toEqual(["BUTTON", "in 2 days"]);
    expect(echo.querySelector("img.m-stream-image")!.getAttribute("src")).toBe(img("https://cdn.example/c4.jpg"));
    applyData(doc, "home/index", {}, img);
    expect(doc.documentElement.innerHTML).toBe(html);
  });

  it("streams show with no stories feed (not read yet, or failed)", () => {
    const doc = load("home/index");
    applyData(doc, "home/index", { streams: STREAMS, me: { id: 77, name: "Model One" }, now: NOW }, img);
    expect(names(doc)).toEqual(["Add to story", "Delta Four", "Start profile promotion", "Model One", "Echo Five"]);
  });

  it("a live tile sends nothing and shows the Read-only note; the own scheduled tile is left to its link", () => {
    const doc = load("home/index");
    applyData(doc, "home/index", { streams: STREAMS, me: { id: 77, name: "Model One" }, now: NOW }, img);
    const unbind = bindStory(doc, { addStory: vi.fn(), userStories: vi.fn() });
    doc.querySelector<HTMLElement>("[data-oi-stream='live']")!.click();
    expect(doc.getElementById(VIEWER)).toBeNull();
    expect(doc.getElementById("oi-note")!.textContent).toBe(READ_ONLY);
    doc.getElementById("oi-note")!.remove();
    const link = doc.querySelector<HTMLAnchorElement>("a[data-oi-stream='scheduled']")!;
    const ev = new MouseEvent("click", { bubbles: true, cancelable: true });
    link.dispatchEvent(ev);
    expect([ev.defaultPrevented, doc.getElementById("oi-note")]).toEqual([false, null]);
    unbind();
  });

  it("stripStreams: isActive makes a scheduled stream live; scheduled ones by startedAt (stable, a missing one last); no Creator id, none of theirs", () => {
    const s = (id: number, extra: Partial<FeedStream>): FeedStream => ({ id, user: { id: 1, subscribedBy: true }, isScheduled: true, ...extra });
    const got = stripStreams([s(1, {}), s(2, { startedAt: "2026-10-23T10:00:00Z" }), s(3, { isActive: true }), s(4, { startedAt: "2026-10-22T10:00:00Z" }), s(5, {})], "1");
    expect(got.live.map((x) => x.id)).toEqual([3]);
    expect(got.scheduled.map((x) => x.id)).toEqual([4, 2, 1, 5]);
    expect(stripStreams([{ id: 9, user: 77, isScheduled: false }], undefined)).toEqual({ live: [], scheduled: [] });
    expect(stripStreams([{ id: 9, user: 77, isScheduled: false }], "77").live.map((x) => x.id)).toEqual([9]);
  });

  it("allWatched: every story watched; none, or no stories, is not", () => {
    expect(allWatched({ id: 1, stories: [photo(1, "u", true), photo(2, "v", true)] })).toBe(true);
    expect(allWatched({ id: 1, stories: [photo(1, "u", true), photo(2, "v")] })).toBe(false);
    expect(allWatched({ id: 1, stories: [] })).toBe(false);
    expect(allWatched({ id: 1 })).toBe(false);
  });
});

