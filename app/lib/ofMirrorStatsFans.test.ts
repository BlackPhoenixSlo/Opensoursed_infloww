/**
 * Statistics › Fans' phase-2 parts (ofMirrorStatsFans) called directly on the captured mirror pages
 * (app/public/of-mirror/pages/statistics/fans/*.html) with OF's synthetic replies (app/lib/__fixtures__/of).
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import { applyFans, subsRekey, type FansCtx } from "./ofMirrorStatsFans";
import { PICK_DEFAULTS, applyStats, periodOf, startOf, type PagedBody, type Picks, type StatsData } from "./ofMirrorStats";
import { fansChartOf } from "./ofMirrorChart";
import { NOT_YET } from "./ofMirrorWrites";

const capture = (p: string) => readFileSync(resolve(__dirname, `../public/of-mirror/pages/${p}.html`), "utf8");
const load = (p: string) => {
  document.documentElement.innerHTML = capture(p);
  return document;
};
const fixture = <T = unknown,>(name: string): T => JSON.parse(readFileSync(resolve(__dirname, `__fixtures__/of/statistics-${name}.json`), "utf8")) as T;
const visible = (el: Element) => !el.closest("[style*='display:none'], [style*='display: none']");
const squash = (s: string | null | undefined) => (s ?? "").replace(/\s+/g, " ").trim();
const texts = (root: ParentNode, sel: string) => [...root.querySelectorAll(sel)].filter(visible).map((e) => squash(e.textContent));
const rows = (doc: ParentNode, sel: string) => [...doc.querySelectorAll(`${sel} tbody > tr`)].filter(visible).map((r) => [...r.querySelectorAll(":scope > td")].map((c) => squash(c.textContent)));
const TZ = "Europe/Ljubljana";
const NY = "America/New_York";
const NOW = new Date("2026-10-17T10:00:00Z");
const START = startOf(fixture("start-date"), TZ);
const D30 = periodOf("d30", NOW, TZ, START);
const ALL = periodOf("all", NOW, TZ, START);
const D30_NY = periodOf("d30", NOW, NY, START);
const picks = (p: Partial<Picks> = {}): Picks => ({ ...PICK_DEFAULTS, ...p });
/** A list reply in any of OF's shapes (`list`, `items`, `users`). */
type Listed = { list?: unknown[]; items?: unknown[]; users?: unknown[]; hasMore?: boolean };
const paged = (b: Listed, more: (() => void) | null = null): PagedBody => ({ list: b.list ?? b.items ?? b.users ?? [], hasMore: !!b.hasMore, loading: false, more });
const ctx = (x: Partial<FansCtx> = {}): FansCtx => ({ picks: picks(), v2: true, ...x });

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
});

describe("subsRekey: Fans › Subscriptions' summary from OF's chart for the tab", () => {
  const el = () => document.createElement("span");
  const RENEW = fixture("subs-chart-renew");
  const cases: [name: string, chart: unknown, v2: boolean, key: string, want: string][] = [
    ["subscribers", RENEW, true, "fans:fans.subscribers.total", "subsChart:subscribers"],
    ["earnings", RENEW, true, "fans:fans.earnings.total", "subsChart:total"],
    ["subscribers delta", RENEW, true, "fans:fans.subscribers.delta", "subsChart:delta"],
    ["earnings delta", RENEW, true, "fans:fans.earnings.delta", "subsChart:delta"],
    // Every fans:fans.*.delta reads the tab chart's one change: the rekey ignores the element, so the sidebar's New
    // subs/Renews change does too (see the BUG (pinned) sidebar test).
    ["new subs delta", RENEW, true, "fans:fans.subscriptions.new.delta", "subsChart:delta"],
    ["new subs total stays", RENEW, true, "fans:fans.subscriptions.new.total", "fans:fans.subscriptions.new.total"],
    ["another source's delta stays", RENEW, true, "posts:posts.count.delta", "posts:posts.count.delta"],
    ["today's Relay (no v2)", RENEW, false, "fans:fans.subscribers.total", "fans:fans.subscribers.total"],
    ["no chart", undefined, true, "fans:fans.subscribers.total", "fans:fans.subscribers.total"],
    ["chart an array", [], true, "fans:fans.subscribers.total", "fans:fans.subscribers.total"],
    ["a numeric string counts", { subscribers: "7" }, true, "fans:fans.subscribers.total", "subsChart:subscribers"],
    ["null figure stays", { subscribers: null, total: null, delta: null }, true, "fans:fans.subscribers.total", "fans:fans.subscribers.total"],
    ["non-numeric total stays", { total: "x" }, true, "fans:fans.earnings.total", "fans:fans.earnings.total"],
    ["no delta stays", { subscribers: 1 }, true, "fans:fans.earnings.delta", "fans:fans.earnings.delta"],
    ["zero delta counts", { delta: 0 }, true, "fans:fans.earnings.delta", "subsChart:delta"],
  ];
  it.each(cases)("%s", (_n, chart, v2, key, want) => {
    expect(subsRekey(chart, v2)(el(), key)).toBe(want);
  });
});

describe("applyFans › Subscriptions", () => {
  const data = (x: Partial<StatsData> = {}): StatsData => ({ subsChart: fixture("subs-chart-renew"), subsLatest: paged(fixture<Listed>("subs-latest")), ...x });
  const level = (doc: Document) => texts(doc, ".b-statistics-page-content__wrapper > .b-elements-determinant__value .b-statistics-level");
  const tabs = (doc: Document) => [...doc.querySelectorAll<HTMLButtonElement>("[data-oi-pick^='subs:']")].map((b) => [squash(b.textContent), b.disabled, b.classList.contains("m-current")]);

  it("Renews (v2): tabs, the chart's change, the Renew date column, a row per fan; an expired one grey", () => {
    const doc = load("statistics/fans/subscriptions");
    applyFans(doc, "fans/subscriptions", data(), D30, ctx({ picks: picks({ subs: "renew" }) }));
    expect(tabs(doc)).toEqual([["All", false, false], ["Renews", false, true], ["New subscribers", false, false]]);
    expect(level(doc)).toEqual(["-20%"]);
    expect(doc.querySelector(".b-statistics-page-content__wrapper .b-statistics-level")!.classList.contains("m-level-down")).toBe(true);
    expect(texts(doc, "[data-oi-table='subs'] thead th")).toEqual(["Name", "Price", "Price/ Renew date"]);
    expect(rows(doc, "[data-oi-table='subs']")).toEqual([
      ["SF Synthetic Fan D @u_synthetic_d", "free", ""],
      ["u900011 @u900011", "$9.99", "Oct 10, 2026"],
    ]);
    const trs = [...doc.querySelectorAll("[data-oi-table='subs'] tbody tr[data-oi-data]")];
    expect(trs.map((t) => t.classList.contains("g-gray-text"))).toEqual([false, true]); // expired Oct 12, before now
    expect(texts(doc, "[data-oi-table='subs'] .empty-message")).toEqual([]);
    expect(doc.querySelector(".b-statistics-page-content__wrapper")!.classList.contains("m-empty-wrapper")).toBe(false);
  });

  const columnCases: [tab: string, period: typeof D30, head: string, third: [string, string]][] = [
    ["total", D30, "Total duration", ["1 month", "3 months"]],
    ["new", D30, "Subscription date", ["Oct 1, 2026", "Jul 10, 2026"]],
    // Midnight UTC is the evening before in New York.
    ["new", D30_NY, "Subscription date", ["Sep 30, 2026", "Jul 9, 2026"]],
    ["renew", D30_NY, "Renew date", ["", "Oct 9, 2026"]],
  ];
  it.each(columnCases)("%s tab (%#): its column and dates in the owner's zone", (tab, period, head, third) => {
    const doc = load("statistics/fans/subscriptions");
    applyFans(doc, "fans/subscriptions", data(), period, ctx({ picks: picks({ subs: tab }) }));
    expect(squash(doc.querySelectorAll("[data-oi-table='subs'] thead th")[2].textContent)).toBe(`Price/ ${head}`);
    expect(rows(doc, "[data-oi-table='subs']").map((r) => r[2])).toEqual(third);
  });

  it("All time: no change shown; no change in the chart (0): none either", () => {
    const all = load("statistics/fans/subscriptions");
    applyFans(all, "fans/subscriptions", data(), ALL, ctx());
    expect(level(all)).toEqual([]);
    const zero = load("statistics/fans/subscriptions");
    applyFans(zero, "fans/subscriptions", data({ subsChart: { ...fixture<object>("subs-chart-renew"), delta: 0 } }), D30, ctx());
    expect(level(zero)).toEqual([]);
  });

  it("today's Relay (no v2): tabs disabled, no change, the column kept; the rows still drawn", () => {
    const doc = load("statistics/fans/subscriptions");
    applyFans(doc, "fans/subscriptions", data(), D30, ctx({ v2: false }));
    expect([...doc.querySelectorAll<HTMLButtonElement>("[data-oi-pick^='subs:']")].every((b) => b.disabled && b.title === NOT_YET)).toBe(true);
    expect(level(doc)).toEqual([]);
    expect(texts(doc, "[data-oi-table='subs'] thead th")[2]).toBe("Price/ Total duration");
    expect(rows(doc, "[data-oi-table='subs']")).toHaveLength(2);
  });

  it("none and no more: \"Nothing found\" and the empty wrapper", () => {
    const doc = load("statistics/fans/subscriptions");
    applyFans(doc, "fans/subscriptions", data({ subsLatest: paged(fixture<Listed>("users-empty")) }), D30, ctx());
    expect(texts(doc, "[data-oi-table='subs'] .empty-message")).toEqual(["Nothing found"]);
    expect(doc.querySelector(".b-statistics-page-content__wrapper")!.classList.contains("m-empty-wrapper")).toBe(true);
  });

  it.each<[string, Partial<StatsData>]>([
    ["none with more to read: no claim", { subsLatest: paged({ users: [], hasMore: true }) }],
    ["no source: untouched", { subsLatest: undefined }],
  ])("%s", (_name, x) => {
    const doc = load("statistics/fans/subscriptions");
    applyFans(doc, "fans/subscriptions", data(x), D30, ctx());
    expect(texts(doc, "[data-oi-table='subs'] .empty-message")).toEqual([NOT_YET]);
  });

  it("more to read: the table's last row observed, the next page read when it scrolls into view", () => {
    const seen = stubIO();
    const doc = load("statistics/fans/subscriptions");
    const more = vi.fn();
    applyFans(doc, "fans/subscriptions", data({ subsLatest: paged({ ...fixture<Listed>("subs-latest"), hasMore: true }, more) }), D30, ctx());
    expect(seen.map((s) => s.el)).toEqual([doc.querySelector("[data-oi-table='subs'] tbody")!.lastElementChild]);
    seen[0].fire();
    expect(more).toHaveBeenCalledTimes(1);
  });

  it("BUG (pinned): with OF's chart, the sidebar Summary shows the tab chart's figures and change, not the overview's (through applyStats)", () => {
    // BUG: see PR — subsRekey (like messagesRekey) ignores the element it rekeys, and applyStats' figures pass every
    // [data-oi-stat] / [data-oi-delta] on the page through it, the `.l-wrapper__sidebar` Summary's included. So on the
    // Renews tab the sidebar "Subscribers" and "Subscriptions earnings" read the Renews chart (2, $19.98) and every
    // sidebar change is the chart's -20%, even "New subs/Renews", whose figures (7 / 3) stay the overview's (its own
    // change is +40%). Correct: the sidebar keeps the overview's figures and changes, as it does without the chart
    // (second half).
    const overview = { fans: { fans: { subscribers: { total: 50, delta: 10 }, earnings: { total: 200, delta: 15 }, subscriptions: { new: { total: 7, delta: 40 }, renew: { total: 3 } } } } };
    const side = (doc: Document) => squash(doc.querySelector(".l-wrapper__sidebar .b-useful-data")!.textContent);
    const doc = load("statistics/fans/subscriptions");
    applyStats(doc, "statistics/fans/subscriptions", { ...overview, subsChart: fixture("subs-chart-renew") }, D30, { v2: true, picks: { subs: "renew" } });
    expect(side(doc)).toBe("Summary Subscribers 2 -20% New subs/Renews 7 / 3 -20% Subscriptions earnings $19.98 -20%");
    const plain = load("statistics/fans/subscriptions");
    applyStats(plain, "statistics/fans/subscriptions", overview, D30, { v2: true, picks: { subs: "renew" } });
    expect(side(plain)).toBe("Summary Subscribers 50 10% New subs/Renews 7 / 3 40% Subscriptions earnings $200.00 15%");
  });
});

describe("applyFans › Top fans", () => {
  const TOP = paged(fixture<Listed>("subs-top"));
  const cases: [tab: string, head: string[], row: string[]][] = [
    ["total", ["Name", "Tips / Total"], ["SF Synthetic Fan E @u_synthetic_e", "$12.00"]],
    ["tips", ["Name", "Tips", "Tips / Total"], ["SF Synthetic Fan E @u_synthetic_e", "$7.00", "$12.00"]],
    ["messages", ["Name", "Messages", "Tips / Total"], ["SF Synthetic Fan E @u_synthetic_e", "$5.00", "$12.00"]],
    ["post", ["Name", "Posts", "Tips / Total"], ["SF Synthetic Fan E @u_synthetic_e", "$0.00", "$12.00"]],
    ["subscribes", ["Name", "Subscriptions", "Tips / Total"], ["SF Synthetic Fan E @u_synthetic_e", "$0.00", "$12.00"]],
    ["streams", ["Name", "Streams", "Tips / Total"], ["SF Synthetic Fan E @u_synthetic_e", "$0.00", "$12.00"]],
  ];
  it.each(cases)("%s tab: its column and sum, the total", (tab, head, row) => {
    const doc = load("statistics/fans/top-fans");
    applyFans(doc, "fans/top-fans", { subsTop: TOP }, D30, ctx({ picks: picks({ top: tab }) }));
    const current = [...doc.querySelectorAll("[data-oi-pick^='top:']")].filter((b) => b.classList.contains("m-current"));
    expect(current.map((b) => b.getAttribute("data-oi-pick"))).toEqual([`top:${tab}`]);
    expect(texts(doc, "[data-oi-table='topfans'] thead th")).toEqual(head);
    expect(rows(doc, "[data-oi-table='topfans']")).toEqual([row]);
    // The tab's own sum bold; the total bold only on Total.
    const tr = doc.querySelector("[data-oi-table='topfans'] tbody tr[data-oi-data]")!;
    expect(squash(tr.querySelector("strong")!.textContent)).toBe(row[1]);
  });

  it("an unknown tab: no tab current; the column titled and summed as Total's (TOP_TABS.total), next to the total", () => {
    const doc = load("statistics/fans/top-fans");
    applyFans(doc, "fans/top-fans", { subsTop: TOP }, D30, ctx({ picks: picks({ top: "bogus" }) }));
    expect([...doc.querySelectorAll("[data-oi-pick^='top:']")].filter((b) => b.classList.contains("m-current"))).toEqual([]);
    expect(texts(doc, "[data-oi-table='topfans'] thead th")).toEqual(["Name", "Total", "Tips / Total"]);
    expect(rows(doc, "[data-oi-table='topfans']")).toEqual([["SF Synthetic Fan E @u_synthetic_e", "$12.00", "$12.00"]]);
  });

  it("an all-zero period: \"No users found\"; no v2: tabs disabled", () => {
    const doc = load("statistics/fans/top-fans");
    applyFans(doc, "fans/top-fans", { subsTop: paged(fixture<Listed>("users-empty")) }, D30, ctx({ v2: false }));
    expect(texts(doc, "[data-oi-table='topfans'] .empty-message")).toEqual(["No users found"]);
    expect([...doc.querySelectorAll<HTMLButtonElement>("[data-oi-pick^='top:']")].every((b) => b.disabled)).toBe(true);
  });
});

describe("applyFans › Fans activity", () => {
  const shown = (doc: Document, which: string) => doc.querySelector<HTMLElement>(`[data-oi-activity='${which}']`)!.style.display !== "none";
  const note = (doc: Document, which: string) => doc.querySelector<HTMLElement>(`[data-oi-activity-empty='${which}']`)!;

  it("both charts drawn from OF's replies (sectors, 24 hour bars as ratio × 100); their empty notes hidden", () => {
    const doc = load("statistics/fans/activity");
    applyFans(doc, "fans/activity", { fansActivity: fixture("fans-activity"), fansHours: fixture("fans-hours") }, D30, ctx());
    expect([shown(doc, "sectors"), shown(doc, "hours")]).toEqual([true, true]);
    expect([note(doc, "sectors").style.display, note(doc, "hours").style.display]).toEqual(["none", "none"]);
    expect(fansChartOf(doc.querySelector<HTMLCanvasElement>("[data-oi-activity='sectors'] canvas")!)!.kind).toBe("sectors");
    const bars = fansChartOf(doc.querySelector<HTMLCanvasElement>("[data-oi-activity='hours'] canvas")!)!;
    expect(bars.kind).toBe("bars");
    if (bars.kind !== "bars") return; // narrowed for the type checker; asserted just above
    expect(bars.spec.values).toHaveLength(24);
    expect(bars.spec.values[9]).toBe(5);
  });

  it("ratios missing or not numbers count as 0", () => {
    const doc = load("statistics/fans/activity");
    applyFans(doc, "fans/activity", { fansHours: { data: [{ ratio: 0.25 }, {}, { ratio: "0.5" }, { ratio: "x" }, null] } }, D30, ctx());
    const bars = fansChartOf(doc.querySelector<HTMLCanvasElement>("[data-oi-activity='hours'] canvas")!)!;
    expect(bars.spec).toMatchObject({ values: [25, 0, 50, 0, 0] });
    expect(shown(doc, "sectors")).toBe(false); // no table reply: untouched
  });

  it("no hours at all: OF's \"No Profile activity\"; replies not in OF's shape: both boxes untouched", () => {
    const doc = load("statistics/fans/activity");
    applyFans(doc, "fans/activity", { fansHours: { data: [] } }, D30, ctx());
    expect(shown(doc, "hours")).toBe(false);
    expect(texts(doc, "[data-oi-activity-empty='hours']")).toEqual(["No Profile activity during selected period"]);
    const odd = load("statistics/fans/activity");
    applyFans(odd, "fans/activity", { fansActivity: [], fansHours: { data: "x" } }, D30, ctx());
    expect([shown(odd, "sectors"), shown(odd, "hours")]).toEqual([false, false]);
    expect(texts(odd, ".b-statistics-page-content__wrapper .empty-message")).toEqual([NOT_YET, NOT_YET]);
  });
});

describe("applyFans › the sidebar Top Fan card (every Fans tab)", () => {
  const card = (doc: Document) => doc.querySelector<HTMLElement>("[data-oi-fan-card]")!;
  /** Each fan tab: [text, disabled, current, m-disabled]. */
  const fanTabs = (doc: Document) =>
    [...card(doc).querySelectorAll<HTMLButtonElement>("[data-oi-pick^='fan:']")].map((b) => [squash(b.textContent), b.disabled, b.classList.contains("m-current"), b.classList.contains("m-disabled")]);
  const currentFanTab = (doc: Document) => fanTabs(doc).filter(([, , current]) => current).map(([text]) => text);
  const list = (doc: Document) => texts(card(doc), ".b-fans__item__list__item");

  it("Subscription: the fan, the tabs with a fan (the rest m-disabled), the known details only", () => {
    const doc = load("statistics/fans/activity");
    applyFans(doc, "fans/activity", { topFan: fixture("top-fan") }, D30, ctx());
    expect(visible(card(doc))).toBe(true);
    expect((card(doc).previousElementSibling as HTMLElement).style.display).toBe("none");
    expect(texts(card(doc), ".g-user-name, .g-user-username")).toEqual(["Synthetic Fan B", "@u_synthetic_b"]);
    expect(fanTabs(doc)).toEqual([
      ["Total", false, true, false],
      ["Subscriptions", false, false, false],
      ["Tips", true, false, true],
      ["Messages", false, false, false],
      ["Streams", true, false, true],
    ]);
    expect(list(doc)).toEqual(["Current subscription $9.99", "Total duration 3 months"]);
    // OF's avatar in place of the generator's slot.
    const slot = card(doc).querySelector<HTMLElement>("[data-oi-fan-avatar]")!;
    expect(slot.style.display).toBe("none");
    expect(slot.nextElementSibling!.classList.contains("g-avatar")).toBe(true);
    expect(texts(slot.nextElementSibling!, ".g-avatar__placeholder")).toEqual(["SF"]);
  });

  it("a picked tab with no fan falls back to the first with one; Earnings: OF's five sums", () => {
    const doc = load("statistics/fans/subscriptions");
    applyFans(doc, "fans/subscriptions", { topFan: fixture("top-fan") }, D30, ctx({ picks: picks({ fan: "tips", fantab: "earnings" }) }));
    expect(currentFanTab(doc)).toEqual(["Total"]);
    const fantab = [...card(doc).querySelectorAll("[data-oi-pick^='fantab:']")].filter((b) => b.classList.contains("m-current"));
    expect(fantab.map((b) => b.getAttribute("data-oi-pick"))).toEqual(["fantab:earnings"]);
    expect(list(doc)).toEqual(["Total $42.50", "Subscriptions $29.97", "Tips $7.53", "Messages $5.00", "Streams $0.00"]);
  });

  it("a free fan with dates: free, Started, and Renews from the expiry when no renewal; no name: the username; in the owner's zone", () => {
    const fan = { id: 1, name: null, username: "u_free", avatar: null, subscribedOnDuration: "1 month", subscribedOnData: { price: 0, subscribeAt: "2026-10-01T00:00:00+00:00", renewedAt: null, expiredAt: "2026-11-01T00:00:00+00:00" } };
    const topFan = { ...fixture<object>("top-empty"), messages: fan };
    const doc = load("statistics/fans/top-fans");
    applyFans(doc, "fans/top-fans", { topFan }, D30, ctx());
    expect(currentFanTab(doc)).toEqual(["Messages"]);
    expect(texts(card(doc), ".g-user-name, .g-user-username")).toEqual(["u_free", "@u_free"]);
    expect(list(doc)).toEqual(["Current subscription free", "Started Oct 1, 2026", "Total duration 1 month", "Renews Nov 1, 2026"]);
    const ny = load("statistics/fans/top-fans");
    applyFans(ny, "fans/top-fans", { topFan }, D30_NY, ctx());
    expect(list(ny)).toEqual(["Current subscription free", "Started Sep 30, 2026", "Total duration 1 month", "Renews Oct 31, 2026"]);
  });

  it("no top fan in the period: OF's \"No Fans yet\", the card hidden; no source: untouched", () => {
    const doc = load("statistics/fans/top-fans");
    applyFans(doc, "fans/top-fans", { topFan: fixture("top-empty") }, D30, ctx());
    expect(card(doc).style.display).toBe("none");
    expect(texts(doc, ".l-wrapper__sidebar .b-clean-state .empty-message")).toEqual(["No Fans yet"]);
    const absent = load("statistics/fans/top-fans");
    applyFans(absent, "fans/top-fans", {}, D30, ctx());
    expect(card(absent).style.display).toBe("none");
    expect(texts(absent, ".l-wrapper__sidebar .b-clean-state .empty-message")).toEqual([NOT_YET]);
  });
});
