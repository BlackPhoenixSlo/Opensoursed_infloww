import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

import { FANSLY_LIGHT_CLASS, FANSLY_CHROME_STYLE_ID, prepareFanslyDoc } from "./fanslyMirrorDoc";

const PAGE = `<!doctype html><html class="bright-theme"><head><title>x</title></head><body>
<div class="left-side" data-oi-nav><a href="/fansly-manager/home">Home</a></div>
<div class="middle-side">
  <img class="user-avatar" data-oi-avatar src="data:," alt="Your Model avatar" title="@yourmodel">
  <div class="profile-banner" data-oi-banner></div>
  <h1 class="display-name">Your Model</h1>
  <span class="handle">@yourmodel</span>
  <button aria-label="Message yourmodel">m</button>
  <input placeholder="Write to Your Model">
  <a class="go" href="/fansly-manager/lists/list?tab=2#top">list</a>
  <a class="hash" href="#">menu</a>
  <a class="out" href="/fansly-mirror/static/x.css">css</a>
  <a class="ext" href="https://example.invalid/x">ext</a>
</div></body></html>`;

const fresh = () => new DOMParser().parseFromString(PAGE, "text/html");
const A = { username: "ava_test", name: "Ava Test", avatar: "https://cdn.example.invalid/a.jpg", header: "https://cdn.example.invalid/a-banner.jpg" };
const B = { username: "bea_test", name: "Bea Test", avatar: "https://cdn.example.invalid/b.jpg", header: "https://cdn.example.invalid/b-banner.jpg" };
const $ = (doc: Document, sel: string) => doc.querySelector(sel)!;

describe("prepareFanslyDoc", () => {
  it("puts the creator's handle and name over the placeholders, in text and attributes", () => {
    const doc = fresh();
    prepareFanslyDoc(doc, { me: A, accountId: "fa", dark: false });
    expect($(doc, ".display-name").textContent).toBe("Ava Test");
    expect($(doc, ".handle").textContent).toBe("@ava_test");
    expect($(doc, "img[data-oi-avatar]").getAttribute("alt")).toBe("Ava Test avatar");
    expect($(doc, "img[data-oi-avatar]").getAttribute("title")).toBe("@ava_test");
    expect($(doc, "button").getAttribute("aria-label")).toBe("Message ava_test");
    expect($(doc, "input").getAttribute("placeholder")).toBe("Write to Ava Test");
    expect(doc.body.innerHTML).not.toMatch(/yourmodel|Your Model/);
  });

  it("a handle and name holding the placeholder swap once: re-runs and theme flips leave the text as it was", () => {
    const doc = fresh();
    const C = { username: "notyourmodel", name: "Mr yourmodel", avatar: A.avatar, header: A.header };
    prepareFanslyDoc(doc, { me: C, accountId: "fa", dark: false });
    const first = doc.body.innerHTML;
    prepareFanslyDoc(doc, { me: C, accountId: "fa", dark: true });
    prepareFanslyDoc(doc, { me: C, accountId: "fa", dark: false });
    expect(doc.body.innerHTML).toBe(first);
    expect($(doc, ".display-name").textContent).toBe("Mr yourmodel");
    expect($(doc, ".handle").textContent).toBe("@notyourmodel");
    expect($(doc, "img[data-oi-avatar]").getAttribute("alt")).toBe("Mr yourmodel avatar");
    expect($(doc, "img[data-oi-avatar]").getAttribute("title")).toBe("@notyourmodel");
    expect($(doc, "button").getAttribute("aria-label")).toBe("Message notyourmodel");
    expect($(doc, "input").getAttribute("placeholder")).toBe("Write to Mr yourmodel");
  });

  it("loads avatar and banner through the /img proxy for the shown creator", () => {
    const doc = fresh();
    prepareFanslyDoc(doc, { me: A, accountId: "fa", dark: false });
    expect($(doc, "img[data-oi-avatar]").getAttribute("src")).toBe("/img?u=https%3A%2F%2Fcdn.example.invalid%2Fa.jpg&account_id=fa");
    expect(($(doc, "[data-oi-banner]") as HTMLElement).style.backgroundImage).toContain("/img?u=https%3A%2F%2Fcdn.example.invalid%2Fa-banner.jpg&account_id=fa");
  });

  it("hides the rail with one chrome style however often it runs", () => {
    const doc = fresh();
    prepareFanslyDoc(doc, { me: A, accountId: "fa", dark: false });
    prepareFanslyDoc(doc, { me: A, accountId: "fa", dark: false });
    expect(doc.querySelectorAll(`style#${FANSLY_CHROME_STYLE_ID}`)).toHaveLength(1);
    expect($(doc, `style#${FANSLY_CHROME_STYLE_ID}`).textContent).toContain("[data-oi-nav]{display:none!important}");
  });

  it("sets Fansly's theme marker both ways: dark drops the light class, light puts it back", () => {
    const doc = fresh();
    prepareFanslyDoc(doc, { me: null, accountId: "fa", dark: true });
    expect(doc.documentElement.classList.contains("bright-theme")).toBe(false);
    prepareFanslyDoc(doc, { me: null, accountId: "fa", dark: false });
    expect(doc.documentElement.classList.contains("bright-theme")).toBe(true);
  });

  it("the marker is the generator's dark-boot class (Tracer facts dark_marker)", () => {
    const wire = readFileSync(resolve(__dirname, "../../scripts/fansly-mirror/wire.mjs"), "utf8");
    expect(wire).toContain(`export const THEME_MARKER = "${FANSLY_LIGHT_CLASS}";`);
  });

  it("with no me the placeholders stay; a later run with me fills them on the same document", () => {
    const doc = fresh();
    prepareFanslyDoc(doc, { me: null, accountId: "fa", dark: false });
    expect($(doc, ".display-name").textContent).toBe("Your Model");
    expect($(doc, "img[data-oi-avatar]").getAttribute("src")).toBe("data:,");
    expect(($(doc, "[data-oi-banner]") as HTMLElement).style.backgroundImage).toBe("");
    prepareFanslyDoc(doc, { me: A, accountId: "fa", dark: false });
    expect($(doc, ".display-name").textContent).toBe("Ava Test");
    expect($(doc, ".handle").textContent).toBe("@ava_test");
  });

  it("A then B on a fresh document gives B's identity, never A's", () => {
    prepareFanslyDoc(fresh(), { me: A, accountId: "fa", dark: false });
    const doc = fresh();
    prepareFanslyDoc(doc, { me: B, accountId: "fb", dark: false });
    expect($(doc, ".display-name").textContent).toBe("Bea Test");
    expect($(doc, "img[data-oi-avatar]").getAttribute("src")).toContain("account_id=fb");
    expect(doc.documentElement.outerHTML).not.toMatch(/ava_test|Ava Test|account_id=fa/);
  });

  it("an in-frame /fansly-manager/ link carries the creator; # and other links stay", () => {
    const doc = fresh();
    prepareFanslyDoc(doc, { me: null, accountId: "fb", dark: false });
    expect($(doc, "a.go").getAttribute("href")).toBe("/fansly-manager/lists/list?tab=2&creator=fb#top");
    expect($(doc, "[data-oi-nav] a").getAttribute("href")).toBe("/fansly-manager/home?creator=fb");
    expect($(doc, "a.hash").getAttribute("href")).toBe("#");
    expect($(doc, "a.out").getAttribute("href")).toBe("/fansly-mirror/static/x.css");
    expect($(doc, "a.ext").getAttribute("href")).toBe("https://example.invalid/x");
    prepareFanslyDoc(doc, { me: null, accountId: "fb", dark: false });
    expect($(doc, "a.go").getAttribute("href")).toBe("/fansly-manager/lists/list?tab=2&creator=fb#top");
  });
});
