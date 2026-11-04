import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it, vi } from "vitest";
import {
  applyScript,
  bindChat,
  chatDraftKey,
  collectMessage,
  loadChatDraft,
  loadVaultPick,
  NO_CHAT,
  sendPath,
  vaultPickKey,
  type PickedScript,
} from "./ofMirrorChat";
import { EMPTY_MESSAGE, readPrice, type ChatContext, type ChatDraft } from "./ofMirrorChatShared";
import { applyData } from "./ofMirrorData";
import { bindWrites, localIso, READ_ONLY, SELECT_MODEL, TOO_SOON } from "./ofMirrorWrites";
import type { VaultMedia, VaultUploadResp } from "./relay";

/** A committed messages capture (path under of-mirror/pages/messages). */
const loadPage = (page: string) => {
  document.documentElement.innerHTML = readFileSync(resolve(__dirname, `../public/of-mirror/pages/messages/${page}.html`), "utf8");
  return document;
};
const memoryStorage = (): Storage => {
  const m = new Map<string, string>();
  return {
    get length() {
      return m.size;
    },
    key: (i) => [...m.keys()][i] ?? null,
    getItem: (k) => m.get(k) ?? null,
    setItem: (k, v) => void m.set(k, String(v)),
    removeItem: (k) => void m.delete(k),
    clear: () => m.clear(),
  };
};
const flush = () => new Promise((r) => setTimeout(r, 0));
const EDITOR = "[contenteditable][aria-label='Textbox field']";
const SEND = "button[at-attr='send_btn']";
const editor = (d: Document) => d.querySelector<HTMLElement>(EDITOR)!;
const send = (d: Document) => d.querySelector<HTMLButtonElement>(SEND)!;
const type = (d: Document, text: string) => {
  editor(d).innerHTML = text.split("\n").map((l) => `<p>${l || "<br>"}</p>`).join("");
  editor(d).dispatchEvent(new Event("input", { bubbles: true }));
};
const noteText = (d: Document) => d.getElementById("oi-note")?.textContent;
const handlers = (over: Partial<ChatContext["handlers"] & object> = {}) => ({
  send: vi.fn((_path: string, _body: object) => Promise.resolve({ id: 1 })),
  upload: vi.fn((_file: File) => Promise.resolve({ ready: true, deduped: false, vault_id: null, send_with: [{ processId: "p1" }] } as VaultUploadResp)),
  mute: vi.fn((_on: boolean) => Promise.resolve({ success: true })),
  hide: vi.fn(() => Promise.resolve({ success: true })),
  confirm: vi.fn((_text: string) => true),
  navigate: vi.fn(),
  ...over,
});
const ACCOUNT = "acct-1";
const CHAT = "9001";
const ctxOf = (h: ReturnType<typeof handlers> | null, storage: Storage, over: Partial<ChatContext> = {}): ChatContext => ({
  handlers: h,
  storage,
  accountId: ACCOUNT,
  chat: CHAT,
  fan: { name: "Fan A", muted: false },
  ...over,
});
const draft = (over: Partial<ChatDraft> = {}): ChatDraft => ({ text: "", media_files: [], thumbs: [], ...over });
const saveDraft = (s: Storage, d: ChatDraft) => s.setItem(chatDraftKey(ACCOUNT, CHAT), JSON.stringify(d));

describe("readPrice", () => {
  it("empty is free; a price is at least $3 with up to two decimals", () => {
    expect(readPrice("")).toBe(0);
    expect(readPrice(" 0 ")).toBe(0);
    expect(readPrice("5")).toBe(5);
    expect(readPrice("$12.50")).toBe(12.5);
    expect(readPrice("2.99")).toBeNull();
    expect(readPrice("abc")).toBeNull();
    expect(readPrice("5.123")).toBeNull();
  });
});

describe("collectMessage", () => {
  it("text gives the Relay's send body; media alone is enough", () => {
    expect(collectMessage("  hi there \n", draft())).toEqual({ text: "hi there", price: 0, media_files: [] });
    expect(collectMessage("", draft({ media_files: [61, 62], price: 9 }))).toEqual({ text: "", price: 9, media_files: [61, 62] });
    expect(collectMessage(" ", draft())).toBe(EMPTY_MESSAGE);
  });

  it("a script's free previews and locked text go with a price only, the previews among the media", () => {
    const d = draft({ media_files: [61, 62], previews: [61, 99], locked_text: true });
    expect(collectMessage("ppv", { ...d, price: 9 })).toEqual({ text: "ppv", price: 9, media_files: [61, 62], previews: [61], locked_text: true });
    expect(collectMessage("free", d)).toEqual({ text: "free", price: 0, media_files: [61, 62] });
  });

  it("a schedule adds scheduled_date and the queue path; a stale one gives the note", () => {
    const now = new Date(2026, 9, 12, 10, 0);
    const at = localIso(new Date(2026, 9, 13, 18, 30));
    const body = collectMessage("later", draft({ scheduled_date: at }), now);
    expect(body).toEqual({ text: "later", price: 0, media_files: [], scheduled_date: at });
    expect(sendPath(CHAT, body as never)).toBe(`/api/of/v2/chats/${CHAT}/messages/scheduled`);
    expect(sendPath(CHAT, { text: "x", price: 0, media_files: [] })).toBe(`/api/of/v2/chats/${CHAT}/messages`);
    expect(collectMessage("later", draft({ scheduled_date: localIso(new Date(2026, 9, 12, 9, 0)) }), now)).toBe(TOO_SOON);
  });
});

describe("applyScript: a Messages Pro script beside the chat", () => {
  const script = (over: Partial<PickedScript> = {}): PickedScript => ({ text: "Script line", price: 0, lockedText: false, media: [], previews: [], taggedUsers: [], ...over });

  it("replaces the draft's text, media, price and extras (a reply and a schedule stay), and the composer shows it", () => {
    const doc = loadPage("chat");
    const storage = memoryStorage();
    saveDraft(storage, draft({ text: "old", html: "<p>old</p>", price: 5, media_files: [7], thumbs: ["t"], giphy_id: "g", reply_to: "55", reply_text: "hi", scheduled_date: "2026-10-21T13:00:00+02:00" }));
    bindChat(doc, "messages/chat", ctxOf(handlers(), storage));
    expect(editor(doc).textContent).toBe("old");
    applyScript(storage, ACCOUNT, CHAT, script({ text: "Hey\nthere", price: 12, lockedText: true, media: [{ id: 61 }, { id: 62 }], previews: [61], taggedUsers: [4] }), doc);
    expect(loadChatDraft(storage, ACCOUNT, CHAT)).toEqual(
      draft({ text: "Hey\nthere", price: 12, media_files: [61, 62], thumbs: ["", ""], previews: [61], locked_text: true, tags: [{ id: 4, type: "user", name: "" }], reply_to: "55", reply_text: "hi", scheduled_date: "2026-10-21T13:00:00+02:00" }),
    );
    expect([...editor(doc).querySelectorAll("p")].map((p) => p.textContent)).toEqual(["Hey", "there"]);
    expect(doc.getElementById("oi-chat-summary")!.textContent).toContain("Price: $12");
    expect(send(doc).disabled).toBe(false);
  });

  it("a free script drops the price, previews and locked text; its GIF rides along", () => {
    const storage = memoryStorage();
    saveDraft(storage, draft({ text: "x", price: 9, previews: [1], locked_text: true }));
    applyScript(storage, ACCOUNT, CHAT, script({ previews: [1], lockedText: true, gifId: "gif1", gifUrl: "https://g/1.gif" }), null);
    expect(loadChatDraft(storage, ACCOUNT, CHAT)).toEqual(draft({ text: "Script line", giphy_id: "gif1", giphy_thumb: "https://g/1.gif" }));
  });
});

describe("bindChat: the composer", () => {
  it("typing enables Send; Send posts exactly the body to the chat, then clears the draft", async () => {
    const doc = loadPage("chat");
    const storage = memoryStorage();
    const h = handlers();
    bindChat(doc, "messages/chat", ctxOf(h, storage));
    expect(send(doc).disabled).toBe(true);
    type(doc, "Synthetic hello");
    expect(send(doc).disabled).toBe(false);
    expect(loadChatDraft(storage, ACCOUNT, CHAT).text).toBe("Synthetic hello");
    send(doc).click();
    expect(h.send).toHaveBeenCalledTimes(1);
    expect(h.send).toHaveBeenCalledWith(`/api/of/v2/chats/${CHAT}/messages`, { text: "Synthetic hello", price: 0, media_files: [] });
    expect(h.confirm).not.toHaveBeenCalled();
    await flush();
    expect(storage.getItem(chatDraftKey(ACCOUNT, CHAT))).toBeNull();
    expect(editor(doc).textContent).toBe("");
    expect(noteText(doc)).toBe("Sent");
  });

  it("restores the draft and names its extras; Clear drops them", () => {
    const doc = loadPage("chat");
    const storage = memoryStorage();
    saveDraft(storage, draft({ text: "kept", price: 7, media_files: [61], thumbs: ["t"] }));
    bindChat(doc, "messages/chat", ctxOf(handlers(), storage));
    expect(editor(doc).textContent).toBe("kept");
    const summary = doc.getElementById("oi-chat-summary")!;
    expect(summary.textContent).toContain("Price: $7");
    expect(summary.textContent).toContain("1 media");
    summary.querySelector<HTMLElement>("[data-oi-clear]")!.click();
    expect(loadChatDraft(storage, ACCOUNT, CHAT)).toEqual(draft({ text: "kept" }));
    expect(doc.getElementById("oi-chat-summary")).toBeNull();
  });

  it("a priced message asks first, naming the fan and price; a refusal sends nothing", () => {
    const doc = loadPage("chat");
    const storage = memoryStorage();
    saveDraft(storage, draft({ text: "ppv", price: 12, media_files: [61], thumbs: ["t"] }));
    const h = handlers({ confirm: vi.fn(() => false) });
    bindChat(doc, "messages/chat", ctxOf(h, storage));
    send(doc).click();
    expect(h.confirm).toHaveBeenCalledWith("Send this message to Fan A for $12?");
    expect(h.send).not.toHaveBeenCalled();
    expect(loadChatDraft(storage, ACCOUNT, CHAT).price).toBe(12);
  });

  it("a price with cents shows them, as OF's formatPrice: the summary and the confirm say $12.50", () => {
    const doc = loadPage("chat");
    const storage = memoryStorage();
    saveDraft(storage, draft({ text: "ppv", price: 12.5, media_files: [61], thumbs: ["t"] }));
    const h = handlers({ confirm: vi.fn(() => false) });
    bindChat(doc, "messages/chat", ctxOf(h, storage));
    expect(doc.getElementById("oi-chat-summary")!.textContent).toContain("Price: $12.50");
    send(doc).click();
    expect(h.confirm).toHaveBeenCalledWith("Send this message to Fan A for $12.50?");
  });

  it("a confirmed PPV sends price and media; a scheduled one goes to the scheduled route", () => {
    const doc = loadPage("chat");
    const storage = memoryStorage();
    const at = localIso(new Date(Date.now() + 86_400_000));
    saveDraft(storage, draft({ text: "ppv", price: 12, media_files: [61], thumbs: ["t"], scheduled_date: at }));
    const h = handlers();
    bindChat(doc, "messages/chat", ctxOf(h, storage));
    send(doc).click();
    expect(h.send).toHaveBeenCalledWith(`/api/of/v2/chats/${CHAT}/messages/scheduled`, { text: "ppv", price: 12, media_files: [61], scheduled_date: at });
  });

  it("a Relay failure keeps the draft and shows its text in red", async () => {
    const doc = loadPage("chat");
    const storage = memoryStorage();
    const h = handlers({ send: vi.fn(() => Promise.reject(new Error("This fan already paid for video in this message."))) });
    bindChat(doc, "messages/chat", ctxOf(h, storage));
    type(doc, "again");
    send(doc).click();
    await flush();
    expect(noteText(doc)).toBe("Could not send: This fan already paid for video in this message.");
    expect(loadChatDraft(storage, ACCOUNT, CHAT).text).toBe("again");
    expect(send(doc).disabled).toBe(false);
  });

  it("the example chat (no ?chat=) and All-Creators scope send nothing", () => {
    let doc = loadPage("chat");
    const h = handlers();
    bindChat(doc, "messages/chat", ctxOf(h, memoryStorage(), { chat: null }));
    type(doc, "x");
    send(doc).click();
    expect(noteText(doc)).toBe(NO_CHAT);
    doc = loadPage("chat");
    const storage = memoryStorage();
    bindChat(doc, "messages/chat", ctxOf(null, storage));
    type(doc, "x");
    send(doc).click();
    expect(noteText(doc)).toBe(SELECT_MODEL);
    expect(h.send).not.toHaveBeenCalled();
    expect(storage.length).toBe(0);
  });

  it("Send is not the click fallback's (no Read-only note beside bindWrites)", () => {
    const doc = loadPage("chat");
    const h = handlers();
    bindWrites(doc, "messages/chat", null);
    bindChat(doc, "messages/chat", ctxOf(h, memoryStorage()));
    type(doc, "x");
    send(doc).click();
    expect(h.send).toHaveBeenCalledTimes(1);
    expect(noteText(doc)).not.toBe(READ_ONLY);
  });

  it("Add media uploads the picked file and sends its claim with the text; Send waits while it uploads", async () => {
    const doc = loadPage("chat");
    const storage = memoryStorage();
    let done!: (r: VaultUploadResp) => void;
    const h = handlers({ upload: vi.fn(() => new Promise<VaultUploadResp>((r) => (done = r))) });
    bindChat(doc, "messages/chat", ctxOf(h, storage));
    const picker = doc.querySelector<HTMLInputElement>("input[type='file'][data-oi-wired]")!;
    expect(doc.querySelector("button[aria-label='Add media']")!.hasAttribute("data-oi-wired")).toBe(true);
    const file = new File(["x"], "a.jpg", { type: "image/jpeg" });
    Object.defineProperty(picker, "files", { value: [file], configurable: true });
    picker.dispatchEvent(new Event("change"));
    expect(h.upload).toHaveBeenCalledWith(file);
    type(doc, "with a pic");
    expect(send(doc).disabled).toBe(true);
    done({ ready: true, deduped: false, vault_id: null, send_with: [{ processId: "p1" }] });
    await flush();
    await flush();
    expect(loadChatDraft(storage, ACCOUNT, CHAT).media_files).toEqual([{ processId: "p1" }]);
    expect(send(doc).disabled).toBe(false);
    send(doc).click();
    expect(h.send).toHaveBeenCalledWith(`/api/of/v2/chats/${CHAT}/messages`, { text: "with a pic", price: 0, media_files: [{ processId: "p1" }] });
  });

  it("Add media with no chat open or in All-Creators scope uploads nothing", () => {
    let doc = loadPage("chat");
    const h = handlers();
    bindChat(doc, "messages/chat", ctxOf(h, memoryStorage(), { chat: null }));
    doc.querySelector<HTMLElement>("button[aria-label='Add media']")!.click();
    expect(noteText(doc)).toBe(NO_CHAT);
    doc = loadPage("chat");
    bindChat(doc, "messages/chat", ctxOf(null, memoryStorage()));
    doc.querySelector<HTMLElement>("button[aria-label='Add media']")!.click();
    expect(noteText(doc)).toBe(SELECT_MODEL);
    expect(h.upload).not.toHaveBeenCalled();
  });

  it("the header's bell follows the real state and toggles it", async () => {
    const doc = loadPage("chat");
    const h = handlers();
    bindChat(doc, "messages/chat", ctxOf(h, memoryStorage()));
    const bell = doc.querySelector<HTMLButtonElement>("button[at-attr='mute_chat']")!;
    expect(bell.getAttribute("aria-label")).toBe("Mute notifications");
    bell.click();
    expect(h.mute).toHaveBeenCalledWith(true);
    await flush();
    expect(noteText(doc)).toBe("Muted");
  });
});

describe("bindChat: the dialogs", () => {
  it("Message price: Save is enabled for a valid price and keeps it, then goes back to the chat", () => {
    const doc = loadPage("chat/state-price");
    const storage = memoryStorage();
    const h = handlers();
    bindChat(doc, "messages/chat/state-price", ctxOf(h, storage));
    const input = doc.querySelector<HTMLInputElement>(".modal.show input[at-attr='input']")!;
    const save = doc.querySelector<HTMLButtonElement>(".modal.show .modal-footer button")!;
    input.value = "2";
    input.dispatchEvent(new Event("input", { bubbles: true }));
    expect(save.disabled).toBe(true);
    input.value = "15";
    input.dispatchEvent(new Event("input", { bubbles: true }));
    expect(save.disabled).toBe(false);
    save.click();
    expect(loadChatDraft(storage, ACCOUNT, CHAT).price).toBe(15);
    expect(h.navigate).toHaveBeenCalledWith(`/of-manager/messages/chat?chat=${CHAT}`);
  });

  it("Scheduled messages: Next keeps the picked moment (local ISO) on the draft", () => {
    const doc = loadPage("chat/state-schedule");
    const storage = memoryStorage();
    const h = handlers();
    bindChat(doc, "messages/chat/state-schedule", ctxOf(h, storage));
    const tab = doc.querySelector<HTMLElement>(".vdatetime-popup__tab.time")!;
    tab.textContent = "11:59 PM";
    doc.querySelector<HTMLButtonElement>(".vdatetime-popup__actions__button--confirm button")!.click();
    const saved = loadChatDraft(storage, ACCOUNT, CHAT).scheduled_date!;
    expect(saved).toMatch(/^\d{4}-\d{2}-\d{2}T23:59:00[+-]\d{2}:\d{2}$/);
    expect(h.navigate).toHaveBeenCalledWith(`/of-manager/messages/chat?chat=${CHAT}`);
  });

  it("Add media from vault, as OF's: a tile only ticks (OF's \"N / 40 Selected\" bar); Add attaches the ticks and goes back", () => {
    const doc = loadPage("chat/state-vault");
    const storage = memoryStorage();
    const h = handlers();
    const media = [{ id: 61, type: "photo", createdAt: "2026-10-01T10:00:00Z" } as VaultMedia, { id: 62, type: "photo" } as VaultMedia];
    applyData(doc, "messages/chat/state-vault", { vaultMedia: media, picked: [] });
    const un = bindChat(doc, "messages/chat/state-vault", ctxOf(h, storage));
    const bar = () => doc.querySelector<HTMLElement>(".modal.show [data-oi-vault-bar]");
    expect(bar()).toBeNull();
    const t61 = doc.querySelector<HTMLElement>("[data-oi-media='61']")!;
    const t62 = doc.querySelector<HTMLElement>("[data-oi-media='62']")!;
    t61.click();
    t62.click();
    // Nothing is attached by a tick: the draft stays empty until Add.
    expect(loadChatDraft(storage, ACCOUNT, CHAT).media_files).toEqual([]);
    expect(t62.classList.contains("selected")).toBe(true);
    expect(bar()!.querySelector(".b-row-selected__text")!.textContent!.trim()).toBe("2 / 40 Selected");
    t61.click();
    expect(t61.classList.contains("selected")).toBe(false);
    expect(bar()!.querySelector(".b-row-selected__text")!.textContent!.trim()).toBe("1 / 40 Selected");
    expect(loadVaultPick(storage, vaultPickKey(ACCOUNT, "messages/chat/state-vault", CHAT)).ids).toEqual([62]);
    bar()!.querySelector<HTMLElement>("button[data-oi-vault-add]")!.click();
    expect(loadChatDraft(storage, ACCOUNT, CHAT).media_files).toEqual([62]);
    expect(h.navigate).toHaveBeenCalledWith(`/of-manager/messages/chat?chat=${CHAT}`);
    expect(loadVaultPick(storage, vaultPickKey(ACCOUNT, "messages/chat/state-vault", CHAT)).ids).toEqual([]);
    un();
  });

  it("Add media from vault: the folder Search opens the dialog with ?slist= as New post's, the chat kept", async () => {
    vi.useFakeTimers();
    const doc = loadPage("chat/state-vault");
    const h = handlers();
    const un = bindChat(doc, "messages/chat/state-vault", ctxOf(h, memoryStorage()));
    const search = doc.querySelector<HTMLButtonElement>(".modal.show .l-sidebar-column .g-page__header button[aria-label='Search']")!;
    // The generator greys it ("Not available in Inflowwww yet"); the bind runs it.
    expect([search.hasAttribute("data-oi-wired"), search.disabled, search.title]).toEqual([true, false, ""]);
    search.click();
    const field = doc.querySelector<HTMLInputElement>("input[aria-label='Search folders']")!;
    field.value = "alp";
    field.dispatchEvent(new Event("input"));
    await vi.advanceTimersByTimeAsync(400);
    expect(h.navigate).toHaveBeenCalledWith(`/of-manager/messages/chat/state-vault?slist=alp&chat=${CHAT}`);
    un();
    vi.useRealTimers();
  });

  it("Add media from vault: Close (back on the chat) and the bar's Clear attach nothing and drop the ticks", () => {
    const storage = memoryStorage();
    const h = handlers();
    let doc = loadPage("chat/state-vault");
    applyData(doc, "messages/chat/state-vault", { vaultMedia: [{ id: 62, type: "photo" } as VaultMedia], picked: [] });
    let un = bindChat(doc, "messages/chat/state-vault", ctxOf(h, storage));
    const tile = () => doc.querySelector<HTMLElement>("[data-oi-media='62']")!;
    tile().click();
    doc.querySelector<HTMLElement>("[data-oi-vault-clear]")!.click();
    expect(tile().classList.contains("selected")).toBe(false);
    expect(doc.querySelector("[data-oi-vault-bar]")).toBeNull();
    tile().click();
    // Close is a link back to the chat: the chat's page binds, nothing attached, the ticks gone.
    expect(doc.querySelector(".modal.show .modal-footer a")!.getAttribute("href")).toBe("/of-manager/messages/chat");
    un();
    doc = loadPage("chat");
    un = bindChat(doc, "messages/chat", ctxOf(h, storage));
    expect(loadChatDraft(storage, ACCOUNT, CHAT).media_files).toEqual([]);
    expect(loadVaultPick(storage, vaultPickKey(ACCOUNT, "messages/chat/state-vault", CHAT)).ids).toEqual([]);
    un();
  });

  it("Add media from vault: a type tab opens the dialog on that type, the chat and folder kept; Search media opens", () => {
    const doc = loadPage("chat/state-vault");
    const h = handlers();
    bindChat(doc, "messages/chat/state-vault", ctxOf(h, memoryStorage(), { vaultView: { list: "7" } }));
    const tabs = [...doc.querySelectorAll<HTMLElement>(".modal.show .b-tabs__nav__link")];
    expect(tabs.map((t) => t.classList.contains("m-current"))).toEqual([true, false, false, false, false]);
    tabs[3].click();
    expect(h.navigate).toHaveBeenCalledWith(`/of-manager/messages/chat/state-vault?list=7&type=video&chat=${CHAT}`);
    tabs[0].click(); // the open tab
    expect(h.navigate).toHaveBeenCalledTimes(1);
    doc.querySelector<HTMLElement>("button[aria-label='Search media']")!.click();
    expect(doc.querySelector("input[name='media_vault_search']")!.closest(".g-page__header")!.classList.contains("m-search-form-visible")).toBe(true);
  });

  it("Header menu: Hide chat hides it and returns to the list; the mute item is labelled from the real state", async () => {
    const doc = loadPage("chat/state-header-menu");
    const h = handlers();
    const go = vi.fn();
    doc.addEventListener("click", go); // the frame's own link handler (bubble): never reached
    bindChat(doc, "messages/chat/state-header-menu", ctxOf(h, memoryStorage(), { fan: { name: "Fan A", muted: true } }));
    const items = [...doc.querySelectorAll<HTMLElement>(".of-state-menu .v-list-item")];
    const mute = items.find((i) => /mute notifications/i.test(i.textContent ?? ""))!;
    expect(mute.textContent?.trim()).toBe("Unmute notifications");
    mute.querySelector("a")!.click();
    expect(h.mute).toHaveBeenCalledWith(false);
    items.find((i) => i.textContent?.trim() === "Hide chat")!.querySelector("a")!.click();
    expect(h.hide).toHaveBeenCalledTimes(1);
    expect(go).not.toHaveBeenCalled();
    await flush();
    expect(h.navigate).toHaveBeenCalledWith("/of-manager/messages");
  });
});
