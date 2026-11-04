import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it, vi } from "vitest";
import {
  bindMass,
  collectMass,
  loadMassDraft,
  massDraftKey,
  tickMassList,
  MASS_PICKED_TITLE,
  massViewOf,
  massRequest,
  NO_LISTS,
} from "./ofMirrorMass";
import { applyListRows } from "./ofMirrorDataLists";
import { EMPTY_MESSAGE, NO_DATE, type ChatContext } from "./ofMirrorChatShared";
import { localIso, SELECT_MODEL, TOO_SOON } from "./ofMirrorWrites";
import type { VaultUploadResp } from "./relay";

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

describe("collectMass: Exclude wins over Send to", () => {
  const rows: Array<[string, Parameters<typeof collectMass>[1], ReturnType<typeof collectMass>]> = [
    ["a list on both: dropped from user_lists, kept in excluded", { text: "", user_lists: ["fans", "42"], excluded_user_lists: ["42"] }, { text: "hi", user_lists: ["fans"], excluded_user_lists: ["42"] }],
    ["a stale draft (both hold it, other lists picked too): disjoint, the list only in excluded", { text: "", user_lists: ["fans", "42", "7"], excluded_user_lists: ["99", "42"] }, { text: "hi", user_lists: ["fans", "7"], excluded_user_lists: ["99", "42"] }],
    ["the overlap is the only Send to list and no user_ids: NO_LISTS", { text: "", user_lists: ["42"], excluded_user_lists: ["42"] }, NO_LISTS],
    ["the overlap is the only Send to list, with user_ids: user_lists empty, the fans kept", { text: "", user_lists: ["42"], excluded_user_lists: ["42"], user_ids: [501] }, { text: "hi", user_lists: [], user_ids: [501], excluded_user_lists: ["42"] }],
  ];
  it.each(rows)("%s", (_name, draft, want) => {
    const body = collectMass("hi", draft);
    expect(body).toEqual(want);
    if (typeof body !== "string") {
      expect(body.user_lists.filter((l) => body.excluded_user_lists?.includes(l))).toEqual([]);
      expect(body.excluded_user_lists).toEqual(draft.excluded_user_lists);
    }
  });
  it("no overlap: the body is byte-identical to before", () => {
    const draft = { text: "", user_lists: ["fans", "42"], excluded_user_lists: ["99"], user_ids: [501], media_files: [8105], price: 5 };
    const before = { text: "hi", user_lists: ["fans", "42"], user_ids: [501], excluded_user_lists: ["99"], media_files: [8105], price: 5 };
    expect(JSON.stringify(collectMass("hi", draft))).toBe(JSON.stringify(before));
    expect(JSON.stringify(collectMass("hi", { text: "", user_lists: ["fans"] }))).toBe(JSON.stringify({ text: "hi", user_lists: ["fans"] }));
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
