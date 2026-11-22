import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import { bindWrites, NOT_YET, READ_ONLY, SAVED_TOAST, SELECT_MODEL } from "./ofMirrorWrites";
import { applyPageExtras, applySettings } from "./ofMirrorSettings";
import { drawObsServer, STREAM_KEY_MASK } from "./ofMirrorObsServer";
import { DIGEST_OFF } from "./ofMirrorSettingsPages";
import { streamCopy } from "./ofMirrorStreamCopy";
import {
  bindSettingsWrites,
  CLOSE_ALL_ASK,
  CLOSE_ALL_WRITE,
  closeAllNote,
  collectWatermarks,
  frequencyChoices,
  frequencyWrite,
  isPricePage,
  parsePrice,
  RESET_KEY_ASK,
  resetKeyNote,
  resetKeyWrite,
  settingWrite,
  toggleWrite,
  type SettingsWrite,
} from "./ofMirrorSettingsWrites";

/** The captured page `settings/<page>` as the frame's document. */
const load = (page: string) => {
  document.documentElement.innerHTML = readFileSync(resolve(__dirname, `../public/of-mirror/pages/settings/${page}.html`), "utf8");
  return document;
};
const input = (id: string) => document.getElementById(id) as HTMLInputElement;
const noteText = () => document.getElementById("oi-note")?.textContent ?? null;
const toastText = () => document.querySelector("#oi-toast .toast__text")?.textContent ?? null;
const flush = () => new Promise((r) => setTimeout(r, 0));
/** A click on the control's label, as an operator toggles OF's switches (the browser fires change on the input). */
const toggle = (id: string) => (document.querySelector(`label[for='${id}']`) as HTMLElement).click();

let unbinds: (() => void)[] = [];
afterEach(() => {
  for (const u of unbinds) u();
  unbinds = [];
});

/** Bind both write layers on `settings/<page>`, as the frame does; returns the recorded settings writes. */
function bind(page: string, opts: { data?: object; me?: object; fail?: string; confirm?: boolean; scope?: "all"; standIn?: boolean; newWrites?: boolean } = {}) {
  const doc = load(page);
  const sent: SettingsWrite[] = [];
  const handlers =
    opts.scope === "all"
      ? null
      : {
          send: (w: SettingsWrite) => (sent.push(w), opts.fail ? Promise.reject(new Error(opts.fail)) : Promise.resolve({ success: true })),
          confirm: vi.fn(() => opts.confirm ?? true),
          standIn: !!opts.standIn,
        };
  unbinds.push(bindWrites(doc, `settings/${page}`, null, true));
  unbinds.push(bindSettingsWrites(doc, `settings/${page}`, () => (opts.data ?? {}) as never, opts.me, handlers, opts.newWrites ?? true));
  return { sent, handlers };
}

describe("settingWrite (OF's saveUserSetting routing)", () => {
  it("sends security-section keys to settings/security, allowReplyFrom to story, the rest to /users/me", () => {
    expect(settingWrite("isAutoFollowBack", true)).toEqual({
      method: "PATCH",
      path: "/api/of/v2/users/me/settings/security",
      body: { isAutoFollowBack: true },
    });
    expect(settingWrite("coStreamingRequestFrom", "friends").path).toBe("/api/of/v2/users/me/settings/security");
    expect(settingWrite("allowReplyFrom", "nobody")).toEqual({
      method: "PATCH",
      path: "/api/of/v2/users/settings/story",
      body: { allowReplyFrom: "nobody" },
    });
    expect(settingWrite("isVisibleOnline", false)).toEqual({ method: "PATCH", path: "/api/of/v2/users/me", body: { isVisibleOnline: false } });
    expect(settingWrite("muteTagsInChats", true).path).toBe("/api/of/v2/users/me");
  });
});

describe("toggleWrite", () => {
  it("maps each mirrored notification toggle to OF's body for its transport", () => {
    load("notifications/toast");
    const el = input("toggle_new_tips");
    el.checked = false;
    expect(toggleWrite("notifications/toast", el, {})).toEqual({
      method: "PATCH",
      path: "/api/of/v2/users/settings/notifications",
      body: { notifications: { toast: [{ code: "new_tips", value: false }] } },
    });
  });

  it("sends email items as 1 or false and a digest as its frequency", () => {
    load("notifications/email");
    const tips = input("toggle_new_tips");
    tips.checked = true;
    expect(toggleWrite("notifications/email", tips, {})!.body).toEqual({ notifications: { email: [{ code: "new_tips", value: 1 }] } });
    tips.checked = false;
    expect(toggleWrite("notifications/email", tips, {})!.body).toEqual({ notifications: { email: [{ code: "new_tips", value: false }] } });
    const digest = input("toggle_new_likes_digest");
    digest.checked = true;
    expect(toggleWrite("notifications/email", digest, {})!.body).toEqual({ notifications: { email: [{ code: "new_likes_digest", value: 24 }] } });
    const groups = [{ code: "g", items: [{ code: "new_likes_digest", isEnabled: false, value: 6 }] }];
    expect(toggleWrite("notifications/email", digest, { "notifications:email": groups })!.body).toEqual({
      notifications: { email: [{ code: "new_likes_digest", value: 6 }] },
    });
  });

  it("sends email's master switches as fields, and email off turns the newsletter off too", () => {
    load("notifications/email");
    const all = input("toggle_email-notifications");
    all.checked = false;
    expect(toggleWrite("notifications/email", all, {})).toEqual({
      method: "PATCH",
      path: "/api/of/v2/users/settings/notifications",
      body: { isEmailNotificationsEnabled: false, isMonthlyNewsletters: false },
    });
    const important = input("toggle_important-email-notifications");
    important.checked = true;
    expect(toggleWrite("notifications/email", important, {})!.body).toEqual({ importantSubscriptionNotifications: true });
  });

  it("maps story replies, co-streaming radios and leaves unmapped or Form controls alone", () => {
    load("story");
    const story = input("show_subscribes_offers");
    story.checked = true;
    expect(toggleWrite("story", story, {})!.body).toEqual({ allowReplyFrom: "subscribers" });
    story.checked = false;
    expect(toggleWrite("story", story, {})!.body).toEqual({ allowReplyFrom: "nobody" });

    load("streaming");
    const friends = input("allowFriends");
    friends.checked = true;
    expect(toggleWrite("streaming", friends, {})).toEqual({
      method: "PATCH",
      path: "/api/of/v2/users/me/settings/security",
      body: { coStreamingRequestFrom: "friends" },
    });

    load("notifications/webpush");
    expect(toggleWrite("notifications/webpush", input("push-notifications"), {})).toBeNull(); // the browser's permission
    load("security/watermarks");
    expect(toggleWrite("security/watermarks", input("hasWatermarkPhoto"), {})).toBeNull(); // its Save sends it
    load("profile");
    expect(toggleWrite("profile", input("input-location"), {})).toBeNull(); // ofMirrorWrites' Save
  });
});

describe("bindSettingsWrites: toggles", () => {
  it("a security toggle saves on change with OF's body, shows OF's settings toast and is marked wired", async () => {
    const { sent } = bind("security");
    expect(input("setting_isVisibleOnline").hasAttribute("data-oi-wired")).toBe(true);
    const was = input("setting_showPostsTips").checked;
    toggle("setting_showPostsTips");
    await flush();
    expect(sent).toEqual([{ method: "PATCH", path: "/api/of/v2/users/me/settings/security", body: { showPostsTips: !was } }]);
    expect(input("setting_showPostsTips").checked).toBe(!was);
    expect(toastText()).toBe(SAVED_TOAST);
    expect(noteText()).toBeNull();
  });

  it("a fans toggle off the security list PATCHes /users/me", async () => {
    const { sent } = bind("fans");
    toggle("setting_sendAwardsTop1");
    await flush();
    expect(sent).toEqual([{ method: "PATCH", path: "/api/of/v2/users/me", body: { sendAwardsTop1: input("setting_sendAwardsTop1").checked } }]);
  });

  it("a failed save flips the toggle back with the error note", async () => {
    bind("notifications/mentions", { fail: "403 Forbidden" });
    const was = input("setting_muteTagsInPosts").checked;
    toggle("setting_muteTagsInPosts");
    await flush();
    expect(input("setting_muteTagsInPosts").checked).toBe(was);
    expect(noteText()).toBe("Could not save: 403 Forbidden");
  });

  it("a failed radio puts the loaded value back", async () => {
    bind("streaming", { fail: "nope", data: { settings: { coStreamingRequestFrom: "nobody" } } });
    toggle("allowFriends");
    await flush();
    expect(["allowSubscribers", "allowFriends", "allowNobody"].map((id) => input(id).checked)).toEqual([false, false, true]);
  });

  it("all models: nothing is sent, the toggle flips back and says select a model", () => {
    const { sent } = bind("fans", { scope: "all" });
    const was = input("setting_isAutoFollowBack").checked;
    toggle("setting_isAutoFollowBack");
    expect(sent).toEqual([]);
    expect(input("setting_isAutoFollowBack").checked).toBe(was);
    expect(noteText()).toBe(SELECT_MODEL);
  });

  it("the browser's push permission switch (no Relay write) is disabled with the tooltip and unmarked", () => {
    bind("notifications/webpush");
    const sw = input("push-notifications");
    expect(sw.disabled).toBe(true);
    expect(sw.title).toBe(NOT_YET);
    expect(sw.hasAttribute("data-oi-wired")).toBe(false);
  });
});

describe("watermarks Save", () => {
  it("collects both checkboxes, the position and the typed text only", () => {
    load("security/watermarks");
    input("hasWatermarkPhoto").checked = true;
    input("hasWatermarkVideo").checked = false;
    // A blank field is sent blank, as OF's save(): OF then uses its default text. No position before users/me's.
    expect(collectWatermarks(document)).toEqual({ hasWatermarkPhoto: true, hasWatermarkVideo: false, watermarkText: "" });
    document.querySelector<HTMLInputElement>("input[name='watermark_position']")!.value = "bottom_right"; // as applySettings sets it
    expect(collectWatermarks(document)).toMatchObject({ watermarkPosition: "bottom_right" });
    input("input-watermark-text").value = "Synthetic";
    expect(collectWatermarks(document)).toMatchObject({ watermarkText: "Synthetic" });
    input("hasWatermarkPhoto").checked = false;
    expect(collectWatermarks(document)).not.toHaveProperty("watermarkText"); // OF drops it with no watermark on
  });

  it("turns Save on after a change and PUTs the security section", async () => {
    const { sent } = bind("security/watermarks");
    const save = [...document.querySelectorAll<HTMLButtonElement>("form .g-btn__wrapper button")].find((b) => b.textContent!.trim() === "Save")!;
    expect(save.disabled).toBe(true);
    toggle("hasWatermarkVideo");
    expect(noteText()).toBeNull(); // not ofMirrorWrites' read-only note
    expect(save.disabled).toBe(false);
    save.click();
    await flush();
    expect(sent).toEqual([{ method: "PUT", path: "/api/of/v2/users/me/settings/security", body: collectWatermarks(document) }]);
    expect(toastText()).toBe(SAVED_TOAST);
    expect(noteText()).toBeNull();
  });
});

describe("subscription price", () => {
  it("parses OF's price field", () => {
    expect(parsePrice("")).toBe(0);
    expect(parsePrice("9.99")).toBe(9.99);
    expect(parsePrice("$12")).toBe(12);
    expect(parsePrice("9.999")).toBe("Enter a valid price");
    expect(parsePrice("abc")).toBe("Enter a valid price");
  });

  it("is on the subscription tabs, not their modals", () => {
    expect(isPricePage("settings/subscription")).toBe(true);
    expect(isPricePage("settings/subscription/trial-links")).toBe(true);
    expect(isPricePage("settings/subscription/tracking-links/state-kebab")).toBe(true);
    expect(isPricePage("settings/subscription/tracking-links/modal-1")).toBe(false);
    expect(isPricePage("settings/security")).toBe(false);
  });

  it("shows the real price and PATCHes subscribePrice after the confirm", async () => {
    const { sent, handlers } = bind("subscription", { me: { subscribePrice: 9.99 } });
    const price = input("priceInput_23");
    expect(price.value).toBe("9.99");
    const save = document.querySelector<HTMLButtonElement>("form[data-vv-scope='action-info-form'] button[type='submit']")!;
    expect(save.hasAttribute("data-oi-wired")).toBe(true);
    price.value = "12.50";
    price.dispatchEvent(new Event("input", { bubbles: true }));
    expect(save.disabled).toBe(false);
    save.click();
    await flush();
    expect(handlers!.confirm).toHaveBeenCalledWith("Change the subscription price to $12.50 per month?");
    expect(sent).toEqual([{ method: "PATCH", path: "/api/of/v2/users/me", body: { subscribePrice: 12.5 } }]);
    expect(toastText()).toBe(SAVED_TOAST);
  });

  it("sends nothing when the confirm is declined or the price is invalid", () => {
    const { sent } = bind("subscription", { confirm: false });
    const price = input("priceInput_23");
    const save = document.querySelector<HTMLButtonElement>("form[data-vv-scope='action-info-form'] button[type='submit']")!;
    price.value = "";
    price.dispatchEvent(new Event("input", { bubbles: true }));
    save.click();
    price.value = "1.2.3";
    price.dispatchEvent(new Event("input", { bubbles: true }));
    save.click();
    expect(sent).toEqual([]);
    expect(noteText()).toBe("Enter a valid price");
  });
});

// ticket 60
describe("drawn switches and email Update frequency", () => {
  const NOTIF = "/api/of/v2/users/settings/notifications";
  /** `settings/<page>` with its extras drawn from `data`, then both write layers bound. */
  function drawn(page: string, data: object, opts: { fail?: string; scope?: "all" } = {}) {
    const r = bind(page, { ...opts, data });
    applySettings(document, page, data as never);
    applyPageExtras(document, page, data as never, true);
    return r;
  }
  const freq = () => document.querySelector("#toggle_new_likes_digest")!.closest("span")!.parentElement!.querySelector<HTMLElement>(".v-select")!;
  const shown = () => freq().querySelector(".v-select__selection")?.textContent;
  const menuRows = () => [...document.querySelectorAll<HTMLElement>("#oi-menu [data-oi-group]")];
  const email = (on: boolean, hours: number | false) => ({
    settings: { isEmailNotificationsEnabled: true },
    "notifications:email": [{ items: [{ code: "new_likes_digest", isEnabled: on, value: on ? hours : 0 }] }], // the fixture's shape
  });

  it.each([
    ["messaging", "messageOnlyFromFriends", { me: { subscribePrice: 0 }, settings: { canAcceptMessageOnlyFromFriends: false } }, "/api/of/v2/users/me", "canAcceptMessageOnlyFromFriends"],
    ["security", "setting_isPrivate", { me: { isPerformer: true, isAdultContent: false }, settings: { isPrivate: false } }, "/api/of/v2/users/me/settings/security", "isPrivate"],
  ])("%s: the drawn switch saves its key on change, keeps the tooltip, is not the read-only note", async (page, id, data, path, key) => {
    const { sent } = drawn(page, data);
    expect(input(id).title).toBe(NOT_YET);
    toggle(id);
    await flush();
    expect(sent).toEqual([{ method: "PATCH", path, body: { [key]: true } }]);
    expect(toastText()).toBe(SAVED_TOAST);
    expect(noteText()).toBeNull();
  });

  it.each([
    ["messaging", "messageOnlyFromFriends", { me: { subscribePrice: 0 }, settings: { canAcceptMessageOnlyFromFriends: true } }],
    ["security", "setting_isPrivate", { me: { isPerformer: true, isAdultContent: false }, settings: { isPrivate: true } }],
  ])("%s: a failed save (502) puts the drawn switch back with the red note", async (page, id, data) => {
    drawn(page, data, { fail: "502 Bad Gateway" });
    toggle(id);
    await flush();
    expect(input(id).checked).toBe(true);
    expect(noteText()).toBe("Could not save: 502 Bad Gateway");
    expect((document.getElementById("oi-note") as HTMLElement).style.color).toMatch(/255, 69, 69|#ff4545/i);
  });

  it("switch off (OFM_NEW_WRITES_ENABLED unset): the drawn Fully private stays Not yet, never marked Wired, sends nothing (live 2026-11-21)", () => {
    const data = { me: { isPerformer: true, isAdultContent: false }, settings: { isPrivate: false } };
    const { sent } = bind("security", { data, newWrites: false }); // bound first, as live: Show activity status is Wired
    applySettings(document, "security", data as never);
    applyPageExtras(document, "security", data as never, false); // the drawn row is its clone
    const el = input("setting_isPrivate");
    expect([el.hasAttribute("data-oi-wired"), el.disabled, el.title]).toEqual([false, true, NOT_YET]);
    toggle("setting_isPrivate");
    expect(sent).toEqual([]);
  });

  it("no model: the drawn switch sends nothing, flips back, says select a model", () => {
    const { sent } = drawn("messaging", { me: { subscribePrice: 0 }, settings: { canAcceptMessageOnlyFromFriends: false } }, { scope: "all" });
    toggle("messageOnlyFromFriends");
    expect(sent).toEqual([]);
    expect(input("messageOnlyFromFriends").checked).toBe(false);
    expect(noteText()).toBe(SELECT_MODEL);
  });

  const OF_LIST = [
    { value: 1, label: "Every Hour" },
    { value: 3, label: "3 Hours" },
    { value: 6, label: "6 Hours" },
    { value: 12, label: "12 Hours" },
    { value: 24, label: "24 Hours" },
  ];
  it.each([
    [24, OF_LIST],
    [1, OF_LIST],
    [48, [...OF_LIST, { value: 48, label: "Every 48 Hours" }]],
    [2, [OF_LIST[0], { value: 2, label: "Every 2 Hours" }, ...OF_LIST.slice(1)]],
  ])("frequency choices for stored %s h: OF's captured list (settings--email-frequency-menu-page), a stored value off it kept", (stored, want) => {
    expect(frequencyChoices(stored)).toEqual(want);
  });

  it("frequencyWrite is the email digest notifications body", () => {
    expect(frequencyWrite(12)).toEqual({ method: "PATCH", path: NOTIF, body: { notifications: { email: [{ code: "new_likes_digest", value: 12 }] } } });
  });

  it.each([
    [false, false, "Every 24 Hours", true],
    [true, 12, "Every 12 Hours", false],
  ])("digest on=%s stored=%s: shows %s, disabled=%s; select and field lose the Not-yet title (Live pass, D1), an off select says why", (on, hours, text, disabled) => {
    drawn("notifications/email", email(on as boolean, hours as number | false));
    expect(shown()).toBe(text);
    expect(freq().classList.contains("v-input--is-disabled")).toBe(disabled);
    expect(freq().closest(".b-menu-list__el")!.classList.contains("m-disabled")).toBe(disabled);
    expect(freq().querySelector<HTMLInputElement>("input#input-189")!.disabled).toBe(disabled);
    expect(freq().getAttribute("title")).toBe(disabled ? DIGEST_OFF : null);
    expect(freq().querySelector<HTMLInputElement>("input#input-189")!.hasAttribute("title")).toBe(false);
    expect(freq().hasAttribute("data-oi-wired")).toBe(true);
  });

  it("a pick sends the digest with the hours and shows it; the menu lists OF's choices", async () => {
    const { sent } = drawn("notifications/email", email(true, 12));
    freq().click();
    expect(menuRows().map((r) => r.textContent)).toEqual(["Every Hour", "3 Hours", "6 Hours", "12 Hours", "24 Hours"]);
    menuRows()[4].click();
    await flush();
    expect(sent).toEqual([frequencyWrite(24)]);
    expect(shown()).toBe("Every 24 Hours");
    expect(toastText()).toBe(SAVED_TOAST);
    expect(noteText()).toBeNull();
  });

  it("a failed frequency save (502) puts the old value back with the red note", async () => {
    drawn("notifications/email", email(true, 12), { fail: "502 Bad Gateway" });
    freq().click();
    menuRows()[1].click();
    await flush();
    expect(shown()).toBe("Every 12 Hours");
    expect(noteText()).toBe("Could not save: 502 Bad Gateway");
  });

  it("while the digest is off the select opens nothing; switching it on makes it usable", async () => {
    const { sent } = drawn("notifications/email", email(false, false));
    freq().click();
    expect(menuRows()).toEqual([]);
    toggle("toggle_new_likes_digest");
    await flush();
    expect(sent).toEqual([{ method: "PATCH", path: NOTIF, body: { notifications: { email: [{ code: "new_likes_digest", value: 24 }] } } }]);
    expect(freq().classList.contains("v-input--is-disabled")).toBe(false);
  });

  it("no model: a pick sends nothing and says select a model", () => {
    const { sent } = drawn("notifications/email", email(true, 12), { scope: "all" });
    freq().click();
    menuRows()[1].click();
    expect(sent).toEqual([]);
    expect(shown()).toBe("Every 12 Hours");
    expect(noteText()).toBe(SELECT_MODEL);
  });
});

// ticket 63
describe("Close all sessions (account/sessions)", () => {
  const button = () =>
    [...document.querySelectorAll<HTMLButtonElement>("#content button")].find((b) => b.textContent?.trim() === "Close all sessions")!;
  const modal = () => document.getElementById("ModalConfirm");
  const [cancelBtn, okBtn] = [0, 1].map((i) => () => modal()!.querySelectorAll<HTMLButtonElement>(".modal-footer button")[i]);
  const WRONG_USER = 'upstream 400: {"error":{"code":301,"message":"Wrong user."}}';

  it("is usable and Wired, its Not-yet title kept, after the page's settings apply", () => {
    bind("account/sessions");
    applyPageExtras(document, "account/sessions", { sessions: [] }, true);
    expect([button().disabled, button().hasAttribute("data-oi-wired"), button().title]).toEqual([false, true, NOT_YET]);
    // every other Account control stays disabled
    expect([...document.querySelectorAll<HTMLButtonElement>("#content button")].filter((b) => b !== button() && !b.disabled)).toEqual([]);
  });

  it.each([
    ["Cancel", cancelBtn, []],
    ["Confirm", okBtn, [CLOSE_ALL_WRITE]],
  ])("%s on OF's confirm sends %j", async (_name, pick, want) => {
    const { sent } = bind("account/sessions");
    button().click();
    await flush();
    expect([modal()?.querySelector(".modal-title")?.textContent, modal()?.querySelector(".dialog_message")?.textContent]).toEqual([
      CLOSE_ALL_ASK.title,
      CLOSE_ALL_ASK.text,
    ]);
    expect(CLOSE_ALL_ASK.text).toMatch(/cannot be undone/);
    pick().click();
    await flush();
    expect([sent, modal()]).toEqual([want, null]);
    expect(CLOSE_ALL_WRITE).toEqual({ method: "DELETE", path: "/api/of/v2/sessions" });
  });

  it.each([
    ["a session-lost answer says to re-link the Creator", WRONG_USER, /re-linked in Manage creators/],
    ["a 502 says it could not", "upstream 502: synthetic", /^Could not close sessions: upstream 502/],
  ])("%s, in red", async (_name, fail, want) => {
    bind("account/sessions", { fail });
    button().click();
    await flush();
    okBtn().click();
    await flush();
    await flush();
    expect(noteText()).toMatch(want);
    expect(document.getElementById("oi-note")!.style.color).toBe("rgb(255, 69, 69)");
  });

  it.each([
    ["All models with no stand-in", { scope: "all" as const }],
    ["All models' stand-in", { standIn: true }],
  ])("%s: no confirm, nothing sent, Select a model", async (_name, opts) => {
    const { sent } = bind("account/sessions", opts);
    button().click();
    await flush();
    expect([sent, modal(), noteText()]).toEqual([[], null, SELECT_MODEL]);
  });

  it.each([
    [WRONG_USER, true],
    ["upstream 400: Wrong password", false],
    ["upstream 502: x", false],
  ])("closeAllNote(%j) re-link: %s", (fail, relink) => {
    expect(closeAllNote(new Error(fail)).includes("re-linked")).toBe(relink);
  });

  it.each([
    ['{"upstream_status":"refused_by_relay","upstream_body":"refused: DELETE /api2/v2/sessions (ends sessions)"}',
      `Could not close sessions: ${NOT_YET}`],
    ["upstream 502: x", "Could not close sessions: upstream 502: x"],
  ])("closeAllNote(%j) = %j", (fail, want) => {
    expect(closeAllNote(new Error(fail))).toBe(want);
  });
});

// ticket 66
describe("Block by country and Block by IP (Lockout writes)", () => {
  const COUNTRIES = [
    { code: "AQ", name: "Antarctica" },
    { code: "US", name: "United States of America" },
  ];
  const data = { settings: { blockedCountries: [], blockedStates: [], blockedIps: [] }, countries: COUNTRIES };
  const modal = () => document.getElementById("ModalConfirm");
  const [cancelBtn, okBtn] = [0, 1].map((i) => () => modal()!.querySelectorAll<HTMLButtonElement>(".modal-footer button")[i]);
  const box = () => document.querySelector<HTMLElement>("#content .g-select__wrapper .v-input")!;
  const countrySave = () => document.querySelector<HTMLButtonElement>("#content .g-page__header .g-btn__wrapper button[type='submit']")!;
  const field = () => document.getElementById("input-blocked-ips") as HTMLTextAreaElement;
  const ipButton = (t: string) => [...document.querySelectorAll<HTMLButtonElement>("#content .b-settings__row.g-btn__wrapper button")].find((b) => b.textContent?.trim() === t)!;
  const chips = () => [...document.querySelectorAll("#oi-countries [data-oi-country]")].map((c) => c.getAttribute("data-oi-country"));
  const type = (text: string) => {
    field().value = text;
    field().dispatchEvent(new Event("input", { bubbles: true }));
  };
  const pickAntarctica = async () => {
    box().click();
    await flush();
    document.querySelector<HTMLElement>("#oi-menu [data-oi-value='AQ']")!.click();
  };
  const COUNTRY_PAGE = "security/block_by_country";
  const IP_PAGE = "security/block_by_ip";

  it.each([COUNTRY_PAGE, IP_PAGE])("%s: its controls Wired, their Not-yet titles dropped (Live pass, D1)", (page) => {
    bind(page, { data });
    const els = page === COUNTRY_PAGE ? [box(), document.getElementById("input-298")!, countrySave()] : [field(), ipButton("Cancel"), ipButton("Save")];
    expect(els.map((e) => e.hasAttribute("data-oi-wired"))).toEqual([true, true, true]);
    expect(els.map((e) => e.hasAttribute("title"))).toEqual([false, false, false]);
    expect(document.querySelector("a.of-state-link")).toBeNull();
  });

  it("the saved countries show as chips by name once the settings read lands", () => {
    const read: { settings?: object; countries?: object } = {};
    bind(COUNTRY_PAGE, { data: read });
    expect(chips()).toEqual([]);
    Object.assign(read, { ...data, settings: { blockedCountries: ["US"] } });
    applyPageExtras(document, COUNTRY_PAGE, read as never, true);
    expect(document.querySelector("#oi-countries")?.textContent).toBe("United States of America ✕");
  });

  it.each([COUNTRY_PAGE, IP_PAGE])("%s: a read landing during an edit keeps the edit; after Cancel it shows", async (page) => {
    const read = { ...data };
    bind(page, { data: read });
    if (page === COUNTRY_PAGE) await pickAntarctica();
    else type("192.0.2.1");
    read.settings = { blockedCountries: ["US"], blockedStates: [], blockedIps: ["198.51.100.7"] } as never;
    applyPageExtras(document, page, read as never, true);
    expect(page === COUNTRY_PAGE ? chips() : field().value).toEqual(page === COUNTRY_PAGE ? ["AQ"] : "192.0.2.1");
    if (page === IP_PAGE) {
      ipButton("Cancel").click();
      applyPageExtras(document, page, read as never, true);
      expect(field().value).toBe("198.51.100.7");
    }
  });

  it.each([
    ["OK", okBtn, [{ method: "PUT", path: "/api/of/v2/users/me/settings/security/blocked-countries", body: { blockedCountries: ["AQ"], blockedStates: [] } }]],
    ["Cancel", cancelBtn, []],
  ])("country: pick Antarctica, Save, %s on the confirm naming it", async (_n, pick, want) => {
    const { sent } = bind(COUNTRY_PAGE, { data });
    expect(countrySave().disabled).toBe(true);
    await pickAntarctica();
    expect([chips(), countrySave().disabled]).toEqual([["AQ"], false]);
    countrySave().click();
    await flush();
    expect(modal()?.querySelector(".dialog_message")?.textContent).toBe("People in Antarctica will not be able to see your profile or posts.");
    pick().click();
    await flush();
    await flush();
    expect(sent).toEqual(want);
    if (want.length) expect([toastText(), countrySave().disabled]).toEqual([SAVED_TOAST, true]);
  });

  it("country: a chip click unpicks it; typing filters the list", async () => {
    bind(COUNTRY_PAGE, { data });
    await pickAntarctica();
    document.querySelector<HTMLElement>("#oi-countries [data-oi-country='AQ']")!.click();
    expect([chips(), countrySave().disabled]).toEqual([[], true]);
    const input = document.getElementById("input-298") as HTMLInputElement;
    input.value = "united";
    input.dispatchEvent(new Event("input", { bubbles: true }));
    expect([...document.querySelectorAll("#oi-menu [data-oi-value]")].map((r) => r.getAttribute("data-oi-value"))).toEqual(["US"]);
  });

  it.each([
    ["OK", okBtn, [{ method: "PUT", path: "/api/of/v2/users/me/settings/security/blocked-ips", body: { blockedIps: ["192.0.2.1"] } }]],
    ["Cancel", cancelBtn, []],
  ])("IP: type 192.0.2.1, Save, %s on the confirm naming it", async (_n, pick, want) => {
    const { sent } = bind(IP_PAGE, { data });
    expect([ipButton("Save").disabled, ipButton("Cancel").disabled]).toEqual([true, true]);
    type("192.0.2.1");
    ipButton("Save").click();
    await flush();
    expect(modal()?.querySelector(".dialog_message")?.textContent).toBe("Visitors from 192.0.2.1 will not be able to see your profile or posts.");
    pick().click();
    await flush();
    await flush();
    expect(sent).toEqual(want);
  });

  it("IP: Cancel puts the saved list back and sends nothing", () => {
    const { sent } = bind(IP_PAGE, { data: { settings: { blockedIps: ["198.51.100.7"] } } });
    type("192.0.2.1");
    ipButton("Cancel").click();
    expect([field().value, sent, modal(), ipButton("Cancel").disabled]).toEqual(["198.51.100.7", [], null, true]);
  });

  it("IP: a line that is not an address disables Save and says so", () => {
    bind(IP_PAGE, { data });
    type("192.0.2.999");
    expect([ipButton("Save").disabled, ipButton("Cancel").disabled]).toEqual([true, false]);
    expect(document.querySelector("#content .v-messages__wrapper")?.textContent).toBe("Not an IP address: 192.0.2.999");
  });

  it.each([
    ["All models with no stand-in", { scope: "all" as const }],
    ["All models' stand-in", { standIn: true }],
  ])("%s: read-only, Select a model, nothing sent", async (_name, opts) => {
    const { sent } = bind(COUNTRY_PAGE, { data, ...opts });
    box().click();
    await flush();
    expect([document.getElementById("oi-menu"), noteText(), (document.getElementById("input-298") as HTMLInputElement).readOnly]).toEqual([null, SELECT_MODEL, true]);
    bind(IP_PAGE, { data, ...opts });
    field().click();
    expect([noteText(), field().readOnly, ipButton("Save").disabled, sent]).toEqual([SELECT_MODEL, true, true, []]);
  });

  it.each([COUNTRY_PAGE, IP_PAGE])("%s: a 502 says it could not, in red, and the page shows the saved list", async (page) => {
    bind(page, { data, fail: "upstream 502: synthetic" });
    if (page === COUNTRY_PAGE) await pickAntarctica();
    else type("192.0.2.1");
    (page === COUNTRY_PAGE ? countrySave() : ipButton("Save")).click();
    await flush();
    okBtn().click();
    await flush();
    await flush();
    expect(noteText()).toBe("Could not save: upstream 502: synthetic");
    expect(document.getElementById("oi-note")!.style.color).toBe("rgb(255, 69, 69)");
    expect(page === COUNTRY_PAGE ? chips() : field().value).toEqual(page === COUNTRY_PAGE ? [] : "");
  });
});

// ticket 76
describe("Reset stream key (streaming)", () => {
  const button = () =>
    [...document.querySelectorAll<HTMLButtonElement>("#content button")].find((b) => b.textContent?.trim() === "Reset")!;
  const modal = () => document.getElementById("ModalConfirm");
  const [cancelBtn, okBtn] = [0, 1].map((i) => () => modal()!.querySelectorAll<HTMLButtonElement>(".modal-footer button")[i]);
  const keyField = () => {
    const label = [...document.querySelectorAll<HTMLLabelElement>("#content label.v-label")].find((l) => l.textContent?.trim() === "Stream Key")!;
    return document.getElementById(label.htmlFor) as HTMLInputElement;
  };

  it("is usable and Wired, its Not-yet title kept", () => {
    bind("streaming");
    expect([button().disabled, button().hasAttribute("data-oi-wired"), button().title]).toEqual([false, true, NOT_YET]);
  });

  it.each([
    ["Cancel", cancelBtn, []],
    ["Confirm", okBtn, [resetKeyWrite("obs_agora")]],
  ])("%s on OF's confirm sends %j", async (_name, pick, want) => {
    const { sent } = bind("streaming");
    button().click();
    await flush();
    expect([modal()?.querySelector(".modal-title")?.textContent, modal()?.querySelector(".dialog_message")?.textContent]).toEqual([
      RESET_KEY_ASK.title,
      RESET_KEY_ASK.text,
    ]);
    pick().click();
    await flush();
    expect([sent, modal()]).toEqual([want, null]);
  });

  it("sends the capture record's request for the OBS server the page shows, no body", async () => {
    expect(resetKeyWrite("obs_agora")).toEqual({ method: "DELETE", path: "/api/of/v2/streams/obs/key?type=obs_agora" });
    const { sent } = bind("streaming");
    drawObsServer(document, undefined, "mux_direct");
    button().click();
    await flush();
    okBtn().click();
    await flush();
    expect(sent).toEqual([{ method: "DELETE", path: "/api/of/v2/streams/obs/key?type=mux_direct" }]);
    expect(toastText()).toBe(SAVED_TOAST);
  });

  it("after a reset the field shows the new key masked, never its text; Copy key copies the new key", () => {
    load("streaming");
    const fresh = { streamingRtmpServer: "rtmp://synthetic.invalid/live", streamingRtmpKey: "oi-synthetic-new-key" };
    drawObsServer(document, fresh);
    expect(keyField().value).toBe(STREAM_KEY_MASK);
    expect(document.documentElement.outerHTML.includes("oi-synthetic-new-key")).toBe(false);
    expect(streamCopy("key", fresh, null, true, "obs_agora")).toEqual({ text: "oi-synthetic-new-key", toast: "Copied to clipboard" });
  });

  it("a failed reset is the red note", async () => {
    bind("streaming", { fail: "upstream 502: synthetic" });
    button().click();
    await flush();
    okBtn().click();
    await flush();
    await flush();
    expect(noteText()).toBe("Could not reset the stream key: upstream 502: synthetic");
    expect(document.getElementById("oi-note")!.style.color).toBe("rgb(255, 69, 69)");
    expect(resetKeyNote(new Error("x"))).toBe("Could not reset the stream key: x");
    expect(resetKeyNote(new Error('{"upstream_status":"refused_by_relay","upstream_body":"Live guard refused"}'))).toBe(
      `Could not reset the stream key: ${NOT_YET}`,
    );
  });

  it.each([
    ["All models with no stand-in", { scope: "all" as const }],
    ["All models' stand-in", { standIn: true }],
  ])("%s: no confirm, nothing sent, Select a model", async (_name, opts) => {
    const { sent } = bind("streaming", opts);
    button().click();
    await flush();
    expect([sent, modal(), noteText()]).toEqual([[], null, SELECT_MODEL]);
  });
});
