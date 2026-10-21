import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import { applySubscription, ASKS, OF_DISALLOWS, PRICE_FIRST, bindSubscription, campaignLink, LIST_MAX_HEIGHT, listOf, mePromotions, subscriptionParts, trialLength, type SubData, type SubHandlers } from "./ofMirrorSubscription";
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
    if (page !== PROMOTIONS) expect(prompts()).toEqual([false, true, false, false]); // "No results :("
  });
});

describe("promotions and bundles", () => {
  const live = { id: 11, price: 0, type: "new", subscribeDays: 30, subscribeCounts: 0, claimsCount: 4, isFinished: false, canClaim: true, message: "<p>Synthetic welcome</p>", createdAt: "2026-03-02T12:00:00+00:00", finishedAt: null };
  const ended = { id: 12, price: 5, type: "expired", subscribeDays: 31, subscribeCounts: 3, claimsCount: 1, isFinished: true, canClaim: false, message: "", createdAt: "2025-09-30T12:00:00+00:00", finishedAt: "2025-10-07T12:00:00+00:00" };
  const data: SubData = { promotions: { rows: [live, ended] }, bundles: { rows: [{ id: 21, price: 20.35, duration: 3, discount: 30 }, { id: 22, price: 60, duration: 6, discount: 0 }] } };

  it("draws one card per promotion and bundle as OF does, in the Relay's order", () => {
    const d = load(PROMOTIONS);
    applySubscription(d, PROMOTIONS, data, ME);
    const [p1, p2, b1, b2] = rows();
    expect(rows()).toHaveLength(4);
    expect(textOf(p1.querySelector(".b-offer-join__details"))).toBe("Limited offer - Free trial for 30 days!");
    expect(textOf(p1.querySelector(".b-offer-join__left-time"))).toBe("For new subscribers");
    expect(textOf(p1.querySelector(".b-offer-join__bubble__text"))).toBe("Synthetic welcome");
    expect(textOf(p1.querySelector(".b-fans__item__list"))).toBe("Started Mar 2, 2026 Claims count 4");
    expect(buttons(p1)).toEqual([["4", true], ["Stop promotion", false], ["Copy link to profile", false]]);
    expect(p1.querySelector("button[data-oi-finish]")?.getAttribute("data-oi-finish")).toBe(String(live.id)); // ofMirrorOffers stops it
    expect(textOf(p2.querySelector(".b-offer-join__details"))).toBe("Limited offer - 50% off for 31 days");
    expect(p2.querySelector(".b-offer-join__details")!.classList.contains("g-gray-text")).toBe(true);
    expect(textOf(p2.querySelector(".b-offer-join__left-time"))).toBe("For expired subscribers ended Oct 7 left 3");
    expect(p2.querySelector(".b-offer-join__bubble")).toBeNull(); // no message: no bubble
    expect(buttons(p2)).toEqual([["1", true], ["Remove", false]]);
    expect(textOf(b1)).toBe("$20.35 USD total for 3 months -30%");
    expect(textOf(b2)).toBe("$60 USD total for 6 months");
    expect(buttons(b1)).toEqual([["Delete", false]]);
    // Drawn again: the same rows, not twice.
    applySubscription(d, PROMOTIONS, data, ME);
    expect(rows()).toHaveLength(4);
    applySubscription(d, PROMOTIONS, {}, ME);
    expect(rows()).toHaveLength(0);
  });

  it("Copy link to profile copies the Creator's profile with OF's toast; Remove deletes the ended promotion without asking", async () => {
    const d = load(PROMOTIONS);
    applySubscription(d, PROMOTIONS, data, ME);
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
    applySubscription(d, PROMOTIONS, data, ME);
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
    applySubscription(d, PROMOTIONS, data, ME);
    unbinds.push(bindWrites(d, PROMOTIONS, null));
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
    applySubscription(d, PROMOTIONS, { ...data, promotions: { rows: many } }, ME);
    const box = d.querySelector<HTMLElement>("[data-oi-template='promotion-row']")!.parentElement!;
    expect(box.hasAttribute("data-oi-scroll")).toBe(true);
    expect(box.style.overflowY).toBe("auto");
    expect(box.style.maxHeight).toBe(LIST_MAX_HEIGHT);
    // OF's wrapper is a wrapping flex column: capped, it must not flow the cards sideways.
    expect(box.style.flexWrap).toBe("nowrap");
    expect(box.querySelectorAll(":scope > [data-oi-row]")).toHaveLength(12);
    // The bundles are outside the box, not scrolled away with it.
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
    applySubscription(d, TRACKING, data, ME);
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
    applySubscription(d, TRACKING, data, ME);
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
    applySubscription(d, TRACKING, data, ME);
    const h = handlers();
    unbinds.push(bindSubscription(d, h));
    [...rows()[1].querySelectorAll("button")].find((b) => textOf(b) === "Remove")!.click();
    expect(h.confirm).toHaveBeenCalledWith(ASKS.campaign);
  });

  it("shows OF's list status: the preloader, No results, and Something went wrong with a working Retry", () => {
    const d = load(TRACKING);
    applySubscription(d, TRACKING, { campaigns: { loading: true } }, ME);
    expect(prompts()).toEqual([true, false, false, false]);
    applySubscription(d, TRACKING, { campaigns: { rows: [] } }, ME);
    expect(prompts()).toEqual([false, true, false, false]);
    applySubscription(d, TRACKING, { campaigns: { rows: [], error: true } }, ME);
    expect(prompts()).toEqual([false, false, false, true]);
    const h = handlers();
    unbinds.push(bindSubscription(d, h));
    const retry = [...d.querySelectorAll<HTMLButtonElement>(".infinite-status-prompt button")].find((b) => textOf(b) === "Retry")!;
    expect(retry.hasAttribute("data-oi-wired")).toBe(true);
    retry.click();
    expect(h.retry).toHaveBeenCalledTimes(1);
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
    applySubscription(d, TRIALS, data, ME);
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
    applySubscription(d, TRIALS, data, ME);
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
    applySubscription(d, TRIALS, data, ME);
    const [a, b] = rows();
    for (const [r, id] of [[a, "41"], [b, "42"]] as const) {
      expect(r.dataset.oiTrial).toBe(id);
      const share = r.querySelector<HTMLElement>("[data-oi-share]");
      expect(textOf(share)).toBe("Share link's statistics with another user");
      expect(share!.hasAttribute("data-oi-wired")).toBe(true);
    }
    const s = load(TRIALS);
    applySubscription(s, TRIALS, data, ME, undefined, true);
    expect(rows().every((r) => !r.querySelector(".b-hint-offer") && !r.dataset.oiTrial)).toBe(true);
  });

  it("OF's TrialItem extras: Link expires, Shared with @user (its remove-access button disabled), Not claimed yet in gray", () => {
    const d = load(TRIALS);
    const row = { ...data.trials!.rows![0], claimCounts: 0, expiredAt: "2026-11-12T00:00:00+00:00", sharedWith: { username: "synthetic_fan" } };
    applySubscription(d, TRIALS, { trials: { rows: [row] } }, ME);
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
    applySubscription(d, TRIALS, { trials: { rows: [row] } }, ME, undefined, true);
    const line = rows()[0].querySelector<HTMLElement>(".b-hint-offer")!;
    expect(textOf(line)).toBe("Shared from @synthetic_owner");
    expect(line.querySelector("button")).toBeNull();
  });

  it("canCreateTrial false: OF's disabled header line, and the model's own links in gray", () => {
    const d = load(TRIALS);
    const hint = () => d.querySelector("#trial .b-menu-list__el.m-reset-bb")!;
    applySubscription(d, TRIALS, { trials: { rows: [data.trials!.rows![0]] } }, { ...ME, canCreateTrial: false });
    expect(textOf(hint())).toBe("Set subscription price to create and share separate links with free trial subscription.");
    expect(hint().classList.contains("g-gray-text")).toBe(true);
    const [a] = rows();
    expect(a.querySelector(".b-offer-join__content")!.classList.contains("g-gray-text")).toBe(true);
    // Created, Offer limit and Clicks count (Claims count is its link, as OF's).
    expect(a.querySelectorAll(".b-fans__item__list__item > .g-gray-text").length).toBe(3);
    applySubscription(d, TRIALS, { trials: { rows: [] } }, { ...ME, canCreateTrial: true });
    expect(textOf(hint())).toBe("Create and share separate links with free trial subscription.");
    expect(hint().classList.contains("g-gray-text")).toBe(false);
  });

  it("with all models (no rows): OF's No results", () => {
    const d = load(TRIALS);
    applySubscription(d, TRIALS, {}, undefined);
    expect(rows()).toHaveLength(0);
    expect(prompts()).toEqual([false, true, false, false]);
  });
});

describe("OF's create gates", () => {
  const link = (text: string) => [...document.querySelectorAll<HTMLAnchorElement>("a.g-btn")].find((a) => textOf(a) === text)!;
  const trial = { id: 41, trialLinkName: "Synthetic trial", url: "https://onlyfans.com/action/trial/abc", subscribeDays: 7, subscribeCounts: 10, claimCounts: 0, clicksCounts: 0, createdAt: "2026-06-11T00:00:00+00:00", isFinished: false };

  it("canCreateTrial false: Create new free trial link and the model's own Copy link are disabled, as OF's", () => {
    const d = load(TRIALS);
    applySubscription(d, TRIALS, { trials: { rows: [trial] } }, { ...ME, canCreateTrial: false });
    const a = link("Create new free trial link");
    expect(a.hasAttribute("href")).toBe(false);
    expect(a.getAttribute("aria-disabled")).toBe("true");
    expect(a.title).toBe(OF_DISALLOWS); // the account's state, not a missing feature
    applySubscription(d, TRIALS, { trials: { rows: [trial] } }, { ...ME, subscribePrice: 0, canCreateTrial: false });
    expect(link("Create new free trial link").title).toBe(PRICE_FIRST);
    expect(buttons(rows()[0])).toEqual([["Delete", false], ["Copy link", true]]);
    // A link shared with the model keeps its Copy link.
    applySubscription(d, TRIALS, { trials: { rows: [trial] } }, { ...ME, canCreateTrial: false }, undefined, true);
    expect(buttons(rows()[0])).toEqual([["Copy link", false]]);
    applySubscription(d, TRIALS, { trials: { rows: [trial] } }, ME);
    expect(link("Create new free trial link").getAttribute("href")).toBe("/of-manager/settings/subscription/trial-links/modal-1");
  });

  it("Start promotion campaign: enabled only for a priced performer that may promote and earn", () => {
    const d = load(PROMOTIONS);
    const ok = { ...ME, isPerformer: true, canCreatePromotion: true, canEarn: true };
    applySubscription(d, PROMOTIONS, {}, ok);
    expect(link("Start promotion campaign").hasAttribute("href")).toBe(true);
    expect(link("Start promotion campaign").hasAttribute("title")).toBe(false);
    const cases: [object, string][] = [[{ subscribePrice: 0 }, PRICE_FIRST], [{ isPerformer: false }, OF_DISALLOWS], [{ canCreatePromotion: false }, OF_DISALLOWS], [{ canEarn: false }, OF_DISALLOWS]];
    for (const [off, why] of cases) {
      applySubscription(d, PROMOTIONS, {}, { ...ok, ...off });
      const a = link("Start promotion campaign");
      expect([a.hasAttribute("disabled"), a.title], JSON.stringify(off)).toEqual([true, why]);
    }
  });

  it("Add bundle: its tooltip names why OF disables it (no price, or no bundle left), never a missing feature", () => {
    const d = load(PROMOTIONS);
    const settings = { canAddSubscriberByBundle: { discounts: { "10": "10%" }, durations: { "3": "3 months" } } };
    const add = () => link("Add bundle");
    applySubscription(d, PROMOTIONS, {}, ME, undefined, false, settings);
    expect([add().hasAttribute("disabled"), add().hasAttribute("title")]).toEqual([false, false]);
    for (const [me, s, why] of [[{ ...ME, subscribePrice: 0 }, settings, PRICE_FIRST], [ME, { canAddSubscriberByBundle: false as const }, NO_BUNDLES_LEFT]] as const) {
      applySubscription(d, PROMOTIONS, {}, me, undefined, false, s);
      expect([add().hasAttribute("disabled"), add().title]).toEqual([true, why]);
      expect(add().title).not.toBe(NOT_YET);
    }
  });
});
