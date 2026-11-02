import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterAll, describe, expect, it, vi } from "vitest";
import { applyAccount, applyMessaging, applySecurity } from "./ofMirrorSettingsPages";
import type { SettingsData } from "./ofMirrorSettings";
import { ELSEWHERE } from "./ofMirrorTooltip";
import { NOT_YET } from "./ofMirrorWrites";

// The host zone pinned before any import (vi.hoisted runs above them; format.ts builds its clock formatter at load,
// so a later pin would split the date from the time): Kathmandu, +05:45 all year, no DST, so local-time expectations
// are literals that fail if the module drew UTC or any other zone. Restored after the file.
vi.hoisted(() => vi.stubEnv("TZ", "Asia/Kathmandu"));
afterAll(() => vi.unstubAllEnvs());

/** The captured page `settings/<page>` as the frame's document. */
const load = (page: string) => {
  document.documentElement.innerHTML = readFileSync(resolve(__dirname, `../public/of-mirror/pages/settings/${page}.html`), "utf8");
  return document;
};
const $ = <T extends Element = HTMLElement>(sel: string) => document.querySelector<T>(sel);
const $$ = <T extends Element = HTMLElement>(sel: string) => [...document.querySelectorAll<T>(sel)];
const input = (id: string) => document.getElementById(id) as HTMLInputElement | null;

// ---------------------------------------------------------------- Account

describe("applyAccount: Account menu (settings/account)", () => {
  const phoneRow = () => $("#content a[href='/of-manager/settings/account/phone']")!;
  const emailLine = () => $("#content a[href='/of-manager/settings/account/email'] .b-menu-list__subtext")!;

  it("Phone number line shows OF's masked phone (six stars, the last 4) after its label, once", () => {
    const doc = load("account");
    expect(phoneRow().querySelector(".b-menu-list__subtext")).toBeNull();
    applyAccount(doc, "account", { settings: { phoneLast4: "1234" } });
    applyAccount(doc, "account", { settings: { phoneLast4: "1234" } });
    const subs = phoneRow().querySelectorAll(".b-menu-list__subtext");
    expect(subs).toHaveLength(1);
    expect(subs[0].textContent).toBe("******1234");
    expect(subs[0].previousElementSibling?.classList.contains("b-menu-list__text")).toBe(true);
  });

  it.each<[string, unknown]>([
    ["no settings", undefined],
    ["empty last4", { phoneLast4: "" }],
    ["numeric last4", { phoneLast4: 1234 }],
    ["null last4", { phoneLast4: null }],
  ])("no Phone number line without a string last4 (%s)", (_name, settings) => {
    const doc = load("account");
    applyAccount(doc, "account", { settings });
    expect(phoneRow().querySelector(".b-menu-list__subtext")).toBeNull();
  });

  it("Email line is users/me's email; none or empty email leaves the generator's dash", () => {
    let doc = load("account");
    expect(emailLine().textContent).toBe("—");
    applyAccount(doc, "account", { me: { email: "m@example.com" } });
    expect(emailLine().textContent).toBe("m@example.com");
    doc = load("account");
    applyAccount(doc, "account", { me: { email: "" } });
    expect(emailLine().textContent).toBe("—");
    applyAccount(doc, "account", { me: { email: 5 } });
    expect(emailLine().textContent).toBe("—");
  });

  it("disables every #content control, adding the house tooltip only where none is set", () => {
    const doc = load("account/2fa");
    const face = input("otp_face_info")!;
    expect(face.title).toBe("");
    const titled = input("otp_phone_settings")!;
    titled.title = "Already explained";
    // The capture ships them disabled: enable both so the disable below is applyAccount's own.
    face.disabled = titled.disabled = false;
    applyAccount(doc, "account/2fa", {});
    const controls = $$<HTMLInputElement | HTMLButtonElement>("#content input, #content button, #content textarea, #content select");
    expect(controls.length).toBeGreaterThan(0);
    for (const c of controls) {
      expect(c.disabled).toBe(true);
      expect(c.title).not.toBe("");
    }
    expect(face.title).toBe(NOT_YET);
    expect(titled.disabled).toBe(true); // processed like the rest...
    expect(titled.title).toBe("Already explained"); // ...but an existing title survives
  });
});

describe("applyAccount: Phone number (settings/account/phone)", () => {
  it("draws OF's connected-phone view with the masked number, verified hint and disabled Delete / Update phone, once", () => {
    const doc = load("account/phone");
    expect(input("connected_phone_number")).toBeNull();
    applyAccount(doc, "account/phone", { settings: { phoneLast4: "0042" } });
    applyAccount(doc, "account/phone", { settings: { phoneLast4: "0042" } });
    expect($$("#connected_phone_number")).toHaveLength(1);
    const field = input("connected_phone_number")!;
    expect(field.value).toBe("******0042");
    expect(field.readOnly).toBe(true);
    expect($(".phone-setting-block [data-oi-hint]")?.textContent).toBe("Phone number ******0042 is verified");
    expect($("label[for='connected_phone_number']")?.textContent).toBe("Connected phone number");
    const buttons = $$<HTMLButtonElement>(".phone-setting-block button");
    expect(buttons.map((b) => b.textContent?.trim())).toEqual(["Delete", "Update phone"]);
    for (const b of buttons) {
      expect(b.disabled).toBe(true);
      expect(b.title).toBe(NOT_YET);
    }
    // The generator's telephone entry is gone.
    expect($("input[name='telephone']")).toBeNull();
  });

  it("without a phone keeps the generator's entry form", () => {
    const doc = load("account/phone");
    applyAccount(doc, "account/phone", { settings: {} });
    expect(input("connected_phone_number")).toBeNull();
    expect($("input[name='telephone']")).not.toBeNull();
  });

  it("only on account/phone: the same page applied as another base keeps its entry form", () => {
    const doc = load("account/phone");
    applyAccount(doc, "account", { settings: { phoneLast4: "0042" } });
    expect(input("connected_phone_number")).toBeNull();
  });
});

describe("applyAccount: Two Step Authentication (settings/account/2fa)", () => {
  const smsHelp = () => input("otp_phone_settings")!.closest(".g-input__wrapper")!.querySelectorAll(".g-input__help");

  it("Verification via SMS help reads 'Phone ******<last 4>', once", () => {
    const doc = load("account/2fa");
    expect(smsHelp()).toHaveLength(0);
    applyAccount(doc, "account/2fa", { settings: { phoneLast4: "7788" } });
    applyAccount(doc, "account/2fa", { settings: { phoneLast4: "7788" } });
    expect(smsHelp()).toHaveLength(1);
    expect(smsHelp()[0].textContent).toBe("Phone ******7788");
    expect(smsHelp()[0].tagName).toBe("P");
  });

  it("no SMS help without a phone, nor on another base", () => {
    let doc = load("account/2fa");
    applyAccount(doc, "account/2fa", { settings: {} });
    expect(smsHelp()).toHaveLength(0);
    doc = load("account/2fa");
    applyAccount(doc, "account", { settings: { phoneLast4: "7788" } });
    expect(smsHelp()).toHaveLength(0);
  });

  it("the passwordless note's 'Email: <b>' is users/me's email", () => {
    const doc = load("account/2fa");
    const b = () => [...document.querySelectorAll("#content .alert-text-wrapper b")].find((x) => /Email:\s*$/.test(x.previousSibling?.textContent ?? ""));
    expect(b()?.textContent).toBe("—");
    applyAccount(doc, "account/2fa", { me: { email: "otp@example.com" } });
    expect(b()?.textContent).toBe("otp@example.com");
  });
});

describe("applyAccount: Email (settings/account/email)", () => {
  const help = () => input("authUser_email")!.closest(".v-input")!.querySelector(".g-input__help")!;
  const hints = () => help().querySelectorAll("[data-oi-hint]");

  it("Current email is users/me's email; verified adds OF's hint, once", () => {
    const doc = load("account/email");
    applyAccount(doc, "account/email", { me: { email: "v@example.com", isEmailChecked: true } });
    applyAccount(doc, "account/email", { me: { email: "v@example.com", isEmailChecked: true } });
    expect(input("authUser_email")!.value).toBe("v@example.com");
    expect(hints()).toHaveLength(1);
    expect(hints()[0].textContent).toBe("E-mail v@example.com is verified");
    // After the help's first node (OF's v-if slot), not first.
    expect(help().firstChild).not.toBe(hints()[0]);
  });

  it.each<[string, unknown]>([
    ["false", false],
    ["missing", undefined],
    ["truthy non-true", 1],
  ])("no hint unless isEmailChecked === true (%s)", (_name, isEmailChecked) => {
    const doc = load("account/email");
    applyAccount(doc, "account/email", { me: { email: "n@example.com", isEmailChecked } });
    expect(input("authUser_email")!.value).toBe("n@example.com");
    expect(hints()).toHaveLength(0);
  });

  it("a later unverified apply takes the verified hint out", () => {
    const doc = load("account/email");
    applyAccount(doc, "account/email", { me: { email: "v@example.com", isEmailChecked: true } });
    applyAccount(doc, "account/email", { me: { email: "v@example.com", isEmailChecked: false } });
    expect(hints()).toHaveLength(0);
  });
});

describe("applyAccount: Login sessions (settings/account/sessions)", () => {
  const lists = () => $$("#content .b-sessions-list");
  const rows = (i: number) => [...lists()[i].querySelectorAll<HTMLElement>("[data-oi-session]")];
  const squash = (s: string | null | undefined) => (s ?? "").replace(/\s+/g, " ").trim();
  // The module draws the browser's local time; the host zone is pinned for this file (see HOST_TZ at the top).
  const T1 = Date.UTC(2026, 9, 9, 13, 4) / 1000;
  const T2 = Date.UTC(2005, 0, 2, 3, 0) / 1000; // a two-digit year with a leading zero
  const SESSIONS = [
    { sessionId: "b", client: "Firefox", os: "Linux", brand: null, ipAddress: "5.6.7.8", countryName: "Croatia", lastActivity: T1 },
    { sessionId: "a", client: "Chrome", os: "macOS", brand: "Apple", ipAddress: "1.2.3.4", countryName: "Slovenia", isCurrent: true, loginMessage: "Logged in" },
    { sessionId: "c", client: "Safari", os: "iOS", brand: "Apple", ipAddress: 99, countryName: "Italy", lastActivity: T2 },
    { sessionId: "d", client: "Edge", os: "Windows", lastActivity: NaN },
    { sessionId: "e", client: "Opera", os: "Android", lastActivity: "1760000000" },
    null,
  ];

  it("current session first in the first list ('Active now', ip • country), above Close all sessions", () => {
    const doc = load("account/sessions");
    applyAccount(doc, "account/sessions", { sessions: SESSIONS });
    const [cur] = rows(0);
    expect(rows(0)).toHaveLength(1);
    expect(lists()[0].firstElementChild).toBe(cur);
    expect(cur.querySelector("strong")?.textContent).toBe("Chrome");
    expect(squash(cur.textContent)).toBe("Chrome, macOS, Apple Active now 1.2.3.4 • Slovenia Logged in");
    const online = cur.querySelector(".session-time")!;
    expect(["session-time", "m-online", "g-blue"].map((c) => online.classList.contains(c))).toEqual([true, true, true]);
    expect(cur.querySelector(".b-session-location")?.textContent).toBe(" 1.2.3.4 • Slovenia ");
    // Close all sessions stays the generator's: disabled, house tooltip.
    const close = lists()[0].querySelector("button")!;
    expect(close.textContent?.trim()).toBe("Close all sessions");
    expect(close.disabled).toBe(true);
    expect(close.title).toBe(NOT_YET);
  });

  it("the others in the second list in order, with OF's M/D/YY h:mm a local time and 'ip - country'", () => {
    const doc = load("account/sessions");
    applyAccount(doc, "account/sessions", { sessions: SESSIONS });
    expect(lists()[1].style.display).toBe("");
    const others = rows(1);
    expect(others.map((r) => r.querySelector("strong")?.textContent)).toEqual(["Firefox", "Safari", "Edge", "Opera"]);
    expect(others.every((r) => r.parentElement?.classList.contains("b-settings__block"))).toBe(true);
    const time = (r: HTMLElement) => r.querySelector(".session-time > span")?.textContent;
    expect(new Date(T1 * 1000).getTimezoneOffset()).toBe(-345); // the pin took effect
    expect(time(others[0])).toBe(" 10/9/26 6:49 pm "); // 13:04 UTC + 05:45
    expect(time(others[1])).toBe(" 1/2/05 8:45 am "); // 03:00 UTC + 05:45
    // Not a valid time / not a number: empty.
    expect(time(others[2])).toBe("  ");
    expect(time(others[3])).toBe("  ");
    expect(others[0].querySelector(".b-session-location")?.textContent).toBe(" 5.6.7.8 - Croatia ");
    expect(others[1].querySelector(".b-session-location")?.textContent).toBe(" 99 - Italy ");
    expect(others[2].querySelector(".b-session-location")?.textContent).toBe("  -  ");
    // Brand only when set.
    expect(squash(others[0].childNodes[1].textContent)).toBe(", Linux");
    expect(squash(others[1].childNodes[1].textContent)).toBe(", iOS, Apple");
  });

  it("idempotent: a second apply redraws the same rows", () => {
    const doc = load("account/sessions");
    applyAccount(doc, "account/sessions", { sessions: SESSIONS });
    applyAccount(doc, "account/sessions", { sessions: SESSIONS });
    expect(rows(0)).toHaveLength(1);
    expect(rows(1)).toHaveLength(4);
  });

  it("no other sessions: the second list is hidden; a later apply with some shows it again", () => {
    const doc = load("account/sessions");
    applyAccount(doc, "account/sessions", { sessions: [SESSIONS[1]] });
    expect(rows(0)).toHaveLength(1);
    expect(rows(1)).toHaveLength(0);
    expect(lists()[1].style.display).toBe("none");
    applyAccount(doc, "account/sessions", { sessions: SESSIONS });
    expect(lists()[1].style.display).toBe("");
    expect(rows(1)).toHaveLength(4);
  });

  it("no current session: nothing prepended to the first list", () => {
    const doc = load("account/sessions");
    applyAccount(doc, "account/sessions", { sessions: [SESSIONS[0]] });
    expect(rows(0)).toHaveLength(0);
    expect(rows(1)).toHaveLength(1);
  });

  it("sessions not an array, or another base: nothing drawn", () => {
    let doc = load("account/sessions");
    applyAccount(doc, "account/sessions", { sessions: { list: SESSIONS } });
    expect($$("[data-oi-session]")).toHaveLength(0);
    doc = load("account/sessions");
    applyAccount(doc, "account", { sessions: SESSIONS });
    expect($$("[data-oi-session]")).toHaveLength(0);
  });
});

// ---------------------------------------------------------------- Security

describe("applySecurity: Fully private profile (settings/security)", () => {
  const row = () => input("setting_isPrivate")?.closest(".g-input__wrapper") ?? null;
  const performer = { isPerformer: true, isAdultContent: false };

  it("a non-adult performer's switch right after Show activity status: value, disabled, tooltip, OF's names, help", () => {
    const doc = load("security");
    applySecurity(doc, "security", { me: performer, settings: { isPrivate: true } });
    const r = row()!;
    expect(r).not.toBeNull();
    expect(r.previousElementSibling).toBe(input("setting_isVisibleOnline")!.closest(".g-input__wrapper"));
    expect(r.querySelector(".g-input__label")?.textContent).toBe("Fully private profile");
    const i = input("setting_isPrivate")!;
    expect(i.name).toBe("isPrivate");
    expect(i.checked).toBe(true);
    expect(i.disabled).toBe(true);
    expect(i.title).toBe(NOT_YET);
    const sw = r.querySelector("label.b-checkbox-switcher")!;
    expect(sw.getAttribute("for")).toBe("setting_isPrivate");
    expect(sw.getAttribute("at-attr")).toBe("isPrivate");
    expect(sw.getAttribute("title")).toBe(NOT_YET);
    expect(r.querySelector("p.g-input__help")?.textContent).toBe("Text will be hidden");
    // The source row is untouched.
    expect(input("setting_isVisibleOnline")!.name).toBe("isVisibleOnline");
    expect(input("setting_isVisibleOnline")!.disabled).toBe(false);
    expect($("label[for='setting_isVisibleOnline'].b-checkbox-switcher")).not.toBeNull();
  });

  it.each<[unknown, boolean]>([
    [true, true],
    [false, false],
    ["true", false],
    [undefined, false],
  ])("isPrivate %j -> checked %j", (isPrivate, checked) => {
    const doc = load("security");
    applySecurity(doc, "security", { me: performer, settings: { isPrivate } });
    expect(input("setting_isPrivate")!.checked).toBe(checked);
  });

  it("idempotent: re-applying replaces the row with the new value", () => {
    const doc = load("security");
    applySecurity(doc, "security", { me: performer, settings: { isPrivate: true } });
    applySecurity(doc, "security", { me: performer, settings: { isPrivate: false } });
    expect($$("#setting_isPrivate")).toHaveLength(1);
    expect(input("setting_isPrivate")!.checked).toBe(false);
    expect($$("p.g-input__help").filter((p) => p.textContent === "Text will be hidden")).toHaveLength(1);
  });

  it.each<[string, object]>([
    ["adult content", { isPerformer: true, isAdultContent: true }],
    ["adult content unknown", { isPerformer: true }],
    ["not a performer", { isPerformer: false, isAdultContent: false }],
  ])("no switch for %s; a drawn one is taken out", (_name, me) => {
    const doc = load("security");
    applySecurity(doc, "security", { me, settings: { isPrivate: true } });
    expect(row()).toBeNull();
    applySecurity(doc, "security", { me: performer, settings: { isPrivate: true } });
    expect(row()).not.toBeNull();
    applySecurity(doc, "security", { me, settings: { isPrivate: true } });
    expect(row()).toBeNull();
  });

  it("me or settings not read yet: nothing drawn, nothing taken out", () => {
    const doc = load("security");
    applySecurity(doc, "security", { me: performer });
    applySecurity(doc, "security", { settings: { isPrivate: true } });
    expect(row()).toBeNull();
    applySecurity(doc, "security", { me: performer, settings: { isPrivate: true } });
    applySecurity(doc, "security", { me: { isPerformer: false }, settings: null });
    expect(row()).not.toBeNull();
  });
});

// ---------------------------------------------------------------- Messaging

describe("applyMessaging: the Tip switch (settings/messaging)", () => {
  const tip = () => input("messageOnlyFromFriends");
  const LABEL = "Don't accept messages without a Tip from free followers whom you don't follow back";

  it("while free: OF's switch in its own list before the Welcome message form, disabled with the value", () => {
    const doc = load("messaging");
    applyMessaging(doc, "messaging", { me: { subscribePrice: 0 }, settings: { canAcceptMessageOnlyFromFriends: true } }, (u) => u);
    const list = tip()!.closest(".b-menu-list")!;
    expect(list.nextElementSibling).toBe(input("autoMessage")!.closest("form"));
    expect(list.querySelector(".g-input__label")?.textContent).toBe(LABEL);
    expect(tip()!.name).toBe("messageOnlyFromFriends");
    expect(tip()!.checked).toBe(true);
    expect(tip()!.disabled).toBe(true);
    expect(tip()!.title).toBe(NOT_YET);
    const sw = list.querySelector("label.b-checkbox-switcher")!;
    expect(sw.getAttribute("for")).toBe("messageOnlyFromFriends");
    expect(sw.getAttribute("at-attr")).toBe("messageOnlyFromFriends");
    // The Welcome message switch it was cloned from is untouched.
    expect(input("autoMessage")!.disabled).toBe(false);
    expect(input("autoMessage")!.closest(".g-input__wrapper")?.querySelector(".g-input__label")?.textContent).toBe("Send a welcome message to new fans");
  });

  it.each<[unknown, boolean]>([
    [0, true],
    [undefined, true],
    ["0", true],
    [null, true],
    [4.99, false],
    ["9.99", false],
  ])("subscribePrice %j -> tip row shown %j", (subscribePrice, shown) => {
    const doc = load("messaging");
    applyMessaging(doc, "messaging", { me: { subscribePrice }, settings: {} }, (u) => u);
    expect(!!tip()).toBe(shown);
  });

  it("idempotent, and going paid takes it out", () => {
    const doc = load("messaging");
    const free = { me: { subscribePrice: 0 }, settings: { canAcceptMessageOnlyFromFriends: false } };
    applyMessaging(doc, "messaging", free, (u) => u);
    applyMessaging(doc, "messaging", free, (u) => u);
    expect($$("#messageOnlyFromFriends")).toHaveLength(1);
    expect(tip()!.checked).toBe(false);
    applyMessaging(doc, "messaging", { me: { subscribePrice: 5 }, settings: {} }, (u) => u);
    expect(tip()).toBeNull();
  });

  it("settings not read: no tip row", () => {
    const doc = load("messaging");
    applyMessaging(doc, "messaging", { me: { subscribePrice: 0 } }, (u) => u);
    expect(tip()).toBeNull();
  });
});

describe("applyMessaging: the welcome message (settings/messaging)", () => {
  const box = () => $("[data-oi-welcome].b-settings__message");
  const msg = () => box()?.querySelector<HTMLElement>(".b-chat__message") ?? null;
  /** The bubble's look: OF's chat message classes on or off. */
  const bubble = () => Object.fromEntries(["m-has-media", "m-photo", "m-text", "m-from-me"].map((c) => [c, msg()!.classList.contains(c)]));
  const proxy = (u: string) => `/api/img?u=${encodeURIComponent(u)}`;
  const PREVIEW = "https://cdn.of/p/preview.jpg?sig=1";
  const VIDEO = "https://cdn.of/v/full.mp4?sig=2";
  const POSTER = "https://cdn.of/v/poster.jpg";
  const VOICE = "https://cdn.of/a/voice.mp3";
  const LOOSE = "https://cdn.of/l/loose.png";
  const MEDIA = [
    { id: 1, type: "photo", files: { preview: { url: PREVIEW }, full: { url: "https://cdn.of/p/full.jpg" } } },
    { id: 2, type: "video", files: { full: { url: VIDEO }, preview: { url: POSTER } } },
    { id: 3, type: "audio", files: { full: { url: VOICE } } },
    { id: 4, type: "photo", url: LOOSE },
  ];
  const welcome = (tpl: object, extra: SettingsData = {}): SettingsData => ({
    me: { subscribePrice: 5 }, settings: { replyOnSubscribe: true }, templates: [{ template: "other", text: "nope" }, { template: "reply_on_subscribe", ...tpl }], ...extra,
  });

  it("maps each medium's still through img onto its <img src>, skips a medium with none, keeps order", () => {
    const doc = load("messaging");
    const img = vi.fn(proxy);
    applyMessaging(doc, "messaging", welcome({ text: "Hi<br>there", media: MEDIA }), img);
    expect(img.mock.calls.map((c) => c[0])).toEqual([PREVIEW, POSTER, LOOSE]);
    const pics = [...box()!.querySelectorAll("img")];
    expect(pics.map((p) => p.getAttribute("src"))).toEqual([proxy(PREVIEW), proxy(POSTER), proxy(LOOSE)]);
    // Never the raw url, never the video or voice file.
    const html = box()!.outerHTML;
    for (const raw of [VIDEO, VOICE]) expect(html).not.toContain(raw);
    for (const p of pics) expect([p.style.display, p.style.width, p.style.height]).toEqual(["block", "100%", "auto"]);
    expect(bubble()).toEqual({ "m-has-media": true, "m-photo": true, "m-text": true, "m-from-me": true });
    expect([...box()!.querySelectorAll(".b-chat__message__text p")].map((p) => p.textContent)).toEqual(["Hi", "there"]);
  });

  it("text only: a text bubble with one <p> per line", () => {
    const doc = load("messaging");
    applyMessaging(doc, "messaging", welcome({ text: "<p>Hello</p><p>fan</p>" }), proxy);
    expect(bubble()).toEqual({ "m-has-media": false, "m-photo": false, "m-text": true, "m-from-me": true });
    expect(box()!.querySelectorAll("img")).toHaveLength(0);
    expect([...box()!.querySelectorAll(".b-chat__message__text p")].map((p) => p.textContent)).toEqual(["Hello", "fan"]);
    expect(box()!.querySelector(".b-chat__message__text-wrapper")?.getAttribute("at-attr")).toBe("message_text");
  });

  it("media only: no text box, no m-text", () => {
    const doc = load("messaging");
    applyMessaging(doc, "messaging", welcome({ text: "", media: [MEDIA[0]] }), proxy);
    expect(bubble()).toEqual({ "m-has-media": true, "m-photo": true, "m-text": false, "m-from-me": true });
    expect(box()!.querySelector(".b-chat__message__text-wrapper")).toBeNull();
    expect(box()!.querySelector("img")?.getAttribute("src")).toBe(proxy(PREVIEW));
  });

  it("only a voice note and no text: an empty text bubble, img never called", () => {
    const doc = load("messaging");
    const img = vi.fn(proxy);
    applyMessaging(doc, "messaging", welcome({ media: [MEDIA[2]] }), img);
    expect(img).not.toHaveBeenCalled();
    expect(bubble()).toEqual({ "m-has-media": false, "m-photo": false, "m-text": true, "m-from-me": true });
    expect([...box()!.querySelectorAll(".b-chat__message__text p")].map((p) => p.textContent)).toEqual([""]);
  });

  it("sits after the Welcome switch, then its disabled Delete and Edit with the elsewhere tooltip", () => {
    const doc = load("messaging");
    applyMessaging(doc, "messaging", welcome({ text: "Hi" }), proxy);
    expect(box()!.previousElementSibling).toBe(input("autoMessage")!.closest(".g-input__wrapper"));
    const row = box()!.nextElementSibling as HTMLElement;
    expect(row.hasAttribute("data-oi-welcome")).toBe(true);
    const buttons = [...row.querySelectorAll("button")];
    expect(buttons.map((b) => b.textContent?.trim())).toEqual(["Delete", "Edit"]);
    expect(buttons[0].classList.contains("m-danger")).toBe(true);
    expect(buttons[1].classList.contains("m-danger")).toBe(false);
    for (const b of buttons) {
      expect(b.disabled).toBe(true);
      expect(b.title).toBe(ELSEWHERE.welcome);
    }
  });

  it.each<[string, unknown, boolean | null]>([
    ["on", true, false],
    ["off", false, true],
    ["truthy non-true is off", 1, true],
  ])("switch %s -> g-disabled %j", (_name, replyOnSubscribe, grayed) => {
    const doc = load("messaging");
    applyMessaging(doc, "messaging", welcome({ text: "Hi" }, { settings: { replyOnSubscribe } }), proxy);
    expect(box()!.classList.contains("g-disabled")).toBe(grayed);
  });

  it("settings not read: neither look (no g-disabled)", () => {
    const doc = load("messaging");
    applyMessaging(doc, "messaging", { me: {}, templates: [{ template: "reply_on_subscribe", text: "Hi" }] }, proxy);
    expect(box()).not.toBeNull();
    expect(box()!.classList.contains("g-disabled")).toBe(false);
  });

  it("idempotent: one welcome box and one button row after two applies", () => {
    const doc = load("messaging");
    applyMessaging(doc, "messaging", welcome({ text: "Hi", media: MEDIA }), proxy);
    applyMessaging(doc, "messaging", welcome({ text: "Hi again" }), proxy);
    expect($$("[data-oi-welcome]")).toHaveLength(2);
    expect($$("[data-oi-welcome].b-settings__message")).toHaveLength(1);
    expect(box()!.querySelectorAll("img")).toHaveLength(0);
    expect(box()!.querySelector(".b-chat__message__text p")?.textContent).toBe("Hi again");
  });

  it.each<[string, SettingsData]>([
    ["the model cannot chat", { me: { canChat: false }, templates: [{ template: "reply_on_subscribe", text: "Hi" }] }],
    ["no reply_on_subscribe template", { me: {}, templates: [{ template: "other", text: "Hi" }] }],
    ["empty template list", { me: {}, templates: [] }],
  ])("none when %s; a drawn one is taken out", (_name, d) => {
    const doc = load("messaging");
    applyMessaging(doc, "messaging", welcome({ text: "Hi" }), proxy);
    expect(box()).not.toBeNull();
    applyMessaging(doc, "messaging", d, proxy);
    expect($$("[data-oi-welcome]")).toHaveLength(0);
  });

  it("templates or me not read: the drawn welcome stays", () => {
    const doc = load("messaging");
    applyMessaging(doc, "messaging", welcome({ text: "Hi" }), proxy);
    applyMessaging(doc, "messaging", { me: {} }, proxy);
    expect(box()).not.toBeNull();
    applyMessaging(doc, "messaging", { templates: [] }, proxy);
    expect(box()).not.toBeNull();
  });
});
