import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { bindWrites, NOT_YET, SAVED_TOAST, SELECT_MODEL } from "./ofMirrorWrites";
import { applyPageExtras, SOURCE_PATHS, sourcesFor } from "./ofMirrorSettings";
import { bindSettingsWrites, type SettingsWrite } from "./ofMirrorSettingsWrites";
import {
  canSave,
  drawLinks,
  likedLinkBody,
  LINK_BODY_INFERRED,
  LINK_BODY_MEASURED,
  LISTS,
  normalLink,
  ofUrl,
  providersOf,
  socialButtonBody,
  type SocialProvider,
} from "./ofMirrorProfileLinks";

const SOCIAL = LISTS["social-media"];
const load = (page: string) => {
  document.documentElement.innerHTML = readFileSync(resolve(__dirname, `../public/of-mirror/pages/settings/${page}.html`), "utf8");
  return document;
};
const noteText = () => document.getElementById("oi-note")?.textContent ?? null;
const noteColor = () => document.getElementById("oi-note")?.style.color ?? null;
const toastText = () => document.querySelector("#oi-toast .toast__text")?.textContent ?? null;
const flush = () => new Promise((r) => setTimeout(r, 0));
const add = () => document.querySelector<HTMLButtonElement>(SOCIAL.add)!;
const labels = () => [...document.querySelectorAll("[data-oi-link-row] .g-semibold")].map((e) => e.textContent);
const saveBtn = () => document.querySelector<HTMLButtonElement>("[data-oi-link-save]");
const type = (id: string, text: string) => {
  const el = document.getElementById(id) as HTMLInputElement;
  el.value = text;
  el.dispatchEvent(new Event("input", { bubbles: true }));
};
const IG: SocialProvider = { socialMedia: "instagram", label: "Instagram", isLink: false, isShowAt: false };
const TT: SocialProvider = { socialMedia: "tiktok", label: "Tiktok", isLink: false, isShowAt: true };
const AMZ: SocialProvider = { socialMedia: "amazon", label: "Amazon", isLink: true, isShowAt: false };
const INIT = { socialMediaProviders: [IG, TT, AMZ] };
const pickProvider = (value: string) => {
  const el = document.getElementById("oi-link-provider") as HTMLSelectElement;
  el.value = value;
  el.dispatchEvent(new Event("input", { bubbles: true }));
};
const B1 = { id: 1, socialMedia: "instagram", label: "My Insta", link: "https://instagram.com/a", username: "a" };
const B2 = { id: 2, socialMedia: "tiktok", label: "My TikTok", link: "https://tiktok.com/@b", username: "b" };

let unbinds: (() => void)[] = [];
afterEach(() => {
  for (const u of unbinds) u();
  unbinds = [];
});

function bind(page: string, opts: { scope?: "all"; fail?: string; reply?: unknown; standIn?: boolean; data?: unknown[]; init?: unknown } = {}) {
  const doc = load(page);
  if (opts.data) drawLinks(doc, LISTS[page], opts.data, true);
  const sent: SettingsWrite[] = [];
  const handlers =
    opts.scope === "all"
      ? null
      : {
          send: (w: SettingsWrite) => (sent.push(w), opts.fail ? Promise.reject(new Error(opts.fail)) : Promise.resolve(opts.reply ?? { success: true })),
          confirm: () => true,
          standIn: !!opts.standIn,
        };
  unbinds.push(bindWrites(doc, `settings/${page}`, null, true));
  const init = "init" in opts ? opts.init : INIT;
  unbinds.push(bindSettingsWrites(doc, `settings/${page}`, () => ({ init }), undefined, handlers, true));
  return sent;
}

describe("normalLink", () => {
  it.each([
    ["instagram.com/a", "https://instagram.com/a"],
    [" https://www.youtube.com/@b ", "https://www.youtube.com/@b"],
    ["http://x.co", "http://x.co/"],
    ["", null],
    ["javascript:alert(1)", null],
    ["ftp://x.com/a", null],
    ["localhost:3000", null],
    ["https://nodot/a", null],
    ["two words.com", null],
  ])("%j -> %j", (text, want) => expect(normalLink(text)).toBe(want));
});

describe("providersOf (GET /init socialMediaProviders)", () => {
  it.each([
    [INIT, [IG, TT, AMZ]],
    [{ socialMediaProviders: [{ socialMedia: "x", label: "X" }, { label: "no name" }, null, { socialMedia: "" }] }, [{ socialMedia: "x", label: "X", isLink: false, isShowAt: false }]],
    [{}, []],
    [undefined, []],
    [[], []],
  ])("%j", (init, want) => expect(providersOf(init)).toEqual(want));
});

describe("socialButtonBody (OF's form submit, 67786.js)", () => {
  it("is tagged measured-in-js and sends exactly the capture record's four keys; Things I Like stays inferred", () => {
    expect([LISTS["social-media"].source, LISTS.links.source]).toEqual([LINK_BODY_MEASURED, LINK_BODY_INFERRED]);
    expect(LINK_BODY_MEASURED).toBe("measured-in-js");
    expect(Object.keys(socialButtonBody("My Insta", "alpha", IG)!)).toEqual(["socialMedia", "label", "link", "username"]);
  });
  it.each([
    [IG, "My Insta", "alpha", { socialMedia: "instagram", label: "My Insta", link: "", username: "alpha" }],
    [IG, " IG ", " @alpha.one_2 ", { socialMedia: "instagram", label: "IG", link: "", username: "alpha.one_2" }],
    [TT, "TT", "@beta", { socialMedia: "tiktok", label: "TT", link: "", username: "beta" }],
    [IG, "Proof", "oi_proof_20261121t000000z", { socialMedia: "instagram", label: "Proof", link: "", username: "oi_proof_20261121t000000z" }],
    [AMZ, "Wishlist", "https://www.amazon.com/hz/wishlist/ls/X1", { socialMedia: "amazon", label: "Wishlist", link: "https://www.amazon.com/hz/wishlist/ls/X1", username: "" }],
    [AMZ, "Shop", " http://amzn.to/abc ", { socialMedia: "amazon", label: "Shop", link: "http://amzn.to/abc", username: "" }],
  ])("%j %j %j", (provider, label, value, want) => expect(socialButtonBody(label, value, provider)).toEqual(want));
  it.each([
    [null, "Label", "alpha"],
    [IG, "", "alpha"],
    [IG, "  ", "alpha"],
    [IG, "Label", ""],
    [IG, "Label", "@"],
    [IG, "Label", "https://instagram.com/alpha"],
    [AMZ, "Label", "amazon.com/x"],
    [AMZ, "Label", "https://nodot/x"],
    [AMZ, "Label", "javascript:alert(1)"],
    [IG, "x".repeat(256), "alpha"],
    [IG, "Label", "a".repeat(256)],
  ])("no body (Save off) for %j %j %j", (provider, label, value) => {
    expect(socialButtonBody(label, value, provider)).toBeNull();
    expect(canSave(SOCIAL, label, value, provider)).toBe(false);
  });
  it.each([
    ["https://instagram.com/a", true],
    ["http://a.co", true],
    ["HTTPS://A.CO/x y", false],
    ["instagram.com/a", false],
    ["https://-a.com", false],
    ["https://a--b.com", false],
  ])("ofUrl(%j) = %j (module 648075 bK)", (v, want) => expect(ofUrl(v)).toBe(want));
});

describe("Social media's list (ticket 69)", () => {
  it("reads GET /users/social/buttons and draws each button's label and link as text, idempotently", () => {
    expect(sourcesFor("social-media")).toEqual(["socialButtons", "init"]);
    expect(SOURCE_PATHS.socialButtons).toBe("/api/of/v2/users/social/buttons");
    expect(SOURCE_PATHS.init).toBe("/api/of/v2/init");
    const d = load("social-media");
    for (let i = 0; i < 2; i++) applyPageExtras(d, "social-media", { socialButtons: [B1, B2] }, true);
    expect(labels()).toEqual(["My Insta", "My TikTok"]);
    expect(d.querySelectorAll("[data-oi-link-row] a[href]").length).toBe(0);
    expect([...d.querySelectorAll("[data-oi-link-remove]")].every((b) => b.hasAttribute("data-oi-wired"))).toBe(true);
    applyPageExtras(d, "social-media", {}, true);
    expect(labels()).toEqual(["My Insta", "My TikTok"]);
  });
});

describe("Social media's Add button (ticket 69)", () => {
  it("is usable and Wired, its Not-yet title dropped (Live pass, D1), and opens the form (aria-expanded); Cancel sends nothing", () => {
    const sent = bind("social-media");
    expect(add().disabled).toBe(false);
    expect(add().hasAttribute("data-oi-wired")).toBe(true);
    expect(add().hasAttribute("title")).toBe(false);
    add().click();
    expect(add().getAttribute("aria-expanded")).toBe("true");
    expect(document.querySelector("[data-oi-link-dialog] .modal-title")?.textContent).toBe("Add button");
    document.querySelector<HTMLButtonElement>("[data-oi-link-cancel]")!.click();
    expect(document.querySelector("[data-oi-link-dialog]")).toBeNull();
    expect(add().getAttribute("aria-expanded")).toBe("false");
    expect(sent).toEqual([]);
  });

  it("opens on init's first provider, its name in Label; picking another follows OF's form", () => {
    bind("social-media");
    add().click();
    const select = document.getElementById("oi-link-provider") as HTMLSelectElement;
    const field = () => document.getElementById("oi-link-url") as HTMLInputElement;
    const at = () => document.querySelector<HTMLElement>("[data-oi-link-at]")!;
    expect([...select.options].map((o) => [o.value, o.textContent])).toEqual([["instagram", "Instagram"], ["tiktok", "Tiktok"], ["amazon", "Amazon"]]);
    expect(select.hasAttribute("data-oi-wired")).toBe(true);
    expect(select.value).toBe("instagram");
    expect((document.getElementById("oi-link-label") as HTMLInputElement).value).toBe("Instagram");
    expect([field().placeholder, at().hidden]).toEqual(["Username", true]);
    type("oi-link-url", "alpha");
    pickProvider("tiktok");
    expect((document.getElementById("oi-link-label") as HTMLInputElement).value).toBe("Tiktok");
    expect([field().value, field().placeholder, at().hidden]).toEqual(["alpha", "Username", false]);
    pickProvider("amazon");
    expect([field().value, field().placeholder, at().hidden]).toEqual(["", "Link", true]);
    expect(saveBtn()!.disabled).toBe(true);
  });

  it("keeps Save off until a label and a value the provider takes are typed", () => {
    bind("social-media");
    add().click();
    type("oi-link-url", "");
    expect(saveBtn()!.disabled).toBe(true);
    type("oi-link-url", "https://instagram.com/alpha");
    expect(saveBtn()!.disabled).toBe(true);
    type("oi-link-url", "alpha");
    expect(saveBtn()!.disabled).toBe(false);
    type("oi-link-label", " ");
    expect(saveBtn()!.disabled).toBe(true);
    pickProvider("amazon");
    type("oi-link-url", "amazon.com/x");
    expect(saveBtn()!.disabled).toBe(true);
    type("oi-link-url", "https://amazon.com/x");
    expect(saveBtn()!.disabled).toBe(false);
  });

  it("init unread or empty: the select has no provider and Save stays off (nothing a host could guess is sent)", () => {
    const sent = bind("social-media", { init: undefined });
    add().click();
    expect((document.getElementById("oi-link-provider") as HTMLSelectElement).options.length).toBe(0);
    type("oi-link-label", "My Insta");
    type("oi-link-url", "alpha");
    expect(saveBtn()!.disabled).toBe(true);
    saveBtn()!.click();
    expect(sent).toEqual([]);
  });

  it("Save sends OF's body (a username provider: link empty), draws OF's full-list reply and shows the saved toast", async () => {
    const sent = bind("social-media", { reply: [B1] });
    add().click();
    type("oi-link-label", "My Insta");
    type("oi-link-url", "@a");
    saveBtn()!.click();
    await flush();
    expect(sent).toEqual([
      { method: "PUT", path: "/api/of/v2/users/social/buttons", body: { socialMedia: "instagram", label: "My Insta", link: "", username: "a" } },
    ]);
    expect(document.querySelector("[data-oi-link-dialog]")).toBeNull();
    expect(labels()).toEqual(["My Insta"]);
    expect(toastText()).toBe(SAVED_TOAST);
  });

  it("a link provider's Save sends the link and an empty username", async () => {
    const sent = bind("social-media", { reply: [] });
    add().click();
    pickProvider("amazon");
    type("oi-link-url", "https://www.amazon.com/hz/wishlist/ls/X1");
    saveBtn()!.click();
    await flush();
    expect(sent.map((w) => w.body)).toEqual([{ socialMedia: "amazon", label: "Amazon", link: "https://www.amazon.com/hz/wishlist/ls/X1", username: "" }]);
  });

  it("a failed Save shows the red note in the open form and leaves the list as it was", async () => {
    const sent = bind("social-media", { fail: "synthetic failure", data: [B1] });
    add().click();
    type("oi-link-label", "TT");
    type("oi-link-url", "b");
    saveBtn()!.click();
    await flush();
    expect(sent.length).toBe(1);
    expect(noteText()).toBe("Could not save: synthetic failure");
    expect(noteColor()).toBe("rgb(255, 69, 69)");
    expect(document.querySelector("[data-oi-link-dialog]")).not.toBeNull();
    expect(saveBtn()!.disabled).toBe(false);
    expect(labels()).toEqual(["My Insta"]);
  });

  it("All models: says Select a model and sends nothing; the stand-in page sends as the stand-in", async () => {
    const none = bind("social-media", { scope: "all" });
    add().click();
    expect(noteText()).toBe(SELECT_MODEL);
    expect(document.querySelector("[data-oi-link-dialog]")).toBeNull();
    expect(none).toEqual([]);
    for (const u of unbinds) u();
    unbinds = [];
    const sent = bind("social-media", { standIn: true, reply: [B1] });
    add().click();
    type("oi-link-label", "My Insta");
    type("oi-link-url", "a");
    saveBtn()!.click();
    await flush();
    expect(sent.map((w) => w.method)).toEqual(["PUT"]);
  });
});

describe("Social media's remove (ticket 69)", () => {
  it("removes only the targeted button: DELETE /users/social/buttons/{id}, then that row goes", async () => {
    const sent = bind("social-media", { data: [B1, B2] });
    document.querySelector<HTMLButtonElement>("[data-oi-link-remove='2']")!.click();
    await flush();
    expect(sent).toEqual([{ method: "DELETE", path: "/api/of/v2/users/social/buttons/2" }]);
    expect(labels()).toEqual(["My Insta"]);
  });

  it("a failed remove keeps the row and shows the red note", async () => {
    bind("social-media", { data: [B1, B2], fail: "synthetic failure" });
    document.querySelector<HTMLButtonElement>("[data-oi-link-remove='1']")!.click();
    await flush();
    expect(labels()).toEqual(["My Insta", "My TikTok"]);
    expect(noteText()).toBe("Could not remove: synthetic failure");
  });

  it("All models: Select a model, nothing sent", () => {
    const sent = bind("social-media", { scope: "all", data: [B1] });
    document.querySelector<HTMLButtonElement>("[data-oi-link-remove='1']")!.click();
    expect(noteText()).toBe(SELECT_MODEL);
    expect(sent).toEqual([]);
    expect(labels()).toEqual(["My Insta"]);
  });
});

const LINKS = LISTS.links;
const createBtn = () => document.querySelector<HTMLButtonElement>(LINKS.add)!;
const liked = (id: number, url: string) => ({
  id,
  sort: id,
  url,
  title: " - YouTube",
  description: "a page's meta description",
  image: { src: "", thumbs: { c50: "", c144: "" }, width: 0, height: 0 },
});
const L1 = liked(1, "https://www.youtube.com/watch?v=a");
const L2 = liked(2, "https://www.imdb.com/title/tt1/");

describe("likedLinkBody (inferred site check, the record's one key)", () => {
  it.each([
    ["youtube.com/watch?v=a", { link: "https://youtube.com/watch?v=a" }],
    ["https://www.youtube.com/@b", { link: "https://www.youtube.com/@b" }],
    ["youtu.be/x", { link: "https://youtu.be/x" }],
    ["https://www.amazon.co.uk/dp/1", { link: "https://www.amazon.co.uk/dp/1" }],
    ["amazon.de/dp/1", { link: "https://amazon.de/dp/1" }],
    ["https://www.goodreads.com/book/show/1", { link: "https://www.goodreads.com/book/show/1" }],
    ["m.imdb.com/title/tt1", { link: "https://m.imdb.com/title/tt1" }],
    ["of.tv/videos/1", { link: "https://of.tv/videos/1" }],
    ["instagram.com/a", null],
    ["notyoutube.com/a", null],
    ["amazon.com.evil.net/a", null],
    ["javascript:alert(1)", null],
    ["", null],
  ])("%j -> %j", (link, want) => {
    expect(likedLinkBody("", link)).toEqual(want);
    expect(canSave(LINKS, "", link, null)).toBe(want !== null);
  });
});

describe("Things I Like's list (ticket 70)", () => {
  it("reads GET /users/links and draws each link as text with its Wired delete, idempotently", () => {
    expect(sourcesFor("links")).toEqual(["thingsLinks"]);
    expect(SOURCE_PATHS.thingsLinks).toBe("/api/of/v2/users/links");
    const d = load("links");
    for (let i = 0; i < 2; i++) applyPageExtras(d, "links", { thingsLinks: [L1, L2] }, true);
    expect(L1).not.toHaveProperty("link");
    expect(labels()).toEqual([L1.url, L2.url]);
    expect(d.querySelectorAll("[data-oi-link-row] a[href]").length).toBe(0);
    expect([...d.querySelectorAll("[data-oi-link-remove]")].every((b) => b.hasAttribute("data-oi-wired"))).toBe(true);
  });
});

describe("Things I Like's Create link (ticket 70)", () => {
  it("is usable and Wired, its Not-yet title dropped (Live pass, D1); its form asks the link alone; Cancel sends nothing", () => {
    const sent = bind("links");
    expect(createBtn().disabled).toBe(false);
    expect(createBtn().hasAttribute("data-oi-wired")).toBe(true);
    expect(createBtn().hasAttribute("title")).toBe(false);
    createBtn().click();
    expect(createBtn().getAttribute("aria-expanded")).toBe("true");
    expect(document.querySelector("[data-oi-link-dialog] .modal-title")?.textContent).toBe("Create link");
    expect(document.getElementById("oi-link-label")).toBeNull();
    document.querySelector<HTMLButtonElement>("[data-oi-link-cancel]")!.click();
    expect(document.querySelector("[data-oi-link-dialog]")).toBeNull();
    expect(sent).toEqual([]);
  });

  it("keeps Save off for a link off OF's sites; Save sends PUT /users/links {link}, draws the reply, shows the toast", async () => {
    const sent = bind("links", { reply: [L1] });
    createBtn().click();
    type("oi-link-url", "instagram.com/a");
    expect(saveBtn()!.disabled).toBe(true);
    type("oi-link-url", "https://www.youtube.com/watch?v=a");
    expect(saveBtn()!.disabled).toBe(false);
    saveBtn()!.click();
    await flush();
    expect(sent).toEqual([{ method: "PUT", path: "/api/of/v2/users/links", body: { link: "https://www.youtube.com/watch?v=a" } }]);
    expect(document.querySelector("[data-oi-link-dialog]")).toBeNull();
    expect(labels()).toEqual([L1.url]);
    expect(toastText()).toBe(SAVED_TOAST);
  });

  it("a failed Save shows the red note and leaves the list as it was", async () => {
    bind("links", { fail: "synthetic failure", data: [L1] });
    createBtn().click();
    type("oi-link-url", "imdb.com/title/tt1");
    saveBtn()!.click();
    await flush();
    expect(noteText()).toBe("Could not save: synthetic failure");
    expect(document.querySelector("[data-oi-link-dialog]")).not.toBeNull();
    expect(labels()).toEqual([L1.url]);
  });

  it("All models: Select a model, nothing sent; the stand-in page sends as the stand-in", async () => {
    const none = bind("links", { scope: "all" });
    createBtn().click();
    expect(noteText()).toBe(SELECT_MODEL);
    expect(none).toEqual([]);
    for (const u of unbinds) u();
    unbinds = [];
    const sent = bind("links", { standIn: true, reply: [L1] });
    createBtn().click();
    type("oi-link-url", "youtube.com/watch?v=a");
    saveBtn()!.click();
    await flush();
    expect(sent.map((w) => w.method)).toEqual(["PUT"]);
  });
});

describe("Things I Like's delete (ticket 70)", () => {
  it("deletes only the targeted link: DELETE /users/links/{id}, then that row goes", async () => {
    const sent = bind("links", { data: [L1, L2] });
    document.querySelector<HTMLButtonElement>("[data-oi-link-remove='2']")!.click();
    await flush();
    expect(sent).toEqual([{ method: "DELETE", path: "/api/of/v2/users/links/2" }]);
    expect(labels()).toEqual([L1.url]);
  });

  it("a failed delete keeps the row and shows the red note", async () => {
    bind("links", { data: [L1, L2], fail: "synthetic failure" });
    document.querySelector<HTMLButtonElement>("[data-oi-link-remove='1']")!.click();
    await flush();
    expect(labels()).toEqual([L1.url, L2.url]);
    expect(noteText()).toBe("Could not remove: synthetic failure");
  });
});
