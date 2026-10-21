import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it, vi } from "vitest";
import { applyData } from "./ofMirrorData";
import { applyIdentity, formatCount } from "./ofMirrorIdentity";
import { ARCHIVE_PATH, bindProfile, PROFILE_CHANGE, standInModel, type Highlight, type MediaPost, type MirrorProfile, type ProfileHandlers, type ProfileUser } from "./ofMirrorProfile";
import type { MirrorPost, Promotion } from "./ofMirrorFeeds";
import type { PostLabel } from "./ofMirrorData";
import { bindStory, highlightItems } from "./ofMirrorPost";
import { STORY_PHOTO_MS, VIEWER } from "./ofMirrorVault";

const capture = (p: string) => readFileSync(resolve(__dirname, `../public/of-mirror/pages/${p}.html`), "utf8");
const load = (p: string) => {
  document.documentElement.innerHTML = capture(p);
  return document;
};
const visible = (el: Element) => !el.closest("[style*='display:none']");
const shown = (doc: Document, sel: string) => [...doc.querySelectorAll(sel)].filter(visible);
const texts = (doc: Document, sel: string) => shown(doc, sel).map((e) => e.textContent?.replace(/\s+/g, " ").trim());
const flush = () => new Promise((r) => setTimeout(r, 0));
const NOT_YET = "Not available in Inflowwww yet";
const SECTIONS = ".b-profile__sections__count";
const LABELS = "[at-attr='profile_label']";

/** OF's own /api2/v2 responses for My profile, captured through the Relay and scrubbed (app/lib/__fixtures__/of). */
const fixture = <T,>(name: string): T => JSON.parse(readFileSync(resolve(__dirname, `__fixtures__/of/profile-${name}.json`), "utf8")) as T;
const ME = fixture<ProfileUser & { name: string; username: string; avatar: string; header: string; about: string }>("me");
const HIGHLIGHTS = fixture<{ list: Highlight[]; hasMore: boolean }>("highlights");
const ARCHIVE = fixture<{ list: unknown[]; hasMore: boolean; marker: number }>("archive");
const LABELS_RESP = fixture<{ list: PostLabel[] }>("labels");
const POSTS = fixture<MirrorPost[]>("posts");
const PHOTOS = fixture<MirrorPost[]>("photos");
const VIDEOS = fixture<MirrorPost[]>("videos");
const PROMOTIONS = fixture<{ hasMore: boolean; items: Promotion[] }>("promotions");

const PROFILE: MirrorProfile = {
  user: { postsCount: 3, mediasCount: 5, photosCount: 4, videosCount: 1, favoritedCount: 1530, subscribersCount: 13, archivedPostsCount: 2, privateArchivedPostsCount: 0 },
  labels: [
    { id: 5, name: "Beach", postsCount: 2 },
    { id: 6, name: "Gym", postsCount: 1 },
    { id: "archived", name: "Archive", postsCount: 2 },
  ],
  highlights: HIGHLIGHTS.list.slice(0, 2),
};
const [H1, H2] = HIGHLIGHTS.list;


describe.each(["profile/index", "profile/media", "profile/state-more-menu"])("%s as generated", (p) => {
  it("shows no example count, label, post, tile or picture", () => {
    const doc = load(p);
    expect(texts(doc, SECTIONS)).toEqual(["", "", "", ""]);
    expect(texts(doc, ".b-tabs__nav__text").slice(0, 2)).toEqual(["Posts", "Media"]);
    expect(shown(doc, ".user_posts .vue-recycle-scroller__item-view")).toEqual([]);
    expect(texts(doc, ".user_posts [data-oi-empty]")).toEqual(["No posts yet"]);
    expect(shown(doc, "[data-oi-recent]")).toEqual([]);
    expect(shown(doc, "[data-oi-template='promotion']")).toEqual([]);
    expect(shown(doc, "*").filter((e) => !e.children.length && /Lorem|Fan \d/.test(e.textContent ?? ""))).toEqual([]);
  });

  it("its story strip: Story archive is wired with the Creator's picture (no fan's), Create highlight disabled with the tooltip, Go live a link", () => {
    const doc = load(p);
    const archive = doc.querySelector(".b-story-item.m-story-archive")!;
    expect(archive.hasAttribute("data-oi-wired")).toBe(true);
    expect([archive.querySelector(".g-avatar__placeholder")?.classList.contains("of-fan"), archive.textContent?.includes("F")]).toEqual([false, false]);
    const [create, live] = [...doc.querySelectorAll(".b-story-item.m-create")];
    expect([create.tagName, create.hasAttribute("disabled"), create.getAttribute("title")]).toEqual(["BUTTON", true, NOT_YET]);
    expect(live.getAttribute("href")).toBe("/of-manager/streaming");
  });

  it("every enabled button is wired, a menu toggle, a post action or the composer's; the rest are disabled with the tooltip", () => {
    const doc = load(p);
    const off = [...doc.querySelectorAll<HTMLButtonElement>("button[disabled]")].filter((b) => !b.closest("[data-oi-template]"));
    for (const b of off) expect(b.title, b.outerHTML.slice(0, 120)).toBe(NOT_YET);
    for (const sel of ["button[aria-label='Compact view']", "button[aria-label='Sort']"]) expect(doc.querySelector(sel)?.hasAttribute("disabled"), sel).toBe(true);
    const status = doc.querySelector("button.m-user-status");
    if (status) expect([status.hasAttribute("disabled"), status.hasAttribute("data-oi-wired"), status.hasAttribute("data-oi-user-status")]).toEqual([false, true, true]);
  });
});

describe("My profile's counts, label tabs and highlights", () => {
  it("profile/index: the Creator's counts (OF's short form), tab counts, label tabs (disabled) and highlight tiles (viewable); no data restores the page", () => {
    const doc = load("profile/index");
    const html = doc.documentElement.innerHTML;
    applyData(doc, "profile/index", { profile: PROFILE }, (u) => `/img?u=${u}`);
    expect(texts(doc, SECTIONS)).toEqual(["4", "1", "1.5K", "13"]);
    expect(texts(doc, ".b-tabs__nav__text").slice(0, 2)).toEqual(["3 posts", "5 Media"]);
    expect(texts(doc, LABELS)).toEqual(["All 3", "Archive 2", "Beach 2", "Gym 1"]);
    const tabs = shown(doc, LABELS).map((t) => t.closest("button")!);
    expect(tabs.slice(1).map((b) => [b.disabled, b.title])).toEqual(Array(3).fill([true, NOT_YET]));
    const tiles = shown(doc, ".stories-list .b-story-item");
    expect(tiles.map((t) => t.querySelector(".b-story-item__text")?.textContent?.trim())).toEqual(["Story archive", "Create highlight", "Go live", H1.title, H2.title]);
    const [one, two] = tiles.slice(3) as HTMLButtonElement[];
    expect([one.disabled, one.title, two.disabled]).toEqual([false, "", false]);
    expect([one, two].map((t) => [t.dataset.oiFull, t.dataset.oiType])).toEqual([[`/img?u=${H1.cover}`, "photo"], [`/img?u=${H2.cover}`, "photo"]]);
    expect([one, two].map((t) => t.dataset.oiHighlight)).toEqual([String(H1.id), String(H2.id)]);
    // OF's highlight `cover` is the cover story's picture URL.
    expect([one, two].map((t) => t.querySelector("img")?.getAttribute("src"))).toEqual([`/img?u=${H1.cover}`, `/img?u=${H2.cover}`]);
    applyData(doc, "profile/index", {});
    expect(doc.documentElement.innerHTML).toBe(html);
  });

  it("a highlight tile plays its stories in order (GET /stories/highlights/{id}); none or a failure is a note", async () => {
    const doc = load("profile/index");
    applyData(doc, "profile/index", { profile: PROFILE }, (u) => `/img?u=${u}`);
    // OF's answer: the highlight with its stories (normalizr `highlights` entity, `{stories: [...]}`).
    const answer = {
      id: H1.id,
      title: H1.title,
      stories: [
        { id: 1, isWatched: true, media: [{ id: 11, type: "photo", files: { full: { url: "https://cdn.example/h1.jpg" } } }] },
        { id: 2, media: [{ id: 12, type: "video", files: { full: { url: "https://cdn.example/h2.mp4" } } }] },
      ],
    };
    const highlightStories = vi.fn(async (id: string) => (id === String(H1.id) ? highlightItems(answer, (u) => `/img?u=${u}`) : []));
    const unbind = bindStory(doc, { addStory: vi.fn(), highlightStories });
    const tiles = shown(doc, ".stories-list .b-story-item") as HTMLButtonElement[];
    tiles[3].click();
    await flush();
    expect(highlightStories).toHaveBeenCalledWith(String(H1.id));
    const viewer = doc.getElementById(VIEWER)!;
    expect(viewer.querySelector("img")!.getAttribute("src")).toBe("/img?u=https://cdn.example/h1.jpg"); // not the cover
    viewer.querySelector<HTMLButtonElement>("button[aria-label='Next']")!.click();
    expect(viewer.querySelector("video")!.getAttribute("src")).toBe("/img?u=https://cdn.example/h2.mp4");
    viewer.querySelector<HTMLButtonElement>("button[aria-label='Close']")!.click();
    tiles[4].click();
    await flush();
    expect(doc.getElementById(VIEWER)).toBeNull();
    expect(doc.getElementById("oi-note")!.textContent).toBe("No story to show");
    highlightStories.mockRejectedValueOnce(new Error("boom"));
    tiles[3].click();
    await flush();
    expect(doc.getElementById("oi-note")!.textContent).toBe("Could not load the highlight: boom");
    unbind();
  });

  it("with a Creator: a highlight tile plays its own stories (highlightStories by its id) in OF's story player, then closes", async () => {
    vi.useFakeTimers();
    try {
      const doc = load("profile/index");
      applyData(doc, "profile/index", { profile: PROFILE }, (u) => `/img?u=${u}`);
      const stories = [{ src: "/img?u=s1.jpg", type: "photo" }, { src: "/img?u=s2.mp4", type: "video" }, { src: "/img?u=s3.jpg", type: "photo" }];
      const highlightStories = vi.fn((_id: string) => Promise.resolve(stories));
      const unbind = bindStory(doc, { addStory: vi.fn(), highlightStories });
      const tile = (shown(doc, ".stories-list .b-story-item") as HTMLButtonElement[])[4];
      expect(tile.dataset.oiHighlight).toBe(String(H2.id));
      tile.click();
      await vi.advanceTimersByTimeAsync(0);
      expect(highlightStories.mock.calls).toEqual([[String(H2.id)]]);
      const viewer = doc.getElementById(VIEWER)!;
      const media = () => viewer.querySelector("[data-oi-viewer-media]")!;
      const widths = () => [...viewer.querySelectorAll<HTMLElement>("[data-oi-story-bars] > span > span")].map((b) => b.style.width);
      // OF's header: the highlight's title and cover, a segment per story.
      expect(viewer.querySelector(".b-story-header__author__title")!.textContent).toBe(H2.title);
      expect(viewer.querySelector(".b-story-header__author img")!.getAttribute("src")).toBe(`/img?u=${H2.cover}`);
      expect([media().getAttribute("src"), widths()]).toEqual(["/img?u=s1.jpg", ["100%", "0px", "0px"]]); // the current one filling to full
      // A photo for 5 s, then the next story; a video to its end.
      await vi.advanceTimersByTimeAsync(STORY_PHOTO_MS);
      expect([media().tagName, media().getAttribute("src"), widths().slice(0, 1)]).toEqual(["VIDEO", "/img?u=s2.mp4", ["100%"]]);
      await vi.advanceTimersByTimeAsync(STORY_PHOTO_MS);
      expect(media().getAttribute("src")).toBe("/img?u=s2.mp4");
      media().dispatchEvent(new Event("ended"));
      expect(media().getAttribute("src")).toBe("/img?u=s3.jpg");
      await vi.advanceTimersByTimeAsync(STORY_PHOTO_MS);
      expect(doc.getElementById(VIEWER)).toBeNull();
      unbind();
    } finally {
      vi.useRealTimers();
    }
  });

  it("highlightItems: the answer's stories' media in order; no stories list, none", () => {
    const img = (u: string) => `/img?u=${u}`;
    const photo = (url: string) => ({ id: 1, media: [{ id: 2, type: "photo", files: { full: { url } } }] });
    expect(highlightItems({ stories: [photo("https://cdn.example/a.jpg"), photo("https://cdn.example/b.jpg")] }, img)).toEqual([
      { src: img("https://cdn.example/a.jpg"), type: "photo" },
      { src: img("https://cdn.example/b.jpg"), type: "photo" },
    ]);
    expect(highlightItems({ id: 1 }, img)).toEqual([]);
    expect(highlightItems(null, img)).toEqual([]);
    expect(highlightItems([photo("https://cdn.example/a.jpg")], img)).toEqual([]);
  });

  it("a highlight tile opens its cover in the viewer with no single Creator; Escape closes it", () => {
    const doc = load("profile/index");
    applyData(doc, "profile/index", { profile: PROFILE }, (u) => `/img?u=${u}`);
    const unbind = bindStory(doc, null);
    const tiles = shown(doc, ".stories-list .b-story-item") as HTMLButtonElement[];
    tiles[4].click();
    expect(doc.getElementById(VIEWER)!.querySelector("img")!.getAttribute("src")).toBe(`/img?u=${H2.cover}`);
    expect(doc.getElementById("oi-note")).toBeNull();
    doc.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
    expect(doc.getElementById(VIEWER)).toBeNull();
    unbind();
  });

  it("a count OF does not send hides its section; one post reads '1 post'; no labels: just All", () => {
    const doc = load("profile/index");
    applyData(doc, "profile/index", { profile: { user: { postsCount: 1, mediasCount: 0, photosCount: 0, videosCount: 0, favoritedCount: 0 } } });
    expect(texts(doc, SECTIONS)).toEqual(["0", "0", "0"]);
    expect(shown(doc, "[aria-label='Fans']")).toEqual([]);
    expect(texts(doc, ".b-tabs__nav__text").slice(0, 2)).toEqual(["1 post", "0 Media"]);
    expect(texts(doc, LABELS)).toEqual(["All 1"]);
  });

  it("profile/media: the All, Photo and Video tabs' counts", () => {
    const doc = load("profile/media");
    applyData(doc, "profile/media", { profile: PROFILE });
    expect(texts(doc, "[data-oi-media-tab] .b-tabs__nav__text")).toEqual(["All 5", "Photo 4", "Video 1"]);
  });

  it("the wall's and the Media grid's empty message reads Loading posts… then the red error", () => {
    for (const [p, key] of [["profile/index", "postsStatus"], ["profile/media", "profileMediaStatus"]] as const) {
      const doc = load(p);
      applyData(doc, p, { [key]: null });
      expect(texts(doc, ".user_posts [data-oi-empty]")).toEqual(["Loading posts…"]);
      applyData(doc, p, { [key]: "relay down" });
      const span = doc.querySelector<HTMLElement>(".user_posts [data-oi-empty] > span")!;
      expect([span.textContent, span.style.color]).toEqual(["Could not load posts: relay down", "rgb(255, 69, 69)"]);
      applyData(doc, p, {});
      expect(texts(doc, ".user_posts [data-oi-empty]")).toEqual(["No posts yet"]);
    }
  });

  it("posts hide the wall's No posts yet", () => {
    const doc = load("profile/index");
    applyData(doc, "profile/index", { posts: [{ id: 1, text: "Hi", postedAt: "2026-10-10T10:00:00", media: [] }] });
    expect(texts(doc, ".user_posts [data-oi-empty]")).toEqual([]);
    expect(shown(doc, ".user_posts [data-oi-post]")).toHaveLength(1);
  });

  it("promotions fill both copies of the right column's cards", () => {
    const doc = load("profile/index");
    applyData(doc, "profile/index", { promotions: [{ id: 3, type: "new", price: 0, subscribeDays: 30, canClaim: true, isFinished: false }] });
    expect(texts(doc, ".b-offer-join .b-menu-list__text")).toEqual(["Limited offer - Free trial for 30 days!", "Limited offer - Free trial for 30 days!"]);
  });
});

describe("bindProfile", () => {
  const handlers = (over: Partial<ProfileHandlers> = {}): ProfileHandlers => ({ username: "livemodel", read: vi.fn(() => Promise.resolve({ list: [] })), img: (u) => `/img?u=${u}`, ...over });
  const click = (el: Element) => {
    const ev = new MouseEvent("click", { bubbles: true, cancelable: true });
    el.dispatchEvent(ev);
    return ev;
  };
  const box = (doc: Document) => doc.querySelector<HTMLElement>("[data-oi-story-archive-box]");

  it("Story archive opens a box under the strip with the archived stories (picture, date); a second click closes it", async () => {
    const doc = load("profile/index");
    // OF's own /stories/archive page: {list, marker, hasMore}, each story {id, createdAt, media}.
    const read = vi.fn(() => Promise.resolve(ARCHIVE));
    const stories = ARCHIVE.list as { createdAt: string; media: { files: { squarePreview: { url: string }; preview: { url: string } } }[] }[];
    const unbind = bindProfile(doc, handlers({ read }));
    const archive = doc.querySelector<HTMLElement>("[data-oi-story-archive]")!;
    click(archive);
    expect(read).toHaveBeenCalledWith(ARCHIVE_PATH);
    expect(box(doc)?.previousElementSibling).toBe(doc.querySelector(".stories-list"));
    expect(box(doc)?.textContent).toBe("Loading…");
    expect(archive.getAttribute("aria-expanded")).toBe("true");
    await flush();
    const stills = [...box(doc)!.querySelectorAll("img")].map((i) => i.getAttribute("src"));
    expect(stills).toHaveLength(stories.length);
    stills.forEach((src, i) => expect([stories[i].media[0].files.squarePreview.url, stories[i].media[0].files.preview.url].map((u) => `/img?u=${u}`)).toContain(src));
    const day = (iso: string) => new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
    expect(box(doc)!.textContent).toBe(stories.map((st) => day(st.createdAt)).join(""));
    click(archive);
    expect(box(doc)).toBeNull();
    expect(archive.getAttribute("aria-expanded")).toBe("false");
    unbind();
    click(archive);
    expect(box(doc)).toBeNull();
  });

  it("Story archive: none is OF's Nothing found, a failure the red error, All Creators asks for a model", async () => {
    const doc = load("profile/index");
    const archive = doc.querySelector<HTMLElement>("[data-oi-story-archive]")!;
    let unbind = bindProfile(doc, handlers());
    click(archive);
    await flush();
    expect(box(doc)?.textContent).toBe("Nothing found");
    click(archive);
    unbind();
    unbind = bindProfile(doc, handlers({ read: () => Promise.reject(new Error("relay down")) }));
    click(archive);
    await flush();
    expect(box(doc)?.textContent).toBe("Could not load the story archive: relay down");
    expect((box(doc)?.firstElementChild as HTMLElement).style.color).toBe("rgb(255, 69, 69)");
    click(archive);
    unbind();
    unbind = bindProfile(doc, handlers({ read: null, username: null }));
    click(archive);
    expect(box(doc)?.textContent).toBe("Select a model to see its story archive");
    unbind();
  });

  it.each(["profile/index", "profile/state-more-menu"])("%s: Copy link to profile copies the Creator's OF link and OF's toast says so; All Creators asks for a model", async (p) => {
    const doc = load(p);
    const writeText = vi.fn(() => Promise.resolve());
    Object.defineProperty(doc.defaultView!.navigator, "clipboard", { value: { writeText }, configurable: true });
    const copies = [...doc.querySelectorAll<HTMLElement>("[data-oi-copy-link]")];
    expect(copies.length).toBeGreaterThan(0);
    let unbind = bindProfile(doc, handlers());
    for (const copy of copies) {
      click(copy);
      await flush();
      // A toast, not the note: the note sat in the header's button row and pushed EDIT PROFILE aside.
      expect(doc.querySelector("#oi-toast .toast__text")?.textContent).toBe("Link copied");
      expect(doc.getElementById("oi-note")).toBeNull();
      doc.getElementById("oi-toast")?.remove();
    }
    expect(writeText).toHaveBeenCalledWith("https://onlyfans.com/livemodel");
    unbind();
    unbind = bindProfile(doc, handlers({ username: null, read: null }));
    click(copies[0]);
    expect(doc.getElementById("oi-note")?.textContent).toBe("Select a model to copy its link");
    unbind();
    doc.getElementById("oi-note")?.remove();
  });

  it("the status menu: the Creator's status, OF's two rows, a pick shown at once and saved; a failed save puts it back", async () => {
    const doc = load("profile/index");
    const status = doc.querySelector<HTMLElement>("[data-oi-user-status]")!;
    const setVisible = vi.fn(() => Promise.resolve());
    let unbind = bindProfile(doc, handlers({ visible: false, setVisible }));
    expect(status.textContent?.trim()).toBe("Invisible");
    click(status);
    const rows = () => [...doc.querySelectorAll<HTMLElement>("#oi-menu [role='menuitem']")];
    expect(rows().map((r) => [r.textContent?.trim(), r.querySelector("input")?.checked])).toEqual([["Available", false], ["Invisible", true]]);
    click(rows()[0]);
    expect(status.textContent?.trim()).toBe("Available");
    expect(setVisible).toHaveBeenCalledWith(true);
    unbind();
    const failing = vi.fn(() => Promise.reject(new Error("boom")));
    unbind = bindProfile(doc, handlers({ visible: true, setVisible: failing }));
    click(status);
    click(rows()[1]);
    expect(status.textContent?.trim()).toBe("Invisible");
    await flush();
    expect(failing).toHaveBeenCalledWith(false);
    expect(status.textContent?.trim()).toBe("Available");
    expect(doc.getElementById("oi-note")?.textContent).toContain("Could not change the status");
    unbind();
    doc.getElementById("oi-note")?.remove();
    unbind = bindProfile(doc, handlers({ setVisible: null }));
    click(status);
    expect(doc.getElementById("oi-menu")).toBeNull();
    expect(doc.getElementById("oi-note")?.textContent).toBe("Select a model to save changes");
    unbind();
    doc.getElementById("oi-note")?.remove();
  });

  it.each(["profile/index", "profile/media"])("%s: the compact header holds More over the cover and turns sticky past 180px of scroll, as OF's", (p) => {
    const doc = load(p);
    const header = doc.querySelector<HTMLElement>(".js-compact-sticky-header")!;
    const back = header.querySelector(".g-page__header__btn")!;
    const more = header.querySelector(".b-compact-header__settings .dropdown-toggle")!;
    const sticky = [...header.querySelectorAll<HTMLElement>("[data-oi-sticky-only]")];
    const extra = () => sticky.filter((e) => e.style.display !== "none").map((e) => e.getAttribute("aria-label"));
    // The full header has Edit profile and Copy link; More is the compact header's only, as OF's.
    expect(doc.querySelector(".b-profile__header__user [aria-label='More']")).toBeNull();
    expect(header.querySelector(".b-group-profile-btns")!.lastElementChild!.classList.contains("b-compact-header__settings")).toBe(true);
    const scrollTo = (y: number) => {
      Object.defineProperty(window, "scrollY", { value: y, configurable: true });
      window.dispatchEvent(new Event("scroll"));
    };
    scrollTo(0);
    const unbind = bindProfile(doc, handlers());
    const sections = header.querySelector(".b-profile__sections")!;
    const state = () => [header.classList.contains("m-sticky"), back.className.match(/m-(?:white|light|default-color)/g), more.className.match(/m-(?:light|dark)\b/g), sections.classList.contains("d-flex"), extra()];
    const top = [false, ["m-white", "m-light"], ["m-light"], true, []];
    expect(state()).toEqual(top);
    scrollTo(180);
    expect(state()).toEqual(top);
    scrollTo(181);
    expect(state()).toEqual([true, ["m-default-color"], ["m-dark"], false, ["Edit profile", "Copy link to profile"]]);
    const [edit, copy] = sticky;
    expect([edit.getAttribute("href"), copy.hasAttribute("data-oi-copy-link"), copy.hasAttribute("data-oi-wired")]).toEqual(["/of-manager/settings/profile", true, true]);
    scrollTo(40);
    expect(state()).toEqual(top);
    unbind();
    scrollTo(500);
    expect(header.classList.contains("m-sticky")).toBe(false);
    scrollTo(0);
  });

  it("More info expands the bio and Collapse info folds it; Spotify's title folds and opens its section", () => {
    const doc = load("profile/index");
    // A bio taller than its 85px fold (jsdom lays nothing out).
    Object.defineProperty(doc.querySelector(".b-user-info__content > .g-truncated-text")!, "scrollHeight", { configurable: true, value: 200 });
    const unbind = bindProfile(doc, handlers());
    const bio = doc.querySelector<HTMLElement>("[data-oi-bio-toggle]")!;
    const text = bio.parentElement!.querySelector<HTMLElement>(".g-truncated-text")!;
    expect([bio.style.display, text.classList.contains("m-over-limit"), text.classList.contains("m-collapsed")]).toEqual(["", true, true]);
    click(bio);
    // OF's expanded box: its own 20vh with a scroll bar (m-over-limit:not(.m-collapsed)), no inline height.
    expect([bio.textContent?.trim(), text.classList.contains("m-collapsed"), text.style.maxHeight]).toEqual(["Collapse info", false, ""]);
    click(bio);
    expect([bio.textContent?.trim(), text.classList.contains("m-collapsed"), text.style.maxHeight]).toEqual(["More info", true, "85px"]);
    const spotify = doc.querySelector<HTMLElement>("[data-oi-collapse]")!;
    click(spotify);
    expect([spotify.parentElement!.classList.contains("m-active"), (spotify.nextElementSibling as HTMLElement).style.display]).toEqual([false, "none"]);
    click(spotify);
    expect([spotify.parentElement!.classList.contains("m-active"), (spotify.nextElementSibling as HTMLElement).style.display]).toEqual([true, ""]);
    unbind();
  });

  it("the bio keeps the Creator's line breaks with no captured gap; More info shows only while it overflows its fold (U16)", () => {
    const doc = load("profile/index");
    const p = doc.querySelector<HTMLElement>(".b-user-info__text > p")!;
    expect([p.querySelectorAll("br").length, p.style.whiteSpace]).toEqual([0, "pre-line"]);
    applyIdentity(doc, { username: "livemodel", about: "First line<br />Second line" });
    expect(p.textContent).toBe("First line\nSecond line");
    let refit = () => {};
    const observed: Element[] = [];
    vi.stubGlobal("ResizeObserver", class {
      constructor(cb: () => void) {
        refit = cb;
      }
      observe(el: Element) {
        observed.push(el);
      }
      disconnect() {}
    });
    const text = doc.querySelector<HTMLElement>(".b-user-info__text")!;
    let height = 40;
    Object.defineProperty(text.parentElement!, "scrollHeight", { configurable: true, get: () => height });
    try {
      const unbind = bindProfile(doc, handlers());
      const bio = doc.querySelector<HTMLElement>("[data-oi-bio-toggle]")!;
      const box = text.parentElement!;
      const state = () => [bio.style.display, box.classList.contains("m-over-limit"), box.classList.contains("m-collapsed")];
      // A short bio: whole, unfaded, no More info (OF shows it only over the limit).
      expect(observed).toEqual([text]);
      expect(state()).toEqual(["none", false, false]);
      // Its text grew (a longer bio, a narrower frame): folded, with More info.
      height = 300;
      refit();
      expect(state()).toEqual(["", true, true]);
      click(bio);
      expect(state()).toEqual(["", true, false]);
      // Short again while open: whole, folded state reset.
      height = 40;
      refit();
      expect([...state(), bio.textContent?.trim(), bio.getAttribute("aria-expanded"), box.style.maxHeight]).toEqual(["none", false, false, "More info", "false", "85px"]);
      unbind();
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it("the Media tab's Photo marks itself current, keeps the filter on the frame and tells ofMirrorData", () => {
    const doc = load("profile/media");
    const unbind = bindProfile(doc, handlers());
    const changed = vi.fn();
    doc.addEventListener(PROFILE_CHANGE, changed);
    click(doc.querySelector("[data-oi-media-tab='photo']")!);
    expect(doc.documentElement.dataset.oiMediaType).toBe("photo");
    expect([...doc.querySelectorAll("[data-oi-media-tab].m-current")].map((t) => t.getAttribute("data-oi-media-tab"))).toEqual(["photo"]);
    expect(changed).toHaveBeenCalledTimes(1);
    doc.removeEventListener(PROFILE_CHANGE, changed);
    delete doc.documentElement.dataset.oiMediaType;
    unbind();
  });
});

describe("profile/state-more-menu: the header's More menu", () => {
  it("Statistics opens Statistics' Overview (as OF's), QR code Settings' QR code page, Copy link to profile is wired", () => {
    const doc = load("profile/state-more-menu");
    const items = [...doc.querySelectorAll<HTMLElement>("[role='menuitem']")];
    const item = (t: string) => items.find((i) => i.textContent?.trim().toLowerCase() === t)!;
    expect(item("statistics").querySelector("a.of-state-link")?.getAttribute("href")).toBe("/of-manager/statistics/overview/earnings");
    expect([item("qr code").getAttribute("aria-disabled"), item("qr code").querySelector("a.of-state-link")?.getAttribute("href")]).toEqual([null, "/of-manager/settings/qrcode"]);
    expect([item("copy link to profile").hasAttribute("data-oi-copy-link"), item("copy link to profile").querySelector("a")]).toEqual([true, null]);
  });

  it("the open menu's content column stops being a stacking context under the backdrop, so its items take their clicks (U2)", () => {
    const doc = load("profile/state-more-menu");
    // OF's own rule (its CSS is linked, not inline): the content column is position relative, z-index 0.
    const of = doc.createElement("style");
    of.textContent = ".l-wrapper__content { position: relative; z-index: 0; }";
    doc.head.prepend(of);
    const column = doc.querySelector(".l-wrapper__content")!;
    expect(column.querySelector(".of-state-menu [role='menuitem']")).not.toBeNull();
    expect(doc.querySelector("a.of-state-backdrop")).not.toBeNull();
    expect(getComputedStyle(column).zIndex).toBe("auto");
    // A page with no open menu keeps OF's.
    load("profile/index").head.prepend(of);
    expect(getComputedStyle(document.querySelector(".l-wrapper__content")!).zIndex).toBe("0");
  });
});

describe("My profile from OF's captured responses (app/lib/__fixtures__/of)", () => {
  it("/users/me, /labels and /stories/highlights: the counts, label tabs and highlight tiles", () => {
    const doc = load("profile/index");
    applyData(doc, "profile/index", { profile: { user: ME, labels: LABELS_RESP.list, highlights: HIGHLIGHTS.list } }, (u) => `/img?u=${u}`);
    expect(texts(doc, SECTIONS)).toEqual([ME.photosCount, ME.videosCount, ME.favoritedCount, ME.subscribersCount].map((n) => formatCount(n!)));
    expect(texts(doc, ".b-tabs__nav__text").slice(0, 2)).toEqual([`${ME.postsCount} posts`, `${ME.mediasCount} Media`]);
    const custom = LABELS_RESP.list.filter((l) => l.id !== "archived" && l.id !== "private_archived");
    expect(texts(doc, LABELS)).toEqual([`All ${ME.postsCount}`, `Archive ${ME.archivedPostsCount}`, ...custom.map((l) => `${l.name} ${l.postsCount}`)]);
    const tiles = shown(doc, ".stories-list .b-story-item").slice(3);
    expect(tiles.map((t) => t.querySelector(".b-story-item__text")?.textContent?.trim())).toEqual(HIGHLIGHTS.list.map((h) => h.title));
  });

  it("/users/{id}/posts: one wall row per post, no example row; /posts/photos and /posts/videos: the Media grid and the Recent strip", () => {
    const wall = load("profile/index");
    applyData(wall, "profile/index", { posts: POSTS });
    expect(shown(wall, ".user_posts [data-oi-post]")).toHaveLength(POSTS.length);
    expect(texts(wall, ".user_posts [data-oi-empty]")).toEqual([]);
    const media: MediaPost[] = [...PHOTOS.map((p) => ({ ...p, _kind: "photo" as const })), ...VIDEOS.map((p) => ({ ...p, _kind: "video" as const }))];
    const grid = load("profile/media");
    applyData(grid, "profile/media", { profileMedia: media }, (u) => `/img?u=${u}`);
    expect(texts(grid, ".user_posts [data-oi-empty]")).toEqual([]);
    expect(shown(grid, "[data-oi-recent] .m-recent-list a[at-attr='photo_item']").length).toBe(Math.min(3, new Set(media.map((p) => p.id)).size));
  });

  it("/promotions ({hasMore, items}): finished promotions put no offer card up", () => {
    const doc = load("profile/index");
    expect(PROMOTIONS.items.every((p) => p.isFinished)).toBe(true);
    applyData(doc, "profile/index", { promotions: PROMOTIONS.items });
    expect(shown(doc, ".b-offer-join")).toEqual([]);
  });
});

describe("standInModel: My profile and Messages in All models show the first model", () => {
  const accounts = [{ id: "7" }, { id: "9" }];
  it("All models, a My profile or Messages page: the first model; a model selected, another page or no model: none", () => {
    expect(standInModel("/of-mirror/pages/profile/index.html", null, accounts)).toBe("7");
    expect(standInModel("/of-mirror/pages/profile/media.html", null, accounts)).toBe("7");
    for (const p of ["index", "chat", "chat/state-price", "send"]) expect(standInModel(`/of-mirror/pages/messages/${p}.html`, null, accounts)).toBe("7");
    expect(standInModel("/of-mirror/pages/messages/index.html", "9", accounts)).toBeNull();
    expect(standInModel("/of-mirror/pages/messages/index.html", null, [])).toBeNull();
    expect(standInModel("/of-mirror/pages/profile/index.html", "9", accounts)).toBeNull();
    expect(standInModel("/of-mirror/pages/home/index.html", null, accounts)).toBeNull();
    expect(standInModel("/of-mirror/pages/profile/index.html", null, [])).toBeNull();
    // The Vault too, with its state pages; Home's vault dialog is not the Vault page.
    expect(standInModel("/of-mirror/pages/vault/index.html", null, accounts)).toBe("7");
    expect(standInModel("/of-mirror/pages/vault/state-sort-dropdown.html", null, accounts)).toBe("7");
    expect(standInModel("/of-mirror/pages/vault/index.html", "9", accounts)).toBeNull();
    expect(standInModel("/of-mirror/pages/home/state-vault.html", null, accounts)).toBeNull();
  });

  it("Statements' Earnings (and statements/index, its default tab) too; the other Statements tabs not", () => {
    expect(standInModel("/of-mirror/pages/statements/earnings.html", null, accounts)).toBe("7");
    expect(standInModel("/of-mirror/pages/statements/index.html", null, accounts)).toBe("7");
    expect(standInModel("/of-mirror/pages/statements/earnings.html", "9", accounts)).toBeNull();
    expect(standInModel("/of-mirror/pages/statements/payouts.html", null, accounts)).toBeNull();
    expect(standInModel("/of-mirror/pages/statements/stats/earnings.html", null, accounts)).toBeNull();
  });
});
