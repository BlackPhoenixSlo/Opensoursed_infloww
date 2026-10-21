import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
// ofMirrorWrites first: its SUBMITS keys come from ofMirrorOffers, which imports it back.
import { bindWrites, NOT_YET, ofErrorMessage, type WriteHandlers } from "./ofMirrorWrites";
import type { OfMe } from "./ofMirrorIdentity";
import { BUNDLE_MODAL, bindBundleDialog, bundleAmount, collectBundle, type BundleSettings } from "./ofMirrorOffers";
import { CARRY_MS, frameNavigate } from "./ofMirrorPost";
import { applySubscription, bindSubscription, type Bundle, type SubData, type SubHandlers } from "./ofMirrorSubscription";
import { RelayError } from "./relay";

/** Settings > Subscription's bundles: the rows, Add bundle and its dialog, the delete, OF's gray and OF's error. */

interface Side {
  me: OfMe & { subscriptionBundles: Bundle[] };
  settings: BundleSettings;
}
interface Call {
  method: string;
  path: string;
  body?: object;
}
const fixture = <T,>(name: string): T => JSON.parse(readFileSync(resolve(__dirname, `__fixtures__/of/${name}.json`), "utf8")) as T;
const fx = fixture<
  Side & {
    rows: { price: string; time: string; discount: string | null }[];
    create: { form: { discount: number; duration: number }; amount: number; relay: Call };
    delete: { relay: Call };
    error: { status: number; body: unknown; message: string };
  }
>("settings-bundles");
const free = fixture<Record<"free" | "empty" | "full", Side>>("settings-bundles-free");

const PAGE = "settings/subscription/promotion-campaign";
const load = (page: string) => {
  document.documentElement.innerHTML = readFileSync(resolve(__dirname, `../public/of-mirror/pages/${page}.html`), "utf8");
  return document;
};
/** `page` loaded as the frame document at its own URL (the carried toast reads it). */
const at = (page: string) => {
  window.history.replaceState(null, "", `/of-mirror/pages/${page}.html`);
  return load(page);
};
const flush = () => new Promise((r) => setTimeout(r, 0));
const click = (el: Element | null) => el!.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
const textOf = (el: Element | null | undefined) => (el?.textContent ?? "").replace(/\s+/g, " ").trim();
const unbinds: (() => void)[] = [];
afterEach(() => {
  unbinds.splice(0).forEach((u) => u());
  window.history.replaceState(null, "", "/");
});

const data = (s: Side): SubData => ({ promotions: { rows: [] }, bundles: { rows: s.me.subscriptionBundles } });
const bundleRows = () => [...document.querySelectorAll<HTMLElement>("[data-oi-row]")].filter((r) => r.querySelector("button[aria-label='Delete']"));
const addBundle = () => [...document.querySelectorAll<HTMLAnchorElement>("a.g-btn")].find((a) => textOf(a) === "Add bundle")!;
const header = () => [...document.querySelectorAll("h3.b-menu-list__el")].find((h) => textOf(h.querySelector(".b-menu-list__text")) === "Subscription bundles")!;
const relayError = () => new RelayError(fx.error.status, fx.error.body, "upstream 400: Synthetic");
const subHandlers = (over: Partial<SubHandlers> = {}): SubHandlers =>
  ({ remove: vi.fn(() => Promise.resolve()), copy: vi.fn(), confirm: vi.fn(() => Promise.resolve(true)), retry: vi.fn(), ...over }) as SubHandlers;

describe("the bundle rows", () => {
  it("draws each of users/me's bundles as OF does: total, months, discount", () => {
    const d = load(PAGE);
    applySubscription(d, PAGE, data(fx), fx.me, undefined, false, fx.settings);
    const rows = bundleRows();
    expect(rows).toHaveLength(2);
    rows.forEach((r, i) => {
      expect(r.querySelector(".b-amount-price")?.textContent).toBe(fx.rows[i].price);
      expect(r.querySelector(".b-offer-join__details__time")?.lastChild?.textContent).toBe(fx.rows[i].time);
      expect(r.querySelector(".b-offer-join__details__discount")?.textContent ?? null).toBe(fx.rows[i].discount);
      expect(r.querySelector(".b-offer-join__content")?.classList.contains("g-disabled")).toBe(false);
    });
    expect(header().classList.contains("m-disabled-block")).toBe(false);
    // A duration (12 months) is left: Add bundle opens the dialog.
    expect(addBundle().getAttribute("href")).toBe(`/of-manager/${BUNDLE_MODAL}`);
    expect(addBundle().hasAttribute("disabled")).toBe(false);
  });

  it("an empty list draws no row, and Add bundle stays open", () => {
    const d = load(PAGE);
    applySubscription(d, PAGE, data(free.empty), free.empty.me, undefined, false, free.empty.settings);
    expect(bundleRows()).toHaveLength(0);
    expect(addBundle().hasAttribute("href")).toBe(true);
  });

  it("free: OF grays the header and each bundle, and disables Add bundle", () => {
    const d = load(PAGE);
    applySubscription(d, PAGE, data(free.free), free.free.me, undefined, false, free.free.settings);
    expect(header().classList.contains("m-disabled-block")).toBe(true);
    expect(bundleRows()[0].querySelector(".b-offer-join__content")?.classList.contains("g-disabled")).toBe(true);
    const a = addBundle();
    expect(a.hasAttribute("href")).toBe(false);
    expect(a.hasAttribute("disabled")).toBe(true);
    expect(a.title).toBe(NOT_YET);
    // Priced again (another model): the link comes back.
    applySubscription(d, PAGE, data(free.empty), free.empty.me, undefined, false, free.empty.settings);
    expect(a.getAttribute("href")).toBe(`/of-manager/${BUNDLE_MODAL}`);
    expect(a.hasAttribute("disabled")).toBe(false);
  });

  it("every offered duration has a bundle: Add bundle is disabled (OF's isAddBundleDisabled)", () => {
    const d = load(PAGE);
    applySubscription(d, PAGE, data(free.full), free.full.me, undefined, false, free.full.settings);
    expect(addBundle().hasAttribute("disabled")).toBe(true);
    expect(header().classList.contains("m-disabled-block")).toBe(false);
  });

  it("no model read yet: Add bundle is left as it is", () => {
    const d = load(PAGE);
    applySubscription(d, PAGE, {}, undefined);
    expect(addBundle().hasAttribute("href")).toBe(true);
  });
});

describe("delete", () => {
  it("asks, then DELETEs the bundle and drops its row", async () => {
    const d = load(PAGE);
    applySubscription(d, PAGE, data(fx), fx.me, undefined, false, fx.settings);
    const h = subHandlers();
    unbinds.push(bindSubscription(d, h));
    const row = bundleRows()[1];
    click(row.querySelector("button[aria-label='Delete']"));
    expect(h.confirm).toHaveBeenCalledTimes(1);
    await Promise.resolve(); // OF's ModalConfirm answers
    expect(h.remove).toHaveBeenCalledWith(fx.delete.relay.path);
    await flush();
    expect(row.isConnected).toBe(false);
  });

  it("an OF error: the row stays, its button works again, and OF's message shows in OF's toast", async () => {
    const d = load(PAGE);
    applySubscription(d, PAGE, data(fx), fx.me, undefined, false, fx.settings);
    unbinds.push(bindSubscription(d, subHandlers({ remove: vi.fn(() => Promise.reject(relayError())) })));
    const row = bundleRows()[1];
    const del = row.querySelector<HTMLButtonElement>("button[aria-label='Delete']")!;
    click(del);
    await Promise.resolve(); // OF's ModalConfirm answers
    expect(del.disabled).toBe(true);
    await flush();
    expect(row.isConnected).toBe(true);
    expect(del.disabled).toBe(false);
    expect(textOf(d.querySelector("#oi-toast .toast__text"))).toBe(fx.error.message);
  });

  it("reads OF's own error.message out of the relay's 502", () => {
    expect(ofErrorMessage(relayError())).toBe(fx.error.message);
    expect(ofErrorMessage(new Error("network"))).toBeNull();
    expect(ofErrorMessage(new RelayError(401, { detail: "sign in required" }))).toBeNull();
  });
});

describe("Add bundle's dialog", () => {
  const pick = (doc: Document, i: number, label: string) => {
    click(doc.querySelectorAll(".modal.show .v-input.v-select")[i]);
    click([...doc.querySelectorAll("#oi-menu [data-oi-value]")].find((r) => r.textContent?.trim() === label) ?? null);
  };
  const save = () => document.querySelector<HTMLButtonElement>(".modal.show .modal-footer button")!;
  const writes = (over: Partial<WriteHandlers> = {}) =>
    ({ saveProfile: vi.fn(), setReplyOnSubscribe: vi.fn(), submit: vi.fn(() => Promise.resolve({ id: 1 })), navigate: vi.fn(), ...over }) as WriteHandlers & {
      submit: ReturnType<typeof vi.fn>;
      navigate: ReturnType<typeof vi.fn>;
    };
  /** WriteHandlers whose navigate is the hooks' (frameNavigate over the test's document as the frame's): router.push is `push`. */
  const framed = (submit: WriteHandlers["submit"], push = vi.fn()) => ({ h: writes({ submit, navigate: vi.fn(frameNavigate({ current: { contentDocument: document } as HTMLIFrameElement }, push)) }), push });

  it("offers only the durations with no bundle yet, shows OF's amount and POSTs {discount, duration}", async () => {
    const d = load(BUNDLE_MODAL);
    unbinds.push(bindBundleDialog(d, fx.me, fx.settings));
    pick(d, 0, "10% discount");
    click(d.querySelectorAll(".modal.show .v-input.v-select")[1]);
    const offered = [...d.querySelectorAll("#oi-menu [data-oi-value]")];
    expect(offered.map((r) => r.textContent?.trim())).toEqual(["12 months"]);
    click(offered[0]);
    expect(bundleAmount(fx.create.form, fx.me.subscribePrice!)).toBe(fx.create.amount);
    expect(textOf(d.querySelector(".modal.show p.g-input__help"))).toBe(`Promotional subscription $${fx.create.amount} for 12 months.`);
    expect(collectBundle(d)).toEqual(fx.create.relay.body);
    const h = writes();
    unbinds.push(bindWrites(d, BUNDLE_MODAL, h));
    click(save());
    expect(h.submit).toHaveBeenCalledWith(fx.create.relay.path, fx.create.relay.body);
    await flush();
    expect(h.navigate).toHaveBeenCalledTimes(1);
  });

  it("over OF's max price: Save is disabled with the reason in the help line (m-danger)", () => {
    const d = load(BUNDLE_MODAL);
    unbinds.push(bindBundleDialog(d, fx.me, { ...fx.settings, bundleMaxPrice: 50 }));
    pick(d, 1, "12 months");
    expect(save().disabled).toBe(true);
    expect(d.querySelector(".modal.show p.g-input__help")?.classList.contains("m-danger")).toBe(true);
    expect(textOf(d.querySelector(".modal.show p.g-input__help"))).toBe("Maximum bundle price is $50"); // OF's bundle_max_price_error
    expect(typeof collectBundle(d)).toBe("string");
  });

  it("an OF error: the dialog closes as OF's (its save's finally) and OF's message shows in OF's toast on the page", async () => {
    const d = at(BUNDLE_MODAL);
    unbinds.push(bindBundleDialog(d, fx.me, fx.settings));
    const { h, push } = framed(vi.fn(() => Promise.reject(relayError())));
    unbinds.push(bindWrites(d, BUNDLE_MODAL, h));
    const back = d.querySelector(".modal-footer a[href]")!.getAttribute("href");
    click(save());
    expect(save().disabled).toBe(true);
    await flush();
    expect(h.navigate).toHaveBeenCalledWith(back, fx.error.message);
    expect(push).toHaveBeenCalledWith(back);
    // A rebind of the dialog's page it left, while the frame loads, keeps it.
    unbinds.push(bindWrites(at(BUNDLE_MODAL), BUNDLE_MODAL, h));
    expect(document.querySelector("#oi-toast")).toBeNull();
    // The new frame's about:blank placeholder binds first (OfMirrorFrame's key={src}): it neither shows nor uses up the toast.
    const blank = document.implementation.createHTMLDocument("");
    unbinds.push(bindWrites(blank, PAGE, h));
    expect(blank.querySelector("#oi-toast")).toBeNull();
    // The page under the dialog binds next: the toast shows there.
    const page = at(PAGE);
    unbinds.push(bindWrites(page, PAGE, h));
    expect(textOf(page.querySelector("#oi-toast .toast__text"))).toBe(fx.error.message);
  });

  it("an error without OF's message closes the dialog too, its toast the save's failure", async () => {
    const d = at(BUNDLE_MODAL);
    unbinds.push(bindBundleDialog(d, fx.me, fx.settings));
    const { h } = framed(vi.fn(() => Promise.reject(new Error("offline"))));
    unbinds.push(bindWrites(d, BUNDLE_MODAL, h));
    click(save());
    await flush();
    expect(h.navigate).toHaveBeenCalledWith("/of-manager/" + PAGE, "Could not add the bundle: offline");
    const page = at(PAGE);
    unbinds.push(bindWrites(page, PAGE, h));
    expect(textOf(page.querySelector("#oi-toast .toast__text"))).toBe("Could not add the bundle: offline");
  });

  it("an error's toast shows on its own page only: another page binding first drops it", async () => {
    const d = at(BUNDLE_MODAL);
    unbinds.push(bindBundleDialog(d, fx.me, fx.settings));
    unbinds.push(bindWrites(d, BUNDLE_MODAL, framed(vi.fn(() => Promise.reject(relayError()))).h));
    click(save());
    await flush();
    const other = at("settings/subscription/trial-links");
    unbinds.push(bindWrites(other, "settings/subscription/trial-links", writes()));
    expect(other.querySelector("#oi-toast")).toBeNull();
    const page = at(PAGE);
    unbinds.push(bindWrites(page, PAGE, writes()));
    expect(page.querySelector("#oi-toast")).toBeNull();
  });

  it("the frame already back on the page under the dialog when the save fails: the toast shows there at once, no navigation", async () => {
    // The dialog's own (old) frame document, apart from the frame's document now.
    const d = document.implementation.createHTMLDocument("");
    d.documentElement.innerHTML = readFileSync(resolve(__dirname, `../public/of-mirror/pages/${BUNDLE_MODAL}.html`), "utf8");
    unbinds.push(bindBundleDialog(d, fx.me, fx.settings));
    let fail!: (e: unknown) => void;
    const { h, push } = framed(vi.fn(() => new Promise((_, reject) => (fail = reject))));
    unbinds.push(bindWrites(d, BUNDLE_MODAL, h));
    click(d.querySelector(".modal.show .modal-footer button"));
    // The user went back (Cancel) before OF answered: the same URL again would not reload the frame.
    const page = at(PAGE);
    unbinds.push(bindWrites(page, PAGE, writes()));
    fail(relayError());
    await flush();
    expect(textOf(page.querySelector("#oi-toast .toast__text"))).toBe(fx.error.message);
    expect(push).not.toHaveBeenCalled();
  });

  it("a toast carried to a section root shows on its index page's document (the route's page)", () => {
    at("settings/security");
    const push = vi.fn();
    frameNavigate({ current: { contentDocument: document } as HTMLIFrameElement }, push)("/of-manager/settings", "Synthetic error");
    expect(push).toHaveBeenCalledWith("/of-manager/settings");
    expect(document.querySelector("#oi-toast")).toBeNull();
    const page = at("settings/profile");
    unbinds.push(bindWrites(page, "settings/profile", writes()));
    expect(textOf(page.querySelector("#oi-toast .toast__text"))).toBe("Synthetic error");
  });

  it("a dialog with no Cancel link (no destination): the error's toast shows on the frame's page at once, no navigation", async () => {
    const d = at(BUNDLE_MODAL);
    d.querySelectorAll(".modal-footer a[href]").forEach((a) => a.remove());
    unbinds.push(bindBundleDialog(d, fx.me, fx.settings));
    const { h, push } = framed(vi.fn(() => Promise.reject(relayError())));
    unbinds.push(bindWrites(d, BUNDLE_MODAL, h));
    click(save());
    await flush();
    expect(h.navigate).toHaveBeenCalledWith("", fx.error.message);
    expect(textOf(d.querySelector("#oi-toast .toast__text"))).toBe(fx.error.message);
    expect(push).not.toHaveBeenCalled();
  });

  it("a carried toast expires: its page opened after CARRY_MS shows none", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    try {
      const d = at(BUNDLE_MODAL);
      unbinds.push(bindBundleDialog(d, fx.me, fx.settings));
      unbinds.push(bindWrites(d, BUNDLE_MODAL, framed(vi.fn(() => Promise.reject(relayError()))).h));
      click(save());
      await flush();
      vi.setSystemTime(Date.now() + CARRY_MS);
      const page = at(PAGE);
      unbinds.push(bindWrites(page, PAGE, writes()));
      expect(page.querySelector("#oi-toast")).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });

  it("free (no options): Save is disabled with the reason", () => {
    const d = load(BUNDLE_MODAL);
    unbinds.push(bindBundleDialog(d, free.free.me, free.free.settings));
    expect(save().disabled).toBe(true);
  });
});
