import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { applyData } from "./ofMirrorData";
import { queueDay, queueMonth, queueTypes } from "./ofMirrorFeedsSchedule";
import { TEMPLATES, type QueueItem } from "./ofMirrorFeedsShared";
import { capture, load, shown, texts } from "./ofMirrorData.fixtures";

describe("queueMonth", () => {
  it("reads the month the calendar shows from the captured header", () => {
    expect(queueMonth(load("queue/index"))).toEqual({ start: "2026-10-01", end: "2026-10-31" });
    expect(queueMonth(load("queue/state-list-view"))).toEqual({ start: "2026-10-01", end: "2026-10-31" });
  });

  it("a page with no month header gives none", () => {
    expect(queueMonth(load("queue/saved-for-later-posts"))).toBeNull();
  });
});

describe("queueTypes and queueDay", () => {
  it("the selected tabs' item types: none on the calendar, chat on Messages, chat and stream on Streams", () => {
    expect(queueTypes(load("queue/index"))).toEqual([]);
    expect(queueTypes(load("queue/state-list-view"))).toEqual([]);
    expect(queueTypes(load("queue/state-tab-messages"))).toEqual(["chat"]);
    expect(queueTypes(load("queue/state-tab-streams"))).toEqual(["chat", "stream"]);
  });

  it("the right column's day, and none without one", () => {
    expect(queueDay(load("queue/index"))).toBe("2026-10-12");
    expect(queueDay(load("queue/saved-for-later-posts"))).toBeNull();
  });
});

// The `agenda` template as useOfData borrows it: the list view's capture, parsed inertly.
const AGENDA_TPL = TEMPLATES.agenda!.pick(new DOMParser().parseFromString(capture(TEMPLATES.agenda!.page), "text/html"))!;
// OF's own /schedules item (app/lib/__fixtures__/of, captured through the Relay and scrubbed): the others take its shape.
const REAL = (JSON.parse(readFileSync(resolve(__dirname, "__fixtures__/of/queue-schedules-2026-11.json"), "utf8")) as { list: QueueItem[] }).list[0];
/**
 * OF's item with another type, time (local, no offset: the days and times read the same in every time zone) and entity.
 * A scheduled message's entity has its send time (`scheduledAt`; one without is saved for later, OF's isSFLMessage).
 */
const scheduled = (type: string, publishDateTime: string, entity: QueueItem["entity"]): QueueItem => ({
  ...REAL,
  type,
  publishDateTime,
  entity: { ...REAL.entity, text: null, ...(type === "chat" ? { scheduledAt: publishDateTime } : {}), ...entity },
});
// Not in order, as no order is promised.
const SCHEDULES: QueueItem[] = [
  scheduled("chat", "2026-10-14T18:30:00", { text: "<p>Alpha One chat</p>" }),
  scheduled("post", "2026-10-12T09:05:00", { text: "Alpha Two <b>post</b>" }),
  scheduled("post", "2026-10-14T08:00:00", { text: "", mediaCount: 2 }),
  scheduled("chat", "2026-10-12T21:00:00", {}),
];
// [day label, [[indicator, time, text] per item]] per section, soonest first.
const WANT_SCHEDULES = [
  ["Oct 12", [["post-indicator", "9:05 am", "Alpha Two post"], ["chat-indicator", "9:00 pm", ""]]],
  ["Oct 14", [["post-indicator", "8:00 am", "Media"], ["chat-indicator", "6:30 pm", "Alpha One chat"]]],
];
const AGENDA = ".b-agenda";
const sections = (doc: Document) =>
  shown(doc, ".b-agenda__section").map((s) => [
    s.querySelector(".b-agenda__section-date")!.textContent,
    [...s.querySelectorAll("a.b-agenda__area-events__item")].map((a) => [
      [...a.classList].filter((c) => c.endsWith("-indicator")).join(" "),
      a.querySelector(".b-agenda__area-events__item-details")!.textContent,
      a.querySelector(".b-agenda__area-events__item-inward")!.textContent,
    ]),
  ]);
// [day, type, text] per event bar on the calendar's days.
const bars = (doc: Document) =>
  [...doc.querySelectorAll<HTMLElement>(".v-calendar-monthly .v-event[data-oi-data]")].map((b) => [b.dataset.date, [...b.classList].find((c) => ["post", "chat", "stream"].includes(c)), b.textContent]);
const WANT_BARS = [
  ["2026-10-12", "post", "1"],
  ["2026-10-12", "chat", "1"],
  ["2026-10-14", "post", "1"],
  ["2026-10-14", "chat", "1"],
];
const scopeOf = (el: Element) => el.getAttributeNames().filter((n) => n.startsWith("data-v-")).sort();
const QUEUE_PAGES = ["queue/index", "queue/state-list-view", "queue/state-tab-messages", "queue/state-tab-streams", "queue/saved-for-later-posts", "queue/saved-for-later-messages"];

describe("queue: the Creator's scheduled and saved-for-later items", () => {
  it("the agenda template is the list view's agenda block, its empty state removed", () => {
    expect(TEMPLATES.agenda!.page).toBe("queue/state-list-view");
    expect(AGENDA_TPL.matches(".b-queue-scroll-wrapper")).toBe(true);
    expect(AGENDA_TPL.querySelector(".b-agenda.m-main-block")).not.toBeNull();
    expect(AGENDA_TPL.querySelector(".empty-message")).toBeNull();
  });

  it("list view: the month's items in its own agenda block, by local day soonest first, in OF's agenda classes and scope", () => {
    const doc = load("queue/state-list-view");
    applyData(doc, "queue/state-list-view", { queue: SCHEDULES });
    expect(sections(doc)).toEqual(WANT_SCHEDULES);
    expect(texts(doc, `${AGENDA} > .empty-message`)).toEqual([]);
    // One outside the right column (whose day's list is its own block).
    expect([...doc.querySelectorAll(".b-agenda")].filter((a) => !a.closest(".l-wrapper__sidebar"))).toHaveLength(1);
    const agenda = doc.querySelector(".b-agenda")!;
    // The More buttons' icons are SVG, outside the scope.
    const built = [...agenda.querySelectorAll(".b-agenda__section, .b-agenda__section *")].filter((el) => !el.closest("svg"));
    expect(built.every((el) => scopeOf(el).join() === scopeOf(agenda).join())).toBe(true);
    expect(scopeOf(agenda)).toEqual(["data-v-13609a39", "data-v-f602563e"]);
    expect(doc.querySelector(".b-queue-scroll-wrapper")!.classList.contains("m-empty-content")).toBe(false);
    // OF's items carry their ids: each row its More menu.
    expect(agenda.querySelectorAll(".b-post__tools__more [aria-label='More']")).toHaveLength(4);
  });

  it.each(["queue/index", "queue/state-tab-messages"])("%s: the calendar marks the days with OF's event bars and counts; nothing under it", (p) => {
    const doc = load(p);
    const html = doc.documentElement.innerHTML;
    applyData(doc, p, { queue: [] });
    expect(doc.documentElement.innerHTML).toBe(html);
    const items: QueueItem[] = p === "queue/index" ? SCHEDULES : [scheduled("chat", "2026-10-20T07:15:00", { text: "Queued hello" }), scheduled("chat", "2026-10-20T09:15:00", { text: "Queued again" })];
    applyData(doc, p, { queue: items, templates: { agenda: AGENDA_TPL } });
    expect(bars(doc)).toEqual(p === "queue/index" ? WANT_BARS : [["2026-10-20", "chat", "2"]]);
    // OF's month view lists nothing under its calendar.
    expect(doc.querySelector(".v-calendar")!.nextElementSibling).toBeNull();
    expect(doc.querySelector(".b-queue-scroll-wrapper")).toBeNull();
    // The bars sit in their day's cell, after its label, in OF's calendar scope.
    const bar = doc.querySelector(".v-event[data-oi-data]")!;
    expect(bar.previousElementSibling!.matches(".v-calendar-weekly__day-label")).toBe(true);
    expect(bar.closest(".v-calendar[data-v-13609a39]")).not.toBeNull();
    applyData(doc, p, {});
    expect(doc.documentElement.innerHTML).toBe(html);
  });

  it("Messages tab: only the month's messages are counted; a post, one outside the month or undated is not", () => {
    const doc = load("queue/state-tab-messages");
    const queue: QueueItem[] = [
      scheduled("chat", "2026-11-01T00:30:00", { text: "November" }),
      scheduled("chat", "2026-10-31T23:30:00", { text: "Last evening" }),
      scheduled("chat", "2026-09-30T23:59:00", { text: "September" }),
      { ...scheduled("chat", "", { text: "Undated" }), publishDateTime: undefined },
      scheduled("post", "2026-10-15T10:00:00", { text: "A post" }),
      scheduled("chat", "2026-10-01T00:10:00", { text: "", mediaCount: 1 }),
    ];
    applyData(doc, "queue/state-tab-messages", { queue, templates: { agenda: AGENDA_TPL } });
    expect(bars(doc)).toEqual([
      ["2026-10-01", "chat", "1"],
      ["2026-10-31", "chat", "1"],
    ]);
  });

  it("Messages tab: no item in the month marks no day", () => {
    const doc = load("queue/state-tab-messages");
    const html = doc.documentElement.innerHTML;
    applyData(doc, "queue/state-tab-messages", { queue: [scheduled("chat", "2026-11-02T10:00:00", { text: "November" }), SCHEDULES[1]], templates: { agenda: AGENDA_TPL } });
    expect(doc.documentElement.innerHTML).toBe(html);
  });

  it.each([
    ["queue/saved-for-later-posts", "sfl-post-indicator", "There are no saved for later posts"],
    ["queue/saved-for-later-messages", "sfl-chat-indicator", "There are no saved for later messages"],
  ])("%s: saved items as OF's cards in place of the empty state; an empty list keeps it", (p, mark, empty) => {
    const doc = load(p);
    applyData(doc, p, { queue: [], templates: { agenda: AGENDA_TPL } });
    expect(texts(doc, ".saved-for-later > .empty-message")).toEqual([empty]);
    expect(shown(doc, ".b-post.m-queue-post")).toEqual([]);
    applyData(doc, p, { queue: [{ text: "<p>Saved Alpha</p>" }, { text: null, mediaCount: 3 }, { text: "" }], templates: { agenda: AGENDA_TPL } });
    // OF's card classes per kind (sfl-post / sfl-message), the item's text, "Media", or nothing.
    const kind = mark === "sfl-post-indicator" ? "sfl-post" : "sfl-message";
    expect(shown(doc, ".saved-for-later > .b-post.m-queue-post").map((c) => [c.classList.contains(kind), c.querySelector(".b-post__text")!.textContent])).toEqual([
      [true, "Saved Alpha"],
      [true, "Media"],
      [true, ""],
    ]);
    expect(texts(doc, ".saved-for-later > .empty-message")).toEqual([]);
    expect(doc.querySelector(".saved-for-later > .g-page__header")!.nextElementSibling!.matches(".empty-message")).toBe(true);
    expect(doc.querySelector(".saved-for-later")!.classList.contains("m-empty-content")).toBe(false);
  });

  it("a stream gets OF's stream mark and its description; an unknown /schedules type no colour mark", () => {
    const doc = load("queue/state-list-view");
    applyData(doc, "queue/state-list-view", {
      queue: [
        { type: "stream", publishDateTime: "2026-10-03T10:00:00", entity: { id: 9, description: "Live" } },
        { type: "story", publishDateTime: "2026-10-03T11:00:00", entity: { text: "Other" } },
      ],
    });
    expect(sections(doc)).toEqual([["Oct 3", [["stream-indicator", "10:00 am", "Live"], ["", "11:00 am", "Other"]]]]);
    // No stream edit or delete in the Relay: no More menu.
    expect(doc.querySelectorAll(".b-agenda [aria-label='More']")).toHaveLength(0);
  });

  it("the right column lists the shown day's items in place of its empty state; another day keeps it", () => {
    const doc = load("queue/index");
    const html = doc.documentElement.innerHTML;
    applyData(doc, "queue/index", { queue: SCHEDULES, templates: { agenda: AGENDA_TPL } });
    const side = doc.querySelector(".l-wrapper__sidebar")!;
    expect(shown(doc, ".l-wrapper__sidebar > .empty-message")).toEqual([]);
    expect(side.classList.contains("m-empty-section")).toBe(false);
    expect([...side.querySelectorAll(".b-agenda[data-oi-data] .b-agenda__area-events__item-inward")].map((e) => e.textContent)).toEqual(["Alpha Two post", ""]);
    applyData(doc, "queue/index", { queue: [SCHEDULES[0]], templates: { agenda: AGENDA_TPL } });
    expect(texts(doc, ".l-wrapper__sidebar > .empty-message")).toEqual(["There are no scheduled events for this day"]);
    expect(side.querySelector(".b-agenda")).toBeNull();
    applyData(doc, "queue/index", {});
    expect(doc.documentElement.innerHTML).toBe(html);
  });

  it("the month pages with no template (no agenda scope yet): the days marked, the right column as captured", () => {
    const doc = load("queue/index");
    const side = doc.querySelector(".l-wrapper__sidebar")!.outerHTML;
    applyData(doc, "queue/index", { queue: SCHEDULES });
    expect(bars(doc)).toEqual(WANT_BARS);
    expect(doc.querySelector(".l-wrapper__sidebar")!.outerHTML).toBe(side);
  });

  it.each(QUEUE_PAGES)("%s: Creator A's items then Creator B's leave only B's; no data restores the capture byte for byte", (p) => {
    const doc = load(p);
    const html = doc.documentElement.innerHTML;
    // The calendar pages: on the right column's day (Oct 12), so their rows show there; the list view another.
    const at = p.includes("saved-for-later") ? {} : { type: p.includes("state-tab") ? "chat" : "post", publishDateTime: p.includes("list-view") ? "2026-10-05T10:00:00" : "2026-10-12T10:00:00" };
    const item = (text: string): QueueItem => ({ ...at, text, entity: { text } });
    applyData(doc, p, { queue: [item("Alpha item"), item("Alpha other")], templates: { agenda: AGENDA_TPL } });
    applyData(doc, p, { queue: [item("Beta item")], templates: { agenda: AGENDA_TPL } });
    expect(shown(doc, ".b-agenda__area-events__item-inward, .b-post.m-queue-post .b-post__text").map((e) => e.textContent)).toEqual(["Beta item"]);
    expect(doc.querySelectorAll(".b-agenda__area-events__item, .b-post.m-queue-post")).toHaveLength(1);
    applyData(doc, p, {});
    expect(doc.documentElement.innerHTML).toBe(html);
  });

  it("the Streams tab (Messages and Streams selected): the month's messages and streams marked, no post", () => {
    const doc = load("queue/state-tab-streams");
    const stream = scheduled("stream", "2026-10-20T19:00:00", { id: 4, description: "Synthetic live" });
    applyData(doc, "queue/state-tab-streams", { queue: [...SCHEDULES, stream], templates: { agenda: AGENDA_TPL } });
    expect(bars(doc)).toEqual([
      ["2026-10-12", "chat", "1"],
      ["2026-10-14", "chat", "1"],
      ["2026-10-20", "stream", "1"],
    ]);
    // The right column: Oct 12's message only.
    expect(shown(doc, ".l-wrapper__sidebar .b-agenda__area-events__item").map((a) => a.className.includes("chat-indicator"))).toEqual([true]);
  });
});
