import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import { bindChat, bindMass, chatDraftKey, collectMass, collectMessage, loadChatDraft, loadMassDraft, loadVaultPick, massDraftKey, vaultPickKey, NO_CHAT, NO_EDIT_GIF, NO_MASS_FORMS, NO_SCHEDULED_FORMS, NO_SCHEDULED_GIF, type ChatContext, type ChatDraft, type MassDraft } from "./ofMirrorChat";
import { applyData } from "./ofMirrorData";
import { bareType, CAMERA_BLOCKED, GIF_ALONE, GIF_SEARCH_MS, MIC_BLOCKED, NO_GIFS, NO_MIC, notMedia, VOICE_MAX_MS } from "./ofMirrorComposer";
import { localIso, SELECT_MODEL } from "./ofMirrorWrites";
import type { GiphyItem, TaggedFriendUser, VaultMedia, VaultUploadResp } from "./relay";

/** The committed chat captures (the generator's output). */
const loadPage = (page: string) => {
  document.documentElement.innerHTML = readFileSync(resolve(__dirname, `../public/of-mirror/pages/messages/${page}.html`), "utf8");
  document.body.className = "";
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
const flush = async (n = 3) => {
  for (let i = 0; i < n; i++) await new Promise((r) => setTimeout(r, 0));
};
const ACCOUNT = "acct-1";
const CHAT = "9001";
const GIFS: GiphyItem[] = [
  { type: "gif", id: "g1", title: "Wave", images: { fixed_height: { url: "https://media.giphy.com/media/g1/200.gif" } } },
  { type: "gif", id: "g2", title: "Cat", images: { fixed_height: { url: "https://media.giphy.com/media/g2/200.gif", webp: "https://media.giphy.com/media/g2/200.webp" } } },
];
const handlers = (over: Record<string, unknown> = {}) => ({
  send: vi.fn((_path: string, _body: object) => Promise.resolve({ id: 1 })),
  upload: vi.fn((_file: File) => Promise.resolve({ ready: true, deduped: false, vault_id: null, send_with: [{ processId: "p1" }] } as VaultUploadResp)),
  gifs: vi.fn((_q: string) => Promise.resolve(GIFS)),
  toggleTag: vi.fn(() => Promise.resolve({})),
  inviteGuest: vi.fn(() => Promise.resolve({})),
  mute: vi.fn(() => Promise.resolve({})),
  hide: vi.fn(() => Promise.resolve({})),
  confirm: vi.fn(() => true),
  navigate: vi.fn(),
  ...over,
});
type H = ReturnType<typeof handlers>;
const ctxOf = (h: H | null, storage: Storage, over: Partial<ChatContext> = {}): ChatContext => ({
  handlers: h,
  storage,
  accountId: ACCOUNT,
  chat: CHAT,
  fan: { name: "Fan A", muted: false },
  mobile: false,
  ...over,
});
const draft = (over: Partial<ChatDraft> = {}): ChatDraft => ({ text: "", media_files: [], thumbs: [], ...over });
const saveDraft = (s: Storage, d: ChatDraft) => s.setItem(chatDraftKey(ACCOUNT, CHAT), JSON.stringify(d));
const $ = <T extends Element = HTMLElement>(d: ParentNode, sel: string) => d.querySelector<T>(sel)!;
const send = (d: Document) => $<HTMLButtonElement>(d, "button[at-attr='send_btn']");
const editor = (d: Document) => $(d, "[contenteditable][aria-label='Textbox field']");
const noteText = (d: Document) => d.getElementById("oi-note")?.textContent;
/** Nothing but the asked-for calls reached the Relay. */
const writes = (h: H) => [h.send, h.upload, h.toggleTag, h.inviteGuest, h.mute, h.hide].reduce((n, f) => n + f.mock.calls.length, 0);

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("collectMessage: the composer's fields", () => {
  it("a GIF alone is a message (text \"\", OF's giphyId); tags go to OF's rfTag / rfGuest / rfPartner", () => {
    expect(collectMessage("", draft({ giphy_id: "g1" }))).toEqual({ text: "", price: 0, media_files: [], giphy_id: "g1" });
    const tags = [
      { id: 501, type: "user", name: "A" },
      { id: 77, type: "guest", name: "G" },
      { id: 88, type: "document", name: "D" },
      { id: 89, type: "link", name: "L" },
    ];
    expect(collectMessage("hi", draft({ tags }))).toEqual({ text: "hi", price: 0, media_files: [], tagged_users: [501], rf_guest: [77], rf_partner: [88, 89] });
  });

  it("a scheduled message keeps creator tags but cannot carry a GIF, a guest or a release form", () => {
    const at = localIso(new Date(Date.now() + 86_400_000));
    expect(collectMessage("x", draft({ scheduled_date: at, tags: [{ id: 501, type: "user", name: "A" }] }))).toEqual({ text: "x", price: 0, media_files: [], tagged_users: [501], scheduled_date: at });
    expect(collectMessage("x", draft({ scheduled_date: at, giphy_id: "g1" }))).toBe(NO_SCHEDULED_GIF);
    expect(collectMessage("x", draft({ scheduled_date: at, tags: [{ id: 77, type: "guest", name: "G" }] }))).toBe(NO_SCHEDULED_FORMS);
  });
});

describe("the chat composer's tools", () => {
  it("the generator leaves a chat's tools enabled (Send tip stays disabled) and puts OF's Format panel in, hidden", () => {
    const d = loadPage("chat");
    for (const label of ["Add GIF", "Record video", "Record voice", "Format Text", "Tag other creators"]) {
      const el = $(d, `[aria-label='${label}']`);
      expect(el.hasAttribute("disabled"), label).toBe(false);
    }
    expect($(d, "[at-attr='release_forms_btn']").getAttribute("href")).toBe("/of-manager/messages/chat/state-tag-people");
    const tip = $<HTMLButtonElement>(d, "button[at-attr='send_tip']");
    expect(tip.disabled).toBe(true);
    expect(tip.title).toBe("Not available in Inflowwww yet");
    const panel = $(d, "[data-oi-format-panel]");
    expect(panel.style.display).toBe("none");
    expect(panel.parentElement!.classList.contains("b-make-post__sticky-panel")).toBe(true);
    // Closed, it isn't OF's .b-form-editor: OF's `.b-create-post-form:has(.b-form-editor)` rule would take its 56px off
    // the text box's max-height (the box shrank to a sliver and the editor vanished once media was added).
    expect(d.querySelector(".b-create-post-form .b-form-editor")).toBeNull();
    for (const icon of ["icon-bold", "icon-italic", "icon-text-colour", "icon-clear-format"]) expect(d.getElementById(icon), icon).not.toBeNull();
    // New message's composer has them too (its Format panel in place); off a composer (its list pages) they stay disabled.
    const m = loadPage("send");
    for (const label of ["Add media", "Add GIF", "Record video", "Record voice", "Format Text", "Tag other creators", "Add media from vault", "Message price", "Scheduled messages"]) {
      expect($(m, `[aria-label='${label}']`).hasAttribute("disabled"), label).toBe(false);
    }
    expect($(m, "[at-attr='release_forms_btn']").getAttribute("href")).toBe("/of-manager/messages/send/state-tag-people");
    expect($(m, "[at-attr='add_vault_media']").getAttribute("href")).toBe("/of-manager/messages/send/state-vault");
    expect($(m, "[at-attr='price_btn']").getAttribute("href")).toBe("/of-manager/messages/send/state-price");
    expect($(m, "[data-oi-format-panel]").parentElement!.classList.contains("b-make-post__sticky-panel")).toBe(true);
    expect(m.querySelector(".b-create-post-form .b-form-editor")).toBeNull();
    const x = loadPage("send/list-exclude");
    for (const label of ["Add GIF", "Record video", "Record voice"]) {
      const el = x.querySelector(`[aria-label='${label}']`);
      if (el) expect(el.hasAttribute("disabled"), label).toBe(true);
    }
  });

  it("Send tip shows only for a fan who takes tips; Record video is hidden on a phone", () => {
    let d = loadPage("chat");
    let un = bindChat(d, "messages/chat", ctxOf(handlers(), memoryStorage(), { fan: { name: "A", tipsEnabled: true } }));
    expect($(d, "button[at-attr='send_tip']").style.display).toBe("");
    expect($(d, "button.js-chat__video-record-btn").style.display).toBe("");
    un();
    d = loadPage("chat");
    un = bindChat(d, "messages/chat", ctxOf(handlers(), memoryStorage(), { fan: { name: "A" }, mobile: true }));
    expect($(d, "button[at-attr='send_tip']").style.display).toBe("none");
    expect($(d, "button.js-chat__video-record-btn").style.display).toBe("none");
    un();
  });

  it("Format Text opens OF's panel; Bold on a selection leaves OF's markup, which Send sends as the text and a reload restores", async () => {
    const d = loadPage("chat");
    const s = memoryStorage();
    const h = handlers();
    // jsdom has no editing commands: bold wraps the selection in <b>, as a browser does.
    d.execCommand = vi.fn((name: string) => {
      if (name !== "bold") return true;
      const r = d.getSelection()!.getRangeAt(0);
      r.surroundContents(d.createElement("b"));
      return true;
    }) as never;
    let un = bindChat(d, "messages/chat", ctxOf(h, s));
    const panel = $(d, "[data-oi-format-panel]");
    $(d, "button[aria-label='Format Text']").click();
    expect(panel.style.display).toBe("");
    expect(panel.classList.contains("b-form-editor")).toBe(true);
    editor(d).innerHTML = "<p>Hi there</p>";
    editor(d).dispatchEvent(new Event("input", { bubbles: true }));
    const text = editor(d).querySelector("p")!.firstChild!;
    const range = d.createRange();
    range.setStart(text, 0);
    range.setEnd(text, 2);
    d.getSelection()!.removeAllRanges();
    d.getSelection()!.addRange(range);
    d.dispatchEvent(new Event("selectionchange"));
    $(panel, "button[aria-label='Bold']").click();
    expect(loadChatDraft(s, ACCOUNT, CHAT).html).toBe("<p><strong>Hi</strong> there</p>");
    // The same words stay selected, so a second tool (Text Color) formats them too.
    expect(d.getSelection()!.toString()).toBe("Hi");
    un();
    // A State page round trip: the editor comes back formatted.
    loadPage("chat");
    un = bindChat(d, "messages/chat", ctxOf(h, s));
    expect(editor(d).innerHTML).toBe("<p><strong>Hi</strong> there</p>");
    send(d).click();
    expect(h.send).toHaveBeenCalledWith(`/api/of/v2/chats/${CHAT}/messages`, { text: "<p><strong>Hi</strong> there</p>", price: 0, media_files: [] });
    $(d, "[data-oi-format-panel] [aria-label='Close Formatting Panel']").click();
    expect($(d, "[data-oi-format-panel]").style.display).toBe("none");
    expect(d.querySelector(".b-create-post-form .b-form-editor")).toBeNull();
    un();
  });

  it("Format without a model says so and formats nothing", () => {
    const d = loadPage("chat");
    const un = bindChat(d, "messages/chat", ctxOf(null, memoryStorage()));
    $(d, "button[aria-label='Format Text']").click();
    $(d, "[data-oi-format-panel] button[aria-label='Bold']").click();
    expect(noteText(d)).toBe(SELECT_MODEL);
    un();
  });

  it("Add GIF: OF's picker lists trending GIFs, searches, and a pick is the draft's giphy_id; Send sends it; Delete drops it", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    const d = loadPage("chat");
    const s = memoryStorage();
    const h = handlers();
    const un = bindChat(d, "messages/chat", ctxOf(h, s));
    $(d, "button[aria-label='Add GIF']").click();
    expect(h.gifs).toHaveBeenCalledWith("");
    await vi.advanceTimersByTimeAsync(0);
    const box = $(d, "div.b-comments__giphy.m-chat-giphy");
    expect(box.classList.contains("m-opened")).toBe(true);
    expect($<HTMLInputElement>(box, ".b-comments__giphy-form input").placeholder).toBe("Search GIFs");
    expect([...box.querySelectorAll(".b-comments__giphy__img")].map((b) => b.getAttribute("aria-label"))).toEqual(["Wave", "Cat"]);
    const field = $<HTMLInputElement>(box, ".b-comments__giphy-form input");
    field.value = "cat";
    field.dispatchEvent(new Event("input", { bubbles: true }));
    expect(h.gifs).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(GIF_SEARCH_MS);
    expect(h.gifs).toHaveBeenLastCalledWith("cat");
    $(box, "[data-oi-gif='g2']").click();
    expect(loadChatDraft(s, ACCOUNT, CHAT)).toMatchObject({ giphy_id: "g2", giphy_thumb: "https://media.giphy.com/media/g2/200.webp" });
    expect(box.classList.contains("m-opened")).toBe(false);
    expect(d.querySelector("#oi-chat-gif .b-comments__giphy-item img")!.getAttribute("src")).toBe("https://media.giphy.com/media/g2/200.webp");
    expect(d.getElementById("oi-chat-summary")!.textContent).toContain("GIF");
    // OF's rules: with a GIF, Add GIF, the price and Record video are off.
    expect($(d, "button[aria-label='Add GIF']").hasAttribute("disabled")).toBe(true);
    expect($(d, "[at-attr='price_btn']").style.pointerEvents).toBe("none");
    expect($(d, "button.js-chat__video-record-btn").hasAttribute("disabled")).toBe(true);
    expect(send(d).disabled).toBe(false);
    send(d).click();
    expect(h.send).toHaveBeenCalledWith(`/api/of/v2/chats/${CHAT}/messages`, { text: "", price: 0, media_files: [], giphy_id: "g2" });
    expect(writes(h)).toBe(1);
    un();
    // Delete
    const d2 = loadPage("chat");
    saveDraft(s, draft({ giphy_id: "g1", giphy_thumb: "t" }));
    const un2 = bindChat(d2, "messages/chat", ctxOf(h, s));
    $(d2, "[data-oi-gif-delete]").click();
    expect(loadChatDraft(s, ACCOUNT, CHAT).giphy_id).toBeUndefined();
    expect(d2.getElementById("oi-chat-gif")).toBeNull();
    expect($(d2, "button[aria-label='Add GIF']").hasAttribute("disabled")).toBe(false);
    un2();
  });

  it("Add GIF: nothing found, a failure, and no chat or model", async () => {
    let d = loadPage("chat");
    let h = handlers({ gifs: vi.fn(() => Promise.resolve([])) });
    let un = bindChat(d, "messages/chat", ctxOf(h, memoryStorage()));
    $(d, "button[aria-label='Add GIF']").click();
    await flush();
    expect($(d, ".b-comments__giphy__wrapper").classList.contains("m-empty-list")).toBe(true);
    expect($(d, ".b-comments__giphy__wrapper").textContent).toBe(NO_GIFS);
    un();
    d = loadPage("chat");
    h = handlers({ gifs: vi.fn(() => Promise.reject(new Error("502 Bad Gateway"))) });
    un = bindChat(d, "messages/chat", ctxOf(h, memoryStorage()));
    $(d, "button[aria-label='Add GIF']").click();
    await flush();
    expect($(d, ".b-comments__giphy__wrapper").textContent).toBe("Could not load GIFs: 502 Bad Gateway");
    un();
    d = loadPage("chat");
    h = handlers();
    un = bindChat(d, "messages/chat", ctxOf(h, memoryStorage(), { chat: null }));
    $(d, "button[aria-label='Add GIF']").click();
    expect(noteText(d)).toBe(NO_CHAT);
    expect(h.gifs).not.toHaveBeenCalled();
    un();
  });

  it("OF's rules: a price or media other than voice turns Add GIF off; a voice note turns Record voice off", () => {
    const s = memoryStorage();
    let d = loadPage("chat");
    saveDraft(s, draft({ price: 5 }));
    let un = bindChat(d, "messages/chat", ctxOf(handlers(), s));
    expect($(d, "button[aria-label='Add GIF']").hasAttribute("disabled")).toBe(true);
    un();
    d = loadPage("chat");
    saveDraft(s, draft({ media_files: [{ processId: "v" }], thumbs: ["t"], audio: 1 }));
    un = bindChat(d, "messages/chat", ctxOf(handlers(), s));
    expect($(d, "button[aria-label='Add GIF']").hasAttribute("disabled")).toBe(false);
    expect($(d, "button[aria-label='Record voice']").hasAttribute("disabled")).toBe(true);
    un();
    d = loadPage("chat");
    saveDraft(s, draft({ media_files: [61, { processId: "v" }], thumbs: ["a", "b"], audio: 1 }));
    un = bindChat(d, "messages/chat", ctxOf(handlers(), s));
    expect($(d, "button[aria-label='Add GIF']").hasAttribute("disabled")).toBe(true);
    un();
  });
});

/**
 * A fake microphone / camera: getUserMedia's stream and a MediaRecorder whose stop() hands over one chunk.
 * `supported`: the types its isTypeSupported says yes to (absent: no isTypeSupported); `recorded`: the mimeType it
 * reports for an asked type (a browser adds codecs). `hold`: getUserMedia waits for `grant()`.
 */
function fakeMedia(fail?: string, opts: { supported?: string[]; recorded?: (asked: string) => string; hold?: boolean } = {}) {
  const tracks = [{ stop: vi.fn() }];
  const stream = { getTracks: () => tracks } as unknown as MediaStream;
  let grant: () => void = () => {};
  const getUserMedia = vi.fn(() =>
    fail ? Promise.reject(Object.assign(new Error(fail), { name: fail })) : opts.hold ? new Promise<MediaStream>((r) => (grant = () => r(stream))) : Promise.resolve(stream),
  );
  const recorders: Array<{ state: string; asked?: string }> = [];
  class Rec {
    static isTypeSupported = opts.supported ? (t: string) => opts.supported!.includes(t) : undefined;
    state = "inactive";
    // As a browser that picks its default: the type then comes from the kind recorded.
    mimeType = "";
    asked?: string;
    ondataavailable: ((e: { data: Blob }) => void) | null = null;
    onstop: (() => void) | null = null;
    constructor(_s: MediaStream, o?: { mimeType?: string }) {
      this.asked = o?.mimeType;
      if (o?.mimeType) this.mimeType = opts.recorded ? opts.recorded(o.mimeType) : o.mimeType;
      recorders.push(this);
    }
    start() {
      this.state = "recording";
    }
    stop() {
      this.state = "inactive";
      this.ondataavailable?.({ data: new Blob(["rec"], { type: this.mimeType }) });
      this.onstop?.();
    }
  }
  Object.defineProperty(window.navigator, "mediaDevices", { value: { getUserMedia }, configurable: true });
  vi.stubGlobal("MediaRecorder", Rec);
  return { getUserMedia, tracks, recorders, grant: () => grant() };
}

describe("Record voice and Record video", () => {
  it("Record voice: OF's panel records, and a stopped recording uploads as a voice note on the draft", async () => {
    const m = fakeMedia();
    const d = loadPage("chat");
    const s = memoryStorage();
    const h = handlers();
    const un = bindChat(d, "messages/chat", ctxOf(h, s));
    $(d, "button[aria-label='Record voice']").click();
    const panel = $(d, ".js-chat__audiorecord-panel");
    expect(panel.style.display).toBe("");
    expect(d.body.classList.contains("open-panel")).toBe(true);
    expect(m.getUserMedia).not.toHaveBeenCalled(); // opening asks for nothing
    $(panel, ".b-float-panel__btn-record").click();
    await flush();
    expect(m.getUserMedia).toHaveBeenCalledWith({ audio: true });
    expect($(panel, ".js-message-header-recording").classList.contains("g-hidden")).toBe(false);
    expect($(panel, ".js-chat__audio-record-timer").textContent).toBe(" 0:00 / 30:00 ");
    $(panel, ".b-float-panel__btn-record").click();
    expect(panel.style.display).toBe("none");
    expect(m.tracks[0].stop).toHaveBeenCalled();
    expect(h.upload).toHaveBeenCalledTimes(1);
    const file = h.upload.mock.calls[0][0];
    expect(file.type).toBe("audio/webm");
    expect(file.name).toMatch(/^voice-\d+\.webm$/);
    await flush();
    expect(loadChatDraft(s, ACCOUNT, CHAT)).toMatchObject({ media_files: [{ processId: "p1" }], audio: 1 });
    expect($(d, "button[aria-label='Record voice']").hasAttribute("disabled")).toBe(true);
    send(d).click();
    expect(h.send).toHaveBeenCalledWith(`/api/of/v2/chats/${CHAT}/messages`, { text: "", price: 0, media_files: [{ processId: "p1" }] });
    un();
  });

  it("Record voice stops itself at OF's 30:00 and keeps the recording", async () => {
    fakeMedia();
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval", "Date"] });
    const d = loadPage("chat");
    const h = handlers();
    const un = bindChat(d, "messages/chat", ctxOf(h, memoryStorage()));
    $(d, "button[aria-label='Record voice']").click();
    $(d, ".b-float-panel__btn-record").click();
    await flush();
    expect($(d, ".js-message-header-recording").classList.contains("g-hidden")).toBe(false);
    vi.advanceTimersByTime(61_000);
    expect($(d, ".js-chat__audio-record-timer").textContent).toBe(" 1:01 / 30:00 ");
    vi.advanceTimersByTime(VOICE_MAX_MS);
    expect(h.upload).toHaveBeenCalledTimes(1);
    expect($(d, ".js-chat__audiorecord-panel").style.display).toBe("none");
    un();
  });

  it.each([
    ["NotFoundError", NO_MIC],
    ["NotAllowedError", MIC_BLOCKED],
  ])("Record voice: %s says so and uploads nothing", async (err, text) => {
    fakeMedia(err);
    const d = loadPage("chat");
    const h = handlers();
    const un = bindChat(d, "messages/chat", ctxOf(h, memoryStorage()));
    $(d, "button[aria-label='Record voice']").click();
    $(d, ".b-float-panel__btn-record").click();
    await flush();
    expect(noteText(d)).toBe(text);
    expect($(d, ".js-chat__audiorecord-panel").style.display).toBe("none");
    expect(writes(h)).toBe(0);
    un();
  });

  it("Record voice: Back cancels a recording, nothing is uploaded", async () => {
    const m = fakeMedia();
    const d = loadPage("chat");
    const h = handlers();
    const un = bindChat(d, "messages/chat", ctxOf(h, memoryStorage()));
    $(d, "button[aria-label='Record voice']").click();
    $(d, ".b-float-panel__btn-record").click();
    await flush();
    $(d, ".js-message-header-recording button").click();
    expect(m.tracks[0].stop).toHaveBeenCalled();
    expect($(d, ".js-chat__audiorecord-panel").style.display).toBe("none");
    expect(d.body.classList.contains("open-panel")).toBe(false);
    expect(writes(h)).toBe(0);
    un();
  });

  it("Record video: OF's recorder previews the camera, records, and the clip uploads; its close cancels", async () => {
    const m = fakeMedia();
    const d = loadPage("chat");
    const h = handlers();
    const un = bindChat(d, "messages/chat", ctxOf(h, memoryStorage()));
    $(d, "button.js-chat__video-record-btn").click();
    await flush();
    expect(m.getUserMedia).toHaveBeenCalledWith({ audio: true, video: true });
    const box = $(d, ".b-chat__video-message__preview");
    expect(box.classList.contains("g-hidden")).toBe(false);
    const rec = $(box, ".vjs-record-button");
    expect(rec.classList.contains("vjs-hidden")).toBe(false);
    rec.click();
    expect(rec.title).toBe("Stop");
    expect($(box, ".b-chat__videorec-live-label").classList.contains("g-hidden")).toBe(false);
    rec.click();
    expect(h.upload).toHaveBeenCalledTimes(1);
    expect(h.upload.mock.calls[0][0].name).toMatch(/^video-\d+\.webm$/);
    expect(box.classList.contains("g-hidden")).toBe(true);
    // Open again and close: nothing more is uploaded.
    $(d, "button.js-chat__video-record-btn").click();
    await flush();
    $(box, ".js-video-message-close").click();
    expect(box.classList.contains("g-hidden")).toBe(true);
    expect(h.upload).toHaveBeenCalledTimes(1);
    un();
  });

  it("Record video: a blocked camera says so", async () => {
    fakeMedia("NotAllowedError");
    const d = loadPage("chat");
    const h = handlers();
    const un = bindChat(d, "messages/chat", ctxOf(h, memoryStorage()));
    $(d, "button.js-chat__video-record-btn").click();
    await flush();
    expect(noteText(d)).toBe(CAMERA_BLOCKED);
    expect(writes(h)).toBe(0);
    un();
  });
});

describe("Drop files onto the composer", () => {
  const drag = (el: Element, type: string, files: File[] = []) => {
    const ev = new Event(type, { bubbles: true, cancelable: true });
    Object.defineProperty(ev, "dataTransfer", { value: { files } });
    el.dispatchEvent(ev);
  };
  it("shows OF's \"Drop files to upload\" and uploads the dropped files as Add media's", async () => {
    const d = loadPage("chat");
    const s = memoryStorage();
    const h = handlers();
    const un = bindChat(d, "messages/chat", ctxOf(h, s));
    const area = $(d, ".b-dropzone__label:not([aria-hidden])").parentElement!;
    drag(area, "dragenter");
    expect(area.classList.contains("is-dragover")).toBe(true);
    drag(area, "dragleave");
    expect(area.classList.contains("is-dragover")).toBe(false);
    const file = new File(["x"], "a.jpg", { type: "image/jpeg" });
    drag(area, "dragenter");
    drag(area, "drop", [file]);
    expect(area.classList.contains("is-dragover")).toBe(false);
    expect(h.upload).toHaveBeenCalledWith(file);
    await flush();
    expect(loadChatDraft(s, ACCOUNT, CHAT).media_files).toEqual([{ processId: "p1" }]);
    un();
  });
  it("without a model nothing is uploaded", () => {
    const d = loadPage("chat");
    const un = bindChat(d, "messages/chat", ctxOf(null, memoryStorage()));
    const area = $(d, ".b-dropzone__label:not([aria-hidden])").parentElement!;
    drag(area, "drop", [new File(["x"], "a.jpg")]);
    expect(noteText(d)).toBe(SELECT_MODEL);
    un();
  });
});

describe("Tag other creators (messages/chat/state-tag-people)", () => {
  const ITEMS: TaggedFriendUser[] = [
    { id: 2001, name: "Synth Creator 1", type: "user", user: { id: 2001, name: "Synth Creator 1", username: "synthcreator1" } },
    { id: 77, name: "Synth Guest", type: "guest" },
    { id: 88, name: "Synth &amp; Form", type: "document" },
  ];
  it("New post's dialog over the chat: a row tags it on the chat draft; Send carries OF's three tag fields", () => {
    const s = memoryStorage();
    const h = handlers();
    let d = loadPage("chat/state-tag-people");
    let un = bindChat(d, "messages/chat/state-tag-people", ctxOf(h, s, { tagItems: ITEMS }));
    const rows = [...d.querySelectorAll<HTMLElement>("label.b-rows-lists__item[data-oi-user]")];
    expect(rows.map((r) => [r.getAttribute("data-oi-user"), r.getAttribute("data-oi-type")])).toEqual([["2001", "user"], ["77", "guest"], ["88", "document"]]);
    for (const r of rows) {
      const box = $<HTMLInputElement>(r, "input[type='checkbox']");
      box.checked = true;
      box.dispatchEvent(new Event("change", { bubbles: true }));
    }
    expect(loadChatDraft(s, ACCOUNT, CHAT).tags).toEqual([
      { id: 2001, type: "user", name: "Synth Creator 1" },
      { id: 77, type: "guest", name: "Synth Guest" },
      { id: 88, type: "document", name: "Synth & Form" }, // OF's HTML-encoded name, decoded
    ]);
    // Unticking drops it.
    const first = $<HTMLInputElement>(rows[2], "input[type='checkbox']");
    first.checked = false;
    first.dispatchEvent(new Event("change", { bubbles: true }));
    expect(loadChatDraft(s, ACCOUNT, CHAT).tags!.map((t) => t.id)).toEqual([2001, 77]);
    // The tabs keep the chat.
    $(d, ".modal.show .b-tabs__nav__link:not(.m-current)").click();
    expect(h.navigate).toHaveBeenCalledWith(`/of-manager/messages/chat/state-tag-people?tab=forms&chat=${CHAT}`);
    un();
    d = loadPage("chat");
    un = bindChat(d, "messages/chat", ctxOf(h, s));
    expect(d.getElementById("oi-chat-summary")!.textContent).toContain("Tagged: Synth Creator 1, Synth Guest");
    // Tags turn Add GIF off (OF: release forms).
    expect($(d, "button[aria-label='Add GIF']").hasAttribute("disabled")).toBe(true);
    editor(d).innerHTML = "<p>hi</p>";
    editor(d).dispatchEvent(new Event("input", { bubbles: true }));
    send(d).click();
    expect(h.send).toHaveBeenCalledWith(`/api/of/v2/chats/${CHAT}/messages`, { text: "hi", price: 0, media_files: [], tagged_users: [2001], rf_guest: [77] });
    un();
  });
  it("All-Creators: no rows, nothing tagged", () => {
    const d = loadPage("chat/state-tag-people");
    const s = memoryStorage();
    const un = bindChat(d, "messages/chat/state-tag-people", ctxOf(null, s, { tagItems: ITEMS }));
    expect(d.querySelectorAll("label.b-rows-lists__item[data-oi-user]").length).toBe(0);
    expect(s.length).toBe(0);
    un();
  });
});

describe("devils-advocate fixes: GIF alone, drops, recorder types, rebinds", () => {
  const drag = (el: Element, type: string, files: File[] = []) => {
    const ev = new Event(type, { bubbles: true, cancelable: true });
    Object.defineProperty(ev, "dataTransfer", { value: { files } });
    el.dispatchEvent(ev);
  };
  const area = (d: Document) => $(d, ".b-dropzone__label:not([aria-hidden])").parentElement!;

  it("a plain text send is exactly as before: one POST {text, price 0, media_files []}", () => {
    const d = loadPage("chat");
    const h = handlers();
    const un = bindChat(d, "messages/chat", ctxOf(h, memoryStorage()));
    editor(d).innerHTML = "<p>hello</p>";
    editor(d).dispatchEvent(new Event("input", { bubbles: true }));
    send(d).click();
    expect(h.send.mock.calls).toEqual([[`/api/of/v2/chats/${CHAT}/messages`, { text: "hello", price: 0, media_files: [] }]]);
    expect(writes(h)).toBe(1);
    un();
  });

  it("with a GIF: Tag creators, Add media and the vault are locked as OF's, a click on them only says why, and a drop uploads nothing", () => {
    const d = loadPage("chat");
    const s = memoryStorage();
    const h = handlers();
    saveDraft(s, draft({ giphy_id: "g1", giphy_thumb: "t" }));
    const un = bindChat(d, "messages/chat", ctxOf(h, s));
    const tag = $(d, "[at-attr='release_forms_btn']");
    const add = $(d, "button.attach_file[aria-label='Add media']");
    const vault = $(d, "[at-attr='add_vault_media']");
    for (const el of [tag, add, vault]) {
      expect(el.hasAttribute("disabled")).toBe(true);
      expect(el.style.pointerEvents).toBe("none");
      const click = new MouseEvent("click", { bubbles: true, cancelable: true });
      el.dispatchEvent(click); // a keyboard Enter on the focused control
      expect(click.defaultPrevented).toBe(true);
      expect(noteText(d)).toBe(GIF_ALONE);
    }
    expect(h.navigate).not.toHaveBeenCalled();
    drag(area(d), "drop", [new File(["x"], "a.jpg", { type: "image/jpeg" })]);
    expect(h.upload).not.toHaveBeenCalled();
    expect(noteText(d)).toBe(GIF_ALONE);
    // Delete the GIF: they come back.
    $(d, "[data-oi-gif-delete]").click();
    for (const el of [tag, add, vault]) expect(el.hasAttribute("disabled")).toBe(false);
    expect(writes(h)).toBe(0);
    un();
  });

  it("a voice note may still join a GIF (OF's rule); a body never carries giphy_id with other media, tags or a price", async () => {
    const d = loadPage("chat");
    const s = memoryStorage();
    const h = handlers();
    saveDraft(s, draft({ giphy_id: "g1" }));
    const un = bindChat(d, "messages/chat", ctxOf(h, s));
    drag(area(d), "drop", [new File(["v"], "v.webm", { type: "audio/webm" })]);
    expect(h.upload).toHaveBeenCalledTimes(1);
    await flush();
    expect(loadChatDraft(s, ACCOUNT, CHAT)).toMatchObject({ giphy_id: "g1", media_files: [{ processId: "p1" }], audio: 1 });
    un();
    expect(collectMessage("", draft({ giphy_id: "g1", media_files: [{ processId: "v" }], audio: 1 }))).toEqual({ text: "", price: 0, media_files: [{ processId: "v" }], giphy_id: "g1" });
    expect(collectMessage("", draft({ giphy_id: "g1", media_files: [61] }))).toBe(GIF_ALONE);
    expect(collectMessage("", draft({ giphy_id: "g1", tags: [{ id: 501, type: "user", name: "A" }] }))).toBe(GIF_ALONE);
    expect(collectMessage("", draft({ giphy_id: "g1", price: 5 }))).toBe(GIF_ALONE);
  });

  it("the vault dialog adds no vault media while a GIF is set", () => {
    const d = loadPage("chat/state-vault");
    const s = memoryStorage();
    saveDraft(s, draft({ giphy_id: "g1" }));
    const un = bindChat(d, "messages/chat/state-vault", ctxOf(handlers(), s));
    const tile = $(d, ".b-photos__item.m-checkbox-control");
    tile.setAttribute("data-oi-media", "61");
    tile.click();
    expect(loadChatDraft(s, ACCOUNT, CHAT).media_files).toEqual([]);
    expect(noteText(d)).toBe(GIF_ALONE);
    un();
  });

  it("a drop takes only photos, videos and audio, and names what it left out", () => {
    const d = loadPage("chat");
    const h = handlers();
    const un = bindChat(d, "messages/chat", ctxOf(h, memoryStorage()));
    const pic = new File(["x"], "a.jpg", { type: "image/jpeg" });
    drag(area(d), "drop", [new File(["%PDF"], "doc.pdf", { type: "application/pdf" }), pic, new File(["z"], "notes.txt", { type: "text/plain" })]);
    expect(h.upload.mock.calls).toEqual([[pic]]);
    expect(noteText(d)).toBe(notMedia(["doc.pdf", "notes.txt"]));
    drag(area(d), "drop", [new File(["z"], "x.zip", { type: "application/zip" })]);
    expect(h.upload).toHaveBeenCalledTimes(1);
    un();
  });

  it("an audio file picked in Add media counts as the voice note (Record voice turns off)", async () => {
    const d = loadPage("chat");
    const s = memoryStorage();
    const h = handlers();
    const un = bindChat(d, "messages/chat", ctxOf(h, s));
    const input = d.querySelector<HTMLInputElement>("input[type='file'][data-oi-wired]")!;
    Object.defineProperty(input, "files", { value: [new File(["a"], "a.m4a", { type: "audio/mp4" })], configurable: true });
    input.dispatchEvent(new Event("change"));
    await flush();
    expect(loadChatDraft(s, ACCOUNT, CHAT)).toMatchObject({ media_files: [{ processId: "p1" }], audio: 1 });
    expect($(d, "button[aria-label='Record voice']").hasAttribute("disabled")).toBe(true);
    un();
  });

  it("the recorders ask for mp4 first (then webm) and the uploaded File's type has no ;codecs", async () => {
    expect(bareType("video/webm;codecs=vp8,opus")).toBe("video/webm");
    const m = fakeMedia(undefined, { supported: ["audio/mp4", "audio/webm", "video/mp4", "video/webm"], recorded: (t) => `${t};codecs=avc1,mp4a.40.2` });
    const d = loadPage("chat");
    const h = handlers();
    const un = bindChat(d, "messages/chat", ctxOf(h, memoryStorage()));
    $(d, "button[aria-label='Record voice']").click();
    $(d, ".b-float-panel__btn-record").click();
    await flush();
    $(d, ".b-float-panel__btn-record").click();
    expect(m.recorders[0].asked).toBe("audio/mp4");
    const voice = h.upload.mock.calls[0][0];
    expect(voice.type).toBe("audio/mp4");
    expect(voice.name).toMatch(/^voice-\d+\.m4a$/);
    un();
    await flush();
    // Only webm recordable: webm is asked for.
    const m2 = fakeMedia(undefined, { supported: ["video/webm"], recorded: (t) => `${t};codecs=vp8,opus` });
    const d2 = loadPage("chat");
    const h2 = handlers();
    const un2 = bindChat(d2, "messages/chat", ctxOf(h2, memoryStorage()));
    $(d2, "button.js-chat__video-record-btn").click();
    await flush();
    $(d2, ".vjs-record-button").click();
    $(d2, ".vjs-record-button").click();
    expect(m2.recorders[0].asked).toBe("video/webm");
    const clip = h2.upload.mock.calls[0][0];
    expect(clip.type).toBe("video/webm");
    expect(clip.name).toMatch(/^video-\d+\.webm$/);
    un2();
  });

  it("unbinding mid-recording stops every track and uploads nothing", async () => {
    const m = fakeMedia();
    const d = loadPage("chat");
    const h = handlers();
    const un = bindChat(d, "messages/chat", ctxOf(h, memoryStorage()));
    $(d, "button[aria-label='Record voice']").click();
    $(d, ".b-float-panel__btn-record").click();
    await flush();
    expect(m.recorders[0].state).toBe("recording");
    un();
    await flush();
    expect(m.recorders[0].state).toBe("inactive");
    expect(m.tracks[0].stop).toHaveBeenCalled();
    expect(writes(h)).toBe(0);
  });

  it("unbinding mid-permission: the stream granted afterwards is stopped at once, nothing recorded or uploaded", async () => {
    const m = fakeMedia(undefined, { hold: true });
    const d = loadPage("chat");
    const h = handlers();
    const un = bindChat(d, "messages/chat", ctxOf(h, memoryStorage()));
    $(d, "button[aria-label='Record voice']").click();
    $(d, ".b-float-panel__btn-record").click();
    expect(m.getUserMedia).toHaveBeenCalledTimes(1);
    un();
    await flush();
    m.grant();
    await flush();
    expect(m.tracks[0].stop).toHaveBeenCalled();
    expect(m.recorders).toHaveLength(0);
    expect(writes(h)).toBe(0);
    // The camera too.
    const v = fakeMedia(undefined, { hold: true });
    const d2 = loadPage("chat");
    const un2 = bindChat(d2, "messages/chat", ctxOf(h, memoryStorage()));
    $(d2, "button.js-chat__video-record-btn").click();
    un2();
    await flush();
    v.grant();
    await flush();
    expect(v.tracks[0].stop).toHaveBeenCalled();
    expect(writes(h)).toBe(0);
  });

  it("a rebind of the same chat (its name, mute or tips flag changed) keeps a recording going; its stop uploads once", async () => {
    const m = fakeMedia();
    const d = loadPage("chat");
    const s = memoryStorage();
    const h = handlers();
    let un = bindChat(d, "messages/chat", ctxOf(h, s));
    $(d, "button[aria-label='Record voice']").click();
    $(d, ".b-float-panel__btn-record").click();
    await flush();
    // useOfChat's effect: the old bind's cleanup, then the new bind, in one go.
    un();
    un = bindChat(d, "messages/chat", ctxOf(h, s, { fan: { name: "Fan A renamed", muted: true, tipsEnabled: true } }));
    await flush();
    expect(m.recorders[0].state).toBe("recording");
    expect(m.tracks[0].stop).not.toHaveBeenCalled();
    expect($(d, ".js-chat__audiorecord-panel").style.display).toBe("");
    $(d, ".b-float-panel__btn-record").click();
    expect(h.upload).toHaveBeenCalledTimes(1);
    await flush();
    expect(loadChatDraft(s, ACCOUNT, CHAT)).toMatchObject({ media_files: [{ processId: "p1" }], audio: 1 });
    un();
    // Another chat on the same document: the recording does not follow it.
    const m2 = fakeMedia();
    const d2 = loadPage("chat");
    const h2 = handlers();
    const s2 = memoryStorage();
    un = bindChat(d2, "messages/chat", ctxOf(h2, s2));
    $(d2, "button[aria-label='Record voice']").click();
    $(d2, ".b-float-panel__btn-record").click();
    await flush();
    un();
    un = bindChat(d2, "messages/chat", ctxOf(h2, s2, { chat: "9002" }));
    expect(m2.recorders[0].state).toBe("inactive");
    expect(m2.tracks[0].stop).toHaveBeenCalled();
    expect(writes(h2)).toBe(0);
    un();
  });
});

describe("New message: the chat composer's tools on the Mass draft", () => {
  const LISTS = [{ id: "fans", name: "Fans", usersCount: 12 }];
  const mass = (h: H | null, s: Storage, over: Partial<ChatContext> = {}) => ctxOf(h, s, { chat: null, fan: undefined, lists: LISTS, ...over });
  const saveMass = (s: Storage, d: Partial<MassDraft>) => s.setItem(massDraftKey(ACCOUNT), JSON.stringify({ text: "", user_lists: ["fans"], ...d }));
  const tag = (id: number, type: string) => ({ id, type, name: `#${id}` });

  it("the mass body carries tagged creators and a GIF; OF's GIF rule, no guest or release-form tag, no GIF on an edit", () => {
    const d = (over: Partial<MassDraft>): MassDraft => ({ text: "", user_lists: ["fans"], ...over });
    expect(collectMass("hi", d({ tags: [tag(2001, "user")], price: 5, media_files: [61] }))).toEqual({ text: "hi", user_lists: ["fans"], media_files: [61], price: 5, tagged_users: [2001] });
    expect(collectMass("", d({ giphy_id: "g1" }))).toEqual({ text: "", user_lists: ["fans"], giphy_id: "g1" });
    expect(collectMass("", d({ giphy_id: "g1", media_files: [{ processId: "a" }], audio: 1 }))).toEqual({ text: "", user_lists: ["fans"], media_files: [{ processId: "a" }], giphy_id: "g1" });
    expect(collectMass("x", d({ giphy_id: "g1", price: 5 }))).toBe(GIF_ALONE);
    expect(collectMass("x", d({ giphy_id: "g1", media_files: [61] }))).toBe(GIF_ALONE);
    expect(collectMass("x", d({ tags: [tag(77, "guest")] }))).toBe(NO_MASS_FORMS);
    expect(collectMass("x", d({ tags: [tag(88, "link")] }))).toBe(NO_MASS_FORMS);
    expect(collectMass("x", d({ giphy_id: "g1", save_for_later: true, edit_id: "6105" }))).toBe(NO_EDIT_GIF);
  });

  it("the tools are wired on New message: Add media uploads and its claim goes in the POST /messages/queue body", async () => {
    const d = loadPage("send");
    const s = memoryStorage();
    saveMass(s, {});
    const h = handlers();
    const un = bindMass(d, mass(h, s));
    for (const sel of ["button[aria-label='Add media']", "button[aria-label='Add GIF']", "button[aria-label='Record voice']", "button[aria-label='Format Text']"]) expect($(d, sel).hasAttribute("data-oi-wired"), sel).toBe(true);
    const picker = $<HTMLInputElement>(d, "input[type='file'][data-oi-wired]");
    const file = new File(["x"], "a.jpg", { type: "image/jpeg" });
    Object.defineProperty(picker, "files", { value: [file], configurable: true });
    picker.dispatchEvent(new Event("change"));
    expect(h.upload).toHaveBeenCalledWith(file);
    expect(send(d).disabled).toBe(true); // uploading
    await flush();
    expect(loadMassDraft(s, ACCOUNT).media_files).toEqual([{ processId: "p1" }]);
    expect(d.getElementById("oi-chat-summary")!.textContent).toContain("1 media");
    expect(send(d).disabled).toBe(false); // media alone is a message
    send(d).click();
    expect(h.send).toHaveBeenCalledWith("/api/of/v2/messages/queue", { text: "", user_lists: ["fans"], media_files: [{ processId: "p1" }] });
    un();
  });

  it("Add GIF on New message: a pick is the Mass draft's giphy_id and Send sends it; Clear drops every extra", async () => {
    const d = loadPage("send");
    const s = memoryStorage();
    saveMass(s, {});
    const h = handlers();
    const un = bindMass(d, mass(h, s));
    $(d, "button[aria-label='Add GIF']").click();
    expect(h.gifs).toHaveBeenCalledWith("");
    await flush();
    $(d, "[data-oi-gif='g2']").click();
    expect(loadMassDraft(s, ACCOUNT)).toMatchObject({ giphy_id: "g2", user_lists: ["fans"] });
    expect(d.getElementById("oi-chat-summary")!.textContent).toContain("GIF");
    expect($(d, "button[aria-label='Add GIF']").hasAttribute("disabled")).toBe(true);
    send(d).click();
    expect(h.confirm).toHaveBeenCalledWith("Send this message to 12 users on Fans?");
    expect(h.send).toHaveBeenCalledWith("/api/of/v2/messages/queue", { text: "", user_lists: ["fans"], giphy_id: "g2" });
    un();
    const d2 = loadPage("send");
    saveMass(s, { giphy_id: "g1", price: 5, tags: [tag(2001, "user")] });
    const un2 = bindMass(d2, mass(h, s));
    $(d2, "[data-oi-clear]").click();
    expect(loadMassDraft(s, ACCOUNT)).toEqual({ text: "", user_lists: ["fans"] });
    expect(d2.getElementById("oi-chat-gif")).toBeNull();
    un2();
  });

  it("Message price over New message (send/state-price): Save keeps it on the Mass draft and goes back; Send asks with the price", () => {
    const s = memoryStorage();
    saveMass(s, { text: "ppv" });
    const h = handlers();
    let d = loadPage("send/state-price");
    let un = bindMass(d, mass(h, s), "messages/send/state-price");
    const input = $<HTMLInputElement>(d, ".modal.show input[at-attr='input']");
    input.value = "15";
    input.dispatchEvent(new Event("input", { bubbles: true }));
    $(d, ".modal.show .modal-footer button").click();
    expect(loadMassDraft(s, ACCOUNT).price).toBe(15);
    expect(h.navigate).toHaveBeenCalledWith("/of-manager/messages/send");
    un();
    d = loadPage("send");
    un = bindMass(d, mass(h, s));
    expect(d.getElementById("oi-chat-summary")!.textContent).toContain("Price: $15");
    send(d).click();
    expect(h.confirm).toHaveBeenCalledWith("Send this message to 12 users on Fans for $15?");
    expect(h.send).toHaveBeenCalledWith("/api/of/v2/messages/queue", { text: "ppv", user_lists: ["fans"], price: 15 });
    un();
  });

  it("Add media from vault over New message (send/state-vault): a tile only ticks, a type tab keeps the ticks, Add appends them (no chat)", () => {
    const s = memoryStorage();
    saveMass(s, { media_files: [5], thumbs: ["five.jpg"] });
    const h = handlers();
    let d = loadPage("send/state-vault");
    applyData(d, "messages/send/state-vault", { vaultMedia: [{ id: 62, type: "photo" } as VaultMedia], picked: [] });
    let un = bindMass(d, mass(h, s, { vaultView: { list: "7" } }), "messages/send/state-vault");
    $(d, "[data-oi-media='62']").click();
    expect(loadMassDraft(s, ACCOUNT)).toMatchObject({ media_files: [5], user_lists: ["fans"] });
    expect($(d, "[data-oi-media='62']").classList.contains("selected")).toBe(true);
    [...d.querySelectorAll<HTMLElement>(".modal.show .b-tabs__nav__link")][3].click();
    expect(h.navigate).toHaveBeenCalledWith("/of-manager/messages/send/state-vault?list=7&type=video");
    un();
    // The Video tab's page: the tick is still there (ofMirrorData pre-marks it), and so is the bar.
    expect(loadVaultPick(s, vaultPickKey(ACCOUNT, "messages/send/state-vault")).ids).toEqual([62]);
    d = loadPage("send/state-vault");
    applyData(d, "messages/send/state-vault", { vaultMedia: [{ id: 62, type: "photo" } as VaultMedia], picked: [62] });
    un = bindMass(d, mass(h, s, { vaultView: { list: "7", type: "video" } }), "messages/send/state-vault");
    expect($(d, "[data-oi-vault-bar] .b-row-selected__text").textContent!.trim()).toBe("1 / 40 Selected");
    $(d, "[data-oi-vault-bar] button[data-oi-vault-add]").click();
    expect(loadMassDraft(s, ACCOUNT)).toMatchObject({ media_files: [5, 62], user_lists: ["fans"] });
    expect(h.navigate).toHaveBeenLastCalledWith("/of-manager/messages/send");
    un();
  });

  it("New message's vault: Close goes back with nothing attached and the ticks dropped", () => {
    const s = memoryStorage();
    saveMass(s, {});
    const h = handlers();
    const d = loadPage("send/state-vault");
    applyData(d, "messages/send/state-vault", { vaultMedia: [{ id: 62, type: "photo" } as VaultMedia], picked: [] });
    let un = bindMass(d, mass(h, s), "messages/send/state-vault");
    $(d, "[data-oi-media='62']").click();
    expect($(d, ".modal.show .modal-footer a").getAttribute("href")).toBe("/of-manager/messages/send");
    un();
    un = bindMass(loadPage("send"), mass(h, s));
    expect(loadMassDraft(s, ACCOUNT).media_files ?? []).toEqual([]);
    expect(loadVaultPick(s, vaultPickKey(ACCOUNT, "messages/send/state-vault")).ids).toEqual([]);
    un();
  });

  it("Tag other creators over New message (send/state-tag-people): a creator goes as tagged_users; a guest is refused", () => {
    const ITEMS: TaggedFriendUser[] = [
      { id: 2001, name: "Synth Creator 1", type: "user", user: { id: 2001, name: "Synth Creator 1", username: "synthcreator1" } },
      { id: 77, name: "Synth Guest", type: "guest" },
    ];
    const s = memoryStorage();
    saveMass(s, { text: "hi" });
    const h = handlers();
    let d = loadPage("send/state-tag-people");
    let un = bindMass(d, mass(h, s, { tagItems: ITEMS }), "messages/send/state-tag-people");
    const rows = [...d.querySelectorAll<HTMLElement>("label.b-rows-lists__item[data-oi-user]")];
    expect(rows.map((r) => r.getAttribute("data-oi-user"))).toEqual(["2001", "77"]);
    // In the dialog, shown; the Send to lists behind it are New message's own.
    expect(rows.every((r) => r.closest(".modal.show") && r.style.display !== "none")).toBe(true);
    expect([...d.querySelectorAll(".b-chats__scroller label.b-rows-lists__item[data-oi-list]")].map((r) => r.getAttribute("data-oi-list"))).toEqual(["fans"]);
    const tick = (r: HTMLElement, on: boolean) => {
      const box = $<HTMLInputElement>(r, "input[type='checkbox']");
      box.checked = on;
      box.dispatchEvent(new Event("change", { bubbles: true }));
    };
    tick(rows[0], true);
    tick(rows[1], true);
    expect(loadMassDraft(s, ACCOUNT).tags!.map((t) => t.id)).toEqual([2001, 77]);
    $(d, ".modal.show .b-tabs__nav__link:not(.m-current)").click();
    expect(h.navigate).toHaveBeenCalledWith("/of-manager/messages/send/state-tag-people?tab=forms");
    un();
    d = loadPage("send");
    un = bindMass(d, mass(h, s));
    expect(d.getElementById("oi-chat-summary")!.textContent).toContain("Tagged: Synth Creator 1, Synth Guest");
    send(d).click();
    expect(noteText(d)).toBe(NO_MASS_FORMS);
    expect(h.send).not.toHaveBeenCalled();
    un();
    d = loadPage("send/state-tag-people");
    un = bindMass(d, mass(h, s, { tagItems: ITEMS }), "messages/send/state-tag-people");
    tick([...d.querySelectorAll<HTMLElement>("label.b-rows-lists__item[data-oi-user]")][1], false);
    un();
    d = loadPage("send");
    un = bindMass(d, mass(h, s));
    send(d).click();
    expect(h.send).toHaveBeenCalledWith("/api/of/v2/messages/queue", { text: "hi", user_lists: ["fans"], tagged_users: [2001] });
    un();
  });

  it("Format Text on New message: formatted text is kept as OF's markup, restored on load and sent as the text", () => {
    const s = memoryStorage();
    saveMass(s, {});
    const h = handlers();
    let d = loadPage("send");
    let un = bindMass(d, mass(h, s));
    $(d, "button[aria-label='Format Text']").click();
    expect($(d, "[data-oi-format-panel]").style.display).not.toBe("none");
    editor(d).innerHTML = "<p><strong>Bold</strong> plain</p>";
    editor(d).dispatchEvent(new Event("input", { bubbles: true }));
    const html = loadMassDraft(s, ACCOUNT).html!;
    expect(html).toContain("<strong>Bold</strong>");
    un();
    d = loadPage("send");
    un = bindMass(d, mass(h, s));
    expect(editor(d).querySelector("strong")!.textContent).toBe("Bold");
    send(d).click();
    expect(h.send).toHaveBeenCalledWith("/api/of/v2/messages/queue", { text: html, user_lists: ["fans"] });
    un();
  });

  it("All-Creators: the tools upload and pick nothing on New message", () => {
    const d = loadPage("send");
    const s = memoryStorage();
    const un = bindMass(d, mass(null, s));
    const picker = $<HTMLInputElement>(d, "input[type='file'][data-oi-wired]");
    $(d, "button[aria-label='Add media']").click();
    expect(noteText(d)).toBe(SELECT_MODEL);
    Object.defineProperty(picker, "files", { value: [new File(["x"], "a.jpg", { type: "image/jpeg" })], configurable: true });
    picker.dispatchEvent(new Event("change"));
    $(d, "button[aria-label='Add GIF']").click();
    expect(s.length).toBe(0);
    un();
  });
});
