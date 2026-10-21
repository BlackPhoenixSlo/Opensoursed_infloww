import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  bindBundleDialog,
  bindOffers,
  bindPromotionDialog,
  bindTrialDialog,
  bundleBody,
  bundleOptions,
  collectBundle,
  collectPromotion,
  collectTrial,
  discountDisabled,
  discountOptions,
  promotionBody,
  replaceText,
  shareDialog,
  TRIAL_DURATIONS,
  trialBody,
  trialHref,
  trialsRoute,
  trialViewOf,
  type BundleForm,
  type PromotionForm,
  type TrialForm,
  AFTER_NEW_POST_PROMOTION,
  AFTER_NEW_POST_TRIAL,
  applyOfferTiles,
  NEW_POST_PROMOTION,
  NEW_POST_TRIAL,
  PROMOTION_MODAL,
  TRIAL_MODAL,
} from "./ofMirrorOffers";
import { SUBMITS } from "./ofMirrorWrites";
import { applyPromotions } from "./ofMirrorFeeds";
import type { OfMe } from "./ofMirrorIdentity";

const fixture = <T,>(name: string): T => JSON.parse(readFileSync(resolve(__dirname, `__fixtures__/of/${name}.json`), "utf8")) as T;
const loadPage = (page: string) => {
  document.documentElement.innerHTML = readFileSync(resolve(__dirname, `../public/of-mirror/pages/${page}.html`), "utf8");
  return document;
};
const flush = () => new Promise((r) => setTimeout(r, 0));
/** Every bind a test makes is undone after it (the jsdom document is shared). */
const unbinds: (() => void)[] = [];
const bound = (u: () => void) => void unbinds.push(u);
afterEach(() => unbinds.splice(0).forEach((u) => u()));
const click = (el: Element | null) => el!.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
/** Open the dialog's `i`-th dropdown and pick the row labelled `label`. */
const pick = (doc: Document, i: number, label: string) => {
  click(doc.querySelectorAll(".modal.show .v-input.v-select")[i]);
  const row = [...doc.querySelectorAll("#oi-menu [data-oi-value]")].find((r) => r.textContent?.trim() === label);
  expect(row, `menu row ${label}`).toBeTruthy();
  click(row!);
};
/** A dialog tab by its text (the copy over New post carries no ids). */
const tabEl = (doc: Document, text: string) => [...doc.querySelectorAll(".modal.show .b-tabs__nav__link")].find((t) => t.textContent?.trim() === text) ?? null;
const tab = (doc: Document, text: string) => click(tabEl(doc, text));

interface Case<F> {
  name: string;
  form: F;
  relay: object;
}
const me = { subscribePrice: 9.99, username: "yourmodel", promotions: [] } as unknown as OfMe;

describe("promotion campaign (Start campaign)", () => {
  const cases = fixture<{ cases: Case<PromotionForm>[] }>("new-post-promotion-body").cases;
  it.each(cases.map((c) => [c.name, c] as const))("%s: the body is the fixture's", (_, c) => {
    expect(promotionBody(c.form)).toEqual(c.relay);
  });

  it.each([PROMOTION_MODAL, NEW_POST_PROMOTION])("drives the captured dialog (%s): tabs, dropdowns and message give each fixture body", (page) => {
    for (const c of cases) {
      const doc = loadPage(page);
      const unbind = bindPromotionDialog(doc, me);
      tab(doc, { new: "New subscribers", expired: "Expired subscribers", both: "Both new and expired" }[c.form.audience]);
      tab(doc, c.form.kind === "trial" ? "Free trial" : "First month discount");
      const limit = c.form.limit ? `${c.form.limit} subscriber${c.form.limit === 1 ? "" : "s"}` : "No limits";
      pick(doc, 0, limit);
      pick(doc, 1, c.form.expiration ? `${c.form.expiration} days` : "No expiration");
      if (c.form.kind === "trial") pick(doc, 2, `${c.form.duration} days`);
      else pick(doc, 2, `${c.form.percent}% discount`);
      const area = doc.querySelector<HTMLTextAreaElement>(".modal.show textarea")!;
      area.value = c.form.message;
      area.dispatchEvent(new Event("input", { bubbles: true }));
      expect(collectPromotion(doc), c.name).toEqual(c.relay);
      unbind();
    }
  });

  it("shows OF's defaults, the trial line and the counter", () => {
    const doc = loadPage("settings/subscription/promotion-campaign/modal-1");
    bound(bindPromotionDialog(doc, me));
    const shown = [...doc.querySelectorAll(".modal.show .v-select__selection")].map((e) => e.textContent);
    expect(shown).toEqual(["10 subscribers", "7 days", "7 days"]);
    expect(doc.querySelectorAll(".modal.show p.g-input__help")[1].textContent).toContain("Promotional subscription $0.00 for 7 days.");
    const area = doc.querySelector<HTMLTextAreaElement>(".modal.show textarea")!;
    area.value = "Hi";
    area.dispatchEvent(new Event("input", { bubbles: true }));
    expect(doc.querySelector(".modal.show .v-counter")?.textContent).toBe("2 / 500");
    expect(tabEl(doc, "New subscribers")?.classList.contains("m-current")).toBe(true);
  });

  it("disables First month discount where OF does (the price would fall under $3)", () => {
    expect(discountDisabled(0)).toBe(true);
    expect(discountDisabled(3.15)).toBe(true);
    expect(discountDisabled(9.99)).toBe(false);
    const doc = loadPage("settings/subscription/promotion-campaign/modal-1");
    bound(bindPromotionDialog(doc, { subscribePrice: 0 } as OfMe));
    expect((tabEl(doc, "First month discount") as HTMLButtonElement).disabled).toBe(true);
    tab(doc, "First month discount");
    expect((collectPromotion(doc) as { discount: number }).discount).toBe(100);
  });

  it("offers OF's discount steps for the price", () => {
    expect(discountOptions(9.99).map((o) => o.value)).toEqual(["5", "10", "15", "20", "25", "30", "35", "40", "45", "50", "55", "60", "65"]); // floor(100 * (9.99 - 3) / 9.99) = 69
    expect(discountOptions(100).at(-1)?.value).toBe("95");
  });

  it("names the promotion it replaces, as OF's replacePromoText", () => {
    expect(replaceText("new", [])).toBe("");
    expect(replaceText("new", [{ type: "all", canClaim: true }])).toContain("for new subscribers");
    expect(replaceText("expired", [{ type: "all", canClaim: true }])).toBe("");
    expect(replaceText("expired", [{ type: "expired", canClaim: true }])).toContain("expired");
    expect(replaceText("both", [{ type: "all", canClaim: true }, { type: "expired", canClaim: true }])).toContain("new and expired");
  });
});

describe("free trial link (Create link)", () => {
  const cases = fixture<{ cases: Case<TrialForm>[] }>("new-post-trial-body").cases;
  it.each(cases.map((c) => [c.name, c] as const))("%s: the body is the fixture's", (_, c) => {
    expect(trialBody(c.form)).toEqual(c.relay);
  });

  it.each([TRIAL_MODAL, NEW_POST_TRIAL])("drives the captured dialog (%s): the name and the three dropdowns", (page) => {
    for (const c of cases) {
      const doc = loadPage(page);
      const unbind = bindTrialDialog(doc, me);
      const name = doc.querySelector<HTMLInputElement>(".modal.show input[at-attr='input']")!;
      name.value = c.form.name;
      name.dispatchEvent(new Event("input", { bubbles: true }));
      pick(doc, 0, c.form.limit ? `${c.form.limit} subscribers` : "No limits");
      pick(doc, 1, c.form.expiration ? `${c.form.expiration} days` : "No expiration");
      pick(doc, 2, TRIAL_DURATIONS.find((o) => Number(o.value) === c.form.duration)!.label);
      expect(collectTrial(doc), c.name).toEqual(c.relay);
      unbind();
    }
  });

  it("labels OF's trial durations in days, then months", () => {
    expect(TRIAL_DURATIONS.map((o) => o.label)).toEqual(["1 day", "3 days", "7 days", "14 days", "1 month", "3 months", "6 months", "12 months"]);
  });
});

describe("subscription bundle (Save)", () => {
  const fx = fixture<{ settings: never; form: BundleForm; relay: object }>("new-post-bundle-body");
  it("sends {discount, duration} from OF's own options", () => {
    expect(bundleBody(fx.form)).toEqual(fx.relay);
    const doc = loadPage("settings/subscription/promotion-campaign/modal-2");
    bound(bindBundleDialog(doc, me, fx.settings));
    pick(doc, 0, "10% discount");
    pick(doc, 1, "3 months");
    expect(collectBundle(doc)).toEqual(fx.relay);
    expect(doc.querySelector<HTMLButtonElement>(".modal.show .modal-footer button")?.disabled).toBe(false);
  });

  it("drops durations the page already has, and gives OF's reason when none is left", () => {
    expect(bundleOptions(fx.settings, [3]).durations.map((d) => d.value)).toEqual(["6", "12"]);
    const doc = loadPage("settings/subscription/promotion-campaign/modal-2");
    bound(bindBundleDialog(doc, me, { canAddSubscriberByBundle: false }));
    expect(collectBundle(doc)).toMatch(/no more subscription bundles/);
    expect(doc.querySelector<HTMLButtonElement>(".modal.show .modal-footer button")?.disabled).toBe(true);
  });
});

describe("free trial links page", () => {
  it("sorts and switches tabs through the URL, as OF's TrialFilter", () => {
    const view = trialViewOf(new URLSearchParams("field=claims_count&sort=asc"));
    expect(trialsRoute(view)).toBe("/api/of/v2/trials?field=claims_count&sort=asc");
    expect(trialsRoute(trialViewOf(new URLSearchParams("")))).toBe("/api/of/v2/trials");
    expect(trialsRoute(trialViewOf(new URLSearchParams("tab=shared")))).toBe("/api/of/v2/trials/share-access");
    const doc = loadPage("settings/subscription/trial-links");
    const navigate = vi.fn();
    bound(bindOffers(doc, "settings/subscription/trial-links", { trialView: view, handlers: { navigate } as never }));
    click(doc.querySelector("button[aria-label='Sort']"));
    const rows = [...doc.querySelectorAll<HTMLElement>("#oi-menu [data-oi-value]")];
    expect(rows.map((r) => r.textContent?.trim())).toEqual(["Created", "Expires", "Limit", "Duration", "Claims count", "Clicks count", "Shared", "Ascending", "Descending"]);
    click(rows.find((r) => r.dataset.oiValue === "clicks_count")!);
    expect(navigate).toHaveBeenLastCalledWith(trialHref({ field: "clicks_count", sort: "asc", tab: null }));
    click(doc.getElementById("Shared-with-you"));
    expect(navigate).toHaveBeenLastCalledWith("/of-manager/settings/subscription/trial-links?field=claims_count&sort=asc&tab=shared");
  });

  it("shares a link's statistics: OF's performers search, then {trial_id, user_id}", async () => {
    vi.useFakeTimers();
    const fx = fixture<{ relay: { trial_id: number; user_id: number } }>("new-post-trial-share-body");
    document.body.innerHTML = "";
    const searchPerformers = vi.fn().mockResolvedValue([{ id: fx.relay.user_id, name: "Synthetic &amp; Creator", username: "synthetic" }]);
    const share = vi.fn().mockResolvedValue({ success: true });
    const root = shareDialog(document, fx.relay.trial_id, { searchPerformers, share });
    const input = root.querySelector("input")!;
    input.value = "synth";
    input.dispatchEvent(new Event("input"));
    await vi.advanceTimersByTimeAsync(300);
    expect(searchPerformers).toHaveBeenCalledWith("synth");
    // OF's escaped name shows as text
    expect(root.querySelector("[data-oi-performer]")!.textContent).toBe("Synthetic & Creator @synthetic");
    click(root.querySelector("[data-oi-performer]"));
    expect(input.value).toBe("@synthetic");
    click(root.querySelector("[data-oi-send]"));
    expect(share).toHaveBeenCalledWith(fx.relay);
    vi.useRealTimers();
    await flush();
    expect(document.getElementById("oi-share")).toBeNull();
  });
});

describe("promotion cards (Stop promotion, Copy link to profile)", () => {
  it("keeps OF's two buttons on New post's right column and wires them", async () => {
    const doc = loadPage("new-post/index");
    applyPromotions(doc, [{ id: 1001, price: 0, subscribeDays: 7, type: "all", canClaim: true, isFinished: false }], 5, { id: 1, username: "yourmodel" }, (u) => u);
    const stop = doc.querySelector<HTMLButtonElement>("button[data-oi-finish='1001']");
    const copy = doc.querySelector<HTMLButtonElement>("button[data-oi-copy]");
    expect(stop?.textContent?.trim()).toBe("Stop promotion");
    expect(copy?.getAttribute("data-oi-copy")).toBe("https://onlyfans.com/yourmodel");
    const finish = vi.fn().mockResolvedValue({});
    const copyText = vi.fn().mockResolvedValue(undefined);
    bound(bindOffers(doc, "new-post/index", { trialView: { field: null, sort: null, tab: null }, handlers: { finish, copy: copyText, confirm: () => true } as never }));
    click(stop);
    expect(finish).toHaveBeenCalledWith("1001");
    click(copy);
    expect(copyText).toHaveBeenCalledWith("https://onlyfans.com/yourmodel");
    await flush();
    expect(doc.getElementById("oi-toast")?.textContent).toContain("Link copied");
  });

  it("stop sends nothing when the confirm is declined", () => {
    const doc = loadPage("new-post/index");
    applyPromotions(doc, [{ id: 7, price: 0, subscribeDays: 7, type: "all", canClaim: true, isFinished: false }], 5, { id: 1, username: "m" }, (u) => u);
    const finish = vi.fn();
    bound(bindOffers(doc, "new-post/index", { trialView: { field: null, sort: null, tab: null }, handlers: { finish, confirm: () => false } as never }));
    click(doc.querySelector("button[data-oi-finish]"));
    expect(finish).not.toHaveBeenCalled();
  });
});

describe("New post's offer tiles and dialogs (OF's PromoteProfile and CreateTrialLinkBtn)", () => {
  const tiles = (doc: Document) =>
    Object.fromEntries([...doc.querySelectorAll<HTMLElement>(".b-story-item.m-create")].map((t) => [t.textContent!.trim(), t]));

  it("the tiles open their dialogs over New post, not Settings", () => {
    const t = tiles(loadPage("new-post/index"));
    expect(t["Start profile promotion"].getAttribute("href")).toBe("/of-manager/new-post/state-promotion");
    expect(t["Create new trial link"].getAttribute("href")).toBe("/of-manager/new-post/state-trial-link");
  });

  it("each dialog is the Settings dialog over New post's own page: its composer behind, Cancel and the backdrop back to New post", () => {
    for (const page of [NEW_POST_PROMOTION, NEW_POST_TRIAL]) {
      const doc = loadPage(page);
      expect(doc.querySelector(".b-make-post"), page).not.toBeNull();
      expect(doc.querySelector(".modal.show .modal-footer a")?.getAttribute("href"), page).toBe("/of-manager/new-post");
      expect(doc.querySelector(".modal.show a.of-state-backdrop")?.getAttribute("href"), page).toBe("/of-manager/new-post");
      expect(doc.querySelectorAll(".modal.show .v-input.v-select:not(.v-input--is-disabled)").length, page).toBe(3);
    }
  });

  it("hides a tile where users/me says the model cannot (OF's v-if), shows it when unknown", () => {
    const doc = loadPage("new-post/index");
    applyOfferTiles(doc, undefined);
    expect(tiles(doc)["Start profile promotion"].style.display).toBe("");
    applyOfferTiles(doc, { canCreatePromotion: false, canCreateTrial: true } as unknown as OfMe);
    expect(tiles(doc)["Start profile promotion"].style.display).toBe("none");
    expect(tiles(doc)["Create new trial link"].style.display).toBe("");
    applyOfferTiles(doc, { canCreatePromotion: true, canCreateTrial: false } as unknown as OfMe);
    expect(tiles(doc)["Start profile promotion"].style.display).toBe("");
    expect(tiles(doc)["Create new trial link"].style.display).toBe("none");
  });

  it("a claimable \"all\" promotion sends the promotion tile to Settings > Subscription, as OF's PromoteProfile", () => {
    const doc = loadPage("new-post/index");
    applyOfferTiles(doc, { canCreatePromotion: true, promotions: [{ type: "all", canClaim: true }] } as unknown as OfMe);
    expect(tiles(doc)["Start profile promotion"].getAttribute("href")).toBe(AFTER_NEW_POST_PROMOTION);
    applyOfferTiles(doc, { canCreatePromotion: true, promotions: [{ type: "expired", canClaim: true }] } as unknown as OfMe);
    expect(tiles(doc)["Start profile promotion"].getAttribute("href")).toBe("/of-manager/new-post/state-promotion");
  });

  it("their submits send Settings' bodies to the same routes, then go where OF goes from New post", () => {
    const doc = loadPage(NEW_POST_PROMOTION);
    expect(SUBMITS[NEW_POST_PROMOTION].send).toBe(SUBMITS[PROMOTION_MODAL].send);
    expect(SUBMITS[NEW_POST_PROMOTION].then(doc)).toBe("/of-manager/settings/subscription#promotion");
    expect(SUBMITS[NEW_POST_TRIAL].send).toBe("/api/of/v2/trials");
    expect(SUBMITS[NEW_POST_TRIAL].then(loadPage(NEW_POST_TRIAL))).toBe(AFTER_NEW_POST_TRIAL);
    // On Settings each still returns to its Cancel's tab.
    expect(SUBMITS[TRIAL_MODAL].then(loadPage(TRIAL_MODAL))).toBe("/of-manager/settings/subscription/trial-links");
  });
});
