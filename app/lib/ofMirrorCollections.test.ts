import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import { applyData } from "./ofMirrorData";
import { ADD_TO_LIST, bindCollections as bindC, CARD_TOOL, CREATE_LIST, DIALOG, labelsPage, LIST_MORE, listsPage, openListPage, USERS_SEARCH, USERS_SEARCH_ID, usernames, type CollectionList, type CollectionsHandlers } from "./ofMirrorCollections";
import { bindWrites as bindW, NOT_YET, SELECT_MODEL } from "./ofMirrorWrites";
import type { ChatToolWrites, FanState, FanToolsContext } from "./ofMirrorChatTools";

const capture = (p: string) => readFileSync(resolve(__dirname, `../public/of-mirror/pages/${p}.html`), "utf8");
const load = (p: string) => {
  document.documentElement.innerHTML = capture(p);
  return document;
};
const noteText = (doc: Document) => doc.getElementById("oi-note")?.textContent ?? null;
const items = (doc: Document) => [...doc.querySelectorAll<HTMLElement>("[data-oi-menu] [role=menuitem], [data-oi-menu] hr")].map((e) => e.textContent || "—");
const flush = () => new Promise((r) => setTimeout(r, 0));
// Every test reuses the one document: its binders are unbound after it.
const unbinds: (() => void)[] = [];
afterEach(() => unbinds.splice(0).forEach((u) => u()));
const bindCollections = (...a: Parameters<typeof bindC>) => {
  const u = bindC(...a);
  unbinds.push(u);
  return u;
};
const bindWrites = (...a: Parameters<typeof bindW>) => {
  const u = bindW(...a);
  unbinds.push(u);
  return u;
};

const LISTS: CollectionList[] = [
  { id: 31, name: "Whales", canUpdate: true, canDelete: true, canAddUsers: true, canManageUsers: true },
  { id: 32, name: "Regulars", canUpdate: true, canDelete: true, canAddUsers: true, canManageUsers: true },
  { id: "fans", name: "Fans", canAddUsers: false },
];
const PEOPLE = [
  { id: 201, name: "Delta Four", username: "delta" },
  { id: 202, name: "Echo Five", username: "echo" },
];

function handlers(over: Partial<CollectionsHandlers> = {}) {
  return {
    createList: vi.fn(() => Promise.resolve({ id: 40 })),
    createLabel: vi.fn(() => Promise.resolve({ id: 7 })),
    renameList: vi.fn(() => Promise.resolve({})),
    addUsers: vi.fn((_id: string, names: string[]) => Promise.resolve(names.length)),
    clearList: vi.fn(() => Promise.resolve({})),
    deleteList: vi.fn(() => Promise.resolve({})),
    addUser: vi.fn(() => Promise.resolve({})),
    removeUser: vi.fn(() => Promise.resolve({})),
    cardFans: vi.fn(() => Promise.resolve({} as Record<string, FanState>)),
    cardContext: vi.fn((uid: string) => Promise.resolve(cardCtx(uid))),
    navigate: vi.fn(),
    ...over,
  };
}

// The cards' fans as /users/list sends them: 201 a restricted subscriber with a note, 202 never subscribed.
const FANS: Record<string, FanState> = {
  "201": { id: 201, username: "delta", subscribedOn: true, isRestricted: true, canRestrict: true, notice: "vip", displayName: "Delta" },
  "202": { id: 202, username: "echo", subscribedOn: false, canRestrict: true, isRestricted: false },
};
const cardWrites = (): ChatToolWrites & Record<string, ReturnType<typeof vi.fn>> =>
  ({
    rename: vi.fn(() => Promise.resolve({})),
    note: vi.fn(() => Promise.resolve({})),
    list: vi.fn(() => Promise.resolve({})),
    discount: vi.fn(() => Promise.resolve({})),
    restrict: vi.fn(() => Promise.resolve({})),
    block: vi.fn(() => Promise.resolve({})),
  }) as never;
let lastWrites = cardWrites();
const cardCtx = (uid: string): FanToolsContext => ({
  chat: uid,
  fan: FANS[uid],
  me: { subscribePrice: 10 },
  writes: (lastWrites = cardWrites()),
});

/** `page` (the list page, or Collections) for list 31 with its real cards, bound as OfMirrorFrame binds it (bindWrites too). */
function listPage(h: CollectionsHandlers | null, lists: CollectionList[] = LISTS, page = "collections/user-lists/list") {
  const doc = load(page);
  applyData(doc, page, { list: "31", userLists: lists, listUsers: PEOPLE });
  bindWrites(doc, page, null);
  bindCollections(doc, page, { lists, list: "31" }, h);
  return { doc };
}

const dialog = (doc: Document) => doc.querySelector<HTMLElement>(DIALOG);
const field = (doc: Document) => dialog(doc)!.querySelector<HTMLInputElement>("input")!;
const save = (doc: Document) => dialog(doc)!.querySelector<HTMLButtonElement>("button[type=submit]")!;

/** Type `text` into the open dialog's field (as a user does: an input event) and press Save. */
function submit(doc: Document, text: string) {
  const input = field(doc);
  input.value = text;
  input.dispatchEvent(new Event("input", { bubbles: true }));
  input.form!.requestSubmit();
}

const pick = (doc: Document, label: string) => {
  doc.querySelector<HTMLButtonElement>(LIST_MORE)!.click();
  [...doc.querySelectorAll<HTMLElement>("[role=menuitem]")].find((b) => b.textContent === label)!.click();
};

describe("helpers", () => {
  it("the header + makes a user list on the user-list pages, a label on Post Labels", () => {
    expect(["collections/index", "collections/user-lists/list", "collections/user-lists/subscriptions/active"].map(listsPage)).toEqual([true, true, true]);
    expect(["collections/bookmarks/all", "collections/post-labels/archived", "vault/index"].map(listsPage)).toEqual([false, false, false]);
    expect(["collections/post-labels/archived", "collections/bookmarks/all"].map(labelsPage)).toEqual([true, false]);
  });
  it("a list is open on the collections page, the list page and its Posts tab", () => {
    expect(["collections/index", "collections/user-lists/list", "collections/user-lists/list/posts", "collections/user-lists/subscriptions"].map(openListPage)).toEqual([true, true, true, false]);
  });
  it("usernames: without @, split on commas and spaces, once each", () => {
    expect(usernames(" @alpha, beta  @gamma,@alpha ")).toEqual(["alpha", "beta", "gamma"]);
    expect(usernames(" , ")).toEqual([]);
  });
});

describe("Create new list", () => {
  it("opens OF's dialog; Save (off until a name is typed) sends the trimmed name and notes it", async () => {
    const doc = load("collections/index");
    const h = handlers();
    const unbind = bindCollections(doc, "collections/index", { lists: null, list: null }, h);
    const plus = doc.querySelector<HTMLButtonElement>(CREATE_LIST)!;
    expect(plus.hasAttribute("data-oi-wired")).toBe(true);
    plus.click();
    const d = dialog(doc)!;
    expect(d.querySelector(".modal.b-modal__custom-list .modal-title")!.textContent!.trim()).toBe("Create new list");
    expect(d.querySelector(".v-label")!.textContent).toBe("List name");
    expect(d.querySelector(".v-counter")!.textContent).toBe("0 / 64");
    expect(save(doc).disabled).toBe(true);
    expect(field(doc).maxLength).toBe(64);
    submit(doc, "  Big spenders ");
    expect(d.querySelector(".v-counter")!.textContent).toBe("15 / 64");
    expect(h.createList).toHaveBeenCalledWith("Big spenders");
    await flush();
    expect(dialog(doc)).toBeNull();
    expect(noteText(doc)).toBe("List created");
    unbind();
    expect(plus.hasAttribute("data-oi-wired")).toBe(false);
  });

  it("a blank name sends nothing; a relay error keeps the dialog and shows it under the field", async () => {
    const doc = load("collections/index");
    const h = handlers({ createList: vi.fn(() => Promise.reject(new Error("Name taken"))) });
    bindCollections(doc, "collections/index", { lists: null, list: null }, h);
    doc.querySelector<HTMLButtonElement>(CREATE_LIST)!.click();
    submit(doc, "   ");
    expect(save(doc).disabled).toBe(true);
    expect(h.createList).not.toHaveBeenCalled();
    submit(doc, "Dupe");
    await flush();
    expect(dialog(doc)!.querySelector(".v-messages__message")!.textContent).toBe("Could not save: Name taken");
    expect(save(doc).disabled).toBe(false);
  });

  it("Cancel, Escape and the backdrop close it", () => {
    const doc = load("collections/index");
    bindCollections(doc, "collections/index", { lists: null, list: null }, handlers());
    const plus = doc.querySelector<HTMLButtonElement>(CREATE_LIST)!;
    plus.click();
    dialog(doc)!.querySelector<HTMLElement>(".modal-footer a")!.click();
    expect(dialog(doc)).toBeNull();
    plus.click();
    doc.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
    expect(dialog(doc)).toBeNull();
    plus.click();
    dialog(doc)!.querySelector<HTMLElement>(".modal")!.click();
    expect(dialog(doc)).toBeNull();
  });

  it("all models: Select a model, no dialog, no Read-only note", () => {
    const doc = load("collections/index");
    bindWrites(doc, "collections/index", null);
    bindCollections(doc, "collections/index", { lists: null, list: null }, null);
    doc.querySelector<HTMLButtonElement>(CREATE_LIST)!.click();
    expect(noteText(doc)).toBe(SELECT_MODEL);
    expect(dialog(doc)).toBeNull();
  });

  it("on Bookmarks it is disabled (OF's + makes a bookmark folder there, which the relay cannot)", () => {
    const doc = load("collections/bookmarks/all");
    bindCollections(doc, "collections/bookmarks/all", { lists: null, list: null }, handlers());
    const plus = doc.querySelector<HTMLButtonElement>(CREATE_LIST)!;
    expect(plus.disabled).toBe(true);
    expect(plus.title).toBe(NOT_YET);
  });

  it("on Post Labels it is Create new label", async () => {
    const doc = load("collections/post-labels/archived");
    const h = handlers();
    bindCollections(doc, "collections/post-labels/archived", { lists: null, list: null }, h);
    doc.querySelector<HTMLButtonElement>(CREATE_LIST)!.click();
    expect(dialog(doc)!.querySelector(".modal-title")!.textContent!.trim()).toBe("Create new label");
    submit(doc, "Beach");
    expect(h.createLabel).toHaveBeenCalledWith("Beach");
    expect(h.createList).not.toHaveBeenCalled();
    await flush();
    expect(noteText(doc)).toBe("Label created");
  });
});

describe("a real list's More", () => {
  it("lists OF's items by the list's flags", () => {
    const { doc } = listPage(handlers());
    const more = doc.querySelector<HTMLButtonElement>(LIST_MORE)!;
    expect(more.hasAttribute("data-oi-wired")).toBe(true);
    more.click();
    expect(items(doc)).toEqual(["Rename list", "Add users", "—", "Clear list", "Delete list"]);
    expect(more.closest(".b-dropdown-wrapper")!.classList.contains("m-show-dropdown")).toBe(true);
    more.click();
    expect(items(doc)).toEqual([]);
  });

  it("a list that only takes users: Add users alone", () => {
    const ro = listPage(handlers(), [{ id: 31, name: "Whales", canAddUsers: true }]).doc;
    ro.querySelector<HTMLButtonElement>(LIST_MORE)!.click();
    expect(items(ro)).toEqual(["Add users"]);
  });

  it("no flags: OF shows no menu, so More is disabled; the unbind gives it back", () => {
    const doc = load("collections/user-lists/list");
    applyData(doc, "collections/user-lists/list", { list: "31", userLists: [{ id: 31, name: "Whales" }], listUsers: PEOPLE });
    const unbind = bindC(doc, "collections/user-lists/list", { lists: [{ id: 31, name: "Whales" }], list: "31" }, handlers());
    const more = doc.querySelector<HTMLButtonElement>(LIST_MORE)!;
    expect(more.hasAttribute("data-oi-wired")).toBe(false);
    expect([more.disabled, more.title]).toEqual([true, NOT_YET]);
    unbind();
    expect([more.disabled, more.hasAttribute("title")]).toEqual([false, false]);
  });

  it("Rename list: the dialog holds the name (Save off until it changes); Save sends the new one", async () => {
    const h = handlers();
    const { doc } = listPage(h);
    pick(doc, "Rename list");
    expect(dialog(doc)!.querySelector(".modal-title")!.textContent!.trim()).toBe("Rename list");
    expect(field(doc).value).toBe("Whales");
    expect(save(doc).disabled).toBe(true);
    submit(doc, "Big whales");
    expect(h.renameList).toHaveBeenCalledWith("31", "Big whales");
    await flush();
    expect(noteText(doc)).toBe("Saved");
  });

  it("Add users: the typed @usernames go to the bulk add", async () => {
    const h = handlers();
    const { doc } = listPage(h);
    pick(doc, "Add users");
    expect(field(doc).placeholder).toBe("@username, @username");
    submit(doc, "@alpha, beta");
    expect(h.addUsers).toHaveBeenCalledWith("31", ["alpha", "beta"]);
    await flush();
    expect(noteText(doc)).toBe("Added 2 users");
  });

  it("Clear list and Delete list ask first; No sends nothing", async () => {
    const h = handlers();
    const { doc } = listPage(h);
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    pick(doc, "Clear list");
    pick(doc, "Delete list");
    expect(confirm).toHaveBeenCalledTimes(2);
    expect(confirm.mock.calls[0][0]).toContain('"Whales"');
    expect(h.clearList).not.toHaveBeenCalled();
    expect(h.deleteList).not.toHaveBeenCalled();

    confirm.mockReturnValue(true);
    pick(doc, "Clear list");
    expect(h.clearList).toHaveBeenCalledWith("31");
    await flush();
    expect(noteText(doc)).toBe("List cleared");
    pick(doc, "Delete list");
    expect(h.deleteList).toHaveBeenCalledWith("31");
    await flush();
    expect(h.navigate).toHaveBeenCalledWith("/of-manager/collections");
    confirm.mockRestore();
  });

  it("all models (no lists): More is disabled", () => {
    const doc = load("collections/user-lists/list");
    bindCollections(doc, "collections/user-lists/list", { lists: null, list: null }, null);
    expect(doc.querySelector<HTMLButtonElement>(LIST_MORE)!.title).toBe(NOT_YET);
  });
});

describe("a real user card's Lists", () => {
  it("offers Remove from this list and Add to each other list that takes users", async () => {
    const h = handlers();
    const { doc } = listPage(h);
    const buttons = [...doc.querySelectorAll<HTMLButtonElement>(ADD_TO_LIST)];
    expect(buttons.length).toBeGreaterThan(0);
    expect(buttons.every((b) => b.hasAttribute("data-oi-wired") && !b.disabled)).toBe(true);
    const lists = doc.querySelector<HTMLButtonElement>(`[data-oi-user='202'] ${"button[at-attr='add_to_list']"}`)!;
    lists.click();
    expect(items(doc)).toEqual(["Remove from Whales", "Add to Regulars"]);
    [...doc.querySelectorAll<HTMLElement>("[role=menuitem]")][1].click();
    expect(h.addUser).toHaveBeenCalledWith("32", "202");
    await flush();
    expect(noteText(doc)).toBe("Added to Regulars");

    lists.click();
    [...doc.querySelectorAll<HTMLElement>("[role=menuitem]")][0].click();
    expect(h.removeUser).toHaveBeenCalledWith("31", "202");
    await flush();
    expect(noteText(doc)).toBe("Removed");
  });

  it("on Collections the first list's cards are wired the same", () => {
    const { doc } = listPage(handlers(), LISTS, "collections/index");
    doc.querySelector<HTMLButtonElement>(`[data-oi-user='201'] button[at-attr='add_to_list']`)!.click();
    expect(items(doc)).toEqual(["Remove from Whales", "Add to Regulars"]);
  });

  it("on Fans a card can be added to each list that takes users", () => {
    const page = "collections/user-lists/subscribers/active";
    const doc = load(page);
    applyData(doc, page, { userLists: LISTS, subscribers: PEOPLE });
    bindCollections(doc, page, { lists: LISTS, list: null }, handlers());
    doc.querySelector<HTMLButtonElement>(`[data-oi-user='201'] button[at-attr='add_to_list']`)!.click();
    expect(items(doc)).toEqual(["Add to Whales", "Add to Regulars"]);
  });

  it("a card cloned after binding is still wired at its click (never the Read-only note)", () => {
    const h = handlers();
    const doc = load("collections/user-lists/list");
    bindWrites(doc, "collections/user-lists/list", null);
    bindCollections(doc, "collections/user-lists/list", { lists: LISTS, list: "31" }, h);
    applyData(doc, "collections/user-lists/list", { list: "31", userLists: LISTS, listUsers: PEOPLE });
    doc.querySelector<HTMLButtonElement>(`[data-oi-user='201'] button[at-attr='add_to_list']`)!.click();
    expect(noteText(doc)).toBeNull();
    expect(items(doc)).toEqual(["Remove from Whales", "Add to Regulars"]);
  });

  it("nothing to do (a list without flags, no other list taking users): Lists is disabled, also on cards cloned later", async () => {
    const doc = load("collections/user-lists/list");
    const lists = [{ id: 31, name: "Fans" }];
    bindCollections(doc, "collections/user-lists/list", { lists, list: "31" }, handlers());
    applyData(doc, "collections/user-lists/list", { list: "31", userLists: lists, listUsers: PEOPLE });
    await flush(); // the MutationObserver's sweep
    const buttons = [...doc.querySelectorAll<HTMLButtonElement>(ADD_TO_LIST)];
    expect(buttons.length).toBeGreaterThan(0);
    expect(buttons.every((b) => b.disabled && b.title === NOT_YET)).toBe(true);
  });
});

describe("a real user card's chat tools", () => {
  const cardTool = (doc: Document, uid: string, name: string) => doc.querySelector<HTMLButtonElement>(`[data-oi-user='${uid}'] [data-oi-card-tool='${name}']`)!;
  const label = (el: Element) => el.querySelector(".b-tabs__nav__text")!.textContent!.trim();
  const modal = (doc: Document) => doc.querySelector<HTMLElement>(".modal.show[role='dialog']");
  afterEach(() => document.getElementById("oi-toast")?.remove());

  it("the pencil, Discount, Restrict and Add notes are wired (not disabled), labelled from the cards' fans read at once", async () => {
    const h = handlers({ cardFans: vi.fn(() => Promise.resolve(FANS)) });
    const { doc } = listPage(h);
    expect(h.cardFans).toHaveBeenCalledWith(["201", "202"]);
    await flush();
    const tools = [...doc.querySelectorAll<HTMLButtonElement>(CARD_TOOL)];
    expect(tools.map((b) => b.dataset.oiCardTool).slice(0, 4)).toEqual(["rename", "discount", "restrict", "notes"]);
    expect(tools.every((b) => !b.disabled && b.hasAttribute("data-oi-wired"))).toBe(true);
    expect([label(cardTool(doc, "201", "restrict")), label(cardTool(doc, "201", "notes"))]).toEqual(["Unrestrict", "Edit notes"]);
    expect(label(cardTool(doc, "202", "restrict"))).toBe("Restrict");
    // 202 never subscribed: OF offers no notes and no rename (the chat header's rules).
    expect([cardTool(doc, "202", "notes").style.display, cardTool(doc, "202", "rename").style.display]).toEqual(["none", "none"]);
  });

  it("Restrict reads the fan again and sends Restrict / Unrestrict by its state, OF's toast, then reads the cards again", async () => {
    const h = handlers({ cardFans: vi.fn(() => Promise.resolve(FANS)) });
    const { doc } = listPage(h);
    await flush();
    const before = vi.mocked(h.cardFans).mock.calls.length;
    cardTool(doc, "202", "restrict").click();
    expect(h.cardContext).toHaveBeenCalledWith("202");
    await flush();
    expect(lastWrites.restrict).toHaveBeenCalledWith(true);
    await flush();
    expect(doc.getElementById("oi-toast")!.textContent).toContain("User restricted");
    // The toast's sweep reads the cards' fans again (the write invalidated their cached query).
    expect(vi.mocked(h.cardFans).mock.calls.length).toBeGreaterThan(before);
    cardTool(doc, "201", "restrict").click();
    await flush();
    expect(lastWrites.restrict).toHaveBeenCalledWith(false);
  });

  it("Edit notes and the pencil open the chat's dialogs on the fan's own values; Save sends them", async () => {
    const { doc } = listPage(handlers());
    cardTool(doc, "201", "notes").click();
    await flush();
    expect(modal(doc)!.querySelector(".modal-title")!.textContent!.trim()).toBe("Edit notes");
    const area = modal(doc)!.querySelector<HTMLTextAreaElement>("textarea")!;
    expect(area.value).toBe("vip");
    area.value = "whale";
    [...modal(doc)!.querySelectorAll<HTMLButtonElement>("button")].find((b) => b.textContent!.trim() === "Save")!.click();
    expect(lastWrites.note).toHaveBeenCalledWith("whale");
    await flush();
    cardTool(doc, "201", "rename").click();
    await flush();
    expect(modal(doc)!.querySelector(".modal-title")!.textContent!.trim()).toBe("Rename user");
    expect(modal(doc)!.querySelector<HTMLInputElement>("input")!.value).toBe("Delta");
  });

  it("Discount opens OF's PERSONAL_OFFER dialog", async () => {
    const { doc } = listPage(handlers());
    cardTool(doc, "201", "discount").click();
    await flush();
    expect(modal(doc)!.querySelector(".modal-title")!.textContent!.trim()).toBe("Give user a discount");
  });

  it("a fan that cannot be read: the red note, no dialog", async () => {
    const { doc } = listPage(handlers({ cardContext: vi.fn(() => Promise.reject(new Error("502 Bad Gateway"))) }));
    cardTool(doc, "201", "notes").click();
    await flush();
    expect(noteText(doc)).toBe("Could not load this user: 502 Bad Gateway");
    expect(modal(doc)).toBeNull();
  });

  it("all models: Select a model, nothing read", () => {
    const { doc } = listPage(null);
    cardTool(doc, "201", "restrict").click();
    expect(noteText(doc)).toBe(SELECT_MODEL);
  });

  it("on Fans the cards' tools are wired too", () => {
    const page = "collections/user-lists/subscribers/active";
    const doc = load(page);
    applyData(doc, page, { userLists: LISTS, subscribers: PEOPLE });
    const h = handlers();
    bindCollections(doc, page, { lists: LISTS, list: null }, h);
    cardTool(doc, "202", "discount").click();
    expect(h.cardContext).toHaveBeenCalledWith("202");
  });
});

describe("Search users", () => {
  const row = (doc: Document) => doc.getElementById(USERS_SEARCH_ID);
  const type = (doc: Document, text: string, key = "Enter") => {
    const input = row(doc)!.querySelector<HTMLInputElement>("input")!;
    input.value = text;
    input.dispatchEvent(new KeyboardEvent("keydown", { key, bubbles: true }));
  };

  it("on a list page: opens a field under the users' header; Enter searches the open list (?query=)", () => {
    const h = handlers();
    const { doc } = listPage(h);
    const btn = doc.querySelector<HTMLButtonElement>(USERS_SEARCH)!;
    expect([btn.disabled, btn.hasAttribute("data-oi-wired")]).toEqual([false, true]);
    btn.click();
    expect(row(doc)!.previousElementSibling!.classList.contains("b-content-filter")).toBe(true);
    expect(btn.getAttribute("aria-expanded")).toBe("true");
    type(doc, "  alpha one ");
    expect(h.navigate).toHaveBeenCalledWith("/of-manager/collections/user-lists/list?list=31&query=alpha+one");
    btn.click();
    expect(row(doc)).toBeNull();
  });

  it("while searching it stays open on the query; Escape drops it", () => {
    const h = handlers();
    const page = "collections/index";
    const doc = load(page);
    applyData(doc, page, { list: "31", userLists: LISTS, listUsers: PEOPLE });
    bindCollections(doc, page, { lists: LISTS, list: "31", query: "alpha" }, h);
    expect(row(doc)!.querySelector("input")!.value).toBe("alpha");
    type(doc, "alpha", "Escape");
    expect(h.navigate).toHaveBeenCalledWith("/of-manager/collections?list=31");
    expect(row(doc)).toBeNull();
  });

  it("an empty Enter with no search closes it, sending nothing", () => {
    const h = handlers();
    const { doc } = listPage(h);
    doc.querySelector<HTMLButtonElement>(USERS_SEARCH)!.click();
    type(doc, "");
    expect(h.navigate).not.toHaveBeenCalled();
    expect(row(doc)).toBeNull();
  });

  it("all models: Select a model, no field", () => {
    const none = listPage(null).doc;
    none.querySelector<HTMLButtonElement>(USERS_SEARCH)!.click();
    expect(noteText(none)).toBe(SELECT_MODEL);
    expect(row(none)).toBeNull();
  });

  it("on Fans it stays disabled (no evidenced search there)", () => {
    const doc = load("collections/user-lists/subscribers/active");
    expect(doc.querySelector<HTMLButtonElement>(USERS_SEARCH)!.title).toBe(NOT_YET);
  });
});
