import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { applyStats, bindMenu, bindPicks, currentPeriodKey, currentPicks, customKey, nextOffset, pagedRoute, resetPicks, setPick, derive, isPeriodKey, periodMenu, periodOf, setPeriod, startOf, statsRoute, statsSources, utcOffset, type StatsData } from "./ofMirrorStats";
import { chartSpecOf, viewDuration } from "./ofMirrorChart";
import { parseDay } from "./ofMirrorDatepicker";
import { standInModel } from "./ofMirrorProfile";

const capture = (p: string) => readFileSync(resolve(__dirname, `../public/of-mirror/pages/${p}.html`), "utf8");
const load = (p: string) => {
  document.documentElement.innerHTML = capture(p);
  return document;
};
const visible = (el: Element) => !el.closest("[style*='display:none'], [style*='display: none']");
const texts = (doc: Document, sel: string) => [...doc.querySelectorAll(sel)].filter(visible).map((e) => e.textContent?.replace(/\s+/g, " ").trim());
/** A sidebar or summary unit's value by its label. */
const unit = (doc: Document, label: string) =>
  [...doc.querySelectorAll(".b-elements-determinant__unit")]
    .filter(visible)
    .filter((u) => u.querySelector(".b-elements-determinant__label")?.textContent?.trim() === label)
    .map((u) => u.querySelector(".b-elements-determinant__value")!.textContent!.replace(/\s+/g, " ").trim());
const NOT_YET = "Not available in Inflowwww yet";
const TZ = "Europe/Ljubljana";
const NOW = new Date("2026-10-17T10:00:00Z"); // 12:00 in Ljubljana (UTC +02:00)

/** OF's own /api2/v2 responses for the last 30 days, read through the Relay and scrubbed (app/lib/__fixtures__/of). */
const fixture = <T = unknown,>(name: string): T => JSON.parse(readFileSync(resolve(__dirname, `__fixtures__/of/statistics-${name}.json`), "utf8")) as T;
const OVERVIEW = fixture<Record<string, unknown>>("overview");
/** Every source as the Relay answered it: a real period with no earnings (OF's zeros), counts and charts. */
const LIVE: StatsData = {
  ...OVERVIEW,
  stats: fixture("payouts-stats"),
  transactions: fixture("transactions"),
  massMessages: fixture("messages-group"),
  chargebacks: fixture("chargebacks-ratio"),
  profileStats: fixture("profile-stats"),
  subsChart: fixture("subscribers-chart"),
  postsChart: fixture("posts-chart"),
  topPost: fixture("top-post"),
  postsTop: fixture("posts-top"),
  payoutRequests: fixture("payout-requests"),
  referralRequests: fixture("referral-requests"),
  referralBalance: fixture("referrals-balance"),
  startDate: fixture("start-date"),
};
const START = startOf(LIVE.startDate, TZ);
const D30 = periodOf("d30", NOW, TZ, START);
/** `LIVE` with the period's earnings set (net, gross, change in %) per overview source. */
const earning = (net: Record<string, [number, number, number]>): StatsData => {
  const out: StatsData = structuredClone(LIVE);
  const set = (src: string, path: string, [total, gross, delta]: [number, number, number]) => {
    let o = out[src as keyof StatsData] as Record<string, unknown>;
    const keys = path.split(".");
    for (const k of keys.slice(0, -1)) o = o[k] as Record<string, unknown>;
    o[keys.at(-1)!] = { total, gross, delta };
  };
  const paths: Record<string, [string, string]> = { earnings: ["earnings", "earning"], fans: ["fans", "fans.earnings"], messages: ["messages", "massMessages.earnings"], posts: ["posts", "posts.earnings"], streams: ["streams", "streams.earnings"] };
  for (const [k, v] of Object.entries(net)) set(paths[k][0], paths[k][1], v);
  return out;
};

describe("the period (OF's PeriodDatepicker, in the owner's time zone)", () => {
  it("Last 30 days: from the day's start 30 days back (its wall time) to now (UTC, as OF sends today)", () => {
    expect(D30).toMatchObject({ title: "Last 30 days", from: "Sep 17, 2026", to: "Oct 17, 2026", startApi: "2026-09-17 00:00:00", endApi: "2026-10-17 10:00:00" });
    expect(utcOffset(NOW, TZ)).toBe("UTC +02:00");
    expect(utcOffset(NOW, "America/New_York")).toBe("UTC -04:00");
    expect(periodOf("d30", NOW, "America/New_York", START)).toMatchObject({ from: "Sep 17, 2026", startApi: "2026-09-17 00:00:00" });
  });

  it("24 hours, a past year, a past month, this month and All time; the start never before the Creator's", () => {
    expect(periodOf("24h", NOW, TZ, START)).toMatchObject({ title: "Last 24 hours", startApi: "2026-10-16 10:00:00", endApi: "2026-10-17 10:00:00", from: "12:00 pm, Oct 16", to: "12:00 pm, Oct 17, 2026" });
    expect(periodOf("y2025", NOW, TZ, START)).toMatchObject({ title: "2025", startApi: "2025-01-01 00:00:00", endApi: "2025-12-31 23:59:59", from: "Jan 01, 2025", to: "Dec 31, 2025" });
    expect(periodOf("m1", NOW, TZ, START)).toMatchObject({ title: "September", startApi: "2026-09-01 00:00:00", endApi: "2026-09-30 23:59:59" });
    expect(periodOf("m0", NOW, TZ, START)).toMatchObject({ title: "October", startApi: "2026-10-01 00:00:00", endApi: "2026-10-17 10:00:00" });
    expect(periodOf("all", NOW, TZ, START)).toMatchObject({ title: "All time", startApi: "2021-09-28 16:24:48", from: "Sep 28, 2021" });
    const lateStart = new Date("2026-10-10T08:00:00Z");
    expect(periodOf("d30", NOW, TZ, lateStart)).toMatchObject({ startApi: "2026-10-10 10:00:00", from: "Oct 10, 2026" });
  });

  it("the menu: OF's items; days shorter than the account's age and years and months before its start left out", () => {
    const titles = (start: Date | null) => periodMenu(NOW, TZ, start).map((i) => (i ? i.title : "—"));
    expect(titles(START)).toEqual(["Custom", "—", "Last 24 hours", "Last 7 days", "Last 30 days", "Last 90 days", "Last 180 days", "Last 365 days", "—", "2026", "2025", "All time", "—", "October", "September", "August", "July", "June", "May"]);
    expect(titles(new Date("2026-09-25T10:00:00Z"))).toEqual(["Custom", "—", "Last 24 hours", "Last 7 days", "Last 30 days", "—", "2026", "All time", "—", "October", "September"]);
    expect(periodMenu(NOW, TZ, START)[0]).toEqual({ title: "Custom", key: null }); // it opens OF's date picker
  });

  it("Custom: its first day's start to its last day's end, titled Custom, its dates with their times (OF's format)", () => {
    const key = customKey(parseDay("2026-09-01")!, parseDay("2026-09-15")!);
    expect(key).toBe("c2026-09-01_2026-09-15");
    expect(isPeriodKey(key)).toBe(true);
    expect(isPeriodKey("c2026-09-15_2026-09-01")).toBe(false);
    expect(isPeriodKey("c2026-02-30_2026-03-01")).toBe(false);
    expect(periodOf(key, NOW, TZ, START)).toMatchObject({ title: "Custom", startApi: "2026-09-01 00:00:00", endApi: "2026-09-15 23:59:59", from: "12:00 am, Sep 01", to: "11:59 pm, Sep 15, 2026" });
    // Ending today: now, sent as UTC; across years the start carries its year.
    expect(periodOf("c2025-12-30_2026-10-17", NOW, TZ, START)).toMatchObject({ startApi: "2025-12-30 00:00:00", endApi: "2026-10-17 10:00:00", from: "12:00 am, Dec 30, 2025", to: "12:00 pm, Oct 17, 2026" });
  });

  it("the menu's Custom opens OF's date picker on the period shown; Apply picks those days", () => {
    const doc = load("statistics/overview/earnings");
    bindMenu(doc, D30, START);
    doc.querySelector<HTMLElement>("[data-oi-period]")!.click();
    const custom = doc.querySelector<HTMLElement>("[data-oi-period-custom]")!;
    expect(custom.textContent!.trim()).toBe("Custom");
    expect(custom.hasAttribute("aria-disabled")).toBe(false);
    custom.click();
    expect(doc.querySelector("[data-oi-period-menu]")).toBeNull();
    expect(doc.querySelector(".vdatetime-popup__title")!.textContent!.trim()).toBe("31 days selected");
    doc.querySelector<HTMLElement>("[data-oi-day='2026-09-20']")!.click();
    doc.querySelector<HTMLElement>("[data-oi-month='prev']")!.click(); // the end tab opened on the end's month
    doc.querySelector<HTMLElement>("[data-oi-day='2026-09-25']")!.click();
    doc.querySelector<HTMLElement>("[data-oi-picker-apply]")!.click();
    expect(currentPeriodKey()).toBe("c2026-09-20_2026-09-25");
    setPeriod("d30");
  });
});

describe("statsSources and statsRoute", () => {
  it("per Statistics tab (plus the Creator's start), none elsewhere; routes carry the period", () => {
    expect(statsSources("statistics/statements/disputes")).toEqual(["earnings", "fans", "posts", "messages", "streams", "referralBalance", "referralRequests", "earningsSide", "chargebacks", "chargebacksList", "chargebacksChart", "startDate"]);
    expect(statsSources("statistics/reach/profile-visitors")).toEqual(["visitors", "profileStats", "startDate"]);
    expect(statsSources("statistics/fans/activity")).toEqual(["fans", "fansActivity", "fansHours", "topFan", "startDate"]);
    for (const p of ["statements/earnings", "home/index"]) expect(statsSources(p)).toEqual([]);
    expect(statsRoute("fans", D30)).toBe("/api/of/v2/users/me/stats/overview?by=fans&start=2026-09-17+00%3A00%3A00&end=2026-10-17+10%3A00%3A00");
    expect(statsRoute("massMessages", D30)).toBe("/api/of/v2/users/me/stats/messages/group?startDate=2026-09-17+00%3A00%3A00&endDate=2026-10-17+10%3A00%3A00&limit=50&offset=0");
    expect(statsRoute("profileStats", D30)).toBe("/api/of/v2/users/me/profile/stats?limit=3&start=2026-09-17+00%3A00%3A00&end=2026-10-17+10%3A00%3A00");
    expect(statsRoute("chargebacks", D30)).toMatch(/^\/api\/of\/v2\/payouts\/chargebacks\/ratio\?start=/);
  });

  it("All models shows the first model on every Statistics tab, as on My profile", () => {
    const accounts = [{ id: "7" }, { id: "8" }];
    expect(standInModel("/of-mirror/pages/statistics/statements/disputes.html", null, accounts)).toBe("7");
    expect(standInModel("/of-mirror/pages/statistics/overview/earnings.html", "8", accounts)).toBeNull();
  });
});

describe("the generator's Statistics pages", () => {
  it("no captured figure, fan, example text or level mark shows; the period button is OF's, wired", { timeout: 30_000 }, () => {
    for (const p of ["overview/earnings", "overview/top-highlights", "overview/streaks", "engagement/messages", "engagement/posts", "fans/subscriptions", "fans/top-fans", "reach/profile-visitors", "reach/promotions", "statements/earnings", "statements/disputes"]) {
      const doc = load(`statistics/${p}`);
      const main = [...doc.querySelectorAll("main")].map((m) => [...m.querySelectorAll("*")].filter(visible)).flat();
      const text = main.map((e) => [...e.childNodes].filter((n) => n.nodeType === 3).map((n) => n.textContent).join(" ")).join(" ");
      expect(text.replace("Minimum withdrawal amount is $20", ""), p).not.toMatch(/\$\d|Fan \d|@fan|Lorem|\d+(\.\d+)?%|TOP \d|\b\d+ \/ \d+\b/);
      expect(doc.querySelectorAll(".b-statistics-level").length, p).toBe(0);
      const button = doc.querySelector<HTMLButtonElement>("button[data-oi-period]")!;
      expect(button.disabled, p).toBe(false);
      expect(button.hasAttribute("data-oi-wired"), p).toBe(true);
      expect(doc.querySelectorAll("[data-oi-stat^='chart:']").length, p).toBe(0); // /earnings/chart answers [] through the Relay
    }
  });
});

describe("applyStats on the live bodies (a real period with no earnings)", () => {
  it("Chargebacks: 0% and OF's \"No data\", the balances' sidebar lists no earnings (OF's clean state), never a dash", () => {
    const doc = load("statistics/statements/disputes");
    applyStats(doc, "statistics/statements/disputes", LIVE, D30);
    expect(texts(doc, ".m-statistics-alert .alert-text-wrapper > p")).toEqual(["Chargeback ratio 0%"]);
    expect(texts(doc, ".b-statistics-page-content__wrapper .empty-message")).toEqual(["No data during selected period"]);
    expect(texts(doc, ".b-useful-data:has(> .b-useful-data__header) .b-clean-state .empty-message")).toEqual(["No earnings for this period"]);
    expect(texts(doc, "[data-oi-period-title]")).toEqual(["Last 30 days"]);
    expect(texts(doc, "[data-oi-range]")).toEqual(["Sep 17, 2026 - Oct 17, 2026"]);
    applyStats(doc, "statistics/statements/disputes", { ...LIVE, chargebacks: { chargebacksRatio: 1.236 } }, D30);
    expect(texts(doc, ".m-statistics-alert .alert-text-wrapper > p")).toEqual(["Chargeback ratio 1.24%"]); // OF rounds to two places
    expect(texts(doc, ".b-statistics-page-content__wrapper .empty-message")).toEqual([NOT_YET]); // chargebacks, but no list route
  });

  it("Overview › Earnings: the sidebar's figures and OF's marks, the period's sums as $0.00, All time and every month since the start", () => {
    const doc = load("statistics/overview/earnings");
    const html = doc.documentElement.innerHTML;
    applyStats(doc, "statistics/overview/earnings", LIVE, D30);
    expect(unit(doc, "Earnings")).toEqual(["$0.00"]);
    expect(unit(doc, "Profile visitors")).toEqual(["200 86.9%"]);
    expect(unit(doc, "New subs/Renews")).toEqual(["10 / 0"]);
    expect(unit(doc, "Posts views")).toEqual(["20 60%"]);
    expect(doc.querySelector(".b-elements-determinant__value .m-level-down")!.textContent!.trim()).toBe("60%"); // not a Summary: no sign
    expect(texts(doc, "[data-oi-range='tz']")).toEqual(["Sep 17, 2026 - Oct 17, 2026 (local time UTC +02:00)"]);
    const row = (name: string) => texts(doc, `.b-stats-row__label:has(input[name='${name}']) .b-stats-row__val`);
    for (const k of ["total", "subscribes", "tips", "tips_stream", "post", "chat_messages", "ref", "stream"]) expect(row(k), k).toEqual(["$0.00", "$0.00"]);
    const months = texts(doc, ".b-stats-row__month");
    expect(months.slice(0, 4)).toEqual(["All time", "Sep 17, 2026 - Oct 17, 2026", "October, 2026", "September, 2026"]);
    expect(months.at(-1)).toBe("September, 2021"); // the Creator's start
    const nets = texts(doc, ".b-stats-row__total-net > span");
    expect(nets).not.toContain("—");
    expect(nets[months.indexOf("May, 2026")]).not.toBe("$0.00"); // /payouts/stats' month
    expect(nets[months.indexOf("April, 2026")]).toBe("$0.00"); // a month it lists nothing for
    expect(texts(doc, ".l-wrapper__sidebar .empty-message")).toEqual(["No Streaming activity during selected period"]);
    applyStats(doc, "statistics/overview/earnings", LIVE, D30); // idempotent
    expect(texts(doc, ".b-stats-row__month")).toHaveLength(months.length);
    applyStats(doc, "statistics/overview/earnings", {}, D30);
    expect(unit(doc, "Earnings")).toEqual(["—"]);
    applyStats(doc, "home/index", {}, D30);
    expect(doc.documentElement.innerHTML).toBe(html);
  });

  it("Top highlights: OF's empty Message and Stream cards (proven by the period's figures); Top Fan has no source", () => {
    const doc = load("statistics/overview/top-highlights");
    applyStats(doc, "statistics/overview/top-highlights", LIVE, D30);
    const card = (t: string) => texts(doc, `.b-clean-state:has(> .b-clean-state__title) `).find((x) => x?.startsWith(t));
    expect(card("Top Post")).toBeUndefined(); // OF's card instead (below)
    expect(card("Top Message")).toBe("Top Message No Message activity during selected period");
    expect(card("Top Stream")).toBe("Top Stream No Streaming activity during selected period");
    expect(card("Top Fan")).toBe(`Top Fan ${NOT_YET}`);
    const none = structuredClone(LIVE);
    none.topPost = { purchases: null, tips: null, views: null, likes: null, comments: null };
    applyStats(doc, "statistics/overview/top-highlights", none, D30);
    expect(card("Top Post")).toBe("Top Post No Post activity during selected period");
  });

  it("Top Post: OF's card for the period's top post, its metric tabs (none: disabled), date, text, footer; tabs switch in place", () => {
    for (const page of ["statistics/overview/top-highlights", "statistics/engagement/posts"]) {
      const doc = load(page);
      applyStats(doc, page, LIVE, D30, { img: (u) => `/img?u=${encodeURIComponent(u)}` });
      const card = doc.querySelector("[data-oi-top='Top Post']")!;
      expect(card, page).not.toBeNull();
      expect([...card.querySelectorAll<HTMLButtonElement>(".b-tabs__nav__link")].map((b) => `${b.textContent!.trim()}${b.disabled ? "×" : ""}${b.classList.contains("m-current") ? "*" : ""}`)).toEqual(["Purchases×", "Tips×", "Views*", "Likes×", "Comments×"]);
      expect(card.querySelector(".b-top-statistic__header__date")!.textContent!.trim()).toBe("Oct 17, 2026, 01:52 am"); // OF's "MMM D, YYYY, hh:mm a", owner's zone
      expect(card.querySelector(".b-top-statistic__text p")!.textContent).toBe("Synthetic post text 1");
      expect(card.querySelector(".b-top-statistic__img img")!.getAttribute("src")).toMatch(/^\/img\?u=/); // through the Relay, never OF's CDN
      expect(texts(doc, "[data-oi-top='Top Post'] .b-summary-list__item")).toEqual(["6 views"]);
      const full = card.querySelector<HTMLButtonElement>(".b-top-statistic__btns button")!;
      expect([full.textContent!.trim(), full.disabled, full.title]).toEqual(["Full stat", true, NOT_YET]);
      expect(texts(doc, ".b-clean-state:has(> .b-clean-state__title)").find((x) => x?.startsWith("Top Post"))).toBeUndefined();
    }
    const doc = load("statistics/overview/top-highlights");
    const both = structuredClone(LIVE);
    const views = (both.topPost as Record<string, Record<string, unknown>>).views;
    (both.topPost as Record<string, unknown>).purchases = { ...views, id: 7002, rawText: "Synthetic post text 2", price: 5, stats: { purchasedSumm: 15, lookCount: 3 } };
    applyStats(doc, "statistics/overview/top-highlights", both, D30);
    expect(texts(doc, "[data-oi-top='Top Post'] .b-top-statistic__text")).toEqual(["Synthetic post text 2"]); // OF's first tab with a post
    expect(texts(doc, "[data-oi-top='Top Post'] .b-price")).toEqual(["$5.00"]);
    expect(doc.querySelector("[data-oi-top='Top Post'] .b-top-statistic__body")!.className).toContain("m-without-img"); // no image proxy: no picture
    expect(texts(doc, "[data-oi-top='Top Post'] .b-summary-list__item")).toEqual(["$15.00 purchases", "3 views"]);
    bindPicks(doc);
    doc.querySelector<HTMLElement>("[data-oi-pick='tpost:views']")!.click();
    expect(currentPicks().tpost).toBe("views");
    applyStats(doc, "statistics/overview/top-highlights", both, D30, { picks: currentPicks() });
    expect(texts(doc, "[data-oi-top='Top Post'] .b-top-statistic__text")).toEqual(["Synthetic post text 1"]);
    resetPicks();
    expect(doc.querySelectorAll("[data-oi-top='Top Post']")).toHaveLength(1);
  });

  it("Engagement › Messages: OF's own mass messages of the period, in the owner's time zone", () => {
    const doc = load("statistics/engagement/messages");
    applyStats(doc, "statistics/engagement/messages", LIVE, D30);
    expect(unit(doc, "Messages")).toEqual(["40 -34.4%"]); // a Summary: OF prints the sign
    expect(texts(doc, ".b-statistics-page-content__wrapper > .b-elements-determinant__value")).toEqual(["40 messages $0.00 34.4%"]);
    const rows = [...doc.querySelectorAll(".b-statements-table tbody > tr")].filter(visible);
    expect(rows).toHaveLength(6);
    expect(rows[0].querySelector("strong")!.textContent!.trim()).toBe("Oct 14, 2026, 03:36 am");
    expect([...rows[0].querySelectorAll(":scope > td")].slice(1, 5).map((c) => c.textContent!.trim())).toEqual(["1", "0", "—", "—"]);
    expect(rows[0].querySelector(".b-top-statistic__text p")!.textContent).toBe("Synthetic mass message 1");
    expect(rows[0].querySelector(".b-content-inside-thumbs")).toBeNull();
    expect(rows[0].querySelector(".b-top-statistic__img")!.outerHTML).toBe('<div class="b-top-statistic__img b-top-statistic__img--placeholder"></div>'); // OF's, no media
    // OF's buttons: a canceled message "New message" (disabled) and the "Canceled" mark; an unsendable one Unsend and its "i".
    expect(rows[0].classList.contains("m-colored-bg")).toBe(true);
    const newMessage = rows[0].querySelector<HTMLButtonElement>(".b-top-statistic__btns button")!;
    expect([newMessage.textContent!.trim(), newMessage.disabled, newMessage.title]).toEqual(["New message", true, NOT_YET]);
    expect(rows[0].querySelector(".b-top-statistic__btns [aria-label='Canceled'] use")!.getAttribute("href")).toBe("#icon-undo");
    expect(rows[3].querySelector(".b-top-statistic__btns button")!.textContent!.trim()).toBe("Unsend");
    expect(rows[3].querySelector(".b-top-statistic__btns .g-icon-info")).not.toBeNull();
    const plainMsg = structuredClone(LIVE);
    (plainMsg.massMessages as { items: Record<string, unknown>[] }).items[0].isCanceled = false;
    applyStats(doc, "statistics/engagement/messages", plainMsg, D30);
    expect([...doc.querySelectorAll(".b-statements-table tbody > tr")].filter(visible)[0].querySelector(".b-top-statistic__btns")).toBeNull(); // neither: no buttons
  });

  it("Engagement › Messages: read by pages (OF's offset); \"Loading…\" while more may come, OF's \"No data\" once read", () => {
    const doc = load("statistics/engagement/messages");
    applyStats(doc, "statistics/engagement/messages", { ...LIVE, massMessages: { list: [], hasMore: true } }, D30);
    expect(texts(doc, ".b-statements-table .empty-message")).toEqual(["Loading…"]);
    applyStats(doc, "statistics/engagement/messages", { ...LIVE, massMessages: { items: [], hasMore: false } }, D30);
    expect(texts(doc, ".b-statements-table .empty-message")).toEqual(["No data during selected period"]);
    applyStats(doc, "statistics/engagement/messages", { ...LIVE, massMessages: undefined }, D30);
    expect(texts(doc, ".b-statements-table .empty-message")).toEqual([NOT_YET]); // not read (a Relay error): no claim
  });

  it("Engagement › Posts: OF's metric tabs, the period's top posts in OF's table; Purchases with its summary and chart", () => {
    const doc = load("statistics/engagement/posts");
    expect(statsRoute("postsTop", D30, { picks: { by: "comments" } })).toBe("/api/of/v2/posts/top?by=comments&limit=50&start=2026-09-17+00%3A00%3A00&end=2026-10-17+10%3A00%3A00");
    applyStats(doc, "statistics/engagement/posts", LIVE, D30, { img: (u) => `/img?u=${encodeURIComponent(u)}` });
    expect(texts(doc, "[data-oi-pick^='by:'].m-current")).toEqual(["Purchases"]);
    expect(texts(doc, "[data-oi-table='posts'] thead th")).toEqual(["Date", "Views", "Tips", "Price", "Purchases"]);
    const rows = [...doc.querySelectorAll("[data-oi-table='posts'] tbody > tr")].map((r) => [...r.querySelectorAll(":scope > td")].slice(0, 5).map((c) => c.textContent!.trim()));
    expect(rows).toEqual([["Oct 17, 2026, 01:52 am", "6", "$0.00", "—", "—"]]);
    expect(doc.querySelector("[data-oi-table='posts'] .b-top-statistic__text p")!.textContent).toBe("Synthetic post text 1");
    expect(doc.querySelector("[data-oi-table='posts'] .b-top-statistic__img img")!.getAttribute("src")).toMatch(/^\/img\?u=/);
    expect(texts(doc, ".b-statistics-page-content__wrapper > .empty-message")).toEqual([]);
    expect(texts(doc, "[data-oi-posts-summary]")).toEqual(["1 post $0.00"]); // purchases' change 0: no mark
    expect(chartSpecOf(doc.querySelector<HTMLCanvasElement>("[data-oi-posts-chart] canvas.b-chart__double-line__main")!)!.series).toMatchObject({ title: "Purchases", kind: "money" });
    expect(chartSpecOf(doc.querySelector<HTMLCanvasElement>("[data-oi-posts-chart] canvas.b-chart__double-line__aside")!)!.series.values.reduce((a, b) => a + b)).toBe(1);
    applyStats(doc, "statistics/engagement/posts", LIVE, D30, { picks: { by: "comments" } });
    expect(texts(doc, "[data-oi-pick^='by:'].m-current")).toEqual(["Comments"]);
    expect(texts(doc, "[data-oi-table='posts'] thead th")[2]).toBe("Comments");
    expect(texts(doc, "[data-oi-posts-summary]")).toEqual([]); // the chart filter does not reach OF: no summary, no chart
    expect(chartSpecOf(doc.querySelector<HTMLCanvasElement>("[data-oi-posts-chart] canvas.b-chart__double-line__main")!)).toBeUndefined();
    applyStats(doc, "statistics/engagement/posts", { ...LIVE, postsTop: { hasMore: false, items: [] } }, D30);
    expect(texts(doc, ".b-statistics-page-content__wrapper > .empty-message")).toEqual(["No Post activity during selected period"]);
  });

  it("Reach › Profile visitors: the stat rows (OF's counts and view durations) and OF's top countries with its Others row", () => {
    const doc = load("statistics/reach/profile-visitors");
    applyStats(doc, "statistics/reach/profile-visitors", LIVE, D30);
    const rows = (i: number) => [...doc.querySelectorAll("table")[i].querySelectorAll("tbody > tr")].filter(visible).map((r) => [...r.querySelectorAll("td")].map((c) => c.textContent!.trim()));
    expect(rows(0)).toEqual([["Profile visitors", "43", "157", "200"], ["View duration", "0h:01m", "0h:24m", "0h:26m"]]);
    expect(rows(1)).toEqual([["Malaysia", "3", "83", "86"], ["United States", "31", "10", "41"], ["Slovenia", "7", "31", "38"], ["Others", "2", "33", "35"]]);
    expect([...doc.querySelectorAll("table")[1].querySelectorAll("tbody > tr .vti__flag")].filter(visible).map((f) => f.className)).toEqual(["vti__flag my", "vti__flag us", "vti__flag si"]);
    expect(texts(doc, ".b-engagements-summary__item")).toEqual(["200 visitors"]);
    expect(unit(doc, "Profile visitors")).toEqual(["200 86.9%"]);
    expect(viewDuration(3600 * 5 + 3 * 60)).toBe("05h:03m");
    expect(viewDuration(86400 + 60)).toBe("1d 0h:01m");
  });

  it("the main charts: OF's pair with its titles and value kinds; Promotions' has no source and stays blank", () => {
    const visitors = load("statistics/reach/profile-visitors");
    applyStats(visitors, "statistics/reach/profile-visitors", LIVE, D30);
    const main = (d: Document) => chartSpecOf(d.querySelector<HTMLCanvasElement>("canvas.b-chart__double-line__main")!);
    const aside = (d: Document) => chartSpecOf(d.querySelector<HTMLCanvasElement>("canvas.b-chart__double-line__aside")!);
    expect(main(visitors)).toMatchObject({ ticks: 3, xLabels: false, series: { title: "Visitors", kind: "count" } });
    expect(main(visitors)!.series.values.reduce((a, b) => a + b)).toBe(200);
    expect(main(visitors)!.labels[0]).toBe("Sep 17, 2026");
    expect(aside(visitors)).toMatchObject({ ticks: 2, xLabels: true, series: { title: "View duration", kind: "duration" } });
    const fans = load("statistics/fans/subscriptions");
    applyStats(fans, "statistics/fans/subscriptions", LIVE, D30);
    expect(main(fans)!.series).toMatchObject({ title: "Earnings", kind: "money" }); // OF's order: earnings, then subscribes
    expect(aside(fans)!.series.values.reduce((a, b) => a + b)).toBe(10);
    const promo = load("statistics/reach/promotions");
    applyStats(promo, "statistics/reach/promotions", LIVE, D30);
    for (const c of promo.querySelectorAll<HTMLCanvasElement>(".b-statistics-page-content__wrapper canvas")) expect(chartSpecOf(c)).toBeUndefined();
    applyStats(fans, "statistics/fans/subscriptions", {}, D30);
    expect(main(fans)).toBeUndefined(); // no data: blank again
  });

  it("Reach › Profile visitors: OF's \"View all\" while OF has more countries, \"View less\" once all are read; Guests/Users stay disabled", () => {
    const doc = load("statistics/reach/profile-visitors");
    expect(statsRoute("profileStats", D30, { picks: { countries: "all" } })).toBe("/api/of/v2/users/me/profile/stats?limit=50&start=2026-09-17+00%3A00%3A00&end=2026-10-17+10%3A00%3A00");
    applyStats(doc, "statistics/reach/profile-visitors", LIVE, D30);
    const more = () => doc.querySelector<HTMLElement>("[data-oi-countries-more]")!;
    expect(visible(more())).toBe(true);
    expect(more().textContent!.trim()).toBe("View all");
    expect(more().querySelector("use")!.getAttribute("href")).toBe("#icon-arrow-down");
    bindPicks(doc);
    more().querySelector("button")!.click();
    expect(currentPicks().countries).toBe("all");
    applyStats(doc, "statistics/reach/profile-visitors", LIVE, D30, { picks: { countries: "all" } });
    expect(more().textContent!.trim()).toBe("View less");
    expect(more().querySelector("use")!.getAttribute("href")).toBe("#icon-arrow-up");
    resetPicks();
    const shown = structuredClone(LIVE);
    (shown.profileStats as { topCountries: { hasMore: boolean } }).topCountries.hasMore = false;
    applyStats(doc, "statistics/reach/profile-visitors", shown, D30);
    expect(visible(more())).toBe(false); // OF has no more: no button
    // The chart's Guests/Users split needs OF's `by`, which the Relay does not forward.
    for (const t of ["Guests", "Users"]) {
      const chip = [...doc.querySelectorAll<HTMLButtonElement>(".b-statistics-page-content__wrapper button.b-tabs__nav__link")].find((b) => b.textContent!.trim() === t)!;
      expect([chip.disabled, chip.title], t).toEqual([true, NOT_YET]);
    }
  });

  it("Reach › Tracking links: OF's Summary (tracking links, clicks, subscribers) when the period has statistics, else OF's text", () => {
    const doc = load("statistics/reach/tracking-links");
    applyStats(doc, "statistics/reach/tracking-links", LIVE, D30);
    expect(unit(doc, "Tracking links")).toEqual(["1 -75%"]); // a Summary: OF prints the sign
    expect(unit(doc, "Clicks")).toEqual(["0"]);
    expect(unit(doc, "Subscribers")).toEqual(["0"]);
    expect(texts(doc, ".l-wrapper__sidebar .empty-message")).toEqual([]);
    const none = structuredClone(LIVE);
    (none.campaign as { campaigns: { hasStatistic: boolean } }).campaigns.hasStatistic = false;
    applyStats(doc, "statistics/reach/tracking-links", none, D30);
    expect(unit(doc, "Tracking links")).toEqual([]);
    expect(texts(doc, ".l-wrapper__sidebar .empty-message")).toEqual(["No tracking links during selected period"]);
  });

  it("Fans › Subscriptions and Activity, Stories, Streaming: their figures, OF's empty text where the period has none", () => {
    const fans = load("statistics/fans/subscriptions");
    applyStats(fans, "statistics/fans/subscriptions", LIVE, D30);
    expect(texts(fans, ".b-statistics-page-content__wrapper > .b-elements-determinant__value")).toEqual(["10 Subscribers $0.00"]);
    expect(unit(fans, "Subscribers")).toEqual(["10 -9.1%"]);
    expect(unit(fans, "New subs/Renews")).toEqual(["10 / 0"]);
    const activity = load("statistics/fans/activity");
    applyStats(activity, "statistics/fans/activity", LIVE, D30);
    expect(unit(activity, "Subscriptions earnings")).toEqual(["$0.00"]);
    const stories = load("statistics/engagement/stories");
    applyStats(stories, "statistics/engagement/stories", LIVE, D30);
    expect(new Set(texts(stories, ".empty-message"))).toEqual(new Set(["No Stories activity during selected period"]));
    const streaming = load("statistics/engagement/streaming");
    applyStats(streaming, "statistics/engagement/streaming", LIVE, D30); // OF's count arrives as the string "0"
    expect(new Set(texts(streaming, ".empty-message"))).toEqual(new Set(["No Streaming activity during selected period"]));
  });

  it("Payout Requests and Referrals: OF's \"No data\" when none falls in the period; otherwise OF's rows of the period", () => {
    const doc = load("statistics/statements/payout-request");
    applyStats(doc, "statistics/statements/payout-request", LIVE, D30);
    expect(texts(doc, ".b-statistics-page-content__wrapper .empty-message")).toEqual(["No data during selected period"]);
    expect(doc.querySelector<HTMLElement>("[data-oi-table='payouts']")!.style.display).toBe("none");
    applyStats(doc, "statistics/statements/payout-request", LIVE, periodOf("all", NOW, TZ, START));
    expect(texts(doc, ".b-statistics-page-content__wrapper .empty-message")).toEqual([]);
    expect(texts(doc, "[data-oi-table='payouts'] thead th")).toEqual(["Date", "Invoice", "Amount"]);
    const rows = [...doc.querySelectorAll("[data-oi-table='payouts'] tbody > tr")].map((r) => [...r.querySelectorAll(":scope > td")].map((c) => c.textContent!.replace(/\s+/g, " ").trim()));
    expect(rows).toEqual([
      ["Jan 26, 2025, 10:05 pm", "60000000", "$85.23", "Payout has been processed Download invoice"],
      ["Jun 05, 2024, 03:02 pm", "60000001", "$95.73", "Payout has been processed Download invoice"],
    ]);
    const dl = doc.querySelector<HTMLButtonElement>("[data-oi-table='payouts'] .download-invoice-link")!;
    expect([dl.disabled, dl.title]).toEqual([true, NOT_YET]); // OF's invoice file: no Relay route
    expect(doc.querySelector("[data-oi-table='payouts'] .useable-icon")!.className).toBe("useable-icon m-payout-cell m-done");
    // A rejected request (OF's copy and its reason) and a pending one.
    const states = { list: [
      { invoiceId: "61", createdAt: "2026-10-10T08:00:00+00:00", amount: 20, currency: "USD", state: "rejected", rejectReason: "Synthetic reason" },
      { invoiceId: "62", createdAt: "2026-10-09T08:00:00+00:00", amount: 0, currency: "USD", state: "new", rejectReason: null },
    ], hasMore: false };
    applyStats(doc, "statistics/statements/payout-request", { ...LIVE, payoutRequests: states }, D30);
    expect(texts(doc, "[data-oi-table='payouts'] tbody td:last-child")).toEqual([
      "Payout request could not be processed and this amount was returned to your Current Balance. Reason: Synthetic reason",
      "Payout request is being processed",
    ]);
    expect(texts(doc, "[data-oi-table='payouts'] tbody td:nth-child(3)")).toEqual(["$20.00", "$0.00"]); // a real zero
    const ref = load("statistics/statements/referrals/earnings");
    applyStats(ref, "statistics/statements/referrals/earnings", LIVE, D30);
    expect(texts(ref, ".b-statistics-page-content__wrapper .empty-message")).toEqual(["No data during selected period"]);
    expect(texts(ref, ".b-elements-determinant__value.m-inline")).toEqual(["$0.00"]); // no referral balance, no referral payout ever
    applyStats(ref, "statistics/statements/referrals/earnings", { ...LIVE, referralRequests: { list: [states.list[0]], hasMore: false } }, D30);
    expect(ref.querySelector("[data-oi-table='referrals'] tbody .rejected .b-state-icon use")!.getAttribute("href")).toBe("#icon-alert");
  });

  it("Referrals: OF's Copy link is live (the link a dash until the Creator's); Referred creators and users are disabled", () => {
    const ref = load("statistics/statements/referrals/earnings");
    const copy = [...ref.querySelectorAll<HTMLButtonElement>(".b-referrals-state__content button")].find((b) => b.textContent!.trim() === "Copy link")!;
    expect([copy.disabled, copy.hasAttribute("data-oi-wired")]).toEqual([false, true]);
    expect(texts(ref, ".b-referrals-state__copy-url__link")).toEqual(["—"]);
    for (const name of ["Referred creators", "Referred users"]) {
      const tab = [...ref.querySelectorAll<HTMLButtonElement>("button.b-tabs__nav__link")].find((b) => b.textContent!.trim() === name)!;
      expect([tab.disabled, tab.title], name).toEqual([true, NOT_YET]);
    }
    expect(ref.querySelector("a[href='#'].b-tabs__nav__link")).toBeNull();
  });

  it("Statements › Earnings: the period's transactions only; none: OF's empty state alone (no summary or chart)", () => {
    const doc = load("statistics/statements/earnings");
    applyStats(doc, "statistics/statements/earnings", LIVE, D30);
    expect(texts(doc, ".b-statements-table .empty-message")).toEqual(["No data during selected period"]); // the fixture's are older
    expect(texts(doc, ".b-statements-table thead th")).toEqual([]); // OF's placeholder alone, no header
    expect(texts(doc, ".b-statistics-page-content__wrapper > .b-elements-determinant")).toEqual([]);
    applyStats(doc, "statistics/statements/earnings", LIVE, periodOf("all", NOW, TZ, START));
    expect(texts(doc, ".b-statistics-page-content__wrapper .b-elements-determinant__value.m-inline")).toEqual(["$0.00 ( $0.00 Gross)"]);
    const rows = [...doc.querySelectorAll(".b-statements-table tbody > tr")].filter(visible);
    expect(rows.map((r) => r.querySelector(".b-statements-text-table")!.textContent)).toEqual(["Subscription from Fan One", ...Array(5).fill("Payment for message from Fan Two")]);
    expect(rows[0].querySelector(".m-width-statements strong > span")!.textContent).toBe("May 19, 2026,");
    // Still reading towards the period: "Loading…", never a claim.
    applyStats(doc, "statistics/statements/earnings", { ...LIVE, transactions: { list: [], hasMore: true } }, D30);
    expect(texts(doc, ".b-statements-table .empty-message")).toEqual(["Loading…"]);
  });

  it("Statements › Earnings' type tabs: OF's current tab, its summary from the overview's figures, Tips' sub-tabs", () => {
    const doc = load("statistics/statements/earnings");
    const data = { ...earning({ earnings: [12, 15, 50], fans: [8, 10, 0], messages: [4, 5, -20], posts: [0, 0, 0], streams: [0, 0, 0] }), transactions: { list: [], hasMore: false } };
    applyStats(doc, "statistics/statements/earnings", data, D30, { picks: { type: "subscribes" } });
    const current = () => texts(doc, "[data-oi-pick^='type:']:not([data-oi-href]).m-current");
    expect(current()).toEqual(["Subscriptions"]);
    expect(doc.querySelector("[data-oi-pick='type:subscribes']")!.className).toContain("m-no-pointer");
    applyStats(doc, "statistics/statements/earnings", { ...data, transactions: { list: [{ createdAt: "2026-10-12T09:41:07+00:00", amount: 10, fee: 2, net: 8, status: "done", description: "Synthetic" }], hasMore: false } }, D30, { picks: { type: "subscribes" } });
    expect(texts(doc, ".b-statistics-page-content__wrapper .b-elements-determinant__value.m-inline")).toEqual(["$8.00 ( $10.00 Gross)"]);
    applyStats(doc, "statistics/statements/earnings", { ...data, transactions: { list: [{ createdAt: "2026-10-12T09:41:07+00:00", amount: 5, fee: 1, net: 4, status: "done" }], hasMore: false } }, D30, { picks: { type: "chat_messages" } });
    expect(texts(doc, ".b-statistics-page-content__wrapper .b-elements-determinant__value.m-inline")).toEqual(["$4.00 ( $5.00 Gross) 20%"]);
    expect(doc.querySelector(".b-statistics-page-content__wrapper .b-statistics-level")!.className).toContain("m-level-down");
    expect(texts(doc, "[data-oi-tips-tabs] button")).toEqual([]);
    applyStats(doc, "statistics/statements/earnings", data, D30, { picks: { type: "tips" } });
    expect(texts(doc, "[data-oi-tips-tabs] button")).toEqual(["All tips", "Profile", "Posts", "Messages", "Streams", "Stories"]);
    expect([...doc.querySelectorAll<HTMLButtonElement>("[data-oi-tips-tabs] button")].map((b) => b.disabled)).toEqual([false, true, true, true, true, true]);
    bindPicks(doc);
    setPick("tips", "chat");
    doc.querySelector<HTMLElement>("[data-oi-pick='type:post']")!.click();
    expect([currentPicks().type, currentPicks().tips]).toEqual(["post", "all"]); // OF opens Tips on "All tips" again
    setPick("type", "total");
  });

  it("the Statements sidebar's Earnings rows open Statements › Earnings on their type tab, as OF's", () => {
    const doc = load("statistics/statements/disputes");
    applyStats(doc, "statistics/statements/disputes", earning({ earnings: [12, 15, 50], fans: [8, 10, 0], messages: [4, 5, -20], posts: [0, 0, 0], streams: [0, 0, 0] }), D30);
    const row = doc.querySelector<HTMLElement>("[data-oi-pick='type:chat_messages'][data-oi-href]")!;
    expect(row.classList.contains("g-pointer-cursor")).toBe(true);
    bindPicks(doc);
    let went: string | null = null;
    doc.addEventListener("click", (ev) => (went = (ev.target as Element).closest("a")?.getAttribute("href") ?? went));
    row.click();
    expect(currentPicks().type).toBe("chat_messages");
    expect(went).toBe("/of-manager/statistics/statements/earnings");
    resetPicks();
    expect(currentPicks().type).toBe("chat_messages"); // kept across the tabs, as OF keeps it
    setPick("type", "total");
  });

  it("paging: OF's pages of 50 by offset, the next while OF has more or a page is full; none when a page repeats", () => {
    expect(pagedRoute("transactions", 50, "tips")).toBe("/api/of/v2/payouts/transactions?limit=50&offset=50&type=tips");
    expect(pagedRoute("payoutRequests", 0)).toBe("/api/of/v2/payouts/requests?limit=50&offset=0");
    const page = (n: number, from = 0, hasMore?: boolean) => ({ list: Array.from({ length: n }, (_, i) => ({ id: from + i })), ...(hasMore === undefined ? {} : { hasMore }) });
    expect(nextOffset(page(50, 0, true), [page(50, 0, true)])).toBe(50);
    expect(nextOffset(page(20, 0, false), [page(20)])).toBeUndefined();
    expect(nextOffset(page(50), [page(50)])).toBe(50); // no hasMore (payout requests): a full page may have more
    expect(nextOffset(page(12), [page(12)])).toBeUndefined();
    expect(nextOffset(page(50, 0, true), [page(50, 0, true), page(50, 0, true)])).toBeUndefined(); // OF ignored the offset
  });
});

describe("applyStats with earnings in the period", () => {
  const DATA = earning({ earnings: [12, 15, 50], fans: [8, 10, 0], messages: [4, 5, -20], posts: [0, 0, 0], streams: [0, 0, 0] });

  it("the Statements sidebar lists OF's categories with earnings, each change signed; Tips $0.00 is not listed", () => {
    const doc = load("statistics/statements/disputes");
    applyStats(doc, "statistics/statements/disputes", DATA, D30);
    expect(unit(doc, "Total")).toEqual(["$12.00 50%"]);
    expect(unit(doc, "Subscriptions")).toEqual(["$8.00"]);
    expect(unit(doc, "Messages")).toEqual(["$4.00 -20%"]);
    expect(unit(doc, "Tips")).toEqual([]);
    expect(texts(doc, "[data-oi-earnings-empty]")).toEqual([]);
  });

  it("Overview › Earnings: the sums per category; Tips $0.00 once the others add up to the total, a dash when they do not", () => {
    const doc = load("statistics/overview/earnings");
    applyStats(doc, "statistics/overview/earnings", DATA, D30);
    const row = (name: string) => texts(doc, `.b-stats-row__label:has(input[name='${name}']) .b-stats-row__val`);
    expect(row("total")).toEqual(["$15.00", "$12.00"]);
    expect(row("subscribes")).toEqual(["$10.00", "$8.00"]);
    expect(row("chat_messages")).toEqual(["$5.00", "$4.00"]);
    expect(row("tips")).toEqual(["$0.00", "$0.00"]);
    const rest = earning({ earnings: [20, 25, 0], fans: [8, 10, 0], messages: [4, 5, 0], posts: [0, 0, 0], streams: [0, 0, 0] });
    expect(derive(rest).tips).toBeUndefined();
    applyStats(doc, "statistics/overview/earnings", rest, D30);
    expect(row("tips")).toEqual(["—", "—"]); // $8.00 the overview does not place: no made-up split
    expect(row("ref")).toEqual(["$0.00", "$0.00"]); // no referral balance and no referral payout ever
  });

  it("All time: no change marks (OF shows none for it)", () => {
    const doc = load("statistics/overview/earnings");
    applyStats(doc, "statistics/overview/earnings", DATA, periodOf("all", NOW, TZ, START));
    expect(unit(doc, "Earnings")).toEqual(["$12.00"]);
    expect(texts(doc, "[data-oi-period-title]")).toEqual(["All time"]);
    expect(texts(doc, "[data-name='period']")).toEqual([]); // OF draws no period row for All time
  });
});
