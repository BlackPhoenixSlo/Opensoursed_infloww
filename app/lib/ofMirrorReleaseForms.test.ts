/**
 * Release forms (release-forms/index): the tab's Relay rows in place of the example, the tabs, the sidebar search, Sort,
 * a row's More (OF's toggle-show body, the fixture's), the Release form tab's empty placeholder, no model, and the
 * generator's Mentions link and disabled Create new release form and Create new invitation link.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import { bindReleaseForms, RELEASE_FORMS_PAGE, type ReleaseFormsHandlers } from "./ofMirrorReleaseForms";
import { tagViewOf } from "./ofMirrorPost";
import type { TaggedFriendUser } from "./relay";

const fixture = <T,>(name: string): T => JSON.parse(readFileSync(resolve(__dirname, `__fixtures__/of/${name}.json`), "utf8")) as T;
const TAGS = fixture<{ items: TaggedFriendUser[] }>("new-post-tags").items;
const load = () => {
  document.documentElement.innerHTML = readFileSync(resolve(__dirname, `../public/of-mirror/pages/${RELEASE_FORMS_PAGE}.html`), "utf8");
  return document;
};
const flush = () => new Promise((r) => setTimeout(r, 0));
const click = (el: Element | null | undefined) => el!.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
const textOf = (el: Element | null | undefined) => (el?.textContent ?? "").replace(/\s+/g, " ").trim();
const menuRows = (d: Document) => [...d.querySelectorAll<HTMLElement>("#oi-menu [data-oi-value]")];
const pickRow = (d: Document, label: string) => click(menuRows(d).find((r) => r.textContent?.trim() === label));
const rows = (d: Document) => [...d.querySelectorAll<HTMLElement>("label.b-rows-lists__item[data-oi-user]")];
const examples = (d: Document) => [...d.querySelectorAll<HTMLElement>("label.b-rows-lists__item:not([data-oi-user])")];
const handlers = () => ({
  navigate: vi.fn<(href: string) => void>(),
  toggleTag: vi.fn<ReleaseFormsHandlers["toggleTag"]>(() => Promise.resolve({})),
});
const unbinds: (() => void)[] = [];
afterEach(() => {
  unbinds.splice(0).forEach((u) => u());
  vi.useRealTimers();
});
const bind = (h: ReturnType<typeof handlers> | null, items: TaggedFriendUser[] | undefined = TAGS, query = "") => {
  const d = load();
  unbinds.push(bindReleaseForms(d, { handlers: h, items, view: tagViewOf(new URLSearchParams(query)), accountId: "acct-1" }));
  return d;
};

describe("Release forms page", () => {
  it("the generator's page: one example row, Mentions opens Notifications' Tags, Create new release form and Create new invitation link disabled", () => {
    const d = load();
    expect(examples(d)).toHaveLength(1);
    const mentions = [...d.querySelectorAll<HTMLAnchorElement>("a.b-tabs__nav__link")].find((a) => textOf(a) === "Mentions")!;
    expect(mentions.getAttribute("href")).toBe("/of-manager/notifications/tags");
    expect(mentions.querySelector(".b-tabs__nav__count")).toBeNull();
    for (const text of ["Create new release form", "Create new invitation link"]) {
      const b = [...d.querySelectorAll<HTMLButtonElement>("button")].find((x) => textOf(x) === text)!;
      expect([b.disabled, b.title]).toEqual([true, "Not available in Inflowwww yet"]);
    }
  });

  it("shows the Relay's rows (name, @username) in place of the example; the unbind puts it back", () => {
    const d = load();
    const unbind = bindReleaseForms(d, { handlers: handlers(), items: TAGS, view: tagViewOf(new URLSearchParams()), accountId: "acct-1" });
    expect(rows(d).map((r) => textOf(r.querySelector(".b-rows-lists__item__name")))).toEqual(TAGS.map((t) => t.user!.name));
    expect(textOf(rows(d)[0].querySelector(".b-content-inside-thumbs"))).toBe(`@${TAGS[0].user!.username}`);
    expect(examples(d).every((e) => e.style.display === "none")).toBe(true);
    unbind();
    expect(rows(d)).toHaveLength(0);
    expect(examples(d)[0].style.display).toBe("");
  });

  it("no model: no rows, and each tool says Select a model without sending", () => {
    const d = bind(null);
    expect(rows(d)).toHaveLength(0);
    click(d.querySelector(".b-content-filter button[aria-label='Sort']"));
    expect(d.getElementById("oi-note")?.textContent).toBe("Select a model to save changes");
    expect(d.getElementById("oi-menu")).toBeNull();
  });

  it("the tabs, Sort and the sidebar search open the page with that view", () => {
    vi.useFakeTimers();
    const h = handlers();
    const d = bind(h);
    const tabs = [...d.querySelectorAll<HTMLButtonElement>("button.b-tabs__nav__link")];
    expect(tabs.map((t) => [textOf(t), t.classList.contains("m-current")])).toEqual([["Tag user", true], ["Release form", false]]);
    click(tabs[1]);
    expect(h.navigate).toHaveBeenLastCalledWith("/of-manager/release-forms?tab=forms");
    click(d.querySelector(".b-content-filter button[aria-label='Sort']"));
    expect(menuRows(d).map((r) => r.textContent?.trim())).toEqual(["All", "Pending", "Recent", "Name", "Ascending", "Descending"]);
    pickRow(d, "Name");
    expect(h.navigate).toHaveBeenLastCalledWith("/of-manager/release-forms?sort=name");
    const field = d.querySelector<HTMLInputElement>(".b-release-form__side-bar input[type='search']")!;
    field.value = "synth";
    field.dispatchEvent(new Event("input", { bubbles: true }));
    vi.advanceTimersByTime(400);
    expect(h.navigate).toHaveBeenLastCalledWith("/of-manager/release-forms?q=synth");
  });

  it("a view's tab, sort and query show: the Release form tab current, the filter titled Name, the field filled", () => {
    const d = bind(handlers(), TAGS, "tab=forms&sort=name&q=syn");
    const current = d.querySelector("button.b-tabs__nav__link.m-current");
    expect(textOf(current)).toBe("Release form");
    expect(textOf(d.querySelector(".b-content-filter__title"))).toBe("Name");
    expect(d.querySelector<HTMLInputElement>(".b-release-form__side-bar input[type='search']")!.value).toBe("syn");
  });

  it("an empty Release form tab shows OF's placeholder; searching, Nothing found", () => {
    expect(textOf(bind(handlers(), [], "tab=forms").querySelector("[data-oi-empty]"))).toBe("No release forms yet");
    unbinds.splice(0).forEach((u) => u());
    expect(textOf(bind(handlers(), [], "tab=forms&q=zz").querySelector("[data-oi-empty]"))).toBe("Nothing found");
  });

  it("a row's More > Hide from list sends OF's toggle-show body (the fixture's), then Show in list", async () => {
    const fx = fixture<{ relay: { entity_id: number; entity_type: string } }>("new-post-tag-hide-body");
    const h = handlers();
    const d = bind(h, [{ ...TAGS[0], id: fx.relay.entity_id }]);
    const row = rows(d)[0];
    click(row.querySelector(".m-btn-vertical-dots"));
    pickRow(d, "Hide from list");
    expect(h.toggleTag).toHaveBeenCalledWith(fx.relay);
    await flush();
    expect(row.hasAttribute("data-oi-hidden")).toBe(true);
    click(row.querySelector(".m-btn-vertical-dots"));
    expect(menuRows(d).map((r) => r.textContent?.trim())).toEqual(["Show in list"]);
  });

  it("a row's click picks nothing (no post to tag here)", () => {
    const d = bind(handlers());
    const box = rows(d)[0].querySelector<HTMLInputElement>("input[type='checkbox']")!;
    click(rows(d)[0].querySelector(".b-rows-lists__item__name"));
    expect(box.checked).toBe(false);
  });
});
