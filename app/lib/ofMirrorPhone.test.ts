import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import { closeMenu, ORDER_GROUP, showMenu } from "./ofMirrorMenu";
import { applyPhoneHeader, applyPhoneMenus } from "./ofMirrorPhone";

/** OF's phone bar (WebsiteHeader's isXSMQ), on a desktop capture. */

const load = () => {
  document.documentElement.innerHTML = readFileSync(resolve(__dirname, "../public/of-mirror/pages/settings/profile.html"), "utf8");
  return document;
};
const visible = () =>
  [...document.querySelectorAll<HTMLElement>("nav.l-header__menu > .l-header__menu__item")]
    .filter((e) => e.style.display !== "none")
    .map((e) => (e.textContent ?? "").replace(/\s+/g, " ").trim());

describe("applyPhoneHeader", () => {
  it("on a phone: the avatar, Home, Notifications, Messages and a plain New post, as OF's template", () => {
    const d = load();
    applyPhoneHeader(d, true);
    expect(visible()).toEqual(["Y", "Home", "Notifications", "Messages", "New post"]);
    const nav = d.querySelector("nav.l-header__menu")!;
    expect(nav.className).toBe("l-header__menu g-sides-gaps");
    expect(d.querySelector(".m-avatar-item .g-avatar")!.classList.contains("m-w24")).toBe(true);
    expect([...d.querySelector(".m-create-post")!.classList].some((c) => ["g-btn", "m-rounded", "m-lg"].includes(c))).toBe(false);
  });

  it("back above XS: the desktop capture as it was", () => {
    const d = load();
    const before = d.querySelector("header.l-header")!.outerHTML;
    applyPhoneHeader(d, true);
    applyPhoneHeader(d, false);
    expect(visible()).toContain("Collections");
    expect(visible()).toContain("More");
    const nav = d.querySelector("nav.l-header__menu")!;
    expect(nav.classList.contains("m-native-custom-scrollbar")).toBe(true);
    expect(d.querySelector(".m-create-post")!.classList.contains("g-btn")).toBe(true);
    expect(d.querySelector(".m-avatar-item .g-avatar")!.classList.contains("m-w36")).toBe(true);
    expect(d.querySelector("header.l-header")!.outerHTML.replace(/ style=""/g, "")).toBe(before);
  });
});

/** OF's phone menu (below SM, 768px): full-screen over its `v-menu-overlay`, the list in the middle (live phone capture). */
describe("phone menus", () => {
  const page = (slug: string) => {
    document.documentElement.innerHTML = readFileSync(resolve(__dirname, `../public/of-mirror/pages/settings/${slug}.html`), "utf8");
    return document;
  };
  afterEach(() => {
    closeMenu(document);
    vi.unstubAllGlobals();
  });

  it("a state page's open select: moved to the body with OF's overlay after it on a phone, back under its control above", () => {
    const d = page("security/watermarks/state-options");
    const menu = d.querySelector<HTMLElement>(".of-state-menu")!;
    const home = menu.parentElement!;
    const style = menu.getAttribute("style");
    applyPhoneMenus(d, true);
    applyPhoneMenus(d, true);
    expect(menu.parentElement).toBe(d.body);
    expect(menu.nextElementSibling!.className).toBe("v-menu-overlay");
    expect(d.querySelectorAll(".v-menu-overlay")).toHaveLength(1);
    expect(menu.style.getPropertyValue("position")).toBe("fixed");
    expect(menu.style.getPropertyPriority("position")).toBe("important");
    applyPhoneMenus(d, false);
    expect(menu.parentElement).toBe(home);
    expect(d.querySelector(".v-menu-overlay")).toBeNull();
    expect(menu.getAttribute("style")).toBe(style);
  });

  it("a sort dropdown takes OF's m-modal-view (no overlay); a press on the box outside the list follows the backdrop link; the country picker stays under its field", () => {
    const d = page("subscription/tracking-links/state-kebab");
    applyPhoneMenus(d, true);
    const sort = d.querySelector<HTMLElement>(".of-state-menu")!;
    expect(sort.parentElement).toBe(d.body);
    expect(sort.classList.contains("m-modal-view")).toBe(true);
    expect(d.querySelector(".v-menu-overlay")).toBeNull();
    const clicked = vi.fn((ev: Event) => ev.preventDefault());
    d.querySelector("a.of-state-backdrop")!.addEventListener("click", clicked);
    d.querySelector<HTMLElement>(".of-state-menu .v-list-item")!.click();
    expect(clicked).not.toHaveBeenCalled();
    d.querySelector<HTMLElement>(".of-state-menu")!.click();
    expect(clicked).toHaveBeenCalledTimes(1);
    const c = page("security/block_by_country/state-country-picker");
    const picker = c.querySelector<HTMLElement>(".of-state-menu")!;
    const parent = picker.parentElement;
    applyPhoneMenus(c, true);
    expect(picker.parentElement).toBe(parent);
    expect(c.querySelector(".v-menu-overlay")).toBeNull();
  });

  it("a runtime sort menu on a phone: OF's m-modal-view and scope mark, no placement of its own; a press beside the list closes it", async () => {
    document.body.innerHTML = '<button id="a">Sort</button>';
    vi.stubGlobal("matchMedia", (q: string) => ({ matches: q === "(max-width: 767.98px)" }));
    showMenu(document, document.getElementById("a")!, [ORDER_GROUP("desc")], () => {});
    const menu = document.getElementById("oi-menu")!;
    expect(menu.style.position).toBe("");
    expect(menu.style.top).toBe("");
    expect(menu.classList.contains("m-modal-view")).toBe(true);
    expect(menu.hasAttribute("data-v-55f3fe86")).toBe(true);
    await new Promise((r) => setTimeout(r, 0));
    menu.querySelector<HTMLElement>("[data-oi-group]")!.parentElement!.dispatchEvent(new MouseEvent("mousedown", { bubbles: true }));
    expect(document.getElementById("oi-menu")).not.toBeNull();
    menu.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    expect(document.getElementById("oi-menu")).toBeNull();
  });
});
