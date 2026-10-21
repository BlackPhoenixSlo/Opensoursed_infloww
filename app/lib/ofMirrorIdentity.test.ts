import { describe, expect, it, vi } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { applyIdentity, bindSwitcher, bioOf, formatCount, switcherModels, type OfMe } from "./ofMirrorIdentity";
import { standInModel } from "./ofMirrorProfile";

const FIXTURE = `
<a href="#"> @yourmodel </a>
<div>https://onlyfans.com/yourmodel</div>
<div class="b-menu-list__subtext"><span class="b-amount-price m-num">$5.00</span> per month</div>
<img class="b-profile__header__cover-img" src="data:,x" alt="Your Model">
<a href="#" title="Your Model" aria-label="Message @yourmodel"><svg aria-label="yourmodel's page"></svg></a>
<span class="g-avatar"><div class="g-avatar__placeholder m-text-avatar"> Y </div></span>
<span class="g-avatar"><div class="g-avatar__placeholder m-text-avatar of-fan"> F </div></span>
<div class="g-input__wrapper"><input id="input-name" value="Your Model"><div class="v-counter">10 / 40</div></div>
<div class="g-input__wrapper"><input id="input-login" value="yourmodel"><div class="v-counter">9 / 24</div></div>
<div class="g-input__wrapper"><div data-placeholder="Bio"><p>Welcome to my page.</p></div><div class="b-under-field"><div class="count-block text-right"> 19/1000</div></div></div>
<input id="priceInput_1" placeholder="Free">`;

const doc = () => {
  document.body.innerHTML = FIXTURE;
  return document;
};
const me = { username: "livemodel", name: "Live Model", subscribePrice: 12.5, rawAbout: "Hi from live", avatar: null, header: null };

describe("applyIdentity", () => {
  it("swaps every placeholder for the live values", () => {
    const d = doc();
    applyIdentity(d, me);
    const text = d.body.textContent ?? "";
    expect(text).toContain("@livemodel");
    expect(text).toContain("https://onlyfans.com/livemodel");
    expect(text).toContain("$12.50");
    expect(text).toContain("Hi from live");
    expect(text).not.toMatch(/yourmodel|Welcome to my page|5\.00/);
    expect(d.querySelector<HTMLInputElement>("#input-name")!.value).toBe("Live Model");
    expect(d.querySelector<HTMLInputElement>("#input-login")!.value).toBe("livemodel");
    expect(d.querySelector("#input-login + .v-counter")!.textContent).toBe("9 / 24");
    expect(d.querySelector("#input-name + .v-counter")!.textContent).toBe("10 / 40");
    expect(d.querySelector(".m-text-avatar")!.textContent).toBe(" L ");
    expect(d.querySelector("img")!.getAttribute("alt")).toBe("Live Model");
    const a = d.querySelector("a[title]")!;
    expect(a.getAttribute("title")).toBe("Live Model");
    expect(a.getAttribute("aria-label")).toBe("Message @livemodel");
    expect(a.querySelector("svg")!.getAttribute("aria-label")).toBe("livemodel's page");
    expect(d.querySelector<HTMLInputElement>("#priceInput_1")!.value).toBe("12.5");
    expect(d.querySelector("[data-placeholder='Bio']")!.closest(".g-input__wrapper")!.querySelector(".count-block")!.textContent).toBe(" 12/1000");
  });

  it("keeps `about`'s line breaks as newlines (OF's editor shows and counts them)", () => {
    const about = '<p>I travel.<br /><br />All content is mine. By <a href="https://onlyfans.com/away?url=x">site.com</a>.</p>';
    expect(bioOf({ about })).toBe("I travel.\n\nAll content is mine. By site.com.");
    expect(bioOf({ about: "<p>one</p><p>two</p>" })).toBe("one\ntwo");
    // OF's nl2br markup: "<br />\n" is one line break, not two.
    expect(bioOf({ about: "one<br />\ntwo<br />\n<br />\nthree" })).toBe("one\ntwo\n\nthree");
    const d = doc();
    applyIdentity(d, { ...me, rawAbout: undefined, about });
    expect(d.querySelector("[data-placeholder='Bio'] p")!.textContent).toBe("I travel.\n\nAll content is mine. By site.com.");
    expect(d.querySelector(".count-block")!.textContent).toBe(" 44/1000");
  });

  it("shows Free for a zero price and strips markup from `about`", () => {
    const d = doc();
    applyIdentity(d, { ...me, subscribePrice: 0, rawAbout: undefined, about: "Hi <b>there</b><img src=x onerror=alert(1)>" });
    expect(d.querySelector(".b-amount-price")!.textContent).toBe("Free");
    expect(d.querySelector("[data-placeholder='Bio']")!.innerHTML).toBe("<p>Hi there</p>");
    expect(d.querySelector<HTMLInputElement>("#priceInput_1")!.value).toBe("");
  });

  it("points the cover and avatar at the (proxied) OF images", () => {
    const d = doc();
    applyIdentity(d, { ...me, header: "https://cdn.onlyfans.com/h.jpg", avatar: "https://cdn.onlyfans.com/a.jpg" }, (u) => `/img?u=${u}`);
    expect(d.querySelector(".b-profile__header__cover-img")!.getAttribute("src")).toBe("/img?u=https://cdn.onlyfans.com/h.jpg");
    // A picture inside the placeholder (OF paints the placeholder's ::after over its own background), once on a re-apply.
    applyIdentity(d, { ...me, avatar: "https://cdn.onlyfans.com/a.jpg" }, (u) => `/img?u=${u}`);
    const own = d.querySelector(".m-text-avatar:not(.of-fan)")!;
    expect([...own.children].map((c) => c.getAttribute("src"))).toEqual(["/img?u=https://cdn.onlyfans.com/a.jpg"]);
    expect(own.textContent).toBe("");
    // A fan's avatar keeps its placeholder.
    expect(d.querySelector(".of-fan img")).toBeNull();
    expect(d.querySelector(".of-fan")!.textContent).toBe(" F ");
  });

  it("Edit profile: with an avatar, OF's remove button beside the avatar's camera, disabled as the header's", () => {
    document.documentElement.innerHTML = readFileSync(resolve(__dirname, "../public/of-mirror/pages/settings/profile.html"), "utf8");
    const remove = () => [...document.querySelectorAll<HTMLButtonElement>(".b-profile__user .b-profile__header__cover__btns > button")];
    applyIdentity(document, { ...me, avatar: null });
    expect(remove()).toHaveLength(0);
    for (let i = 0; i < 2; i++) applyIdentity(document, { ...me, avatar: "https://cdn.onlyfans.com/a.jpg" });
    expect(remove().map((b) => [b.querySelector("use")?.getAttribute("href"), b.disabled, b.title, b.hasAttribute("data-v-710dd05d")])).toEqual([
      ["#icon-close", true, "Not available in Inflowwww yet", true],
    ]);
  });

  it("is idempotent and leaves placeholders alone for fields it lacks", () => {
    const d = doc();
    applyIdentity(d, {});
    expect(d.body.innerHTML).toBe(doc().body.innerHTML);
    applyIdentity(d, me);
    const once = d.body.innerHTML;
    applyIdentity(d, me);
    expect(d.body.innerHTML).toBe(once);
  });

  it("re-applies new values over earlier ones (after a profile save)", () => {
    const d = doc();
    applyIdentity(d, me);
    applyIdentity(d, { ...me, name: "New Name", username: "newmodel" });
    const text = d.body.textContent ?? "";
    expect(text).toContain("@newmodel");
    expect(text).not.toMatch(/livemodel|Live Model/);
    expect(d.querySelector("a[title]")!.getAttribute("title")).toBe("New Name");
    expect(d.querySelector(".m-text-avatar")!.textContent).toBe(" N ");
    expect(d.querySelector<HTMLInputElement>("#input-name")!.value).toBe("New Name");
  });

  it("the left nav's counts: the generator leaves no captured count; the Creator's own fill them, a zero badge stays hidden", () => {
    const html = readFileSync(resolve(__dirname, "../public/of-mirror/pages/home/index.html"), "utf8");
    document.documentElement.innerHTML = html.slice(html.indexOf("<body"));
    const d = document;
    const count = (f: string) => d.querySelector<HTMLElement>(`[data-oi-count='${f}']`)!;
    const fields = ["notificationsCount", "chatMessagesCount", "subscribersCount", "subscribesCount"];
    // The capture's "12+", "12", "12 Fans" and "123 Following" are gone: badges hidden and empty, Fans and Following "—".
    expect(fields.map((f) => count(f).textContent)).toEqual(["", "", " — ", " — "]);
    expect(fields.slice(0, 2).map((f) => count(f).style.display)).toEqual(["none", "none"]);
    expect(d.querySelectorAll(".l-header__menu__item__count:not([data-oi-count]), .l-sidebar__user-data__item__count:not([data-oi-count])")).toHaveLength(0);
    applyIdentity(d, { notificationsCount: 150, chatMessagesCount: 14, subscribersCount: 13, subscribesCount: 1530 });
    expect(fields.map((f) => count(f).textContent)).toEqual([" 99+ ", " 14 ", " 13 ", " 1.5K "]);
    expect(fields.slice(0, 2).map((f) => count(f).style.display)).toEqual(["", ""]);
    applyIdentity(d, { notificationsCount: 0, chatMessagesCount: 3 });
    expect(count("notificationsCount").style.display).toBe("none");
    expect(count("chatMessagesCount").textContent).toBe(" 3 ");
    expect(count("subscribersCount").textContent).toBe(" 13 ");
  });

  it("formatCount: OF's B4, by digit count, OF's own rounding at the edges", () => {
    const ns = [0, 16, 867, 999, 1000, 1530, 1999, 2698, 9999, 14_093, 99_999, 123_456, 999_950, 999_999, 1_000_000, 1_234_567, 9_999_999, 12_345_678];
    expect(ns.map(formatCount)).toEqual(["0", "16", "867", "999", "1.0K", "1.5K", "2.0K", "2.7K", "10.0K", "14.1K", "100.0K", "123.5K", "1000.0K", "1000.0K", "1.00M", "1.23M", "10.00M", "12.3M"]);
  });
});

/** OF's own /api2/v2/users/me and the Relay's /admin/accounts, captured and scrubbed (app/lib/__fixtures__/of). */
const fixture = <T,>(name: string): T => JSON.parse(readFileSync(resolve(__dirname, `__fixtures__/of/avatar-menu-${name}.json`), "utf8")) as T;
const ME = fixture<OfMe & { name: string; username: string; avatar: string }>("me");
const ACCOUNTS = fixture<{ accounts: { id: string; nickname: string; has_session: boolean }[] }>("accounts").accounts;
const MENU_SRC = "/of-mirror/pages/home/state-avatar-menu.html";

describe("the avatar menu (home/state-avatar-menu)", () => {
  const load = () => {
    const html = readFileSync(resolve(__dirname, "../public/of-mirror/pages/home/state-avatar-menu.html"), "utf8");
    document.documentElement.innerHTML = html.slice(html.indexOf("<body"));
    return document;
  };
  const drawer = (d: Document) => d.querySelector<HTMLElement>(".l-sidebar")!;
  const text = (e: Element | null) => e?.textContent?.replace(/\s+/g, " ").trim();

  it("All models shows the first model, a selected model itself", () => {
    expect(standInModel(MENU_SRC, null, ACCOUNTS)).toBe(ACCOUNTS[0].id);
    expect(standInModel(MENU_SRC, "2", ACCOUNTS)).toBeNull();
    expect(standInModel("/of-mirror/pages/home/index.html", null, ACCOUNTS)).toBeNull();
  });

  it("the model's own avatar, name, handle, Fans and Following; no placeholder or dash left", () => {
    const d = load();
    applyIdentity(d, ME, (u) => `/img?u=${u}`);
    const s = drawer(d);
    expect(text(s.querySelector(".l-sidebar__username .g-user-name"))).toBe(ME.name);
    expect(text(s.querySelector(".l-sidebar__username .g-user-username"))).toBe(`@${ME.username}`);
    expect(s.querySelector(".l-sidebar__avatar img")!.getAttribute("src")).toBe(`/img?u=${ME.avatar}`);
    expect([...s.querySelectorAll(".l-sidebar__user-data__item")].map(text)).toEqual([`${ME.subscribersCount} Fans`, `${ME.subscribesCount} Following`]);
    expect(s.textContent).not.toMatch(/Your Model|yourmodel|—/);
    // Verified and visible online, as the capture already shows.
    expect(s.querySelector(".l-sidebar__username .g-user-name")!.classList.contains("m-verified")).toBe(true);
    expect(s.querySelector<HTMLElement>(".l-sidebar__avatar .g-avatar__icon")!.style.display).toBe("");
  });

  it("OF's rows, in OF's order, each linking to its OF Manager page or disabled with the tooltip when it has none", () => {
    const d = load();
    applyIdentity(d, ME);
    const rows = [...drawer(d).querySelectorAll<HTMLElement>(".l-sidebar__menu__item")].map((e) => [text(e), e.getAttribute("href") ?? (e.matches("button") ? (e as HTMLButtonElement) : e.querySelector("button"))!.disabled]);
    expect(rows).toEqual([
      ["My profile", "/of-manager/profile"],
      ["Referrals", "/of-manager/statistics/statements/referrals/earnings"],
      ["Collections", "/of-manager/collections"],
      ["Queue", "/of-manager/queue"],
      ["Vault", "/of-manager/vault"],
      ["Settings", "/of-manager/settings"],
      ["Streaming", "/of-manager/streaming/dashboard"],
      ["Statements", "/of-manager/statements"],
      // OF's own Statistics link opens Overview (the bare section is Infloww's landing, next.config.ts).
      ["Statistics", "/of-manager/statistics/overview/earnings"],
      ["Promotions", "/of-manager/settings/subscription"],
      ["Release forms", "/of-manager/release-forms"],
      ["Your сards (to subscribe)", "/of-manager/bank/payments"],
      // canReceiveManualPayout: OF's bank row, not the capture's "Add bank (to earn)".
      ["Bank (to earn)", "/of-manager/bank"],
      ["Help and support", true],
      ["Dark mode", true],
      ["English", true],
      ["Log out", true],
    ]);
    expect(drawer(d).querySelector("a[at-attr='bank'] use")!.getAttribute("href")).toBe("#icon-bank");
    expect(d.querySelector("#icon-bank")).not.toBeNull();
    for (const a of drawer(d).querySelectorAll(".l-sidebar__menu a.l-sidebar__menu__item")) expect(a.getAttribute("target")).toBe("_top");
  });

  it("a model that cannot be paid out, is not verified or hides its online status gets OF's rows for that, and back", () => {
    const d = load();
    applyIdentity(d, { ...ME, canReceiveManualPayout: false, isVerified: false, isVisibleOnline: false });
    const s = drawer(d);
    expect(text(s.querySelector("a[at-attr='bank']"))).toBe("Add bank (to earn)");
    expect(s.querySelector("a[at-attr='bank'] use")!.getAttribute("href")).toBe("#icon-add-bank");
    expect(s.querySelector(".l-sidebar__username .g-user-name")!.classList.contains("m-verified")).toBe(false);
    expect(s.querySelector<SVGElement>(".l-sidebar__username .g-user-name svg")!.style.display).toBe("none");
    expect(s.querySelector<HTMLElement>(".l-sidebar__avatar .g-avatar__icon")!.style.display).toBe("none");
    applyIdentity(d, ME);
    expect(text(s.querySelector("a[at-attr='bank']"))).toBe("Bank (to earn)");
    expect(s.querySelector(".l-sidebar__username .g-user-name")!.classList.contains("m-verified")).toBe(true);
  });

  it("the chevron lists the agency's models, the shown one ticked with its own name, handle and picture; a pick switches", () => {
    const d = load();
    const accounts = [...ACCOUNTS, { id: "2", nickname: "Second", has_session: true }];
    const models = switcherModels(accounts, ACCOUNTS[0].id, ME);
    expect(models).toEqual([
      { id: ACCOUNTS[0].id, name: ME.name, username: ME.username, avatar: ME.avatar },
      { id: "2", name: "Second" },
    ]);
    const onPick = vi.fn();
    const unbind = bindSwitcher(d, models, ACCOUNTS[0].id, onPick, (u) => `/img?u=${u}`);
    const toggle = d.querySelector<HTMLButtonElement>("[data-oi-switcher] > button")!;
    expect([toggle.disabled, toggle.hasAttribute("data-oi-wired"), d.querySelector("[data-oi-switcher-menu]")]).toEqual([false, true, null]);
    toggle.click();
    const menu = d.querySelector("[data-oi-switcher-menu]")!;
    expect(toggle.getAttribute("aria-expanded")).toBe("true");
    const rows = [...menu.querySelectorAll(".connected-accounts")];
    expect(rows.map((r) => [text(r), r.classList.contains("m-current"), r.querySelector("img")?.getAttribute("src") ?? null])).toEqual([
      [`${ME.name} @${ME.username}`, true, `/img?u=${ME.avatar}`],
      ["S Second", false, null],
      ["Add another account", false, null],
    ]);
    expect(rows[0].querySelector("use")!.getAttribute("href")).toBe("#icon-done");
    expect(menu.querySelector("a")!.getAttribute("href")).toBe("/creators");
    // A pick closes it and selects that model (the ticked one too: in All models it is only the stand-in).
    menu.querySelector<HTMLButtonElement>("[data-oi-model='1001']")!.click();
    expect([onPick.mock.calls, d.querySelector("[data-oi-switcher-menu]")]).toEqual([[["1001"]], null]);
    toggle.click();
    d.querySelector<HTMLButtonElement>("[data-oi-model='2']")!.click();
    expect([onPick.mock.calls, d.querySelector("[data-oi-switcher-menu]")]).toEqual([[["1001"], ["2"]], null]);
    // Escape and a click outside close it; the unbind leaves it shut and deaf.
    toggle.click();
    d.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
    expect(d.querySelector("[data-oi-switcher-menu]")).toBeNull();
    toggle.click();
    d.body.dispatchEvent(new MouseEvent("mousedown", { bubbles: true }));
    expect(d.querySelector("[data-oi-switcher-menu]")).toBeNull();
    unbind();
    toggle.click();
    expect(d.querySelector("[data-oi-switcher-menu]")).toBeNull();
  });
});
