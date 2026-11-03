import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it, vi } from "vitest";
import { applyData } from "./ofMirrorData";
import { isVaultPage, nextVaultOffset, vaultPageMedia, vaultPagesQuery } from "./ofMirrorDataQueries";
import type { VaultList, VaultMediaResp } from "./relay";
import { load, shown, texts } from "./ofMirrorData.fixtures";

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
