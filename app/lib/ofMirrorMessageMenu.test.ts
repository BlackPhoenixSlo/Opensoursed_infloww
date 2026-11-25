import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { createElement, type ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { applyData, rowsOf } from "./ofMirrorData";
import { applyScript, chatDraftKey, collectMessage, DRAFT_EVENT, loadChatDraft } from "./ofMirrorChat";
import { countdown } from "./ofMirrorThread";
import { bindMessageMenu, COPIED_TEXT, messageItems, messageWrites, stampReads, unsendLeft, type MenuMessage, type MessageRead, type MessageMenuContext, type MessageWrites } from "./ofMirrorMessageMenu";
import { bubbleExtras, scriptFromMessage } from "./ofMirrorBubbleExtras";
import { NOT_YET, SELECT_MODEL } from "./ofMirrorWrites";
import { NOT_CONFIRMED, useUnsendMessage } from "@/hooks/useUnsendMessage";
import { HANDOFF_TITLE } from "./ofMirrorHandoffs";
import { relay, type OFMessage } from "./relay";

const page = (p: string) => {
  document.documentElement.innerHTML = readFileSync(resolve(__dirname, `../public/of-mirror/pages/messages/${p}.html`), "utf8");
  return document;
};
const fixture = <T,>(name: string): T => JSON.parse(readFileSync(resolve(__dirname, `__fixtures__/of/${name}.json`), "utf8")) as T;
const thread = rowsOf<MenuMessage>(fixture("messages-thread"))!;
const FAN = { id: 2006, name: "Fan", username: "fan" };
const theirs = thread.find((m) => m.fromUser?.id === 2006 && m.text)!;
const mine = thread.find((m) => m.fromUser?.id !== 2006 && m.text)!;
const flush = () => new Promise((r) => setTimeout(r, 0));
const unbinds: (() => void)[] = [];
afterEach(() => {
  while (unbinds.length) unbinds.pop()!();
  vi.restoreAllMocks();
  sessionStorage.clear();
});

const writes = (over: Partial<MessageWrites> = {}) =>
  ({
    like: vi.fn(() => Promise.resolve({})),
    pin: vi.fn(() => Promise.resolve({})),
    bookmark: vi.fn(() => Promise.resolve({})),
    hide: vi.fn(() => Promise.resolve({})),
    unsend: vi.fn(() => Promise.resolve({})),
    unpinAll: vi.fn(() => Promise.resolve({})),
    ...over,
  }) as MessageWrites & Record<keyof MessageWrites, ReturnType<typeof vi.fn>>;
const ctx = (over: Partial<MessageMenuContext> = {}): MessageMenuContext => ({
  chat: "2006",
  message: (id) => thread.find((m) => String(m.id) === id),
  left: (m) => m.cancelSeconds ?? 0,
  limited: false,
  writes: writes(),
  storage: sessionStorage,
  accountId: "acc",
  copy: vi.fn(() => Promise.resolve()),
  newWrites: true,
  ...over,
});
const chatPage = (over: Partial<MessageMenuContext> = {}) => {
  const d = page("chat");
  applyData(d, "messages/chat", { chat: "2006", thread: { fan: FAN, messages: thread } });
  const c = ctx(over);
  unbinds.push(bindMessageMenu(d, c));
  return { d, c };
};
const openMenu = (d: Document, m: MenuMessage) => {
  d.querySelector<HTMLButtonElement>(`[data-oi-msg="${m.id}"] button[data-oi-msg-menu]`)!.click();
  return [...d.querySelectorAll<HTMLElement>("#oi-msg-menu [data-oi-msg-action]")];
};
const pick = (d: Document, key: string) => d.querySelector<HTMLElement>(`#oi-msg-menu [data-oi-msg-action='${key}']`)!.click();
const modal = (d: Document) => d.querySelector<HTMLElement>(".modal.show[role='dialog']");
const button = (d: Document, text: string) => [...modal(d)!.querySelectorAll<HTMLButtonElement>("button")].find((b) => b.textContent!.trim() === text)!;

describe("OF's message ⋮ items (ItemActions, 13560)", () => {
  it("the fan's message: copy, like, reply, bookmark, pin, hide, report (off; only with canReport); the Creator's: copy, reply, bookmark, pin, forward and tag (off), unsend with its countdown", () => {
    expect(messageItems(theirs, { mine: false, limited: false, left: 0, chat: null }).map((i) => [i.label, !!i.off])).toEqual([["Copy message text", false], ["Like", false], ["Reply", false], ["Bookmark", false], ["Pin", false], ["Hide", false], ["Report", true]]);
    expect(messageItems({ ...theirs, canReport: undefined }, { mine: false, limited: false, left: 0, chat: null }).map((i) => i.key)).not.toContain("report");
    expect(messageItems({ ...theirs, canReport: false }, { mine: false, limited: false, left: 0, chat: null }).map((i) => i.key)).not.toContain("report");
    expect(messageItems(theirs, { mine: false, limited: false, left: 0, chat: "2006" }).find((i) => i.key === "report")).toEqual({ key: "report", label: "Report", href: "https://onlyfans.com/my/chats/chat/2006/" });
    const own = { ...mine, media: [{ id: 1, type: "photo" }] } as MenuMessage;
    const items = messageItems(own, { mine: true, limited: false, left: 125, chat: null });
    expect(items.map((i) => [i.label, !!i.off])).toEqual([["Copy message text", false], ["Reply", false], ["Bookmark", false], ["Pin", false], ["Forward", true], ["Add a tag", true], ["Unsend 2:05", false]]);
    expect(countdown(59)).toBe("0:59");
  });

  it("OF's conditions: no Like on a restricted or blocked fan's message, no Copy on locked text, Unlike / Unpin / Unbookmark by state, Add to collection (off) once bookmarked, no Unsend once its window is over", () => {
    expect(messageItems(theirs, { mine: false, limited: true, left: 0, chat: null }).map((i) => i.key)).not.toContain("like");
    expect(messageItems({ ...theirs, lockedText: true }, { mine: false, limited: false, left: 0, chat: null }).map((i) => i.key)).not.toContain("copy");
    const labels = messageItems({ ...theirs, isLiked: true, isPinned: true, isAddedToBookmarks: true }, { mine: false, limited: false, left: 0, chat: null }).map((i) => i.label);
    expect(labels).toEqual(expect.arrayContaining(["Unlike", "Unpin", "Unbookmark", "Add to collection"]));
    expect(messageItems({ ...theirs, canBePinned: false }, { mine: false, limited: false, left: 0, chat: null }).map((i) => i.key)).not.toContain("pin");
    expect(messageItems(mine, { mine: true, limited: false, left: 0, chat: null }).map((i) => i.key)).not.toContain("unsend");
  });
});

describe("the menu on the chat page", () => {
  it("every message's ⋮ is enabled and opens OF's dropdown; its disabled items say why; Escape and a click elsewhere close it", () => {
    const { d } = chatPage();
    const btns = [...d.querySelectorAll<HTMLButtonElement>(".b-chat__messages [data-oi-msg] button[data-oi-msg-menu]")];
    expect(btns.length).toBe(thread.length);
    expect(btns.every((b) => !b.disabled && !b.title)).toBe(true);
    const items = openMenu(d, { ...mine, media: [{ id: 1 }] } as MenuMessage);
    expect(d.getElementById("oi-msg-menu")!.className).toContain("m-dropdown-list");
    const forward = items.find((i) => i.dataset.oiMsgAction === "forward")!;
    expect([forward.getAttribute("aria-disabled"), forward.title]).toEqual(["true", NOT_YET]);
    d.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
    expect(d.getElementById("oi-msg-menu")).toBeNull();
    openMenu(d, theirs);
    d.body.click();
    expect(d.getElementById("oi-msg-menu")).toBeNull();
  });

  it("a scroll moves the menu with its button (OF's popper); it closes once the button leaves the view", () => {
    const { d } = chatPage();
    openMenu(d, theirs);
    const btn = d.querySelector<HTMLElement>(`[data-oi-msg="${theirs.id}"] button[data-oi-msg-menu]`)!;
    vi.spyOn(btn, "getBoundingClientRect").mockReturnValue({ top: 300, bottom: 320, left: 40, right: 60 } as DOMRect);
    d.querySelector(".b-chat__messages")!.dispatchEvent(new Event("scroll"));
    expect(d.getElementById("oi-msg-menu")!.style.top).toBe("320px");
    expect(btn.getAttribute("aria-expanded")).toBe("true");
    vi.spyOn(btn, "getBoundingClientRect").mockReturnValue({ top: 5000, bottom: 5020, left: 40, right: 60 } as DOMRect);
    d.querySelector(".b-chat__messages")!.dispatchEvent(new Event("scroll"));
    expect([d.getElementById("oi-msg-menu"), btn.getAttribute("aria-expanded")]).toEqual([null, "false"]);
  });

  it("Like, Pin, Bookmark (with its chat group) and Hide send at once; an error says so in place", async () => {
    const w = writes({ hide: vi.fn(() => Promise.reject(new Error("405 Method Not Allowed"))) });
    const { d } = chatPage({ writes: w });
    const id = String(theirs.id);
    openMenu(d, theirs);
    pick(d, "like");
    expect(w.like).toHaveBeenCalledWith(id, true);
    openMenu(d, theirs);
    pick(d, "pin");
    expect(w.pin).toHaveBeenCalledWith(id, true);
    openMenu(d, theirs);
    pick(d, "bookmark");
    expect(w.bookmark).toHaveBeenCalledWith(id, Number(theirs.queueId), true);
    openMenu(d, theirs);
    pick(d, "hide");
    await flush();
    expect(d.getElementById("oi-note")!.textContent).toBe("Could not hide the message: 405 Method Not Allowed");
  });

  it("Copy message text: its plain text to the clipboard, OF's toast", async () => {
    const { d, c } = chatPage();
    openMenu(d, theirs);
    pick(d, "copy");
    await flush();
    expect(c.copy).toHaveBeenCalledWith(theirs.text!.replace(/<[^>]+>/g, "").trim());
    expect(d.getElementById("oi-toast")!.textContent!.trim()).toBe(COPIED_TEXT);
  });

  it("Reply: the chat draft answers it (the line under the editor), and Send carries replyToMessageId", () => {
    const { d } = chatPage();
    const heard = vi.fn();
    d.addEventListener(DRAFT_EVENT, heard);
    openMenu(d, theirs);
    pick(d, "reply");
    expect(heard).toHaveBeenCalled();
    const draft = loadChatDraft(sessionStorage, "acc", "2006");
    expect(draft.reply_to).toBe(String(theirs.id));
    expect(collectMessage("ok", draft)).toEqual({ text: "ok", price: 0, media_files: [], reply_to_message_id: Number(theirs.id) });
    expect(sessionStorage.getItem(chatDraftKey("acc", "2006"))).toContain("reply_text");
  });

  it("Unsend asks first, then sends; Report (ticket 42) is OF's link to the chat's onlyfans.com page and sends nothing", async () => {
    const w = writes();
    const { d } = chatPage({ writes: w });
    openMenu(d, mine);
    pick(d, "unsend");
    expect(w.unsend).not.toHaveBeenCalled();
    button(d, "Unsend").click();
    await flush();
    expect(w.unsend).toHaveBeenCalledWith(mine);
    expect(modal(d)).toBeNull();
    const post = vi.spyOn(relay, "post");
    openMenu(d, theirs);
    const report = d.querySelector<HTMLAnchorElement>("#oi-msg-menu [data-oi-msg-action='report']")!;
    expect([report.tagName, report.href, report.target, report.rel, report.hasAttribute("data-oi-wired"), report.title]).toEqual(["A", "https://onlyfans.com/my/chats/chat/2006/", "_blank", "noopener noreferrer", true, HANDOFF_TITLE]);
    expect([report.getAttribute("aria-disabled"), report.classList.contains("v-list-item--disabled"), report.textContent!.trim()]).toEqual([null, false, "Report"]);
    let prevented: boolean | null = null;
    const seen = (ev: Event) => { prevented = ev.defaultPrevented; ev.preventDefault(); };
    d.addEventListener("click", seen);
    report.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
    d.removeEventListener("click", seen);
    await flush();
    expect(prevented).toBe(false);
    expect(d.getElementById("oi-msg-menu")).toBeNull();
    expect(modal(d)).toBeNull();
    expect(Object.values(w).filter((f) => f !== w.unsend).every((f) => f.mock.calls.length === 0)).toBe(true);
    expect(post).not.toHaveBeenCalled();
  });

  it("All models with no model: an action sends nothing and says to pick one", () => {
    const { d } = chatPage({ writes: null });
    openMenu(d, theirs);
    pick(d, "pin");
    expect(d.getElementById("oi-note")!.textContent).toBe(SELECT_MODEL);
  });
});

describe("the unsend window: each message's cancelSeconds from when it was read", () => {
  it("an older page read later does not restart a newer message's clock; a fresh read does; a patched copy keeps its time", () => {
    const reads = new Map<string, MessageRead>();
    const a = { id: 1, cancelSeconds: 100 } as MenuMessage;
    stampReads(reads, [a], 0);
    stampReads(reads, [a, { id: 2, cancelSeconds: 0 } as MenuMessage], 40_000);
    expect(unsendLeft(reads, a, 40_000)).toBe(60);
    expect(unsendLeft(reads, { ...a, isLiked: true }, 40_000)).toBe(60);
    const fresh = { id: 1, cancelSeconds: 50 } as MenuMessage;
    stampReads(reads, [fresh], 50_000);
    expect(unsendLeft(reads, fresh, 60_000)).toBe(40);
    expect(unsendLeft(reads, fresh, 200_000)).toBe(0);
  });
});

describe("the menu at 390px and from the keyboard", () => {
  it("stays inside the window (8px) and scrolls when taller; Enter and Space pick a focused item", async () => {
    const { d } = chatPage();
    const win = d.defaultView!;
    vi.spyOn(win, "innerWidth", "get").mockReturnValue(390);
    vi.spyOn(win, "innerHeight", "get").mockReturnValue(400);
    const rect = (x: number, y: number, w: number, h: number) => ({ left: x, top: y, right: x + w, bottom: y + h, width: w, height: h, x, y, toJSON: () => ({}) }) as DOMRect;
    vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(function (this: HTMLElement) {
      return this.id === "oi-msg-menu" ? rect(0, 0, 220, 500) : rect(300, 100, 24, 24);
    });
    openMenu(d, theirs);
    const menu = d.getElementById("oi-msg-menu")!;
    expect([menu.style.left, menu.style.maxHeight, menu.style.overflow]).toEqual(["162px", "384px", "auto"]);
    expect(Number.parseInt(menu.style.top)).toBeGreaterThanOrEqual(8);
    const copy = vi.fn(() => Promise.resolve());
    const w = writes();
    const k = chatPage({ writes: w, copy });
    openMenu(k.d, theirs);
    const like = k.d.querySelector<HTMLElement>("#oi-msg-menu [data-oi-msg-action='like']")!;
    like.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true, cancelable: true }));
    await flush();
    expect(w.like).toHaveBeenCalledWith(String(theirs.id), true);
    openMenu(k.d, theirs);
    const space = new KeyboardEvent("keydown", { key: " ", bubbles: true, cancelable: true });
    k.d.querySelector<HTMLElement>("#oi-msg-menu [data-oi-msg-action='copy']")!.dispatchEvent(space);
    await flush();
    expect([copy.mock.calls.length, space.defaultPrevented]).toEqual([1, true]);
  });
});

describe("the pinned page's ⋮: Unpin all messages", () => {
  it("asks, then DELETE …/messages/pin; off while there is no pin; its search button is OF's", async () => {
    const d = page("chat/pinned");
    const w = writes();
    unbinds.push(bindMessageMenu(d, ctx({ writes: w, pins: 2 })));
    expect(d.querySelector("button[at-attr='search_btn']")).not.toBeNull();
    const btn = d.querySelector<HTMLButtonElement>("button[data-oi-pinned-menu]")!;
    expect(btn.disabled).toBe(false);
    btn.click();
    expect(d.querySelector("#oi-msg-menu")!.textContent!.trim()).toBe("Unpin all messages");
    pick(d, "unpin-all");
    button(d, "Unpin all").click();
    await flush();
    expect(w.unpinAll).toHaveBeenCalledTimes(1);
    const none = page("chat/pinned");
    unbinds.push(bindMessageMenu(none, ctx({ pins: 0 })));
    expect(none.querySelector<HTMLButtonElement>("button[data-oi-pinned-menu]")!.disabled).toBe(true);
  });
});

describe("messageWrites: the exact Relay requests, the thread patched first and put back on an error", () => {
  it("like, pin, bookmark, hide, unpin all (no report write)", async () => {
    const qc = new QueryClient();
    qc.setQueryData(["messages", "acc", 2006], thread);
    const post = vi.spyOn(relay, "post").mockResolvedValue({});
    const del = vi.spyOn(relay, "delete").mockResolvedValue({});
    const put = vi.spyOn(relay, "put").mockResolvedValue({});
    const unsend = vi.fn(() => Promise.resolve({}));
    const w = messageWrites("acc", "2006", qc, unsend);
    const o = { accountId: "acc" };
    expect(Object.keys(w).sort()).toEqual(["bookmark", "hide", "like", "pin", "unpinAll", "unsend"]);
    await w.like("11", true);
    await w.like("11", false);
    await w.pin("11", true);
    await w.pin("11", false);
    await w.bookmark("11", 5, true);
    await w.bookmark("11", 5, false);
    await w.hide("11");
    await w.unpinAll();
    await w.unsend(mine as OFMessage);
    expect(post.mock.calls).toEqual([
      ["/api/of/v2/messages/11/like", undefined, o],
      ["/api/of/v2/messages/11/pin/user/2006", undefined, o],
      ["/api/of/v2/messages/11/bookmark", { chat_group_id: 5 }, o],
    ]);
    expect(del.mock.calls).toEqual([
      ["/api/of/v2/messages/11/like", o],
      ["/api/of/v2/messages/11/pin/user/2006", o],
      ["/api/of/v2/messages/11/bookmark", o, { chat_group_id: 5 }],
      ["/api/of/v2/chats/2006/messages/pin", o],
    ]);
    expect(put.mock.calls).toEqual([["/api/of/v2/messages/11/hide", { withUserId: 2006 }, o]]);
    expect(unsend).toHaveBeenCalledWith(mine);
  });

  it("a pin shows at once and is put back when OF refuses it; a hidden message leaves the thread", async () => {
    const qc = new QueryClient();
    qc.setQueryData(["messages", "acc", 2006], thread);
    const id = String(theirs.id);
    vi.spyOn(relay, "post").mockRejectedValueOnce(new Error("400 Bad Request"));
    const w = messageWrites("acc", "2006", qc, vi.fn());
    const pinned = () => qc.getQueryData<MenuMessage[]>(["messages", "acc", 2006])!.find((m) => String(m.id) === id)!.isPinned;
    const p = w.pin(id, true);
    expect(pinned()).toBe(true);
    await expect(p).rejects.toThrow("400 Bad Request");
    expect(pinned()).toBe(false);
    vi.spyOn(relay, "put").mockResolvedValue({});
    await w.hide(id);
    expect(qc.getQueryData<MenuMessage[]>(["messages", "acc", 2006])!.some((m) => String(m.id) === id)).toBe(false);
  });

  it("pinned page: a second confirm while the unsend is out sends nothing, from the menu or another caller; on success the bubble leaves the pinned cache", async () => {
    const qc = new QueryClient({ defaultOptions: { queries: { gcTime: Infinity } } });
    const pinnedKey = ["chat-pinned", "acc", "2006"];
    qc.setQueryData(pinnedKey, [mine, theirs]);
    let answer!: (r: unknown) => void;
    const del = vi.spyOn(relay, "delete").mockImplementation(() => new Promise((r) => (answer = r)));
    const wrapper = ({ children }: { children: ReactNode }) => createElement(QueryClientProvider, { client: qc }, children);
    const menu = renderHook(() => useUnsendMessage("acc", 2006), { wrapper }).result.current;
    const button = renderHook(() => useUnsendMessage("acc", 2006), { wrapper }).result.current;
    const first = messageWrites("acc", "2006", qc, menu.unsendOne).unsend(mine as OFMessage);
    const again = messageWrites("acc", "2006", qc, menu.unsendOne).unsend(mine as OFMessage);
    const row = button.unsendOne({ id: String(mine.id) } as OFMessage);
    expect(del).toHaveBeenCalledTimes(1);
    answer({ success: true });
    expect(await Promise.all([first, again, row])).toEqual([{ success: true }, { success: true }, { success: true }]);
    expect(qc.getQueryData<MenuMessage[]>(pinnedKey)!.map((m) => m.id)).toEqual([theirs.id]);
    const later = button.unsendOne(mine as OFMessage);
    expect(del).toHaveBeenCalledTimes(2);
    answer({ success: true });
    await later;
  });

  it("pinned page: a refused or unsent (null) unsend leaves the pinned bubble", async () => {
    const qc = new QueryClient();
    const pinnedKey = ["chat-pinned", "acc", "2006"];
    qc.setQueryData(pinnedKey, [mine]);
    await expect(messageWrites("acc", "2006", qc, vi.fn(() => Promise.reject(new Error(NOT_CONFIRMED)))).unsend(mine as OFMessage)).rejects.toThrow(NOT_CONFIRMED);
    await messageWrites("acc", "2006", qc, vi.fn(() => Promise.resolve(null))).unsend(mine as OFMessage);
    expect(qc.getQueryData<MenuMessage[]>(pinnedKey)!.map((m) => m.id)).toEqual([mine.id]);
  });
});

describe("bubbleExtras: per own/fan, priced/free, window open/closed", () => {
  const free = { id: 1, text: "hi", price: 0 } as MenuMessage;
  const ppv = { id: 2, text: "ppv", price: 5 } as MenuMessage;
  const tip = { id: 3, text: "", price: 5, isTip: true } as MenuMessage;
  it.each([
    ["own PPV, window open", ppv, 90, true, { countdown: "1:30", copyDraft: true, unsendPpv: true }],
    ["own PPV, window closed", ppv, 0, true, { countdown: null, copyDraft: true, unsendPpv: false }],
    ["own free, window open", free, 65, true, { countdown: "1:05", copyDraft: false, unsendPpv: false }],
    ["own free, window closed", free, 0, true, { countdown: null, copyDraft: false, unsendPpv: false }],
    ["own tip (never priced)", tip, 30, true, { countdown: "0:30", copyDraft: false, unsendPpv: false }],
    ["fan's PPV, window open", ppv, 90, false, { countdown: null, copyDraft: false, unsendPpv: false }],
    ["fan's free", free, 0, false, { countdown: null, copyDraft: false, unsendPpv: false }],
  ] as const)("%s", (_, m, left, own, want) => {
    expect(bubbleExtras(m, left, own)).toEqual(want);
  });
});

describe("scriptFromMessage: the bubble as the script applyScript applies (text, price, media ids)", () => {
  const base = { taggedUsers: [], gifId: null };
  it.each([
    ["a PPV with media and previews", { id: 1, text: "<p>hey babe</p>", price: 5, media: [{ id: 61 }, { id: "62" }], previews: [61], lockedText: true },
      { text: "hey babe", displayText: "<p>hey babe</p>", price: 5, lockedText: true, media: [{ id: 61 }, { id: 62 }], previews: [61] }],
    ["formatted text keeps OF's markup", { id: 2, text: "<p><strong>bold</strong></p>", price: 3, media: [] },
      { text: "bold", displayText: "<p><strong>bold</strong></p>", price: 3, lockedText: false, media: [], previews: [] }],
    ["free: price 0 (applyScript then drops previews and locked text)", { id: 3, text: "<p>free</p>", price: 0, media: [{ id: 7 }], previews: [7], lockedText: true },
      { text: "free", displayText: "<p>free</p>", price: 0, lockedText: true, media: [{ id: 7 }], previews: [7] }],
    ["a tip is never priced", { id: 4, text: "", price: 5, isTip: true, media: [] },
      { text: "", displayText: "", price: 0, lockedText: false, media: [], previews: [] }],
  ] as const)("%s", (_, m, want) => {
    expect(scriptFromMessage(m as unknown as MenuMessage)).toEqual({ ...want, ...base });
  });

  it("a tagged PPV keeps its tags (OF's releaseForms): the draft's tags, sent again as rfTag / rfGuest / rfPartner", () => {
    const m = { id: 5, text: "<p>us</p>", price: 9, media: [{ id: 61 }], releaseForms: [
      { id: 71, name: "Co", type: "user" }, { id: 72, name: "Guest", type: "guest" }, { id: 73, name: "Form", type: "document" }, { id: 74 }] } as unknown as MenuMessage;
    const s = scriptFromMessage(m);
    expect([s.taggedUsers, s.tags]).toEqual([[71, 74], [
      { id: 71, type: "user", name: "Co" }, { id: 72, type: "guest", name: "Guest" }, { id: 73, type: "document", name: "Form" }, { id: 74, type: "user", name: "" }]]);
    applyScript(sessionStorage, "acc", "2006", s, null);
    const body = collectMessage("us", loadChatDraft(sessionStorage, "acc", "2006"));
    expect(body).toMatchObject({ price: 9, media_files: [61], tagged_users: [71, 74], rf_guest: [72], rf_partner: [73] });
  });
});

describe("the own bubble's extras on the chat page", () => {
  const ME = { id: 1 };
  const ppv = { id: 501, text: "<p>ppv</p>", createdAt: "2026-10-10T12:01:00Z", fromUser: ME, price: 5, media: [{ id: 61 }], cancelSeconds: 90 } as unknown as MenuMessage;
  const old = { ...ppv, id: 502, cancelSeconds: 0 } as MenuMessage;
  const theirsPpv = { ...ppv, id: 503, fromUser: { id: 2006 } } as unknown as MenuMessage;
  const msgs = [ppv, old, theirsPpv];
  const draw = (over: Partial<MessageMenuContext> = {}, left: Record<string, number> = { 501: 90 }) => {
    const d = page("chat");
    applyData(d, "messages/chat", { chat: "2006", thread: { fan: FAN, messages: msgs } });
    const c = ctx({ message: (id) => msgs.find((m) => String(m.id) === id), left: (m) => left[String(m.id)] ?? 0, ...over });
    unbinds.push(bindMessageMenu(d, c));
    return { d, left };
  };
  const extras = (d: Document, id: number) =>
    [...d.querySelectorAll<HTMLElement>(`[data-oi-msg="${id}"] [data-oi-bubble]`)].map((e) => [e.dataset.oiBubble, e.textContent, e.title === NOT_YET, e.hasAttribute("data-oi-wired")]);
  const btn = (d: Document, id: number, key: string) => d.querySelector<HTMLElement>(`[data-oi-msg="${id}"] [data-oi-bubble='${key}']`)!;

  it("own PPV with 90s left: Countdown 1:30 (ticking), Copy as draft, Unsend PPV, each Wired with the Not-yet title; expired: Copy as draft only; the fan's: none", () => {
    vi.useFakeTimers();
    try {
      const { d, left } = draw();
      expect(extras(d, 501)).toEqual([["countdown", "1:30", true, true], ["copy-draft", "Copy as draft", true, true], ["unsend-ppv", "Unsend PPV", true, true]]);
      expect(d.querySelector(`[data-oi-msg="501"] [data-oi-bubble='countdown']`)!.getAttribute("aria-label")).toBe("Countdown");
      expect(extras(d, 502)).toEqual([["copy-draft", "Copy as draft", true, true]]);
      expect(extras(d, 503)).toEqual([]);
      left[501] = 89;
      vi.advanceTimersByTime(1000);
      expect(extras(d, 501)[0][1]).toBe("1:29");
      left[501] = 0;
      vi.advanceTimersByTime(1000);
      expect(extras(d, 501).map((e) => e[0])).toEqual(["copy-draft"]);
    } finally {
      vi.useRealTimers();
    }
  });

  it("Copy as draft fills this chat's draft (text, price, media; a reply kept) and sends nothing", () => {
    const w = writes();
    const { d } = draw({ writes: w });
    sessionStorage.setItem(chatDraftKey("acc", "2006"), JSON.stringify({ text: "old", media_files: [9], thumbs: ["x"], reply_to: "11", reply_text: "hi", giphy_id: "g" }));
    const heard = vi.fn((e: Event) => (e as CustomEvent).detail);
    d.addEventListener(DRAFT_EVENT, heard);
    btn(d, 501, "copy-draft").click();
    expect(heard).toHaveReturnedWith({ text: true });
    const draft = loadChatDraft(sessionStorage, "acc", "2006");
    expect(draft).toEqual({ text: "ppv", price: 5, media_files: [61], thumbs: [""], reply_to: "11", reply_text: "hi" });
    expect(Object.values(w).every((f) => f.mock.calls.length === 0)).toBe(true);
  });

  it("Unsend PPV asks (the button expanded while it is open); Cancel sends nothing; Unsend unsends this message once and notes Unsent", async () => {
    const w = writes();
    const { d } = draw({ writes: w });
    btn(d, 501, "unsend-ppv").click();
    expect([modal(d)!.textContent?.includes("Unsend this message?"), btn(d, 501, "unsend-ppv").getAttribute("aria-expanded")]).toEqual([true, "true"]);
    button(d, "Cancel").click();
    await flush();
    expect([modal(d), w.unsend.mock.calls.length, btn(d, 501, "unsend-ppv").getAttribute("aria-expanded")]).toEqual([null, 0, "false"]);
    btn(d, 501, "unsend-ppv").click();
    button(d, "Unsend").click();
    await flush();
    expect(w.unsend.mock.calls).toEqual([[ppv]]);
    expect([modal(d), d.getElementById("oi-note")!.textContent]).toEqual([null, "Unsent"]);
    expect(Object.values(w).filter((f) => f !== w.unsend).every((f) => f.mock.calls.length === 0)).toBe(true);
  });

  it("a stale Unsend PPV (the window closed since its draw) sends nothing and goes; with no model nothing is sent", async () => {
    const w = writes();
    const { d, left } = draw({ writes: w });
    const stale = btn(d, 501, "unsend-ppv");
    left[501] = 0;
    stale.click();
    await flush();
    expect([modal(d), w.unsend.mock.calls.length, stale.isConnected]).toEqual([null, 0, false]);
    unbinds.pop()!();
    const none = draw({ writes: null }).d;
    btn(none, 501, "unsend-ppv").click();
    expect([modal(none), none.getElementById("oi-note")!.textContent]).toEqual([null, SELECT_MODEL]);
  });

  it("a refused unsend: the dialog closes, a red note under the bubble", async () => {
    const w = writes({ unsend: vi.fn(() => Promise.reject(new Error("502 Bad Gateway"))) });
    const { d } = draw({ writes: w });
    btn(d, 501, "unsend-ppv").click();
    button(d, "Unsend").click();
    await flush();
    await flush();
    const n = d.getElementById("oi-note")!;
    expect([modal(d), n.textContent, n.style.color, n.previousElementSibling?.getAttribute("data-oi-msg")]).toEqual([null, "Could not unsend: 502 Bad Gateway", "rgb(255, 69, 69)", "501"]);
  });

  it("one unsend path: the menu's Unsend refused shows the same red note; a bubble drawn again only on the next redraw gets it there", async () => {
    let fail!: (e: Error) => void;
    const w = writes({ unsend: vi.fn(() => new Promise((_, rej) => (fail = rej))) });
    const { d } = draw({ writes: w });
    openMenu(d, ppv);
    pick(d, "unsend");
    button(d, "Unsend").click();
    const bubble = d.querySelector<HTMLElement>('[data-oi-msg="501"]')!;
    const [parent, next] = [bubble.parentElement!, bubble.nextSibling];
    bubble.remove();
    fail(new Error("502 Bad Gateway"));
    await flush();
    await flush();
    expect([modal(d), d.getElementById("oi-note")]).toEqual([null, null]);
    parent.insertBefore(bubble, next);
    await flush();
    const n = d.getElementById("oi-note")!;
    expect([n.textContent, n.style.color, n.previousElementSibling?.getAttribute("data-oi-msg")]).toEqual(["Could not unsend: 502 Bad Gateway", "rgb(255, 69, 69)", "501"]);
  });

  it("OFM_NEW_WRITES_ENABLED off: no extra drawn on any bubble (main); the menu's own Unsend stays", () => {
    const w = writes();
    const { d } = draw({ writes: w, newWrites: false });
    expect([extras(d, 501), extras(d, 502), d.querySelector("[data-oi-bubble-extras]")]).toEqual([[], [], null]);
    expect(openMenu(d, ppv).map((i) => i.dataset.oiMsgAction)).toContain("unsend");
  });

  it("an Unsend PPV confirm open when the switch goes off: the rebind closes it, its Unsend sends nothing, no extra stays", async () => {
    const w = writes();
    const { d } = draw({ writes: w });
    btn(d, 501, "unsend-ppv").click();
    const yes = button(d, "Unsend");
    unbinds.pop()!();
    unbinds.push(bindMessageMenu(d, ctx({ writes: w, message: (id) => msgs.find((m) => String(m.id) === id), left: () => 90, newWrites: false })));
    expect([modal(d), d.querySelector("[data-oi-bubble-extras]")]).toEqual([null, null]);
    yes.click();
    await flush();
    expect(w.unsend.mock.calls.length).toBe(0);
  });

  it("OFM_NEW_WRITES_ENABLED off: no ticker runs; the open menu's Unsend countdown ticks only while it is open", () => {
    const every = vi.spyOn(window, "setInterval");
    const stop = vi.spyOn(window, "clearInterval");
    const { d } = draw({ newWrites: false });
    expect(every).not.toHaveBeenCalled();
    openMenu(d, ppv);
    expect(every).toHaveBeenCalledTimes(1);
    const id = every.mock.results[0].value;
    d.body.click();
    expect(stop).toHaveBeenCalledWith(id);
  });

  it.each([
    ["resolves null (useUnsendMessage sent nothing)", () => Promise.resolve(null), "Could not unsend: nothing was sent"],
    ["is not confirmed by OF (useUnsendMessage throws on a 2xx without success: true)", () => Promise.reject(new Error(NOT_CONFIRMED)), `Could not unsend: ${NOT_CONFIRMED}`],
  ])("an unsend that %s: no Unsent, a red note under the bubble", async (_, reply, text) => {
    const w = writes({ unsend: vi.fn(reply) });
    const { d } = draw({ writes: w });
    btn(d, 501, "unsend-ppv").click();
    button(d, "Unsend").click();
    await flush();
    await flush();
    const n = d.getElementById("oi-note")!;
    expect([modal(d), n.textContent, n.style.color, n.previousElementSibling?.getAttribute("data-oi-msg")]).toEqual([null, text, "rgb(255, 69, 69)", "501"]);
  });

  it("the window closes while the confirm stands open: Unsend sends nothing, a red note says so", async () => {
    const w = writes();
    const { d, left } = draw({ writes: w });
    btn(d, 501, "unsend-ppv").click();
    left[501] = 0;
    button(d, "Unsend").click();
    await flush();
    const n = d.getElementById("oi-note")!;
    expect([modal(d), w.unsend.mock.calls.length, n.textContent, n.style.color]).toEqual([null, 0, "The unsend window has closed", "rgb(255, 69, 69)"]);
  });

  it("a bubble drawn after the bind: its ⋮ is Wired on the redraw, as the bind's", async () => {
    const { d } = draw();
    const more = d.querySelector<HTMLElement>('[data-oi-msg="501"] button[data-oi-msg-menu]')!;
    const copy = more.closest("[data-oi-msg]")!.cloneNode(true) as HTMLElement;
    copy.dataset.oiMsg = "502";
    copy.querySelector("button[data-oi-msg-menu]")!.removeAttribute("data-oi-wired");
    d.querySelector('[data-oi-msg="502"]')!.replaceWith(copy);
    await flush();
    expect(copy.querySelector("button[data-oi-msg-menu]")!.hasAttribute("data-oi-wired")).toBe(true);
  });

  it("the open menu's Unsend m:ss ticks on the same second's draw and goes when the window closes", () => {
    vi.useFakeTimers();
    try {
      const { d, left } = draw();
      openMenu(d, ppv);
      const item = () => d.querySelector("#oi-msg-menu [data-oi-msg-action='unsend']")?.textContent?.trim() ?? null;
      expect(item()).toBe("Unsend 1:30");
      left[501] = 75;
      vi.advanceTimersByTime(1000);
      expect(item()).toBe("Unsend 1:15");
      left[501] = 0;
      vi.advanceTimersByTime(1000);
      expect(item()).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });
});
