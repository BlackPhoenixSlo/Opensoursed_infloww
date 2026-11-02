/**
 * Statistics › Engagement's phase-2 parts (ofMirrorStatsEngagement) called directly on the captured mirror pages
 * (app/public/of-mirror/pages/statistics/engagement/*.html) with OF's synthetic replies (app/lib/__fixtures__/of).
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterAll, afterEach, describe, expect, it, vi } from "vitest";
import { applyEngagement, applyEngagementPosts, applyMassMessages, messagesRekey, postsRekey, type EngagementCtx } from "./ofMirrorStatsEngagement";
import { PICK_DEFAULTS, applyStats, periodOf, startOf, type PagedBody, type Picks, type StatsData } from "./ofMirrorStats";
import type { MassMessage, PostsBy } from "./ofMirrorStatsSources";
import { chartSpecOf } from "./ofMirrorChart";
import { NOT_YET } from "./ofMirrorWrites";

// The host zone pinned before any import (a formatter built at module load would keep the old zone): Kathmandu,
// +05:45 all year, no DST, matching no zone named here, so `tz: null` (the browser's clock) expectations are literals
// that fail if the module ignored the host zone. Restored after the file.
vi.hoisted(() => vi.stubEnv("TZ", "Asia/Kathmandu"));
afterAll(() => vi.unstubAllEnvs());

const capture = (p: string) => readFileSync(resolve(__dirname, `../public/of-mirror/pages/${p}.html`), "utf8");
const load = (p: string) => {
  document.documentElement.innerHTML = capture(p);
  return document;
};
/** A page in a Document of its own (as each frame load is): per-Document bindings start unbound. */
const loadFresh = (p: string) => {
  const doc = document.implementation.createHTMLDocument("");
  doc.documentElement.innerHTML = capture(p);
  return doc;
};
const fixture = <T = unknown,>(name: string): T => JSON.parse(readFileSync(resolve(__dirname, `__fixtures__/of/statistics-${name}.json`), "utf8")) as T;
const visible = (el: Element) => !el.closest("[style*='display:none'], [style*='display: none']");
const squash = (s: string | null | undefined) => (s ?? "").replace(/\s+/g, " ").trim();
const texts = (root: ParentNode, sel: string) => [...root.querySelectorAll(sel)].filter(visible).map((e) => squash(e.textContent));
const TZ = "Europe/Ljubljana";
const NOW = new Date("2026-10-17T10:00:00Z");
const START = startOf(fixture("start-date"), TZ);
const D30 = periodOf("d30", NOW, TZ, START);
const picks = (p: Partial<Picks> = {}): Picks => ({ ...PICK_DEFAULTS, ...p });
/** A list reply in any of OF's shapes (`list`, `items`, `users`). */
type Listed = { list?: unknown[]; items?: unknown[]; users?: unknown[]; hasMore?: boolean };
const paged = (b: Listed, more: (() => void) | null = null): PagedBody => ({ list: b.list ?? b.items ?? b.users ?? [], hasMore: !!b.hasMore, loading: false, more });
const ctx = (x: Partial<EngagementCtx> = {}): EngagementCtx => ({ picks: picks(), v2: true, by: "purchases", pick: () => {}, ...x });
const spec = (doc: Document, sel: string) => {
  const c = doc.querySelector<HTMLCanvasElement>(sel);
  return c ? chartSpecOf(c) : undefined;
};

/**
 * jsdom has no IntersectionObserver (and its document.defaultView is globalThis, measured): a stand-in recording what
 * moreAt observes; `fire()` scrolls it into view.
 */
function stubIO() {
  const seen: { el: Element; fire: (isIntersecting?: boolean) => void; disconnected: boolean }[] = [];
  class IO {
    cb: (entries: { isIntersecting: boolean }[]) => void;
    rec?: (typeof seen)[number];
    constructor(cb: (entries: { isIntersecting: boolean }[]) => void) {
      this.cb = cb;
    }
    observe(el: Element) {
      this.rec = { el, fire: (isIntersecting = true) => this.cb([{ isIntersecting }]), disconnected: false };
      seen.push(this.rec);
    }
    disconnect() {
      if (this.rec) this.rec.disconnected = true;
    }
  }
  vi.stubGlobal("IntersectionObserver", IO);
  return seen;
}
afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("messagesRekey: Engagement › Messages' summary from OF's chart for the tab", () => {
  const el = () => document.createElement("span");
  const DIRECT = fixture("messages-chart-direct");
  const ZERO = fixture("messages-chart-zero");
  const cases: [name: string, chart: unknown, t: string, key: string, want: string][] = [
    ["direct count", DIRECT, "direct", "messages:massMessages.count.total", "messagesChart:direct_messages.total"],
    ["direct earnings", DIRECT, "direct", "messages:massMessages.earnings.total", "messagesChart:direct_messages_purchases.total"],
    // OF's single summary change is the purchases' (the count's delta key reads it). The rekey ignores the element: the
    // sidebar's Messages change reads it too (see the BUG (pinned) sidebar test under applyEngagement).
    ["direct count delta -> purchases delta", DIRECT, "direct", "messages:massMessages.count.delta", "messagesChart:direct_messages_purchases.delta"],
    ["earnings delta not rekeyed", DIRECT, "direct", "messages:massMessages.earnings.delta", "messages:massMessages.earnings.delta"],
    ["another key", DIRECT, "direct", "posts:posts.count.total", "posts:posts.count.total"],
    ["tab missing from chart", DIRECT, "group", "messages:massMessages.count.total", "messages:massMessages.count.total"],
    ["group, all zero", ZERO, "group", "messages:massMessages.count.total", "messagesChart:group_messages.total"],
    ["group earnings, all zero", ZERO, "group", "messages:massMessages.earnings.total", "messagesChart:group_messages_purchases.total"],
    ["no chart", undefined, "group", "messages:massMessages.count.total", "messages:massMessages.count.total"],
    ["today's Relay ([])", [], "group", "messages:massMessages.count.total", "messages:massMessages.count.total"],
    ["series not an object", { group_messages: 5 }, "group", "messages:massMessages.count.total", "messages:massMessages.count.total"],
    ["series an array", { group_messages: [] }, "group", "messages:massMessages.count.total", "messages:massMessages.count.total"],
    // Only the series' presence is checked, not its field.
    ["series without total", { group_messages: {} }, "group", "messages:massMessages.count.total", "messagesChart:group_messages.total"],
  ];
  it.each(cases)("%s", (_n, chart, t, key, want) => {
    expect(messagesRekey(chart, t)(el(), key)).toBe(want);
  });
});

describe("postsRekey: Engagement › Posts' summary for a chip", () => {
  const el = () => document.createElement("span");
  const VIEWS = fixture("posts-chart-views");
  const PURCHASES = fixture("posts-chart");
  const cases: [name: string, chart: unknown, by: PostsBy, key: string, want: string][] = [
    ["views total", VIEWS, "views", "postsChart:purchases.total", "postsChart:views.total"],
    ["views delta", VIEWS, "views", "postsChart:purchases.delta", "postsChart:views.delta"],
    ["nested suffix kept", VIEWS, "views", "postsChart:purchases.a.b", "postsChart:views.a.b"],
    ["the posts count stays", VIEWS, "views", "postsChart:posts.total", "postsChart:posts.total"],
    ["overview key stays", VIEWS, "views", "posts:posts.views.total", "posts:posts.views.total"],
    ["chip missing from chart", VIEWS, "likes", "postsChart:purchases.total", "postsChart:purchases.total"],
    ["purchases: itself", PURCHASES, "purchases", "postsChart:purchases.total", "postsChart:purchases.total"],
    ["no chart", null, "views", "postsChart:purchases.total", "postsChart:purchases.total"],
    ["chart an array", [], "views", "postsChart:purchases.total", "postsChart:purchases.total"],
    ["series an array", { views: [] }, "views", "postsChart:purchases.total", "postsChart:purchases.total"],
  ];
  it.each(cases)("%s", (_n, chart, by, key, want) => {
    expect(postsRekey(chart, by)(el(), key)).toBe(want);
  });
});

describe("applyMassMessages: one row per mass message", () => {
  const GROUP = fixture<{ items: MassMessage[]; hasMore: boolean }>("messages-group");
  const dataRows = (doc: Document) => [...doc.querySelectorAll<HTMLElement>(".b-statements-table tbody > tr[data-oi-data]")];
  const cells = (tr: Element) => [...tr.querySelectorAll(":scope > td")].slice(0, 5).map((c) => squash(c.textContent));

  it("OF's free canceled and unsendable messages (the Relay's fixture) in Ljubljana time", () => {
    const doc = load("statistics/engagement/messages");
    applyMassMessages(doc, GROUP.items, TZ, paged(GROUP));
    const rows = dataRows(doc);
    expect(rows).toHaveLength(6);
    expect(rows.every(visible)).toBe(true);
    // The template stays hidden; the empty row goes.
    expect(visible(doc.querySelector(".b-statements-table tbody > tr[data-oi-template]")!)).toBe(false);
    expect(texts(doc, ".b-statements-table .empty-message")).toEqual([]);
    // 01:36 UTC = 03:36 in Ljubljana (+02:00); a free message: dashes for price and purchases.
    expect(cells(rows[0])).toEqual(["Oct 14, 2026, 03:36 am", "1", "0", "—", "—"]);
    expect(cells(rows[5])).toEqual(["Sep 29, 2026, 03:58 pm", "2", "1", "—", "—"]);
    expect(texts(rows[0], ".b-top-statistic__text p")).toEqual(["Synthetic mass message 1"]);
    // No media: the thumbs go, OF's placeholder box with no picture.
    const img = rows[0].querySelector(".b-top-statistic__img")!;
    expect([img.classList.contains("b-top-statistic__img"), img.classList.contains("b-top-statistic__img--placeholder")]).toEqual([true, true]);
    expect(img.children).toHaveLength(0);
    expect(rows[0].querySelector(".b-content-inside-thumbs")).toBeNull();
    // Canceled: tinted, "New message" (disabled), OF's undo mark instead of the "i".
    expect(rows[0].classList.contains("m-colored-bg")).toBe(true);
    const btn = rows[0].querySelector<HTMLButtonElement>(".b-top-statistic__btns button")!;
    expect([squash(btn.textContent), btn.disabled, btn.title]).toEqual(["New message", true, NOT_YET]);
    expect(rows[0].querySelector(".g-icon-info")).toBeNull();
    expect(rows[0].querySelector(".b-top-statistic__btns [aria-label='Canceled'] use")!.getAttribute("href")).toBe("#icon-undo");
    // Still unsendable: "Unsend" and its "i", no tint.
    expect(rows[3].classList.contains("m-colored-bg")).toBe(false);
    expect(texts(rows[3], ".b-top-statistic__btns button")).toEqual(["Unsend"]);
    expect(rows[3].querySelector(".b-top-statistic__btns .g-icon-info")).not.toBeNull();
    expect(rows[3].querySelector("[aria-label='Canceled']")).toBeNull();
  });

  it("a paid message with media: its price, purchases and media count; neither canceled nor unsendable: no buttons; no date: a dash", () => {
    const doc = load("statistics/engagement/messages");
    const items: MassMessage[] = [
      { date: "2026-10-01T12:00:00+00:00", text: "<p>Paid <b>one</b></p>", isFree: false, mediaCount: 2, sentCount: 12345, viewedCount: 1234, price: 4.99, purchasedCount: 3, canUnsend: false, isCanceled: false },
      { date: null, text: null, isFree: false, mediaCount: 0, sentCount: undefined, viewedCount: undefined, price: null, purchasedCount: null, canUnsend: false, isCanceled: false },
      { date: "2026-10-01T12:00:00+00:00", isFree: false, price: 0, purchasedCount: 0, sentCount: 1, viewedCount: 0, canUnsend: true },
    ];
    applyMassMessages(doc, items, TZ);
    const rows = dataRows(doc);
    expect(cells(rows[0])).toEqual(["Oct 1, 2026, 02:00 pm", "12,345", "1,234", "$4.99", "3"]);
    expect(texts(rows[0], ".b-top-statistic__text p")).toEqual(["Paid one"]);
    expect(texts(rows[0], ".b-content-inside-thumbs__count")).toEqual(["2"]);
    expect(rows[0].querySelector(".b-top-statistic__img--placeholder")).toBeNull();
    expect(rows[0].querySelector(".b-top-statistic__btns")).toBeNull();
    // Nothing known: dashes; a paid price unknown: a dash.
    expect(cells(rows[1])).toEqual(["—", "—", "—", "—", "—"]);
    // A paid message at $0 with no buyer: OF's money and count, not dashes.
    expect(cells(rows[2]).slice(3)).toEqual(["$0.00", "0"]);
  });

  it("the time zone: a named one shifts the wall clock; null reads the browser's (host-local, pinned Kathmandu) clock", () => {
    expect(new Date(GROUP.items[0].date!).getTimezoneOffset()).toBe(-345); // the pin took effect
    const at = (tz: string | null) => {
      const doc = load("statistics/engagement/messages");
      applyMassMessages(doc, [GROUP.items[0]], tz);
      return squash(dataRows(doc)[0].querySelector("td strong")!.textContent);
    };
    expect(at(TZ)).toBe("Oct 14, 2026, 03:36 am");
    expect(at("America/New_York")).toBe("Oct 13, 2026, 09:36 pm");
    expect(at("UTC")).toBe("Oct 14, 2026, 01:36 am");
    expect(at(null)).toBe("Oct 14, 2026, 07:21 am"); // 01:36 UTC + 05:45
  });

  it("paged with more: the last row observed; read once it scrolls into view (not before), then the observer disconnects", () => {
    const seen = stubIO();
    const doc = load("statistics/engagement/messages");
    const more = vi.fn();
    applyMassMessages(doc, GROUP.items, TZ, paged({ ...GROUP, hasMore: true }, more));
    expect(seen.map((s) => s.el)).toEqual([dataRows(doc).at(-1)]);
    seen[0].fire(false);
    expect(more).not.toHaveBeenCalled();
    seen[0].fire(true);
    expect(more).toHaveBeenCalledTimes(1);
    expect(seen[0].disconnected).toBe(true);
  });

  it("no more pages, or unpaged: nothing observed", () => {
    const seen = stubIO();
    applyMassMessages(load("statistics/engagement/messages"), GROUP.items, TZ, paged(GROUP));
    applyMassMessages(load("statistics/engagement/messages"), GROUP.items, TZ);
    expect(seen).toEqual([]);
  });

  it("no row yet with more to read: OF's empty row says Loading…, nothing observed", () => {
    const seen = stubIO();
    const doc = load("statistics/engagement/messages");
    applyMassMessages(doc, [], TZ, paged({ items: [], hasMore: true }, vi.fn()));
    expect(texts(doc, ".b-statements-table .empty-message")).toEqual(["Loading…"]);
    expect(seen).toEqual([]); // no row to observe
  });

  it("none and no more: the generator's text stays, no row", () => {
    const doc = load("statistics/engagement/messages");
    applyMassMessages(doc, [], TZ, paged({ items: [], hasMore: false }));
    expect(texts(doc, ".b-statements-table .empty-message")).toEqual([NOT_YET]);
    expect(dataRows(doc)).toHaveLength(0);
  });
});

describe("applyEngagementPosts: the period's top posts in OF's table", () => {
  const TOP = paged(fixture<Listed>("posts-top"));
  const post0 = TOP.list[0] as Record<string, unknown>;
  const THUMB = "https://cdn2.onlyfans.com/files/2/26/26c6b67a522eb095933d646020b85e7a/0010.jpg";
  const img = (u: string) => `/img?u=${encodeURIComponent(u)}`;
  const data = (x: Partial<StatsData> = {}): StatsData => ({ postsTop: TOP, postsChart: fixture("posts-chart"), ...x });
  const row = (doc: Document) => doc.querySelector<HTMLElement>("[data-oi-table='posts'] tbody tr[data-oi-data]")!;
  const cells = (tr: Element) => [...tr.querySelectorAll(":scope > td")].slice(0, 5).map((c) => squash(c.textContent));
  const current = (doc: Document) => [...doc.querySelectorAll("[data-oi-pick^='by:']")].filter((b) => b.classList.contains("m-current")).map((b) => b.getAttribute("data-oi-pick"));

  it("Purchases: the row, its picture through the mapper, media icons, Full stat disabled, OF's summary and chart shown", () => {
    const doc = load("statistics/engagement/posts");
    applyEngagementPosts(doc, data(), D30, "purchases", img);
    expect(current(doc)).toEqual(["by:purchases"]);
    expect(texts(doc, "[data-oi-posts-col]")).toEqual(["Tips"]);
    const table = doc.querySelector<HTMLElement>("[data-oi-table='posts']")!;
    expect(visible(table)).toBe(true);
    expect(texts(doc, ".b-statistics-page-content__wrapper > .empty-message")).toEqual([]);
    expect(doc.querySelector(".b-statistics-page-content__wrapper")!.classList.contains("m-empty-wrapper")).toBe(false);
    const tr = row(doc);
    // 23:52 UTC Oct 16 = 01:52 Oct 17 in Ljubljana; tips "$0" as money; no price, no purchases: dashes.
    expect(cells(tr)).toEqual(["Oct 17, 2026, 01:52 am", "6", "$0.00", "—", "—"]);
    expect(tr.querySelectorAll(":scope > td")[4].querySelector("span")!.className).toBe("g-semibold");
    expect(tr.querySelector<HTMLImageElement>(".b-top-statistic__img img")!.getAttribute("src")).toBe(img(THUMB));
    expect(tr.querySelector(".b-top-statistic__img")!.classList.contains("b-top-statistic__img--placeholder")).toBe(false);
    expect(texts(tr, ".b-top-statistic__text p")).toEqual(["Synthetic post text 1"]);
    expect(texts(tr, ".b-content-inside-thumbs__count")).toEqual(["2"]);
    const full = tr.querySelector<HTMLButtonElement>(".b-top-statistic__btns button")!;
    expect([squash(full.textContent), full.disabled, full.title]).toEqual(["Full stat", true, NOT_YET]);
    expect(tr.querySelector("[data-oi-users]")).toBeNull();
    expect(visible(doc.querySelector("[data-oi-posts-summary]")!)).toBe(true);
    expect(visible(doc.querySelector("[data-oi-posts-chart]")!)).toBe(true);
    expect(texts(doc, "[data-oi-posts-word]")).toEqual(["post"]);
  });

  it("no image mapper: the placeholder; no chart: no summary and the plural", () => {
    const doc = load("statistics/engagement/posts");
    applyEngagementPosts(doc, data({ postsChart: undefined }), D30, "purchases", undefined);
    const pic = row(doc).querySelector(".b-top-statistic__img")!;
    expect(pic.classList.contains("b-top-statistic__img--placeholder")).toBe(true);
    expect(pic.querySelector("img")).toBeNull();
    expect(doc.querySelector<HTMLElement>("[data-oi-posts-summary]")!.style.display).toBe("none");
    expect(doc.querySelector<HTMLElement>("[data-oi-posts-chart]")!.style.display).toBe("none");
    expect(doc.querySelector("[data-oi-posts-word]")!.textContent).toBe("posts");
  });

  const metricCases: [by: PostsBy, col: string, metric: string, bold: string][] = [
    ["tips", "Tips", "$5.00", ":scope > td:nth-child(3) > span"],
    ["views", "Likes", "4", ":scope > td:nth-child(2)"],
    ["likes", "Likes", "4", ":scope > td:nth-child(3) > span"],
    ["comments", "Comments", "3", ":scope > td:nth-child(3) > span"],
  ];
  it.each(metricCases)("%s: column %s, metric %s, the picked metric alone bold; no summary (Purchases only)", (by, col, metric, boldSel) => {
    const post = { ...post0, tipsAmount: "$5", stats: { lookCount: 1234, likeCount: 4, commentCount: 3, purchasedSumm: null } };
    const doc = load("statistics/engagement/posts");
    applyEngagementPosts(doc, data({ postsTop: paged({ items: [post] }) }), D30, by, img);
    expect(current(doc)).toEqual([`by:${by}`]);
    expect(texts(doc, "[data-oi-posts-col]")).toEqual([col]);
    const tr = row(doc);
    expect(cells(tr)).toEqual(["Oct 17, 2026, 01:52 am", "1,234", metric, "—", "—"]);
    // Across the five figure columns exactly one element is bold: the picked metric's.
    const bold = [...tr.querySelectorAll(":scope > td")].slice(0, 5).flatMap((td) => [td, ...td.querySelectorAll("*")]).filter((e) => e.classList.contains("g-semibold"));
    expect(bold).toHaveLength(1);
    expect(bold[0]).toBe(tr.querySelector(boldSel));
    expect(doc.querySelector<HTMLElement>("[data-oi-posts-summary]")!.style.display).toBe("none");
  });

  it("the phase-1 Relay (v3): tips and purchases open their lists, Full stat wired; zero amounts stay plain", () => {
    const post = { ...post0, tipsAmount: "$5", price: 9.99, stats: { ...(post0.stats as object), purchasedSumm: 10 } };
    const doc = load("statistics/engagement/posts");
    applyEngagementPosts(doc, data({ postsTop: paged({ items: [post, { ...post0, id: 7002 }] }) }), D30, "purchases", img, true);
    const [linked, zero] = [...doc.querySelectorAll("[data-oi-table='posts'] tbody tr[data-oi-data]")];
    expect(cells(linked).slice(2)).toEqual(["$5.00", "$9.99", "$10.00"]);
    expect([...linked.querySelectorAll("[data-oi-users]")].map((l) => [squash(l.textContent), l.getAttribute("data-oi-users")])).toEqual([
      ["$5.00", "post-tips:7001:0"],
      ["$10.00", "post-buyers:7001:0"],
    ]);
    const full = linked.querySelector<HTMLButtonElement>(".b-top-statistic__btns button")!;
    expect([full.disabled, full.hasAttribute("data-oi-wired")]).toEqual([false, true]);
    expect(zero.querySelector("[data-oi-users]")).toBeNull();
  });

  it("rawText missing: the text; no post: nothing drawn, the tab and column still set", () => {
    const doc = load("statistics/engagement/posts");
    applyEngagementPosts(doc, data({ postsTop: paged({ items: [{ ...post0, rawText: null, text: "<p>From text</p>" }] }) }), D30, "purchases", img);
    expect(texts(row(doc), ".b-top-statistic__text p")).toEqual(["From text"]);
    const empty = load("statistics/engagement/posts");
    applyEngagementPosts(empty, data({ postsTop: paged({ items: [], hasMore: false }) }), D30, "comments", img);
    expect(current(empty)).toEqual(["by:comments"]);
    expect(texts(empty, "[data-oi-posts-col]")).toEqual([]); // the table stays hidden…
    expect(squash(empty.querySelector("[data-oi-posts-col]")!.textContent)).toBe("Comments"); // …its header set
    expect(empty.querySelector<HTMLElement>("[data-oi-table='posts']")!.style.display).toBe("none");
    expect(empty.querySelectorAll("[data-oi-table='posts'] tbody tr")).toHaveLength(0);
  });
});

describe("applyEngagement: the phase-2 parts per Engagement page", () => {
  const msgRows = (doc: Document, body: PagedBody) => applyMassMessages(doc, body.list as MassMessage[], TZ, body);

  it("Messages (v2, Direct): tabs enabled with Direct current, search on, a paid row's purchases open its buyers, OF's chart pair", () => {
    const doc = load("statistics/engagement/messages");
    const body = paged(fixture<Listed>("messages-direct"));
    msgRows(doc, body);
    applyEngagement(doc, "engagement/messages", { massMessages: body, messagesChart: fixture("messages-chart-direct") }, D30, ctx({ picks: picks({ msg: "direct" }) }));
    expect([...doc.querySelectorAll<HTMLButtonElement>("[data-oi-pick^='msg:']")].map((b) => [squash(b.textContent), b.disabled, b.classList.contains("m-current")])).toEqual([
      ["Mass messages", false, false],
      ["Direct messages", false, true],
    ]);
    const input = doc.querySelector<HTMLInputElement>("[data-oi-search] input[type='search']")!;
    expect([input.disabled, input.hasAttribute("title")]).toEqual([false, false]);
    const links = [...doc.querySelectorAll("[data-oi-users]")];
    expect(links.map((l) => [squash(l.textContent), l.getAttribute("data-oi-users"), l.className])).toEqual([["2", "buyers:55001:0", "g-page__link g-blue"]]);
    // OF's count span hidden behind the link.
    expect((links[0].previousElementSibling as HTMLElement).style.display).toBe("none");
    expect(spec(doc, ".b-statistics-page-content__wrapper > .b-chart canvas.b-chart__double-line__main")!.series.title).toBe("Purchases");
    expect(spec(doc, ".b-statistics-page-content__wrapper > .b-chart canvas.b-chart__double-line__aside")!.series.title).toBe("Messages");
  });

  it("Messages without v2: tabs and search stay disabled, no buyers link", () => {
    const doc = load("statistics/engagement/messages");
    const body = paged(fixture<Listed>("messages-direct"));
    msgRows(doc, body);
    applyEngagement(doc, "engagement/messages", { massMessages: body }, D30, ctx({ v2: false }));
    expect([...doc.querySelectorAll<HTMLButtonElement>("[data-oi-pick^='msg:']")].every((b) => b.disabled && b.title === NOT_YET)).toBe(true);
    expect(doc.querySelector<HTMLInputElement>("[data-oi-search] input")!.disabled).toBe(true);
    expect(doc.querySelector("[data-oi-users]")).toBeNull();
  });

  describe("Messages' search box (OF's SearchOF)", () => {
    /** The search box binds once per Document (a frame load brings a new one), so not jsdom's shared `document`. */
    const searchBox = (pick: EngagementCtx["pick"]) => {
      vi.useFakeTimers();
      const doc = loadFresh("statistics/engagement/messages");
      applyEngagement(doc, "engagement/messages", {}, D30, ctx({ pick }));
      const form = doc.querySelector<HTMLFormElement>("[data-oi-search]")!;
      const input = form.querySelector<HTMLInputElement>("input[type='search']")!;
      const clear = form.querySelector<HTMLElement>(".b-search-form__clear-input")!;
      const type = (v: string) => {
        input.value = v;
        input.dispatchEvent(new Event("input"));
      };
      const submit = (v: string) => {
        input.value = v;
        form.dispatchEvent(new Event("submit", { cancelable: true }));
      };
      return { doc, input, clear, type, submit };
    };

    it("typing: 3+ characters picked half a second after the last key; fewer never; blank picks none", () => {
      const pick = vi.fn();
      const { clear, type } = searchBox(pick);
      expect(clear.style.display).toBe("none"); // no search picked
      type("ab");
      vi.advanceTimersByTime(600);
      expect(pick).not.toHaveBeenCalled();
      type("abc");
      vi.advanceTimersByTime(499);
      expect(pick).not.toHaveBeenCalled();
      vi.advanceTimersByTime(1);
      expect(pick.mock.calls).toEqual([["q", "abc"]]);
      pick.mockClear();
      type("  ");
      vi.advanceTimersByTime(500);
      expect(pick.mock.calls).toEqual([["q", ""]]);
    });

    it("submit: picked at once", () => {
      const pick = vi.fn();
      const { submit } = searchBox(pick);
      submit("synth");
      expect(pick.mock.calls).toEqual([["q", "synth"]]);
    });

    it("a second apply rebinds the handler's ctx without a second listener; the clear button empties and picks none", () => {
      const pick = vi.fn();
      const { doc, input, clear, submit } = searchBox(pick);
      const pick2 = vi.fn();
      applyEngagement(doc, "engagement/messages", {}, D30, ctx({ pick: pick2, picks: picks({ q: "synth" }) }));
      expect(clear.style.display).toBe("");
      input.value = "synth";
      clear.click();
      expect(input.value).toBe("");
      expect(pick2.mock.calls).toEqual([["q", ""]]);
      submit("again");
      expect(pick).not.toHaveBeenCalled();
      expect(pick2.mock.calls).toEqual([["q", ""], ["q", "again"]]);
    });
  });

  describe("Posts' chip summary and chart (v2)", () => {
    const chart = (series: string, total: number) => {
      const posts = fixture<{ posts: { chart: unknown[] } }>("posts-chart-views").posts;
      return { posts: { ...posts, total: 1 }, [series]: { chart: posts.chart, total, delta: 0 } };
    };
    const top = paged(fixture<Listed>("posts-top"));
    const summary = (doc: Document) => doc.querySelector<HTMLElement>("[data-oi-posts-summary]")!;
    const value = (doc: Document) => doc.querySelector("[data-oi-posts-summary] [data-oi-stat='postsChart:purchases.total']")!;

    it("Likes: the chip's own summary (\"<n> likes\") and chart over Posts", () => {
      const doc = load("statistics/engagement/posts");
      applyEngagement(doc, "engagement/posts", { postsTop: top, postsChart: chart("likes", 1234) }, D30, ctx({ by: "likes" }));
      expect(visible(summary(doc))).toBe(true);
      expect(squash(value(doc).textContent)).toBe("1,234 likes");
      expect(value(doc).classList.contains("m-zero-value")).toBe(false);
      expect(spec(doc, "[data-oi-posts-chart] canvas.b-chart__double-line__main")!.series.title).toBe("Likes");
      expect(spec(doc, "[data-oi-posts-chart] canvas.b-chart__double-line__aside")!.series.title).toBe("Posts");
    });

    it("Tips (money): the summary shown, its figure left as it was; the chart titled Tips", () => {
      const doc = load("statistics/engagement/posts");
      const before = squash(value(doc).textContent);
      applyEngagement(doc, "engagement/posts", { postsTop: top, postsChart: chart("tips", 5) }, D30, ctx({ by: "tips" }));
      expect(visible(summary(doc))).toBe(true);
      expect(squash(value(doc).textContent)).toBe(before);
      expect(spec(doc, "[data-oi-posts-chart] canvas.b-chart__double-line__main")!.series.title).toBe("Tips");
    });

    it.each<[string, Partial<EngagementCtx>]>([
      ["Purchases", { by: "purchases" }],
      ["Likes without v2", { by: "likes", v2: false }],
    ])("%s: no chip summary", (_name, x) => {
      const doc = load("statistics/engagement/posts");
      applyEngagement(doc, "engagement/posts", { postsTop: top, postsChart: { ...chart("likes", 3), purchases: { chart: [], total: 0 } } }, D30, ctx(x));
      expect(summary(doc).style.display).toBe("none");
    });

    it("no post: no chip summary", () => {
      const doc = load("statistics/engagement/posts");
      applyEngagement(doc, "engagement/posts", { postsTop: paged({ items: [] }), postsChart: chart("likes", 3) }, D30, ctx({ by: "likes" }));
      expect(summary(doc).style.display).toBe("none");
    });
  });

  it("Posts: more to read observes the table's last row", () => {
    const seen = stubIO();
    const doc = load("statistics/engagement/posts");
    const more = vi.fn();
    const top = paged({ ...fixture<Listed>("posts-top"), hasMore: true }, more);
    applyEngagementPosts(doc, { postsTop: top }, D30, "purchases", undefined);
    applyEngagement(doc, "engagement/posts", { postsTop: top }, D30, ctx());
    expect(seen.map((s) => s.el)).toEqual([doc.querySelector("[data-oi-table='posts'] tbody")!.lastElementChild]);
    seen[0].fire();
    expect(more).toHaveBeenCalledTimes(1);
  });

  it("Streaming (v2, Tips): tabs, OF's cards, summary and chart pair", () => {
    const doc = load("statistics/engagement/streaming");
    applyEngagement(doc, "engagement/streaming", { streamsTop: paged(fixture<Listed>("streams-top")), streamsChart: fixture("streams-chart-tips") }, D30, ctx({ picks: picks({ streams: "tips" }) }));
    const tabs = [...doc.querySelectorAll<HTMLButtonElement>("[data-oi-pick^='streams:']")];
    expect(tabs.filter((b) => b.classList.contains("m-current")).map((b) => squash(b.textContent))).toEqual(["Tips"]);
    expect(tabs.every((b) => !b.disabled)).toBe(true);
    expect(doc.querySelectorAll("[data-oi-list='streams'] > .b-top-statistic")).toHaveLength(2);
    expect(visible(doc.querySelector("[data-oi-list='streams']")!)).toBe(true);
    expect(texts(doc, "[data-oi-summary='streams'] [data-oi-summary-a], [data-oi-summary='streams'] [data-oi-summary-b]")).toEqual(["0h:40m", "$5.00"]);
    expect(spec(doc, "[data-oi-chart='streams'] canvas.b-chart__double-line__main")!.series.title).toBe("Tips");
    expect(spec(doc, "[data-oi-chart='streams'] canvas.b-chart__double-line__aside")!.series).toMatchObject({ title: "Duration", kind: "duration" });
  });

  it("Streaming: none and no more: OF's empty text", () => {
    const none = load("statistics/engagement/streaming");
    applyEngagement(none, "engagement/streaming", { streamsTop: paged(fixture<Listed>("list-empty")) }, D30, ctx());
    expect(texts(none, ".b-statistics-page-content__wrapper > .empty-message")).toEqual(["No Streaming activity during selected period"]);
  });

  it("Streaming: none with more to come: no empty claim, the not-yet text", () => {
    const pending = load("statistics/engagement/streaming");
    applyEngagement(pending, "engagement/streaming", { streamsTop: paged({ items: [], hasMore: true }) }, D30, ctx());
    expect(texts(pending, ".b-statistics-page-content__wrapper > .empty-message")).toEqual([NOT_YET]);
  });

  it("Stories (v2, Viewers): OF's card, \"1 story\" and the viewers", () => {
    const doc = load("statistics/engagement/stories");
    applyEngagement(doc, "engagement/stories", { storiesTop: paged(fixture<Listed>("stories-top")), storiesChart: fixture("stories-chart-views") }, D30, ctx({ picks: picks({ stories: "views" }) }));
    expect(doc.querySelectorAll("[data-oi-list='stories'] > .b-top-statistic")).toHaveLength(1);
    expect(texts(doc, "[data-oi-summary='stories']")).toEqual(["1 story 4 viewers"]);
    expect(spec(doc, "[data-oi-chart='stories'] canvas.b-chart__double-line__aside")!.series.title).toBe("Stories");
  });

  it("Stories without v2: tabs stay disabled, no cards", () => {
    const off = load("statistics/engagement/stories");
    applyEngagement(off, "engagement/stories", {}, D30, ctx({ v2: false }));
    expect([...off.querySelectorAll<HTMLButtonElement>("[data-oi-pick^='stories:']")].every((b) => b.disabled)).toBe(true);
    expect(texts(off, "[data-oi-list='stories']")).toEqual([]);
  });

  it("another page: none of Messages' parts drawn", () => {
    const doc = load("statistics/engagement/messages");
    const body = paged(fixture<Listed>("messages-direct"));
    msgRows(doc, body);
    applyEngagement(doc, "fans/subscriptions", { massMessages: body, messagesChart: fixture("messages-chart-direct") }, D30, ctx({ picks: picks({ msg: "direct" }) }));
    const main = ".b-statistics-page-content__wrapper > .b-chart canvas.b-chart__double-line__main";
    expect(doc.querySelector(main)).not.toBeNull(); // the canvas is there, only undrawn
    expect(spec(doc, main)).toBeUndefined();
    expect(doc.querySelector("[data-oi-users]")).toBeNull();
    expect([...doc.querySelectorAll<HTMLButtonElement>("[data-oi-pick^='msg:']")].every((b) => b.disabled && b.title === NOT_YET)).toBe(true);
    expect(doc.querySelector<HTMLInputElement>("[data-oi-search] input")!.disabled).toBe(true);
  });

  it("BUG (pinned): with OF's chart, the sidebar Summary shows the tab chart's figures and change, not the overview's (through applyStats)", () => {
    // BUG: see PR — messagesRekey (like subsRekey) ignores the element it rekeys, and applyStats' figures pass every
    // [data-oi-stat] / [data-oi-delta] on the page through it, the `.l-wrapper__sidebar` Summary's included. So with the
    // Direct tab's chart the sidebar "Messages" reads the chart's direct count (2) with the chart's PURCHASES change
    // (+12.5%; the count's own change is 0), and "Message earnings" the chart's purchases ($9.98) with the overview's
    // change (-30%). Correct: the sidebar keeps the overview's figures and changes ("Messages 40 5%", "Message earnings
    // $100.00 -30%"), as it does without the chart (second half).
    const overview = { messages: { massMessages: { count: { total: 40, delta: 5 }, earnings: { total: 100, delta: -30 } } } };
    const side = (doc: Document) => squash(doc.querySelector(".l-wrapper__sidebar .b-useful-data")!.textContent);
    const doc = load("statistics/engagement/messages");
    applyStats(doc, "statistics/engagement/messages", { ...overview, messagesChart: fixture("messages-chart-direct") }, D30, { v2: true, picks: { msg: "direct" } });
    expect(side(doc)).toBe("Summary Messages 2 12.5% Message earnings $9.98 -30%");
    const plain = load("statistics/engagement/messages");
    applyStats(plain, "statistics/engagement/messages", overview, D30, { v2: true, picks: { msg: "direct" } });
    expect(side(plain)).toBe("Summary Messages 40 5% Message earnings $100.00 -30%");
  });
});
