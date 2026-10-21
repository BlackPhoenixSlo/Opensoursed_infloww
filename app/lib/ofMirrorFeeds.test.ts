/** Home's story strip from GET /stories (applyStories) and its tiles' clicks (bindStory). */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import { applyData, partsOf } from "./ofMirrorData";
import { storyItems, type StoryUser } from "./ofMirrorFeeds";
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
