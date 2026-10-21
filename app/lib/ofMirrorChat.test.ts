import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it, vi } from "vitest";
import {
  applyListRows,
  applyScript,
  bindChat,
  bindMass,
  chatDraftKey,
  collectMass,
  collectMessage,
  EMPTY_MESSAGE,
  loadChatDraft,
  loadMassDraft,
  loadVaultPick,
  massDraftKey,
  tickMassList,
  MASS_PICKED_TITLE,
  massViewOf,
  massRequest,
  NO_CHAT,
  NO_DATE,
  NO_LISTS,
  readPrice,
  sendPath,
  type ChatContext,
  vaultPickKey,
  type ChatDraft,
  type PickedScript,
} from "./ofMirrorChat";
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

describe("collectMass", () => {
  it("needs text and at least one list", () => {
    expect(collectMass(" hello ", { text: "", user_lists: ["fans", "42"] })).toEqual({ text: "hello", user_lists: ["fans", "42"] });
    expect(collectMass("", { text: "", user_lists: ["fans"] })).toBe(EMPTY_MESSAGE);
    expect(collectMass("hello", { text: "", user_lists: [] })).toBe(NO_LISTS);
  });
  it("a scheduled draft (the Queue's \"+\") sends its scheduled_date, at least a minute ahead", () => {
    const now = new Date("2026-10-17T10:00:00Z");
    const draft = { text: "", user_lists: ["fans"], scheduled_date: "2026-10-21T13:00:00+02:00" };
    expect(collectMass("hi", draft, now)).toEqual({ text: "hi", user_lists: ["fans"], scheduled_date: "2026-10-21T13:00:00+02:00" });
    expect(collectMass("hi", { ...draft, scheduled_date: "2026-10-17T12:00:30+02:00" }, now)).toBe(TOO_SOON);
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

describe("bindMass: New message", () => {
  const lists = [
    { id: "fans", name: "Fans", usersCount: 12 },
    { id: 42, name: "Synthetic list", usersCount: 3 },
  ];
  const rows = (d: Document) => [...d.querySelectorAll<HTMLElement>(".b-chats__scroller label.b-rows-lists__item[data-oi-list]")];

  it("shows the Creator's lists in OF's rows, no links inside", () => {
    const doc = loadPage("send");
    applyListRows(doc, lists, ["42"]);
    const r = rows(doc);
    expect(r.map((x) => x.querySelector(".b-rows-lists__item__name")?.textContent?.trim())).toEqual(["Fans", "Synthetic list"]);
    expect(r.map((x) => x.querySelector(".b-content-inside-thumbs__item")?.textContent?.trim())).toEqual(["12 users", "3 users"]);
    expect(r.map((x) => x.querySelector<HTMLInputElement>("input")!.checked)).toEqual([false, true]);
    expect(r.some((x) => x.querySelector("a"))).toBe(false);
  });

  it("OF's captured /lists (app/lib/__fixtures__/of): one row per list, built-in and the Creator's own, its user count", () => {
    const captured = (JSON.parse(readFileSync(resolve(__dirname, "__fixtures__/of/messages-lists.json"), "utf8")) as { list: { id: string | number; type: string; name: string; usersCount: number }[] }).list;
    expect(new Set(captured.map((l) => l.type))).toContain("fans");
    expect(captured.some((l) => l.type === "custom")).toBe(true);
    const doc = loadPage("send");
    applyListRows(doc, captured, []);
    const r = rows(doc);
    expect(r.map((x) => x.getAttribute("data-oi-list"))).toEqual(captured.map((l) => String(l.id)));
    expect(r.map((x) => x.querySelector(".b-rows-lists__item__name")?.textContent?.trim())).toEqual(captured.map((l) => l.name));
    expect(r.map((x) => x.querySelector(".b-content-inside-thumbs__item")?.textContent?.trim())).toEqual(captured.map((l) => `${l.usersCount} ${l.usersCount === 1 ? "user" : "users"}`));
  });

  it("ticked lists and the text go out as one POST /messages/queue after a confirm", async () => {
    const doc = loadPage("send");
    const storage = memoryStorage();
    const h = handlers();
    bindMass(doc, ctxOf(h, storage, { chat: null, lists }));
    for (const r of rows(doc)) {
      const box = r.querySelector<HTMLInputElement>("input")!;
      box.checked = true;
      box.dispatchEvent(new Event("change", { bubbles: true }));
    }
    expect(loadMassDraft(storage, ACCOUNT).user_lists).toEqual(["fans", "42"]);
    type(doc, "Synthetic blast");
    send(doc).click();
    expect(h.confirm).toHaveBeenCalledWith("Send this message to 15 users on Fans, Synthetic list?");
    expect(h.send).toHaveBeenCalledWith("/api/of/v2/messages/queue", { text: "Synthetic blast", user_lists: ["fans", "42"] });
    await flush();
    expect(storage.getItem(massDraftKey(ACCOUNT))).toBeNull();
    expect(noteText(doc)).toBe("Sent");
  });

  it("a list page's Send message (tickMassList) ticks its list on Send to, keeps the draft, and takes it off Exclude", () => {
    const storage = memoryStorage();
    storage.setItem(massDraftKey(ACCOUNT), JSON.stringify({ text: "kept", user_lists: ["fans"], excluded_user_lists: ["following", "42"] }));
    tickMassList(storage, ACCOUNT, "following");
    tickMassList(storage, ACCOUNT, "following");
    expect(loadMassDraft(storage, ACCOUNT)).toEqual({ text: "kept", user_lists: ["fans", "following"], excluded_user_lists: ["42"] });
    const doc = loadPage("send");
    bindMass(doc, ctxOf(handlers(), storage, { chat: null, lists: [...lists, { id: "following", name: "Following", usersCount: 1 }] }));
    expect(rows(doc).filter((r) => r.querySelector<HTMLInputElement>("input")!.checked).map((r) => r.textContent!.replace(/\s+/g, " ").trim().split(" ")[0])).toContain("Following");
  });

  it("a schedule from the Queue's \"+\": named under the editor, sent as scheduled_date after its own confirm; Clear drops it", async () => {
    const doc = loadPage("send");
    const storage = memoryStorage();
    const at = new Date(Date.now() + 2 * 86_400_000);
    at.setSeconds(0, 0);
    storage.setItem(massDraftKey(ACCOUNT), JSON.stringify({ text: "Synthetic later", user_lists: ["fans"], scheduled_date: localIso(at) }));
    const h = handlers();
    const unbind = bindMass(doc, ctxOf(h, storage, { chat: null, lists }));
    const line = doc.getElementById("oi-chat-summary")!;
    expect(line.textContent).toMatch(/^Scheduled for .+ · Clear$/);
    send(doc).click();
    expect(h.confirm).toHaveBeenCalledWith(expect.stringMatching(/^Schedule this message for .+ to 12 users on Fans\?$/));
    expect(h.send).toHaveBeenCalledWith("/api/of/v2/messages/queue", { text: "Synthetic later", user_lists: ["fans"], scheduled_date: localIso(at) });
    await flush();
    expect(noteText(doc)).toBe("Scheduled");
    expect(doc.getElementById("oi-chat-summary")).toBeNull();
    // Clear: the draft keeps its text and lists, sent now.
    storage.setItem(massDraftKey(ACCOUNT), JSON.stringify({ text: "Again", user_lists: ["fans"], scheduled_date: localIso(at) }));
    unbind();
    bindMass(doc, ctxOf(h, storage, { chat: null, lists }));
    doc.querySelector<HTMLElement>("#oi-chat-summary [data-oi-clear]")!.click();
    expect(loadMassDraft(storage, ACCOUNT)).toEqual({ text: "Again", user_lists: ["fans"] });
    expect(doc.getElementById("oi-chat-summary")).toBeNull();
  });

  it("no list picked gives the note; All-Creators flips a row back", () => {
    let doc = loadPage("send");
    const h = handlers();
    bindMass(doc, ctxOf(h, memoryStorage(), { chat: null, lists }));
    type(doc, "x");
    send(doc).click();
    expect(noteText(doc)).toBe(NO_LISTS);
    expect(h.send).not.toHaveBeenCalled();
    doc = loadPage("send");
    const unbind = bindMass(doc, ctxOf(null, memoryStorage(), { chat: null }));
    const box = doc.querySelector<HTMLInputElement>(".b-chats__scroller label.b-rows-lists__item input")!;
    box.checked = true;
    box.dispatchEvent(new Event("change", { bubbles: true }));
    expect(box.checked).toBe(false);
    expect(noteText(doc)).toBe(SELECT_MODEL);
    unbind();
  });

  const tick = (row: HTMLElement) => {
    const box = row.querySelector<HTMLInputElement>("input")!;
    box.checked = !box.checked;
    box.dispatchEvent(new Event("change", { bubbles: true }));
  };
  const tab = (d: Document, label: string) => [...d.querySelectorAll<HTMLAnchorElement>("a.b-tabs__nav__link")].find((a) => a.textContent?.trim() === label)!;
  const title = (d: Document) => d.querySelector(".b-chat__header .g-page-title .b-inside-el")?.textContent;
  const chip = (d: Document) => d.getElementById("oi-mass-selected")?.querySelector(".b-tabs__nav__text")?.textContent?.trim();

  it("a ticked row shows OF's tick (drops m-not-active), the right side names the pick and the Selected chip counts it", () => {
    const doc = loadPage("send");
    const storage = memoryStorage();
    const unbind = bindMass(doc, ctxOf(handlers(), storage, { chat: null, lists }));
    expect(title(doc)).toBe("Select users to send them a message");
    expect(chip(doc)).toBeUndefined();
    const [fans, own] = rows(doc);
    expect(fans.classList.contains("m-not-active")).toBe(true);
    tick(fans);
    tick(own);
    expect(fans.classList.contains("m-not-active")).toBe(false);
    expect(title(doc)).toBe(MASS_PICKED_TITLE);
    expect(chip(doc)).toBe("15 Selected");
    tick(own);
    expect(own.classList.contains("m-not-active")).toBe(true);
    expect(chip(doc)).toBe("12 Selected");
    // ⊗ drops every pick.
    doc.querySelector<HTMLElement>("#oi-mass-selected [at-attr='filter_delete_btn']")!.click();
    expect(loadMassDraft(storage, ACCOUNT).user_lists).toEqual([]);
    expect(fans.querySelector<HTMLInputElement>("input")!.checked).toBe(false);
    expect(fans.classList.contains("m-not-active")).toBe(true);
    expect(chip(doc)).toBeUndefined();
    expect(title(doc)).toBe("Select users to send them a message");
    tick(fans);
    unbind();
    expect(title(doc)).toBe("Select users to send them a message");
    expect(doc.getElementById("oi-mass-selected")).toBeNull();
  });

  it("the tabs are OF's ?list= views: Send to, Exclude and Users, the current one marked", () => {
    for (const [view, label] of [["send", "Send to"], ["exclude", "Exclude"], ["users", "Users"]] as const) {
      const doc = loadPage("send");
      bindMass(doc, ctxOf(handlers(), memoryStorage(), { chat: null, lists, fans: [], massView: view }));
      expect(["Send to", "Exclude", "Users"].map((l) => tab(doc, l).getAttribute("href"))).toEqual([
        "/of-manager/messages/send",
        "/of-manager/messages/send?list=exclude",
        "/of-manager/messages/send?list=users",
      ]);
      expect(["Send to", "Exclude", "Users"].filter((l) => tab(doc, l).classList.contains("m-current"))).toEqual([label]);
    }
    expect(massViewOf("exclude")).toBe("exclude");
    expect(massViewOf("users")).toBe("users");
    expect(massViewOf(null)).toBe("send");
    expect(massViewOf("bogus")).toBe("send");
  });

  it("Exclude ticks lists to leave out (a Send to list is disabled there) and Send carries them as excluded_user_lists", () => {
    const doc = loadPage("send");
    const storage = memoryStorage();
    storage.setItem(massDraftKey(ACCOUNT), JSON.stringify({ text: "", user_lists: ["fans"] }));
    const h = handlers();
    bindMass(doc, ctxOf(h, storage, { chat: null, lists, massView: "exclude" }));
    const [fans, own] = rows(doc);
    expect(fans.querySelector<HTMLInputElement>("input")!.disabled).toBe(true);
    expect(fans.querySelector<HTMLInputElement>("input")!.checked).toBe(false);
    tick(own);
    expect(loadMassDraft(storage, ACCOUNT)).toMatchObject({ user_lists: ["fans"], excluded_user_lists: ["42"] });
    expect(own.classList.contains("m-not-active")).toBe(false);
    type(doc, "Synthetic blast");
    send(doc).click();
    expect(h.send).toHaveBeenCalledWith("/api/of/v2/messages/queue", { text: "Synthetic blast", user_lists: ["fans"], excluded_user_lists: ["42"] });
  });

  it("Users ticks fans one by one (user_ids), and Send goes with them alone", () => {
    const doc = loadPage("send");
    const storage = memoryStorage();
    const h = handlers();
    const fans = [
      { id: 501, name: "Fan A", sub: "@fana" },
      { id: 502, name: "Fan B", sub: "@fanb" },
    ];
    bindMass(doc, ctxOf(h, storage, { chat: null, lists, fans, massView: "users" }));
    const r = rows(doc);
    expect(r.map((x) => x.querySelector(".b-content-inside-thumbs__item")?.textContent?.trim())).toEqual(["@fana", "@fanb"]);
    tick(r[1]);
    expect(loadMassDraft(storage, ACCOUNT).user_ids).toEqual([502]);
    expect(chip(doc)).toBe("1 Selected");
    type(doc, "Synthetic hello");
    send(doc).click();
    expect(h.confirm).toHaveBeenCalledWith("Send this message to 1 user picked?");
    expect(h.send).toHaveBeenCalledWith("/api/of/v2/messages/queue", { text: "Synthetic hello", user_lists: [], user_ids: [502] });
  });

  it("Search users and lists filters the tab's rows, and Enter does not submit OF's form", () => {
    const doc = loadPage("send");
    bindMass(doc, ctxOf(handlers(), memoryStorage(), { chat: null, lists }));
    const input = doc.querySelector<HTMLInputElement>(".b-search-users-form input")!;
    input.value = "synth";
    input.dispatchEvent(new Event("input", { bubbles: true }));
    expect(rows(doc).map((x) => x.style.display)).toEqual(["none", ""]);
    const submit = new Event("submit", { bubbles: true, cancelable: true });
    doc.querySelector("form.b-search-users-form")!.dispatchEvent(submit);
    expect(submit.defaultPrevented).toBe(true);
  });

  it("Send to says Loading lists… until the lists are here (never a false Nothing found), the red error after a failure", () => {
    const empty = (d: Document) => d.querySelector<HTMLElement>(".b-chats__scroller [data-oi-empty] .empty-message > span")!;
    let doc = loadPage("send");
    let unbind = bindMass(doc, ctxOf(handlers(), memoryStorage(), { chat: null }));
    expect(empty(doc).textContent).toBe("Loading lists…");
    unbind();
    expect(empty(doc).textContent).toBe("Nothing found");
    doc = loadPage("send");
    unbind = bindMass(doc, ctxOf(handlers(), memoryStorage(), { chat: null, listsError: "502 Bad Gateway" }));
    expect(empty(doc).textContent).toBe("Could not load lists: 502 Bad Gateway");
    expect(empty(doc).style.color).toBe("rgb(255, 69, 69)");
    unbind();
    doc = loadPage("send");
    bindMass(doc, ctxOf(handlers(), memoryStorage(), { chat: null, lists: [] }));
    expect(empty(doc).textContent).toBe("Nothing found");
  });
});

describe("New message: Save for later, the schedule dialog and Edit message", () => {
  const lists = [
    { id: "fans", name: "Fans", usersCount: 12 },
    { id: 1234, name: "Synthetic list", usersCount: 3 },
  ];
  type Req = { method: string; path: string; body: Record<string, unknown> };
  const requests = JSON.parse(readFileSync(resolve(__dirname, "__fixtures__/of/queue-edit-requests.json"), "utf8")) as Record<string, { of: Req; relay?: Req }>;
  const ZONE = "Europe/Ljubljana";
  const withPut = () => handlers({ put: vi.fn((_path: string, _body: object) => Promise.resolve({ id: 6105 })) } as never) as ReturnType<typeof handlers> & { put: ReturnType<typeof vi.fn> };
  const modal = (d: Document) => d.getElementById("oi-mass-schedule");
  // A document of its own: the shared one still holds the listeners earlier tests left bound.
  const loadPage = (page: string) => {
    const d = document.implementation.createHTMLDocument("");
    d.documentElement.innerHTML = readFileSync(resolve(__dirname, `../public/of-mirror/pages/messages/${page}.html`), "utf8");
    return d;
  };
  const footer = (d: Document, text: string) => [...modal(d)!.querySelectorAll<HTMLButtonElement>(".modal-footer button")].find((b) => b.textContent!.trim() === text)!;

  it("collectMass: saved for later sends save_for_later and no date; an edit needs a date or Save for later", () => {
    expect(collectMass("hi", { text: "", user_lists: ["fans"], save_for_later: true })).toEqual({ text: "hi", user_lists: ["fans"], save_for_later: true });
    expect(collectMass("hi", { text: "", user_lists: ["fans"], edit_id: "6105" })).toBe(NO_DATE);
    expect(collectMass("", { text: "", user_lists: [], user_ids: [501], media_files: [8105], save_for_later: true })).toEqual({ text: "", user_lists: [], user_ids: [501], media_files: [8105], save_for_later: true });
    expect(massRequest({ text: "", user_lists: [], edit_id: "6105" })).toEqual({ method: "PUT", path: "/api/of/v2/messages/queue/6105" });
    expect(massRequest({ text: "", user_lists: [] })).toEqual({ method: "POST", path: "/api/of/v2/messages/queue" });
    expect(massRequest({ text: "", user_lists: [], save_for_later: true })).toEqual({ method: "POST", path: "/api/of/v2/messages/queue/later" });
  });

  it("the schedule button opens the date and time dialog in the Agency's zone; Save for Later puts it on the draft, sent as the captured shape", async () => {
    const doc = loadPage("send");
    const storage = memoryStorage();
    storage.setItem(massDraftKey(ACCOUNT), JSON.stringify({ text: "Synthetic message", user_lists: ["fans"] }));
    const h = handlers();
    bindMass(doc, ctxOf(h, storage, { chat: null, lists, zone: ZONE }));
    doc.querySelector<HTMLButtonElement>("button[at-attr='scheduled_msg']")!.click();
    expect(modal(doc)!.querySelector(".modal-title")!.textContent!.trim()).toBe("Scheduled messages");
    expect([...modal(doc)!.querySelectorAll(".modal-footer button")].map((b) => b.textContent!.trim())).toEqual(["Cancel", "Save for Later", "Next"]);
    footer(doc, "Save for Later").click();
    expect(modal(doc)).toBeNull();
    expect(doc.getElementById("oi-chat-summary")!.textContent).toBe("Saved for later · Clear");
    send(doc).click();
    expect(h.confirm).toHaveBeenCalledWith("Save this message for later to 12 users on Fans?");
    const want = requests.saveMessageForLater.relay!;
    // OF's own Save for later (captured live) is POST /messages/queue with isPublishedWithPeriod and no date.
    expect([requests.saveMessageForLater.of.path, requests.saveMessageForLater.of.body.isPublishedWithPeriod, "scheduledDate" in requests.saveMessageForLater.of.body]).toEqual(["/api2/v2/messages/queue", 1, false]);
    expect(h.send).toHaveBeenCalledWith(want.path, want.body);
    await flush();
    expect(h.navigate).toHaveBeenCalledWith("/of-manager/queue/saved-for-later-messages");
  });

  it("Next takes the picked day and time as the Agency zone's; a past one keeps the dialog with the note", () => {
    const doc = loadPage("send");
    const storage = memoryStorage();
    const h = handlers();
    bindMass(doc, ctxOf(h, storage, { chat: null, lists, zone: ZONE }));
    doc.querySelector<HTMLButtonElement>("button[at-attr='scheduled_msg']")!.click();
    modal(doc)!.querySelector<HTMLInputElement>("input[at-attr='date_input']")!.value = "2000-01-01";
    footer(doc, "Next").click();
    expect(noteText(doc)).toBe(TOO_SOON);
    modal(doc)!.querySelector<HTMLInputElement>("input[at-attr='date_input']")!.value = "2099-11-07";
    modal(doc)!.querySelector<HTMLInputElement>("input[type='time']")!.value = "10:00";
    footer(doc, "Next").click();
    expect(modal(doc)).toBeNull();
    // 10:00 in Ljubljana (CET) is 09:00 UTC.
    expect(new Date(loadMassDraft(storage, ACCOUNT).scheduled_date!).toISOString()).toBe("2099-11-07T09:00:00.000Z");
  });

  it("an edit of a message with recipients and lists, only its date changed: Send saves it with PUT /messages/queue/{id} (the request shape)", async () => {
    const doc = loadPage("send");
    const storage = memoryStorage();
    const want = requests.rescheduleMessage.relay!;
    // OF's own Save of an edited message (captured live): PUT /messages/queue/{id} with isScheduled + scheduledDate.
    expect([requests.rescheduleMessage.of.method, requests.rescheduleMessage.of.body.isScheduled]).toEqual(["PUT", 1]);
    // messageEditDraft of the queued message (app/lib/__fixtures__/of/queue-edit-message.json), rescheduled.
    storage.setItem(
      massDraftKey(ACCOUNT),
      JSON.stringify({ text: "Synthetic scheduled message", user_lists: ["fans", "1234"], user_ids: [501, 502], excluded_user_lists: ["99"], media_files: [8105], price: 5, scheduled_date: want.body.scheduled_date, edit_id: "6105" }),
    );
    const h = withPut();
    bindMass(doc, ctxOf(h, storage, { chat: null, lists, zone: ZONE }));
    expect(doc.getElementById("oi-chat-summary")!.textContent).toBe("Editing a scheduled message · 2 users picked · 1 excluded list · 1 media · Price: $5 · Scheduled for Nov 7, 10:00 am · Clear · Discard");
    expect(doc.querySelector("#oi-schedule-pill .b-post-piece")!.textContent!.replace(/\s+/g, " ").trim()).toBe("Scheduled for Nov 7, 10:00 am");
    // The lists are ticked from the draft.
    expect([...doc.querySelectorAll<HTMLInputElement>(".b-chats__scroller label.b-rows-lists__item[data-oi-list] input")].map((b) => b.checked)).toEqual([true, true]);
    send(doc).click();
    expect(h.confirm).toHaveBeenCalledWith("Save this message for Nov 7, 10:00 am to 15 users on Fans, Synthetic list and 2 users picked for $5?");
    expect(h.send).not.toHaveBeenCalled();
    expect(h.put).toHaveBeenCalledWith(want.path, want.body);
    await flush();
    expect(storage.getItem(massDraftKey(ACCOUNT))).toBeNull();
    expect(h.navigate).toHaveBeenCalledWith("/of-manager/queue?date=2026-11-07");
  });

  it("an edit whose date was cleared sends nothing and asks for one; Discard drops the draft", () => {
    const doc = loadPage("send");
    const storage = memoryStorage();
    storage.setItem(massDraftKey(ACCOUNT), JSON.stringify({ text: "x", user_lists: ["fans"], scheduled_date: "2099-11-07T10:00:00+01:00", edit_id: "6105" }));
    const h = withPut();
    bindMass(doc, ctxOf(h, storage, { chat: null, lists, zone: ZONE }));
    doc.querySelector<HTMLElement>("#oi-chat-summary [data-oi-clear]")!.click();
    send(doc).click();
    expect(noteText(doc)).toBe(NO_DATE);
    doc.querySelector<HTMLElement>("#oi-chat-summary [data-oi-discard]")!.click();
    expect(storage.getItem(massDraftKey(ACCOUNT))).toBeNull();
    expect(h.put).not.toHaveBeenCalled();
    expect(h.send).not.toHaveBeenCalled();
  });
});
