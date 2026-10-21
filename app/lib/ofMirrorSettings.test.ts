import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { OF_MIRROR_SECTIONS } from "./of-mirror-pages";
import { applyPageExtras, applySettings, SETTINGS_MAP } from "./ofMirrorSettings";
import { ELSEWHERE } from "./ofMirrorTooltip";

const doc = (html: string) => {
  document.body.innerHTML = html;
  return document;
};
const input = (d: Document, id: string) => d.getElementById(id) as HTMLInputElement;

describe("applySettings", () => {
  it("sets checkboxes from /users/me/settings and leaves unmapped or missing ones alone", () => {
    const d = doc(`
      <input id="setting_isAutoFollowBack" type="checkbox">
      <input id="setting_unfollowAutoFollowBack" type="checkbox" checked>
      <input id="setting_recommenderReward" type="checkbox" checked>
      <input id="setting_sendAwardsTop1" type="checkbox">
      <input id="setting_sendAwardsTop5" type="checkbox" checked>
      <input id="dark_mode_switcher" type="checkbox" checked>`);
    applySettings(d, "fans", {
      settings: { isAutoFollowBack: true, unfollowAutoFollowBack: false, recommenderReward: null, sendAwardsTop1: true, streamingRtmpKey: "k" },
    });
    expect(input(d, "setting_isAutoFollowBack").checked).toBe(true);
    expect(input(d, "setting_unfollowAutoFollowBack").checked).toBe(false);
    expect(input(d, "setting_recommenderReward").checked).toBe(false);
    expect(input(d, "setting_sendAwardsTop1").checked).toBe(true);
    expect(input(d, "setting_sendAwardsTop5").checked).toBe(true); // field absent
    expect(input(d, "dark_mode_switcher").checked).toBe(true); // unmapped
  });

  it("sets /users/me checkboxes, text inputs, the watermark help line and the position select", () => {
    const d = doc(`
      <input id="hasWatermarkPhoto" type="checkbox">
      <input id="hasWatermarkVideo" type="checkbox" checked>
      <div class="v-input"><input id="input-watermark-text" type="text"><p class="g-input__help"> Current: yourmodel </p></div>
      <div class="v-select"><div class="v-select__selection">Bottom right</div><input type="hidden" name="watermark_position" value="bottom_right"></div>`);
    applySettings(d, "security/watermarks", {
      me: { hasWatermarkPhoto: true, hasWatermarkVideo: false, watermarkText: "OnlyFans.com/live", watermarkPosition: "top_left" },
    });
    expect(input(d, "hasWatermarkPhoto").checked).toBe(true);
    expect(input(d, "hasWatermarkVideo").checked).toBe(false);
    expect(d.querySelector(".g-input__help")!.textContent).toBe(" Current: OnlyFans.com/live ");
    expect(input(d, "input-watermark-text").value).toBe("");
    expect(d.querySelector<HTMLInputElement>("[name=watermark_position]")!.value).toBe("top_left");
    expect(d.querySelector(".v-select__selection")!.textContent).toBe("Top left");

    // The open position list marks the model's position; the generated page keeps none of the capture's (nor its text).
    document.documentElement.innerHTML = readFileSync(resolve(__dirname, "../public/of-mirror/pages/settings/security/watermarks/state-options.html"), "utf8");
    const marked = () =>
      [...document.querySelectorAll("[role=listbox] .v-list-item")]
        .filter((i) => i.classList.contains("v-list-item--active") || i.getAttribute("aria-selected") === "true")
        .map((i) => [i.textContent?.trim(), i.className.includes("primary--text"), i.getAttribute("aria-selected")]);
    expect(marked()).toEqual([]);
    expect(document.querySelector(".v-select__selection")!.textContent).toBe("");
    expect(document.querySelector<HTMLInputElement>("[name=watermark_position]")!.value).toBe("");
    applySettings(document, "security/watermarks/state-options", { me: { watermarkPosition: "middle_left" } });
    expect(marked()).toEqual([["Middle left", true, "true"]]);
    expect(document.querySelector(".v-select__selection")!.textContent).toBe("Middle left");

    const p = doc(`
      <div class="v-input"><fieldset><legend style="width: 0px;"></legend></fieldset><label class="v-label">Website URL</label><div class="g-input__wrapper"><input id="input-website" type="text"><div class="v-counter">0 / 100</div></div></div>
      <div class="v-input v-input--is-label-active v-input--is-dirty"><label class="v-label v-label--active">Location</label><input id="input-location" type="text" value="x"></div>`);
    applySettings(p, "profile", { me: { website: "https://example.com", location: "" } });
    expect(input(p, "input-website").value).toBe("https://example.com");
    expect(p.querySelector(".v-counter")!.textContent).toBe("19 / 100");
    // The floating label moves up for a filled field and back down for an empty one.
    expect(input(p, "input-website").closest(".v-input")!.className).toBe("v-input v-input--is-label-active v-input--is-dirty");
    expect(p.querySelector("#input-website")!.closest(".v-input")!.querySelector(".v-label")!.className).toBe("v-label v-label--active");
    expect(p.querySelector("legend")!.style.width).toBe("6px"); // jsdom: no layout, so the label measures 0
    expect(input(p, "input-location").closest(".v-input")!.className).toBe("v-input");
    expect(input(p, "input-location").closest(".v-input")!.querySelector(".v-label")!.className).toBe("v-label");
  });

  it("reads per-transport notification toggles by code", () => {
    const d = doc(`
      <input id="toggle_new_tips" type="checkbox">
      <input id="toggle_new_comment" type="checkbox" checked>
      <input id="toggle_new_stream" type="checkbox" checked>`);
    applySettings(d, "notifications/toast", {
      "notifications:toast": [
        { code: "a", items: [{ code: "new_tips", isEnabled: true }] },
        { code: "b", items: [{ code: "new_comment", isEnabled: false }] },
      ],
    });
    expect(input(d, "toggle_new_tips").checked).toBe(true);
    expect(input(d, "toggle_new_comment").checked).toBe(false);
    expect(input(d, "toggle_new_stream").checked).toBe(true); // code absent
  });

  it("checks the matching radio and maps story replies", () => {
    const d = doc(`
      <input id="allowSubscribers" name="allow_costreaming" type="radio" value="subscribers" checked>
      <input id="allowFriends" name="allow_costreaming" type="radio" value="friends">
      <input id="allowNobody" name="allow_costreaming" type="radio" value="nobody">`);
    applySettings(d, "streaming", { settings: { coStreamingRequestFrom: "friends" } });
    expect(["allowSubscribers", "allowFriends", "allowNobody"].map((id) => input(d, id).checked)).toEqual([false, true, false]);

    const s = doc(`<input id="show_subscribes_offers" type="checkbox">`);
    applySettings(s, "story", { story: { allowReplyFrom: "subscribers" } });
    expect(input(s, "show_subscribes_offers").checked).toBe(true);
    applySettings(s, "story", { story: { allowReplyFrom: "nobody" } });
    expect(input(s, "show_subscribes_offers").checked).toBe(false);
  });
});

describe("Security's Fully private profile (OF: a performer's, unless isAdultContent)", () => {
  const page = () =>
    doc(readFileSync(resolve(__dirname, "../public/of-mirror/pages/settings/security.html"), "utf8").replace(/^[\s\S]*?<body[^>]*>/, ""));
  const labels = (d: Document) => [...d.querySelectorAll("#content .g-input__label")].slice(0, 3).map((l) => l.textContent?.trim());

  it("shows the switch after Show activity status with its help, the model's value, disabled", () => {
    const d = page();
    for (let i = 0; i < 2; i++) applyPageExtras(d, "security", { me: { isPerformer: true, isAdultContent: false }, settings: { isPrivate: true } });
    expect(labels(d)).toEqual(["Show activity status", "Fully private profile", "Show fans count on your profile"]);
    const sw = input(d, "setting_isPrivate");
    expect([sw.name, sw.checked, sw.disabled, sw.title]).toEqual(["isPrivate", true, true, "Not available in Inflowwww yet"]);
    expect(sw.closest(".g-input__wrapper")!.querySelector(".g-input__help")!.textContent).toBe("Text will be hidden");
    expect(d.querySelectorAll("#setting_isPrivate")).toHaveLength(1);
  });

  it("none for an adult-content page (OF's v-if)", () => {
    const d = page();
    applyPageExtras(d, "security", { me: { isPerformer: true, isAdultContent: true }, settings: { isPrivate: false } });
    expect(d.getElementById("setting_isPrivate")).toBeNull();
    expect(labels(d)[1]).toBe("Show fans count on your profile");
  });

  it("no switch drawn while users/me/settings loads or after it failed (never a made-up off)", () => {
    for (const settings of [undefined, null]) {
      const d = page();
      applyPageExtras(d, "security", { me: { isPerformer: true, isAdultContent: false }, settings });
      expect(d.getElementById("setting_isPrivate")).toBeNull();
      expect(labels(d)[1]).toBe("Show fans count on your profile");
    }
  });
});

describe("Messaging (OF's settings-messaging.js)", () => {
  const page = () =>
    doc(readFileSync(resolve(__dirname, "../public/of-mirror/pages/settings/messaging.html"), "utf8").replace(/^[\s\S]*?<body[^>]*>/, ""));
  const welcome = { id: "1", template: "reply_on_subscribe", text: "<p>Synthetic hello</p><p>Second line</p>" };

  it("free: the Tip switch before Welcome message, the model's value, disabled; the welcome template with Delete and Edit disabled, pointing at Delayed welcome", () => {
    const d = page();
    for (let i = 0; i < 2; i++)
      applyPageExtras(d, "messaging", {
        me: { subscribePrice: 0, canChat: true },
        settings: { canAcceptMessageOnlyFromFriends: true, replyOnSubscribe: false },
        templates: [{ id: "2", template: null, text: "other" }, welcome],
      });
    const tip = input(d, "messageOnlyFromFriends");
    expect(tip.closest(".g-input__wrapper")!.querySelector(".g-input__label")!.textContent).toBe(
      "Don't accept messages without a Tip from free followers whom you don't follow back",
    );
    expect([tip.checked, tip.disabled, tip.title]).toEqual([true, true, "Not available in Inflowwww yet"]);
    expect(tip.closest(".b-menu-list")!.nextElementSibling!.tagName).toBe("FORM");
    expect(d.querySelectorAll("#messageOnlyFromFriends")).toHaveLength(1);
    const box = d.querySelectorAll(".b-settings__message");
    expect(box).toHaveLength(1);
    expect([...box[0].querySelectorAll("p")].map((p) => p.textContent)).toEqual(["Synthetic hello", "Second line"]);
    expect(box[0].classList.contains("g-disabled")).toBe(true);
    const buttons = [...box[0].nextElementSibling!.querySelectorAll("button")].map((b) => [b.textContent!.trim(), b.disabled, b.title]);
    expect(buttons).toEqual([
      ["Delete", true, ELSEWHERE.welcome],
      ["Edit", true, ELSEWHERE.welcome],
    ]);
  });

  it("the welcome message's media: each still above the text, read-only, through the image proxy; a voice note none", () => {
    const d = page();
    const media = [
      { id: 1, type: "photo", files: { preview: { url: "https://cdn.example.invalid/p1.jpg" }, thumb: { url: "https://cdn.example.invalid/t1.jpg" } } },
      { id: 2, type: "video", files: { full: { url: "https://cdn.example.invalid/v2.mp4" }, preview: { url: "https://cdn.example.invalid/v2.jpg" } } },
      { id: 3, type: "audio", files: { full: { url: "https://cdn.example.invalid/a3.mp3" } } },
    ];
    const run = (text: string) =>
      applyPageExtras(
        d,
        "messaging",
        { me: { subscribePrice: 5, canChat: true }, settings: { replyOnSubscribe: true }, templates: [{ id: "1", template: "reply_on_subscribe", text, media }] },
        (u) => `/img?u=${encodeURIComponent(u)}`,
      );
    run("<p>Synthetic hello</p>");
    run("<p>Synthetic hello</p>");
    const msg = d.querySelector(".b-settings__message .b-chat__message")!;
    expect(msg.className).toBe("b-chat__message m-has-media m-photo m-text m-from-me");
    const body = msg.querySelector(".b-chat__message__body")!;
    expect([...body.children].map((c) => c.className)).toEqual([
      "b-chat__message__media-wrapper",
      "b-chat__message__media-wrapper",
      "b-chat__message__text-wrapper",
    ]);
    expect([...body.querySelectorAll("img")].map((i) => i.getAttribute("src"))).toEqual([
      `/img?u=${encodeURIComponent("https://cdn.example.invalid/p1.jpg")}`,
      `/img?u=${encodeURIComponent("https://cdn.example.invalid/v2.jpg")}`,
    ]);
    // Media only: no text bubble, as OF's (no m-text).
    run("");
    expect(d.querySelector(".b-settings__message .b-chat__message")!.className).toBe("b-chat__message m-has-media m-photo m-from-me");
    expect(d.querySelector(".b-settings__message .b-chat__message__text-wrapper")).toBeNull();
  });

  it("the welcome text keeps a paragraph's line breaks (<br>, nl2br's \"<br />\\n\" once), as bioOf", () => {
    const d = page();
    const text = "<p>Synthetic hello<br />\nSecond line</p><p>Third</p>";
    applyPageExtras(d, "messaging", { me: { subscribePrice: 5, canChat: true }, settings: {}, templates: [{ ...welcome, text }] });
    expect([...d.querySelectorAll(".b-settings__message p")].map((p) => p.textContent)).toEqual(["Synthetic hello", "Second line", "Third"]);
  });

  it("settings not read (loading or failed): no Tip switch, and the welcome neither grayed nor claimed on", () => {
    const d = page();
    applyPageExtras(d, "messaging", { me: { subscribePrice: 0, canChat: true }, templates: [welcome] });
    expect(d.getElementById("messageOnlyFromFriends")).toBeNull();
    const box = d.querySelector(".b-settings__message")!;
    expect(box.classList.contains("g-disabled")).toBe(false);
    // Once read, both show: off grays the welcome.
    applyPageExtras(d, "messaging", { me: { subscribePrice: 0, canChat: true }, settings: { replyOnSubscribe: false }, templates: [welcome] });
    expect(d.getElementById("messageOnlyFromFriends")).not.toBeNull();
    expect(d.querySelector(".b-settings__message")!.classList.contains("g-disabled")).toBe(true);
  });

  it("priced: no Tip switch; no welcome template: nothing under the switch", () => {
    const d = page();
    applyPageExtras(d, "messaging", { me: { subscribePrice: 5, canChat: true }, settings: {}, templates: [] });
    expect(d.getElementById("messageOnlyFromFriends")).toBeNull();
    expect(d.querySelector(".b-settings__message")).toBeNull();
  });
});

describe("SETTINGS_MAP", () => {
  it("names only mirrored pages and controls that exist in them", () => {
    const pages = OF_MIRROR_SECTIONS.settings.pages;
    for (const [page, entries] of Object.entries(SETTINGS_MAP)) {
      expect(Object.hasOwn(pages, page), page).toBe(true);
      const html = readFileSync(resolve(__dirname, `../public/of-mirror/pages/settings/${page}.html`), "utf8");
      for (const key of Object.keys(entries)) {
        expect(html.includes(`id="${key}"`) || html.includes(`name="${key}"`), `${page}: ${key}`).toBe(true);
      }
    }
  });
});

describe("the disabled sort menus (state-kebab)", () => {
  it("show OF's default sort checked: Created, Descending", () => {
    for (const page of ["tracking-links", "trial-links"]) {
      document.documentElement.innerHTML = readFileSync(resolve(__dirname, `../public/of-mirror/pages/settings/subscription/${page}/state-kebab.html`), "utf8");
      const checked = [...document.querySelectorAll<HTMLInputElement>(".m-radio-dropdown-item input[type=radio]")].filter((r) => r.checked);
      expect(checked.map((r) => [r.labels?.[0]?.textContent?.trim() ?? r.closest(".m-radio-dropdown-item")?.textContent?.trim(), r.disabled]), page).toEqual([
        ["Created", true],
        ["Descending", true],
      ]);
    }
  });
});

describe("Edit profile's header and avatar icons", () => {
  it("stay disabled with the tooltip but are not dimmed (OF shows them at full opacity)", () => {
    document.documentElement.innerHTML = readFileSync(resolve(__dirname, "../public/of-mirror/pages/settings/profile.html"), "utf8");
    const icons = [...document.querySelectorAll<HTMLButtonElement>(".b-profile__header button.m-light, .b-profile__user button.m-light")];
    expect(icons.length).toBeGreaterThanOrEqual(3);
    for (const b of icons) expect([b.disabled, b.title, b.style.opacity]).toEqual([true, "Not available in Inflowwww yet", "1"]);
  });
});

describe("Account > Login sessions (OF's settings-sessions.js, read-only)", () => {
  const page = () => {
    document.documentElement.innerHTML = readFileSync(resolve(__dirname, "../public/of-mirror/pages/settings/account/sessions.html"), "utf8");
    return document;
  };
  // Made-up sessions (documentation IPs, no real device or place).
  const at = new Date(2026, 9, 9, 15, 4).getTime() / 1000;
  const SESSIONS = [
    { sessionId: "s2", client: "Firefox 1.0", os: "Linux 1", brand: "", ipAddress: "203.0.113.2", countryName: "Synthetic Land", lastActivity: at, isCurrent: false },
    { sessionId: "s1", client: "Chrome 1.0", os: "Mac OS 1", brand: "Apple", ipAddress: "203.0.113.1", countryName: "Synthetic Land", lastActivity: at, isCurrent: true },
    { sessionId: "s3", client: "Safari 1.0", os: "iOS 1", brand: "Apple", ipAddress: "203.0.113.3", countryName: null, loginMessage: "Synthetic note", lastActivity: at - 12 * 3600, isCurrent: false },
  ];
  const rows = (d: Document) => [...d.querySelectorAll(".b-sessions-list .m-session-row")].map((r) => r.textContent!.replace(/\s+/g, " ").trim());

  it("the current session above Close all sessions, the others in their own list, as OF draws them", () => {
    const d = page();
    expect(rows(d)).toEqual([]);
    expect(d.querySelector("[data-oi-empty]")).toBeNull(); // no invented copy
    for (let i = 0; i < 2; i++) applyPageExtras(d, "account/sessions", { sessions: SESSIONS });
    expect(rows(d)).toEqual([
      "Chrome 1.0, Mac OS 1, Apple Active now 203.0.113.1 • Synthetic Land",
      "Firefox 1.0, Linux 1 10/9/26 3:04 pm 203.0.113.2 - Synthetic Land",
      "Safari 1.0, iOS 1, Apple 10/9/26 3:04 am 203.0.113.3 - Synthetic note",
    ]);
    const [first, second] = d.querySelectorAll<HTMLElement>(".b-sessions-list");
    expect(first.firstElementChild!.querySelector(".session-time")!.className).toBe("session-time m-online g-blue");
    expect(first.firstElementChild!.nextElementSibling!.textContent!.trim()).toBe("Close all sessions");
    expect(second.querySelectorAll(".m-session-row")).toHaveLength(2);
    expect(second.style.display).toBe("");
  });

  it("every control stays disabled with the tooltip; no other sessions: no second list", () => {
    const d = page();
    applyPageExtras(d, "account/sessions", { sessions: [SESSIONS[1]] });
    expect(rows(d)).toHaveLength(1);
    expect(d.querySelectorAll<HTMLElement>(".b-sessions-list")[1].style.display).toBe("none");
    const buttons = [...d.querySelectorAll<HTMLButtonElement>("#content button")];
    expect(buttons.length).toBeGreaterThan(0);
    for (const b of buttons) expect([b.disabled, b.title]).toEqual([true, "Not available in Inflowwww yet"]);
  });
});
