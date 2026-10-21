import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { QueryClient } from "@tanstack/react-query";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  bindChatList,
  chatsHref,
  chatsQuery,
  chatsRequest,
  chatsView,
  chatsWrites,
  CLEAR_CONFIRM,
  counter,
  listHref,
  SEARCH_MS,
  type ChatsContext,
  type ChatsMe,
  type ChatsView,
} from "./ofMirrorChats";
import { applyData, keepThreadScroll, rowsOf, threadScroll, withChatUsers } from "./ofMirrorData";
import { SELECT_MODEL } from "./ofMirrorWrites";
import { relay, type OFChatItem, type OFMessage } from "./relay";
import type { ChatFolder } from "@/hooks/useChatFolders";

const page = (name: string) => {
  document.documentElement.innerHTML = readFileSync(resolve(__dirname, `../public/of-mirror/pages/messages/${name}.html`), "utf8");
  return document;
};
const fixture = <T = unknown>(name: string): T => JSON.parse(readFileSync(resolve(__dirname, `__fixtures__/of/${name}.json`), "utf8"));
const flush = () => new Promise((r) => setTimeout(r, 0));
const noteText = (d: Document) => d.getElementById("oi-note")?.textContent;
const ALL: ChatsView = chatsView(new URLSearchParams());
const ME: ChatsMe = { countPinnedChat: 3, countPriorityChat: 0, chatMessagesCount: 0, unreadTips: 0, tipsEnabled: true };
const FOLDERS = rowsOf<ChatFolder>(fixture("messages-chats-folders"))!;
const writes = (over: Partial<NonNullable<ChatsContext["writes"]>> = {}) => ({
  clear: vi.fn((_id: string) => Promise.resolve({ success: true })),
  markAllRead: vi.fn(() => Promise.resolve({ success: true })),
  pinFolder: vi.fn((_id: string, _on: boolean) => Promise.resolve({ id: 1 })),
  markRead: vi.fn((_id: string, _read: boolean) => Promise.resolve({ success: true })),
  ...over,
});
const ctx = (over: Partial<ChatsContext> = {}): ChatsContext => ({
  view: ALL,
  chat: null,
  me: ME,
  folders: FOLDERS,
  navigate: vi.fn(),
  writes: writes(),
  confirm: vi.fn(() => true),
  ...over,
});
/** The list page with the captured chats (named from /users/list), as useOfData draws them. */
const listWithRows = (name = "index", listQuery = "") => {
  const doc = page(name);
  const rows = withChatUsers(rowsOf<OFChatItem>(fixture("messages-chats"))!, fixture("messages-users-list"));
  applyData(doc, `messages/${name}`, { chats: rows, listQuery });
  return doc;
};
const tab = (d: Document, t: string) => d.querySelector<HTMLButtonElement>(`[data-oi-tab='${t}']`)!;

afterEach(() => vi.restoreAllMocks());

describe("chatsView / chatsRequest: OF's GET /chats params (its chats-list fetch)", () => {
  const req = (q: string) => chatsRequest(chatsView(new URLSearchParams(q)));
  it("All sends no filter, Newest First (order=recent)", () => {
    expect(req("")).toEqual({ filter: null, listId: null, order: "recent", query: null });
  });
  it("a tab is OF's filter; With Tips is who_tipped (OF answers filter=tips with a 400)", () => {
    expect(req("tab=pinned").filter).toBe("pinned");
    expect(req("tab=priority").filter).toBe("priority");
    expect(req("tab=unread").filter).toBe("unread");
    expect(req("tab=who_tipped").filter).toBe("who_tipped");
    expect(fixture<{ detail: { upstream_body: string } }>("messages-chats-with-tips").detail.upstream_body).toContain("Invalid filter");
    expect(rowsOf(fixture("messages-chats-who-tipped"))).toEqual([]); // OF's real answer to who_tipped: a list
  });
  it("With Tips with the dropdown's Unread is unread_tips; the dropdown filter is ignored where OF hides its group", () => {
    expect(req("tab=who_tipped&filter=unread").filter).toBe("unread_tips");
    expect(req("filter=unread_tips").filter).toBe("unread_tips");
    expect(req("tab=who_tipped&filter=unread_tips").filter).toBe("who_tipped");
    expect(req("tab=pinned&filter=unread").filter).toBe("pinned");
    expect(req("filter=priority").filter).toBe("priority");
  });
  it("a folder is list_id (a tab wins over it), Oldest First is order=old, the search is query", () => {
    expect(req("folder=1165234649&order=old&q=%20ab%20")).toEqual({ filter: null, listId: "1165234649", order: "old", query: "ab" });
    expect(req("tab=unread&folder=9").listId).toBeNull();
    expect(req("tab=nope&filter=nope&order=nope")).toEqual({ filter: null, listId: null, order: "recent", query: null });
  });
  it("the view round-trips as a query string; links carry the open chat", () => {
    const v = chatsView(new URLSearchParams("q=x&order=old&folder=7&filter=unread"));
    expect(chatsQuery(v)).toBe("folder=7&filter=unread&order=old&q=x");
    expect(chatsView(new URLSearchParams(chatsQuery(v)))).toEqual(v);
    expect(chatsQuery(ALL)).toBe("");
    expect(listHref(null, ALL)).toBe("/of-manager/messages");
    expect(listHref("3001", { ...ALL, tab: "pinned" })).toBe("/of-manager/messages/chat?chat=3001&tab=pinned");
    expect(chatsHref("/of-manager/messages/state-folders", null, v)).toBe("/of-manager/messages/state-folders?folder=7&filter=unread&order=old&q=x");
  });
  it("OF's tab counter", () => {
    expect([counter(0), counter(null), counter(3), counter(1200)]).toEqual(["", "", "3", "999+"]);
  });
});

describe("the chat list's tabs (messages/index)", () => {
  it("renders from /users/me and /chats/folders: OF's visibility rules, counts, folder tabs, the current one", () => {
    const d = listWithRows();
    bindChatList(d, ctx());
    expect(tab(d, "all").classList.contains("m-current")).toBe(true);
    expect(tab(d, "pinned").textContent?.replace(/\s+/g, " ").trim()).toBe("Pinned 3");
    expect(tab(d, "priority").closest("li")!.style.display).toBe("none"); // countPriorityChat 0
    expect(tab(d, "unread").closest("li")!.style.display).toBe("none"); // chatMessagesCount 0
    expect(tab(d, "who_tipped").closest("li")!.style.display).toBe(""); // tipsEnabled
    const folders = [...d.querySelectorAll<HTMLButtonElement>("[data-oi-tab='folder']")];
    expect(folders.map((b) => [b.textContent?.trim(), b.disabled])).toEqual(
      FOLDERS.filter((f) => f.isPinnedToChat).map((f) => [f.name, !f.usersCount]),
    );
    expect(d.querySelector<HTMLElement>(".b-chats__conversations-list .b-tabs__nav .b-posts_preloader")!.style.display).toBe("none");
  });
  it("an open tab shows even with no count; OF's loader shows until the folders are read", () => {
    const d = listWithRows();
    bindChatList(d, ctx({ view: { ...ALL, tab: "unread" }, folders: undefined }));
    expect(tab(d, "unread").closest("li")!.style.display).toBe("");
    expect(tab(d, "unread").classList.contains("m-current")).toBe(true);
    expect(tab(d, "all").classList.contains("m-current")).toBe(false);
    expect(d.querySelector<HTMLElement>(".b-chats__conversations-list .b-tabs__nav .b-posts_preloader")!.style.display).toBe("");
  });
  it("a click navigates to the list with that tab (the sort and search kept), a folder to its list_id view", () => {
    const d = listWithRows();
    const c = ctx({ view: { ...ALL, order: "old", q: "ab" } });
    bindChatList(d, c);
    tab(d, "pinned").click();
    expect(c.navigate).toHaveBeenLastCalledWith("/of-manager/messages?tab=pinned&order=old&q=ab");
    d.querySelector<HTMLButtonElement>("[data-oi-tab='folder'][data-oi-folder='following']")!.click();
    expect(c.navigate).toHaveBeenLastCalledWith("/of-manager/messages?folder=following&order=old&q=ab");
    tab(d, "all").click(); // already current: nothing
    expect(c.navigate).toHaveBeenCalledTimes(2);
  });
  it("on a chat page the tabs keep the chat open", () => {
    const d = page("chat");
    const c = ctx({ chat: "3001" });
    bindChatList(d, c);
    tab(d, "who_tipped").click();
    expect(c.navigate).toHaveBeenCalledWith("/of-manager/messages/chat?chat=3001&tab=who_tipped");
  });
  it("the pencil opens the folders dialog with the view; the sort toggle opens the dropdown with it", () => {
    const d = listWithRows();
    bindChatList(d, ctx({ view: { ...ALL, tab: "pinned" } }));
    expect(d.querySelector("a[data-oi-tab='folders']")!.getAttribute("href")).toBe("/of-manager/messages/state-folders?tab=pinned");
    expect(d.querySelector("a.of-state-link[aria-label='Toggle']")!.getAttribute("href")).toBe("/of-manager/messages/state-filter-dropdown?tab=pinned");
  });
  it("survives a page without the list and an unbind removes its listeners", () => {
    document.documentElement.innerHTML = "<body><p>nothing</p></body>";
    const c = ctx();
    const unbind = bindChatList(document, c);
    unbind();
    const d = listWithRows();
    const un = bindChatList(d, c);
    un();
    tab(d, "pinned").click();
    expect(c.navigate).not.toHaveBeenCalled();
  });
});

describe("the chat rows (applyChats)", () => {
  it("link to the chat with the list's view, are stamped with the fan id, the avatar goes to OF's profile", () => {
    const d = listWithRows("index", "tab=pinned");
    const rows = [...d.querySelectorAll<HTMLElement>("[data-oi-chat]")];
    expect(rows.length).toBe(20);
    expect(rows[0].dataset.oiChat).toBe("2001");
    expect(rows[0].querySelector(".b-chats__item__link")!.getAttribute("href")).toBe("/of-manager/messages/chat?chat=2001&tab=pinned");
    const a = rows[0].querySelector(".b-available-users__round-img a.g-avatar")!;
    const u = fixture<Record<string, { username: string }>>("messages-users-list")["2001"];
    expect(a.getAttribute("href")).toBe(`https://onlyfans.com/${u.username}`);
    expect(a.getAttribute("target")).toBe("_blank");
    expect(rows[0].querySelector(".b-chats__item__btn-clear")!.hasAttribute("data-oi-wired")).toBe(true);
  });
  it("no profile link where OF says canGoToProfile false", () => {
    const d = page("index");
    const [c] = withChatUsers(rowsOf<OFChatItem>(fixture("messages-chats"))!, fixture("messages-users-list"));
    applyData(d, "messages/index", { chats: [{ ...c, canGoToProfile: false }] });
    expect(d.querySelector("[data-oi-chat] a.g-avatar")!.getAttribute("href")).toBe("#");
  });
  it("a second page (offset 20) draws below the first, one row per chat", () => {
    const d = page("index");
    const two = [...rowsOf<OFChatItem>(fixture("messages-chats"))!, ...rowsOf<OFChatItem>(fixture("messages-chats-offset20"))!];
    applyData(d, "messages/index", { chats: two });
    const ids = [...d.querySelectorAll<HTMLElement>("[data-oi-chat]")].map((r) => r.dataset.oiChat);
    expect(ids.length).toBe(40);
    expect(new Set(ids).size).toBe(40);
  });
  it("OF's loader shows while the next page is read", () => {
    const d = page("index");
    applyData(d, "messages/index", { chats: rowsOf<OFChatItem>(fixture("messages-chats"))!, chatsMore: { loading: true, error: null, next: null } });
    const spinner = [...d.querySelectorAll<HTMLElement>(".b-chats__scroller .infinite-status-prompt")].find((p) => p.querySelector(".b-posts_preloader"))!;
    expect(spinner.getAttribute("style")).toBe("");
  });
});

describe("a row's x: Clear messages (DELETE /chats/{id}; mock only, never live)", () => {
  it("asks first, then clears that chat", async () => {
    const d = listWithRows();
    const c = ctx();
    bindChatList(d, c);
    d.querySelector<HTMLElement>("[data-oi-chat='2003'] .b-chats__item__btn-clear")!.click();
    expect(c.confirm).toHaveBeenCalledWith(CLEAR_CONFIRM);
    expect(c.writes!.clear).toHaveBeenCalledWith("2003");
    await flush();
    expect(c.navigate).not.toHaveBeenCalled();
  });
  it("sends nothing when the confirm is refused", () => {
    const d = listWithRows();
    const c = ctx({ confirm: vi.fn(() => false) });
    bindChatList(d, c);
    d.querySelector<HTMLElement>("[data-oi-chat='2003'] .b-chats__item__btn-clear")!.click();
    expect(c.writes!.clear).not.toHaveBeenCalled();
  });
  it("the open chat's row goes back to the list; an error says so in place", async () => {
    const d = listWithRows("chat");
    const c = ctx({ chat: "2001", view: { ...ALL, tab: "pinned" } });
    bindChatList(d, c);
    d.querySelector<HTMLElement>("[data-oi-chat='2001'] .b-chats__item__btn-clear")!.click();
    await flush();
    expect(c.navigate).toHaveBeenCalledWith("/of-manager/messages?tab=pinned", true);
    const failing = ctx({ writes: writes({ clear: vi.fn(() => Promise.reject(new Error("502 Bad Gateway"))) }) });
    const d2 = listWithRows();
    bindChatList(d2, failing);
    d2.querySelector<HTMLElement>("[data-oi-chat='2002'] .b-chats__item__btn-clear")!.click();
    await flush();
    expect(noteText(d2)).toBe("Could not clear messages: 502 Bad Gateway");
    expect(d2.querySelectorAll("[data-oi-chat]").length).toBe(20);
  });
  it("All models with no model: nothing is sent", () => {
    const d = listWithRows();
    const c = ctx({ writes: null });
    bindChatList(d, c);
    d.querySelector<HTMLElement>("[data-oi-chat='2003'] .b-chats__item__btn-clear")!.click();
    expect(noteText(d)).toBe(SELECT_MODEL);
    expect(c.confirm).not.toHaveBeenCalled();
  });
});

describe("the sort dropdown (messages/state-filter-dropdown)", () => {
  const radios = (d: Document) => [...d.querySelectorAll<HTMLInputElement>("[data-oi-chats] input[type='radio']")].filter((i) => i.checked).map((i) => i.closest<HTMLElement>("[data-oi-chats]")!.dataset.oiChats);
  const href = (d: Document, item: string) => d.querySelector(`[data-oi-chats='${item}'] a.of-state-link`)!.getAttribute("href");
  it("checks the current filter and order and links every option to the list with it", () => {
    const d = page("state-filter-dropdown");
    bindChatList(d, ctx({ view: { ...ALL, folder: "7", order: "old" } }));
    expect(radios(d)).toEqual(["filter:", "order:old"]);
    expect(href(d, "filter:unread")).toBe("/of-manager/messages?folder=7&filter=unread&order=old");
    expect(href(d, "filter:")).toBe("/of-manager/messages?folder=7&order=old");
    expect(href(d, "order:recent")).toBe("/of-manager/messages?folder=7");
    expect(d.querySelector(".b-chats__conversations-list .b-content-filter__title")!.textContent).toBe("Oldest First");
  });
  it("hides the groups OF hides: the filters on Pinned (and its order), Unread with tips on With Tips", () => {
    const d = page("state-filter-dropdown");
    bindChatList(d, ctx({ view: { ...ALL, tab: "pinned" } }));
    const shown = (item: string) => d.querySelector<HTMLElement>(`[data-oi-chats='${item}']`)!.style.display !== "none";
    expect(["filter:", "filter:unread", "order:recent", "order:old"].map(shown)).toEqual([false, false, false, false]);
    const d2 = page("state-filter-dropdown");
    bindChatList(d2, ctx({ view: { ...ALL, tab: "who_tipped" } }));
    expect(d2.querySelector<HTMLElement>("[data-oi-chats='filter:unread_tips']")!.style.display).toBe("none");
    expect(d2.querySelector<HTMLElement>("[data-oi-chats='filter:unread']")!.style.display).toBe("");
    expect(d2.querySelector<HTMLElement>("[data-oi-chats='filter:priority']")!.style.display).toBe("none"); // OF: no Priority on With Tips
    const d3 = page("state-filter-dropdown");
    bindChatList(d3, ctx({ me: { ...ME, tipsEnabled: undefined } }));
    expect(d3.querySelector<HTMLElement>("[data-oi-chats='filter:unread_tips']")!.style.display).toBe("none"); // only tipsEnabled === true
  });
  it("from a chat: every option and the backdrop go back to that chat", () => {
    const d = page("state-filter-dropdown");
    bindChatList(d, ctx({ chat: "3001" }));
    expect(href(d, "order:old")).toBe("/of-manager/messages/chat?chat=3001&order=old");
    expect(d.querySelector("a.of-state-link[aria-label='Toggle']")!.getAttribute("href")).toBe("/of-manager/messages/chat?chat=3001");
  });
  it("Select (bulk select) is disabled with the tooltip", () => {
    const d = page("state-filter-dropdown");
    const select = d.querySelector<HTMLElement>("[data-oi-select]")!;
    expect(select.getAttribute("title")).toBe("Not available in Inflowwww yet");
    expect(select.querySelector("a")).toBeNull();
  });
});

describe("Mark all as read (POST /chats/mark-as-read; mock only, never live)", () => {
  const item = (d: Document) => d.querySelector<HTMLElement>("[data-oi-chats='mark-all']")!;
  it("is disabled while OF has no unread chat (authUser.chatMessagesCount), as OF", () => {
    const d = page("state-filter-dropdown");
    const c = ctx();
    bindChatList(d, c);
    expect(item(d).classList.contains("v-list-item--disabled")).toBe(true);
    item(d).click();
    expect(c.writes!.markAllRead).not.toHaveBeenCalled();
    expect(c.navigate).not.toHaveBeenCalled();
  });
  it("sends it (no confirm, as OF) and closes the menu on the same list", async () => {
    const d = page("state-filter-dropdown");
    const c = ctx({ me: { ...ME, chatMessagesCount: 4 }, view: { ...ALL, tab: "who_tipped" } });
    bindChatList(d, c);
    expect(item(d).hasAttribute("data-oi-wired")).toBe(true);
    item(d).click();
    expect(c.confirm).not.toHaveBeenCalled();
    expect(c.writes!.markAllRead).toHaveBeenCalledTimes(1);
    await flush();
    expect(c.navigate).toHaveBeenCalledWith("/of-manager/messages?tab=who_tipped");
  });
  it("an error stays on the menu with the Relay's text; All models with no model sends nothing", async () => {
    const d = page("state-filter-dropdown");
    bindChatList(d, ctx({ me: { ...ME, chatMessagesCount: 1 }, writes: writes({ markAllRead: vi.fn(() => Promise.reject(new Error("429 Too Many Requests"))) }) }));
    item(d).click();
    await flush();
    expect(noteText(d)).toBe("Could not mark all as read: 429 Too Many Requests");
    const d2 = page("state-filter-dropdown");
    bindChatList(d2, ctx({ me: { ...ME, chatMessagesCount: 1 }, writes: null }));
    item(d2).click();
    expect(noteText(d2)).toBe(SELECT_MODEL);
  });
});

describe("header search", () => {
  const form = (d: Document) => d.querySelector<HTMLFormElement>(".b-chats__header .b-chat__search-form")!;
  const input = (d: Document) => form(d).querySelector<HTMLInputElement>("input[type='search']")!;
  it("the magnifier opens OF's form; typing lists ?q= once the keys stop (replace), Enter at once (push)", () => {
    vi.useFakeTimers();
    const d = listWithRows();
    const c = ctx({ view: { ...ALL, tab: "pinned" } });
    bindChatList(d, c);
    expect(d.querySelector(".b-chats__header")!.classList.contains("m-search-form-visible")).toBe(false);
    d.querySelector<HTMLButtonElement>("button[at-attr='search_header_btn']")!.click();
    expect(d.querySelector(".b-chats__header")!.classList.contains("m-search-form-visible")).toBe(true);
    input(d).value = "syn";
    input(d).dispatchEvent(new Event("input", { bubbles: true }));
    vi.advanceTimersByTime(SEARCH_MS - 1);
    expect(c.navigate).not.toHaveBeenCalled();
    vi.advanceTimersByTime(1);
    expect(c.navigate).toHaveBeenCalledWith("/of-manager/messages?tab=pinned&q=syn", true);
    input(d).value = "synth";
    form(d).dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    expect(c.navigate).toHaveBeenLastCalledWith("/of-manager/messages?tab=pinned&q=synth", false);
    vi.useRealTimers();
  });
  it("as OF's watcher: 1-2 characters list nothing until Enter; emptying the input lists every chat again", () => {
    vi.useFakeTimers();
    const d = listWithRows();
    const c = ctx({ view: { ...ALL, q: "synth" } });
    bindChatList(d, c);
    input(d).value = "sy";
    input(d).dispatchEvent(new Event("input", { bubbles: true }));
    vi.advanceTimersByTime(SEARCH_MS);
    expect(c.navigate).not.toHaveBeenCalled();
    form(d).dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    expect(c.navigate).toHaveBeenLastCalledWith("/of-manager/messages?q=sy", false);
    input(d).value = "";
    input(d).dispatchEvent(new Event("input", { bubbles: true }));
    vi.advanceTimersByTime(SEARCH_MS);
    expect(c.navigate).toHaveBeenLastCalledWith("/of-manager/messages", true);
    vi.useRealTimers();
  });
  it("opens with the URL's query; Clear closes it and lists everything again", () => {
    const d = listWithRows();
    const c = ctx({ view: { ...ALL, q: "synth" } });
    bindChatList(d, c);
    expect(d.querySelector(".b-chats__header")!.classList.contains("m-search-form-visible")).toBe(true);
    expect(input(d).value).toBe("synth");
    form(d).querySelector<HTMLButtonElement>("button[aria-label='Clear']")!.click();
    expect(d.querySelector(".b-chats__header")!.classList.contains("m-search-form-visible")).toBe(false);
    expect(c.navigate).toHaveBeenCalledWith("/of-manager/messages", false);
  });
  it("a search result (OF's /chats?query=) draws its rows", () => {
    const d = page("index");
    applyData(d, "messages/index", { chats: rowsOf<OFChatItem>(fixture("messages-chats-search"))!, listQuery: "q=synth" });
    expect([...d.querySelectorAll<HTMLElement>("[data-oi-chat]")].map((r) => r.dataset.oiChat)).toEqual(["3020", "3036", "3037"]);
  });
});

describe("the folders dialog (messages/state-folders; PATCH /lists/{id}/pin-chat, mock only)", () => {
  const rows = (d: Document) => [...d.querySelectorAll<HTMLElement>(".modal label.b-rows-lists__item[data-oi-list]")];
  it("lists every pinnable list from /chats/folders, the pinned ones ticked", () => {
    const d = page("state-folders");
    bindChatList(d, ctx());
    expect(d.querySelector(".modal-title")!.textContent?.trim()).toBe("Pinned lists");
    expect(rows(d).length).toBe(FOLDERS.length);
    const ticked = rows(d).filter((r) => r.querySelector("input")!.checked).map((r) => r.dataset.oiList);
    expect(ticked).toEqual(FOLDERS.filter((f) => f.isPinnedToChat).map((f) => String(f.id)));
    expect(d.querySelector<HTMLElement>(".modal [data-oi-empty]")!.style.display).toContain("none");
  });
  it("leaves another modal's rows alone (a chat's Tag other creators dialog)", () => {
    const d = page("chat/state-tag-people");
    const shown = () => [...d.querySelectorAll<HTMLElement>(".modal label.b-rows-lists__item")].filter((r) => !r.style.display).length;
    const before = shown();
    bindChatList(d, ctx());
    expect(d.querySelectorAll(".modal label.b-rows-lists__item[data-oi-list]").length).toBe(0);
    expect(shown()).toBe(before);
  });
  it("a tick pins the list, an untick unpins it; an error puts the box back", async () => {
    const d = page("state-folders");
    const c = ctx();
    bindChatList(d, c);
    const box = (id: string) => d.querySelector<HTMLInputElement>(`.modal label[data-oi-list='${id}'] input`)!;
    box("1299098471").click();
    expect(c.writes!.pinFolder).toHaveBeenLastCalledWith("1299098471", true);
    box("following").click();
    expect(c.writes!.pinFolder).toHaveBeenLastCalledWith("following", false);
    const failing = ctx({ writes: writes({ pinFolder: vi.fn(() => Promise.reject(new Error("400 Bad Request"))) }) });
    const d2 = page("state-folders");
    bindChatList(d2, failing);
    const b2 = d2.querySelector<HTMLInputElement>(".modal label[data-oi-list='1299098471'] input")!;
    b2.click();
    await flush();
    expect(b2.checked).toBe(false);
    expect(noteText(d2)).toBe("Could not pin the list: 400 Bad Request");
  });
  it("All models with no model: the box flips back, nothing is sent", () => {
    const d = page("state-folders");
    bindChatList(d, ctx({ writes: null }));
    const b = d.querySelector<HTMLInputElement>(".modal label[data-oi-list='1299098471'] input")!;
    b.click();
    expect(b.checked).toBe(false);
    expect(noteText(d)).toBe(SELECT_MODEL);
  });
  it("the unbind takes the rows away again", () => {
    const d = page("state-folders");
    const unbind = bindChatList(d, ctx());
    unbind();
    expect(rows(d).length).toBe(0);
  });
});

describe("chatsWrites: the Relay calls (method, path, body, X-Account-Id)", () => {
  it("Clear messages, Mark all as read and pin a folder", async () => {
    const del = vi.spyOn(relay, "delete").mockResolvedValue({ success: true });
    const post = vi.spyOn(relay, "post").mockResolvedValue({ success: true });
    const patch = vi.spyOn(relay, "patch").mockResolvedValue({ id: 1 });
    const qc = new QueryClient();
    const inval = vi.spyOn(qc, "invalidateQueries");
    const w = chatsWrites("80000112", qc);
    await w.clear("3001");
    expect(del).toHaveBeenCalledWith("/api/of/v2/chats/3001", { accountId: "80000112" });
    await w.markAllRead();
    expect(post).toHaveBeenCalledWith("/api/of/v2/chats/mark-as-read", undefined, { accountId: "80000112" });
    await w.pinFolder("following", true);
    expect(patch).toHaveBeenCalledWith("/api/of/v2/lists/following/pin-chat", { pinned: true }, { accountId: "80000112" });
    expect(inval.mock.calls.map(([f]) => f?.queryKey)).toEqual([["chats"], ["chats"], ["of-me", "80000112"], ["chat-folders", "80000112"]]);
  });
  it("a Relay error reaches the caller (the binder shows it)", async () => {
    vi.spyOn(relay, "delete").mockRejectedValue(new Error("502"));
    await expect(chatsWrites("1", new QueryClient()).clear("2")).rejects.toThrow("502");
  });
});

describe("the thread's scroll (older messages, polls): threadScroll / keepThreadScroll", () => {
  const box = (d: Document, sh: number, ch: number, top: number) => {
    const b = d.querySelector<HTMLElement>(".b-chat__messages")!;
    Object.defineProperty(b, "scrollHeight", { configurable: true, get: () => sh });
    Object.defineProperty(b, "clientHeight", { configurable: true, get: () => ch });
    b.scrollTop = top;
    return b;
  };
  const drawn = () => {
    const d = page("chat");
    applyData(d, "messages/chat", { chat: "2001", thread: { fan: null, messages: rowsOf(fixture("messages-thread"))! } });
    return d;
  };
  it("a first draw (or a view at the newest message) goes to the end, as OF opens a chat", () => {
    const d = page("chat");
    box(d, 2000, 500, 0);
    expect(threadScroll(d, "2001")).toBeNull(); // nothing real drawn yet
    const d2 = drawn();
    const b = box(d2, 2600, 500, 0);
    keepThreadScroll(d2, "2001", null);
    expect(b.scrollTop).toBe(2600);
    box(d2, 2000, 500, 1490);
    expect(threadScroll(d2, "2001")).toBeNull(); // within 40px of the end: a new message is followed
  });
  it("older messages put in above keep what is in view (no jump)", () => {
    const d = drawn();
    keepThreadScroll(d, "2001", null);
    box(d, 2000, 500, 100);
    const was = threadScroll(d, "2001");
    expect(was?.fromEnd).toBe(1900);
    // An older page arrived: one more message above the oldest one drawn, 1500px taller.
    const messages = rowsOf<OFMessage>(fixture("messages-thread"))!;
    const older = { ...messages[messages.length - 1], id: 1, createdAt: "2020-01-01T00:00:00Z" } as OFMessage;
    applyData(d, "messages/chat", { chat: "2001", thread: { fan: null, messages: [...messages, older] } });
    const b = box(d, 3500, 500, 0);
    keepThreadScroll(d, "2001", was);
    expect(b.scrollTop).toBe(1600);
  });
  it("a redraw with nothing put in above (a poll, a new message below) keeps the scrollTop, not the distance from the end", () => {
    const d = drawn();
    keepThreadScroll(d, "2001", null);
    box(d, 2000, 500, 100);
    const was = threadScroll(d, "2001");
    const messages = rowsOf<OFMessage>(fixture("messages-thread"))!;
    const newer = { ...messages[0], id: 99999999999999, createdAt: "2030-01-01T00:00:00Z" } as OFMessage;
    applyData(d, "messages/chat", { chat: "2001", thread: { fan: null, messages: [newer, ...messages] } });
    const b = box(d, 2300, 500, 0); // 300px arrived below
    keepThreadScroll(d, "2001", was);
    expect(b.scrollTop).toBe(100);
  });
  it("another chat opens at its newest message, never at the last chat's offset", () => {
    const d = drawn();
    keepThreadScroll(d, "2001", null);
    box(d, 2000, 500, 100);
    expect(threadScroll(d, "2001")).not.toBeNull();
    expect(threadScroll(d, "3001")).toBeNull(); // the box still shows 2001
    const b = box(d, 2400, 500, 100);
    keepThreadScroll(d, "3001", threadScroll(d, "3001"));
    expect(b.scrollTop).toBe(2400);
    expect(b.dataset.oiChat).toBe("3001");
  });
  it("an older page (before_id) draws above the newest one", () => {
    const d = page("chat");
    const head = rowsOf<{ id: number }>(fixture("messages-thread-older"))!;
    applyData(d, "messages/chat", { chat: "3001", thread: { fan: null, messages: head as never } });
    expect(d.querySelectorAll(".b-chat__item-message[data-oi-data] .b-chat__message").length).toBe(head.length);
  });
});

describe("a row's swipe: OF's Mark as Read / Mark as Unread (its SwipeOut), never on open", () => {
  // A held button while moving (OF's swipe needs one); `buttons: 0` is a move after the button was let go elsewhere.
  const ev = (type: string, x: number, y = 10, buttons = type === "pointermove" ? 1 : 0) => new MouseEvent(type, { bubbles: true, cancelable: true, clientX: x, clientY: y, button: 0, buttons });
  const swipe = (el: Element, to: number) => {
    el.dispatchEvent(ev("pointerdown", 300));
    el.dispatchEvent(ev("pointermove", 290));
    el.dispatchEvent(ev("pointermove", to));
    el.dispatchEvent(ev("pointerup", to));
    el.dispatchEvent(ev("click", to));
  };
  const rows = (d: Document) => [...d.querySelectorAll<HTMLElement>(".b-chats__item[data-oi-chat]")];

  it("each row's label says what a swipe does: Mark as Read on an unread chat, Mark as Unread on a read one", () => {
    const d = listWithRows();
    const all = rowsOf<OFChatItem>(fixture("messages-chats"))!;
    for (const r of rows(d)) {
      const c = all.find((x) => String(x.withUser.id) === r.dataset.oiChat)!;
      const label = r.closest(".swipeout")!.querySelector(".b-chats__mark-as-read-label")!.textContent!.trim();
      expect(label).toBe((c.unreadMessagesCount ?? 0) > 0 ? "Mark as Read" : "Mark as Unread");
    }
  });

  it("past 100 px: one POST (unread chat) or DELETE (read chat) /chats/{id}/mark-as-read; short of it, or a click, nothing", async () => {
    const d = listWithRows();
    const w = writes();
    const nav = vi.fn();
    const unbind = bindChatList(d, ctx({ writes: w, navigate: nav }));
    const read = rows(d).find((r) => !r.hasAttribute("data-oi-unread"))!;
    // A click (no drag) marks nothing.
    read.dispatchEvent(ev("pointerdown", 300));
    read.dispatchEvent(ev("pointerup", 300));
    swipe(read, 240); // 60 px: short of OF's threshold
    expect(w.markRead).not.toHaveBeenCalled();
    swipe(read, 150);
    expect(w.markRead).toHaveBeenCalledTimes(1);
    expect(w.markRead).toHaveBeenLastCalledWith(read.dataset.oiChat, false);
    await Promise.resolve();
    await Promise.resolve();
    expect(read.hasAttribute("data-oi-unread")).toBe(true);
    swipe(read, 150);
    expect(w.markRead).toHaveBeenLastCalledWith(read.dataset.oiChat, true);
    // The row slid back.
    expect(read.closest(".swipeout")!.querySelector<HTMLElement>(".swipeout-content")!.style.transform).toBe("");
    unbind();
  });

  it("a plain press takes no pointer capture (so its click still reaches the row's link); a real drag does", () => {
    const d = listWithRows();
    const unbind = bindChatList(d, ctx({ writes: writes() }));
    const row = rows(d)[0];
    const box = row.closest<HTMLElement>(".swipeout")!;
    const capture = vi.fn();
    box.setPointerCapture = capture;
    row.dispatchEvent(ev("pointerdown", 300));
    row.dispatchEvent(ev("pointermove", 298)); // a jitter, no drag
    row.dispatchEvent(ev("pointerup", 298));
    expect(capture).not.toHaveBeenCalled();
    const click = ev("click", 298);
    row.dispatchEvent(click);
    expect(click.defaultPrevented).toBe(false); // the click opens the chat
    row.dispatchEvent(ev("pointerdown", 300));
    row.dispatchEvent(ev("pointermove", 290));
    expect(capture).toHaveBeenCalled(); // (by every binder still on this shared test document)
    const n = capture.mock.calls.length;
    row.dispatchEvent(ev("pointermove", 280));
    expect(capture).toHaveBeenCalledTimes(n); // once per drag, not per move
    row.dispatchEvent(ev("pointerup", 280));
    unbind();
  });

  it("no deliberate release, no write: a move with no button held, or a pointercancel, slides the row back; touch scrolls vertically", () => {
    const d = listWithRows();
    const w = writes();
    const unbind = bindChatList(d, ctx({ writes: w }));
    const row = rows(d)[0];
    const content = row.closest(".swipeout")!.querySelector<HTMLElement>(".swipeout-content")!;
    row.dispatchEvent(ev("pointerdown", 300));
    row.dispatchEvent(ev("pointermove", 290));
    row.dispatchEvent(ev("pointermove", 150));
    expect(content.style.transform).toBe("translateX(-150px)");
    row.dispatchEvent(ev("pointermove", 140, 10, 0)); // the button came up outside the frame
    expect(content.style.transform).toBe("");
    row.dispatchEvent(ev("pointerup", 140));
    row.dispatchEvent(ev("pointerdown", 300));
    row.dispatchEvent(ev("pointermove", 290));
    row.dispatchEvent(ev("pointermove", 150));
    row.dispatchEvent(ev("pointercancel", 150));
    row.dispatchEvent(ev("pointerup", 150));
    expect(content.style.transform).toBe("");
    expect(w.markRead).not.toHaveBeenCalled();
    expect(d.getElementById("oi-swipe-touch")!.textContent).toBe(".swipeout { touch-action: pan-y; }");
    unbind();
    expect(d.getElementById("oi-swipe-touch")).toBeNull();
  });

  it("the exact requests, and a Relay error says so on the row; with no model nothing is sent", async () => {
    const qc = new QueryClient();
    const post = vi.spyOn(relay, "post").mockResolvedValue({ success: true });
    const del = vi.spyOn(relay, "delete").mockResolvedValue({ success: true });
    const w = chatsWrites("acc", qc);
    await w.markRead("800000002", true);
    await w.markRead("800000002", false);
    expect(post).toHaveBeenCalledWith("/api/of/v2/chats/800000002/mark-as-read", undefined, { accountId: "acc" });
    expect(del).toHaveBeenCalledWith("/api/of/v2/chats/800000002/mark-as-read", { accountId: "acc" });
    const d = listWithRows();
    const bad = writes({ markRead: vi.fn(() => Promise.reject(new Error("502 Bad Gateway"))) });
    bindChatList(d, ctx({ writes: bad }));
    const row = rows(d)[0];
    swipe(row, 100);
    await new Promise((r) => setTimeout(r, 0));
    expect(d.getElementById("oi-note")!.textContent).toMatch(/^Could not mark as (read|unread): 502 Bad Gateway$/);
    const none = listWithRows();
    bindChatList(none, ctx({ writes: null }));
    swipe(rows(none)[0], 100);
    expect(none.getElementById("oi-note")!.textContent).toBe("Select a model to save changes");
  });
});
