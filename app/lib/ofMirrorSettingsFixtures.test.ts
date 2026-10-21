/**
 * The Settings pages against OF's own /api2/v2 answers for one model, read through the Relay and scrubbed
 * (app/lib/__fixtures__/of/settings-*.json: synthetic names, a placeholder email, no phone, stream keys or IPs).
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { applyPageExtras, applySettings, sourcesFor, STREAM_KEY_MASK, type SettingsSource } from "./ofMirrorSettings";
import { toggleWrite } from "./ofMirrorSettingsWrites";
import { applySubscription, type Bundle } from "./ofMirrorSubscription";
import { standInModel } from "./ofMirrorProfile";
import type { OfMe } from "./ofMirrorIdentity";

const fixture = <T,>(name: string): T => JSON.parse(readFileSync(resolve(__dirname, `__fixtures__/of/settings-${name}.json`), "utf8")) as T;
const ME = fixture<OfMe & Record<string, unknown>>("me");
const SETTINGS = fixture<Record<string, unknown>>("settings");
const load = (page: string) => {
  document.documentElement.innerHTML = readFileSync(resolve(__dirname, `../public/of-mirror/pages/settings/${page}.html`), "utf8");
  return document;
};
const input = (id: string) => document.getElementById(id) as HTMLInputElement;
const textOf = (el: Element | null | undefined) => (el?.textContent ?? "").replace(/\s+/g, " ").trim();
const line = (title: string) =>
  [...document.querySelectorAll("a[href='/of-manager/settings/subscription']")]
    .filter((a) => textOf(a.querySelector(".b-menu-list__text")) === title)
    .map((a) => a.querySelector<HTMLElement>(".b-menu-list__subtext"))
    .find(Boolean)!;
const data = (over: Partial<Record<SettingsSource, unknown>> = {}) => ({
  me: ME,
  settings: SETTINGS,
  story: fixture("story"),
  "notifications:email": fixture("notifications-email"),
  "notifications:message": fixture("notifications-message"),
  "notifications:toast": fixture("notifications-toast"),
  "notifications:webpush": fixture("notifications-webpush"),
  ...over,
});
const PRICED = { ...ME, subscribePrice: 9.69 };

describe("All models: every Settings page shows the first model", () => {
  const accounts = [{ id: "80000112" }, { id: "2" }];
  it.each(["profile", "account", "account/2fa", "subscription", "subscription/trial-links/modal-1", "notifications/email", "security/watermarks/state-options", "qrcode"])(
    "settings/%s",
    (page) => {
      expect(standInModel(`/of-mirror/pages/settings/${page}.html`, null, accounts)).toBe("80000112");
      expect(standInModel(`/of-mirror/pages/settings/${page}.html`, "2", accounts)).toBeNull();
      expect(standInModel(`/of-mirror/pages/settings/${page}.html`, null, [])).toBeNull();
    },
  );
});

describe("the toggles show the model's captured values", () => {
  it("Fans and following", () => {
    load("fans");
    applySettings(document, "fans", data());
    expect(input("setting_isAutoFollowBack").checked).toBe(SETTINGS.isAutoFollowBack);
    expect(input("setting_unfollowAutoFollowBack").checked).toBe(SETTINGS.unfollowAutoFollowBack);
    expect(input("setting_recommenderReward").checked).toBe(!!SETTINGS.recommenderReward);
    expect(input("setting_sendAwardsTop1").checked).toBe(SETTINGS.sendAwardsTop1);
    expect(input("setting_sendAwardsTop5").checked).toBe(SETTINGS.sendAwardsTop5);
  });

  it("Privacy and safety reads /users/me and /users/me/settings", () => {
    load("security");
    applySettings(document, "security", data());
    for (const f of ["isVisibleOnline", "showSubscribersCount", "showMediaCount", "isWantComments"]) expect(input(`setting_${f}`).checked).toBe(ME[f]);
    for (const f of ["showFriendsToSubscribers", "isOldLoginRedirect", "isSuggestionsOptOut", "commentsOnlyForPayers", "creatorsCommentsOnlyForFriends", "showPostsTips", "isDrmEnabled"])
      expect(input(`setting_${f}`).checked).toBe(SETTINGS[f]);
  });

  it("Two Step Authentication shows the app, SMS and Face ID switches, all disabled", () => {
    load("account/2fa");
    applySettings(document, "account/2fa", data({ settings: { ...SETTINGS, appOtp: true, phoneOtp: false, faceOtp: true } }));
    applyPageExtras(document, "account/2fa", data());
    expect([input("show_otp_settings").checked, input("otp_phone_settings").checked, input("otp_face_info").checked]).toEqual([true, false, true]);
    for (const el of document.querySelectorAll<HTMLInputElement | HTMLButtonElement>("#content input, #content button")) {
      expect(el.disabled).toBe(true);
      expect(el.title).toBe("Not available in Inflowwww yet");
    }
  });

  it("Account: the Phone number line is OF's six stars and the last four digits; no phone, no line", () => {
    expect(sourcesFor("account")).toContain("settings");
    load("account");
    const phone = () => document.querySelector("#content a[href='/of-manager/settings/account/phone'] .b-menu-list__subtext");
    applyPageExtras(document, "account", data({ settings: { ...SETTINGS, phoneLast4: null } }));
    expect(phone()).toBeNull();
    applyPageExtras(document, "account", data());
    applyPageExtras(document, "account", data());
    expect(textOf(phone())).toBe(`******${SETTINGS.phoneLast4}`);
    expect(document.querySelectorAll("#content a[href='/of-manager/settings/account/phone'] .b-menu-list__subtext")).toHaveLength(1);
  });

  it("Phone number with a phone: OF's connected view (masked number, verified hint), Delete and Update phone disabled", () => {
    expect(sourcesFor("account/phone")).toContain("settings");
    load("account/phone");
    for (let i = 0; i < 2; i++) applyPageExtras(document, "account/phone", data());
    const field = input("connected_phone_number");
    expect([field.value, field.readOnly, field.disabled]).toEqual([`******${SETTINGS.phoneLast4}`, true, true]);
    expect(textOf(document.querySelector(".phone-setting-block .g-input__help"))).toBe(`Phone number ******${SETTINGS.phoneLast4} is verified`);
    const buttons = [...document.querySelectorAll<HTMLButtonElement>(".phone-setting-block button")].map((b) => [textOf(b), b.disabled, b.title]);
    expect(buttons).toEqual([
      ["Delete", true, "Not available in Inflowwww yet"],
      ["Update phone", true, "Not available in Inflowwww yet"],
    ]);
    expect(document.querySelectorAll("#connected_phone_number")).toHaveLength(1);
  });

  it("Two Step Authentication: Verification via SMS says OF's Phone ******<last 4>", () => {
    load("account/2fa");
    for (let i = 0; i < 2; i++) applyPageExtras(document, "account/2fa", data());
    const sms = input("otp_phone_settings").closest(".g-input__wrapper")!;
    expect(textOf(sms.querySelector(".g-input__help"))).toBe(`Phone ******${SETTINGS.phoneLast4}`);
    expect(sms.querySelectorAll(".g-input__help")).toHaveLength(1);
  });

  it("Streaming: OBS's Server is the model's; the Stream Key is masked, never in the page; Reset and Copy stay disabled", () => {
    load("streaming");
    applySettings(document, "streaming", data());
    applyPageExtras(document, "streaming", data());
    const field = (label: string) => {
      const l = [...document.querySelectorAll<HTMLLabelElement>("#content label.v-label")].find((x) => textOf(x) === label)!;
      return input(l.htmlFor);
    };
    expect(field("Server").value).toBe(SETTINGS.streamingRtmpServer);
    expect(field("Stream Key").value).toBe(STREAM_KEY_MASK);
    expect(document.documentElement.outerHTML).not.toContain(String(SETTINGS.streamingRtmpKey));
    for (const b of [...document.querySelectorAll<HTMLButtonElement>("#content button")].filter((x) => /^(Reset|Copy key|Copy link)$/.test(textOf(x)))) {
      expect(b.disabled).toBe(true);
      expect(b.title).toBe("Not available in Inflowwww yet");
    }
    applyPageExtras(document, "streaming", data({ settings: { ...SETTINGS, streamingRtmpKey: "" } }));
    expect(field("Stream Key").value).toBe("");
  });

  it("Account: the Email line and Email's field are users/me's email, read-only, with OF's verified hint", () => {
    expect(sourcesFor("account")).toContain("me");
    expect(sourcesFor("account/email")).toEqual(["me"]);
    load("account");
    applyPageExtras(document, "account", data());
    expect(textOf(document.querySelector("#content a[href='/of-manager/settings/account/email'] .b-menu-list__subtext"))).toBe(ME.email);
    load("account/email");
    applyPageExtras(document, "account/email", data());
    applyPageExtras(document, "account/email", data());
    const field = input("authUser_email");
    expect(field.value).toBe(ME.email);
    expect([field.readOnly, field.disabled, field.title]).toEqual([true, true, "Not available in Inflowwww yet"]);
    const help = field.closest(".v-input")!.querySelector(".g-input__help")!;
    expect(textOf(help)).toBe(`E-mail ${ME.email} is verified`);
    // Not verified: no hint (OF's error text is not in the capture).
    applyPageExtras(document, "account/email", data({ me: { ...ME, isEmailChecked: false } }));
    expect(textOf(help)).toBe("");
    // Two Step Authentication's passwordless note.
    load("account/2fa");
    expect(sourcesFor("account/2fa")).toContain("me");
    applyPageExtras(document, "account/2fa", data());
    expect(document.querySelector("#content .alert-text-wrapper b")?.textContent).toBe(ME.email);
  });

  it("Tags and Mentions, and each notification channel's group=1 answer", () => {
    load("notifications/mentions");
    applySettings(document, "notifications/mentions", data());
    for (const f of ["notifyOnAllMentions", "muteTagsInChats", "muteTagsInPosts", "muteTagsInStories"]) expect(input(`setting_${f}`).checked).toBe(SETTINGS[f]);
    for (const t of ["email", "message", "toast", "webpush"] as const) {
      load(`notifications/${t}`);
      applySettings(document, `notifications/${t}`, data());
      const groups = fixture<{ items: { code: string; isEnabled: boolean }[] }[]>(`notifications-${t}`);
      for (const it of groups.flatMap((g) => g.items)) {
        const el = input(`toggle_${it.code}`);
        if (el) expect([t, it.code, el.checked]).toEqual([t, it.code, it.isEnabled]);
      }
    }
  });

  it("Story's replies switch and the watermarks", () => {
    load("story");
    applySettings(document, "story", data());
    expect(input("show_subscribes_offers").checked).toBe(fixture<{ allowReplyFrom: string }>("story").allowReplyFrom === "subscribers");
    load("security/watermarks");
    applySettings(document, "security/watermarks", data());
    expect(input("hasWatermarkPhoto").checked).toBe(ME.hasWatermarkPhoto);
    expect(document.querySelector<HTMLInputElement>("input[name='watermark_position']")?.value).toBe(ME.watermarkPosition);
    expect(textOf(document.querySelector("#input-watermark-text")?.closest(".v-input")?.querySelector(".g-input__help"))).toBe(`Current: ${ME.watermarkText}`);
  });

  it("a failed or missing read leaves OF's captured state (the error state)", () => {
    load("fans");
    const before = input("setting_isAutoFollowBack").checked;
    applySettings(document, "fans", {});
    applyPageExtras(document, "fans", {});
    expect(input("setting_isAutoFollowBack").checked).toBe(before);
    expect(line("Following price").style.display).toBe("none"); // the generator's hidden placeholder price stays hidden
  });
});

describe("OF's computed lines (applyPageExtras)", () => {
  it("Profile: no price line while free; '$P per month, N subscription bundles' with a price", () => {
    expect(sourcesFor("profile")).toContain("me");
    load("profile");
    applyPageExtras(document, "profile", data());
    expect(line("Subscription price and bundles").style.display).toBe("none");
    applyPageExtras(document, "profile", data({ me: PRICED }));
    expect(textOf(line("Subscription price and bundles"))).toBe("$9.69 per month, 2 subscription bundles");
    expect(line("Subscription price and bundles").hasAttribute("data-oi-price")).toBe(false);
  });

  it("Fans: 'Free' and the referral switch disabled while free; '$P per month' with a price", () => {
    expect(sourcesFor("fans")).toEqual(expect.arrayContaining(["settings", "me"]));
    load("fans");
    applyPageExtras(document, "fans", data());
    expect(textOf(line("Following price"))).toBe("Free");
    expect(input("setting_recommenderReward").disabled).toBe(true);
    applyPageExtras(document, "fans", data({ me: PRICED }));
    expect(textOf(line("Following price"))).toBe("$9.69 per month");
    expect(input("setting_recommenderReward").disabled).toBe(false);
  });

  it("the referral switch saves OF's transform-value", () => {
    load("fans");
    const el = input("setting_recommenderReward");
    el.checked = true;
    expect(toggleWrite("fans", el, data())).toEqual({ method: "PATCH", path: "/api/of/v2/users/me", body: { recommenderReward: "1 month" } });
    el.checked = false;
    expect(toggleWrite("fans", el, data())?.body).toEqual({ recommenderReward: null });
  });
});

describe("Subscription bundles come from /users/me, as OF's list", () => {
  const bundles = ME.subscriptionBundles as Bundle[];
  const header = (t: string) => [...document.querySelectorAll("h3.b-menu-list__el")].find((h) => textOf(h.querySelector(".b-menu-list__text")) === t)!;
  it("draws the captured bundles; free: both headers and every bundle grayed, as OF", () => {
    load("subscription");
    applySubscription(document, "settings/subscription", { promotions: { rows: [] }, bundles: { rows: bundles } }, ME);
    const rows = [...document.querySelectorAll(".m-bundle-row[data-oi-row]")];
    expect(rows.map((r) => textOf(r.querySelector(".b-offer-join__details")))).toEqual(bundles.map((b) => `$${(b.price ?? 0).toFixed(2).replace(".00", "")} USD total for ${b.duration} months -${b.discount}%`));
    expect(rows.every((r) => r.querySelector(".b-offer-join__content")!.classList.contains("g-disabled"))).toBe(true);
    expect(header("Subscription bundles").classList.contains("m-disabled-block")).toBe(true);
    expect(header("Profile promotion campaign").classList.contains("m-disabled-block")).toBe(true);
  });

  it("with a price nothing is grayed; no bundles draws none (the empty state)", () => {
    load("subscription");
    applySubscription(document, "settings/subscription", { promotions: { rows: [] }, bundles: { rows: [] } }, { ...PRICED, canCreatePromotion: true });
    expect(document.querySelectorAll(".m-bundle-row[data-oi-row]")).toHaveLength(0);
    expect(header("Subscription bundles").classList.contains("m-disabled-block")).toBe(false);
    expect(header("Profile promotion campaign").classList.contains("m-disabled-block")).toBe(false);
  });
});

describe("Watermarks: the custom text field, as OF's form", () => {
  it("holds the model's custom text, blank for OF's default; an untouched Save sends it back", async () => {
    const { collectWatermarks } = await import("./ofMirrorSettingsWrites");
    load("security/watermarks");
    applySettings(document, "security/watermarks", data());
    applyPageExtras(document, "security/watermarks", data());
    expect(input("input-watermark-text").value).toBe(ME.watermarkText);
    expect(collectWatermarks(document)).toMatchObject({ watermarkText: ME.watermarkText, watermarkPosition: ME.watermarkPosition });
    applyPageExtras(document, "security/watermarks", data({ me: { ...ME, watermarkText: `OnlyFans.com/${ME.username}` } }));
    expect(input("input-watermark-text").value).toBe("");
  });
});

describe("OF's narrow layout (below its LG media query, 1004px)", () => {
  it("adds the sheet once and marks the root", async () => {
    const { applyLayout, NARROW_CSS } = await import("./ofMirrorSettings");
    load("profile");
    applyLayout(document, true);
    applyLayout(document, true);
    expect(document.querySelectorAll("#oi-settings-mq")).toHaveLength(1);
    expect(document.getElementById("oi-settings-mq")!.textContent).toBe(NARROW_CSS);
    expect(NARROW_CSS).toContain("max-width: 1003.98px");
    expect(document.documentElement.classList.contains("oi-settings-root")).toBe(true);
    applyLayout(document, false);
    expect(document.documentElement.classList.contains("oi-settings-root")).toBe(false);
  });

  it("narrow: the root's menu marks nothing current; a page's back arrow leads to the settings menu", async () => {
    const { applyLayout } = await import("./ofMirrorSettings");
    const mm = window.matchMedia;
    window.matchMedia = ((q: string) => ({ matches: q.includes("1003.98"), media: q })) as never;
    try {
      load("profile");
      applyLayout(document, false);
      expect(document.querySelector(".b-settings__header__left-col > a")!.getAttribute("href")).toBe("/of-manager/settings");
      load("profile");
      applyLayout(document, true);
      expect(document.querySelectorAll(".b-settings__nav .m-current")).toHaveLength(0);
    } finally {
      window.matchMedia = mm;
    }
  });
});
