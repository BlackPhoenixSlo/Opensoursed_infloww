import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import { applyData } from "./ofMirrorData";
import { BAR, bindVault, CUSTOMIZE, LIST_SORTS, LISTS_SEARCH, ORDER_BOX, PHONE_BACK, pollUpload, vaultHref, vaultListsPath, vaultMediaPath, VIEWER, viewOf, VIEW_OPEN, type VaultContext, type VaultHandlers, type VaultLists } from "./ofMirrorVault";
import { SELECT_MODEL } from "./ofMirrorWrites";
import type { VaultMedia } from "./relay";

const capture = (p: string) => readFileSync(resolve(__dirname, `../public/of-mirror/pages/${p}.html`), "utf8");
const load = (p: string) => {
  document.documentElement.innerHTML = capture(p);
  return document;
};
const visible = (el: Element) => !el.closest("[style*='display:none']");
const flush = () => new Promise((r) => setTimeout(r, 0));
const noteText = (doc: Document) => doc.getElementById("oi-note")?.textContent;
// One document for every test: each one's listeners go before the next.
const bound: (() => void)[] = [];
const bind = (...args: Parameters<typeof bindVault>) => {
  const unbind = bindVault(...args);
  bound.push(unbind);
  return unbind;
};
afterEach(() => {
  for (const u of bound.splice(0)) u();
});

/** OF's own vault responses, captured through the Relay and scrubbed (app/lib/__fixtures__/of/vault-*.json). */
const fixture = <T,>(name: string): T => JSON.parse(readFileSync(resolve(__dirname, `__fixtures__/of/vault-${name}.json`), "utf8")) as T;
const LISTS = fixture<VaultLists>("lists");
const CUSTOM = LISTS.list!.filter((l) => l.type === "custom");
/** A custom folder with media (the open one) and one without (the target). */
const [A, B] = [CUSTOM.find((l) => l.hasMedia)!, CUSTOM.find((l) => !l.hasMedia)!];
const [AID, BID] = [String(A.id), String(B.id)];
const MEDIA = fixture<{ list: VaultMedia[] }>("media-all").list.slice(0, 3);
const IDS = MEDIA.map((m) => m.id);

function handlers(over: Partial<VaultHandlers> = {}): VaultHandlers {
  return {
    createFolder: vi.fn(async () => ({ id: 12 })),
    renameFolder: vi.fn(async () => ({})),
    deleteFolder: vi.fn(async () => ({})),
    sortFolders: vi.fn(async () => ({})),
    customOrder: vi.fn(async () => ({})),
    addToFolder: vi.fn(async () => ({})),
    removeFromFolder: vi.fn(async () => ({})),
    hide: vi.fn(async () => ({})),
    upload: vi.fn(async () => ({ status: "done", total: 1, done: 1 })),
    tags: vi.fn(async () => ["beach", "red"]),
    saveTags: vi.fn(async (_id: number, tags: string[]) => tags),
    confirm: vi.fn(() => true),
    ...over,
  };
}
const ctxOf = (params: string, over: Partial<VaultContext> = {}): VaultContext => {
  const sp = new URLSearchParams(params);
  return { view: viewOf(sp), edit: sp.get("edit") === "1", lists: LISTS, navigate: vi.fn(), handlers: handlers(), ...over };
};
const click = (el: Element) => el.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
/** A tile's own checkbox (OF's: it selects the tile). */
const check = (tile: Element) => click(tile.querySelector(".checkbox-item")!);

describe("the view", () => {
  it("viewOf keeps known values only; vaultHref and vaultMediaPath carry them", () => {
    const view = viewOf(new URLSearchParams("list=7&type=video&field=buyers&sort=asc&date=2026-09-08&q=%20beach%20&slist=%20fold%20"));
    expect(view).toEqual({ list: "7", type: "video", field: "buyers", sort: "asc", date: "2026-09-08", q: "beach", slist: "fold" });
    expect(viewOf(new URLSearchParams("type=pdf&field=recent&sort=desc&date=9/8/2026&q=%20&slist=%20"))).toEqual({ list: null, type: null, field: null, sort: null, date: null, q: null, slist: null });
    expect(vaultHref(view)).toBe("/of-manager/vault?list=7&type=video&field=buyers&sort=asc&date=2026-09-08&q=beach&slist=fold");
    expect(vaultHref({})).toBe("/of-manager/vault");
    // Go to date: OF's beforePublishDate (the Relay's before_publish_date); the folder search is not the media's.
    expect(vaultMediaPath(view)).toBe("/api/of/v2/vault/media?limit=24&list_id=7&type=video&field=buyers&sort=asc&query=beach&before_publish_date=2026-09-08");
    expect(vaultMediaPath(viewOf(new URLSearchParams()))).toBe("/api/of/v2/vault/media?limit=24");
    // The folder search: GET /vault/lists `query`; none without one.
    expect(vaultListsPath(view)).toBe("/api/of/v2/vault/lists?view=main&limit=50&query=fold");
    expect(vaultListsPath(viewOf(new URLSearchParams()))).toBe("/api/of/v2/vault/lists?view=main&limit=50");
  });

  it("links to the page and its state pages keep the view; folder rows do not", () => {
    const doc = load("vault/index");
    applyData(doc, "vault/index", { vaultLists: LISTS.list, list: AID });
    bind(doc, "vault/index", ctxOf(`list=${AID}&type=photo`));
    const hrefs = [...doc.querySelectorAll<HTMLAnchorElement>("a[href^='/of-manager/vault']")].map((a) => a.getAttribute("href")!);
    expect(hrefs.filter((h) => h.startsWith("/of-manager/vault/state-")).every((h) => h.endsWith(`?list=${AID}&type=photo`))).toBe(true);
    expect(hrefs).toContain(`/of-manager/vault?list=${BID}`);
  });

  it("vault/list's folder sort, media sort and Create new category open the Vault's state pages with the view; More stays disabled", () => {
    const doc = load("vault/list");
    applyData(doc, "vault/list", { vaultLists: LISTS.list, list: AID });
    bind(doc, "vault/list", ctxOf(`list=${AID}&type=photo`));
    const link = (sel: string) => doc.querySelector(sel)?.getAttribute("href");
    const sorts = [...doc.querySelectorAll(".b-dropdown-wrapper")].filter((w) => w.querySelector(":scope > button[aria-label='Sort']"));
    expect(sorts.map((w) => w.querySelector(":scope > a.of-state-link")?.getAttribute("href"))).toEqual([
      `/of-manager/vault/state-lists-sort-dropdown?list=${AID}&type=photo`,
      `/of-manager/vault/state-sort-dropdown?list=${AID}&type=photo`,
    ]);
    expect(link("a[aria-label='Create new category']")).toBe(`/of-manager/vault/state-add-list?list=${AID}&type=photo`);
    expect(doc.querySelector<HTMLButtonElement>("button[aria-label='More']")!.disabled).toBe(true);
  });

  it("the rail, the side menu and the column's Back go to the bare Vault, as OF's; closing the search keeps the folder", () => {
    const doc = load("vault/list");
    applyData(doc, "vault/list", { vaultLists: LISTS.list, list: AID });
    bind(doc, "vault/list", ctxOf(`list=${AID}&type=photo&q=beach`));
    const hrefs = (sel: string) => [...doc.querySelectorAll(sel)].map((a) => a.getAttribute("href"));
    expect(hrefs("a.l-header__menu__item[data-name='MediaVault'], a.l-sidebar__menu__item[at-attr='vault']")).toEqual(["/of-manager/vault", "/of-manager/vault"]);
    expect(hrefs(".l-sidebar-column a.g-page__header__btn[aria-label='Back']:not([at-attr='close_search'])")).toEqual(["/of-manager/vault"]);
    expect(hrefs(".l-main-content.m-r-side [at-attr='close_search']")).toEqual([`/of-manager/vault?list=${AID}&type=photo`]);
  });

  it("a phone's open folder has a Back to the folder list before the media's title; unbind takes it away", () => {
    const doc = load("vault/index");
    const unbind = bind(doc, "vault/index", ctxOf(`list=${AID}`));
    const back = doc.getElementById(PHONE_BACK)!;
    expect([back.getAttribute("href"), back.getAttribute("aria-label"), back.nextElementSibling?.tagName]).toEqual(["/of-manager/vault", "Back", "H1"]);
    expect(back.closest(".l-main-content.m-r-side .g-page__header")).not.toBeNull();
    const css = doc.head.querySelector("style:last-of-type")!.textContent!;
    // Shown only on a phone with a view open (the folder column, with its own Back, is hidden there).
    expect(css).toContain(`#${PHONE_BACK}{display:none!important}`);
    expect(css).toContain(`html[${VIEW_OPEN}] #${PHONE_BACK}{display:inline-flex!important`);
    unbind();
    expect(doc.getElementById(PHONE_BACK)).toBeNull();
  });

  it("the folder column's title is the folders' sort as OF sent it, on the Vault page and in every composer's vault dialog", () => {
    for (const page of ["vault/index", "new-post/state-vault", "home/state-vault", "messages/chat/state-vault"]) {
      const doc = load(page);
      const title = () => doc.querySelector(".l-sidebar-column .b-content-filter__title")!.textContent!.trim();
      expect(title(), page).toBe("custom"); // the capture's
      applyData(doc, page, { vaultLists: LISTS.list, vaultAll: LISTS.all, vaultSort: LISTS.sort, chat: "1" });
      expect(title(), page).toBe("Recent"); // vault-lists.json: OF's sort "recent"
      for (const [sort, label] of Object.entries(LIST_SORTS)) {
        applyData(doc, page, { vaultLists: LISTS.list, vaultAll: LISTS.all, vaultSort: sort, chat: "1" });
        expect(title(), page).toBe(label);
      }
    }
  });

  it("the folder column's Search opens OF's search form in its header; a search is ?slist=, its Back drops it", () => {
    const doc = load("vault/index");
    const ctx = ctxOf(`list=${AID}`);
    const unbind = bind(doc, "vault/index", ctx);
    const header = doc.querySelector(".l-sidebar-column .g-page__header")!;
    const opener = header.querySelector("button[type='button'][aria-label='Search']")!;
    expect([opener.hasAttribute("disabled"), opener.hasAttribute("data-oi-wired")]).toEqual([false, true]);
    const form = doc.getElementById(LISTS_SEARCH) as HTMLFormElement;
    expect(header.contains(form)).toBe(true);
    expect(header.classList.contains("m-search-form-visible")).toBe(false);
    click(opener);
    expect(header.classList.contains("m-search-form-visible")).toBe(true);
    const input = form.querySelector<HTMLInputElement>("input[name='vault_lists_search']")!;
    input.value = " fold ";
    form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    expect(ctx.navigate).toHaveBeenLastCalledWith(`/of-manager/vault?list=${AID}&slist=fold`);
    unbind();
    expect(doc.getElementById(LISTS_SEARCH)).toBeNull();
    // An open search: the form open with it, its Back to the view without it; a phone still shows the folders.
    bind(doc, "vault/index", ctxOf("slist=fold"));
    expect(header.classList.contains("m-search-form-visible")).toBe(true);
    expect((doc.getElementById(LISTS_SEARCH)!.querySelector("input") as HTMLInputElement).value).toBe("fold");
    expect(doc.getElementById(LISTS_SEARCH)!.querySelector("[at-attr='close_search']")!.getAttribute("href")).toBe("/of-manager/vault");
    expect(doc.documentElement.hasAttribute(VIEW_OPEN)).toBe(false);
  });

  it("a phone, as OF's: an open view shows the media alone; the bare Vault the folders, then the grid, nothing stuck over it", () => {
    const doc = load("vault/index");
    const css = () => doc.head.querySelector("style:last-of-type")!.textContent!;
    let unbind = bind(doc, "vault/index", ctxOf(`list=${AID}`));
    expect(doc.documentElement.hasAttribute(VIEW_OPEN)).toBe(true);
    expect(css()).toContain("@media (max-width: 1003.98px)");
    expect(css()).toContain(`html[${VIEW_OPEN}] .l-sidebar-column.m-l-side{display:none!important}`); // over OF's d-flex
    expect(css()).toContain(".l-sidebar-column.m-l-side.m-sticky-column{position:static!important}");
    unbind();
    expect(doc.documentElement.hasAttribute(VIEW_OPEN)).toBe(false);
    unbind = bind(doc, "vault/index", ctxOf("type=video"));
    expect(doc.documentElement.hasAttribute(VIEW_OPEN)).toBe(true);
    unbind();
    bind(doc, "vault/index", ctxOf(""));
    expect(doc.documentElement.hasAttribute(VIEW_OPEN)).toBe(false);
    // Every Vault page: its State pages' Search opens the form too.
    const state = load("vault/state-lists-sort-dropdown");
    bind(state, "vault/state-lists-sort-dropdown", ctxOf(""));
    click(state.querySelector(".l-sidebar-column .g-page__header button[type='button'][aria-label='Search']")!);
    expect(state.querySelector(".l-sidebar-column .g-page__header")!.classList.contains("m-search-form-visible")).toBe(true);
  });

  it("marks the view's tab and the sort title; a tab click navigates with its type", () => {
    const doc = load("vault/index");
    const ctx = ctxOf("type=photo&field=most-liked");
    bind(doc, "vault/index", ctx);
    const tabs = [...doc.querySelectorAll(".l-main-content.m-r-side .b-tabs__nav__link")];
    expect(tabs.map((t) => t.classList.contains("m-current"))).toEqual([false, true, false, false, false]);
    expect(doc.querySelector(".l-main-content.m-r-side .b-content-filter__title")!.textContent).toBe("Most liked");
    click(tabs[3]);
    expect(ctx.navigate).toHaveBeenCalledWith("/of-manager/vault?type=video&field=most-liked");
  });
  it("Search media opens OF's search form and says so on itself; Back closes it", () => {
    const doc = load("vault/index");
    bind(doc, "vault/index", ctxOf(""));
    const opener = doc.querySelector(".l-main-content.m-r-side button[aria-label='Search media']")!;
    const header = doc.querySelector("input[name='media_vault_search']")!.closest(".g-page__header")!;
    click(opener);
    expect([header.classList.contains("m-search-form-visible"), opener.getAttribute("aria-expanded")]).toEqual([true, "true"]);
    click(doc.querySelector(".l-main-content.m-r-side [at-attr='close_search']")!);
    expect([header.classList.contains("m-search-form-visible"), opener.getAttribute("aria-expanded")]).toEqual([false, "false"]);
  });
});

describe("the sort dropdowns", () => {
  it("media sort: each pick links to the view with it; the view's are checked", () => {
    const doc = load("vault/state-sort-dropdown");
    bind(doc, "vault/state-sort-dropdown", ctxOf("list=7&field=buyers&sort=asc", { handlers: null }));
    const items = [...doc.querySelectorAll(".of-state-menu .v-list-item")].filter((i) => i.querySelector("[name='vault-filter-field'], [name='ascending-field']"));
    const rows = items.map((i) => [i.querySelector<HTMLInputElement>("input")!.value, i.querySelector("a")!.getAttribute("href"), i.querySelector<HTMLInputElement>("input")!.checked]);
    expect(rows).toEqual([
      ["recent", "/of-manager/vault?list=7&sort=asc", false],
      ["most-liked", "/of-manager/vault?list=7&field=most-liked&sort=asc", false],
      ["highest-tips", "/of-manager/vault?list=7&field=highest-tips&sort=asc", false],
      ["buyers", "/of-manager/vault?list=7&field=buyers&sort=asc", true],
      ["asc", "/of-manager/vault?list=7&field=buyers&sort=asc", true],
      ["desc", "/of-manager/vault?list=7&field=buyers", false],
    ]);
  });

  it("folder sort: OF's sort and order are checked; a pick sends it with the order and navigates back", async () => {
    const doc = load("vault/state-lists-sort-dropdown");
    const ctx = ctxOf(`list=${AID}`);
    bind(doc, "vault/state-lists-sort-dropdown", ctx);
    const radio = (v: string) => [...doc.querySelectorAll<HTMLInputElement>(".of-state-menu input[type='radio']")].find((r) => r.value === v)!;
    expect([LISTS.sort, LISTS.order]).toEqual(["recent", "desc"]); // as OF sent them
    expect(["recent", "name", "asc", "desc"].map((v) => radio(v).checked)).toEqual([true, false, false, true]);
    expect(radio("asc").closest(".v-list-item")!.classList.contains("v-list-item--disabled")).toBe(false);
    expect(["default", "name", "recent", "media", "custom", "asc", "desc"].every((v) => radio(v).closest(".v-list-item")!.hasAttribute("data-oi-wired"))).toBe(true);
    click(radio("media").closest(".v-list-item")!.querySelector("a")!);
    await flush();
    expect(ctx.handlers!.sortFolders).toHaveBeenCalledWith("media", "desc");
    expect(ctx.navigate).toHaveBeenCalledWith(`/of-manager/vault?list=${AID}`);
    click(radio("asc").closest(".v-list-item")!);
    expect(ctx.handlers!.sortFolders).toHaveBeenLastCalledWith("recent", "asc");
  });

  it("folder sort: each pick sends its sort with OF's order, or its order with OF's sort", async () => {
    const doc = load("vault/state-lists-sort-dropdown");
    const ctx = ctxOf("");
    bind(doc, "vault/state-lists-sort-dropdown", ctx);
    const sent: unknown[] = [];
    for (const radio of doc.querySelectorAll<HTMLInputElement>(".of-state-menu input[type='radio']")) {
      click(radio.closest(".v-list-item")!);
      await flush();
      sent.push((ctx.handlers!.sortFolders as ReturnType<typeof vi.fn>).mock.lastCall);
    }
    expect(sent).toEqual([
      ["default", "desc"],
      ["name", "desc"],
      ["recent", "desc"],
      ["media", "desc"],
      ["custom", "desc"],
      ["recent", "asc"],
      ["recent", "desc"],
    ]);
  });

  it("the open folder sort menu's column goes over the backdrop (a sticky column is its own stacking context)", () => {
    for (const p of ["vault/index", "vault/state-lists-sort-dropdown"]) expect(capture(p)).toContain(".l-sidebar-column:has(.m-show-dropdown) { z-index: 2; }");
  });

  it("Go to date: All time links to the view without a date; Go to date opens a date picker from the model's first day to today", () => {
    const doc = load("vault/state-sort-dropdown");
    const ctx = ctxOf("list=7&date=2026-09-08", { minDate: "2020-11-24T00:00:00+00:00" });
    bind(doc, "vault/state-sort-dropdown", ctx);
    const item = (v: string) => doc.querySelector(`.of-state-menu input[name='vault-go-date-field'][value='${v}']`)!.closest(".v-list-item")!;
    const all = item("date_all_time");
    const go = item("");
    expect([all.querySelector("a")!.getAttribute("href"), all.querySelector<HTMLInputElement>("input")!.checked]).toEqual(["/of-manager/vault?list=7", false]);
    expect([go.querySelector("label")!.textContent, go.querySelector<HTMLInputElement>("input[type='radio']")!.checked, go.hasAttribute("data-oi-wired"), go.querySelector("a")]).toEqual(["2026-09-08", true, true, null]);
    // OF's day popup, on the view's day; the model's first day is the earliest, today the last.
    click(go);
    const popup = doc.querySelector<HTMLElement>("[data-oi-picker] .vdatetime-popup")!;
    expect(popup.querySelector(".vdatetime-popup__title")!.textContent!.trim()).toBe("Sep 8, 2026");
    expect(popup.querySelector(".vdatetime-popup__tabs")).toBeNull();
    popup.querySelector<HTMLElement>("[data-oi-day='2026-09-01']")!.click();
    doc.querySelector<HTMLButtonElement>("[data-oi-picker] [data-oi-picker-apply]")!.click();
    expect(ctx.navigate).toHaveBeenLastCalledWith("/of-manager/vault?list=7&date=2026-09-01");
    expect(doc.querySelector("[data-oi-picker]")).toBeNull();
    // No first day known: no lower bound; no date: "Go to date" and All time checked.
    const bare = load("vault/state-sort-dropdown");
    bind(bare, "vault/state-sort-dropdown", ctxOf(""));
    const g = bare.querySelector(".of-state-menu input[name='vault-go-date-field'][value='']")!.closest(".v-list-item")!;
    expect(g.querySelector("label")!.textContent!.trim()).toBe("Go to date");
    click(g);
    const months = bare.querySelector<HTMLButtonElement>("[data-oi-picker] [data-oi-month='prev']")!;
    expect(months.disabled).toBe(false);
    bare.querySelector<HTMLButtonElement>("[data-oi-picker] [data-oi-picker-close]")!.click();
    expect(bare.querySelector<HTMLInputElement>(".of-state-menu input[value='date_all_time']")!.checked).toBe(true);
  });

  it("folder sort: only the custom sort turns the order off (OF's orderDisabled); all models only say to pick one", () => {
    const doc = load("vault/state-lists-sort-dropdown");
    const item = (v: string) => doc.querySelector(`.of-state-menu input[value='${v}']`)!.closest(".v-list-item")!;
    bind(doc, "vault/state-lists-sort-dropdown", ctxOf("", { lists: { ...LISTS, sort: "custom" } }))();
    expect(item("asc").getAttribute("aria-disabled")).toBe("true");
    const ctx = ctxOf("", { lists: { ...LISTS, sort: "default" }, handlers: null });
    bind(doc, "vault/state-lists-sort-dropdown", ctx);
    expect(item("asc").getAttribute("aria-disabled")).toBe("false");
    click(item("name"));
    expect(noteText(doc)).toBe(SELECT_MODEL);
  });

  it("Customize order opens the folder column's custom order (keeping the view); off while a folder search is open", () => {
    const doc = load("vault/state-lists-sort-dropdown");
    const ctx = ctxOf(`list=${AID}`);
    const unbind = bind(doc, "vault/state-lists-sort-dropdown", ctx);
    const customize = () => [...doc.querySelectorAll(".of-state-menu .v-list-item")].find((i) => i.textContent!.trim() === "Customize order")!;
    expect([customize().hasAttribute("data-oi-wired"), customize().getAttribute("aria-disabled")]).toEqual([true, "false"]);
    click(customize());
    expect(ctx.navigate).toHaveBeenLastCalledWith(`/of-manager/vault?list=${AID}&customize=1`);
    unbind();
    const searching = ctxOf("slist=fold");
    bind(doc, "vault/state-lists-sort-dropdown", searching);
    expect(customize().getAttribute("aria-disabled")).toBe("true");
    click(customize());
    expect(searching.navigate).not.toHaveBeenCalled();
  });
});

describe("Customize order", () => {
  const setup = (over: Partial<VaultHandlers> = {}) => {
    const doc = load("vault/index");
    const ctx = ctxOf("customize=1", { customize: true, handlers: handlers(over) });
    applyData(doc, "vault/index", { vaultLists: LISTS.list, vaultAll: LISTS.all, vaultSort: LISTS.sort });
    const unbind = bind(doc, "vault/index", ctx);
    const box = doc.getElementById(ORDER_BOX)!;
    const order = () => [...box.querySelectorAll<HTMLElement>("[data-oi-order]")].map((r) => Number(r.dataset.oiOrder));
    const filter = doc.querySelector(".l-sidebar-column .b-content-filter")!;
    return { doc, ctx, unbind, box, order, filter, h: ctx.handlers! };
  };

  it("OF's mode: title Customize order, X and check; every folder with a drag handle, All media pinned and inert", () => {
    const { doc, box, order, filter } = setup();
    expect(doc.documentElement.hasAttribute(CUSTOMIZE)).toBe(true);
    const shown = [...filter.children].filter((c) => c.hasAttribute("data-oi-order-ui"));
    expect(shown.map((c) => c.textContent!.trim() || c.getAttribute("aria-label") || c.querySelector("button")!.getAttribute("aria-label"))).toEqual(["Cancel", "Customize order", "Save order"]);
    expect(order()).toEqual(LISTS.list!.map((l) => Number(l.id)));
    const first = box.firstElementChild!;
    expect(first.hasAttribute("data-oi-order")).toBe(false);
    expect(first.textContent).toContain("All media");
    expect(first.querySelector("[data-oi-drag]")).toBeNull();
    expect(box.querySelectorAll("a[href]")).toHaveLength(0); // no row navigates while ordering
    expect(box.querySelectorAll("[data-oi-order] [data-oi-drag] path")).toHaveLength(LISTS.list!.length);
  });

  it("the check sends the new order (OF's customOrder) and goes back; X goes back without it", async () => {
    const { doc, ctx, box, order, filter, h } = setup();
    const rows = [...box.querySelectorAll<HTMLElement>("[data-oi-order]")];
    box.insertBefore(rows[2], rows[0]); // as a drag leaves them
    const want = order();
    click(filter.querySelector("[aria-label='Save order']")!);
    await flush();
    expect(h.customOrder).toHaveBeenCalledWith(want);
    expect(want[0]).toBe(Number(LISTS.list![2].id));
    expect(ctx.navigate).toHaveBeenLastCalledWith("/of-manager/vault");
    click(filter.querySelector("[aria-label='Cancel']")!);
    expect(ctx.navigate).toHaveBeenCalledTimes(2);
    expect(h.customOrder).toHaveBeenCalledTimes(1);
    expect(noteText(doc)).toBeUndefined();
  });

  it("a drag by the handle moves the row over the one under the pointer", () => {
    const { doc, box, order } = setup();
    const rows = [...box.querySelectorAll<HTMLElement>("[data-oi-order]")];
    const [a, , c] = rows;
    // jsdom has no layout: the third row lies under the pointer, its top half below it.
    doc.elementFromPoint = () => c;
    c.getBoundingClientRect = () => ({ top: 0, height: 10 }) as DOMRect;
    const handle = a.querySelector("[data-oi-drag]")!;
    handle.dispatchEvent(new MouseEvent("pointerdown", { bubbles: true, cancelable: true }));
    handle.dispatchEvent(new MouseEvent("pointermove", { bubbles: true, clientY: 9 }));
    handle.dispatchEvent(new MouseEvent("pointerup", { bubbles: true }));
    expect(order().slice(0, 3)).toEqual([rows[1], c, a].map((r) => Number(r.dataset.oiOrder)));
  });

  it("a failed save is said and the check comes back; unbind puts the column back", async () => {
    const { doc, filter, unbind, h } = setup({ customOrder: vi.fn(async () => Promise.reject(new Error("OF said no"))) });
    const save = filter.querySelector<HTMLButtonElement>("[aria-label='Save order']")!;
    click(save);
    await flush();
    await flush();
    expect(h.customOrder).toHaveBeenCalledTimes(1);
    expect([noteText(doc), save.disabled]).toEqual(["Could not save the order: OF said no", false]);
    unbind();
    expect([doc.getElementById(ORDER_BOX), doc.documentElement.hasAttribute(CUSTOMIZE), filter.querySelector("[data-oi-order-ui]")]).toEqual([null, false, null]);
  });

  it("no mode without a model, or while a folder search is open", () => {
    const doc = load("vault/index");
    bind(doc, "vault/index", ctxOf("customize=1", { customize: true, handlers: null }))();
    expect(doc.getElementById(ORDER_BOX)).toBeNull();
    bind(doc, "vault/index", ctxOf("customize=1&slist=fold", { customize: true }));
    expect(doc.getElementById(ORDER_BOX)).toBeNull();
  });
});

describe("the folder form", () => {
  const form = (doc: Document) => ({
    input: doc.querySelector<HTMLInputElement>(".modal input[at-attr='input']")!,
    save: doc.querySelector<HTMLButtonElement>(".modal-footer button[type='submit']")!,
  });
  const type = (input: HTMLInputElement, text: string) => {
    input.value = text;
    input.dispatchEvent(new Event("input", { bubbles: true }));
  };
  const submit = (input: HTMLInputElement) => input.form!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));

  it("Create: Save is on with a name, creates the folder and opens it", async () => {
    const doc = load("vault/state-add-list");
    const ctx = ctxOf("");
    bind(doc, "vault/state-add-list", ctx);
    const { input, save } = form(doc);
    expect(input.hasAttribute("data-oi-wired") && save.hasAttribute("data-oi-wired")).toBe(true);
    type(input, "  ");
    expect(save.disabled).toBe(true);
    type(input, "Beach");
    expect(save.disabled).toBe(false);
    expect(input.closest(".v-input")!.querySelector(".v-counter")!.textContent).toMatch(/^5 \//);
    submit(input);
    await flush();
    expect(ctx.handlers!.createFolder).toHaveBeenCalledWith("Beach");
    expect(ctx.navigate).toHaveBeenCalledWith("/of-manager/vault?list=12");
  });

  it("?edit=1 in a custom folder renames it; an error is said and Save comes back", async () => {
    const doc = load("vault/state-add-list");
    const ctx = ctxOf(`list=${AID}&edit=1`, { handlers: handlers({ renameFolder: vi.fn(async () => Promise.reject(new Error("boom"))) }) });
    bind(doc, "vault/state-add-list", ctx);
    const { input, save } = form(doc);
    expect(input.value).toBe(A.name);
    expect(doc.querySelector(".modal-title")!.textContent!.trim()).toBe("Rename category");
    type(input, "Folder 7");
    submit(input);
    await flush();
    expect(ctx.handlers!.renameFolder).toHaveBeenCalledWith(AID, "Folder 7");
    expect(ctx.navigate).not.toHaveBeenCalled();
    expect(noteText(doc)).toBe("Could not rename: boom");
    expect(save.disabled).toBe(false);
  });
});

describe("the action row", () => {
  const setup = (params: string, over: Partial<VaultHandlers> = {}) => {
    const doc = load("vault/index");
    const ctx = ctxOf(params, { handlers: handlers(over) });
    applyData(doc, "vault/index", { vaultLists: LISTS.list, vaultMedia: MEDIA, list: ctx.view.list });
    bind(doc, "vault/index", ctx);
    const bar = doc.getElementById(BAR)!;
    const tiles = [...doc.querySelectorAll<HTMLElement>(".l-main-content.m-r-side [data-oi-media]")].filter(visible);
    const btn = (act: string) => bar.querySelector<HTMLElement>(`[data-oi-act='${act}']`);
    return { doc, ctx, bar, tiles, btn, h: ctx.handlers! };
  };

  it("all media: Upload only; a tile's checkbox selects it, then add to a folder", async () => {
    const { bar, tiles, btn, h } = setup("");
    expect([...bar.querySelectorAll("[data-oi-act]")].map((b) => (b as HTMLElement).dataset.oiAct)).toEqual(["upload"]);
    check(tiles[0]);
    click(tiles[2]); // while one is selected, a click anywhere on a tile selects it (OF's selection mode)
    expect(bar.textContent).toContain("2 selected");
    expect(btn("remove")).toBeNull();
    const pick = bar.querySelector<HTMLSelectElement>("select[data-oi-act='add']")!;
    // OF's custom folders only (no built-in one takes media).
    expect([...pick.options].map((o) => o.text)).toEqual(["Add to folder…", ...CUSTOM.map((l) => l.name)]);
    pick.value = BID;
    pick.dispatchEvent(new Event("change", { bubbles: true }));
    await flush();
    expect(h.addToFolder).toHaveBeenCalledWith(BID, [IDS[0], IDS[2]]);
    expect(tiles.some((t) => t.classList.contains("selected"))).toBe(false);
  });

  it("a custom folder: move (add, then remove), remove from folder", async () => {
    const { bar, tiles, btn, h } = setup(`list=${AID}`);
    expect(btn("rename") && btn("delete")).toBeTruthy();
    check(tiles[1]);
    const pick = bar.querySelector<HTMLSelectElement>("select[data-oi-act='move']")!;
    expect([...pick.options].map((o) => o.value)).toEqual(["", ...CUSTOM.filter((l) => l !== A).map((l) => String(l.id))]);
    pick.value = BID;
    pick.dispatchEvent(new Event("change", { bubbles: true }));
    await flush();
    expect(h.addToFolder).toHaveBeenCalledWith(BID, [IDS[1]]);
    expect(h.removeFromFolder).toHaveBeenCalledWith(AID, [IDS[1]]);
    check(tiles[0]);
    click(btn("remove")!);
    await flush();
    expect(h.removeFromFolder).toHaveBeenLastCalledWith(AID, [IDS[0]]);
  });

  it("remove from vault and delete folder are confirmed: a no sends nothing", async () => {
    const no = setup(`list=${AID}`, { confirm: vi.fn(() => false) });
    check(no.tiles[0]);
    click(no.btn("hide")!);
    click(no.btn("clear")!);
    click(no.btn("delete")!);
    await flush();
    expect(no.h.confirm).toHaveBeenCalledTimes(2);
    expect(no.h.hide).not.toHaveBeenCalled();
    expect(no.h.deleteFolder).not.toHaveBeenCalled();
  });

  it("remove from vault and delete folder: a yes sends them", async () => {
    const yes = setup(`list=${AID}`);
    check(yes.tiles[0]);
    click(yes.btn("hide")!);
    await flush();
    expect(yes.h.hide).toHaveBeenCalledWith([IDS[0]]);
    click(yes.btn("delete")!);
    await flush();
    expect(yes.h.deleteFolder).toHaveBeenCalledWith(AID);
    expect(yes.ctx.navigate).toHaveBeenCalledWith("/of-manager/vault");
  });

  it("one selected tile: Edit tags shows its tags; Save writes them and the row comes back", async () => {
    const { bar, tiles, btn, h } = setup("");
    check(tiles[0]);
    check(tiles[1]);
    expect(btn("tags")).toBeNull(); // one media at a time
    check(tiles[0]);
    click(btn("tags")!);
    const input = bar.querySelector<HTMLInputElement>("input[name='oi-vault-tags']")!;
    expect(input.disabled).toBe(true);
    await flush();
    expect(h.tags).toHaveBeenCalledWith(IDS[1]);
    expect([input.value, input.disabled, btn("tags-save")!.hasAttribute("disabled")]).toEqual(["beach, red", false, false]);
    input.value = "beach, , sunset ";
    input.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter" }));
    await flush();
    expect(h.saveTags).toHaveBeenCalledWith(IDS[1], ["beach", "sunset"]);
    expect(noteText(bar.ownerDocument)).toBe("Tags saved");
    expect(bar.querySelector("input[name='oi-vault-tags']")).toBeNull();
    expect(btn("tags")).not.toBeNull();
  });

  it("Edit tags: a media missing from the Relay's copy cannot be saved; Cancel closes the editor", async () => {
    const { bar, tiles, btn, h, doc } = setup("", { tags: vi.fn(async () => null) });
    check(tiles[2]);
    click(btn("tags")!);
    await flush();
    expect(noteText(doc)).toMatch(/^Not in Inflowwww's vault copy yet/);
    expect(btn("tags-save")!.hasAttribute("disabled")).toBe(true);
    click(btn("tags-cancel")!);
    expect(bar.querySelector("input[name='oi-vault-tags']")).toBeNull();
    expect(h.saveTags).not.toHaveBeenCalled();
  });

  it("a tile click opens its media in the viewer through /img: a photo, a video's player, a GIF looping, an audio's player", () => {
    const doc = load("vault/index");
    const one = (kind: string) => fixture<{ list: VaultMedia[] }>(`media-${kind}`).list[0];
    const media = [one("photo"), one("video"), one("gif"), one("audio")];
    const img = (u: string) => `/img?u=${encodeURIComponent(u)}&account_id=1`;
    applyData(doc, "vault/index", { vaultLists: LISTS.list, vaultMedia: media }, img);
    bind(doc, "vault/index", ctxOf(""));
    const tiles = [...doc.querySelectorAll<HTMLElement>(".l-main-content.m-r-side [data-oi-media]")].filter(visible);
    const open = (i: number) => {
      click(tiles[i]);
      const el = doc.getElementById(VIEWER)!.querySelector<HTMLMediaElement>("img, video, audio")!;
      return [el.tagName, el.getAttribute("src"), el.controls, el.loop];
    };
    expect(open(0)).toEqual(["IMG", img(media[0].files!.full!.url!), undefined, undefined]);
    click(doc.querySelector(`#${VIEWER} button[aria-label='Close']`)!);
    expect(doc.getElementById(VIEWER)).toBeNull();
    expect(open(1)).toEqual(["VIDEO", img(media[1].videoSources!["720"]!), true, false]);
    doc.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
    expect(doc.getElementById(VIEWER)).toBeNull();
    expect(open(2)).toEqual(["VIDEO", img(media[2].files!.full!.url!), false, true]);
    click(doc.getElementById(VIEWER)!); // its backdrop
    expect(open(3)).toEqual(["AUDIO", img(media[3].files!.full!.url!), true, false]);
    expect(tiles.some((t) => t.classList.contains("selected"))).toBe(false); // a view selects nothing
    expect(doc.querySelectorAll(`#${VIEWER}`)).toHaveLength(1);
  });

  it("the viewer steps through the folder's loaded tiles with ← / → and its buttons, stops at either end; Escape closes", () => {
    const doc = load("vault/index");
    const one = (kind: string) => fixture<{ list: VaultMedia[] }>(`media-${kind}`).list[0];
    const media = [one("photo"), one("video"), one("gif")];
    const img = (u: string) => `/img?u=${encodeURIComponent(u)}`;
    applyData(doc, "vault/index", { vaultLists: LISTS.list, vaultMedia: media }, img);
    bind(doc, "vault/index", ctxOf(""));
    const tiles = [...doc.querySelectorAll<HTMLElement>(".l-main-content.m-r-side [data-oi-media]")].filter(visible);
    const shown = () => doc.getElementById(VIEWER)!.querySelector("img, video, audio")!.getAttribute("src");
    const key = (k: string) => doc.dispatchEvent(new KeyboardEvent("keydown", { key: k, cancelable: true }));
    const btn = (label: string) => doc.querySelector<HTMLButtonElement>(`#${VIEWER} button[aria-label='${label}']`)!;
    click(tiles[1]);
    expect(shown()).toBe(img(media[1].videoSources!["720"]!));
    key("ArrowRight");
    expect(shown()).toBe(img(media[2].files!.full!.url!));
    expect(btn("Next").disabled).toBe(true);
    key("ArrowRight"); // the last: stays
    expect(shown()).toBe(img(media[2].files!.full!.url!));
    key("ArrowLeft");
    key("ArrowLeft");
    expect(shown()).toBe(img(media[0].files!.full!.url!));
    expect(btn("Previous").disabled).toBe(true);
    click(btn("Next"));
    expect(shown()).toBe(img(media[1].videoSources!["720"]!));
    expect(doc.querySelectorAll(`#${VIEWER} img, #${VIEWER} video`)).toHaveLength(1);
    key("Escape");
    expect(doc.getElementById(VIEWER)).toBeNull();
    key("ArrowLeft"); // no viewer: nothing
    expect(doc.getElementById(VIEWER)).toBeNull();
  });

  it("all models: no action row", () => {
    const doc = load("vault/index");
    bind(doc, "vault/index", ctxOf("", { handlers: null }));
    expect(doc.getElementById(BAR)).toBeNull();
  });

  it("unbind removes the row", () => {
    const doc = load("vault/index");
    const unbind = bind(doc, "vault/index", ctxOf(""));
    expect(doc.getElementById(BAR)).not.toBeNull();
    unbind();
    expect(doc.getElementById(BAR)).toBeNull();
  });
});

describe("pollUpload", () => {
  afterEach(() => vi.useRealTimers());

  it("returns the first status that is no longer running", async () => {
    const status = vi.fn().mockResolvedValueOnce({ running: true }).mockResolvedValueOnce({ running: false, status: "done" });
    await expect(pollUpload(status, 1, 1000)).resolves.toEqual({ running: false, status: "done" });
    expect(status).toHaveBeenCalledTimes(2);
  });

  it("gives up after the timeout, so the action bar comes back", async () => {
    vi.useFakeTimers();
    const status = vi.fn(async () => ({ running: true }));
    const out = pollUpload(status, 2000, 10_000);
    const done = expect(out).rejects.toThrow(/still importing/);
    await vi.advanceTimersByTimeAsync(12_000);
    await done;
    expect(status.mock.calls.length).toBeLessThanOrEqual(5);
  });
});
