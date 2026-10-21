import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it, vi } from "vitest";
import { applyData } from "./ofMirrorData";
import { formatCount } from "./ofMirrorIdentity";
import { ARCHIVE_PATH, bindProfile, PROFILE_CHANGE, standInModel, type Highlight, type MediaPost, type MirrorProfile, type ProfileHandlers, type ProfileUser } from "./ofMirrorProfile";
import type { MirrorPost, Promotion } from "./ofMirrorFeeds";
import type { PostLabel } from "./ofMirrorData";
import { bindStory } from "./ofMirrorPost";
import { VIEWER } from "./ofMirrorVault";

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
    for (const sel of ["button[aria-label='Compact view']", "button[aria-label='Sort']", "button.m-user-status"]) expect(doc.querySelector(sel)?.hasAttribute("disabled"), sel).toBe(true);
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
    // OF's highlight `cover` is the cover story's picture URL.
    expect([one, two].map((t) => t.querySelector("img")?.getAttribute("src"))).toEqual([`/img?u=${H1.cover}`, `/img?u=${H2.cover}`]);
    applyData(doc, "profile/index", {});
    expect(doc.documentElement.innerHTML).toBe(html);
  });

  it("a highlight tile opens its cover in the viewer (in either scope); Escape closes it", () => {
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

  it.each(["profile/index", "profile/state-more-menu"])("%s: Copy link to profile copies the Creator's OF link and notes it; All Creators asks for a model", async (p) => {
    const doc = load(p);
    const writeText = vi.fn(() => Promise.resolve());
    Object.defineProperty(doc.defaultView!.navigator, "clipboard", { value: { writeText }, configurable: true });
    const copies = [...doc.querySelectorAll<HTMLElement>("[data-oi-copy-link]")];
    expect(copies.length).toBeGreaterThan(0);
    let unbind = bindProfile(doc, handlers());
    for (const copy of copies) {
      click(copy);
      await flush();
      expect(doc.getElementById("oi-note")?.textContent).toBe("Link copied");
    }
    expect(writeText).toHaveBeenCalledWith("https://onlyfans.com/livemodel");
    unbind();
    unbind = bindProfile(doc, handlers({ username: null, read: null }));
    click(copies[0]);
    expect(doc.getElementById("oi-note")?.textContent).toBe("Select a model to copy its link");
    unbind();
    doc.getElementById("oi-note")?.remove();
  });

  it("More info expands the bio and Collapse info folds it; Spotify's title folds and opens its section", () => {
    const doc = load("profile/index");
    const unbind = bindProfile(doc, handlers());
    const bio = doc.querySelector<HTMLElement>("[data-oi-bio-toggle]")!;
    const text = bio.parentElement!.querySelector<HTMLElement>(".g-truncated-text")!;
    click(bio);
    expect([bio.textContent?.trim(), text.classList.contains("m-collapsed"), text.style.maxHeight]).toEqual(["Collapse info", false, "none"]);
    click(bio);
    expect([bio.textContent?.trim(), text.classList.contains("m-collapsed"), text.style.maxHeight]).toEqual(["More info", true, "85px"]);
    const spotify = doc.querySelector<HTMLElement>("[data-oi-collapse]")!;
    click(spotify);
    expect([spotify.parentElement!.classList.contains("m-active"), (spotify.nextElementSibling as HTMLElement).style.display]).toEqual([false, "none"]);
    click(spotify);
    expect([spotify.parentElement!.classList.contains("m-active"), (spotify.nextElementSibling as HTMLElement).style.display]).toEqual([true, ""]);
    unbind();
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
  it("Statistics opens Statistics' Overview (as OF's), QR code is disabled with the tooltip, Copy link to profile is wired", () => {
    const doc = load("profile/state-more-menu");
    const items = [...doc.querySelectorAll<HTMLElement>("[role='menuitem']")];
    const item = (t: string) => items.find((i) => i.textContent?.trim().toLowerCase() === t)!;
    expect(item("statistics").querySelector("a.of-state-link")?.getAttribute("href")).toBe("/of-manager/statistics/overview/earnings");
    expect([item("qr code").getAttribute("aria-disabled"), item("qr code").title, item("qr code").querySelector("a")]).toEqual(["true", NOT_YET, null]);
    expect([item("copy link to profile").hasAttribute("data-oi-copy-link"), item("copy link to profile").querySelector("a")]).toEqual([true, null]);
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
