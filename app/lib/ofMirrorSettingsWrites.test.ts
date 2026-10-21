import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import { bindWrites, NOT_YET, READ_ONLY, SAVED_TOAST, SELECT_MODEL } from "./ofMirrorWrites";
import {
  bindSettingsWrites,
  collectWatermarks,
  isPricePage,
  parsePrice,
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
function bind(page: string, opts: { data?: object; me?: object; fail?: string; confirm?: boolean; scope?: "all" } = {}) {
  const doc = load(page);
  const sent: SettingsWrite[] = [];
  const handlers =
    opts.scope === "all"
      ? null
      : {
          send: (w: SettingsWrite) => (sent.push(w), opts.fail ? Promise.reject(new Error(opts.fail)) : Promise.resolve({ success: true })),
          confirm: vi.fn(() => opts.confirm ?? true),
        };
  unbinds.push(bindWrites(doc, `settings/${page}`, null));
  unbinds.push(bindSettingsWrites(doc, `settings/${page}`, () => (opts.data ?? {}) as never, opts.me, handlers));
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
