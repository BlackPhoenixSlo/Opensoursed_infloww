import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, describe, expect, it, vi, type Mock } from "vitest";
import { applyData } from "./ofMirrorData";
import { dayBars, dayCounts, queueActions, TEMPLATES, wallClock, type QueueItem } from "./ofMirrorFeeds";
import {
  ADD_HELP,
  ADD_MENU,
  ADD_TABS,
  ADD_TITLE,
  bindCalendar,
  bindQueue,
  CONFIRM_DELETE,
  CONFIRM_PUBLISH,
  createAt,
  createHref,
  drawQueue,
  fromWallClock,
  LATER_MENU,
  laterHref,
  messageEditDraft,
  postEditDraft,
  queueStart,
  shiftMonth,
  ymd,
  type CreateKind,
  type EditablePost,
  type LaterKind,
  type QueuedMessage,
  type QueueHandlers,
} from "./ofMirrorQueue";
import { loadDraft } from "./ofMirrorPost";
import { loadMassDraft } from "./ofMirrorChat";
import { localIso } from "./ofMirrorWrites";
import { QUEUE_CHANGE } from "./ofMirrorFeeds";
import { bindWrites, NOT_YET, SELECT_MODEL, TOO_SOON } from "./ofMirrorWrites";
import type { QueueKind } from "./ofMirrorFeeds";
import { standInModel } from "./ofMirrorProfile";

const capture = (p: string) => readFileSync(resolve(__dirname, `../public/of-mirror/pages/${p}.html`), "utf8");
const load = (p: string) => {
  document.documentElement.innerHTML = capture(p);
  return document;
};
const AGENDA_TPL = TEMPLATES.agenda!.pick(new DOMParser().parseFromString(capture(TEMPLATES.agenda!.page), "text/html"))!;

// Synthetic schedule items: the schedule's own id wraps the post's or message's.
const POST: QueueItem = { id: 901, type: "post", publishDateTime: "2026-10-12T09:05:00", entity: { id: 11, text: "Alpha post", isMediaReady: true } };
const PINNED: QueueItem = { id: 902, type: "post", publishDateTime: "2026-10-13T09:05:00", entity: { id: 12, text: "Pinned post", isPinned: true, isMediaReady: false } };
// A scheduled message has its send time on the entity (OF's isSFLMessage is a chat entity without one).
const CHAT: QueueItem = { id: 903, type: "chat", publishDateTime: "2026-10-14T18:30:00", entity: { id: 22, text: "Alpha chat", scheduledAt: "2026-10-14T18:30:00" } };

// Queue rows: the month pages' agenda items, the saved-for-later pages' OF cards.
const rows = (doc: Document) => [...doc.querySelectorAll<HTMLElement>(".b-agenda__area-events__item, .b-post.m-queue-post")];
const more = (row: Element) => row.querySelector<HTMLButtonElement>("[at-attr='more_menu']")!;
const menu = (doc: Document) => doc.getElementById("oi-queue-menu");
const entries = (doc: Document) => [...menu(doc)!.querySelectorAll<HTMLButtonElement>("button")].map((b) => [b.getAttribute("at-attr"), b.textContent!.trim(), b.disabled]);
const entry = (doc: Document, at: string) => menu(doc)!.querySelector<HTMLButtonElement>(`button[at-attr='${at}']`)!;
const handlers = (over: Partial<{ [K in keyof QueueHandlers]: Mock<QueueHandlers[K]> }> = {}) => ({
  publish: vi.fn((_id: string) => Promise.resolve({ success: true })),
  remove: vi.fn((_kind: string, _id: string) => Promise.resolve({ success: true })),
  pin: vi.fn((_id: string) => Promise.resolve({ success: true })),
  confirm: vi.fn((_text: string) => true),
  create: vi.fn((_kind: CreateKind, _at: Date) => {}),
  later: vi.fn((_kind: LaterKind) => {}),
  edit: vi.fn((_kind: QueueKind, _id: string) => Promise.resolve()),
  ...over,
});
const flush = () => new Promise((r) => setTimeout(r, 0));
const noteText = (doc: Document) => doc.getElementById("oi-note")?.textContent;

describe("queueActions", () => {
  it("a wrapped item: its entity is the target, its own id the schedule", () => {
    expect(queueActions("queue/state-list-view", POST)).toEqual({ kind: "post", target: "11", schedule: "901", ready: true, pinned: false });
    expect(queueActions("queue/state-list-view", PINNED)).toMatchObject({ ready: false, pinned: true });
  });
  it("a saved-for-later item takes its page's kind when it has no type", () => {
    expect(queueActions("queue/saved-for-later-messages", { id: 5, entity: { id: 6 } })).toMatchObject({ kind: "chat", target: "6", schedule: "5" });
    expect(queueActions("queue/saved-for-later-posts", { id: 5, entity: { id: 6 } })).toMatchObject({ kind: "post" });
  });
  it("a flat item (no entity): its id is the target, no schedule", () => {
    expect(queueActions("queue/state-tab-messages", { id: 31, type: "chat", publishDateTime: "2026-10-20T07:15:00" })).toMatchObject({ kind: "chat", target: "31", schedule: "" });
  });
  it("no id or a stream: no actions", () => {
    expect(queueActions("queue/state-list-view", { type: "post", entity: { text: "x" } })).toBeNull();
    expect(queueActions("queue/state-list-view", { id: 1, type: "stream", entity: { id: 2 } })).toBeNull();
  });
});

describe("queue rows: OF's More button", () => {
  it("each post or message row with an id gets the round More button in the agenda scope; one without gets none", () => {
    const doc = load("queue/state-list-view");
    applyData(doc, "queue/state-list-view", { queue: [POST, CHAT, { type: "post", publishDateTime: "2026-10-15T10:00:00", entity: { text: "No id" } }] });
    const [a, b, c] = rows(doc);
    expect(more(a).closest(".b-post__tools__more")).not.toBeNull();
    expect(more(a).matches("button.m-btn-round-dots[aria-label='More'][data-oi-wired]")).toBe(true);
    expect(more(a).querySelector("svg path")).not.toBeNull();
    expect(a.dataset).toMatchObject({ oiQueueKind: "post", oiQueueTarget: "11", oiQueueSchedule: "901" });
    expect(more(b)).not.toBeNull();
    expect(c.querySelector("[at-attr='more_menu']")).toBeNull();
    const scope = doc.querySelector(".b-agenda")!.getAttributeNames().filter((n) => n.startsWith("data-v-"));
    for (const n of scope) expect(more(a).hasAttribute(n)).toBe(true);
  });

  it("no data restores the capture byte for byte", () => {
    const doc = load("queue/state-list-view");
    const html = doc.documentElement.innerHTML;
    applyData(doc, "queue/state-list-view", { queue: [POST, CHAT] });
    applyData(doc, "queue/state-list-view", {});
    expect(doc.documentElement.innerHTML).toBe(html);
  });
});

describe("bindQueue", () => {
  // Every test shares `document`: its listeners go when it ends.
  const unbinds: (() => void)[] = [];
  afterEach(() => {
    while (unbinds.length) unbinds.pop()!();
  });
  const setup = (page = "queue/state-list-view", queue: QueueItem[] = [POST, PINNED, CHAT], h: ReturnType<typeof handlers> | null = handlers()) => {
    const doc = load(page);
    applyData(doc, page, { queue, templates: { agenda: AGENDA_TPL } });
    const unbind = bindQueue(doc, h);
    unbinds.push(unbind);
    return { doc, h, unbind };
  };

  it("More opens OF's post menu; a second click closes it", () => {
    const { doc } = setup();
    more(rows(doc)[0]).click();
    expect(entries(doc)).toEqual([
      ["pin_to_profile", "Pin to your profile page", false],
      ["edit_post", "Edit post", false],
      ["publish_now", "Publish now", false],
      ["delete_post", "Delete post", false],
    ]);
    expect(entry(doc, "edit_post").title).toBe("");
    expect(entry(doc, "publish_now").title).toBe("");
    expect(menu(doc)!.querySelector("hr + button.m-danger")?.getAttribute("at-attr")).toBe("delete_post");
    expect(more(rows(doc)[0]).getAttribute("aria-expanded")).toBe("true");
    more(rows(doc)[0]).click();
    expect(menu(doc)).toBeNull();
  });

  it("a pinned post offers unpin; media not ready greys out Post now; a message gets the message menu", () => {
    const { doc } = setup();
    more(rows(doc)[1]).click();
    expect(entries(doc)[0]).toEqual(["pin_to_profile", "Unpin from your profile page", false]);
    expect(entry(doc, "publish_now").disabled).toBe(true);
    more(rows(doc)[2]).click();
    expect(entries(doc)).toEqual([
      ["edit_message", "Edit message", false],
      ["message_now", "Send message right now", false],
      ["delete_message", "Delete message", false],
    ]);
  });

  it("Post now publishes the schedule id after a confirm; Message now too", async () => {
    const { doc, h } = setup();
    more(rows(doc)[0]).click();
    entry(doc, "publish_now").click();
    expect(h!.confirm).toHaveBeenCalledWith(CONFIRM_PUBLISH.post);
    expect(menu(doc)).toBeNull();
    await flush();
    more(rows(doc)[2]).click();
    entry(doc, "message_now").click();
    expect(h!.confirm).toHaveBeenLastCalledWith(CONFIRM_PUBLISH.chat);
    await flush();
    expect(h!.publish.mock.calls).toEqual([["901"], ["903"]]);
  });

  it("Post now / Message now cancelled sends nothing", () => {
    const { doc, h } = setup(undefined, undefined, handlers({ confirm: vi.fn(() => false) }));
    more(rows(doc)[0]).click();
    entry(doc, "publish_now").click();
    more(rows(doc)[2]).click();
    entry(doc, "message_now").click();
    expect(h!.confirm).toHaveBeenCalledTimes(2);
    expect(h!.publish).not.toHaveBeenCalled();
  });

  it("a second action while one is in flight sends nothing", () => {
    const { doc, h } = setup(undefined, undefined, handlers({ publish: vi.fn(() => new Promise(() => {})) }));
    more(rows(doc)[0]).click();
    entry(doc, "publish_now").click();
    more(rows(doc)[2]).click();
    entry(doc, "message_now").click();
    expect(h!.publish).toHaveBeenCalledTimes(1);
  });

  it("Delete asks first, then deletes the post or the queued message by its own id", async () => {
    const { doc, h } = setup();
    more(rows(doc)[0]).click();
    entry(doc, "delete_post").click();
    expect(h!.confirm).toHaveBeenCalledWith(CONFIRM_DELETE.post);
    await flush();
    more(rows(doc)[2]).click();
    entry(doc, "delete_message").click();
    expect(h!.confirm).toHaveBeenLastCalledWith(CONFIRM_DELETE.chat);
    await flush();
    expect(h!.remove.mock.calls).toEqual([
      ["post", "11"],
      ["chat", "22"],
    ]);
  });

  it("Delete cancelled sends nothing", () => {
    const { doc, h } = setup(undefined, undefined, handlers({ confirm: vi.fn(() => false) }));
    more(rows(doc)[0]).click();
    entry(doc, "delete_post").click();
    expect(h!.remove).not.toHaveBeenCalled();
  });

  it("Pin toggles through the post id and says Saved", async () => {
    const { doc, h } = setup();
    more(rows(doc)[1]).click();
    entry(doc, "pin_to_profile").click();
    await flush();
    expect(h!.pin.mock.calls).toEqual([["12"]]);
    expect(noteText(doc)).toBe("Saved");
  });

  it("Edit post and Edit message open the item's composer by the post's or the queued message's own id; nothing is written", async () => {
    const { doc, h } = setup();
    more(rows(doc)[0]).click();
    entry(doc, "edit_post").click();
    await flush();
    more(rows(doc)[2]).click();
    entry(doc, "edit_message").click();
    await flush();
    expect(h!.edit.mock.calls).toEqual([
      ["post", "11"],
      ["chat", "22"],
    ]);
    expect([h!.publish, h!.remove, h!.pin].every((f) => f.mock.calls.length === 0)).toBe(true);
  });

  it("Edit that cannot load the item notes the relay error under the row", async () => {
    const { doc } = setup(undefined, undefined, handlers({ edit: vi.fn(() => Promise.reject(new Error("upstream 404"))) }));
    more(rows(doc)[0]).click();
    entry(doc, "edit_post").click();
    await flush();
    expect(noteText(doc)).toBe("Could not open: upstream 404");
  });

  it("a failure notes the relay error under the row", async () => {
    const { doc } = setup(undefined, undefined, handlers({ remove: vi.fn(() => Promise.reject(new Error("upstream 400"))) }));
    more(rows(doc)[0]).click();
    entry(doc, "delete_post").click();
    await flush();
    expect(noteText(doc)).toBe("Could not delete: upstream 400");
    expect(rows(doc)[0].nextElementSibling?.id).toBe("oi-note");
  });

  it("Messages tab: a flat message has no schedule id, so Message now is quietly disabled; delete cancels its id", async () => {
    const { doc, h } = setup("queue/state-tab-messages", [{ id: 31, type: "chat", publishDateTime: "2026-10-12T07:15:00", text: "Queued hello" }]);
    more(rows(doc)[0]).click();
    expect(entry(doc, "message_now").disabled).toBe(true);
    expect(entry(doc, "message_now").title).toBe(NOT_YET);
    entry(doc, "message_now").dispatchEvent(new MouseEvent("click", { bubbles: true }));
    expect(noteText(doc)).toBeUndefined();
    expect(h!.publish).not.toHaveBeenCalled();
    more(rows(doc)[0]).click();
    entry(doc, "delete_message").click();
    await flush();
    expect(h!.remove.mock.calls).toEqual([["chat", "31"]]);
  });

  it("saved for later: Post now publishes the schedule id", async () => {
    const { doc, h } = setup("queue/saved-for-later-posts", [{ id: 41, entity: { id: 42, text: "Saved" } }]);
    more(rows(doc)[0]).click();
    entry(doc, "publish_now").click();
    await flush();
    expect(h!.publish.mock.calls).toEqual([["41"]]);
  });

  it("no single model: every action sends nothing and asks for a model", () => {
    const { doc } = setup(undefined, undefined, null);
    more(rows(doc)[0]).click();
    entry(doc, "delete_post").click();
    expect(noteText(doc)).toBe(SELECT_MODEL);
  });

  it("an outside click or Escape closes the menu; unbind removes it", () => {
    const { doc, unbind } = setup();
    more(rows(doc)[0]).click();
    doc.body.click();
    expect(menu(doc)).toBeNull();
    more(rows(doc)[0]).click();
    doc.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
    expect(menu(doc)).toBeNull();
    more(rows(doc)[0]).click();
    unbind();
    expect(menu(doc)).toBeNull();
  });

  it("with bindWrites bound too, More and the menu never get the read-only fallback note", () => {
    const { doc } = setup();
    unbinds.push(bindWrites(doc, "queue/state-list-view", null));
    more(rows(doc)[0]).click();
    expect(noteText(doc)).toBeUndefined();
    entry(doc, "publish_now").click();
    expect(noteText(doc)).toBeUndefined();
  });
});

describe("the month pages' calendar (OF's changeMonth / changeDay / tabs)", () => {
  const TODAY = new Date(2026, 9, 12, 15, 0);
  const at = (y: number, m: number, d: number) => new Date(y, m - 1, d);
  const cells = (doc: Document) => [...doc.querySelectorAll(".v-calendar-monthly .v-calendar-weekly__day")];
  const cellOf = (doc: Document, day: string) => doc.querySelector(`.b-month-day-cell__value[at-attr='date:${day}']`)!.closest(".v-calendar-weekly__day")!;
  const header = (doc: Document) => doc.querySelector(".g-page__subheader .b-queue-header__date")!.textContent!.trim();
  const sideDay = (doc: Document) => doc.querySelector(".l-wrapper__sidebar .b-queue-header__date")!.textContent!.trim();
  const btn = (doc: Document, a: string) => doc.querySelector<HTMLButtonElement>(`[at-attr='${a}']`)!;
  const unbinds: (() => void)[] = [];
  afterEach(() => {
    while (unbinds.length) unbinds.pop()!();
  });

  it("shiftMonth: back to today's month gives today; forward the month's first day; the day clamps to a short month", () => {
    expect(ymd(shiftMonth(at(2026, 11, 1), -1, TODAY))).toBe("2026-10-12");
    expect(ymd(shiftMonth(at(2026, 10, 12), 1, TODAY))).toBe("2026-11-01");
    expect(ymd(shiftMonth(at(2026, 12, 1), -1, TODAY))).toBe("2026-11-01");
    expect(ymd(shiftMonth(at(2027, 1, 31), 1, TODAY))).toBe("2027-02-01");
  });

  it("queueStart: ?date= when it is a day, else today", () => {
    expect(ymd(queueStart("2026-11-20", TODAY))).toBe("2026-11-20");
    expect(ymd(queueStart(null, TODAY))).toBe("2026-10-12");
    expect(ymd(queueStart("garbage", TODAY))).toBe("2026-10-12");
  });

  it("drawQueue on today: the capture's month as captured (header, weeks, selected day, arrows)", () => {
    const doc = load("queue/index");
    const want = cells(doc).map((c) => [c.className.split(" ").filter((x) => x.startsWith("v-")).sort().join(" "), c.querySelector(".b-month-day-cell__value")!.textContent!.trim()]);
    drawQueue(doc, TODAY, TODAY);
    expect(header(doc)).toBe("October 2026");
    expect(sideDay(doc)).toBe("October 12, 2026");
    expect(btn(doc, "prev_month").disabled).toBe(true);
    expect(btn(doc, "prev_day_sidebar").disabled).toBe(true);
    expect(cells(doc).map((c) => [c.className.split(" ").filter((x) => x.startsWith("v-")).sort().join(" "), c.querySelector(".b-month-day-cell__value")!.textContent!.trim()])).toEqual(want);
    expect(cellOf(doc, "2026-10-12").querySelector(".b-month-day-cell.selected")).not.toBeNull();
  });

  it("drawQueue on a later month: its weeks, nothing past, the back arrows on, the view switch carrying ?date=", () => {
    const doc = load("queue/index");
    drawQueue(doc, at(2026, 11, 1), TODAY);
    expect(header(doc)).toBe("November 2026");
    expect(sideDay(doc)).toBe("November 1, 2026");
    expect(btn(doc, "prev_month").disabled).toBe(false);
    expect(btn(doc, "prev_day_sidebar").disabled).toBe(false);
    // Nov 2026: Sunday the 1st to Monday the 30th, then Dec 1-5: five weeks.
    expect(doc.querySelectorAll(".v-calendar-monthly > .v-calendar-weekly__week")).toHaveLength(5);
    expect(cells(doc)).toHaveLength(35);
    expect(cells(doc)[0].querySelector(".b-month-day-cell__value")!.textContent!.trim()).toBe("Nov 1");
    expect(cells(doc).some((c) => c.classList.contains("v-past"))).toBe(false);
    expect(cellOf(doc, "2026-12-01").classList.contains("v-outside")).toBe(true);
    expect(doc.querySelector(".g-page__subheader .b-content-filter__group-btns a[href]")!.getAttribute("href")).toBe("/of-manager/queue/state-list-view?date=2026-11-01");
  });

  it("drawQueue keeps the cells shown, adding a sixth week for a long month and dropping it again", () => {
    const doc = load("queue/index");
    const kept = cells(doc)[3];
    drawQueue(doc, at(2027, 1, 1), TODAY);
    expect(doc.querySelectorAll(".v-calendar-monthly > .v-calendar-weekly__week")).toHaveLength(6);
    expect(cells(doc).map((c) => c.querySelector(".b-month-day-cell__value")!.getAttribute("at-attr"))).toEqual(
      Array.from({ length: 42 }, (_, i) => `date:${ymd(at(2026, 12, 27 + i))}`),
    );
    expect(cells(doc)[3]).toBe(kept);
    drawQueue(doc, at(2027, 2, 1), TODAY);
    expect(doc.querySelectorAll(".v-calendar-monthly > .v-calendar-weekly__week")).toHaveLength(5);
    expect(cells(doc)).toHaveLength(35);
    expect(cells(doc)[0].querySelector(".b-month-day-cell__value")!.textContent!.trim()).toBe("31");
    expect(cellOf(doc, "2027-02-01").querySelector(".b-month-day-cell__value")!.textContent!.trim()).toBe("Feb 1");
  });

  it("bindCalendar: the arrows, a day and the tabs act in place, each sending QUEUE_CHANGE; a past day does nothing", () => {
    const doc = load("queue/index");
    const changes = vi.fn();
    doc.addEventListener(QUEUE_CHANGE, changes);
    unbinds.push(() => doc.removeEventListener(QUEUE_CHANGE, changes));
    unbinds.push(bindCalendar(doc, TODAY, () => TODAY));
    expect(changes).toHaveBeenCalledTimes(1);
    btn(doc, "prev_month").click();
    expect(changes).toHaveBeenCalledTimes(1);
    btn(doc, "next_month").click();
    expect([header(doc), sideDay(doc)]).toEqual(["November 2026", "November 1, 2026"]);
    btn(doc, "prev_month").click();
    expect([header(doc), sideDay(doc)]).toEqual(["October 2026", "October 12, 2026"]);
    (cellOf(doc, "2026-10-11").querySelector(".b-month-day-cell") as HTMLElement).click();
    expect(sideDay(doc)).toBe("October 12, 2026");
    (cellOf(doc, "2026-10-20").querySelector(".b-month-day-cell") as HTMLElement).click();
    expect(sideDay(doc)).toBe("October 20, 2026");
    btn(doc, "next_day_sidebar").click();
    expect(sideDay(doc)).toBe("October 21, 2026");
    btn(doc, "prev_day_sidebar").click();
    expect(sideDay(doc)).toBe("October 20, 2026");
    expect(changes).toHaveBeenCalledTimes(6);
    const tabs = [...doc.querySelectorAll<HTMLElement>(".g-page__subheader .b-tabs__nav__link")];
    tabs[1].click();
    tabs[2].click();
    expect(tabs.map((t) => t.classList.contains("m-current"))).toEqual([false, true, true]);
    tabs[1].click();
    expect(tabs.map((t) => t.classList.contains("m-current"))).toEqual([false, false, true]);
    expect(changes).toHaveBeenCalledTimes(9);
  });

  it("bindCalendar: a tab captured selected loses and regains its check mark", () => {
    const doc = load("queue/state-tab-messages");
    unbinds.push(bindCalendar(doc, TODAY, () => TODAY));
    const tab = doc.querySelectorAll<HTMLElement>(".g-page__subheader .b-tabs__nav__link")[1];
    expect(tab.querySelector(".b-tabs__nav__icon")).not.toBeNull();
    tab.click();
    expect(tab.querySelector(".b-tabs__nav__icon")).toBeNull();
    tab.click();
    expect(tab.querySelector(".b-tabs__nav__icon")).not.toBeNull();
  });
});

/** OF's own /api2/v2 queue responses, read through the Relay on 2026-10-17 and scrubbed (app/lib/__fixtures__/of). */
const fixture = <T,>(name: string): T => JSON.parse(readFileSync(resolve(__dirname, `__fixtures__/of/queue-${name}.json`), "utf8")) as T;
type Schedules = { list: QueueItem[]; syncInProcess: boolean };
// October: nothing scheduled. November: one post on the 26th, 02:14 UTC (03:14 in Ljubljana, CET).
const OCT = fixture<Schedules>("schedules-2026-10");
const NOV = fixture<Schedules>("schedules-2026-11");
// /schedules/counters for the same months: an empty month is OF's empty array, not an object.
const COUNTERS_OCT = fixture<{ list: Record<string, Record<string, number>> | [] }>("counters-2026-10");
const COUNTERS_NOV = fixture<{ list: Record<string, Record<string, number>> | [] }>("counters-2026-11");
const ZONE = "Europe/Ljubljana";

describe("the queue with OF's captured responses", () => {
  const TODAY = new Date(2026, 9, 17, 12, 0);
  const bars = (doc: Document) =>
    [...doc.querySelectorAll<HTMLElement>(".v-calendar-monthly .v-event[data-oi-data]")].map((b) => [b.dataset.date, b.classList.contains("post"), b.textContent]);
  const side = (doc: Document) =>
    [...doc.querySelectorAll<HTMLElement>(".l-wrapper__sidebar .b-agenda__area-events__item")].map((a) => [
      a.classList.contains("post-indicator"),
      a.querySelector(".b-agenda__area-events__item-details")!.textContent,
      a.querySelector(".b-agenda__area-events__item-inward")!.textContent,
    ]);
  const sideEmpty = (doc: Document) => (doc.querySelector<HTMLElement>(".l-wrapper__sidebar > .empty-message")!.getAttribute("style") ?? "").includes("display:none");
  const monthPage = (page: string, day: Date, items: QueueItem[], zone = ZONE) => {
    const doc = load(page);
    drawQueue(doc, day, TODAY);
    applyData(doc, page, { queue: items, templates: { agenda: AGENDA_TPL }, zone });
    return doc;
  };

  it("the days the calendar marks are OF's own counters for the month", () => {
    expect(dayCounts(NOV.list, ZONE)).toEqual(COUNTERS_NOV.list);
    expect(COUNTERS_OCT.list).toEqual([]);
    expect(dayCounts(OCT.list, ZONE)).toEqual({});
  });

  it("an empty month (October): no bar on any day, the right column's empty state, the page as captured", () => {
    const doc = load("queue/index");
    drawQueue(doc, TODAY, TODAY);
    const html = doc.documentElement.innerHTML;
    applyData(doc, "queue/index", { queue: OCT.list, templates: { agenda: AGENDA_TPL }, zone: ZONE });
    expect(bars(doc)).toEqual([]);
    expect(sideEmpty(doc)).toBe(false);
    expect(doc.documentElement.innerHTML).toBe(html);
  });

  it("November on the 26th: the day's bar, and the right column lists the post at 3:14 am with its More menu", () => {
    const doc = monthPage("queue/index", new Date(2026, 10, 26), NOV.list);
    expect(bars(doc)).toEqual([["2026-11-26", true, "1"]]);
    expect(side(doc)).toEqual([[true, "3:14 am", "Synthetic scheduled post 1"]]);
    expect(sideEmpty(doc)).toBe(true);
    const row = doc.querySelector<HTMLElement>(".l-wrapper__sidebar .b-agenda__area-events__item")!;
    expect(row.dataset).toMatchObject({ oiQueueKind: "post", oiQueueTarget: "2433845504", oiQueueSchedule: "1457214731", oiQueueReady: "true" });
    // Nothing under the calendar (OF lists the month only in its list view).
    expect(doc.querySelector(".v-calendar")!.nextElementSibling).toBeNull();
  });

  it("another day of November: the bar stays, the right column keeps its empty state", () => {
    const doc = monthPage("queue/index", new Date(2026, 10, 1), NOV.list);
    expect(bars(doc)).toEqual([["2026-11-26", true, "1"]]);
    expect(side(doc)).toEqual([]);
    expect(sideEmpty(doc)).toBe(false);
  });

  it("the filters: Posts keeps the post; Messages, and Messages with Streams, drop it", () => {
    const doc = load("queue/index");
    drawQueue(doc, new Date(2026, 10, 26), TODAY);
    const posts = [...doc.querySelectorAll(".g-page__subheader .b-tabs__nav__link")].find((t) => t.textContent!.trim() === "Posts")!;
    posts.classList.add("m-current");
    applyData(doc, "queue/index", { queue: NOV.list, templates: { agenda: AGENDA_TPL }, zone: ZONE });
    expect(bars(doc)).toEqual([["2026-11-26", true, "1"]]);
    for (const page of ["queue/state-tab-messages", "queue/state-tab-streams"]) {
      const d = monthPage(page, new Date(2026, 10, 26), NOV.list);
      expect([bars(d), side(d)]).toEqual([[], []]);
    }
  });

  it("the list view: November's post in its own agenda block under its day", () => {
    const doc = monthPage("queue/state-list-view", new Date(2026, 10, 26), NOV.list);
    const sections = [...doc.querySelectorAll(".b-agenda.m-main-block .b-agenda__section")].map((s) => [
      s.querySelector(".b-agenda__section-date")!.textContent,
      [...s.querySelectorAll(".b-agenda__area-events__item-inward")].map((e) => e.textContent),
    ]);
    expect(sections).toEqual([["Nov 26", ["Synthetic scheduled post 1"]]]);
    expect(bars(doc)).toEqual([]);
  });

  it("the Agency's time zone sets the item's day and time: Los Angeles reads it on Nov 25 at 6:14 pm", () => {
    const doc = monthPage("queue/index", new Date(2026, 10, 25), NOV.list, "America/Los_Angeles");
    expect(bars(doc)).toEqual([["2026-11-25", true, "1"]]);
    expect(side(doc)).toEqual([[true, "6:14 pm", "Synthetic scheduled post 1"]]);
  });

  it("today is the Agency's time zone's: 22:30 UTC on Oct 16 is Oct 17 in Ljubljana and Oct 16 in New York", () => {
    const at = new Date("2026-10-16T22:30:00Z");
    expect(ymd(wallClock(at, ZONE))).toBe("2026-10-17");
    expect(ymd(wallClock(at, "America/New_York"))).toBe("2026-10-16");
    expect(wallClock(at, "Not/AZone")).toBe(at);
    const doc = load("queue/index");
    const today = wallClock(at, ZONE);
    drawQueue(doc, queueStart(null, today), today);
    const present = doc.querySelector(".v-calendar-weekly__day.v-present .b-month-day-cell__value")!;
    expect(present.getAttribute("at-attr")).toBe("date:2026-10-17");
    expect(present.closest(".b-month-day-cell")!.classList.contains("selected")).toBe(true);
    expect(doc.querySelector(".l-wrapper__sidebar .b-queue-header__date")!.textContent).toBe("October 17, 2026");
  });

  it("All models: the Queue's pages show the first model; a model selected shows its own", () => {
    const accounts = [{ id: "80000112" }, { id: "2" }];
    for (const p of ["index", "state-list-view", "state-tab-messages", "saved-for-later-posts"]) expect(standInModel(`/of-mirror/pages/queue/${p}.html`, null, accounts)).toBe("80000112");
    expect(standInModel("/of-mirror/pages/queue/index.html", "2", accounts)).toBeNull();
    expect(standInModel("/of-mirror/pages/queue/index.html", null, [])).toBeNull();
  });
});

describe("Add to queue (the \"+\": OF's NEW_SCHEDULED_EVENT modal)", () => {
  const unbinds: (() => void)[] = [];
  afterEach(() => {
    while (unbinds.length) unbinds.pop()!();
  });
  // 12:00 in Ljubljana on Oct 12, 2026 (the queue capture's today).
  const NOW = new Date("2026-10-12T10:00:00Z");
  const bound = (page: string, h: QueueHandlers | null, now = NOW) => {
    const doc = load(page);
    unbinds.push(bindQueue(doc, h, ZONE, () => now));
    return doc;
  };
  const modal = (doc: Document) => doc.getElementById("newScheduleEventModal");
  const tabs = (doc: Document) => [...modal(doc)!.querySelectorAll<HTMLButtonElement>("[data-oi-tab]")].map((b) => [b.textContent!.trim(), b.classList.contains("m-current")]);
  const types = (doc: Document) => [...modal(doc)!.querySelectorAll<HTMLButtonElement>(".modal-body button[at-attr]")].map((b) => [b.getAttribute("at-attr"), b.textContent!.trim()]);
  const field = (doc: Document, t: "date" | "time") => modal(doc)!.querySelector<HTMLInputElement>(`input[at-attr='${t}_input']`)!;
  const memory = (): Storage => {
    const m = new Map<string, string>();
    return { get length() { return m.size; }, key: (i) => [...m.keys()][i] ?? null, getItem: (k) => m.get(k) ?? null, setItem: (k, v) => void m.set(k, String(v)), removeItem: (k) => void m.delete(k), clear: () => m.clear() };
  };

  it("the generator wires every \"+\": the queue pages', the saved-for-later pages' and the Scheduled events widget's on New post and Go live", () => {
    for (const page of ["queue/index", "queue/state-list-view", "queue/state-tab-messages", "queue/state-tab-streams"]) {
      const doc = load(page);
      const plus = [...doc.querySelectorAll<HTMLButtonElement>("[at-attr^='add_event_']")];
      expect(plus.length, page).toBeGreaterThan(0);
      for (const b of plus) expect([b.disabled, b.title, b.hasAttribute("data-oi-wired")], `${page} ${b.getAttribute("at-attr")}`).toEqual([false, "", true]);
    }
    for (const page of ["queue/saved-for-later-posts", "queue/saved-for-later-messages"]) {
      const plus = [...load(page).querySelectorAll<HTMLButtonElement>("[data-oi-add]")];
      expect(plus.map((b) => [b.disabled, b.title, b.hasAttribute("data-oi-wired")]), page).toEqual([
        [false, "", true],
        [false, "", true],
      ]);
    }
    for (const page of ["new-post/index", "new-post/state-schedule", "streaming/dashboard/create"]) {
      const w = load(page).querySelector<HTMLButtonElement>("[at-attr='add_event_widget']")!;
      expect([w.tagName, w.disabled, w.title, w.hasAttribute("data-oi-wired"), w.getAttribute("aria-label")], page).toEqual(["BUTTON", false, "", true, ADD_TITLE]);
    }
  });

  it.each(["add_event_header", "add_event_sidebar"])("%s opens the modal: OF's title, tabs, date and time and types; Cancel closes it", (at) => {
    const doc = bound("queue/index", handlers());
    doc.querySelector<HTMLElement>(`[at-attr='${at}']`)!.click();
    expect(modal(doc)!.querySelector(".modal-title")!.textContent!.trim()).toBe(ADD_TITLE);
    expect(tabs(doc)).toEqual(ADD_TABS.map((t, i) => [t.text, i === 0]));
    expect(modal(doc)!.querySelector(".g-input__help")!.textContent!.trim()).toBe(ADD_HELP.scheduled);
    // The shown day (the capture's Oct 12) at the Agency zone's time ten minutes from now.
    expect([field(doc, "date").value, field(doc, "time").value]).toEqual(["Oct 12, 2026", "12:10"]);
    expect(types(doc)).toEqual(ADD_MENU.map((e) => [e.atAttr, e.title]));
    expect(modal(doc)!.querySelector(".modal-backdrop")).not.toBeNull();
    const cancel = modal(doc)!.querySelector<HTMLButtonElement>(".modal-footer button")!;
    expect(cancel.textContent!.trim()).toBe("Cancel");
    cancel.click();
    expect(modal(doc)).toBeNull();
  });

  it("a type opens its composer on the picked day and time, read in the Agency's zone", () => {
    const h = handlers();
    const doc = bound("queue/index", h);
    for (const kind of ["post", "message", "stream"] as const) {
      doc.querySelector<HTMLElement>("[at-attr='add_event_header']")!.click();
      field(doc, "date").value = "2026-10-21";
      field(doc, "time").value = "18:30";
      modal(doc)!.querySelector<HTMLButtonElement>(`[at-attr='add_${kind}']`)!.click();
      expect(modal(doc)).toBeNull();
    }
    // 18:30 in Ljubljana (CEST) is 16:30 UTC.
    expect(h.create.mock.calls.map(([k, d]) => [k, d.toISOString()])).toEqual([
      ["post", "2026-10-21T16:30:00.000Z"],
      ["message", "2026-10-21T16:30:00.000Z"],
      ["stream", "2026-10-21T16:30:00.000Z"],
    ]);
  });

  it("the date opens OF's day popup from today on: an earlier day is greyed and not taken, Apply sets the field, Escape closes only the popup", () => {
    const h = handlers();
    const doc = bound("queue/index", h);
    doc.querySelector<HTMLElement>("[at-attr='add_event_header']")!.click();
    expect([field(doc, "date").type, field(doc, "date").readOnly]).toEqual(["text", true]);
    field(doc, "date").click();
    const popup = () => doc.querySelector<HTMLElement>("[data-oi-picker] .vdatetime-popup");
    const day = (iso: string) => doc.querySelector<HTMLElement>(`[data-oi-picker] [data-oi-day='${iso}']`)!;
    expect(popup()!.querySelector(".vdatetime-popup__title")!.textContent!.trim()).toBe("Oct 12, 2026");
    expect(popup()!.querySelector(".vdatetime-popup__tabs")).toBeNull();
    expect(popup()!.querySelector<HTMLButtonElement>("[data-oi-month='prev']")!.disabled).toBe(true);
    expect(popup()!.querySelector<HTMLButtonElement>("[data-oi-month='next']")!.disabled).toBe(false);
    expect(day("2026-10-11").querySelector("span")!.className).toBe("vc-disabled");
    day("2026-10-11").click();
    expect(popup()!.querySelector(".vdatetime-popup__title")!.textContent!.trim()).toBe("Oct 12, 2026");
    day("2026-10-21").click();
    expect(popup()!.querySelector(".vdatetime-popup__title")!.textContent!.trim()).toBe("Oct 21, 2026");
    popup()!.querySelector<HTMLButtonElement>("[data-oi-picker-apply]")!.click();
    expect(popup()).toBeNull();
    expect(field(doc, "date").value).toBe("Oct 21, 2026");
    field(doc, "date").click();
    doc.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    expect([popup(), !!modal(doc)]).toEqual([null, true]);
    field(doc, "time").value = "18:30";
    modal(doc)!.querySelector<HTMLButtonElement>("[at-attr='add_post']")!.click();
    expect(h.create.mock.calls.map(([k, d]) => [k, d.toISOString()])).toEqual([["post", "2026-10-21T16:30:00.000Z"]]);
  });

  it("a past moment keeps the modal open with the note and opens nothing", () => {
    const h = handlers();
    const doc = bound("queue/index", h);
    doc.querySelector<HTMLElement>("[at-attr='add_event_header']")!.click();
    field(doc, "time").value = "11:00";
    modal(doc)!.querySelector<HTMLButtonElement>("[at-attr='add_post']")!.click();
    expect(modal(doc)).not.toBeNull();
    expect(noteText(doc)).toBe(TOO_SOON);
    expect(h.create).not.toHaveBeenCalled();
  });

  it("Save for later: its tab lists Post and Mass message, each opening its composer saving for later", () => {
    const h = handlers();
    const doc = bound("queue/index", h);
    doc.querySelector<HTMLElement>("[at-attr='add_event_header']")!.click();
    modal(doc)!.querySelector<HTMLButtonElement>("[data-oi-tab='later']")!.click();
    expect(tabs(doc)).toEqual(ADD_TABS.map((t, i) => [t.text, i === 1]));
    expect(modal(doc)!.querySelector("input[at-attr='date_input']")).toBeNull();
    expect(modal(doc)!.querySelector(".g-input__help")!.textContent!.trim()).toBe(ADD_HELP.later);
    expect(types(doc)).toEqual(LATER_MENU.map((e) => [e.atAttr, e.title]));
    modal(doc)!.querySelector<HTMLButtonElement>("[at-attr='later_message']")!.click();
    expect(h.later.mock.calls).toEqual([["message"]]);
    expect(h.create).not.toHaveBeenCalled();
  });

  it("a saved-for-later page's \"+\" opens the modal on Save for later", () => {
    for (const page of ["queue/saved-for-later-posts", "queue/saved-for-later-messages"]) {
      const doc = bound(page, handlers());
      for (const plus of [...doc.querySelectorAll<HTMLElement>("[data-oi-add]")]) {
        plus.click();
        expect(tabs(doc).find(([, on]) => on)?.[0], page).toBe(ADD_TABS[1].text);
        modal(doc)!.querySelector<HTMLButtonElement>(".modal-footer button")!.click();
      }
    }
  });

  it("the Scheduled events widget's \"+\" on New post and Go live opens the same modal, on today", () => {
    for (const page of ["new-post/index", "streaming/dashboard/create"]) {
      const h = handlers();
      const doc = bound(page, h);
      doc.querySelector<HTMLElement>("[at-attr='add_event_widget']")!.click();
      expect(field(doc, "date").value, page).toBe("Oct 12, 2026");
      modal(doc)!.querySelector<HTMLButtonElement>("[at-attr='add_message']")!.click();
      expect(h.create.mock.calls[0][0]).toBe("message");
    }
  });

  it("no single model: \"+\" asks for a model and opens nothing", () => {
    const doc = bound("queue/index", null);
    doc.querySelector<HTMLElement>("[at-attr='add_event_header']")!.click();
    expect(modal(doc)).toBeNull();
    expect(noteText(doc)).toBe(SELECT_MODEL);
  });

  it("with bindWrites bound too, the modal's buttons never get the read-only fallback note", () => {
    const doc = bound("queue/index", handlers());
    unbinds.push(bindWrites(doc, "queue/index", null));
    doc.querySelector<HTMLElement>("[at-attr='add_event_header']")!.click();
    const time = field(doc, "time");
    time.value = "18:30";
    time.dispatchEvent(new Event("change", { bubbles: true }));
    expect(noteText(doc)).toBeUndefined();
    modal(doc)!.querySelector<HTMLButtonElement>("[data-oi-tab='later']")!.click();
    expect(noteText(doc)).toBeUndefined();
  });

  it("createAt: a later day at its midnight in the Agency's zone, as the live modal opens; today ten minutes from now (OF's default)", () => {
    const now = new Date("2026-10-17T10:00:00Z"); // 12:00 in Ljubljana
    expect(createAt("2026-10-21", "Europe/Ljubljana", now).toISOString()).toBe("2026-10-20T22:00:00.000Z");
    expect(createAt("2026-10-21", "America/Los_Angeles", now).toISOString()).toBe("2026-10-21T07:00:00.000Z");
    expect(createAt("2026-10-17", "Europe/Ljubljana", now).toISOString()).toBe("2026-10-17T10:10:00.000Z");
    // 23:55 in Ljubljana: tomorrow's midnight is not ten minutes on, so ten minutes from now.
    const late = new Date("2026-10-17T21:55:00Z");
    expect(createAt("2026-10-18", "Europe/Ljubljana", late).toISOString()).toBe("2026-10-17T22:05:00.000Z");
    // Across the October DST change (Oct 25 in Europe): midnight of the 26th is UTC+1.
    expect(createAt("2026-10-26", "Europe/Ljubljana", now).toISOString()).toBe("2026-10-25T23:00:00.000Z");
    expect(fromWallClock(wallClock(now, "Asia/Tokyo"), "Asia/Tokyo").getTime()).toBe(now.getTime());
  });

  it("createHref: Post puts the moment on the Post draft and opens New post; Message on the Mass draft; Stream the form's ?date and ?time", () => {
    const storage = memory();
    const at = new Date(2026, 9, 21, 13, 15);
    storage.setItem("oi:new-post:acc1", JSON.stringify({ text: "Kept", save_for_later: true, edit_id: "9" }));
    expect(createHref("post", at, storage, "acc1")).toBe("/of-manager/new-post");
    expect(loadDraft(storage, "acc1")).toMatchObject({ text: "Kept", posted_at: localIso(at) });
    expect([loadDraft(storage, "acc1").save_for_later, loadDraft(storage, "acc1").edit_id]).toEqual([undefined, undefined]);
    storage.setItem("oi:mass:acc1", JSON.stringify({ text: "Hi", user_lists: ["fans"], save_for_later: true }));
    expect(createHref("message", at, storage, "acc1")).toBe("/of-manager/messages/send");
    expect(loadMassDraft(storage, "acc1")).toEqual({ text: "Hi", user_lists: ["fans"], scheduled_date: localIso(at) });
    expect(createHref("stream", at, storage, "acc1")).toBe("/of-manager/streaming/dashboard/create?date=2026-10-21&time=1%3A15%20pm");
  });

  it("laterHref: the composer's draft saves for later, its date dropped", () => {
    const storage = memory();
    storage.setItem("oi:new-post:acc1", JSON.stringify({ text: "Kept", posted_at: "2026-10-21T13:15:00+02:00" }));
    expect(laterHref("post", storage, "acc1")).toBe("/of-manager/new-post");
    expect(loadDraft(storage, "acc1")).toMatchObject({ text: "Kept", save_for_later: true });
    expect(loadDraft(storage, "acc1").posted_at).toBeUndefined();
    storage.setItem("oi:mass:acc1", JSON.stringify({ text: "Hi", user_lists: ["fans"], scheduled_date: "2026-10-21T13:15:00+02:00" }));
    expect(laterHref("message", storage, "acc1")).toBe("/of-manager/messages/send");
    expect(loadMassDraft(storage, "acc1")).toEqual({ text: "Hi", user_lists: ["fans"], save_for_later: true });
  });
});

/** OF's /schedules/later lists (captured: empty) and the guessed shapes of saved-for-later items (marked `_source: guess`). */
type Later = { _source: string; list: QueueItem[]; hasMore: boolean };
const SAVED_POSTS = fixture<Later>("saved-posts");
const SAVED_MESSAGES = fixture<Later>("saved-messages");
const SAVED_POST = fixture<Later>("saved-post-item");
const SAVED_MESSAGE = fixture<Later>("saved-message-item");
const SAVED_MONTH = fixture<Later>("saved-month");

describe("saved for later", () => {
  const unbinds: (() => void)[] = [];
  afterEach(() => {
    while (unbinds.length) unbinds.pop()!();
  });
  const page = (p: string, list: QueueItem[], h: QueueHandlers | null = handlers()) => {
    const doc = load(p);
    applyData(doc, p, { queue: list, templates: { agenda: AGENDA_TPL }, zone: ZONE });
    unbinds.push(bindQueue(doc, h, ZONE));
    return doc;
  };
  const shown = (doc: Document, sel: string) => [...doc.querySelectorAll<HTMLElement>(sel)].filter((e) => !(e.getAttribute("style") ?? "").includes("display:none") && !e.closest("[style*='display:none']"));

  it("the captured empty lists keep OF's empty state on both pages", () => {
    expect([SAVED_POSTS.list, SAVED_MESSAGES.list, SAVED_POSTS._source.startsWith("captured")]).toEqual([[], [], true]);
    for (const [p, list, text] of [
      ["queue/saved-for-later-posts", SAVED_POSTS.list, "There are no saved for later posts"],
      ["queue/saved-for-later-messages", SAVED_MESSAGES.list, "There are no saved for later messages"],
    ] as const) {
      const doc = page(p, list);
      expect(shown(doc, ".saved-for-later > .empty-message").map((e) => e.textContent!.trim()), p).toEqual([text]);
      expect(rows(doc)).toEqual([]);
    }
  });

  // A card's parts as the live page shows them: [date, "Later", "to <fan>", time, text].
  const card = (row: Element) => [
    row.querySelector(".m-date-case")!.textContent!.trim(),
    row.querySelector(".b-queue-post-info")!.textContent!.trim(),
    row.querySelector(".b-post__queue-cell__item")?.textContent!.trim() ?? null,
    row.querySelector(".m-time-passed")!.textContent!.trim(),
    row.querySelector(".b-post__text")!.textContent!.trim(),
  ];

  it("a saved post (captured live) shows as OF's card with its row menu; Edit post opens its composer", async () => {
    expect(SAVED_POST._source.startsWith("captured")).toBe(true);
    const h = handlers();
    const doc = page("queue/saved-for-later-posts", SAVED_POST.list, h);
    const [row] = rows(doc);
    expect(row.matches(".b-post.m-queue-post.m-save-later.sfl-post[data-v-48bf68d0]")).toBe(true);
    // 17:26 UTC is 7:26 pm in Ljubljana (CEST), with OF's star.
    expect(card(row)).toEqual(["Oct 17, 2026", "Later", null, "7:26* pm", "Synthetic saved post"]);
    expect(row.querySelector("svg[data-icon-name='icon-saved-for-later-posts']")).not.toBeNull();
    expect(row.querySelector<HTMLButtonElement>(".b-post__labels-controls button")!.disabled).toBe(true);
    more(row).click();
    expect(entries(doc)).toEqual([
      ["pin_to_profile", "Pin to your profile page", false],
      ["edit_post", "Edit post", false],
      ["publish_now", "Publish now", false],
      ["delete_post", "Delete post", false],
    ]);
    entry(doc, "edit_post").click();
    await flush();
    expect(h.edit.mock.calls).toEqual([["post", "2824438622"]]);
  });

  it("a saved message (captured live): OF's card naming its fan; Send message right now publishes its schedule id after the confirm; Delete removes the queued message", async () => {
    const h = handlers();
    const doc = page("queue/saved-for-later-messages", SAVED_MESSAGE.list, h);
    const [row] = rows(doc);
    expect(row.matches(".b-post.m-queue-post.sfl-message")).toBe(true);
    expect(card(row)).toEqual(["Oct 17, 2026", "Later", "to synthfan", "7:33* pm", "Synthetic saved message"]);
    expect(shown(doc, ".saved-for-later > .empty-message")).toEqual([]);
    more(row).click();
    entry(doc, "message_now").click();
    expect(h.confirm).toHaveBeenLastCalledWith(CONFIRM_PUBLISH.chat);
    await flush();
    more(row).click();
    entry(doc, "delete_message").click();
    expect(h.confirm).toHaveBeenLastCalledWith(CONFIRM_DELETE.chat);
    await flush();
    expect([h.publish.mock.calls, h.remove.mock.calls]).toEqual([[["1767135015"]], [["chat", "48844862425"]]]);
  });

  it("dayBars: OF's counters into calendar events (app.js `R`): a day with both kinds is one half-tinted bar of their sum", () => {
    expect(dayBars({ post: 1, saved_for_later_post: 2 })).toEqual([{ type: "posts", name: "3", value: "33" }]);
    expect(dayBars({ chat: 2, saved_for_later_chat: 2, stream: 1 })).toEqual([{ type: "chats", name: "4", value: "50" }, { type: "stream", name: "1" }]);
    expect(dayBars({ saved_for_later_post: 2 })).toEqual([{ type: "sfl-post", name: "2" }]);
    expect(dayBars({ post: 1 })).toEqual([{ type: "post", name: "1" }]);
  });

  // Not seen live: OF lists a saved-for-later item on a month only once its auto-publishing gives it a date (that switch
  // stays off on the sandbox), so this month is the guessed shape (queue-saved-month.json) and OF's app.js rule.
  it("a month with saved-for-later items: half-tinted day bars with the scheduled part's width, sfl marks and starred times", () => {
    const doc = load("queue/index");
    drawQueue(doc, new Date(2026, 10, 3), new Date(2026, 9, 17));
    applyData(doc, "queue/index", { queue: SAVED_MONTH.list, templates: { agenda: AGENDA_TPL }, zone: ZONE });
    const bars = [...doc.querySelectorAll<HTMLElement>(".v-calendar-monthly .v-event[data-oi-data]")].map((b) => [
      b.dataset.date,
      b.className.replace("v-event v-event-start v-event-end ", "").replace(" white--text", ""),
      b.querySelector(".v-event-summary")!.firstChild!.textContent!.trim(),
      b.querySelector<HTMLElement>(".v-event-summary__level")?.style.width ?? null,
    ]);
    expect(bars).toEqual([
      ["2026-11-03", "posts", "3", "33%"],
      ["2026-11-05", "sfl-chat", "1", null],
      ["2026-11-06", "chat", "1", null],
    ]);
    const side = [...doc.querySelectorAll<HTMLElement>(".l-wrapper__sidebar .b-agenda__area-events__item")].map((a) => [a.className.split(" ").find((c) => c.endsWith("-indicator")), a.querySelector(".b-agenda__area-events__item-details")!.textContent]);
    expect(side).toEqual([
      ["post-indicator", "9:00 am"],
      ["sfl-post-indicator", "1:00* pm"],
      ["sfl-post-indicator", "4:00* pm"],
    ]);
  });
});

describe("Edit: the composer's draft filled from the item", () => {
  it("Edit post: OF's captured GET /posts/{id} fills the Post draft: its text, schedule in place, and the id to save", () => {
    const post = fixture<EditablePost & { _source: string }>("edit-post");
    expect(post._source.startsWith("captured")).toBe(true);
    expect(postEditDraft(post)).toEqual({
      text: "Synthetic scheduled post 1",
      tagged_users: [],
      media_files: [],
      thumbs: [],
      posted_at: localIso(new Date("2026-11-26T02:14:00+00:00")),
      edit_id: "2433845504",
    });
  });

  it("Edit post of the captured saved-for-later post (given media, a price and labels): media ids, their pictures through `img`, saved for later", () => {
    const entity = SAVED_POST.list[0].entity as unknown as EditablePost;
    const media = [{ id: 8001, type: "photo", files: { thumb: { url: "https://cdn2.onlyfans.com/files/a/a1/a1synthetic/300x300_synthetic1.jpg" } } }] as EditablePost["media"];
    const d = postEditDraft({ ...entity, media, price: 5, labelStates: [{ id: 3, isAdded: true }, { id: "archive", isAdded: true }] }, (u) => `/img?u=${encodeURIComponent(u)}`);
    expect(d).toMatchObject({ text: "Synthetic saved post", media_files: [8001], price: 5, label_ids: [3], save_for_later: true, edit_id: "2824438622" });
    expect(d.thumbs[0]).toMatch(/^\/img\?u=https/);
    expect(d.posted_at).toBeUndefined();
  });

  it("Edit message: OF's captured GET /messages/queue/{id}?format=scheduled (a message to one fan) fills the Mass draft; lists and the rest too", () => {
    const msg = fixture<QueuedMessage & { _source: string }>("edit-message");
    expect(msg._source.startsWith("captured")).toBe(true);
    expect(messageEditDraft(msg)).toEqual({
      text: "Synthetic scheduled message",
      user_lists: [],
      user_ids: [5001],
      scheduled_date: localIso(new Date("2026-12-15T11:00:00+00:00")),
      edit_id: "48844793592",
    });
    // A message to lists, with lists left out, media and a price (the same fields OF's ChatsSend reads).
    const media = [{ id: 8105, type: "photo" }] as QueuedMessage["media"];
    expect(messageEditDraft({ ...msg, userIds: [], userLists: ["fans", 1234], excludedLists: [99], media, price: 5 })).toMatchObject({
      user_lists: ["fans", "1234"],
      excluded_user_lists: ["99"],
      media_files: [8105],
      price: 5,
    });
    expect(messageEditDraft({ id: 6002, text: "<p>Later</p>", scheduledAt: null, userLists: ["fans"] })).toEqual({ text: "Later", user_lists: ["fans"], save_for_later: true, edit_id: "6002" });
  });
});

describe("a scheduled message on the calendar (captured live)", () => {
  it("its day gets OF's chat bar, its entity's scheduledAt keeps it a scheduled (not saved-for-later) message", () => {
    const day = fixture<{ _source: string; list: QueueItem[] }>("schedules-message-day");
    expect(day._source.startsWith("captured")).toBe(true);
    expect(dayCounts(day.list, ZONE)).toEqual({ "2026-12-15": { chat: 1 } });
    const doc = load("queue/index");
    drawQueue(doc, new Date(2026, 11, 15), new Date(2026, 9, 17));
    applyData(doc, "queue/index", { queue: day.list, templates: { agenda: AGENDA_TPL }, zone: ZONE });
    const bar = doc.querySelector<HTMLElement>(".v-calendar-monthly .v-event[data-oi-data]")!;
    // OF's live markup: "v-event v-event-start v-event-end chat white--text", its count as the name.
    expect([bar.dataset.date, bar.className, bar.textContent]).toEqual(["2026-12-15", "v-event v-event-start v-event-end chat white--text", "1"]);
    const side = [...doc.querySelectorAll<HTMLElement>(".l-wrapper__sidebar .b-agenda__area-events__item")].map((a) => [a.dataset.oiQueueKind, a.dataset.oiQueueTarget, a.querySelector(".b-agenda__area-events__item-details")!.textContent]);
    expect(side).toEqual([["chat", "48844793592", "12:00 pm"]]);
  });
});
