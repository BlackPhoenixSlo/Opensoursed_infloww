import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { QueryClient } from "@tanstack/react-query";
import { afterEach, describe, expect, it, vi } from "vitest";
import { applyData, rowsOf } from "./ofMirrorData";
import { chatDraftKey, collectMessage, DRAFT_EVENT, loadChatDraft } from "./ofMirrorChat";
import { bindMessageMenu, COPIED_TEXT, countdown, messageItems, messageWrites, stampReads, unsendLeft, type MenuMessage, type MessageRead, type MessageMenuContext, type MessageWrites } from "./ofMirrorMessageMenu";
import { NOT_YET, SELECT_MODEL } from "./ofMirrorWrites";
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
  ...over,
});
/** The chat page with the fixture thread drawn (as useOfData does) and the menus bound. */
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
    expect(messageItems(theirs, { mine: false, limited: false, left: 0 }).map((i) => [i.label, !!i.off])).toEqual([["Copy message text", false], ["Like", false], ["Reply", false], ["Bookmark", false], ["Pin", false], ["Hide", false], ["Report", true]]);
    expect(messageItems({ ...theirs, canReport: undefined }, { mine: false, limited: false, left: 0 }).map((i) => i.key)).not.toContain("report");
    expect(messageItems({ ...theirs, canReport: false }, { mine: false, limited: false, left: 0 }).map((i) => i.key)).not.toContain("report");
    const own = { ...mine, media: [{ id: 1, type: "photo" }] } as MenuMessage;
    const items = messageItems(own, { mine: true, limited: false, left: 125 });
    expect(items.map((i) => [i.label, !!i.off])).toEqual([["Copy message text", false], ["Reply", false], ["Bookmark", false], ["Pin", false], ["Forward", true], ["Add a tag", true], ["Unsend 2:05", false]]);
    expect(countdown(59)).toBe("0:59");
  });

  it("OF's conditions: no Like on a restricted or blocked fan's message, no Copy on locked text, Unlike / Unpin / Unbookmark by state, Add to collection (off) once bookmarked, no Unsend once its window is over", () => {
    expect(messageItems(theirs, { mine: false, limited: true, left: 0 }).map((i) => i.key)).not.toContain("like");
    expect(messageItems({ ...theirs, lockedText: true }, { mine: false, limited: false, left: 0 }).map((i) => i.key)).not.toContain("copy");
    const labels = messageItems({ ...theirs, isLiked: true, isPinned: true, isAddedToBookmarks: true }, { mine: false, limited: false, left: 0 }).map((i) => i.label);
    expect(labels).toEqual(expect.arrayContaining(["Unlike", "Unpin", "Unbookmark", "Add to collection"]));
    expect(messageItems({ ...theirs, canBePinned: false }, { mine: false, limited: false, left: 0 }).map((i) => i.key)).not.toContain("pin");
    expect(messageItems(mine, { mine: true, limited: false, left: 0 }).map((i) => i.key)).not.toContain("unsend");
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

  it("Unsend asks first, then sends; Report is disabled (NOT_YET) and sends nothing", async () => {
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
    const report = d.querySelector<HTMLElement>("#oi-msg-menu [data-oi-msg-action='report']")!;
    expect([report.getAttribute("aria-disabled"), report.title]).toEqual(["true", NOT_YET]);
    report.click();
    await flush();
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
    // 40s later an older page arrives: the same message, the same value read at 0.
    stampReads(reads, [a, { id: 2, cancelSeconds: 0 } as MenuMessage], 40_000);
    expect(unsendLeft(reads, a, 40_000)).toBe(60);
    expect(unsendLeft(reads, { ...a, isLiked: true }, 40_000)).toBe(60); // a like's patched copy
    // A refetch at 50s reads 50 left.
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
    expect([menu.style.left, menu.style.maxHeight, menu.style.overflow]).toEqual(["162px", "384px", "auto"]); // 390 - 220 - 8
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
});
