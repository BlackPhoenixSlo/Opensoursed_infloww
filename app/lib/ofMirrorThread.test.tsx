import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { applyData, GALLERY_EMPTY_CAP, galleryItems, galleryStalled, rowsOf, type MirrorData } from "./ofMirrorData";
import { attachmentIcons, bindFind, FIND_MS, FIND_PAGES, galleryRequest, galleryTab, searchIds, TOO_FAR, useThreadFind, type ThreadMessage } from "./ofMirrorThread";
import { NOT_YET } from "./ofMirrorWrites";
import { relay, type OFMessage } from "./relay";
import { useFanChatMedia } from "@/hooks/useFanChatMedia";

const page = (p: string) => {
  document.documentElement.innerHTML = readFileSync(resolve(__dirname, `../public/of-mirror/pages/messages/${p}.html`), "utf8");
  return document;
};
const fixture = <T,>(name: string): T => JSON.parse(readFileSync(resolve(__dirname, `__fixtures__/of/${name}.json`), "utf8")) as T;
const shown = (d: Document, sel: string) => [...d.querySelectorAll<HTMLElement>(sel)].filter((e) => !e.closest("[style*='display:none']"));
const PLACEHOLDER = /Fan \d|@fan\d|Lorem|List \d/;
const FAN = { id: 3035, name: "Synthetic Creator", username: "synthcreator", avatar: "https://cdn.example/a.jpg" };
const ME = { id: 1001, name: "Model", username: "model", avatar: "https://cdn.example/me.jpg" };

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.useRealTimers();
});

describe("Gallery: the chat's real media, OF's tiles and tabs", () => {
  const items = galleryItems([fixture<{ list: ThreadMessage[] }>("messages-chat-media-locked")]);
  const draw = (gallery: MirrorData["gallery"], extra: MirrorData = {}) => {
    const d = page("chat/gallery");
    applyData(d, "messages/chat/gallery", { chat: "3035", chatFan: FAN, me: ME, gallery, ...extra }, (u) => `/img?u=${u}`);
    return d;
  };

  it("a tile a media message, from OF's captured /chats/{id}/media page: pictures, play buttons, OF's lock card for a PPV the Creator cannot view", () => {
    const d = draw({ tab: "all", items });
    const tiles = shown(d, ".b-gallery-wrapper .b-photos > [data-oi-data]");
    expect(tiles).toHaveLength(items.length);
    const locked = items.filter((m) => !(m.media ?? []).some((x) => x.canView !== false && x.files?.thumb?.url));
    expect(locked.length).toBeGreaterThan(0);
    expect(tiles.filter((t) => t.querySelector(".b-post__unknown")).map((t) => t.querySelector(".b-post__unknown__price")!.textContent!.trim())).toEqual(locked.map((m) => `$${m.price}`));
    // Every tile opens the chat at its message (OF's ?firstId=).
    expect(tiles.map((t) => (t.matches("a") ? t : t.querySelector("a"))!.getAttribute("href"))).toEqual(items.map((m) => `/of-manager/messages/chat?chat=3035&firstId=${m.id}`));
    // A visible tile: its thumb through the image proxy, the sender's avatar, a play button only on a moving first media.
    const visible = tiles.filter((t) => t.querySelector("img.b-photos__item__img"));
    for (const t of visible) expect(t.querySelector("img.b-photos__item__img")!.getAttribute("src")).toMatch(/^\/img\?u=https:\/\/public\.onlyfans\.com\//);
    const moving = items.filter((m) => !locked.includes(m) && ["gif", "video"].includes((m.media ?? []).find((x) => x.canView !== false)?.type ?? ""));
    expect(visible.filter((t) => t.querySelector(".b-photos__item__play-btn"))).toHaveLength(moving.length);
    expect(visible.filter((t) => t.querySelector(".g-avatar img")?.getAttribute("src") === "/img?u=https://cdn.example/me.jpg")).toHaveLength(items.filter((m) => m.fromUser?.id === 1001 && !locked.includes(m)).length);
    for (const t of tiles) expect(t.textContent).not.toMatch(PLACEHOLDER);
    expect(shown(d, ".b-gallery-wrapper [data-oi-empty]").filter((e) => e.style.display !== "none")).toEqual([]);
  });

  it("a PPV tile: OF's price label (locked while the Creator's own is unpaid, unlocked once opened); a media list's counts and lengths", () => {
    const own = { ...items.find((m) => (m.media ?? []).some((x) => x.files?.thumb?.url))!, id: 5, fromUser: { id: 1001 }, isFree: false, price: 12, isOpened: false } as ThreadMessage;
    const d = draw({ tab: "all", items: [own, { ...own, id: 6, isOpened: true }] });
    const labels = shown(d, ".b-photos > [data-oi-data] .m-payment-label");
    expect(labels.map((l) => [l.textContent!.trim(), l.querySelector("svg")!.getAttribute("data-icon-name")])).toEqual([["$12", "icon-locked"], ["$12", "icon-unlocked"]]);
    expect(attachmentIcons([{ type: "photo" }, { type: "photo" }, { type: "video", duration: 446 }] as never, true)).toEqual([
      { icon: "icon-media", content: "2" },
      { icon: "icon-video", content: "7:26" },
      { icon: "icon-text-frame-off", content: null },
    ]);
    expect(attachmentIcons([{ type: "video", duration: 86 }, { type: "video", duration: 76 }] as never)).toEqual([{ icon: "icon-video", content: "2" }]);
  });

  it("the tabs link to this chat's views, the open one current", () => {
    const d = draw({ tab: "photos", items: [] }, { listQuery: "tab=pinned" });
    const tabs = [...d.querySelectorAll<HTMLAnchorElement>("a[data-oi-gallery]")];
    expect(tabs.map((a) => a.getAttribute("href"))).toEqual([
      "/of-manager/messages/chat/gallery?chat=3035&tab=pinned",
      "/of-manager/messages/chat/gallery?chat=3035&tab=pinned&media=opened",
      "/of-manager/messages/chat/gallery?chat=3035&tab=pinned&media=purchased",
      "/of-manager/messages/chat/gallery?chat=3035&tab=pinned&media=photos",
      "/of-manager/messages/chat/gallery?chat=3035&tab=pinned&media=videos",
      "/of-manager/messages/chat/gallery?chat=3035&tab=pinned&media=audios",
    ]);
    expect(tabs.filter((a) => a.classList.contains("m-current")).map((a) => a.dataset.oiGallery)).toEqual(["photos"]);
    expect(tabs.some((a) => a.hasAttribute("disabled") || a.getAttribute("title") === NOT_YET)).toBe(false);
    // Its Back goes to the chat, its header says whose.
    expect(d.querySelector(".b-gallery-wrapper a[aria-label='Back']")!.getAttribute("href")).toBe("/of-manager/messages/chat?chat=3035&tab=pinned");
    expect(d.querySelector(".b-gallery-wrapper .b-chat__user-status")!.textContent).toBe("with Synthetic Creator");
    expect(galleryTab(new URLSearchParams("media=videos"))).toBe("videos");
    expect(galleryTab(new URLSearchParams("media=bogus"))).toBe("all");
  });

  it("loading, a Relay error and no media: OF's prompt says which, never the previous tab's tiles", () => {
    const text = (d: Document) => d.querySelector<HTMLElement>(".b-gallery-wrapper [data-oi-empty] .empty-message span")!;
    expect(text(draw({ tab: "all", status: null })).textContent).toBe("Loading media…");
    const err = text(draw({ tab: "all", status: "502 Bad Gateway" }));
    expect([err.textContent, err.style.color]).toEqual(["Could not load media: 502 Bad Gateway", "rgb(255, 69, 69)"]);
    expect(text(draw({ tab: "all", items: [] })).textContent).toBe("Nothing found");
    // The next page's loader under the grid.
    expect(draw({ tab: "all", items, more: true }).querySelector("#oi-gallery-more")).not.toBeNull();
    // Pages that drew no tile, with more to come: still loading, never a false "Nothing found".
    expect(text(draw({ tab: "audios", items: [], next: true })).textContent).toBe("Loading media…");
    // The next page failed: its error under the grid, the tiles kept; with no tile, in the prompt.
    const failed = draw({ tab: "all", items, next: true, moreError: "502 Bad Gateway" });
    expect(failed.querySelector("#oi-gallery-more")!.textContent).toBe("Could not load more media: 502 Bad GatewayRetry");
    // A Retry under the grid and in the prompt (ofMirrorData reads its click); none while the page is fine.
    expect(failed.querySelectorAll("[data-oi-gallery-retry]")).toHaveLength(1);
    expect(draw({ tab: "all", status: "502 Bad Gateway" }).querySelectorAll("[data-oi-gallery-retry]")).toHaveLength(1);
    expect(draw({ tab: "all", items }).querySelectorAll("[data-oi-gallery-retry]")).toHaveLength(0);
    expect(shown(failed, ".b-gallery-wrapper .b-photos > [data-oi-data]")).toHaveLength(items.length);
    expect(text(draw({ tab: "all", items: [], next: true, moreError: "502 Bad Gateway" })).textContent).toBe("Could not load media: 502 Bad Gateway");
  });

  it("paging stops after GALLERY_EMPTY_CAP pages in a row bring no new item (a repeat counts as none)", () => {
    const page = (...ids: number[]) => ({ list: ids.map((id) => ({ id })) });
    const empties = (n: number) => Array.from({ length: n }, () => page());
    expect(galleryStalled([page(1, 2), ...empties(GALLERY_EMPTY_CAP - 1)])).toBe(false);
    expect(galleryStalled([page(1, 2), ...empties(GALLERY_EMPTY_CAP)])).toBe(true);
    expect(galleryStalled([page(1, 2), ...empties(GALLERY_EMPTY_CAP - 1), page(1)])).toBe(true);
    expect(galleryStalled([...empties(GALLERY_EMPTY_CAP), page(3)])).toBe(false);
  });

  it("an audio message (no picture): OF's tile with the voice icon, never the lock card; the lock card only for media the Creator cannot view", () => {
    const audio = { id: 71, fromUser: { id: 3035 }, isFree: false, price: 5, isOpened: true, media: [{ id: 1, type: "audio", canView: true, duration: 12, files: {} }] } as unknown as ThreadMessage;
    const hidden = { ...audio, id: 72, isOpened: false, media: [{ id: 2, type: "photo", canView: false, files: {} }] } as unknown as ThreadMessage;
    const d = draw({ tab: "audios", items: [audio, hidden] });
    const [a, h] = shown(d, ".b-gallery-wrapper .b-photos > [data-oi-data]");
    expect(a.querySelector(".b-post__unknown")).toBeNull();
    expect(a.querySelector("[data-oi-no-thumb] svg")!.getAttribute("data-icon-name")).toBe("icon-voice");
    expect(a.getAttribute("href")).toBe("/of-manager/messages/chat?chat=3035&firstId=71");
    expect(h.querySelector(".b-post__unknown__price")!.textContent!.trim()).toBe("$5");
    expect(d.querySelector<HTMLElement>(".b-gallery-wrapper [data-oi-empty]")!.style.display).toBe("none");
  });
});

describe("useFanChatMedia for the gallery tabs: OF's exact reads", () => {
  const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>{children}</QueryClientProvider>;
  it.each([
    ["all", "/api/of/v2/chats/3035/media?limit=20&skip_users=all"],
    ["opened", "/api/of/v2/chats/3035/media?limit=20&skip_users=all&opened=1"],
    ["purchased", "/api/of/v2/chats/3035/media?limit=20&skip_users=all&from_user=80000112&purchased=1"],
    ["photos", "/api/of/v2/chats/3035/media/photos?limit=20&skip_users=all"],
    ["videos", "/api/of/v2/chats/3035/media/videos?limit=20&skip_users=all"],
    ["audios", "/api/of/v2/chats/3035/media/audios?limit=20&skip_users=all"],
  ] as const)("%s: GET %s, then OF's last_id cursor", async (tab, path) => {
    const get = vi.spyOn(relay, "get").mockResolvedValue(fixture("messages-chat-media-locked"));
    const { result } = renderHook(() => useFanChatMedia("80000112", 3035, galleryRequest(tab)), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(get.mock.calls[0][0]).toBe(path);
    expect(get.mock.calls[0][1]).toMatchObject({ accountId: "80000112" });
    await result.current.fetchNextPage();
    expect(get.mock.calls[1][0]).toBe(`${path}&last_id=11689647527330`);
  });
  it("a Relay error is the hook's error (the grid shows it), not a throw", async () => {
    vi.spyOn(relay, "get").mockRejectedValue(new Error("404 Not Found"));
    const { result } = renderHook(() => useFanChatMedia("80000112", 3035, galleryRequest("photos")), { wrapper });
    await waitFor(() => expect(result.current.isError).toBe(true));
    expect((result.current.error as Error).message).toBe("404 Not Found");
  });
});

describe("the thread: incoming locked PPVs and tips as OF draws them", () => {
  const locked = rowsOf<ThreadMessage>(fixture("messages-thread-locked"))!;
  it("another creator's PPV: its free previews, then OF's purchase card, Unlock for $X disabled (a payment)", () => {
    const d = page("chat");
    applyData(d, "messages/chat", { chat: "3035", thread: { fan: FAN, messages: locked } });
    const ppv = locked.filter((m) => m.canPurchase && m.fromUser?.id === 3035);
    expect(ppv.length).toBeGreaterThan(2);
    for (const m of ppv) {
      const b = d.querySelector<HTMLElement>(`[data-oi-data] [data-oi-msg="${m.id}"]`)!;
      expect(b.classList.contains("m-purchase") && b.classList.contains("m-not-paid-yet")).toBe(true);
      const btn = b.querySelector<HTMLButtonElement>(".m-purchase-chat button.post-subscribe-btn")!;
      expect([btn.textContent!.trim(), btn.disabled, btn.title]).toEqual([`Unlock for $${m.price}`, true, NOT_YET]);
      expect(b.querySelector(".m-purchase-chat .m-price-lock")!.textContent!.trim()).toBe(`$${m.price}`);
      // Only the media the Creator may view are pictures (OF's free previews).
      expect(b.querySelectorAll(".b-chat__message__media img.b-post__media__img").length).toBe((m.media ?? []).filter((x) => x.canView !== false && x.files?.thumb?.url).length);
      expect(b.querySelector(".b-chat__message__payment-state")!.textContent!.trim()).toBe(`$${m.price} not paid yet`);
    }
    // A free message has no card; the Creator's own message never gets one.
    for (const m of locked.filter((x) => !x.canPurchase)) expect(d.querySelector(`[data-oi-data] [data-oi-msg="${m.id}"] .m-purchase-chat`)).toBeNull();
  });
  it("a tip: OF's tip line (the funds icon, the words, a heart) and the fan's note; no price line, no plain text", () => {
    const tip = rowsOf<ThreadMessage>(fixture("messages-thread-tip"))![0];
    const d = page("chat");
    applyData(d, "messages/chat", { chat: String(tip.fromUser!.id), thread: { fan: FAN, messages: [tip] } });
    const b = d.querySelector<HTMLElement>(`[data-oi-data] [data-oi-msg="${tip.id}"]`)!;
    expect(b.classList.contains("m-tip")).toBe(true);
    const line = b.querySelector(".b-chat__message__tip-text")!;
    expect([...line.querySelectorAll("svg")].map((s) => s.getAttribute("data-icon-name"))).toEqual(["icon-funds", "icon-likes"]);
    expect(line.querySelector("[at-attr='msg_tip']")!.textContent).toBe("I sent you a $10.00 tip");
    expect(b.querySelector(".b-chat__message__text-content")!.textContent).toBe("Synthetic tip note");
    expect(line.hasAttribute("data-v-364cdc78")).toBe(true); // OF's scoped tip style applies
    expect(b.querySelector(".b-chat__message__payment-state")).toBeNull();
    expect(b.querySelector(".b-chat__message__text-holder")).toBeNull();
  });
});

describe("pinned messages: the header's pin and the chat's pinned page", () => {
  const pinned = rowsOf<OFMessage>(fixture("messages-pinned"))!;
  it("the pin lights (icon-pin-on) and opens this chat's pinned page while it has pins; else OF's grey 'No pinned messages'", () => {
    for (const [count, cls, name, label] of [[1, "m-active", "icon-pin-on", "Open pinned messages"], [0, "m-gray", "icon-pin", "No pinned messages"]] as const) {
      const d = page("chat");
      applyData(d, "messages/chat", { chat: "3002", pinnedCount: count, thread: { fan: FAN, messages: [] } });
      const a = d.querySelector<HTMLAnchorElement>("a[at-attr='pinned_btn']")!;
      expect(a.getAttribute("href")).toBe("/of-manager/messages/chat/pinned?chat=3002");
      expect([a.classList.contains(cls), a.querySelector("svg")!.getAttribute("data-icon-name"), a.getAttribute("aria-label")]).toEqual([true, name, label]);
      expect(a.hasAttribute("disabled")).toBe(false);
      expect(d.querySelector("a[at-attr='gallery_btn']")!.getAttribute("href")).toBe("/of-manager/messages/chat/gallery?chat=3002");
    }
  });
  it("the pinned page: OF's chat page titled Pinned messages, with <name>, its pins (GET …?filter=pinned), no composer; none: OF's placeholder", () => {
    const d = page("chat/pinned");
    expect(d.querySelector(".b-chat__header h1")!.textContent!.trim()).toBe("Pinned messages");
    expect(d.querySelector("[contenteditable][aria-label='Textbox field']")).toBeNull();
    applyData(d, "messages/chat/pinned", { chat: "3002", chatFan: FAN, thread: { fan: FAN, messages: pinned } });
    expect(shown(d, ".b-chat__messages-wrapper.m-pinned [data-oi-msg]").map((b) => b.dataset.oiMsg)).toEqual(pinned.map((m) => String(m.id)));
    expect(d.querySelector("[data-oi-with]")!.textContent).toBe("with Synthetic Creator");
    expect(d.querySelector(".b-chat__header a[aria-label='Back']")!.getAttribute("href")).toBe("/of-manager/messages/chat?chat=3002");
    const d2 = page("chat/pinned");
    applyData(d2, "messages/chat/pinned", { chat: "3002", thread: { fan: FAN, messages: [] } });
    expect(d2.querySelector(".b-chat__messages [data-oi-empty]")!.textContent).toBe("Pinned messages will be shown here");
  });
});

describe("Find in chat (GET …/messages/search?query=, OF's flat id list)", () => {
  const thread = rowsOf<OFMessage>(fixture("messages-thread"))!;
  const setup = (search: (q: string) => Promise<string[]>) => {
    const d = page("chat");
    applyData(d, "messages/chat", { chat: "2006", thread: { fan: FAN, messages: thread } });
    const reveal = vi.fn(async () => true);
    const ctx = { search: vi.fn(search), reveal };
    const find = bindFind(d, ctx);
    return { d, ctx, find };
  };
  const input = (d: Document) => d.querySelector<HTMLInputElement>(".b-chat__header form.b-chat__search-form input[name='query']")!;
  const type = (d: Document, v: string) => {
    input(d).value = v;
    input(d).dispatchEvent(new Event("input", { bubbles: true }));
  };
  const flush = () => new Promise((r) => setTimeout(r, 0));
  const textOf = (m: OFMessage) => (m.text ?? "").replace(/<[^>]+>/g, "").trim();
  const hits = thread.filter((m) => /synthetic/i.test(textOf(m))).slice(-2).reverse(); // newest first, as OF
  const ids = hits.map((m) => String(m.id));

  it("Find opens OF's bar; 1-2 characters wait, 3 search once the keys stop; the newest hit is drawn, centred and marked", async () => {
    vi.useFakeTimers();
    const { d, ctx } = setup(async () => ids);
    expect(d.querySelector("button[at-attr='search_btn']")!.hasAttribute("disabled")).toBe(false);
    d.querySelector<HTMLButtonElement>("button[at-attr='search_btn']")!.click();
    const header = input(d).closest(".b-chat__header")!;
    expect(header.classList.contains("m-search-form-visible")).toBe(true);
    type(d, "sy");
    vi.advanceTimersByTime(FIND_MS);
    expect(ctx.search).not.toHaveBeenCalled();
    type(d, "syn");
    vi.advanceTimersByTime(FIND_MS - 1);
    expect(ctx.search).not.toHaveBeenCalled();
    vi.advanceTimersByTime(1);
    vi.useRealTimers();
    await flush();
    await flush();
    expect(ctx.search).toHaveBeenCalledWith("syn");
    expect(ctx.reveal).toHaveBeenCalledWith(ids[0], expect.any(Function));
    expect(d.querySelector(".b-chat__search__results-count")!.textContent!.trim()).toBe("1/2");
    const mark = d.querySelector(`[data-oi-msg="${ids[0]}"] .b-chat__message__text-highlighted`)!;
    expect(mark.textContent!.toLowerCase()).toBe("syn");
    // Up: the older hit; then up is off (the oldest), down on.
    d.querySelector<HTMLButtonElement>("[data-oi-find='prev']")!.click();
    await flush();
    await flush();
    expect(ctx.reveal).toHaveBeenLastCalledWith(ids[1], expect.any(Function));
    expect(d.querySelector(".b-chat__search__results-count")!.textContent!.trim()).toBe("2/2");
    expect(d.querySelector<HTMLButtonElement>("[data-oi-find='prev']")!.disabled).toBe(true);
    expect(d.querySelector<HTMLButtonElement>("[data-oi-find='next']")!.disabled).toBe(false);
    expect(d.querySelectorAll(".b-chat__message__text-highlighted").length).toBeGreaterThan(0);
    expect(d.querySelector(`[data-oi-msg="${ids[0]}"] .b-chat__message__text-highlighted`)).toBeNull();
  });

  it("a redraw (a poll) puts the mark back; closing the bar clears it and the count", async () => {
    const { d, find } = setup(async () => ids);
    d.querySelector<HTMLButtonElement>("button[at-attr='search_btn']")!.click();
    input(d).value = "syn";
    input(d).form!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    await flush();
    await flush();
    applyData(d, "messages/chat", { chat: "2006", thread: { fan: FAN, messages: thread } });
    expect(d.querySelector(`[data-oi-msg="${ids[0]}"] .b-chat__message__text-highlighted`)).toBeNull();
    find.redrawn();
    expect(d.querySelector(`[data-oi-msg="${ids[0]}"] .b-chat__message__text-highlighted`)).not.toBeNull();
    d.querySelector<HTMLButtonElement>("button[at-attr='close_search']")!.click();
    expect(input(d).closest(".b-chat__header")!.classList.contains("m-search-form-visible")).toBe(false);
    expect([input(d).value, d.querySelector(".b-chat__search__results-nav"), d.querySelector(".b-chat__message__text-highlighted")]).toEqual(["", null, null]);
  });

  it("Enter searches at once (any length); no hit counts 0/0; a Relay error says so in place", async () => {
    const { d, ctx } = setup(async () => []);
    input(d).value = "x";
    input(d).form!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    await flush();
    expect(ctx.search).toHaveBeenCalledWith("x");
    expect(d.querySelector(".b-chat__search__results-count")!.textContent!.trim()).toBe("0/0");
    const bad = setup(async () => {
      throw new Error("502 Bad Gateway");
    });
    input(bad.d).value = "syn";
    input(bad.d).form!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    await flush();
    await flush();
    expect(bad.d.getElementById("oi-note")!.textContent).toBe("Could not search this chat: 502 Bad Gateway");
  });

  it("a new query supersedes the one still running: only its hits count", async () => {
    let first: (v: string[]) => void = () => {};
    const { d, ctx } = setup((q) => (q === "old" ? new Promise<string[]>((r) => (first = r)) : Promise.resolve([ids[1]])));
    const submit = (v: string) => {
      input(d).value = v;
      input(d).form!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    };
    submit("old");
    submit("syn");
    await flush();
    await flush();
    expect(ctx.search.mock.calls.map((c) => c[0])).toEqual(["old", "syn"]);
    first(ids);
    await flush();
    await flush();
    expect(d.querySelector(".b-chat__search__results-count")!.textContent!.trim()).toBe("1/1");
    expect(ctx.reveal.mock.calls.map((c) => (c as unknown[])[0])).toEqual([ids[1]]);
  });

  it("a hit too far back to draw says so; the teardown (another chat, a page change) closes the bar and clears it", async () => {
    const { d, ctx, find } = setup(async () => ids);
    ctx.reveal.mockResolvedValue(false);
    d.querySelector<HTMLButtonElement>("button[at-attr='search_btn']")!.click();
    input(d).value = "syn";
    input(d).form!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    await flush();
    await flush();
    expect(d.getElementById("oi-note")!.textContent).toBe(TOO_FAR);
    find.dispose();
    expect(input(d).closest(".b-chat__header")!.classList.contains("m-search-form-visible")).toBe(false);
    expect([input(d).value, d.querySelector(".b-chat__search__results-nav")]).toEqual(["", null]);
    // Its listeners are gone: a click opens nothing.
    d.querySelector<HTMLButtonElement>("button[at-attr='search_btn']")!.click();
    expect(input(d).closest(".b-chat__header")!.classList.contains("m-search-form-visible")).toBe(false);
  });

  it("OF's answer is a flat id list (the captured one), read as strings", () => {
    const raw = fixture<number[]>("messages-search");
    expect(searchIds(raw)).toEqual(raw.map(String));
    expect(searchIds({ list: [1, 2] })).toEqual(["1", "2"]);
    expect(searchIds(null)).toEqual([]);
  });
});

describe("useThreadFind: a gallery tile's ?firstId= jump", () => {
  const thread = rowsOf<OFMessage>(fixture("messages-thread"))!;
  const html = readFileSync(resolve(__dirname, "../public/of-mirror/pages/messages/chat.html"), "utf8");
  const mount = () => {
    const frame = document.createElement("iframe");
    document.body.appendChild(frame);
    return frame;
  };
  /** The frame loads the chat page with `messages` drawn (as useOfData would), then fires its load. */
  const load = (frame: HTMLIFrameElement, messages: OFMessage[]) => {
    const d = frame.contentDocument!;
    d.documentElement.innerHTML = html;
    applyData(d, "messages/chat", { chat: "2006", thread: { fan: FAN, messages } });
    frame.dispatchEvent(new Event("load"));
    return d;
  };
  const flush = () => new Promise((r) => setTimeout(r, 0));

  it("runs when the frame loads after the hook (no redraw needed), and again on the next load of the same tile", async () => {
    const frame = mount();
    const loadOlder = vi.fn(async () => ({ added: 0, hasMore: false }));
    const ref = { current: frame };
    renderHook(() => useThreadFind(ref, "/of-mirror/pages/messages/chat.html", true, "acc", "2006", "999", { hasOlder: true, loadOlder }, 1));
    const d1 = load(frame, thread);
    await waitFor(() => expect(loadOlder).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(d1.getElementById("oi-note")?.textContent).toBe(TOO_FAR), { timeout: 5000 });
    // The same tile clicked again: a new page load jumps again.
    const d2 = load(frame, thread);
    expect(d2.getElementById("oi-note")).toBeNull();
    await waitFor(() => expect(loadOlder).toHaveBeenCalledTimes(2));
    frame.remove();
  }, 15000);

  it("a chat switch mid-jump stops paging (the new chat is never paged for the old firstId) and says nothing", async () => {
    const frame = mount();
    const ref = { current: frame };
    let release: () => void = () => {};
    // Each older page adds a row but never the wanted message; the second waits until released.
    const loadOlder = vi.fn(() => (loadOlder.mock.calls.length === 1 ? Promise.resolve({ added: 1, hasMore: true }) : new Promise<{ added: number; hasMore: boolean }>((r) => (release = () => r({ added: 1, hasMore: true })))));
    const { rerender } = renderHook(({ chat, firstId }) => useThreadFind(ref, "/of-mirror/pages/messages/chat.html", true, "acc", chat, firstId, { hasOlder: true, loadOlder }, 1), { initialProps: { chat: "2006", firstId: "999" as string | null } });
    const d = load(frame, thread);
    await waitFor(() => expect(loadOlder).toHaveBeenCalledTimes(2), { timeout: 8000 });
    rerender({ chat: "2007", firstId: null });
    release();
    await new Promise((r) => setTimeout(r, 3300));
    expect(loadOlder).toHaveBeenCalledTimes(2);
    expect(d.getElementById("oi-note")).toBeNull();
    frame.remove();
  }, 20000);

  it("a firstId already drawn: no older page, the message is centred in the thread", async () => {
    const frame = mount();
    const target = thread[Math.floor(thread.length / 2)];
    const loadOlder = vi.fn(async () => ({ added: 0, hasMore: false }));
    renderHook(() => useThreadFind({ current: frame }, "/of-mirror/pages/messages/chat.html", true, "acc", "2006", String(target.id), { hasOlder: true, loadOlder }, 1));
    const d = frame.contentDocument!;
    d.documentElement.innerHTML = html;
    applyData(d, "messages/chat", { chat: "2006", thread: { fan: FAN, messages: thread } });
    const box = d.querySelector<HTMLElement>(".b-chat__messages")!;
    const el = d.querySelector<HTMLElement>(`[data-oi-data] [data-oi-msg="${target.id}"]`)!;
    Object.defineProperty(box, "clientHeight", { value: 400, configurable: true });
    Object.defineProperty(el, "offsetHeight", { value: 40, configurable: true });
    box.getBoundingClientRect = () => ({ top: 100 }) as DOMRect;
    el.getBoundingClientRect = () => ({ top: 900 }) as DOMRect;
    frame.dispatchEvent(new Event("load"));
    // 900 - 100 + 0 - (400 - 40) / 2 = 620
    await waitFor(() => expect(box.scrollTop).toBe(620));
    expect(loadOlder).not.toHaveBeenCalled();
    frame.remove();
  });

  it("another chat (?chat= changes, the same frame): the Find bar, its query and count are gone", async () => {
    const frame = mount();
    const ref = { current: frame };
    const d = load(frame, thread);
    vi.spyOn(relay, "get").mockResolvedValue([String(thread[0].id)]);
    const paging = { hasOlder: false, loadOlder: vi.fn(async () => ({ added: 0, hasMore: false })) };
    const { rerender } = renderHook(({ chat }) => useThreadFind(ref, "/of-mirror/pages/messages/chat.html", true, "acc", chat, null, paging, 1), { initialProps: { chat: "2006" } });
    d.querySelector<HTMLButtonElement>("button[at-attr='search_btn']")!.click();
    const input = d.querySelector<HTMLInputElement>(".b-chat__header form.b-chat__search-form input[name='query']")!;
    input.value = "syn";
    input.form!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    await waitFor(() => expect(d.querySelector(".b-chat__search__results-count")?.textContent?.trim()).toBe("1/1"));
    rerender({ chat: "2007" });
    expect(input.closest(".b-chat__header")!.classList.contains("m-search-form-visible")).toBe(false);
    expect([input.value, d.querySelector(".b-chat__search__results-nav")]).toEqual(["", null]);
    expect(FIND_PAGES).toBe(12);
    frame.remove();
  });

  it("the pinned page's Find: OF's filter=pinned search, its hits only the pins drawn there (a Relay that drops the filter answers all)", async () => {
    const pins = rowsOf<OFMessage>(fixture("messages-pinned"))!;
    const frame = mount();
    const d = frame.contentDocument!;
    d.documentElement.innerHTML = readFileSync(resolve(__dirname, "../public/of-mirror/pages/messages/chat/pinned.html"), "utf8");
    applyData(d, "messages/chat/pinned", { chat: "2006", thread: { fan: FAN, messages: pins } });
    frame.dispatchEvent(new Event("load"));
    const get = vi.spyOn(relay, "get").mockResolvedValue(["999999", String(pins[0].id)]);
    const paging = { hasOlder: false, loadOlder: vi.fn(async () => ({ added: 0, hasMore: false })) };
    renderHook(() => useThreadFind({ current: frame }, "/of-mirror/pages/messages/chat/pinned.html", true, "acc", "2006", null, paging, 1, true));
    const btn = d.querySelector<HTMLButtonElement>("button[at-attr='search_btn']")!;
    expect(btn.hasAttribute("disabled")).toBe(false);
    btn.click();
    const input = d.querySelector<HTMLInputElement>(".b-chat__header form.b-chat__search-form input[name='query']")!;
    input.value = "syn";
    input.form!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    await waitFor(() => expect(d.querySelector(".b-chat__search__results-count")?.textContent?.trim()).toBe("1/1"));
    expect(get.mock.calls[0][0]).toBe("/api/of/v2/chats/2006/messages/search?query=syn&filter=pinned");
    expect(paging.loadOlder).not.toHaveBeenCalled();
    frame.remove();
  });
});
