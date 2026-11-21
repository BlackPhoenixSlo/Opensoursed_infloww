import { afterEach, describe, expect, it, vi } from "vitest";
import { applyData, partsOf } from "./ofMirrorData";
import { notificationsHref, notificationsRoute, notificationText, NOTIFICATIONS, relatedUserOf, type MirrorNotification } from "./ofMirrorFeedsNotifications";
import type { PastStream } from "./ofMirrorFeedsStatements";
import { bindFeedSearch } from "./ofMirrorPost";
import { bindWrites, NOT_YET } from "./ofMirrorWrites";
import { applyIdentity } from "./ofMirrorIdentity";
import { load, shown, texts, PLACEHOLDER, fan } from "./ofMirrorData.fixtures";

// Local times (no Z): the dates read the same in every time zone. In the Relay's order.
const NOTIFS: MirrorNotification[] = [
  { type: "subscribed", isRead: false, createdAt: "2026-10-10T10:05:00", text: "subscribed to your profile", user: fan(201, "Alpha One", "alphaone") },
  {
    type: "tip",
    isRead: true,
    createdAt: "2026-10-09T21:30:00",
    text: "<p>tipped you <b>{AMOUNT}</b> on {POST}</p>",
    replacePairs: { "{AMOUNT}": "$5.00", "{POST}": '<a href="https://onlyfans.com/1/alpha">your post</a>' },
    fromUser: { id: 202, name: " ", username: "alphatwo", avatar: null },
  },
  { type: "commented", text: "commented: nice", user: { id: 203 } },
];
const NOTIF_TABS = ["index", "subscribed", "commented", "mentioned", "tip", "purchases", "favorited", "message", "deactivated_media", "tags"].map((t) => `notifications/${t}`);
const notifs = (doc: Document) => shown(doc, ".b-notifications__list .vue-recycle-scroller__item-view");
// [name, @handle, text, date, its hover stamp, unread, icon, avatar src] per row shown.
const notifRows = (doc: Document) =>
  notifs(doc).map((r) => [
    r.querySelector(".b-username .g-user-name")!.textContent,
    r.querySelector(".g-user-username")!.textContent,
    r.querySelector(".b-notifications__list__item__text .g-truncated-text")!.innerHTML,
    r.querySelector(".g-date > span")?.textContent ?? null,
    r.querySelector(".g-date > span")?.getAttribute("title") ?? null,
    r.querySelector(".b-notifications__list__item")!.classList.contains("m-unread"),
    r.querySelector(".b-notifications__avatar__icon svg")?.getAttribute("data-icon-name") ?? null,
    [...r.querySelectorAll(".g-avatar img")].map((i) => i.getAttribute("src")),
  ]);
const WANT_NOTIFS = [
  [" Alpha One ", " @alphaone ", "subscribed to your profile", " Oct 10 ", "Oct 10, 10:05 am", true, "icon-follow", ["/img?u=https://cdn.example/alphaone.jpg"]],
  [" alphatwo ", " @alphatwo ", 'tipped you $5.00 on <a href="https://onlyfans.com/1/alpha" target="_blank" rel="noopener noreferrer">your post</a>', " Oct 9 ", "Oct 9, 9:30 pm", false, "icon-price", []],
  [" 203 ", " @u203 ", "commented: nice", null, null, false, null, []],
];

describe("notifications: the Creator's notifications", () => {
  it("gives every tab the notifications, the tab bar's counts and Home's right column, each tab the type OF's own tab sends (Tags: its mentions)", () => {
    for (const p of NOTIF_TABS) expect(partsOf(p)).toEqual(["notifications", "notificationCounts", "promotions", "events"]);
    const types = Object.fromEntries(Object.entries(NOTIFICATIONS).map(([p, r]) => [p, new URL(r, "http://x").searchParams.get("type")]));
    expect(types).toEqual({
      "notifications/index": null,
      "notifications/subscribed": "subscribed",
      "notifications/commented": "commented",
      "notifications/mentioned": "mentioned",
      "notifications/tip": "tip",
      "notifications/purchases": "purchases",
      "notifications/favorited": "favorited",
      "notifications/message": "message",
      "notifications/deactivated_media": "deactivated_media",
      "notifications/tags": null,
    });
    expect(NOTIFICATIONS["notifications/tags"]).toBe("/api/of/v2/release-forms/mentions?limit=20");
  });

  it.each(NOTIF_TABS)("%s: clones the plain row per notification, in order, with exactly the mapped values", (p) => {
    const doc = load(p);
    applyData(doc, p, { notifications: NOTIFS }, (u) => `/img?u=${u}`);
    expect(notifRows(doc)).toEqual(WANT_NOTIFS);
    const rows = notifs(doc);
    expect(rows.map((r) => r.querySelector("[data-index]")!.getAttribute("data-index"))).toEqual(["0", "1", "2"]);
    expect(rows.map((r) => r.querySelectorAll(".b-list-titles a, .g-avatar__icon, .g-user-name svg, .g-avatar img[src^='data:']").length)).toEqual([0, 0, 0]);
    // The tab's own row: Likes, Promotions and OnlyFans capture rows with no "Add to favorites" button.
    const add = ["notifications/favorited", "notifications/message", "notifications/deactivated_media"].includes(p) ? undefined : " Add to favorites and other lists ";
    expect(rows.map((r) => r.querySelector(".b-list-titles__item__text")?.textContent)).toEqual(Array(3).fill(add));
    // Its list buttons (no Relay write behind them) stay disabled with the tooltip.
    for (const b of rows.flatMap((r) => [...r.querySelectorAll("button[at-attr='add_to_list']")])) expect([b.hasAttribute("disabled"), b.getAttribute("title")]).toEqual([true, NOT_YET]);
    for (const r of rows) expect(r.textContent).not.toMatch(PLACEHOLDER);
    // OF's profile links (the user's avatar, name and handle): their OF profile, in a new tab (those tabs' rows have none).
    expect(rows.map((r) => [...new Set([...r.querySelectorAll("a.g-avatar, a.b-username, a.g-user-username")].map((a) => `${a.getAttribute("href")} ${a.getAttribute("target")} ${a.getAttribute("rel")}`))])).toEqual(
      ["alphaone", "alphatwo", "u203"].map((h) => (add ? [`https://onlyfans.com/${h} _blank noopener noreferrer`] : [])),
    );
  });

  it("a notification's text keeps its OF links (an OF chat opens here) and nothing else of its markup", () => {
    const html = (s: string) => {
      const box = document.createElement("div");
      box.replaceChildren(...notificationText(document, s));
      return box.innerHTML;
    };
    expect(html(" <p>bought your <a href='https://onlyfans.com/my/chats/chat/4242?firstId=9'>message</a> for <b>$6.00</b></p> ")).toBe(
      'bought your <a href="/of-manager/messages/chat?chat=4242" target="_top">message</a> for $6.00',
    );
    expect(html('<a href="/123/alpha">post</a>')).toBe('<a href="https://onlyfans.com/123/alpha" target="_blank" rel="noopener noreferrer">post</a>');
    expect(html('<a href="javascript:alert(1)">x</a> <a href="https://evil.example/">y</a> <img src=x onerror="alert(1)"><script>alert(1)</script>z')).toBe("x y z");
  });

  it("no example row; Creator A's rows then Creator B's leave only B's; no data restores the page byte for byte", () => {
    const p = "notifications/index";
    const doc = load(p);
    const html = doc.documentElement.innerHTML;
    expect(notifs(doc)).toEqual([]);
    applyData(doc, p, { notifications: [] });
    expect(notifs(doc)).toEqual([]);
    applyData(doc, p, { notifications: NOTIFS });
    applyData(doc, p, { notifications: [{ type: "mentioned", text: "Beta mention", user: fan(301, "Beta Two", "betatwo") }] });
    expect(notifRows(doc).map((r) => r.slice(0, 3))).toEqual([[" Beta Two ", " @betatwo ", "Beta mention"]]);
    expect(doc.querySelectorAll("[data-oi-data]")).toHaveLength(1);
    applyData(doc, p, {});
    expect(doc.documentElement.innerHTML).toBe(html);
  });

  it.each(NOTIF_TABS)("%s: rows hide OF's empty tab (its message and centring); an empty list keeps it; no data restores it byte for byte", (p) => {
    const doc = load(p);
    const html = doc.documentElement.innerHTML;
    // OF's own status prompts are hidden with "display: none" (ours with "display:none").
    const emptyTab = () => shown(doc, ".b-notifications__list .empty-message").filter((e) => !e.closest("[style*='display: none']")).map((e) => e.textContent?.trim());
    expect(emptyTab()).toEqual(["No notifications currently!"]);
    applyData(doc, p, { notifications: [] });
    expect(emptyTab()).toEqual(["No notifications currently!"]);
    expect(doc.querySelector(".b-notifications")!.classList.contains("m-empty-page")).toBe(true);
    applyData(doc, p, { notifications: NOTIFS });
    expect(emptyTab()).toEqual([]);
    expect(doc.querySelector(".b-notifications")!.classList.contains("m-empty-page")).toBe(false);
    applyData(doc, p, {});
    expect(doc.documentElement.innerHTML).toBe(html);
  });

  it.each(NOTIF_TABS)("%s: OF's empty tab with no example, count or live control; loading and a Relay error say so in its message", (p) => {
    const doc = load(p);
    const html = doc.documentElement.innerHTML;
    const emptyTab = () => shown(doc, ".b-notifications__list .empty-message").filter((e) => !e.closest("[style*='display: none']")).map((e) => e.textContent?.trim());
    expect(emptyTab()).toEqual(["No notifications currently!"]);
    expect(doc.querySelector(".b-notifications")!.classList.contains("m-empty-page")).toBe(true);
    expect(shown(doc, ".b-notifications__list *, .b-tabs__nav *").filter((e) => !e.children.length).map((e) => e.textContent).join(" ")).not.toMatch(PLACEHOLDER);
    expect(doc.querySelectorAll(".b-tabs__nav .b-tabs__nav__count")).toHaveLength(0);
    // Search users, the tab bar's rearrange button, the row's list buttons and the right column's search: no source.
    const off = [...doc.querySelectorAll<HTMLButtonElement | HTMLInputElement>("[aria-label='Search users'], .b-tabs__nav button, [at-attr='add_to_list'], input[name='feed-search-input']")];
    expect(off.length).toBeGreaterThanOrEqual(3);
    for (const b of off) expect([b.disabled, b.title]).toEqual([true, NOT_YET]);
    // OF's own settings link stays.
    expect(doc.querySelector("a[aria-label='Settings']")?.getAttribute("href")).toBe("/of-manager/settings/notifications");
    applyData(doc, p, { notificationsStatus: null });
    expect(emptyTab()).toEqual(["Loading notifications…"]);
    applyData(doc, p, { notificationsStatus: "Relay down" });
    expect(emptyTab()).toEqual(["Could not load notifications: Relay down"]);
    applyData(doc, p, { notifications: [] });
    expect(emptyTab()).toEqual(["No notifications currently!"]);
    applyData(doc, p, {});
    expect(doc.documentElement.innerHTML).toBe(html);
  });

  // [href, count text or null] per tab shown.
  const tabCounts = (doc: Document) =>
    shown(doc, "a.b-tabs__nav__link[href^='/of-manager/notifications']").map((a) => [
      a.getAttribute("href"),
      shown(doc, ".b-tabs__nav__count").find((c) => a.contains(c))?.textContent ?? null,
    ]);

  it.each(NOTIF_TABS)("%s: the tab bar shows the Creator's counts (All capped at 99, Tags its newTagsCount), none at zero; no data restores it", (p) => {
    const doc = load(p);
    const html = doc.documentElement.innerHTML;
    const counts = { all: 120, subscribed: 3, purchases: 0, tip: 12000, commented: 1 };
    applyData(doc, p, { notificationCounts: { counts, tags: 2 } });
    const want: Record<string, string | null> = {
      "/of-manager/notifications": " 99+ ",
      "/of-manager/notifications/subscribed": " 3 ",
      "/of-manager/notifications/purchases": null,
      "/of-manager/notifications/tip": " 9999+ ",
      "/of-manager/notifications/tags": " 2 ",
      "/of-manager/notifications/commented": " 1 ",
    };
    const got = tabCounts(doc);
    expect(got.length).toBeGreaterThanOrEqual(10);
    for (const [href, text] of got) expect(text).toBe(want[href!] ?? null);
    applyData(doc, p, { notificationCounts: { counts: {} } });
    expect(tabCounts(doc).every(([, t]) => t === null)).toBe(true);
    applyData(doc, p, {});
    expect(doc.documentElement.innerHTML).toBe(html);
  });
});

const STREAMS: PastStream[] = [
  { id: 1, media: { files: { thumb: { url: "https://cdn.example/s1.jpg" } } }, viewsCount: 7, startedAt: "2026-10-09T21:30:00" },
  { id: 2, media: null, viewsCount: 1, startedAt: "2026-10-08T10:00:00" },
  { id: 3, media: { files: {} }, startedAt: "bad" },
];

// ticket 17: Search users' URL state (?related_user=) and the read it makes (spec story 15).
describe("notifications: Search users narrows a tab to one fan through the page URL", () => {
  const TYPE_TABS = NOTIF_TABS.filter((p) => p !== "notifications/tags");

  it.each([
    ["related_user=9101", "9101"],
    ["related_user=%209101%20", "9101"],
    ["related_user=", null],
    ["related_user=alpha", null],
    ["related_user=91x01", null],
    ["related_user=-9101", null],
    ["", null],
  ])("?%s: the fan's OF id %s (digits only: the Relay's related_user is a number; anything else is dropped)", (query, want) => {
    expect(relatedUserOf(new URLSearchParams(query))).toBe(want);
  });

  it.each(TYPE_TABS)("%s: a fan re-reads the tab's notifications with OF's related_user; none reads the tab as is", (p) => {
    expect(notificationsRoute(p, "9101")).toBe(`${NOTIFICATIONS[p]}&related_user=9101`);
    expect(notificationsRoute(p, null)).toBe(NOTIFICATIONS[p]);
  });

  it("Tags: a fan keeps the mentions read as is (no related_user there; its rows are filtered as read)", () => {
    expect(notificationsRoute("notifications/tags", "9101")).toBe("/api/of/v2/release-forms/mentions?limit=20");
    expect(notificationsRoute("notifications/tags", null)).toBe("/api/of/v2/release-forms/mentions?limit=20");
  });

  it("a page that is no notifications tab reads nothing", () => {
    expect(notificationsRoute("home/index", "9101")).toBeNull();
  });

  it.each([
    ["notifications/index", "9101", "/of-manager/notifications?related_user=9101"],
    ["notifications/tip", "9101", "/of-manager/notifications/tip?related_user=9101"],
    ["notifications/tags", "9101", "/of-manager/notifications/tags?related_user=9101"],
    ["notifications/tip", null, "/of-manager/notifications/tip"],
    ["notifications/index", null, "/of-manager/notifications"],
  ])("%s for %s opens %s (Back leaves the fan)", (p, user, want) => {
    expect(notificationsHref(p, user)).toBe(want);
  });
});

describe("streaming dashboard: the Creator's past live streams", () => {
  const P = "streaming/dashboard";
  // [img src, button, viewers, date, its hover stamp] per thumb shown.
  const thumbs = (doc: Document) =>
    shown(doc, ".b-s-dashboard__thumbs > .b-s-dashboard__thumb-holder").map((t) => [
      t.querySelector("img")?.getAttribute("src") ?? null,
      t.querySelector(".b-s-dashboard__btn button")?.textContent,
      t.querySelector(".b-s-dashboard__thumb-content__viewers")?.textContent,
      t.querySelector(".b-s-dashboard__thumb-content__time span")?.textContent ?? null,
      t.querySelector(".b-s-dashboard__thumb-content__time span")?.getAttribute("title") ?? null,
    ]);

  it("gives the dashboard the past streams, the schedule form Home's right column and Go live nothing", () => {
    expect(partsOf(P)).toEqual(["pastStreams"]);
    expect(partsOf("streaming/index")).toEqual([]);
    expect(partsOf("streaming/dashboard/create")).toEqual(["promotions", "events"]);
  });

  it("one thumb per stream with media, in OF's markup; the empty-list centring goes; no data restores the capture byte for byte", () => {
    const doc = load(P);
    const html = doc.documentElement.innerHTML;
    applyData(doc, P, { pastStreams: STREAMS }, (u) => `/img?u=${u}`);
    expect(thumbs(doc)).toEqual([
      ["/img?u=https://cdn.example/s1.jpg", " View stats ", " Viewers: 7", " Oct 9 ", "Oct 9, 9:30 pm"],
      [null, " View stats ", " Viewers: 0", null, null],
    ]);
    const scope = doc.querySelector(".b-s-dashboard__thumbs")!.getAttributeNames().filter((a) => a.startsWith("data-v-"));
    expect(scope.length).toBe(1);
    expect(doc.querySelector(".b-s-dashboard__thumb-holder")!.hasAttribute(scope[0])).toBe(true);
    expect(doc.querySelector(".g-sides-gaps")!.classList.contains("d-flex")).toBe(false);
    expect(doc.querySelector(".infinite-loading-container")!.classList.contains("mt-auto")).toBe(false);
    applyData(doc, P, {});
    expect(doc.documentElement.innerHTML).toBe(html);
  });

  it("no stream with media keeps the capture", () => {
    const doc = load(P);
    const html = doc.documentElement.innerHTML;
    applyData(doc, P, { pastStreams: [STREAMS[1]] });
    expect(doc.documentElement.innerHTML).toBe(html);
  });

  it("shows no captured example: the dashboard's list is OF's empty one", () => {
    const doc = load(P);
    expect(doc.querySelectorAll(".b-s-dashboard__thumb-holder")).toHaveLength(0);
  });
});

describe("Go live: Inflowwww cannot stream, so every control is quietly disabled", () => {
  const P = "streaming/index";

  it("Start Live Video shows; the six option rows lose the pointer; the switches and description are disabled (each control's own state: PHASE4_CONTROLS)", () => {
    const doc = load(P);
    const start = doc.querySelector<HTMLButtonElement>(".b-streaming__btn-start")!;
    expect([start.style.display, start.textContent!.trim()]).toEqual(["", "Start Live Video"]);
    const rows = [...doc.querySelectorAll<HTMLElement>(".b-streaming-details__row")];
    expect(rows.length).toBe(6);
    for (const r of rows) expect(r.classList.contains("g-pointer-cursor")).toBe(false);
    const fields = [...doc.querySelectorAll<HTMLInputElement | HTMLTextAreaElement>(".b-streaming-details input, .b-streaming-details textarea")];
    expect(fields.map((f) => [f.tagName, f.disabled])).toEqual([
      ["INPUT", true],
      ["INPUT", true],
      ["TEXTAREA", true],
    ]);
  });

  it("the camera's endless loading says it is not available instead", () => {
    const doc = load(P);
    expect(doc.querySelector(".b-stream-status-connect")!.textContent!.trim()).toBe(NOT_YET);
    expect(doc.querySelector(".b-text-progress__dots")).toBeNull();
  });

  it("no enabled button: a click anywhere sends nothing and shows no Read-only note", () => {
    const doc = load(P);
    const handlers = { uploadProfileImage: vi.fn(), saveProfile: vi.fn(), setReplyOnSubscribe: vi.fn(), submit: vi.fn(), navigate: vi.fn() };
    const unbind = bindWrites(doc, P, handlers, true);
    expect([...doc.querySelectorAll<HTMLButtonElement>(".l-streaming-container button")].filter((b) => !b.disabled)).toEqual([]);
    for (const r of doc.querySelectorAll<HTMLElement>(".b-streaming-details__row")) r.click();
    expect(doc.getElementById("oi-note")).toBeNull();
    expect(handlers.submit).not.toHaveBeenCalled();
    unbind();
  });
});

describe("the stream schedule form: no captured example in its right column", () => {
  const P = "streaming/dashboard/create";

  it("no example price, bundle count, promotion or banner; the price line waits for the Creator's own", () => {
    const doc = load(P);
    expect(shown(doc, ".b-feed__aside .b-offer-join")).toEqual([]); // only OF's card, kept hidden as applyPromotions' template
    expect(doc.querySelectorAll(".b-feed__aside .b-offer-join")).toHaveLength(1);
    expect(doc.querySelector(".b-feed__aside")!.textContent).not.toMatch(/subscription bundles/);
    expect(doc.querySelector(".banner_place")).toBeNull();
    const price = doc.querySelector<HTMLElement>("[data-oi-price]")!;
    expect(price.style.display).toBe("none");
    applyIdentity(doc, { id: 4242, username: "synthcreator", name: "Synthetic Creator", subscribePrice: 9.99 });
    expect(price.style.display).toBe("");
    expect(price.textContent).toContain("$9.99");
  });

  it("the Creator's promotions and Scheduled events, as on Home; no data restores the capture", () => {
    const doc = load(P);
    const html = doc.documentElement.innerHTML;
    const now = new Date(2026, 9, 17, 12, 0);
    applyData(doc, P, {
      promotions: [{ id: 1, message: "Synthetic welcome", price: 0, type: "new", subscribeDays: 7, isFinished: false, canClaim: true }],
      events: [{ id: 4, type: "stream", publishDateTime: "2026-10-25T20:00:00", entity: { id: 40, text: "Live" } }],
      now,
    });
    expect(texts(doc, ".b-offer-join .b-menu-list__text")).toEqual(["Limited offer - Free trial for 7 days!"]);
    expect([...doc.querySelectorAll(".b-widget__events > div")].map((r) => r.lastElementChild!.textContent)).toEqual(["Stream · Live"]);
    applyData(doc, P, {});
    expect(doc.documentElement.innerHTML).toBe(html);
  });

  it("SCHEDULE and Scheduled events' + (Add to queue) are not disabled (search, Add cover and the format button: PHASE4_CONTROLS)", () => {
    const doc = load(P);
    const plus = doc.querySelector<HTMLButtonElement>("[at-attr='add_event_widget']")!;
    expect([plus.disabled, plus.title, plus.hasAttribute("data-oi-wired")]).toEqual([false, "", true]);
    expect(doc.querySelector<HTMLButtonElement>(".g-page__header > button.g-btn")!.disabled).toBe(false);
    expect(doc.querySelector(".b-widget__footer a")!.getAttribute("href")).toBe("/of-manager/queue"); // View queue: OF's link
  });
});

// ticket 83: Phase 4's controls, one row each: [page, control (its Not-yet sweep label), selector, index among the
// selector's shown matches (null: every one), its [disabled, title, data-oi-wired]]. Each Phase 4 control ticket flips
// only its own row (a Wired control keeps the Not-yet title until its Live-proof pass, D1). Go live's rows stay pinned
// until track B's gate ticket closes (D7, D28). A disabled row sends nothing and shows no note when clicked.
type ControlState = [disabled: boolean, title: string, wired: boolean];
const OFF: ControlState = [true, NOT_YET, false];
const SCHED = "streaming/dashboard/create";
const GO = "streaming/index";
const PHASE4_CONTROLS: [string, string, string, number | null, ControlState][] = [
  [SCHED, "Search users or posts", "input[name='feed-search-input']", null, [false, NOT_YET, true]], // ticket 84
  [SCHED, "Search", "button.m-search-btn", null, [true, NOT_YET, true]], // ticket 84: off until the box has text, as OF's
  [SCHED, "Add cover", ".post_media__controls button", null, OFF],
  [SCHED, "[g-btn.m-with-round-hover]", ".b-icon-text-container button", null, OFF], // the description's format button
  ["streaming/dashboard", "View stats", ".b-s-dashboard__btn button", null, OFF], // OF's stats modal, never captured
  [GO, "Post to X that I'm Live", ".b-streaming-details__row", 0, OFF],
  [GO, "Available to all subscribers", ".b-streaming-details__row", 1, OFF],
  [GO, "Add a tip goal", ".b-streaming-details__row", 2, OFF],
  [GO, "Show total collected tips to viewers", ".b-streaming-details__row", 3, OFF],
  [GO, "Private comments only with tips", ".b-streaming-details__row", 4, OFF],
  [GO, "\u200b0 / 500", ".b-streaming-details__row", 5, OFF], // the description
  [GO, "Start Live Video", ".b-streaming__btn-start", null, OFF],
];
// The page as the app shows it before the controls are read: the dashboard lists two past streams (one View stats each).
// A binder's unbind runs after its row.
const PHASE4_PREP: Record<string, (doc: Document) => (() => void) | void> = {
  "streaming/dashboard": (doc) => applyData(doc, "streaming/dashboard", { pastStreams: STREAMS }),
  [SCHED]: (doc) => bindFeedSearch(doc, { handlers: null }), // ticket 84: the right column search
};
const prepUnbinds: (() => void)[] = [];
const stateOf = (e: HTMLElement): ControlState => [
  e.matches("button, input, textarea") ? (e as HTMLButtonElement).disabled : e.getAttribute("aria-disabled") === "true",
  e.title,
  e.hasAttribute("data-oi-wired"),
];
// The Not-yet sweep's label (scripts/of-mirror-check/sweep_diff.py LABEL_JS, less its date rewrite).
const labelOf = (e: HTMLElement): string => {
  const t = (e.getAttribute("aria-label") || e.textContent!.trim() || e.getAttribute("placeholder") || "")
    .trim().replace(/\s+/g, " ").slice(0, 60);
  const cls = (e.getAttribute("class") || "").trim().split(/\s+/).filter(Boolean).slice(0, 2).join(".");
  return t || (cls ? `[${cls}]` : `[${e.tagName}]`);
};

describe("Phase 4's controls on the schedule form, the dashboard and Go live, one row each", () => {
  afterEach(() => prepUnbinds.splice(0).forEach((u) => u()));
  it.each(PHASE4_CONTROLS)("%s %j (%s #%s): %j", (page, control, sel, index, want) => {
    const doc = load(page);
    const unbindPrep = PHASE4_PREP[page]?.(doc);
    if (unbindPrep) prepUnbinds.push(unbindPrep);
    const all = shown(doc, sel) as HTMLElement[];
    const els = index === null ? all : all.slice(index, index + 1);
    expect(els.length).toBeGreaterThan(0);
    expect(els.map(labelOf)).toEqual(els.map(() => control));
    expect(els.map(stateOf)).toEqual(els.map(() => want));
    if (!want[0]) return; // a disabled control: a click sends nothing and shows no note
    const handlers = { uploadProfileImage: vi.fn(), saveProfile: vi.fn(), setReplyOnSubscribe: vi.fn(), submit: vi.fn(), navigate: vi.fn() };
    const unbind = bindWrites(doc, page, handlers, true);
    for (const e of els) e.click();
    expect(doc.getElementById("oi-note")).toBeNull();
    expect(handlers.submit).not.toHaveBeenCalled();
    unbind();
  });
});
