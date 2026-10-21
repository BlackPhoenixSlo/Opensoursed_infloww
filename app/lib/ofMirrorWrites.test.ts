import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it, vi } from "vitest";
import { bindPost } from "./ofMirrorPost";
import { RelayError } from "./relay";
import { BANK_NOTE, BANK_URL, bindWrites, collectProfilePatch, message, OLD_RELAY, collectStream, collectTrackingLink, localIso, parseDate, parseTime, prefillStream, NOT_YET, QUEUE, READ_ONLY, SAVED_TOAST, SELECT_MODEL, SUBMITS, WRITABLE } from "./ofMirrorWrites";

const PROFILE = `
<div class="g-btn__wrapper"><button disabled="disabled" type="submit" class="g-btn"> Save </button></div>
<form>
  <div class="g-input__wrapper"><input id="input-login" value="yourmodel"></div>
  <div class="g-input__wrapper"><input id="input-name" value="Your Model"></div>
  <div class="g-input__wrapper"><div contenteditable="true" data-placeholder="Bio"><p>Line one</p><p>Line two</p></div></div>
  <div class="g-input__wrapper"><input id="input-location" value="Paris"></div>
  <div class="g-input__wrapper"><input id="input-website" value="https://example.com"></div>
  <div class="g-input__wrapper"><input id="input-wishlist" value=""></div>
</form>`;

const doc = (html: string) => {
  document.body.innerHTML = html;
  return document;
};
const handlers = () => ({
  saveProfile: vi.fn(() => Promise.resolve()),
  setReplyOnSubscribe: vi.fn(() => Promise.resolve()),
  submit: vi.fn((_path: string, _body: unknown) => Promise.resolve({ id: 1 })),
  navigate: vi.fn(),
});
/** The real generated schedule form (streaming/dashboard/create). */
const CREATE = "streaming/dashboard/create";
const loadPage = (page: string) => {
  document.documentElement.innerHTML = readFileSync(resolve(__dirname, `../public/of-mirror/pages/${page}.html`), "utf8");
  return document;
};
/** Fill the schedule form: date, time and the description editor's text. */
const fillStream = (d: Document, date: string, time: string, text = "") => {
  (d.querySelector("input[name='date']") as HTMLInputElement).value = date;
  (d.querySelector("input[name='time']") as HTMLInputElement).value = time;
  d.querySelector(".create-scheduled__description [contenteditable]")!.innerHTML = text ? `<p>${text}</p>` : "<p><br></p>";
};
const clickSubmit = (d: Document, page = CREATE) => {
  const ev = new MouseEvent("click", { bubbles: true, cancelable: true });
  d.querySelector(SUBMITS[page].button)!.dispatchEvent(ev);
  return ev;
};
/** The real "Create new tracking link" modal (settings/subscription/tracking-links/modal-1). */
const TRACKING = "settings/subscription/tracking-links/modal-1";
const trackingName = (d: Document) => d.querySelector("input[name='name']") as HTMLInputElement;
const trackingButton = (d: Document) => d.querySelector(SUBMITS[TRACKING].button) as HTMLButtonElement;
/** Type `text` into the tracking link name, as an input event. */
const typeName = (d: Document, text: string) => {
  trackingName(d).value = text;
  fire(trackingName(d), "input");
};
/** A local day `days` ahead, as yyyy-mm-dd. */
const ahead = (days: number) => localIso(new Date(Date.now() + days * 86_400_000)).slice(0, 10);
const flush = () => new Promise((r) => setTimeout(r, 0));
const fire = (el: Element, type: string) => el.dispatchEvent(new Event(type, { bubbles: true }));
/** The real promotion ("Start campaign"), bundle ("Save") and free trial link ("Create link") modals: no Known body. */
const PROMOTION = "settings/subscription/promotion-campaign/modal-1";
const BUNDLE = "settings/subscription/promotion-campaign/modal-2";
const TRIAL = "settings/subscription/trial-links/modal-1";
const UNSENT: Record<string, string> = { [PROMOTION]: "Start campaign", [BUNDLE]: "Save", [TRIAL]: "Create link" };
const footerButton = (d: Document, page: string) =>
  [...d.querySelectorAll<HTMLButtonElement>(".modal-footer button")].find((b) => b.textContent?.trim() === UNSENT[page])!;
/** No handler was called. */
const untouched = (h: ReturnType<typeof handlers>) => Object.values(h).forEach((fn) => expect(fn).not.toHaveBeenCalled());

describe("collectProfilePatch", () => {
  it("reads the writable fields only, the bio one line per paragraph", () => {
    const d = doc(PROFILE);
    expect(collectProfilePatch(d)).toEqual({
      name: "Your Model",
      about: "Line one\nLine two",
      location: "Paris",
      website: "https://example.com",
      wishlist: "",
    });
    expect(collectProfilePatch(d, ["name"])).toEqual({ name: "Your Model" });
  });
});

describe("bindWrites", () => {
  it("enables Save on a change and saves the changed fields", async () => {
    const d = doc(PROFILE);
    const h = handlers();
    const unbind = bindWrites(d, "settings/profile", h);
    const save = d.querySelector("button")!;
    const name = d.getElementById("input-name") as HTMLInputElement;
    name.value = "New Name";
    fire(name, "input");
    expect(save.disabled).toBe(false);
    save.click();
    expect(h.saveProfile).toHaveBeenCalledWith({ name: "New Name" });
    expect(save.disabled).toBe(true);
    await flush();
    expect(save.disabled).toBe(true);
    expect(d.querySelector("#oi-toast .toast__text")?.textContent).toBe(SAVED_TOAST);
    expect(d.getElementById("oi-note")).toBeNull();
    unbind();
  });

  it("settings/profile: Display name's and Bio's counters follow typing; the Bio takes its own click, no State page link over it (U18)", () => {
    const page = "settings/profile";
    const d = loadPage(page);
    expect(d.querySelector(".input-text-editor .of-state-link")).toBeNull();
    const unbind = bindWrites(d, page, handlers());
    const name = d.getElementById("input-name") as HTMLInputElement;
    name.value = "Ana";
    fire(name, "input");
    expect(name.closest(".v-input")!.querySelector(".v-counter")!.textContent!.trim()).toBe("3 / 40");
    const bio = d.querySelector("[data-placeholder='Bio']")!;
    bio.innerHTML = "<p>Hello</p>";
    fire(bio, "input");
    expect(bio.closest(".g-input__wrapper")!.querySelector(".count-block")!.textContent!.trim()).toBe("5/1000");
    unbind();
  });

  it.each(["bank/index", "bank/payments", "bank/dac7/edit"])("%s: one grey line under the title says the bank details stay on onlyfans.com, linking there; unbind removes it", (page) => {
    const d = loadPage(page);
    const unbind = bindWrites(d, page, null);
    const line = d.getElementById("oi-bank-note")!;
    expect(line.previousElementSibling!.matches(".g-page__header")).toBe(true);
    expect(line.textContent).toBe(`${BANK_NOTE} Open banking on onlyfans.com`);
    const link = line.querySelector("a")!;
    expect([link.href, link.target, link.hasAttribute("data-oi-wired")]).toEqual([BANK_URL, "_blank", true]);
    link.addEventListener("click", (ev) => ev.preventDefault());
    link.click();
    expect(d.getElementById("oi-note")).toBeNull(); // not the Read-only note
    unbind();
    expect(d.getElementById("oi-bank-note")).toBeNull();
    // Only the Bank pages have it.
    const other = loadPage("statements/earnings");
    bindWrites(other, "statements/earnings", null)();
    expect(other.getElementById("oi-bank-note")).toBeNull();
  });

  it("re-enables Save and shows the error when saving fails", async () => {
    const d = doc(PROFILE);
    const h = { ...handlers(), saveProfile: vi.fn(() => Promise.reject(new Error("relay 502"))) };
    const unbind = bindWrites(d, "settings/profile", h);
    fire(d.querySelector("[data-placeholder='Bio']")!, "input");
    d.querySelector("button")!.click();
    expect(h.saveProfile).toHaveBeenCalledWith({ about: "Line one\nLine two" });
    await flush();
    expect(d.querySelector("button")!.disabled).toBe(false);
    expect(d.getElementById("oi-note")?.textContent).toBe("Could not save: relay 502");
    unbind();
  });

  it("saves the welcome switch in place with OF's settings toast", async () => {
    const d = doc(`<div class="g-input__wrapper"><input id="autoMessage" type="checkbox" name="autoMessage"></div>`);
    const h = handlers();
    const unbind = bindWrites(d, "settings/messaging", h);
    const sw = d.getElementById("autoMessage") as HTMLInputElement;
    sw.click();
    expect(h.setReplyOnSubscribe).toHaveBeenCalledWith(true);
    await flush();
    expect(sw.checked).toBe(true);
    expect(d.querySelector("#oi-toast .toast__text")?.textContent).toBe(SAVED_TOAST);
    expect(h.navigate).not.toHaveBeenCalled();
    unbind();
  });

  it("sends the welcome switch and reverts it on failure", async () => {
    const d = doc(`<div class="g-input__wrapper"><input id="autoMessage" type="checkbox" name="autoMessage"></div>`);
    const h = { ...handlers(), setReplyOnSubscribe: vi.fn(() => Promise.reject(new Error("relay 403"))) };
    const unbind = bindWrites(d, "settings/messaging", h);
    const sw = d.getElementById("autoMessage") as HTMLInputElement;
    sw.click();
    expect(h.setReplyOnSubscribe).toHaveBeenCalledWith(true);
    await flush();
    expect(sw.checked).toBe(false);
    expect(d.getElementById("oi-note")?.textContent).toBe("Could not save: relay 403");
    unbind();
  });

  it("sends nothing for an unmapped toggle and shows the read-only note", () => {
    const d = doc(`<div class="g-input__wrapper"><input id="setting_isAutoFollowBack" type="checkbox"></div>`);
    const h = handlers();
    const unbind = bindWrites(d, "settings/fans", h);
    const toggle = d.getElementById("setting_isAutoFollowBack") as HTMLInputElement;
    toggle.click();
    expect(h.saveProfile).not.toHaveBeenCalled();
    expect(h.setReplyOnSubscribe).not.toHaveBeenCalled();
    const n = d.getElementById("oi-note");
    expect(n?.textContent).toBe("Read-only in Inflowwww for now");
    expect(n?.previousElementSibling?.classList.contains("g-input__wrapper")).toBe(true);
    expect(toggle.checked).toBe(false); // flipped back
    unbind();
  });

  it("schedule form: SCHEDULE posts the stream and opens the queue", async () => {
    const d = loadPage(CREATE);
    const h = handlers();
    const unbind = bindWrites(d, CREATE, h);
    const day = ahead(2);
    fillStream(d, day, "18:30", "Synthetic stream"); // the browser's time input gives 24h
    const editor = d.querySelector(".create-scheduled__description [contenteditable]")!;
    fire(editor, "input");
    expect(editor.getAttribute("data-is-empty")).toBe("false"); // the label moves up, as OF's script does
    expect(d.querySelector(".create-scheduled__description .count-block")?.textContent?.trim()).toBe("16/500");
    fire(d.querySelector("input[name='date']")!, "change");
    expect(d.getElementById("oi-note")).toBeNull(); // the form's own fields are not read-only
    expect(clickSubmit(d).defaultPrevented).toBe(true);
    const [y, m, dd] = day.split("-").map(Number);
    const want = localIso(new Date(y, m - 1, dd, 18, 30));
    expect(h.submit).toHaveBeenCalledWith("/api/of/v2/streams", { description: "Synthetic stream", scheduledDate: want, isShowTips: true });
    expect(want).toMatch(new RegExp(`^${day}T18:30:00[+-]\\d{2}:\\d{2}$`));
    expect((d.querySelector(SUBMITS[CREATE].button) as HTMLButtonElement).disabled).toBe(true);
    await flush();
    expect(h.navigate).toHaveBeenCalledWith(QUEUE);
    unbind();
  });

  it("schedule form: an empty or past form sends nothing and shows the validation note", () => {
    const d = loadPage(CREATE);
    const h = handlers();
    const unbind = bindWrites(d, CREATE, h);
    const submit = d.querySelector(SUBMITS[CREATE].button)!;
    clickSubmit(d);
    let n = d.getElementById("oi-note");
    expect(n?.textContent).toBe("Enter a date and a time");
    expect(n?.style.color).toBe("rgb(255, 69, 69)");
    expect(n?.nextElementSibling).toBe(submit);
    fillStream(d, ahead(-1), "10:00");
    fire(d.querySelector("input[name='time']")!, "input");
    expect(d.getElementById("oi-note")).toBeNull(); // typing clears the stale note
    clickSubmit(d);
    n = d.getElementById("oi-note");
    expect(n?.textContent).toBe("Pick a time at least a minute from now");
    expect(h.submit).not.toHaveBeenCalled();
    expect(h.navigate).not.toHaveBeenCalled();
    unbind();
  });

  it("schedule form: shows the relay error and stays on the form", async () => {
    const d = loadPage(CREATE);
    const h = { ...handlers(), submit: vi.fn(() => Promise.reject(new Error("upstream 400: Date is in the past"))) };
    const unbind = bindWrites(d, CREATE, h);
    fillStream(d, ahead(1), "12:00");
    clickSubmit(d);
    await flush();
    expect(d.getElementById("oi-note")?.textContent).toBe("Could not schedule: upstream 400: Date is in the past");
    expect((d.querySelector(SUBMITS[CREATE].button) as HTMLButtonElement).disabled).toBe(false);
    expect(h.navigate).not.toHaveBeenCalled();
    unbind();
  });

  it("tracking link: Create Link turns on with a name and posts {name}, then follows Cancel", async () => {
    const d = loadPage(TRACKING);
    const h = handlers();
    const unbind = bindWrites(d, TRACKING, h);
    expect(trackingButton(d).disabled).toBe(true); // as captured: no name yet
    typeName(d, "  Synthetic link ");
    expect(trackingButton(d).disabled).toBe(false);
    // The label floats clear of the value and the counter counts, as OF's script does.
    expect(trackingName(d).closest(".v-input")?.classList.contains("v-input--is-label-active")).toBe(true);
    expect(d.querySelector(".v-counter")?.textContent).toBe("17 / 100"); // "  Synthetic link " as typed;
    expect(collectTrackingLink(d)).toEqual({ name: "Synthetic link" });
    fire(trackingName(d), "change");
    expect(d.getElementById("oi-note")).toBeNull(); // the modal's own field is not read-only
    expect(clickSubmit(d, TRACKING).defaultPrevented).toBe(true);
    expect(h.submit).toHaveBeenCalledTimes(1);
    expect(h.submit).toHaveBeenCalledWith("/api/of/v2/campaigns", { name: "Synthetic link" });
    expect(trackingButton(d).disabled).toBe(true);
    await flush();
    expect(h.navigate).toHaveBeenCalledWith("/of-manager/settings/subscription/tracking-links");
    unbind();
  });

  it("tracking link: a blank name keeps Create Link off and sends nothing", () => {
    const d = loadPage(TRACKING);
    const h = handlers();
    const unbind = bindWrites(d, TRACKING, h);
    typeName(d, "   ");
    expect(trackingButton(d).disabled).toBe(true);
    clickSubmit(d, TRACKING);
    typeName(d, "Synthetic link");
    expect(trackingButton(d).disabled).toBe(false);
    typeName(d, "");
    expect(trackingButton(d).disabled).toBe(true); // off again once cleared
    clickSubmit(d, TRACKING);
    expect(h.submit).not.toHaveBeenCalled();
    expect(h.navigate).not.toHaveBeenCalled();
    unbind();
  });

  it("tracking link: Enter in the name field (a native form submit) sends once and does not navigate the document", () => {
    const d = loadPage(TRACKING);
    const h = handlers();
    const unbind = bindWrites(d, TRACKING, h);
    typeName(d, "Synthetic link");
    let prevented: boolean | undefined;
    const seen = (e: Event) => (prevented = e.defaultPrevented);
    window.addEventListener("submit", seen);
    const href = window.location.href;
    trackingName(d).form!.requestSubmit(); // what Enter in a one-field form does
    window.removeEventListener("submit", seen);
    expect(prevented).toBe(true);
    expect(window.location.href).toBe(href);
    expect(h.submit).toHaveBeenCalledTimes(1);
    expect(h.submit).toHaveBeenCalledWith("/api/of/v2/campaigns", { name: "Synthetic link" });
    unbind();
  });

  it("tracking link: a relay error shows Could not create, re-enables the button and keeps the name", async () => {
    const d = loadPage(TRACKING);
    const h = { ...handlers(), submit: vi.fn(() => Promise.reject(new Error("upstream 400: Synthetic refusal"))) };
    const unbind = bindWrites(d, TRACKING, h);
    typeName(d, "Synthetic link");
    clickSubmit(d, TRACKING);
    await flush();
    const n = d.getElementById("oi-note");
    expect(n?.textContent).toBe("Could not create: upstream 400: Synthetic refusal");
    expect(n?.style.color).toBe("rgb(255, 69, 69)");
    expect(trackingButton(d).disabled).toBe(false);
    expect(trackingName(d).value).toBe("Synthetic link");
    expect(h.navigate).not.toHaveBeenCalled();
    unbind();
  });

  it("tracking link: a second click, or typing, while the create is in flight sends nothing more", () => {
    const d = loadPage(TRACKING);
    const h = { ...handlers(), submit: vi.fn(() => new Promise(() => {})) };
    const unbind = bindWrites(d, TRACKING, h);
    typeName(d, "Synthetic link");
    clickSubmit(d, TRACKING);
    typeName(d, "Synthetic link 2");
    expect(trackingButton(d).disabled).toBe(true);
    clickSubmit(d, TRACKING);
    trackingName(d).form!.requestSubmit();
    expect(h.submit).toHaveBeenCalledTimes(1);
    unbind();
  });

  it("promotion, bundle and free trial link: Start campaign, Save and Create link are enabled (their bodies are OF's own, ofMirrorOffers)", () => {
    for (const page of [PROMOTION, BUNDLE, TRIAL]) {
      const d = loadPage(page);
      const b = footerButton(d, page);
      expect(b, page).toBeTruthy();
      expect(b.disabled, page).toBe(false);
      expect(b.title, page).not.toBe(NOT_YET);
    }
  });

  it("promotion, bundle and free trial link: the submit sends the dialog's collected body to its relay route, then goes to its tab", async () => {
    const want: Record<string, [string, string]> = {
      [PROMOTION]: ["/api/of/v2/promotions", "/of-manager/settings/subscription/promotion-campaign"],
      [BUNDLE]: ["/api/of/v2/subscriptions/bundles", "/of-manager/settings/subscription/promotion-campaign"],
      [TRIAL]: ["/api/of/v2/trials", "/of-manager/settings/subscription/trial-links"],
    };
    for (const page of [PROMOTION, BUNDLE, TRIAL]) {
      const d = loadPage(page);
      // The state ofMirrorOffers keeps on the dialog's form.
      const state = page === BUNDLE ? { discount: 10, duration: 3 } : page === TRIAL ? { name: "Synthetic link", limit: 10, expiration: 7, duration: 7 } : { audience: "new", kind: "trial", limit: 10, expiration: 7, duration: 7, percent: 5, message: "" };
      (d.querySelector(".modal.show form") ?? d.querySelector(".modal.show .modal-body"))!.setAttribute("data-oi-offer", JSON.stringify(state));
      if (page === TRIAL) d.querySelector<HTMLInputElement>(".modal.show input[at-attr='input']")!.value = "Synthetic link";
      const h = handlers();
      const unbind = bindWrites(d, page, h);
      footerButton(d, page).click();
      await Promise.resolve();
      await Promise.resolve();
      expect(h.submit, page).toHaveBeenCalledTimes(1);
      expect(h.submit.mock.calls[0][0], page).toBe(want[page][0]);
      expect(h.navigate, page).toHaveBeenCalledWith(want[page][1]);
      unbind();
    }
  });

  it("promotion and bundle: a native submit from any form on the page is prevented and calls no handler", () => {
    for (const page of [PROMOTION, BUNDLE]) {
      const d = loadPage(page);
      const h = handlers();
      const unbind = bindWrites(d, page, h);
      const forms = [...d.querySelectorAll("form")];
      expect(forms.length, page).toBe(page === PROMOTION ? 2 : 1); // the modal's own form (promotion only) and the price form behind it
      for (const form of forms) {
        const ev = new Event("submit", { bubbles: true, cancelable: true });
        form.dispatchEvent(ev);
        expect(ev.defaultPrevented, page).toBe(true);
      }
      untouched(h);
      unbind();
    }
  });

  it("promotion: its dialog's message and dropdowns are enabled (ofMirrorOffers works them), and their State page openers are gone", () => {
    const d = loadPage(PROMOTION);
    const message = d.querySelector("textarea")!;
    expect(message.disabled).toBe(false);
    const selects = [...d.querySelectorAll(".modal-content .v-select")];
    expect(selects.length).toBeGreaterThan(0);
    for (const sel of selects) expect(sel.classList.contains("v-input--is-disabled")).toBe(false);
    expect(d.querySelector("a.of-state-link[href*='/state-promo-dropdowns-']")).toBeNull();
  });

  describe("with no single model selected (handlers null)", () => {
    it("sends nothing on Save and shows the select-a-model note", () => {
      const d = doc(PROFILE);
      const unbind = bindWrites(d, "settings/profile", null);
      const save = d.querySelector("button")!;
      const name = d.getElementById("input-name") as HTMLInputElement;
      name.value = "New Name";
      fire(name, "input");
      expect(save.disabled).toBe(false);
      const ev = new MouseEvent("click", { bubbles: true, cancelable: true });
      save.dispatchEvent(ev);
      expect(ev.defaultPrevented).toBe(true);
      const n = d.getElementById("oi-note");
      expect(n?.textContent).toBe("Select a model to save changes");
      expect(n?.style.color).toBe("rgb(138, 150, 163)"); // the read-only note's grey
      expect(n?.nextElementSibling).toBe(save);
      unbind();
    });

    it("flips a writable switch back with the select-a-model note", () => {
      const d = doc(`<div class="g-input__wrapper"><input id="autoMessage" type="checkbox" name="autoMessage"></div>`);
      const unbind = bindWrites(d, "settings/messaging", null);
      const sw = d.getElementById("autoMessage") as HTMLInputElement;
      sw.click();
      expect(sw.checked).toBe(false);
      expect(d.getElementById("oi-note")?.textContent).toBe("Select a model to save changes");
      unbind();
    });

    it("an unmapped toggle gets the read-only note and flips back", () => {
      const d = doc(`<div class="g-input__wrapper"><input id="setting_isAutoFollowBack" type="checkbox"></div>`);
      const unbind = bindWrites(d, "settings/fans", null);
      const toggle = d.getElementById("setting_isAutoFollowBack") as HTMLInputElement;
      toggle.click();
      expect(toggle.checked).toBe(false); // flipped back
      expect(d.getElementById("oi-note")?.textContent).toBe(READ_ONLY);
      unbind();
    });

    it("tracking link: Create Link sends nothing and shows the select-a-model note", () => {
      const d = loadPage(TRACKING);
      const unbind = bindWrites(d, TRACKING, null);
      typeName(d, "Synthetic link");
      expect(clickSubmit(d, TRACKING).defaultPrevented).toBe(true);
      expect(d.getElementById("oi-note")?.textContent).toBe(SELECT_MODEL);
      unbind();
    });

    it("promotion, bundle and free trial link: their submit sends nothing and shows the select-a-model note", () => {
      for (const page of [PROMOTION, BUNDLE, TRIAL]) {
        const d = loadPage(page);
        const unbind = bindWrites(d, page, null);
        footerButton(d, page).click();
        expect(d.getElementById("oi-note")?.textContent, page).toBe(SELECT_MODEL);
        unbind();
      }
    });

    it("schedule form: SCHEDULE sends nothing and shows the select-a-model note", () => {
      const d = loadPage(CREATE);
      const unbind = bindWrites(d, CREATE, null);
      fillStream(d, ahead(1), "12:00");
      expect(clickSubmit(d).defaultPrevented).toBe(true);
      expect(d.getElementById("oi-note")?.textContent).toBe("Select a model to save changes");
      unbind();
    });
  });

  it("leaves OF's Dark mode switch alone (it switches our theme)", () => {
    const d = doc(`<div class="g-input__wrapper"><input id="dark_mode_switcher" type="checkbox"></div>`);
    const unbind = bindWrites(d, "settings/display", handlers());
    const sw = d.getElementById("dark_mode_switcher") as HTMLInputElement;
    sw.click();
    expect(sw.checked).toBe(true);
    expect(d.getElementById("oi-note")).toBeNull();
    unbind();
  });
});

describe("bindWrites marks its Wired controls data-oi-wired", () => {
  // bindWrites' Wired controls (the Scheduled events widget's "+" is the generator's, for ofMirrorQueue's Add to queue).
  const wired = (d: Document) => [...d.querySelectorAll("[data-oi-wired]:not([at-attr='add_event_widget'])")];
  const scopes = [["Single-Creator", handlers()], ["All-Creators", null]] as const;

  it.each(scopes)("settings/profile (%s scope): the five profile fields and Save, and only those", (_scope, h) => {
    const d = loadPage("settings/profile");
    const unbind = bindWrites(d, "settings/profile", h);
    const want = ["#input-name", "[data-placeholder='Bio']", "#input-location", "#input-website", "#input-wishlist", ".g-btn__wrapper button[type='submit']"];
    expect(new Set(wired(d))).toEqual(new Set(want.map((sel) => d.querySelector(sel))));
    expect(wired(d)).toHaveLength(want.length);
    unbind();
  });

  it.each(scopes)("settings/messaging (%s scope): the welcome switch", (_scope, h) => {
    const d = loadPage("settings/messaging");
    const unbind = bindWrites(d, "settings/messaging", h);
    expect(wired(d)).toEqual([d.getElementById("autoMessage")]);
    unbind();
  });

  it.each(scopes)("SUBMITS pages (%s scope): the submit button and every field its collect sends (SCHEDULE: date, time, description; Create Link: name)", (_scope, h) => {
    for (const [page, count] of [[CREATE, 3], [TRACKING, 1]] as const) {
      const d = loadPage(page);
      const unbind = bindWrites(d, page, h);
      const fields = [...d.querySelectorAll(SUBMITS[page].fields)];
      expect(fields, page).toHaveLength(count);
      expect(new Set(wired(d)), page).toEqual(new Set([d.querySelector(SUBMITS[page].button), ...fields]));
      expect(wired(d), page).toHaveLength(count + 1);
      unbind();
    }
  });

  it("promotion, bundle and free trial link: the submit and the fields their collect reads are marked", () => {
    for (const page of [PROMOTION, BUNDLE, TRIAL]) {
      const d = loadPage(page);
      const unbind = bindWrites(d, page, handlers());
      const fields = [...d.querySelectorAll(SUBMITS[page].fields)];
      expect(fields.length, page).toBeGreaterThan(0);
      // (the free trial links page behind its dialog: its rows' share, ofMirrorOffers')
      expect(new Set(wired(d).filter((el) => !el.matches("[data-oi-share]"))), page).toEqual(new Set([d.querySelector(SUBMITS[page].button), ...fields]));
      unbind();
    }
  });

  it("profile/state-more-menu, over the profile fixture, marks and binds no WRITABLE field (settings/profile does)", () => {
    const d = doc(PROFILE);
    const h = handlers();
    const unbind = bindWrites(d, "profile/state-more-menu", h);
    expect(wired(d)).toEqual([]);
    const name = d.getElementById("input-name") as HTMLInputElement;
    name.value = "New Name";
    fire(name, "input");
    const save = d.querySelector("button")!;
    expect(save.disabled).toBe(true);
    save.click();
    untouched(h);
    unbind();
    const p = doc(PROFILE);
    const unbindP = bindWrites(p, "settings/profile", h);
    expect(wired(p)).toHaveLength(6); // contrast: the same fixture as a settings page marks its five fields and Save
    unbindP();
  });
});

describe("bindWrites click fallback: an unwired button on any Mirror page shows the Read-only note", () => {
  const scopes = [["Single-Creator", handlers()], ["All-Creators", null]] as const;
  const click = (el: Element) => {
    const ev = new MouseEvent("click", { bubbles: true, cancelable: true });
    el.dispatchEvent(ev);
    return ev;
  };
  const noteOf = (d: Document) => d.getElementById("oi-note");

  it.each(scopes)("queue/index and settings/security/watermarks (%s scope): a <button> and a [role=button] get a fresh note beside them, sending nothing", (_scope, h) => {
    const q = loadPage("queue/index");
    const unbindQ = bindWrites(q, "queue/index", h);
    // OF's sidebar close button: not wired ("Add to queue" is, by ofMirrorQueue).
    const add = q.querySelector("button[at-attr='close_btn']")!;
    expect(noteOf(q)?.textContent ?? null).toBeNull();
    expect(click(add.querySelector("svg") ?? add).defaultPrevented).toBe(false); // a click on its icon; no preventDefault
    expect(noteOf(q)?.textContent).toBe("Read-only in Inflowwww for now");
    expect(noteOf(q)?.nextElementSibling).toBe(add); // before a <button>
    unbindQ();
    noteOf(q)!.remove();
    click(add);
    expect(noteOf(q)).toBeNull(); // the unbind stops it

    // Collections disables its chips and Statements its period select; Watermarks' position select is a [role=button] <div>.
    const c = loadPage("settings/security/watermarks");
    const unbindC = bindWrites(c, "settings/security/watermarks", h);
    const chip = c.querySelector("div[role='button']")!;
    expect(noteOf(c)).toBeNull();
    click(chip.firstElementChild ?? chip);
    expect(noteOf(c)?.textContent).toBe("Read-only in Inflowwww for now");
    expect(noteOf(c)?.previousElementSibling).toBe(chip); // after the control (no field row around it)
    if (h) untouched(h);
    unbindC();
  });

  it("is silent inside a[href], .video-js, [data-oi-wired] and a form field (input, label, textarea, select, [contenteditable])", () => {
    const d = doc(`
      <a href="#queue"><button id="in-link">Open</button></a>
      <a href="#" class="of-state-link"><span role="button" id="in-state-link">Menu</span></a>
      <div class="video-js"><button class="vjs-play-control" id="in-video">Play</button></div>
      <button data-oi-wired id="wired"><span id="in-wired">Post</span></button>
      <div role="button">
        <input id="f-input"><label id="f-label">Label</label><textarea id="f-textarea"></textarea>
        <select id="f-select"></select><div contenteditable="true" id="f-editable"></div>
      </div>
      <button id="other">Other</button>`);
    const unbind = bindWrites(d, "queue/index", handlers());
    for (const id of ["in-link", "in-state-link", "in-video", "wired", "in-wired", "f-input", "f-label", "f-textarea", "f-select", "f-editable"]) {
      click(d.getElementById(id)!);
      expect(noteOf(d), id).toBeNull();
    }
    click(d.getElementById("other")!);
    expect(noteOf(d)?.textContent).toBe(READ_ONLY); // contrast: the same doc's unwired button
    unbind();
  });

  it("is silent on every control of a dialog a binder built ([data-oi-dialog]): a failed Save shows only its own error (U13)", () => {
    const d = doc(`
      <div data-oi-dialog data-oi-wired><div class="modal"><form><div class="modal-footer">
        <button type="submit" id="save"><span id="save-text">Save</span></button><button type="button" id="max">Max</button>
      </div></form></div></div>
      <button id="other">Other</button>`);
    const unbind = bindWrites(d, "collections/index", handlers());
    for (const id of ["save", "save-text", "max"]) {
      click(d.getElementById(id)!);
      expect(noteOf(d), id).toBeNull();
    }
    click(d.getElementById("other")!);
    expect(noteOf(d)?.textContent).toBe(READ_ONLY); // contrast: the page's own unwired button
    unbind();
  });

  it.each(scopes)("covers a dropdown's read-only input and a button nested in a Wired row or a label (%s scope)", (_scope, h) => {
    // settings/security/watermarks: OF's position dropdown is a [role=button] whose middle is a readonly <input>
    const s = loadPage("settings/security/watermarks");
    const unbindS = bindWrites(s, "settings/security/watermarks", h);
    const slot = s.querySelector(".v-input__slot[role='button']")!;
    click(slot.querySelector("input[readonly]")!);
    expect(noteOf(s)?.textContent).toBe(READ_ONLY);
    unbindS();
    // a row kebab inside a marked Co-tag row, and inside a plain label: neither is the row's toggle
    const d = doc(`
      <label class="b-rows-lists__item" data-oi-wired><input type="checkbox"><button id="in-wired-row"><span>More</span></button></label>
      <label class="b-rows-lists__item"><input type="checkbox"><button id="in-label"><span>More</span></button></label>`);
    const unbind = bindWrites(d, "new-post/state-tag-people", h);
    for (const id of ["in-wired-row", "in-label"]) {
      noteOf(d)?.remove();
      click(d.getElementById(id)!.firstElementChild!); // its icon, as OF's kebab
      expect(noteOf(d)?.textContent, id).toBe(READ_ONLY);
      expect(noteOf(d)?.nextElementSibling, id).toBe(d.getElementById(id)); // before the button
    }
    if (h) untouched(h);
    unbind();
  });

  it("is silent on the video player's own buttons (messages/chat)", () => {
    const page = "messages/chat";
    const d = loadPage(page);
    const unbind = bindWrites(d, page, null);
    const player = [...d.querySelectorAll(".video-js button")];
    expect(player.length).toBeGreaterThan(0);
    for (const b of player) click(b);
    expect(noteOf(d)).toBeNull();
    unbind();
  });

  it.each(scopes)("new-post/index (%s scope): the marked Post never shows the Read-only note; All-Creators keeps the select-a-model note", (_scope, h) => {
    const d = loadPage("new-post/index");
    const createPost = vi.fn((_body: unknown) => Promise.resolve({ id: 1 }));
    const unbindPost = bindPost(d, "new-post/index", { handlers: h && { createPost, createLabel: vi.fn(), upload: vi.fn(), navigate: vi.fn() }, storage: null, accountId: null });
    const unbind = bindWrites(d, "new-post/index", h);
    const editor = d.querySelector("[contenteditable][aria-label='Textbox field']")!;
    editor.innerHTML = "<p>Synthetic post</p>";
    fire(editor, "input");
    const post = d.querySelector("button[at-attr='submit_post']")!;
    expect(post.hasAttribute("data-oi-wired")).toBe(true);
    click(post);
    if (h) {
      expect(createPost).toHaveBeenCalledTimes(1);
      expect(noteOf(d)?.textContent).not.toBe(READ_ONLY);
    } else {
      expect(noteOf(d)?.textContent).toBe(SELECT_MODEL);
      expect(createPost).not.toHaveBeenCalled();
    }
    unbind();
    unbindPost();
  });

  /** Click `el` and return the native submit events it raised (as seen after bindWrites' own listener). */
  const submitsOf = (d: Document, el: Element) => {
    const submits: Event[] = [];
    const record = (e: Event) => submits.push(e);
    d.defaultView!.addEventListener("submit", record);
    const ev = click(el);
    d.defaultView!.removeEventListener("submit", record);
    return { click: ev, submits };
  };

  it("settings: another page's Save (no Known body) is disabled with the tooltip and its form's native submit is cancelled", () => {
    const page = "settings/account/password";
    const d = loadPage(page);
    const h = handlers();
    const unbind = bindWrites(d, page, h);
    const save = d.querySelector<HTMLButtonElement>(".g-btn__wrapper button[type='submit']")!;
    expect(save.disabled).toBe(true);
    expect(save.title).toBe(NOT_YET);
    const ev = new Event("submit", { bubbles: true, cancelable: true });
    save.closest("form")!.dispatchEvent(ev);
    expect(ev.defaultPrevented).toBe(true);
    expect(noteOf(d)).toBeNull();
    untouched(h);
    unbind();
  });

  it.each(scopes)("a non-settings page (%s scope): every unwired submit button gets the note and no native submit goes through", (_scope, h) => {
    const d = doc(`
      <form><div class="g-btn__wrapper"><button type="submit" id="first">Search</button></div></form>
      <form><div class="g-btn__wrapper"><button type="submit" id="second">Apply</button></div></form>`);
    const unbind = bindWrites(d, "queue/index", h);
    for (const id of ["first", "second"]) {
      noteOf(d)?.remove();
      const button = d.getElementById(id)!;
      const { submits } = submitsOf(d, button);
      expect(noteOf(d)?.nextElementSibling, id).toBe(button);
      expect(noteOf(d)?.textContent).toBe(READ_ONLY);
      expect(submits.map((e) => e.defaultPrevented), id).toEqual([true]);
    }
    if (h) untouched(h);
    unbind();
  });
});

describe("bindWrites change path: an unwired checkbox on any Mirror page shows the Read-only note and flips back once", () => {
  const scopes = [["Single-Creator", handlers()], ["All-Creators", null]] as const;
  const notes = (d: Document) => [...d.querySelectorAll("#oi-note")].map((n) => n.textContent);

  it.each(scopes)("collections/index (%s scope): an unwired checkbox gets the note and flips back, sending nothing", (_scope, h) => {
    const d = doc(`<div class="b-menu-list__el"><label><input id="box" type="checkbox"> Pinned</label></div>`);
    const unbind = bindWrites(d, "collections/index", h);
    const box = d.getElementById("box") as HTMLInputElement;
    box.click();
    expect(box.checked).toBe(false);
    expect(notes(d)).toEqual([READ_ONLY]);
    if (h) untouched(h);
    unbind();
  });

  it.each(scopes)("a checkbox inside [data-oi-wired] (%s scope) gets no note and no flip", (_scope, h) => {
    const d = doc(`
      <label data-oi-wired><input id="in-wired" type="checkbox"> Alpha One</label>
      <input id="wired" type="checkbox" data-oi-wired>
      <input id="other" type="checkbox">`);
    const unbind = bindWrites(d, "new-post/state-tag-people", h);
    for (const id of ["in-wired", "wired"]) {
      const box = d.getElementById(id) as HTMLInputElement;
      box.click();
      expect(box.checked, id).toBe(true);
      expect(d.getElementById("oi-note"), id).toBeNull();
    }
    (d.getElementById("other") as HTMLInputElement).click();
    expect(notes(d)).toEqual([READ_ONLY]); // contrast: the same doc's unmarked checkbox
    unbind();
  });

  it.each(scopes)("new-post/state-labels with bindPost and bindWrites (%s scope), no Relay labels: no captured example row shows, so none can be checked", (_scope, h) => {
    const page = "new-post/state-labels";
    const d = loadPage(page);
    const createPost = vi.fn((_body: unknown) => Promise.resolve({ id: 1 }));
    const unbindPost = bindPost(d, page, { handlers: h && { createPost, createLabel: vi.fn(), upload: vi.fn(), navigate: vi.fn() }, storage: null, accountId: null });
    const unbind = bindWrites(d, page, h);
    const rows = [...d.querySelectorAll<HTMLElement>(".modal.show label.b-rows-lists__item")];
    expect(rows.length).toBeGreaterThan(0);
    expect(rows.every((r) => r.style.display === "none")).toBe(true);
    expect(createPost).not.toHaveBeenCalled();
    if (h) untouched(h);
    unbind();
    unbindPost();
  });
});

describe("WRITABLE", () => {
  it("names controls that exist in the mirrored pages", () => {
    for (const [page, entries] of Object.entries(WRITABLE)) {
      document.documentElement.innerHTML = readFileSync(resolve(__dirname, `../public/of-mirror/pages/settings/${page}.html`), "utf8");
      for (const sel of Object.keys(entries)) expect(document.querySelector(sel), `${page}: ${sel}`).not.toBeNull();
      const saves = document.querySelectorAll(".g-btn__wrapper button[type='submit']");
      expect(saves.length, page).toBe(page === "profile" ? 1 : 0);
    }
  });

  it("is consulted only for a settings path: the same page outside settings/ writes nothing", () => {
    const d = doc(PROFILE);
    const h = handlers();
    const unbind = bindWrites(d, "profile", h);
    const save = d.querySelector("button")!;
    const name = d.getElementById("input-name") as HTMLInputElement;
    name.value = "New Name";
    fire(name, "input");
    expect(save.disabled).toBe(true);
    save.click();
    expect(h.saveProfile).not.toHaveBeenCalled();
    unbind();
    const m = doc(`<div class="g-input__wrapper"><input id="autoMessage" type="checkbox" name="autoMessage"></div>`);
    const unbindM = bindWrites(m, "messaging", h);
    (m.getElementById("autoMessage") as HTMLInputElement).click();
    expect(h.setReplyOnSubscribe).not.toHaveBeenCalled();
    expect(m.getElementById("oi-note")?.textContent).toBe(READ_ONLY); // the change path's read-only note, as on any page
    expect((m.getElementById("autoMessage") as HTMLInputElement).checked).toBe(false); // flipped back
    unbindM();
  });
});

describe("SUBMITS", () => {
  it("names one submit button in each mirrored page", () => {
    const text: Record<string, string> = {
      [CREATE]: "Schedule", [TRACKING]: "Create Link", [PROMOTION]: "Start campaign", [BUNDLE]: "Save", [TRIAL]: "Create link",
      "new-post/state-promotion": "Start campaign", "new-post/state-trial-link": "Create link", "home/state-promotion": "Start campaign",
    };
    expect(Object.keys(SUBMITS).sort()).toEqual(Object.keys(text).sort());
    for (const [page, { button }] of Object.entries(SUBMITS)) {
      const d = loadPage(page);
      const found = [...d.querySelectorAll(button)];
      expect(found.length, page).toBe(1);
      expect(found[0].textContent?.trim(), page).toBe(text[page]);
    }
  });

  it("the measured labels exist in their modal's page", () => {
    const measured: Record<string, string[]> = {
      [TRACKING]: ["Tracking link name"],
      [PROMOTION]: ["Offer limit", "Offer expiration", "Free trial duration", "Message (optional)"],
      [BUNDLE]: ["Discount percent", "Discount duration"],
    };
    for (const [page, labels] of Object.entries(measured)) {
      const d = loadPage(page);
      const found = [...d.querySelectorAll("label.v-label")].map((l) => l.textContent?.trim());
      for (const label of labels) expect(found, `${page}: ${label}`).toContain(label);
    }
  });
});

describe("schedule form parsing", () => {
  it("reads OF's formatted date and yyyy-mm-dd", () => {
    expect(parseDate("2026-10-20")).toEqual([2026, 10, 20]);
    expect(parseDate("Oct 20, 2026")).toEqual([2026, 10, 20]);
    expect(parseDate("October 20 2026")).toEqual([2026, 10, 20]);
    expect(parseDate("Tue, Oct 20, 2026")).toEqual([2026, 10, 20]);
    expect(parseDate("20 Oct 2026")).toEqual([2026, 10, 20]);
    expect(parseDate("10/20/2026")).toEqual([2026, 10, 20]);
    for (const bad of ["", "2026-02-30", "Foo 20, 2026", "20", "tomorrow"]) expect(parseDate(bad), bad).toBeNull();
  });

  it("reads 24h and 12h times", () => {
    expect(parseTime("18:30")).toEqual([18, 30]);
    expect(parseTime("06:05 PM")).toEqual([18, 5]);
    expect(parseTime("12:00 am")).toEqual([0, 0]);
    expect(parseTime("12:15pm")).toEqual([12, 15]);
    for (const bad of ["", "24:00", "13:00 pm", "7", "7:60"]) expect(parseTime(bad), bad).toBeNull();
  });

  it("formats local ISO with the offset, as moment's .format()", () => {
    const d = new Date(2026, 9, 20, 18, 30);
    const off = -d.getTimezoneOffset();
    const sign = off < 0 ? "-" : "+";
    const hh = String(Math.floor(Math.abs(off) / 60)).padStart(2, "0");
    const mm = String(Math.abs(off) % 60).padStart(2, "0");
    expect(localIso(d)).toBe(`2026-10-20T18:30:00${sign}${hh}:${mm}`);
    expect(new Date(localIso(d)).getTime()).toBe(d.getTime());
  });

  it("the Queue's \"+\" > Stream: ?date= and ?time= fill the empty fields, which collectStream then reads", () => {
    const d = loadPage(CREATE);
    prefillStream(d, "2026-10-21", "1:15 pm");
    const value = (n: string) => d.querySelector<HTMLInputElement>(`input[name='${n}']`)!.value;
    expect([value("date"), value("time")]).toEqual(["Oct 21, 2026", "13:15"]);
    expect(collectStream(d, new Date(2026, 9, 17, 12))).toEqual({ description: "", scheduledDate: localIso(new Date(2026, 9, 21, 13, 15)), isShowTips: true });
    // A typed value stays; a value that does not parse fills nothing.
    fillStream(d, "2026-10-22", "9:00");
    prefillStream(d, "2026-10-21", "1:15 pm");
    expect([value("date"), value("time")]).toEqual(["2026-10-22", "9:00"]);
    const e = loadPage(CREATE);
    prefillStream(e, "someday", "noon");
    expect([e.querySelector<HTMLInputElement>("input[name='date']")!.value, e.querySelector<HTMLInputElement>("input[name='time']")!.value]).toEqual(["", ""]);
  });

  it("Date opens OF's day popup and Apply fills it; Time is the browser's time input; unbind drops the trigger (U11)", () => {
    const d = loadPage(CREATE);
    const unbind = bindWrites(d, CREATE, null);
    const date = d.querySelector<HTMLInputElement>("input[name='date']")!;
    const time = d.querySelector<HTMLInputElement>("input[name='time']")!;
    expect([date.readOnly, time.type]).toEqual([true, "time"]);
    d.querySelector<HTMLElement>(".create-scheduled__time .v-datetime__icon")!.click();
    expect(d.querySelector("[data-oi-picker]")).not.toBeNull();
    d.querySelector<HTMLElement>("[data-oi-picker-apply]")!.click();
    const now = new Date();
    expect(date.value).toBe(now.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" }));
    expect(d.querySelector("[data-oi-picker]")).toBeNull();
    expect(d.getElementById("oi-note")).toBeNull(); // not the Read-only note
    unbind();
    date.click();
    expect(d.querySelector("[data-oi-picker]")).toBeNull();
  });

  it("requires the time at least a minute ahead", () => {
    const d = loadPage(CREATE);
    const now = new Date(2026, 9, 20, 18, 0, 30);
    fillStream(d, "2026-10-20", "18:01", "x");
    expect(collectStream(d, now)).toBe("Pick a time at least a minute from now");
    fillStream(d, "2026-10-20", "18:02", "Line");
    expect(collectStream(d, now)).toEqual({ description: "Line", scheduledDate: localIso(new Date(2026, 9, 20, 18, 2)), isShowTips: true });
    fillStream(d, "someday", "18:02");
    expect(collectStream(d, now)).toBe("Enter a valid date");
    fillStream(d, "2026-10-20", "noon");
    expect(collectStream(d, now)).toBe("Enter a valid time");
  });
});

describe("message: a write's failure as a note says", () => {
  it("FastAPI's no-route answers (a Relay older than the app) say so; every other error keeps its own text", () => {
    expect(message(new RelayError(404, { detail: "Not Found" }, "Not Found"))).toBe(OLD_RELAY);
    expect(message(new RelayError(405, { detail: "Method Not Allowed" }, "Method Not Allowed"))).toBe(OLD_RELAY);
    expect(message(new RelayError(404, { detail: "no proxy with label 'x'" }, "no proxy with label 'x'"))).toBe("no proxy with label 'x'");
    expect(message(new RelayError(502, { detail: { upstream_status: 404, upstream_body: "{}" } }, "upstream 404: {}"))).toBe("upstream 404: {}");
    expect(message(new RelayError(401, "sign in required", "sign in required"))).toBe("sign in required");
    expect(message(new Error("Not Found"))).toBe("Not Found");
    expect(message("boom")).toBe("boom");
  });
});
