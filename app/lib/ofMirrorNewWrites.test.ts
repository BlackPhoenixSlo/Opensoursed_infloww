import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { switchOn } from "./ofMirrorNewWrites";
import { bindWrites, collectProfilePatch, NOT_YET } from "./ofMirrorWrites";
import { ABOUT_FORMAT } from "./ofMirrorProfileFormat";
import { DIGEST_TOGGLE, frequencySelect } from "./ofMirrorSettingsPages";
import { applyPageExtras } from "./ofMirrorSettings";
import { bindSettingsWrites } from "./ofMirrorSettingsWrites";
import { LISTS } from "./ofMirrorProfileLinks";
import { PROFILE_CAMERA, PROFILE_REMOVE } from "./ofMirrorProfileImages";
import { applySubscription } from "./ofMirrorSubscription";
import { applyBlocked, bindStreamBlock, type BlockedUser } from "./ofMirrorStreamBlocked";
import { bindPost } from "./ofMirrorPost";
import { applyData } from "./ofMirrorData";
import { bindMessageMenu, type MenuMessage } from "./ofMirrorMessageMenu";


const load = (page: string) => {
  document.documentElement.innerHTML = readFileSync(resolve(__dirname, `../public/of-mirror/pages/${page}.html`), "utf8");
  return document;
};
const state = (el: HTMLElement | null | undefined) => [
  el && "disabled" in el ? (el as HTMLButtonElement).disabled : el?.getAttribute("aria-disabled") === "true",
  !!el?.hasAttribute("data-oi-wired"),
  el?.title,
];
const OFF = [true, false, NOT_YET];
const ON = [false, true, NOT_YET];
const LIVE = [false, true, ""];
const button = (text: string) => [...document.querySelectorAll<HTMLButtonElement>("#content button")].find((b) => b.textContent?.trim() === text);
const noop = { send: () => Promise.resolve({ success: true }), confirm: () => true, standIn: false };

let unbinds: (() => void)[] = [];
afterEach(() => {
  for (const u of unbinds) u();
  unbinds = [];
});

function bindSettings(page: string, newWrites: boolean, read: object = {}, handlers: typeof noop = noop) {
  const doc = load(`settings/${page}`);
  if (page === "notifications/email") (doc.getElementById(DIGEST_TOGGLE) as HTMLInputElement).checked = true;
  applyPageExtras(doc, page, read as never, newWrites);
  unbinds.push(bindWrites(doc, `settings/${page}`, null, newWrites));
  unbinds.push(bindSettingsWrites(doc, `settings/${page}`, () => read as never, undefined, handlers, newWrites));
  return doc;
}
const rebind = () => {
  for (const u of unbinds) u();
  unbinds = [];
};

describe("switchOn (the probe of OFM_NEW_WRITES_ENABLED, field `on`)", () => {
  it.each([
    [{ on: true }, true],
    [{ on: false }, false],
    [{}, false],
    [null, false],
  ])("%j -> %s", async (reply, want) => expect(await switchOn(() => Promise.resolve(reply as never), "on")).toBe(want));
  it("the switch's 404 (or any failure) is off", async () => expect(await switchOn(() => Promise.reject(new Error("404")), "on")).toBe(false));
});

describe("settings controls follow the switch", () => {
  it.each([
    ["account/sessions", () => button("Close all sessions"), ON],
    ["streaming", () => button("Reset"), ON],
    ["social-media", () => document.querySelector<HTMLButtonElement>(LISTS["social-media"].add), LIVE],
    ["links", () => document.querySelector<HTMLButtonElement>(LISTS.links.add), LIVE],
  ])("%s: off as captured, on Wired", (page, el, on) => {
    bindSettings(page, false);
    expect(state(el()), "off").toEqual(OFF);
    rebind();
    bindSettings(page, true);
    expect(state(el()), "on").toEqual(on);
  });

  const MESSAGING = { me: { subscribePrice: 0 }, settings: { canAcceptMessageOnlyFromFriends: false } };
  const SECURITY = { me: { isPerformer: true, isAdultContent: false }, settings: { isPrivate: false } };
  it.each([
    ["messaging", MESSAGING, "messageOnlyFromFriends"],
    ["security", SECURITY, "setting_isPrivate"],
  ])("%s: the drawn switch %s is Not yet off (a change sends nothing), on Wired", (page, read, id) => {
    const send = vi.fn(() => Promise.resolve({ success: true }));
    const el = () => document.getElementById(id as string) as HTMLInputElement;
    bindSettings(page as string, false, read, { send, confirm: () => true, standIn: false });
    expect(state(el()), "off").toEqual(OFF);
    el().checked = true;
    el().dispatchEvent(new Event("change", { bubbles: true }));
    expect(send).not.toHaveBeenCalled();
    expect(el().checked, "put back").toBe(false);
    rebind();
    bindSettings(page as string, true, read);
    expect(state(el()), "on").toEqual(ON);
  });

  it("notifications/email: Update frequency is Not yet off (select and field titled), on Wired with both titles dropped (D1)", () => {
    const read = { "notifications:email": [{ items: [{ code: "new_likes_digest", value: 12 }] }] };
    const field = () => frequencySelect(document)!.querySelector<HTMLInputElement>("input:not([type='hidden'])");
    bindSettings("notifications/email", false, read);
    expect(state(field()), "off").toEqual(OFF);
    expect([frequencySelect(document)!.hasAttribute("data-oi-wired"), frequencySelect(document)!.title], "off").toEqual([false, NOT_YET]);
    rebind();
    bindSettings("notifications/email", true, read);
    expect(state(field()), "on").toEqual(LIVE);
    expect(frequencySelect(document)!.hasAttribute("title"), "on").toBe(false);
  });

  it.each([
    ["security/block_by_country", () => document.getElementById("input-298")],
    ["security/block_by_ip", () => document.getElementById("input-blocked-ips")],
  ])("%s: off its field stays Not yet (disabled, not Wired, titled); on Wired, title dropped (Live pass, D1)", (page, el) => {
    bindSettings(page, false);
    expect(state(el()), "off").toEqual(OFF);
    rebind();
    bindSettings(page, true);
    expect(state(el()).slice(1), "on").toEqual([true, ""]);
  });

  it("security/block_by_country: the picker's box is titled off, untitled on (one control with its field)", () => {
    const box = () => document.querySelector<HTMLElement>("#content .g-select__wrapper .v-input");
    bindSettings("security/block_by_country", false);
    expect(box()!.title, "off").toBe(NOT_YET);
    rebind();
    bindSettings("security/block_by_country", true);
    expect(box()!.hasAttribute("title"), "on").toBe(false);
  });

  it.each([
    ["social-media", { socialButtons: [{ id: 1, socialMedia: "instagram", label: "My Insta", link: "https://instagram.com/a", username: "a" }] }],
    ["links", { thingsLinks: [{ id: 1, link: "https://www.youtube.com/watch?v=x" }] }],
  ])("%s: off, each drawn row's remove is Not yet; on Wired", (page, read) => {
    const removes = () => [...document.querySelectorAll<HTMLButtonElement>("[data-oi-link-remove]")].map(state);
    bindSettings(page, false, read);
    expect(removes(), "off").toEqual([OFF]);
    rebind();
    bindSettings(page, true, read);
    expect(removes().map((s) => s[1]), "on").toEqual([true]);
  });
});

describe("the switch flips off while a page is open", () => {
  const reapplyOff = (doc: Document, page: string, read: object) => {
    rebind();
    applyPageExtras(doc, page, read as never, false);
    unbinds.push(bindWrites(doc, `settings/${page}`, null, false));
    unbinds.push(bindSettingsWrites(doc, `settings/${page}`, () => read as never, undefined, noop, false));
  };
  const freqField = () => frequencySelect(document)!.querySelector<HTMLInputElement>("input:not([type='hidden'])");
  it.each([
    ["account/sessions", () => button("Close all sessions"), {}],
    ["streaming", () => button("Reset"), {}],
    ["social-media", () => document.querySelector<HTMLButtonElement>(LISTS["social-media"].add), {}],
    ["links", () => document.querySelector<HTMLButtonElement>(LISTS.links.add), {}],
    ["security/block_by_country", () => document.getElementById("input-298"), {}],
    ["security/block_by_ip", () => document.getElementById("input-blocked-ips"), {}],
    ["notifications/email", freqField, { "notifications:email": [{ items: [{ code: "new_likes_digest", value: 12 }] }] }],
  ])("%s: drawn Wired, then Not yet (disabled, not Wired, titled)", (page, el, read) => {
    const doc = bindSettings(page, true, read);
    expect(state(el())[1], "on").toBe(true);
    reapplyOff(doc, page, read);
    expect(state(el()), "off").toEqual(OFF);
  });

  it.each([
    ["home/index", OFF],
    ["new-post/index", [false, true, ""]],
  ])("%s: Record video and Record voice drawn Wired, then as main %j", (page, off) => {
    const d = load(page);
    const ctx = { handlers: null, storage: null, accountId: null, draftId: page.startsWith("home/") ? "home:1" : undefined };
    const records = () => ["Record video", "Record voice"].map((l) => state(d.querySelector<HTMLButtonElement>(`button[aria-label='${l}']`)));
    unbinds.push(bindPost(d, page, { ...ctx, newWrites: true }));
    expect(records(), "on").toEqual([LIVE, LIVE]);
    rebind();
    unbinds.push(bindPost(d, page, { ...ctx, newWrites: false }));
    expect(records(), "off").toEqual([off, off]);
  });

  it("messages/chat: an own PPV's extras (Countdown, Copy as draft, Unsend PPV) drawn Wired, then none drawn (main)", () => {
    const d = load("messages/chat");
    const ppv = { id: 501, text: "<p>ppv</p>", createdAt: "2026-10-10T12:01:00Z", fromUser: { id: 1 }, price: 5, media: [], cancelSeconds: 90 } as unknown as MenuMessage;
    applyData(d, "messages/chat", { chat: "2006", thread: { fan: { id: 2006, name: "Fan", username: "fan" }, messages: [ppv] } });
    const menu = (newWrites: boolean) =>
      bindMessageMenu(d, { chat: "2006", message: (id) => (id === "501" ? ppv : undefined), left: () => 90, limited: false, writes: null, storage: null, accountId: null, copy: () => Promise.resolve(), newWrites });
    const extras = () => [...d.querySelectorAll<HTMLElement>("[data-oi-msg='501'] [data-oi-bubble]")].map((e) => [e.dataset.oiBubble, e.hasAttribute("data-oi-wired")]);
    unbinds.push(menu(true));
    expect(extras(), "on").toEqual([["countdown", true], ["copy-draft", true], ["unsend-ppv", true]]);
    rebind();
    unbinds.push(menu(false));
    expect([extras(), d.querySelector("[data-oi-bubble-extras]")], "off").toEqual([[], null]);
  });

  it("Blocked users: Block's field and button back to Not yet on unbind", () => {
    const d = load("settings/streaming/blocked");
    const unbind = bindStreamBlock(d, { block: () => Promise.resolve(), unblock: () => Promise.resolve() });
    const els = () => [d.querySelector<HTMLElement>("input[name='block-user-by-name']"), d.querySelector<HTMLElement>("#content .b-settings__content form button[type='submit']")];
    expect(els().map((e) => state(e)[1]), "on").toEqual([true, true]);
    unbind();
    expect(els().map(state), "off").toEqual([OFF, OFF]);
  });
});

describe("Edit profile's cover and avatar follow the switch", () => {
  beforeEach(() => {
    URL.createObjectURL = vi.fn(() => "blob:picked");
    URL.revokeObjectURL = vi.fn();
  });
  const handlers = () => ({
    saveProfile: vi.fn(() => Promise.resolve()),
    uploadProfileImage: vi.fn(() => Promise.resolve({ processId: "p1" })),
    setReplyOnSubscribe: vi.fn(() => Promise.resolve()),
    submit: vi.fn(() => Promise.resolve({})),
    navigate: vi.fn(),
  });
  const sels = [PROFILE_CAMERA.header, PROFILE_CAMERA.avatar, PROFILE_REMOVE.header];

  it.each([
    [false, [OFF, OFF, OFF]],
    [true, [LIVE, ON, ON]],
  ])("newWrites %s: cover camera, avatar camera, cover's remove %j", (newWrites, want) => {
    const d = load("settings/profile");
    unbinds.push(bindWrites(d, "settings/profile", handlers() as never, newWrites));
    expect(sels.map((sel) => state(d.querySelector<HTMLButtonElement>(sel)))).toEqual(want);
    expect(!!d.querySelector("input[data-oi-profile-file]")).toBe(newWrites);
  });

  it.each([
    [false, OFF],
    [true, LIVE],
  ])("newWrites %s: the Bio's format button %j", (newWrites, want) => {
    const d = load("settings/profile");
    unbinds.push(bindWrites(d, "settings/profile", handlers() as never, newWrites));
    expect(state(d.querySelector<HTMLButtonElement>(ABOUT_FORMAT))).toEqual(want);
    expect(!!d.querySelector("[data-oi-about-format]")).toBe(newWrites);
  });

  it.each([
    [false, "Hi there"],
    [true, "<p><strong>Hi</strong> there</p>"],
  ])("newWrites %s: a formatted Bio saves as %j", (newWrites, want) => {
    const d = load("settings/profile");
    d.querySelector("[data-placeholder='Bio']")!.innerHTML = "<p><strong>Hi</strong> there</p>";
    expect(collectProfilePatch(d, newWrites, ["about"]).about).toBe(want);
  });
});

describe("a tracking link's Share hint follows the switch", () => {
  const TRACKING = "settings/subscription/tracking-links";
  const ME = { id: 7, username: "synthmodel", name: "Synth Model", avatar: null, subscribePrice: 10, canCreateTrial: true };
  const ROW = { id: 31, campaignCode: 5, campaignName: "Synthetic link", countSubscribers: 2, countTransitions: 9, createdAt: "2026-04-16T00:00:00+00:00", isDeleted: false };

  it.each([
    [false, OFF],
    [true, ON],
  ])("canShare %s: hint %j", (canShare, want) => {
    const d = load(TRACKING);
    applySubscription(d, TRACKING, { campaigns: { rows: [ROW] } }, ME as never, canShare);
    const hint = d.querySelector<HTMLElement>("[data-oi-row] .b-hint-offer")!;
    expect(state(hint)).toEqual(want);
    expect(hint.hasAttribute("data-oi-share")).toBe(canShare);
  });
});

describe("Blocked users' remove follows the switch", () => {
  const USER = { id: 700001, name: "Fan", username: "fan1", avatar: null, isVerified: false } as unknown as BlockedUser;
  it("not writable: the remove stays disabled with its Not-yet title", () => {
    const d = load("settings/streaming/blocked");
    applyBlocked(d, [USER], undefined, false);
    const remove = d.querySelector<HTMLButtonElement>("[data-oi-blocked-list] button.m-btn-remove");
    expect(state(remove)).toEqual(OFF);
  });
});
