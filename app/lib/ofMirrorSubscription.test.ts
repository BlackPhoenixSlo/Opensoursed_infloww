import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import { applySubscription, ASKS, OF_DISALLOWS, PRICE_FIRST, bindSubscription, bindTrackingSort, campaignLink, LIST_MAX_HEIGHT, listOf, mePromotions, subscriptionParts, trackingHref, trackingPick, trackingRoute, trackingViewOf, TRACKING_SORT, trialLength, type SubData, type SubHandlers, type TrackingShareHandlers } from "./ofMirrorSubscription";
import { bindWrites, NOT_YET, ofConfirm, READ_ONLY } from "./ofMirrorWrites";
import { NO_BUNDLES_LEFT } from "./ofMirrorOffers";

const PROMOTIONS = "settings/subscription/promotion-campaign";
const TRACKING = "settings/subscription/tracking-links";
const TRIALS = "settings/subscription/trial-links";
const load = (page: string) => {
  document.documentElement.innerHTML = readFileSync(resolve(__dirname, `../public/of-mirror/pages/${page}.html`), "utf8");
  return document;
};
const flush = () => new Promise((r) => setTimeout(r, 0));
const ME = { id: 7, username: "synthmodel", name: "Synth Model", avatar: null, subscribePrice: 10, canCreateTrial: true };
const rows = () => [...document.querySelectorAll<HTMLElement>("[data-oi-row]")];
const textOf = (el: Element | null | undefined) => (el?.textContent ?? "").replace(/\s+/g, " ").trim();
const buttons = (el: Element) => [...el.querySelectorAll<HTMLButtonElement>("button")].map((b) => [textOf(b) || b.getAttribute("aria-label"), b.disabled]);
const prompts = () => [...document.querySelectorAll<HTMLElement>(".infinite-loading-container > .infinite-status-prompt")].map((p) => p.style.display !== "none");
const handlers = (over: Partial<SubHandlers> = {}): SubHandlers & { [k: string]: ReturnType<typeof vi.fn> } =>
  ({
    remove: vi.fn(() => Promise.resolve()),
    copy: vi.fn(() => Promise.resolve()),
    confirm: vi.fn(() => Promise.resolve(true)),
    retry: vi.fn(),
    ...over,
  }) as never;
const unbinds: (() => void)[] = [];
afterEach(() => {
  while (unbinds.length) unbinds.pop()!();
});

describe("mePromotions (OF's settings list: users/me's promotions)", () => {
  it("none while users/me has no promotions (a free model)", () => {
    expect(mePromotions(undefined)).toEqual([]);
    expect(mePromotions({ subscribePrice: 0 })).toEqual([]);
  });
  it("sorted by type, rows without an id dropped; only the first when several are related", () => {
    const new_ = { id: 1, type: "new" }, all = { id: 2, type: "all" }, expired = { id: 3, type: "expired" };
    expect(mePromotions({ promotions: [new_, { type: "all" }, expired, all] }).map((p) => p.id)).toEqual([2, 3, 1]);
    expect(mePromotions({ promotions: [{ ...new_, hasRelatedPromo: true }, { ...all, hasRelatedPromo: true }] }).map((p) => p.id)).toEqual([1]);
  });
});

describe("subscriptionParts and listOf", () => {
  it("reads promotions and bundles on the price and promotion pages, campaigns and trials on their tabs", () => {
    expect(subscriptionParts("settings/subscription")).toEqual(["promotions", "bundles"]);
    expect(subscriptionParts(`${PROMOTIONS}/modal-2`)).toEqual(["promotions", "bundles"]);
    expect(subscriptionParts(TRACKING)).toEqual(["campaigns"]);
    expect(subscriptionParts(`${TRIALS}/state-kebab`)).toEqual(["trials"]);
    expect(subscriptionParts("settings/profile")).toEqual([]);
    expect(subscriptionParts("home/index")).toEqual([]);
  });

  it("takes a bare array, {list} or {items}", () => {
    expect(listOf([1])).toEqual([1]);
    expect(listOf({ list: [2] })).toEqual([2]);
    expect(listOf({ items: [3], hasMore: false })).toEqual([3]);
    expect(listOf(null)).toEqual([]);
  });

  it("formats OF's trial length and tracking link", () => {
    expect(trialLength(1)).toBe("1 day");
    expect(trialLength(7)).toBe("7 days");
    expect(trialLength(30)).toBe("1 month");
    expect(trialLength(360)).toBe("12 months");
    expect(campaignLink("synthmodel", 3)).toBe("https://onlyfans.com/synthmodel/c3");
  });
});

describe("the generated pages carry no example row", () => {
  it.each([PROMOTIONS, TRACKING, TRIALS])("%s: only hidden templates and OF's empty state", (page) => {
    const d = load(page);
    for (const t of d.querySelectorAll<HTMLElement>("[data-oi-template]")) expect(t.style.display).toBe("none");
    expect(d.querySelectorAll(".b-offer-join:not([data-oi-template]):not([data-oi-template] *):not(.m-only-start-btn)").length).toBe(0);
    if (page !== PROMOTIONS) expect(prompts()).toEqual([false, true, false, false]);
  });
});

describe("promotions and bundles", () => {
  const live = { id: 11, price: 0, type: "new", subscribeDays: 30, subscribeCounts: 0, claimsCount: 4, isFinished: false, canClaim: true, message: "<p>Synthetic welcome</p>", createdAt: "2026-03-02T12:00:00+00:00", finishedAt: null };
  const ended = { id: 12, price: 5, type: "expired", subscribeDays: 31, subscribeCounts: 3, claimsCount: 1, isFinished: true, canClaim: false, message: "", createdAt: "2025-09-30T12:00:00+00:00", finishedAt: "2025-10-07T12:00:00+00:00" };
  const data: SubData = { promotions: { rows: [live, ended] }, bundles: { rows: [{ id: 21, price: 20.35, duration: 3, discount: 30 }, { id: 22, price: 60, duration: 6, discount: 0 }] } };

  it("draws one card per promotion and bundle as OF does, in the Relay's order", () => {
    const d = load(PROMOTIONS);
    applySubscription(d, PROMOTIONS, data, ME, true);
    const [p1, p2, b1, b2] = rows();
    expect(rows()).toHaveLength(4);
    expect(textOf(p1.querySelector(".b-offer-join__details"))).toBe("Limited offer - Free trial for 30 days!");
    expect(textOf(p1.querySelector(".b-offer-join__left-time"))).toBe("For new subscribers");
    expect(textOf(p1.querySelector(".b-offer-join__bubble__text"))).toBe("Synthetic welcome");
    expect(textOf(p1.querySelector(".b-fans__item__list"))).toBe("Started Mar 2, 2026 Claims count 4");
    expect(buttons(p1)).toEqual([["4", true], ["Stop promotion", false], ["Copy link to profile", false]]);
    expect(p1.querySelector("button[data-oi-finish]")?.getAttribute("data-oi-finish")).toBe(String(live.id));
    expect(textOf(p2.querySelector(".b-offer-join__details"))).toBe("Limited offer - 50% off for 31 days");
    expect(p2.querySelector(".b-offer-join__details")!.classList.contains("g-gray-text")).toBe(true);
    expect(textOf(p2.querySelector(".b-offer-join__left-time"))).toBe("For expired subscribers ended Oct 7 left 3");
    expect(p2.querySelector(".b-offer-join__bubble")).toBeNull();
    expect(buttons(p2)).toEqual([["1", true], ["Remove", false]]);
    expect(textOf(b1)).toBe("$20.35 USD total for 3 months -30%");
    expect(textOf(b2)).toBe("$60 USD total for 6 months");
    expect(buttons(b1)).toEqual([["Delete", false]]);
    applySubscription(d, PROMOTIONS, data, ME, true);
    expect(rows()).toHaveLength(4);
    applySubscription(d, PROMOTIONS, {}, ME, true);
    expect(rows()).toHaveLength(0);
  });

  it("Copy link to profile copies the Creator's profile with OF's toast; Remove deletes the ended promotion without asking", async () => {
    const d = load(PROMOTIONS);
    applySubscription(d, PROMOTIONS, data, ME, true);
    const h = handlers();
    unbinds.push(bindSubscription(d, h));
    const [p1, p2] = rows();
    [...p1.querySelectorAll("button")].find((b) => textOf(b) === "Copy link to profile")!.click();
    await flush();
    expect(h.copy).toHaveBeenCalledWith("https://onlyfans.com/synthmodel");
    expect(textOf(d.querySelector("#oi-toast .toast__text"))).toBe("Link copied");
    [...p2.querySelectorAll("button")].find((b) => textOf(b) === "Remove")!.click();
    expect(h.confirm).not.toHaveBeenCalled();
    expect(h.remove).toHaveBeenCalledWith("/api/of/v2/promotions/12");
    await flush();
    expect(p2.isConnected).toBe(false);
  });

  it("a bundle's Delete asks first, and a failed delete keeps the row with the error", async () => {
    const d = load(PROMOTIONS);
    applySubscription(d, PROMOTIONS, data, ME, true);
    const no = handlers({ confirm: vi.fn(() => Promise.resolve(false)) });
    const unbind = bindSubscription(d, no);
    const b1 = rows()[2];
    b1.querySelector<HTMLButtonElement>("button[aria-label='Delete']")!.click();
    expect(no.confirm).toHaveBeenCalledWith(ASKS.bundle);
    await flush();
    expect(no.remove).not.toHaveBeenCalled();
    unbind();
    const h = handlers({ remove: vi.fn(() => Promise.reject(new Error("relay 502"))) });
    unbinds.push(bindSubscription(d, h));
    b1.querySelector<HTMLButtonElement>("button[aria-label='Delete']")!.click();
    await flush();
    expect(h.remove).toHaveBeenCalledWith("/api/of/v2/subscriptions/bundles/21");
    await flush();
    expect(b1.isConnected).toBe(true);
    expect(textOf(d.getElementById("oi-note"))).toBe("Could not delete: relay 502");
  });

  it("OF's ModalConfirm: its title, text and buttons; Delete resolves true, Cancel, the backdrop and Escape false", async () => {
    const d = load(PROMOTIONS);
    const ask = (act: () => void) => {
      const p = ofConfirm(d, ASKS.bundle);
      const m = d.getElementById("ModalConfirm")!;
      expect(m.classList.contains("m-confirm")).toBe(true);
      expect(textOf(m.querySelector(".modal-title"))).toBe("Delete subscription bundle");
      expect(textOf(m.querySelector(".dialog_message"))).toBe("Are you sure you want to delete this subscription bundle?");
      expect([...m.querySelectorAll(".modal-footer button")].map(textOf)).toEqual(["Cancel", "Delete"]);
      expect(d.getElementById("ModalConfirm___BV_modal_backdrop_")).not.toBeNull();
      act();
      return p;
    };
    const buttons = () => [...d.querySelectorAll<HTMLButtonElement>("#ModalConfirm .modal-footer button")];
    expect(await ask(() => buttons()[1].click())).toBe(true);
    expect(d.getElementById("ModalConfirm")).toBeNull();
    expect(d.getElementById("ModalConfirm___BV_modal_backdrop_")).toBeNull();
    expect(await ask(() => buttons()[0].click())).toBe(false);
    expect(await ask(() => d.getElementById("ModalConfirm")!.click())).toBe(false);
    expect(await ask(() => d.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" })))).toBe(false);
    expect(d.body.classList.contains("modal-open")).toBe(false);
  });

  it("the row buttons are marked wired, so ofMirrorWrites' click fallback leaves them alone", () => {
    const d = load(PROMOTIONS);
    applySubscription(d, PROMOTIONS, data, ME, true);
    unbinds.push(bindWrites(d, PROMOTIONS, null, true));
    unbinds.push(bindSubscription(d, handlers()));
    for (const b of rows().flatMap((r) => [...r.querySelectorAll<HTMLButtonElement>("button:not([disabled])")])) {
      expect(b.hasAttribute("data-oi-wired"), textOf(b)).toBe(true);
      b.click();
      expect(textOf(d.getElementById("oi-note")), textOf(b)).not.toBe(READ_ONLY);
    }
  });

  it("a long promotion list scrolls in its own box, so Subscription bundles stays in view (ours)", () => {
    const d = load(PROMOTIONS);
    const many = Array.from({ length: 12 }, (_, i) => ({ ...ended, id: 100 + i }));
    applySubscription(d, PROMOTIONS, { ...data, promotions: { rows: many } }, ME, true);
    const box = d.querySelector<HTMLElement>("[data-oi-template='promotion-row']")!.parentElement!;
    expect(box.hasAttribute("data-oi-scroll")).toBe(true);
    expect(box.style.overflowY).toBe("auto");
    expect(box.style.maxHeight).toBe(LIST_MAX_HEIGHT);
    expect(box.style.flexWrap).toBe("nowrap");
    expect(box.querySelectorAll(":scope > [data-oi-row]")).toHaveLength(12);
    const bundle = d.querySelector("[data-oi-template='bundle-row']")!;
    expect(box.contains(bundle)).toBe(false);
  });
});

describe("tracking links", () => {
  const data: SubData = {
    campaigns: {
      rows: [
        { id: 31, campaignCode: 5, campaignName: "Synthetic link", countSubscribers: 2, countTransitions: 9, createdAt: "2026-04-16T00:00:00+00:00", isDeleted: false },
        { id: 32, campaignCode: 6, campaignName: "Old link", countSubscribers: 0, countTransitions: 0, createdAt: "2026-01-02T00:00:00+00:00", isDeleted: true },
      ],
    },
  };

  it("draws each link with its counts; a deleted one is gray with Remove and no Copy link", () => {
    const d = load(TRACKING);
    applySubscription(d, TRACKING, data, ME, true);
    const [a, b] = rows();
    expect(rows()).toHaveLength(2);
    expect(textOf(a.querySelector(".b-offer-join__details"))).toBe("Synthetic link");
    expect(textOf(a.querySelector(".b-fans__item__list"))).toBe("Tracking link created Apr 16, 2026 Subscribers count 2 Clicks count 9");
    expect(buttons(a)).toEqual([["Delete", false], ["Copy link", false]]);
    expect(textOf(b.querySelector(".b-fans__item__list"))).toBe("Tracking link created Jan 2, 2026 Subscribers count No subscribers yet Clicks count 0");
    expect(buttons(b)).toEqual([["Remove", false], ["Copy link", true]]);
    expect(prompts()).toEqual([false, false, false, false]);
  });

  it("Copy link copies OF's tracking URL; Delete asks, then DELETEs /campaigns/{id}", async () => {
    const d = load(TRACKING);
    applySubscription(d, TRACKING, data, ME, true);
    const h = handlers();
    unbinds.push(bindSubscription(d, h));
    const [a] = rows();
    [...a.querySelectorAll("button")].find((b) => textOf(b) === "Copy link")!.click();
    expect(h.copy).toHaveBeenCalledWith("https://onlyfans.com/synthmodel/c5");
    [...a.querySelectorAll("button")].find((b) => textOf(b) === "Delete")!.click();
    expect(h.confirm).toHaveBeenCalledWith(ASKS.campaign);
    await flush();
    expect(h.remove).toHaveBeenCalledWith("/api/of/v2/campaigns/31");
    await flush();
    expect(a.isConnected).toBe(false);
  });

  it("a deleted link's Remove asks OF's Delete tracking link (CampaignItem: one confirm whatever isDeleted)", () => {
    const d = load(TRACKING);
    applySubscription(d, TRACKING, data, ME, true);
    const h = handlers();
    unbinds.push(bindSubscription(d, h));
    [...rows()[1].querySelectorAll("button")].find((b) => textOf(b) === "Remove")!.click();
    expect(h.confirm).toHaveBeenCalledWith(ASKS.campaign);
  });

  it("shows OF's list status: the preloader, No results, and Something went wrong with a working Retry", () => {
    const d = load(TRACKING);
    applySubscription(d, TRACKING, { campaigns: { loading: true } }, ME, true);
    expect(prompts()).toEqual([true, false, false, false]);
    applySubscription(d, TRACKING, { campaigns: { rows: [] } }, ME, true);
    expect(prompts()).toEqual([false, true, false, false]);
    applySubscription(d, TRACKING, { campaigns: { rows: [], error: true } }, ME, true);
    expect(prompts()).toEqual([false, false, false, true]);
    const h = handlers();
    unbinds.push(bindSubscription(d, h));
    const retry = [...d.querySelectorAll<HTMLButtonElement>(".infinite-status-prompt button")].find((b) => textOf(b) === "Retry")!;
    expect(retry.hasAttribute("data-oi-wired")).toBe(true);
    retry.click();
    expect(h.retry).toHaveBeenCalledTimes(1);
  });
});

describe("tracking links Sort (the Relay sorts; `inferred` field names)", () => {
  const view = (q: string) => trackingViewOf(new URLSearchParams(q));
  const click = (el: Element | null) => el!.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
  const menu = () => [...document.querySelectorAll<HTMLElement>("#oi-menu [data-oi-value]")];

  it.each(TRACKING_SORT.flatMap((f) => (["asc", "desc"] as const).map((s) => [f.value, s] as const)))("%s %s: the GET names exactly that field and order", (field, sort) => {
    const v = trackingPick(trackingPick(view(""), "field", field), "order", sort);
    expect(trackingRoute(view(trackingHref(v).split("?")[1]))).toBe(`/api/of/v2/campaigns?field=${field}&sort=${sort}`);
  });
  it("bare until a sort is picked; an unknown field or order is dropped", () => {
    expect(trackingRoute(view(""))).toBe("/api/of/v2/campaigns");
    expect(trackingRoute(view("field=bogus&sort=up"))).toBe("/api/of/v2/campaigns");
    expect(trackingRoute(view("field=name"))).toBe("/api/of/v2/campaigns?field=name&sort=desc");
    expect(trackingRoute(view("sort=asc"))).toBe("/api/of/v2/campaigns?field=created_date&sort=asc");
  });

  it.each([TRACKING, `${TRACKING}/modal-1`, `${TRACKING}/state-kebab`])("%s: Sort is Wired, its title dropped (Live pass, D1), and opens OF's menu", (page) => {
    const d = load(page);
    const navigate = vi.fn();
    unbinds.push(bindTrackingSort(d, page, view("field=name&sort=asc"), navigate));
    const sort = d.querySelector<HTMLButtonElement>("button[aria-label='Sort']")!;
    expect([sort.disabled, sort.hasAttribute("data-oi-wired"), sort.hasAttribute("title")]).toEqual([false, true, false]);
    expect(textOf(d.querySelector(".b-content-filter__title"))).toBe("Name");
    click(sort);
    expect(menu().map((r) => textOf(r))).toEqual(["Created", "Name", "Subscribers count", "Clicks count", "Shared", "Ascending", "Descending"]);
    click(menu().find((r) => r.dataset.oiValue === "clicks_count")!);
    expect(navigate).toHaveBeenLastCalledWith("/of-manager/settings/subscription/tracking-links?field=clicks_count&sort=asc");
  });

  it("no model: Sort gives the Select-a-model note; another page binds nothing", () => {
    const d = load(TRACKING);
    unbinds.push(bindTrackingSort(d, TRACKING, view(""), null));
    click(d.querySelector("button[aria-label='Sort']"));
    expect(menu()).toHaveLength(0);
    expect(textOf(d.getElementById("oi-note"))).toContain("Select a model");
    const t = load(TRIALS);
    unbinds.push(bindTrackingSort(t, TRIALS, view(""), vi.fn()));
    expect(t.querySelector("button[aria-label='Sort']")!.hasAttribute("data-oi-wired")).toBe(false);
  });

  it("the kebab State page's radios: checked as the URL, each Select link the menu's pick; titles dropped (Live pass, D1)", () => {
    const page = `${TRACKING}/state-kebab`;
    const d = load(page);
    const v = view("field=subscribers_counts");
    unbinds.push(bindTrackingSort(d, page, v, null));
    const radios = [...d.querySelectorAll<HTMLInputElement>("input[name='campaign-field'], input[name='campaign-sort']")];
    expect(radios).toHaveLength(7);
    for (const r of radios) expect([r.disabled, r.hasAttribute("data-oi-wired"), r.hasAttribute("title")]).toEqual([false, true, false]);
    expect(radios.filter((r) => r.checked).map((r) => r.value)).toEqual(["subscribers_counts", "desc"]);
    const href = (value: string) => radios.find((r) => r.value === value)!.closest("[role='menuitem']")!.querySelector("a.of-state-link")!.getAttribute("href");
    expect(href("name")).toBe("/of-manager/settings/subscription/tracking-links?field=name&sort=desc");
    expect(href("asc")).toBe("/of-manager/settings/subscription/tracking-links?field=subscribers_counts&sort=asc");
    expect(d.querySelector(".b-dropdown-wrapper > a.of-state-link[aria-label='Toggle']")!.getAttribute("href")).toBe("/of-manager/settings/subscription/tracking-links?field=subscribers_counts");
  });

  it("draws the rows in the Relay's order (no client reorder)", () => {
    const d = load(TRACKING);
    const names = ["Zeta", "Alpha", "Mid"];
    applySubscription(d, TRACKING, { campaigns: { rows: names.map((n, i) => ({ id: i + 1, campaignName: n, createdAt: "2026-01-0" + (i + 1) + "T00:00:00+00:00" })) } }, ME, true);
    expect(rows().map((r) => textOf(r.querySelector(".b-offer-join__details")))).toEqual(names);
  });
});

describe("tracking links Shared with you and the share hint", () => {
  const view = (q: string) => trackingViewOf(new URLSearchParams(q));
  const click = (el: Element | null) => el!.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
  const fx = JSON.parse(readFileSync(resolve(__dirname, "__fixtures__/of/settings-tracking-share-body.json"), "utf8")) as { relay: { campaignId: number; userId: number } };
  const OWN = { id: fx.relay.campaignId, campaignCode: 2, campaignName: "Mid link", countSubscribers: 3, countTransitions: 20, createdAt: "2026-03-01T00:00:00+00:00", isDeleted: false };
  const PEER = { id: 7491, campaignCode: 91, campaignName: "Peer link", countSubscribers: 4, countTransitions: 12, createdAt: "2026-02-15T00:00:00+00:00", isDeleted: false, user: { username: "synthowner" } };
  const share = (): TrackingShareHandlers & { [k: string]: ReturnType<typeof vi.fn> } =>
    ({ searchPerformers: vi.fn().mockResolvedValue([{ id: fx.relay.userId, name: "Synthetic Peer", username: "synthpeer" }]), share: vi.fn().mockResolvedValue({ success: true }) }) as never;

  it("the tab's read is OF's share-access GET; Name sorts as `shared` there; Your links stays as it was", () => {
    expect(view("")).toEqual({ field: null, sort: null });
    expect(trackingRoute(view("tab=shared"))).toBe("/api/of/v2/campaigns/share-access");
    expect(trackingRoute(view("tab=shared&field=name&sort=asc"))).toBe("/api/of/v2/campaigns/share-access?field=shared&sort=asc");
    expect(trackingRoute(view("tab=shared&field=clicks_count"))).toBe("/api/of/v2/campaigns/share-access?field=clicks_count&sort=desc");
    expect(trackingRoute(view("tab=bogus&field=name"))).toBe("/api/of/v2/campaigns?field=name&sort=desc");
    expect(trackingHref(trackingPick(view("tab=shared"), "field", "name"))).toBe("/of-manager/settings/subscription/tracking-links?field=name&sort=desc&tab=shared");
  });

  it.each([TRACKING, `${TRACKING}/modal-1`, `${TRACKING}/state-kebab`])("%s: Shared with you is Wired with its title kept and goes to the tab, the sort kept", (page) => {
    const d = load(page);
    const navigate = vi.fn();
    unbinds.push(bindTrackingSort(d, page, view("field=name&sort=asc"), navigate, share()));
    const tab = d.querySelector<HTMLButtonElement>("#Shared-with-you")!;
    expect([tab.disabled, tab.hasAttribute("data-oi-wired"), tab.title, tab.classList.contains("m-current")]).toEqual([false, true, NOT_YET, false]);
    expect(d.querySelector("#Your-links")!.classList.contains("m-current")).toBe(true);
    click(tab);
    expect(navigate).toHaveBeenLastCalledWith("/of-manager/settings/subscription/tracking-links?field=name&sort=asc&tab=shared");
  });

  it("on the tab: it is current, Your links goes back (tab dropped); no model: both give the Select-a-model note", () => {
    const d = load(TRACKING);
    const navigate = vi.fn();
    unbinds.push(bindTrackingSort(d, TRACKING, view("tab=shared"), navigate, share()));
    expect(d.querySelector("#Shared-with-you")!.classList.contains("m-current")).toBe(true);
    click(d.querySelector("#Shared-with-you"));
    expect(navigate).not.toHaveBeenCalled();
    click(d.querySelector("#Your-links"));
    expect(navigate).toHaveBeenLastCalledWith("/of-manager/settings/subscription/tracking-links");
    unbinds.pop()!();
    unbinds.push(bindTrackingSort(d, TRACKING, view(""), null, null));
    click(d.querySelector("#Shared-with-you"));
    expect(textOf(d.getElementById("oi-note"))).toContain("Select a model");
  });

  it("Shared with you rows: \"Shared from @owner\", no Delete, Copy link the owner's URL; empty: OF's No results", () => {
    const d = load(TRACKING);
    applySubscription(d, TRACKING, { campaigns: { rows: [PEER] } }, ME, true, undefined, false, undefined, true);
    const [a] = rows();
    expect(textOf(a.querySelector(".b-hint-offer"))).toBe("Shared from @synthowner");
    expect(a.querySelector("[data-oi-share]")).toBeNull();
    expect(buttons(a)).toEqual([["Copy link", false]]);
    const h = handlers();
    unbinds.push(bindSubscription(d, h));
    click([...a.querySelectorAll("button")].find((b) => textOf(b) === "Copy link")!);
    expect(h.copy).toHaveBeenCalledWith("https://onlyfans.com/synthowner/c91");
    applySubscription(d, TRACKING, { campaigns: { rows: [] } }, ME, true, undefined, false, undefined, true);
    expect(prompts()).toEqual([false, true, false, false]);
  });

  it("own rows: the hint is Wired (title kept); a shared link says \"Shared with @user\"; a deleted one has none", () => {
    const d = load(TRACKING);
    const rowsIn = [OWN, { ...OWN, id: 6103, sharedWith: { username: "synthpeer" } }, { ...OWN, id: 6104, isDeleted: true }];
    applySubscription(d, TRACKING, { campaigns: { rows: rowsIn } }, ME, true);
    const [a, b, c] = rows();
    const hint = a.querySelector<HTMLElement>(".b-hint-offer")!;
    expect([hint.dataset.oiCampaign, hint.hasAttribute("data-oi-wired"), hint.getAttribute("aria-disabled"), hint.title, hint.tabIndex]).toEqual([String(fx.relay.campaignId), true, null, NOT_YET, 0]);
    expect(textOf(b.querySelector(".b-hint-offer"))).toBe("Shared with @synthpeer");
    expect(b.querySelector<HTMLButtonElement>(".b-hint-offer button")!.disabled).toBe(true);
    expect(c.querySelector(".b-hint-offer")).toBeNull();
  });

  it.each([[TRACKING, "click"], [`${TRACKING}/modal-1`, "Enter"], [`${TRACKING}/state-kebab`, "Enter"]])("%s: the hint (%s) opens the share dialog, whose Share sends {campaignId, userId}", async (page, how) => {
    vi.useFakeTimers();
    const d = load(page);
    applySubscription(d, page, { campaigns: { rows: [OWN] } }, ME, true);
    const h = share();
    unbinds.push(bindTrackingSort(d, page, view(""), vi.fn(), h));
    const hint = rows()[0].querySelector<HTMLElement>("[data-oi-share]")!;
    if (how === "click") click(hint);
    else hint.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true, cancelable: true }));
    const root = d.getElementById("oi-share")!;
    const input = root.querySelector("input")!;
    input.value = "synthpeer";
    input.dispatchEvent(new Event("input"));
    await vi.advanceTimersByTimeAsync(300);
    expect(h.searchPerformers).toHaveBeenCalledWith("synthpeer");
    click(root.querySelector("[data-oi-performer]"));
    click(root.querySelector("[data-oi-send]"));
    expect(h.share).toHaveBeenCalledWith(fx.relay);
    vi.useRealTimers();
    await flush();
    expect(d.getElementById("oi-share")).toBeNull();
    expect(textOf(d.getElementById("oi-toast"))).toContain("Link's statistics shared with @synthpeer");
  });

  it("no model: the hint gives the Select-a-model note and opens nothing", () => {
    const d = load(TRACKING);
    applySubscription(d, TRACKING, { campaigns: { rows: [OWN] } }, ME, true);
    unbinds.push(bindTrackingSort(d, TRACKING, view(""), null, null));
    click(rows()[0].querySelector("[data-oi-share]"));
    expect(d.getElementById("oi-share")).toBeNull();
    expect(textOf(d.getElementById("oi-note"))).toContain("Select a model");
  });
});

describe("free trial links", () => {
  const data: SubData = {
    trials: {
      rows: [
        { id: 41, trialLinkName: "Synthetic trial", url: "https://onlyfans.com/action/trial/abc", subscribeDays: 7, subscribeCounts: 10, claimCounts: 3, clicksCounts: 12, createdAt: "2026-06-11T00:00:00+00:00", isFinished: false },
        { id: 42, trialLinkName: null, url: "https://onlyfans.com/action/trial/def", subscribeDays: 360, subscribeCounts: 0, claimCounts: 0, clicksCounts: 0, createdAt: "2026-05-01T00:00:00+00:00", isFinished: true },
      ],
    },
  };

  it("draws each link as OF does: name and length, limit, claims and clicks; an expired one is gray with Remove", () => {
    const d = load(TRIALS);
    applySubscription(d, TRIALS, data, ME, true);
    const [a, b] = rows();
    expect(textOf(a.querySelector(".b-offer-join__details"))).toBe("Synthetic trial (7 days free trial)");
    expect(textOf(a.querySelector(".b-fans__item__list"))).toBe("Free trial link created Jun 11, 2026 Offer limit 10 Claims count 3 Clicks count 12");
    expect(buttons(a)).toEqual([["Delete", false], ["Copy link", false]]);
    expect(textOf(b.querySelector(".b-offer-join__details"))).toBe("12 months free trial - expired");
    expect(textOf(b.querySelector(".b-fans__item__list"))).toBe("Free trial link created May 1, 2026 Offer limit Unlimited Claims count Not claimed yet Clicks count 0");
    expect(b.querySelector(".b-offer-join__content")!.classList.contains("g-gray-text")).toBe(true);
    expect(buttons(b)).toEqual([["Remove", false], ["Copy link", true]]);
  });

  it("Copy link copies its url; Remove asks, then DELETEs /trials/{id}", async () => {
    const d = load(TRIALS);
    applySubscription(d, TRIALS, data, ME, true);
    const h = handlers();
    unbinds.push(bindSubscription(d, h));
    const [a, b] = rows();
    [...a.querySelectorAll("button")].find((x) => textOf(x) === "Copy link")!.click();
    expect(h.copy).toHaveBeenCalledWith("https://onlyfans.com/action/trial/abc");
    [...b.querySelectorAll("button")].find((x) => textOf(x) === "Remove")!.click();
    expect(h.confirm).toHaveBeenCalledWith(ASKS.trialFinished);
    await flush();
    expect(h.remove).toHaveBeenCalledWith("/api/of/v2/trials/42");
  });

  it("each own link's share line is marked for the share dialog; a link shared with you has none", () => {
    const d = load(TRIALS);
    applySubscription(d, TRIALS, data, ME, true);
    const [a, b] = rows();
    for (const [r, id] of [[a, "41"], [b, "42"]] as const) {
      expect(r.dataset.oiTrial).toBe(id);
      const share = r.querySelector<HTMLElement>("[data-oi-share]");
      expect(textOf(share)).toBe("Share link's statistics with another user");
      expect(share!.hasAttribute("data-oi-wired")).toBe(true);
    }
    const s = load(TRIALS);
    applySubscription(s, TRIALS, data, ME, true, undefined, true);
    expect(rows().every((r) => !r.querySelector(".b-hint-offer") && !r.dataset.oiTrial)).toBe(true);
  });

  it("OF's TrialItem extras: Link expires, Shared with @user (its remove-access button disabled), Not claimed yet in gray", () => {
    const d = load(TRIALS);
    const row = { ...data.trials!.rows![0], claimCounts: 0, expiredAt: "2026-11-12T00:00:00+00:00", sharedWith: { username: "synthetic_fan" } };
    applySubscription(d, TRIALS, { trials: { rows: [row] } }, ME, true);
    const [a] = rows();
    expect(textOf(a.querySelector(".b-fans__item__list"))).toBe(
      "Free trial link created Jun 11, 2026 Link expires Nov 12, 2026 Offer limit 10 Claims count Not claimed yet Clicks count 12",
    );
    const line = a.querySelector<HTMLElement>(".b-hint-offer")!;
    expect(textOf(line)).toBe("Shared with @synthetic_fan");
    expect(line.hasAttribute("data-oi-share")).toBe(false);
    const close = line.querySelector("button")!;
    expect([close.disabled, close.title]).toEqual([true, "Not available in Inflowwww yet"]);
    expect(a.querySelector(".b-offer-join__content")!.classList.contains("g-gray-text")).toBe(false);
  });

  it("Shared with you: OF's TrialItem draws \"Shared from @owner\" (no remove-access button) when the link has sharedWith", () => {
    const d = load(TRIALS);
    const row = { ...data.trials!.rows![0], user: { username: "synthetic_owner" }, sharedWith: { username: ME.username } };
    applySubscription(d, TRIALS, { trials: { rows: [row] } }, ME, true, undefined, true);
    const line = rows()[0].querySelector<HTMLElement>(".b-hint-offer")!;
    expect(textOf(line)).toBe("Shared from @synthetic_owner");
    expect(line.querySelector("button")).toBeNull();
  });

  it("canCreateTrial false: OF's disabled header line, and the model's own links in gray", () => {
    const d = load(TRIALS);
    const hint = () => d.querySelector("#trial .b-menu-list__el.m-reset-bb")!;
    applySubscription(d, TRIALS, { trials: { rows: [data.trials!.rows![0]] } }, { ...ME, canCreateTrial: false }, true);
    expect(textOf(hint())).toBe("Set subscription price to create and share separate links with free trial subscription.");
    expect(hint().classList.contains("g-gray-text")).toBe(true);
    const [a] = rows();
    expect(a.querySelector(".b-offer-join__content")!.classList.contains("g-gray-text")).toBe(true);
    expect(a.querySelectorAll(".b-fans__item__list__item > .g-gray-text").length).toBe(3);
    applySubscription(d, TRIALS, { trials: { rows: [] } }, { ...ME, canCreateTrial: true }, true);
    expect(textOf(hint())).toBe("Create and share separate links with free trial subscription.");
    expect(hint().classList.contains("g-gray-text")).toBe(false);
  });

  it("with all models (no rows): OF's No results", () => {
    const d = load(TRIALS);
    applySubscription(d, TRIALS, {}, undefined, true);
    expect(rows()).toHaveLength(0);
    expect(prompts()).toEqual([false, true, false, false]);
  });
});

describe("OF's create gates", () => {
  const link = (text: string) => [...document.querySelectorAll<HTMLAnchorElement>("a.g-btn")].find((a) => textOf(a) === text)!;
  const trial = { id: 41, trialLinkName: "Synthetic trial", url: "https://onlyfans.com/action/trial/abc", subscribeDays: 7, subscribeCounts: 10, claimCounts: 0, clicksCounts: 0, createdAt: "2026-06-11T00:00:00+00:00", isFinished: false };

  it("canCreateTrial false: Create new free trial link and the model's own Copy link are disabled, as OF's", () => {
    const d = load(TRIALS);
    applySubscription(d, TRIALS, { trials: { rows: [trial] } }, { ...ME, canCreateTrial: false }, true);
    const a = link("Create new free trial link");
    expect(a.hasAttribute("href")).toBe(false);
    expect(a.getAttribute("aria-disabled")).toBe("true");
    expect(a.title).toBe(OF_DISALLOWS);
    applySubscription(d, TRIALS, { trials: { rows: [trial] } }, { ...ME, subscribePrice: 0, canCreateTrial: false }, true);
    expect(link("Create new free trial link").title).toBe(PRICE_FIRST);
    expect(buttons(rows()[0])).toEqual([["Delete", false], ["Copy link", true]]);
    applySubscription(d, TRIALS, { trials: { rows: [trial] } }, { ...ME, canCreateTrial: false }, true, undefined, true);
    expect(buttons(rows()[0])).toEqual([["Copy link", false]]);
    applySubscription(d, TRIALS, { trials: { rows: [trial] } }, ME, true);
    expect(link("Create new free trial link").getAttribute("href")).toBe("/of-manager/settings/subscription/trial-links/modal-1");
  });

  it("Start promotion campaign: enabled only for a priced performer that may promote and earn", () => {
    const d = load(PROMOTIONS);
    const ok = { ...ME, isPerformer: true, canCreatePromotion: true, canEarn: true };
    applySubscription(d, PROMOTIONS, {}, ok, true);
    expect(link("Start promotion campaign").hasAttribute("href")).toBe(true);
    expect(link("Start promotion campaign").hasAttribute("title")).toBe(false);
    const cases: [object, string][] = [[{ subscribePrice: 0 }, PRICE_FIRST], [{ isPerformer: false }, OF_DISALLOWS], [{ canCreatePromotion: false }, OF_DISALLOWS], [{ canEarn: false }, OF_DISALLOWS]];
    for (const [off, why] of cases) {
      applySubscription(d, PROMOTIONS, {}, { ...ok, ...off }, true);
      const a = link("Start promotion campaign");
      expect([a.hasAttribute("disabled"), a.title], JSON.stringify(off)).toEqual([true, why]);
    }
  });

  it("Add bundle: its tooltip names why OF disables it (no price, or no bundle left), never a missing feature", () => {
    const d = load(PROMOTIONS);
    const settings = { canAddSubscriberByBundle: { discounts: { "10": "10%" }, durations: { "3": "3 months" } } };
    const add = () => link("Add bundle");
    applySubscription(d, PROMOTIONS, {}, ME, true, undefined, false, settings);
    expect([add().hasAttribute("disabled"), add().hasAttribute("title")]).toEqual([false, false]);
    for (const [me, s, why] of [[{ ...ME, subscribePrice: 0 }, settings, PRICE_FIRST], [ME, { canAddSubscriberByBundle: false as const }, NO_BUNDLES_LEFT]] as const) {
      applySubscription(d, PROMOTIONS, {}, me, true, undefined, false, s);
      expect([add().hasAttribute("disabled"), add().title]).toEqual([true, why]);
      expect(add().title).not.toBe(NOT_YET);
    }
  });
});

describe("openers behind the modals (ticket 62)", () => {
  const OK = { ...ME, isPerformer: true, canCreatePromotion: true, canEarn: true };
  const SETTINGS = { canAddSubscriberByBundle: { discounts: { "10": "10%" }, durations: { "3": "3 months" } } };
  const opener = (text: string) => [...document.querySelectorAll<HTMLElement>("a, button")].filter((e) => textOf(e) === text);
  const promoState = ["modal-1", "modal-2", "modal-3", "state-bundle-discount-dropdown", "state-bundle-duration-dropdown", "state-promo-dropdowns-0", "state-promo-dropdowns-1", "state-promo-dropdowns-2"];
  const cases: [string, string, string][] = [
    ...["modal-1", "state-kebab"].map((p): [string, string, string] => [`${TRACKING}/${p}`, "Create new tracking link", `${TRACKING}/modal-1`]),
    ...["modal-1", "state-kebab"].map((p): [string, string, string] => [`${TRIALS}/${p}`, "Create new free trial link", `${TRIALS}/modal-1`]),
    ...promoState.flatMap((p): [string, string, string][] => [
      [`${PROMOTIONS}/${p}`, "Start promotion campaign", `${PROMOTIONS}/modal-1`],
      [`${PROMOTIONS}/${p}`, "Add bundle", `${PROMOTIONS}/modal-2`],
    ]),
  ];
  const titleOf = (label: string) => (label === "Add bundle" ? NOT_YET : "");
  it.each(cases)("%s: %s opens %s, Wired, with its Not-yet title until its Live pass (D1)", (page, label, dialog) => {
    const d = load(page);
    expect(opener(label).map((e) => e.tagName)).toEqual(["BUTTON"]);
    for (let i = 0; i < 2; i++) applySubscription(d, page, {}, OK, true, undefined, false, SETTINGS);
    const [a, ...more] = opener(label);
    expect(more).toEqual([]);
    expect([a.tagName, a.getAttribute("href"), a.getAttribute("target"), a.hasAttribute("disabled"), a.title, a.hasAttribute("data-oi-wired")])
      .toEqual(["A", `/of-manager/${dialog}`, "_top", false, titleOf(label), true]);
    expect(a.hasAttribute("title")).toBe(titleOf(label) !== "");
    expect(a.classList.contains("g-btn")).toBe(true);
  });

  it("gated as on the base page (no link, disabled), with OF's reason once its Live proof passed (D1); Add bundle keeps its Not-yet title", () => {
    for (const [page, label, me, why] of [
      [`${TRIALS}/modal-1`, "Create new free trial link", { ...ME, canCreateTrial: false }, OF_DISALLOWS],
      [`${PROMOTIONS}/modal-2`, "Start promotion campaign", { ...OK, subscribePrice: 0 }, PRICE_FIRST],
      [`${PROMOTIONS}/modal-1`, "Add bundle", { ...OK, subscribePrice: 0 }, NOT_YET],
    ] as const) {
      const d = load(page);
      applySubscription(d, page, {}, me, true, undefined, false, SETTINGS);
      const a = opener(label)[0];
      expect([a.hasAttribute("href"), a.hasAttribute("disabled")], page).toEqual([false, true]);
      expect(a.title, page).toBe(why);
      applySubscription(d, page, {}, OK, true, undefined, false, SETTINGS);
      if (label === "Add bundle") continue;
      expect([a.getAttribute("href"), a.hasAttribute("disabled"), a.hasAttribute("title")], page).toEqual([`/of-manager/${page.replace(/\/modal-\d$/, "/modal-1")}`, false, false]);
    }
  });

  it("the base pages keep OF's own links (no Not-yet title) and the model not read yet leaves them", () => {
    const d = load(PROMOTIONS);
    applySubscription(d, PROMOTIONS, {}, OK, true, undefined, false, SETTINGS);
    expect(opener("Start promotion campaign").map((a) => [a.hasAttribute("data-oi-ny"), a.hasAttribute("title")])).toEqual([[false, false]]);
    load(`${TRACKING}/modal-1`);
    applySubscription(document, `${TRACKING}/modal-1`, {}, undefined, true);
    expect(opener("Create new tracking link").map((a) => [a.tagName, a.getAttribute("href"), a.hasAttribute("title")])).toEqual([["A", `/of-manager/${TRACKING}/modal-1`, false]]);
  });

  it("Claims count behind a promotion modal opens Offer claimed (modal-3); the base page has no opener for it", () => {
    const promo = { id: 11, price: 0, type: "new", subscribeDays: 30, subscribeCounts: 0, claimsCount: 4, isFinished: false, canClaim: true, message: "", createdAt: "2026-03-02T12:00:00+00:00", finishedAt: null };
    for (const page of [`${PROMOTIONS}/modal-1`, `${PROMOTIONS}/modal-3`]) {
      const d = load(page);
      applySubscription(d, page, { promotions: { rows: [promo] } }, OK, true, undefined, false, SETTINGS);
      const claims = [...rows()[0].querySelectorAll(".b-fans__item__list__item")].find((i) => textOf(i).startsWith("Claims count"))!.lastElementChild as HTMLElement;
      expect([claims.tagName, claims.getAttribute("href"), textOf(claims), claims.title, claims.hasAttribute("data-oi-wired")], page)
        .toEqual(["A", `/of-manager/${PROMOTIONS}/modal-3`, "4", NOT_YET, true]);
    }
    const d = load(PROMOTIONS);
    applySubscription(d, PROMOTIONS, { promotions: { rows: [promo] } }, OK, true, undefined, false, SETTINGS);
    expect(buttons(rows()[0])[0]).toEqual(["4", true]);
  });
});
