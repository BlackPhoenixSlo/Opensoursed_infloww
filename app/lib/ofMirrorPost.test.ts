import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { applyLabelRows, applyTagRows, bindPost, RECORD_TEXT, POSTED_TOAST, SAVED_TOAST, clearDraft, collectPost, collectSchedule, draftKey, labelsOf, loadDraft, mergeSendWith, postLabelsOf, postPriceLimits, readPrice, renderCalendar, saveDraft, vaultStoryBody, type PostDraft, type PostLabelsResp } from "./ofMirrorPost";
import type { OfMe } from "./ofMirrorIdentity";
import { standInModel } from "./ofMirrorProfile";
import { bindWrites, localIso, NOT_YET, OLD_RELAY, SELECT_MODEL } from "./ofMirrorWrites";
import { applyData } from "./ofMirrorData";
import { RelayError, type TaggedFriendUser, type VaultList, type VaultMedia } from "./relay";

/** A scrubbed OF response (app/lib/__fixtures__/of/<name>.json). */
const fixture = (name: string): unknown => JSON.parse(readFileSync(resolve(__dirname, `__fixtures__/of/${name}.json`), "utf8"));
/** A committed new-post capture (path under of-mirror/pages/new-post). */
const loadPage = (page: string) => {
  document.documentElement.innerHTML = readFileSync(resolve(__dirname, `../public/of-mirror/pages/new-post/${page}.html`), "utf8");
  return document;
};
/** An in-memory Storage, so a test never touches the real sessionStorage. */
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
const empty = (): PostDraft => ({ text: "", tagged_users: [], media_files: [], thumbs: [] });
/** What bindPost marks on New post's index: Post, Add media and its picker, Record video and voice, the right column's search. */
const composerWired = (d: Document) => [
  d.querySelector("button[at-attr='submit_post']"),
  d.querySelector("button[aria-label='Add media']"),
  d.querySelector("input[type=file]"),
  d.querySelector("button[aria-label='Record video']"),
  d.querySelector("button[aria-label='Record voice']"),
  d.querySelector("input[name='feed-search-input']"),
  d.querySelector("input[name='feed-search-input']")!.closest("form"),
  d.querySelector("input[name='feed-search-input']")!.closest("form")!.querySelector("button[type='submit']"),
];
const flush = () => new Promise((r) => setTimeout(r, 0));
const EDITOR = "[contenteditable][aria-label='Textbox field']";
const POST = "button[at-attr='submit_post']";
const editor = (d: Document) => d.querySelector<HTMLElement>(EDITOR)!;
const post = (d: Document) => d.querySelector<HTMLButtonElement>(POST)!;
/** Type `text` into OF's editor as the browser would: one paragraph per line, then an input event. */
const type = (d: Document, text: string) => {
  editor(d).innerHTML = text.split("\n").map((l) => `<p>${l || "<br>"}</p>`).join("");
  editor(d).dispatchEvent(new Event("input", { bubbles: true }));
};
const handlers = (createPost = vi.fn((_body: unknown) => Promise.resolve({ id: 1 }))) => ({
  createPost,
  createLabel: vi.fn((_name: string) => Promise.resolve({ id: 77 })),
  upload: vi.fn(),
  addVaultStory: vi.fn((_body: unknown) => Promise.resolve({})),
  navigate: vi.fn(),
  posted: vi.fn(),
});
/** OF's toast text, if one shows. */
const toastText = (d: Document) => d.querySelector(".toasts-host .v-snack.m-alert .toast__text")?.textContent;

describe("collectPost", () => {
  it("text only gives exactly the Known body: lines joined by newlines, outer whitespace trimmed", () => {
    expect(collectPost("  Synthetic post\nsecond line \n", empty())).toEqual({ text: "Synthetic post\nsecond line", media_files: [], price: 0 });
  });

  it("omits absent keys rather than sending null", () => {
    expect(Object.keys(collectPost("Synthetic post", empty()) as object).sort()).toEqual(["media_files", "price", "text"]);
  });

  it("Co-tags add tagged_users, alongside posted_at", () => {
    const now = new Date(2026, 9, 12, 10, 0);
    const at = "2026-10-13T18:30:00+02:00";
    expect(collectPost("Synthetic post", { ...empty(), tagged_users: [2001, 2002] }, now)).toEqual({ text: "Synthetic post", media_files: [], price: 0, tagged_users: [2001, 2002] });
    expect(collectPost("Synthetic post", { ...empty(), posted_at: at, tagged_users: [2001] }, now)).toEqual({ text: "Synthetic post", media_files: [], price: 0, posted_at: at, tagged_users: [2001] });
  });

  it("picked vault media go as integer ids in click order", () => {
    const draft = { ...empty(), media_files: [62, 61], thumbs: ["/img?u=a&account_id=1", "/img?u=b&account_id=1"] };
    expect(collectPost("Synthetic post", draft)).toEqual({ text: "Synthetic post", media_files: [62, 61], price: 0 });
  });

  it("empty or whitespace text gives the validation string", () => {
    expect(typeof collectPost("", empty())).toBe("string");
    expect(typeof collectPost(" \n\t ", empty())).toBe("string");
  });

  it("a scheduled draft adds posted_at; one less than a minute ahead gives the note", () => {
    const now = new Date(2026, 9, 12, 10, 0);
    const at = "2026-10-13T18:30:00+02:00";
    expect(collectPost("Synthetic post", { ...empty(), posted_at: at }, now)).toEqual({ text: "Synthetic post", media_files: [], price: 0, posted_at: at });
    const soon = localIso(new Date(2026, 9, 12, 10, 0, 30));
    expect(collectPost("Synthetic post", { ...empty(), posted_at: soon }, now)).toBe("Pick a time at least a minute from now");
    const past = localIso(new Date(2026, 9, 12, 9, 0));
    expect(collectPost("Synthetic post", { ...empty(), posted_at: past }, now)).toBe("Pick a time at least a minute from now");
  });

  it("save for later goes as save_for_later alone, a stale schedule beside it ignored", () => {
    const now = new Date(2026, 9, 12, 10, 0);
    const past = localIso(new Date(2026, 9, 12, 9, 0));
    expect(collectPost("Synthetic post", { ...empty(), save_for_later: true, posted_at: past }, now)).toEqual({ text: "Synthetic post", media_files: [], price: 0, save_for_later: true });
  });

  it("labels, expiry and a fundraising target ride along under the Relay's names", () => {
    const draft = { ...empty(), label_ids: [11, 12], expire_days: 7, fund_raising_target: 50 };
    expect(collectPost("Synthetic post", draft)).toEqual({ text: "Synthetic post", media_files: [], price: 0, label_ids: [11, 12], expire_days: 7, fund_raising_target: 50 });
    expect(Object.keys(collectPost("Synthetic post", { ...empty(), label_ids: [] }) as object).sort()).toEqual(["media_files", "price", "text"]);
  });

  it("a poll sends its typed options (blanks dropped, trimmed) for OF's 7 days, with no correct answer", () => {
    const draft = { ...empty(), voting: { type: 1 as const, options: [" Yes ", "", "No"], correct: 0 } };
    expect(collectPost("Synthetic post", draft)).toEqual({ text: "Synthetic post", media_files: [], price: 0, voting_type: 1, voting_options: ["Yes", "No"], voting_due: 7 });
  });

  it("a poll's chosen length goes as voting_due; No limit (0) sends none, as OF's composer", () => {
    const voting = { type: 1 as const, options: ["Yes", "No"] };
    expect(collectPost("Synthetic post", { ...empty(), voting, voting_due: 3 })).toMatchObject({ voting_due: 3 });
    expect(collectPost("Synthetic post", { ...empty(), voting, voting_due: 0 })).not.toHaveProperty("voting_due");
  });

  it("a quiz's correct answer is counted among the kept options", () => {
    const draft = { ...empty(), voting: { type: 2 as const, options: ["A", "", "C"], correct: 2 } };
    expect(collectPost("Synthetic post", draft)).toEqual({ text: "Synthetic post", media_files: [], price: 0, voting_type: 2, voting_options: ["A", "C"], voting_due: 7, voting_correct_index: 1 });
  });

  it("a poll with fewer than two options, or a quiz with no (or a blank) correct answer, gives the note", () => {
    expect(collectPost("Synthetic post", { ...empty(), voting: { type: 1, options: ["Yes", " "] } })).toBe("Add at least two options");
    expect(collectPost("Synthetic post", { ...empty(), voting: { type: 2, options: ["A", "B"] } })).toBe("Pick the correct answer");
    expect(collectPost("Synthetic post", { ...empty(), voting: { type: 2, options: ["A", "B", ""], correct: 2 } })).toBe("Pick the correct answer");
  });
});

describe("mergeSendWith", () => {
  it("appends vault ids and claim dicts in the Relay's order after the existing entries", () => {
    expect(mergeSendWith([62, { processId: "p0", host: "h0", name: "n0" }], [{ processId: "p1", host: "h", name: "n" }, 42])).toEqual([
      62,
      { processId: "p0", host: "h0", name: "n0" },
      { processId: "p1", host: "h", name: "n" },
      42,
    ]);
  });

  it("appends a vault id that is already present again", () => {
    expect(mergeSendWith([42], [42])).toEqual([42, 42]);
  });

  it("an empty sendWith gives an equal, new array", () => {
    const mediaFiles = [62, { processId: "p0" }];
    const merged = mergeSendWith(mediaFiles, []);
    expect(merged).toEqual([62, { processId: "p0" }]);
    expect(merged).not.toBe(mediaFiles);
  });

  it("mutates neither input", () => {
    const mediaFiles = [62];
    const sendWith = [{ processId: "p1", host: "h", name: "n" }];
    mergeSendWith(mediaFiles, sendWith);
    expect(mediaFiles).toEqual([62]);
    expect(sendWith).toEqual([{ processId: "p1", host: "h", name: "n" }]);
  });
});

describe("Post draft", () => {
  it("round-trips per account under oi:new-post:<accountId>, and clearDraft removes it", () => {
    const s = memoryStorage();
    expect(draftKey("1")).toBe("oi:new-post:1");
    expect(loadDraft(s, "1")).toEqual(empty());
    saveDraft(s, "1", { ...empty(), text: "Alpha draft" });
    saveDraft(s, "2", { ...empty(), text: "Beta draft" });
    expect(s.getItem("oi:new-post:1")).not.toBeNull();
    expect(loadDraft(s, "1").text).toBe("Alpha draft");
    expect(loadDraft(s, "2").text).toBe("Beta draft");
    clearDraft(s, "1");
    expect(s.getItem("oi:new-post:1")).toBeNull();
    expect(loadDraft(s, "1")).toEqual(empty());
    expect(loadDraft(s, "2").text).toBe("Beta draft");
  });
});

describe("bindPost on the new-post capture", () => {
  const wrapper = (d: Document) => editor(d).closest(".g-input__wrapper")!;

  it("typing enables Post and keeps the placeholder marks in step; clearing disables Post", () => {
    const d = loadPage("index");
    const s = memoryStorage();
    const unbind = bindPost(d, "new-post/index", { handlers: handlers(), storage: s, accountId: "1" });
    expect(post(d).disabled).toBe(true);
    type(d, "Synthetic post");
    expect(post(d).disabled).toBe(false);
    expect(editor(d).getAttribute("data-is-empty")).toBe("false");
    expect(wrapper(d).classList.contains("m-empty")).toBe(false);
    expect(loadDraft(s, "1").text).toBe("Synthetic post");
    type(d, "   ");
    expect(post(d).disabled).toBe(true);
    type(d, "");
    expect(post(d).disabled).toBe(true);
    expect(editor(d).getAttribute("data-is-empty")).toBe("true");
    expect(wrapper(d).classList.contains("m-empty")).toBe(true);
    unbind();
  });

  it("restores the draft as one <p> per line on load, with Post enabled", () => {
    const d = loadPage("state-labels");
    const s = memoryStorage();
    saveDraft(s, "1", { ...empty(), text: "Line one\nLine two" });
    const unbind = bindPost(d, "new-post/state-labels", { handlers: handlers(), storage: s, accountId: "1" });
    expect([...editor(d).querySelectorAll("p")].map((p) => p.textContent)).toEqual(["Line one", "Line two"]);
    expect(post(d).disabled).toBe(false);
    expect(editor(d).getAttribute("data-is-empty")).toBe("false");
    unbind();
  });

  it("keeps drafts per account", () => {
    const s = memoryStorage();
    saveDraft(s, "2", { ...empty(), text: "Beta draft" });
    const d = loadPage("index");
    const unbind = bindPost(d, "new-post/index", { handlers: handlers(), storage: s, accountId: "1" });
    expect(editor(d).textContent).toBe("");
    type(d, "Alpha draft");
    expect(loadDraft(s, "2").text).toBe("Beta draft");
    unbind();
  });

  it("a rebind for another scope shows that scope's draft, or an empty editor", () => {
    const d = loadPage("index");
    const s = memoryStorage();
    let unbind = bindPost(d, "new-post/index", { handlers: handlers(), storage: s, accountId: "1" });
    type(d, "Alpha draft");
    unbind();
    unbind = bindPost(d, "new-post/index", { handlers: null, storage: s, accountId: null });
    expect(editor(d).textContent).toBe("");
    expect(post(d).disabled).toBe(true);
    expect(editor(d).getAttribute("data-is-empty")).toBe("true");
    unbind();
    unbind = bindPost(d, "new-post/index", { handlers: handlers(), storage: s, accountId: "1" });
    expect(editor(d).textContent).toBe("Alpha draft");
    unbind();
  });

  it("Post sends the body once, is disabled in flight, then clears the draft and stays, the composer empty, with OF's toast", async () => {
    const d = loadPage("index");
    const s = memoryStorage();
    const h = handlers();
    const unbind = bindPost(d, "new-post/index", { handlers: h, storage: s, accountId: "1" });
    type(d, "Synthetic post");
    post(d).click();
    expect(post(d).disabled).toBe(true);
    post(d).click();
    expect(h.createPost).toHaveBeenCalledTimes(1);
    expect(h.createPost).toHaveBeenCalledWith({ text: "Synthetic post", media_files: [], price: 0 });
    await flush();
    expect(h.navigate).not.toHaveBeenCalled();
    expect(h.posted).toHaveBeenCalledTimes(1);
    expect(editor(d).textContent).toBe("");
    expect(post(d).disabled).toBe(true);
    expect(toastText(d)).toBe(POSTED_TOAST);
    expect(d.querySelectorAll(".toasts-host")).toHaveLength(1);
    expect(s.getItem("oi:new-post:1")).toBeNull();
    unbind();
  });

  it("a rejection re-enables Post, shows the red Could not post note and keeps the draft", async () => {
    const d = loadPage("index");
    const s = memoryStorage();
    const h = handlers(vi.fn(() => Promise.reject(new Error("Please allow 10 seconds"))));
    const unbind = bindPost(d, "new-post/index", { handlers: h, storage: s, accountId: "1" });
    type(d, "Synthetic post");
    post(d).click();
    await flush();
    expect(post(d).disabled).toBe(false);
    const note = d.getElementById("oi-note")!;
    expect(note.textContent).toBe("Could not post: Please allow 10 seconds");
    expect(note.style.color).toBe("rgb(255, 69, 69)");
    expect(h.navigate).not.toHaveBeenCalled();
    expect(loadDraft(s, "1").text).toBe("Synthetic post");
    unbind();
  });

  it("All-Creators scope: Post gives the select-a-model note, sends nothing and stores no draft", () => {
    const d = loadPage("index");
    const s = memoryStorage();
    const unbind = bindPost(d, "new-post/index", { handlers: null, storage: s, accountId: null });
    type(d, "Synthetic post");
    expect(post(d).disabled).toBe(false);
    post(d).click();
    expect(d.getElementById("oi-note")?.textContent).toBe(SELECT_MODEL);
    expect(s.length).toBe(0);
    unbind();
  });

  it("All-Creators scope (handlers null): Post, Add media, schedule Next and the vault search are marked too", () => {
    const ctx = { handlers: null, storage: memoryStorage(), accountId: null };
    let d = loadPage("index");
    let unbind = bindPost(d, "new-post/index", ctx);
    // (The Scheduled events widget's "+" is the generator's Wired control, ofMirrorQueue's Add to queue.)
    expect(new Set(d.querySelectorAll("[data-oi-wired]:not([at-attr='add_event_widget'])"))).toEqual(new Set(composerWired(d)));
    unbind();
    d = loadPage("state-schedule");
    unbind = bindPost(d, "new-post/state-schedule", ctx);
    expect(d.querySelector(".vdatetime-popup__actions__button--confirm button")!.hasAttribute("data-oi-wired")).toBe(true);
    unbind();
    d = loadPage("state-vault");
    unbind = bindPost(d, "new-post/state-vault", ctx);
    expect(d.querySelector("input[name='media_vault_search']")!.hasAttribute("data-oi-wired")).toBe(true);
    unbind();
  });

  it("marks Post, Add media and its picker, Record video and voice, and the search box, and only those, as wired; a pick gets no Read-only note", () => {
    const d = loadPage("index");
    const unbind = bindPost(d, "new-post/index", { handlers: handlers(), storage: memoryStorage(), accountId: "1" });
    const unbindWrites = bindWrites(d, "new-post/index", null); // its change path, as OfMirrorFrame binds it
    const picker = d.querySelector("input[type=file]")!;
    expect(new Set(d.querySelectorAll("[data-oi-wired]:not([at-attr='add_event_widget'])"))).toEqual(new Set(composerWired(d)));
    picker.dispatchEvent(new Event("change", { bubbles: true }));
    expect(d.getElementById("oi-note")).toBeNull();
    unbindWrites();
    unbind();
  });

  it.each(["state-poll", "state-quiz", "state-format-text", "state-labels"])("%s: Add media in the toolbar under the panel is the upload button too", (page) => {
    const d = loadPage(page);
    const unbind = bindPost(d, `new-post/${page}`, { handlers: handlers(), storage: memoryStorage(), accountId: "1" });
    expect(d.querySelector("button[aria-label='Add media']")!.hasAttribute("data-oi-wired")).toBe(true);
    expect(d.querySelectorAll("input[type=file][accept='image/*,video/*,audio/*'][multiple]")).toHaveLength(1);
    unbind();
  });

  it("unbind removes the Add media picker and its click; a rebind of the same document leaves exactly one picker", () => {
    const d = loadPage("index");
    const addMedia = d.querySelector<HTMLButtonElement>("button[aria-label='Add media']")!;
    const pickers = () => d.querySelectorAll("input[type=file]");
    const opened = vi.spyOn(HTMLInputElement.prototype, "click").mockImplementation(() => {});
    try {
      let unbind = bindPost(d, "new-post/index", { handlers: handlers(), storage: memoryStorage(), accountId: "1" });
      expect(pickers()).toHaveLength(1);
      addMedia.click();
      expect(opened).toHaveBeenCalledTimes(1);
      expect(opened.mock.contexts[0]).toBe(pickers()[0]);

      unbind();
      expect(pickers()).toHaveLength(0);
      addMedia.click();
      expect(opened).toHaveBeenCalledTimes(1);
      expect(pickers()).toHaveLength(0);

      // useOfPost rebinds the same frame document when the Creator changes: one picker, one open per click.
      unbind = bindPost(d, "new-post/index", { handlers: handlers(), storage: memoryStorage(), accountId: "1" });
      unbind();
      unbind = bindPost(d, "new-post/index", { handlers: handlers(), storage: memoryStorage(), accountId: "2" });
      expect(pickers()).toHaveLength(1);
      addMedia.click();
      expect(opened).toHaveBeenCalledTimes(2);
      expect(opened.mock.contexts[1]).toBe(pickers()[0]);
      unbind();
    } finally {
      opened.mockRestore();
    }
  });
});

describe("schedule dialog (state-schedule capture)", () => {
  // Monday 12 October 2026, 10:00 local: 1 October is a Thursday, 1 November a Sunday.
  const NOW = new Date(2026, 9, 12, 10, 0);
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(NOW);
  });
  afterEach(() => vi.useRealTimers());

  const DAY = ".vdatetime-calendar__month__day";
  const days = (d: Document) => [...d.querySelectorAll<HTMLElement>(DAY)];
  const cell = (d: Document, n: number) => days(d).find((c) => c.textContent?.trim() === String(n))!;
  const shown = (d: Document) => d.querySelector(".vdatetime-calendar__current--month")!.textContent!.trim();
  const timeTab = (d: Document) => d.querySelector<HTMLElement>(".vdatetime-popup__tab.time")!;
  const next = (d: Document) => d.querySelector<HTMLButtonElement>(".vdatetime-popup__actions__button--confirm button")!;
  const saveLater = (d: Document) => d.querySelector<HTMLButtonElement>(".custom-datepicker-button-save-later")!;
  const setTime = (d: Document, text: string) => {
    timeTab(d).textContent = text;
    timeTab(d).dispatchEvent(new Event("input", { bubbles: true }));
  };
  const bindSchedule = (s = memoryStorage(), h: ReturnType<typeof handlers> | null = handlers()) => {
    const d = loadPage("state-schedule");
    const unbindPost = bindPost(d, "new-post/state-schedule", { handlers: h, storage: s, accountId: h ? "1" : null });
    const unbindWrites = bindWrites(d, "new-post/state-schedule", null); // the click fallback and change path, as OfMirrorFrame binds it
    const unbind = () => {
      unbindPost();
      unbindWrites();
    };
    return { d, s, h, unbind };
  };

  it("renderCalendar rebuilds the grid Sunday-first from a captured cell, past days disabled, the selected day marked", () => {
    const d = loadPage("state-schedule");
    renderCalendar(d, new Date(2026, 9, 1), new Date(2026, 9, 20), NOW);
    expect(shown(d)).toBe("October 2026");
    const all = days(d);
    expect(all).toHaveLength(4 + 31);
    expect(all.slice(0, 4).every((c) => c.textContent === "" && c.classList.contains(`${DAY.slice(1)}--disabled`))).toBe(true);
    for (let n = 1; n <= 11; n++) expect(cell(d, n).classList.contains("vdatetime-calendar__month__day--disabled")).toBe(true);
    for (let n = 12; n <= 31; n++) expect(cell(d, n).classList.contains("vdatetime-calendar__month__day--disabled")).toBe(false);
    expect(d.querySelectorAll(".vdatetime-calendar__month__day--selected")).toHaveLength(1);
    expect(cell(d, 20).classList.contains("vdatetime-calendar__month__day--selected")).toBe(true);
    // the cells are clones of OF's own: its span nesting is kept
    expect(cell(d, 20).querySelector("span > span")?.textContent).toBe("20");

    renderCalendar(d, new Date(2026, 10, 1), new Date(2026, 9, 20), NOW);
    expect(shown(d)).toBe("November 2026");
    expect(days(d)).toHaveLength(30);
    expect(d.querySelectorAll(".vdatetime-calendar__month__day--disabled")).toHaveLength(0);
    expect(d.querySelectorAll(".vdatetime-calendar__month__day--selected")).toHaveLength(0);
  });

  it("opens on the current month with today selected and the time tab at now plus one hour", () => {
    const { d, unbind } = bindSchedule();
    expect(shown(d)).toBe("October 2026");
    expect(cell(d, 12).classList.contains("vdatetime-calendar__month__day--selected")).toBe(true);
    expect(cell(d, 11).classList.contains("vdatetime-calendar__month__day--disabled")).toBe(true);
    expect(timeTab(d).getAttribute("contenteditable")).toBe("true");
    expect(timeTab(d).textContent).toBe("11:00 AM");
    expect(d.querySelector("input.vdatetime-input")?.outerHTML).toBe('<input type="text" class="vdatetime-input">');
    unbind();
  });

  it("opens on the month and time of the draft's schedule", () => {
    const s = memoryStorage();
    saveDraft(s, "1", { ...empty(), text: "Synthetic post", posted_at: localIso(new Date(2026, 10, 3, 18, 30)) });
    const { d, unbind } = bindSchedule(s);
    expect(shown(d)).toBe("November 2026");
    expect(cell(d, 3).classList.contains("vdatetime-calendar__month__day--selected")).toBe(true);
    expect(timeTab(d).textContent).toBe("6:30 PM");
    unbind();
  });

  it("the previous arrow on the current month stays on it; the next arrow shows the following month", () => {
    const { d, unbind } = bindSchedule();
    d.querySelector<HTMLElement>(".vdatetime-calendar__navigation--previous")!.click();
    expect(shown(d)).toBe("October 2026");
    d.querySelector<HTMLElement>(".vdatetime-calendar__navigation--next")!.click();
    expect(shown(d)).toBe("November 2026");
    expect(days(d)).toHaveLength(30);
    d.querySelector<HTMLElement>(".vdatetime-calendar__navigation--previous")!.click();
    expect(shown(d)).toBe("October 2026");
    unbind();
  });

  it("clicking an enabled day selects it and updates the header date, year and date tab; a disabled day does nothing", () => {
    const { d, unbind } = bindSchedule();
    cell(d, 11).click();
    expect(cell(d, 12).classList.contains("vdatetime-calendar__month__day--selected")).toBe(true);
    cell(d, 13).click();
    expect(cell(d, 13).classList.contains("vdatetime-calendar__month__day--selected")).toBe(true);
    expect(d.querySelectorAll(".vdatetime-calendar__month__day--selected")).toHaveLength(1);
    expect(d.querySelector(".vdatetime-popup__date")!.textContent).toBe("13 October");
    expect(d.querySelector(".vdatetime-popup__year")!.textContent).toBe("2026");
    expect(d.querySelector(".vdatetime-popup__tab.date")!.textContent).toBe("Oct 13, Tu");
    unbind();
  });

  it("tomorrow, 6:30 pm and Next saves local ISO of tomorrow 18:30 and returns to the composer", () => {
    const { d, s, h, unbind } = bindSchedule();
    cell(d, 13).click();
    setTime(d, "6:30 pm");
    expect(collectSchedule(d, NOW)).toBe(localIso(new Date(2026, 9, 13, 18, 30)));
    next(d).click();
    expect(loadDraft(s, "1").posted_at).toBe(localIso(new Date(2026, 9, 13, 18, 30)));
    expect(h!.navigate).toHaveBeenCalledWith("/of-manager/new-post");
    unbind();
  });

  it("the selected day carries across months: 13 Oct, then November, then Next still saves 13 Oct", () => {
    const { d, s, unbind } = bindSchedule();
    cell(d, 13).click();
    d.querySelector<HTMLElement>(".vdatetime-calendar__navigation--next")!.click();
    expect(shown(d)).toBe("November 2026");
    expect(d.querySelector(".vdatetime-popup__date")!.textContent).toBe("13 October");
    setTime(d, "6:30 pm");
    next(d).click();
    expect(loadDraft(s, "1").posted_at).toBe(localIso(new Date(2026, 9, 13, 18, 30)));
    d.querySelector<HTMLElement>(".vdatetime-calendar__navigation--previous")!.click();
    expect(cell(d, 13).classList.contains("vdatetime-calendar__month__day--selected")).toBe(true);
    unbind();
  });

  it("24h time is read too", () => {
    const { d, unbind } = bindSchedule();
    cell(d, 13).click();
    setTime(d, "18:30");
    expect(collectSchedule(d, NOW)).toBe(localIso(new Date(2026, 9, 13, 18, 30)));
    unbind();
  });

  it("a time one minute ago, or an unreadable time, gives the red note and saves nothing", () => {
    const { d, s, h, unbind } = bindSchedule();
    for (const t of ["9:59 am", "abc"]) {
      setTime(d, t);
      next(d).click();
      const n = d.getElementById("oi-note")!;
      expect(n.textContent).toBe(t === "abc" ? "Enter a valid time" : "Pick a time at least a minute from now");
      expect(n.style.color).toBe("rgb(255, 69, 69)");
    }
    expect(s.getItem("oi:new-post:1")).toBeNull();
    expect(h!.navigate).not.toHaveBeenCalled();
    unbind();
  });

  it("Save for Later stores save_for_later in place of a schedule and returns to the composer; Next drops it again", () => {
    const s = memoryStorage();
    saveDraft(s, "1", { ...empty(), text: "Synthetic post", posted_at: localIso(new Date(2026, 9, 13, 18, 30)) });
    const { d, h, unbind } = bindSchedule(s);
    saveLater(d).click();
    expect(loadDraft(s, "1")).toEqual({ ...empty(), text: "Synthetic post", save_for_later: true });
    expect(h!.navigate).toHaveBeenCalledWith("/of-manager/new-post");
    expect(h!.createPost).not.toHaveBeenCalled();
    expect(d.getElementById("oi-note")).toBeNull();
    cell(d, 13).click();
    setTime(d, "6:30 pm");
    next(d).click();
    expect(loadDraft(s, "1").save_for_later).toBeUndefined();
    expect(loadDraft(s, "1").posted_at).toBe(localIso(new Date(2026, 9, 13, 18, 30)));
    unbind();
  });

  it("All-Creators scope: Save for Later gives the select-a-model note and stores nothing", () => {
    const { d, s, unbind } = bindSchedule(memoryStorage(), null);
    saveLater(d).click();
    expect(d.getElementById("oi-note")?.textContent).toBe(SELECT_MODEL);
    expect(s.length).toBe(0);
    unbind();
  });

  it("All-Creators scope: Next gives the select-a-model note and stores nothing", () => {
    const { d, s, unbind } = bindSchedule(memoryStorage(), null);
    cell(d, 13).click();
    setTime(d, "6:30 pm");
    next(d).click();
    expect(d.getElementById("oi-note")?.textContent).toBe(SELECT_MODEL);
    expect(s.length).toBe(0);
    unbind();
  });

  it("Next and Save for Later are marked wired; Cancel and the backdrop keep their captured links", () => {
    const { d, unbind } = bindSchedule();
    expect(next(d).hasAttribute("data-oi-wired")).toBe(true);
    expect(saveLater(d).hasAttribute("data-oi-wired")).toBe(true);
    expect(d.querySelector(".vdatetime-popup__actions__button--cancel a")?.getAttribute("href")).toBe("/of-manager/new-post");
    expect(d.querySelector(".vdatetime-overlay")?.getAttribute("href")).toBe("/of-manager/new-post");
    unbind();
  });
});

describe("a scheduled draft on the composer", () => {
  const NOW = new Date(2026, 9, 12, 10, 0);
  const AT = localIso(new Date(2026, 9, 13, 18, 30));
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(NOW);
  });
  afterEach(() => vi.useRealTimers());

  it("Post sends posted_at with the text and stays, OF's toast naming the moment", async () => {
    const d = loadPage("index");
    const s = memoryStorage();
    saveDraft(s, "1", { ...empty(), text: "Synthetic post", posted_at: AT });
    const h = handlers();
    const unbind = bindPost(d, "new-post/index", { handlers: h, storage: s, accountId: "1" });
    post(d).click();
    expect(h.createPost).toHaveBeenCalledWith({ text: "Synthetic post", media_files: [], price: 0, posted_at: AT });
    await flush();
    expect(h.navigate).not.toHaveBeenCalled();
    expect(toastText(d)).toBe("Your post is scheduled for Tue, Oct 13, 6:30 PM");
    expect(s.getItem("oi:new-post:1")).toBeNull();
    unbind();
  });

  it("a stale schedule makes Post show the note and send nothing", () => {
    const d = loadPage("index");
    const s = memoryStorage();
    saveDraft(s, "1", { ...empty(), text: "Synthetic post", posted_at: AT });
    const h = handlers();
    const unbind = bindPost(d, "new-post/index", { handlers: h, storage: s, accountId: "1" });
    vi.setSystemTime(new Date(2026, 9, 13, 18, 30));
    post(d).click();
    expect(d.getElementById("oi-note")?.textContent).toBe("Pick a time at least a minute from now");
    expect(h.createPost).toHaveBeenCalledTimes(0);
    expect(loadDraft(s, "1").posted_at).toBe(AT);
    unbind();
  });

  it("shows a persistent grey summary under the editor, whose Clear removes the schedule", () => {
    const d = loadPage("index");
    const s = memoryStorage();
    saveDraft(s, "1", { ...empty(), text: "Synthetic post", posted_at: AT });
    const unbind = bindPost(d, "new-post/index", { handlers: handlers(), storage: s, accountId: "1" });
    const summary = d.getElementById("oi-post-summary")!;
    expect(summary.textContent).toBe("Scheduled for Tue, Oct 13, 6:30 PM · Clear");
    expect(summary.style.color).toBe("rgb(138, 150, 163)");
    expect(editor(d).closest(".g-input__wrapper")!.nextElementSibling).toBe(summary);
    const clear = [...summary.querySelectorAll<HTMLElement>("a, button")].find((e) => e.textContent === "Clear")!;
    clear.click();
    expect(d.getElementById("oi-post-summary")).toBeNull();
    expect(loadDraft(s, "1").posted_at).toBeUndefined();
    expect(loadDraft(s, "1").text).toBe("Synthetic post");
    unbind();
  });

  it("no schedule, no summary", () => {
    const d = loadPage("index");
    const unbind = bindPost(d, "new-post/index", { handlers: handlers(), storage: memoryStorage(), accountId: "1" });
    expect(d.getElementById("oi-post-summary")).toBeNull();
    unbind();
  });
});

/** Taggable creators: OF's own GET /posts/tagged-friend-users response, scrubbed (the first two). */
const TAGS: TaggedFriendUser[] = (fixture("new-post-tags") as { items: TaggedFriendUser[] }).items.slice(0, 2);

describe("tag dialog (state-tag-people capture)", () => {
  const ROW = "label.b-rows-lists__item";
  const shownRows = (d: Document) => [...d.querySelectorAll<HTMLElement>(ROW)].filter((r) => r.style.display !== "none");
  const examples = (d: Document) => [...d.querySelectorAll<HTMLElement>(`${ROW}:not([data-oi-user])`)];
  const row = (d: Document, id: number) => d.querySelector<HTMLElement>(`${ROW}[data-oi-user='${id}']`)!;
  const box = (r: Element) => r.querySelector<HTMLInputElement>("input[type='checkbox']")!;
  /** bindPost and bindWrites (its change path), both on the tag dialog in `h`'s scope, as OfMirrorFrame binds them. */
  const bindTags = (s: Storage, h: ReturnType<typeof handlers> | null, tagItems?: TaggedFriendUser[]) => {
    const d = loadPage("state-tag-people");
    const unbindPost = bindPost(d, "new-post/state-tag-people", { handlers: h, storage: s, accountId: h ? "1" : null, tagItems });
    const writes = h && { saveProfile: vi.fn(), setReplyOnSubscribe: vi.fn(), submit: vi.fn(), navigate: vi.fn() };
    const unbindWrites = bindWrites(d, "new-post/state-tag-people", writes);
    const unbind = () => {
      unbindWrites();
      unbindPost();
    };
    return { d, unbind };
  };

  it("applyTagRows hides the examples and renders one wired row per item, checked when already picked", () => {
    const d = loadPage("state-tag-people");
    expect(examples(d)).toHaveLength(50);
    applyTagRows(d, TAGS, [2002]);
    expect(examples(d).every((r) => r.style.display === "none")).toBe(true);
    const rows = shownRows(d);
    expect(rows.map((r) => r.getAttribute("data-oi-user"))).toEqual(["2001", "2002"]);
    expect(rows.every((r) => r.hasAttribute("data-oi-wired"))).toBe(true);
    expect(row(d, 2001).querySelector(".b-rows-lists__item__name")!.textContent!.trim()).toBe("Synth Creator 1");
    expect(row(d, 2001).querySelector(".b-rows-lists__item__subline")!.textContent!.trim()).toBe("@synthcreator1");
    expect(row(d, 2002).querySelector(".b-rows-lists__item__name")!.textContent!.trim()).toBe("Synth Creator 2");
    expect(box(row(d, 2001)).checked).toBe(false);
    expect(box(row(d, 2002)).checked).toBe(true);
  });

  it("the row id is user.id, else the top-level id; the name falls back to the username", () => {
    const d = loadPage("state-tag-people");
    applyTagRows(d, [{ id: 903, user: { id: 913, username: "gammathree" } }, { id: 904 }], []);
    expect(shownRows(d).map((r) => r.getAttribute("data-oi-user"))).toEqual(["913", "904"]);
    expect(row(d, 913).querySelector(".b-rows-lists__item__name")!.textContent!.trim()).toBe("gammathree");
  });

  it("a row decodes OF's escaped name and shows the real avatar through the image proxy, else OF's initials", () => {
    const d = loadPage("state-tag-people");
    const img = (u: string) => `/img?u=${encodeURIComponent(u)}`;
    applyTagRows(d, [
      { id: 951, name: "Synth &amp; Co", user: { id: 961, name: "Synth &amp; Co", username: "synthco", avatar: "https://cdn.example/a.jpg", avatarThumbs: { c50: "https://cdn.example/a50.jpg", c144: "https://cdn.example/a144.jpg" } } },
      { id: 952, user: { id: 962, name: "Beta &lt;3", username: "betathree", avatar: null } },
    ], [], img);
    expect(row(d, 961).querySelector(".b-rows-lists__item__name")!.textContent!.trim()).toBe("Synth & Co");
    const pic = row(d, 961).querySelector<HTMLImageElement>(".b-rows-lists__item__icon .g-avatar img")!;
    expect(pic.getAttribute("src")).toBe(img("https://cdn.example/a144.jpg"));
    expect(row(d, 961).querySelectorAll(".b-rows-lists__item__icon .g-avatar")).toHaveLength(1);
    expect(row(d, 962).querySelector(".b-rows-lists__item__name")!.textContent!.trim()).toBe("Beta <3");
    const ph = row(d, 962).querySelector(".b-rows-lists__item__icon .g-avatar__placeholder.m-text-avatar")!;
    expect(ph.textContent!.trim()).toBe("B<"); // OF's initials: two words, their first letters
    expect(row(d, 962).querySelector(".b-rows-lists__item__icon img")).toBeNull();
  });

  it("an empty list hides all rows", () => {
    const d = loadPage("state-tag-people");
    applyTagRows(d, [], []);
    expect(shownRows(d)).toHaveLength(0);
  });

  it("checking a row adds its id in operator order, without duplicates; unchecking removes it", () => {
    const s = memoryStorage();
    saveDraft(s, "1", { ...empty(), text: "Synthetic post" });
    const { d, unbind } = bindTags(s, handlers(), TAGS);
    box(row(d, 2002)).click();
    box(row(d, 2001)).click();
    expect(loadDraft(s, "1").tagged_users).toEqual([2002, 2001]);
    expect(box(row(d, 2002)).checked).toBe(true);
    box(row(d, 2002)).click();
    expect(loadDraft(s, "1").tagged_users).toEqual([2001]);
    box(row(d, 2002)).click();
    expect(loadDraft(s, "1").tagged_users).toEqual([2001, 2002]);
    expect(loadDraft(s, "1").text).toBe("Synthetic post");
    unbind();
  });

  it("a draft's Co-tag renders checked when the dialog opens", () => {
    const s = memoryStorage();
    saveDraft(s, "1", { ...empty(), tagged_users: [2001] });
    const { d, unbind } = bindTags(s, handlers(), TAGS);
    expect(box(row(d, 2001)).checked).toBe(true);
    expect(box(row(d, 2002)).checked).toBe(false);
    unbind();
  });

  it.each([
    ["no tagItems (loading or failed)", true],
    ["All-Creators scope", false],
  ])("%s: no rows at all, never the captured examples, and nothing is kept", (_, single) => {
    const s = memoryStorage();
    const h = single ? handlers() : null;
    const { d, unbind } = bindTags(s, h);
    expect(shownRows(d)).toHaveLength(0);
    expect(s.getItem("oi:new-post:1")).toBeNull();
    unbind();
    expect(shownRows(d)).toHaveLength(50); // unbind puts the capture back
  });

  it("unbind puts the examples back (a scope change rebinds without the Relay rows)", () => {
    const { d, unbind } = bindTags(memoryStorage(), handlers(), TAGS);
    unbind();
    expect(d.querySelectorAll("[data-oi-user]")).toHaveLength(0);
    expect(shownRows(d)).toHaveLength(50);
  });
});

describe("vault dialog (state-vault capture)", () => {
  const PAGE = "new-post/state-vault";
  // Noon UTC keeps the local day; 62 carries the Relay's AI overlay (mirror path), the others none.
  const MEDIA = [61, 62, 63].map((id) => ({
    id,
    type: "photo",
    createdAt: `2026-10-${80 - id}T12:00:00Z`,
    files: { thumb: { url: `https://cdn.example/${id}.jpg` } },
    ...(id === 62 ? { _ai: { description: "Synthetic beach", tags: ["sunset", "sand"] } } : {}),
  }));
  const thumb = (id: number) => `/img?u=https://cdn.example/${id}.jpg&account_id=1`;
  const tile = (d: Document, id: number) => d.querySelector<HTMLElement>(`[data-oi-media='${id}']`)!;
  const exampleTile = (d: Document) => d.querySelector<HTMLElement>(".b-photos__item.m-checkbox-control:not([data-oi-media])")!;
  const marked = (d: Document) => [...d.querySelectorAll(".b-photos__item.selected")].map((t) => t.getAttribute("data-oi-media"));
  /** The dialog with the Creator's 3 media applied (as useOfData does), then bound. */
  const bindVault = (s: Storage, h: ReturnType<typeof handlers> | null) => {
    const d = loadPage("state-vault");
    if (h) applyData(d, PAGE, { vaultMedia: MEDIA, picked: [] }, (u) => `/img?u=${u}&account_id=1`);
    return { d, unbind: bindPost(d, PAGE, { handlers: h, storage: s, accountId: h ? "1" : null }) };
  };

  it("a tile click picks it and a second click unpicks it; media_files and thumbs follow the clicks in order", () => {
    const s = memoryStorage();
    saveDraft(s, "1", { ...empty(), text: "Synthetic post" });
    const h = handlers();
    const { d, unbind } = bindVault(s, h);
    tile(d, 63).click();
    tile(d, 61).click();
    expect(marked(d)).toEqual(["61", "63"]);
    expect(loadDraft(s, "1")).toEqual({ ...empty(), text: "Synthetic post", media_files: [63, 61], thumbs: [thumb(63), thumb(61)] });
    tile(d, 63).click();
    expect(marked(d)).toEqual(["61"]);
    expect(loadDraft(s, "1")).toEqual({ ...empty(), text: "Synthetic post", media_files: [61], thumbs: [thumb(61)] });
    tile(d, 63).click();
    expect(loadDraft(s, "1")).toEqual({ ...empty(), text: "Synthetic post", media_files: [61, 63], thumbs: [thumb(61), thumb(63)] });
    expect(h.createPost).not.toHaveBeenCalled();
    unbind();
  });

  it("its folders are the Creator's (each opens the dialog on that folder), or none: never the captured ones", () => {
    const d = loadPage("state-vault");
    const folders = () => [...d.querySelectorAll<HTMLElement>(".b-rows-lists__item")].filter((r) => r.style.display !== "none");
    const names = () => folders().map((r) => r.querySelector(".b-rows-lists__item__name")!.textContent!.trim());
    expect(names()).toContain("List 36"); // the capture
    applyData(d, PAGE, { vaultLists: [{ id: 7, name: "Beach set", photosCount: 2 } as never], vaultAll: { photosCount: 5 } as never, vaultMedia: [], list: "7" });
    expect(names()).toEqual(["All media", "Beach set"]);
    const links = folders().map((r) => r.querySelector("a")!);
    expect(links.map((a) => a.getAttribute("href"))).toEqual([`/of-manager/${PAGE}`, `/of-manager/${PAGE}?list=7`]);
    expect(links.map((a) => a.classList.contains("m-current"))).toEqual([false, true]);
    expect(d.querySelector(".l-main-content.m-r-side .g-page-title > span")!.textContent).toBe("Beach set");
    applyData(d, PAGE, { vaultLists: [], vaultAll: {}, vaultMedia: [] });
    expect(names()).toEqual(["All media"]);
    expect(folders()[0].querySelector(".b-content-inside-thumbs")!.textContent!.trim()).toBe("empty");
    const hidden = (el: Element | null): boolean => !!el && ((el as HTMLElement).style?.display === "none" || hidden(el.parentElement));
    expect([...d.querySelectorAll(".b-photos__item")].every(hidden)).toBe(true);
  });

  it("its type tabs show the view and open the dialog on another type, the folder kept; All-Creators: the note", () => {
    const d = loadPage("state-vault");
    const tabs = () => [...d.querySelectorAll<HTMLButtonElement>(".modal.show .b-tabs__nav__link")];
    const h = handlers();
    let unbind = bindPost(d, PAGE, { handlers: h, storage: memoryStorage(), accountId: "1", vaultView: { list: "7", type: "video" } });
    expect(tabs().map((t) => t.classList.contains("m-current"))).toEqual([false, false, false, true, false]);
    tabs()[1].click();
    expect(h.navigate).toHaveBeenCalledWith(`/of-manager/${PAGE}?list=7&type=photo`);
    tabs()[3].click(); // the current one
    tabs()[0].click();
    expect(h.navigate.mock.calls).toEqual([[`/of-manager/${PAGE}?list=7&type=photo`], [`/of-manager/${PAGE}?list=7`]]);
    unbind();
    unbind = bindPost(d, PAGE, { handlers: null, storage: null, accountId: null });
    tabs()[2].click();
    expect(d.getElementById("oi-note")?.textContent).toBe(SELECT_MODEL);
    unbind();
  });

  it("a click decides from the draft: a tile marked but not in the draft is picked and stays marked", () => {
    const s = memoryStorage();
    const { d, unbind } = bindVault(s, handlers());
    tile(d, 61).classList.add("selected"); // the mark disagrees with the (empty) draft
    tile(d, 61).click();
    expect(loadDraft(s, "1").media_files).toEqual([61]);
    expect(marked(d)).toEqual(["61"]);
    expect(tile(d, 61).querySelector(".checkbox-item")!.classList.contains("selected")).toBe(true);
    unbind();
  });

  it("search shows only the tiles whose date label or AI description and tags hold the trimmed, case-folded query", () => {
    const s = memoryStorage();
    saveDraft(s, "1", { ...empty(), text: "Synthetic post" });
    const { d, unbind } = bindVault(s, handlers());
    tile(d, 62).click();
    const before = loadDraft(s, "1");
    const box = d.querySelector<HTMLInputElement>("input[name='media_vault_search']")!;
    const search = (q: string) => {
      box.value = q;
      box.dispatchEvent(new Event("input", { bubbles: true }));
      return [61, 62, 63].filter((id) => tile(d, id).style.display !== "none");
    };
    expect(search("beach")).toEqual([62]);
    expect(search("  BEACH ")).toEqual([62]);
    expect(search("Sunset")).toEqual([62]);
    expect(search("oct 17")).toEqual([63]);
    expect(search("nothing like it")).toEqual([]);
    expect(search("")).toEqual([61, 62, 63]);
    expect(search("beach")).toEqual([62]);
    expect(search("   ")).toEqual([61, 62, 63]);
    expect(loadDraft(s, "1")).toEqual(before);
    expect(marked(d)).toEqual(["62"]);
    expect(box.hasAttribute("data-oi-wired")).toBe(true);
    unbind();
    expect(search("beach")).toEqual([61, 62, 63]);
  });

  it("Search media opens OF's search form; Back closes it and shows all tiles; a submit stays on the page", () => {
    const s = memoryStorage();
    const { d, unbind } = bindVault(s, handlers());
    const open = d.querySelector<HTMLElement>("button[aria-label='Search media']")!;
    const header = open.closest(".g-page__header")!;
    const box = d.querySelector<HTMLInputElement>("input[name='media_vault_search']")!;
    expect(header.classList.contains("m-search-form-visible")).toBe(false);
    open.click();
    expect(header.classList.contains("m-search-form-visible")).toBe(true);
    expect(open.hasAttribute("data-oi-wired")).toBe(true);
    box.value = "beach";
    box.dispatchEvent(new Event("input", { bubbles: true }));
    const submit = new Event("submit", { bubbles: true, cancelable: true });
    box.form!.dispatchEvent(submit);
    expect(submit.defaultPrevented).toBe(true);
    expect([61, 62, 63].filter((id) => tile(d, id).style.display !== "none")).toEqual([62]);
    d.querySelector<HTMLElement>("[at-attr='close_search']")!.click();
    expect(header.classList.contains("m-search-form-visible")).toBe(false);
    expect(box.value).toBe("");
    expect([61, 62, 63].filter((id) => tile(d, id).style.display !== "none")).toEqual([61, 62, 63]);
    unbind();
  });

  it("an example tile gives SELECT_MODEL and changes neither the tile nor the draft", () => {
    const s = memoryStorage();
    saveDraft(s, "1", { ...empty(), text: "Synthetic post" });
    const d = loadPage("state-vault");
    const h = handlers();
    const unbind = bindPost(d, PAGE, { handlers: h, storage: s, accountId: "1" });
    exampleTile(d).click();
    expect(d.getElementById("oi-note")?.textContent).toBe(SELECT_MODEL);
    expect(marked(d)).toEqual([]);
    expect(loadDraft(s, "1")).toEqual({ ...empty(), text: "Synthetic post" });
    expect(exampleTile(d).hasAttribute("data-oi-wired")).toBe(false);
    expect(h.createPost).not.toHaveBeenCalled();
    unbind();
  });

  it("All-Creators scope: a tile click gives SELECT_MODEL and stores nothing", () => {
    const s = memoryStorage();
    const { d, unbind } = bindVault(s, null);
    exampleTile(d).click();
    expect(d.getElementById("oi-note")?.textContent).toBe(SELECT_MODEL);
    expect(marked(d)).toEqual([]);
    expect(s.length).toBe(0);
    unbind();
  });

  it("unbind stops picking", () => {
    const s = memoryStorage();
    const { d, unbind } = bindVault(s, handlers());
    unbind();
    tile(d, 61).click();
    expect(marked(d)).toEqual([]);
    expect(loadDraft(s, "1").media_files).toEqual([]);
  });

  const ITEMS = [
    { id: 61, type: "photo", files: { full: { url: "https://cdn.example/61-full.jpg" } } },
    { id: 62, type: "video", files: { full: { url: "https://cdn.example/62.mp4" } } },
  ] as VaultMedia[];
  const storyBtn = (d: Document) => [...d.querySelectorAll<HTMLButtonElement>(".modal.show .modal-footer button")].find((b) => b.textContent?.trim() === "Add to story")!;
  const bindStoryVault = (draft: Partial<PostDraft>, h: ReturnType<typeof handlers> | null = handlers()) => {
    const s = memoryStorage();
    if (h) saveDraft(s, "1", { ...empty(), ...draft });
    const d = loadPage("state-vault");
    return { d, s, h, unbind: bindPost(d, PAGE, { handlers: h, storage: s, accountId: h ? "1" : null, vaultItems: h ? ITEMS : undefined }) };
  };

  it("vaultStoryBody: a photo goes by its full picture, a video (or an unknown item) by its vault id", () => {
    expect(vaultStoryBody(61, ITEMS)).toEqual({ media_url: "https://cdn.example/61-full.jpg" });
    expect(vaultStoryBody(62, ITEMS)).toEqual({ media_files: [62] });
    expect(vaultStoryBody(63, ITEMS)).toEqual({ media_files: [63] });
    expect(vaultStoryBody(61, undefined)).toEqual({ media_files: [61] });
  });

  it("Add to story sits before Close, wired, and publishes the one picked vault item, then says so", async () => {
    const { d, s, h, unbind } = bindStoryVault({ text: "Synthetic post", media_files: [61, { processId: "p1" }], thumbs: ["a", "b"] });
    const btn = storyBtn(d);
    expect(btn.hasAttribute("data-oi-wired")).toBe(true);
    expect(btn.nextElementSibling?.textContent?.trim()).toBe("Close");
    btn.click();
    expect(h!.addVaultStory).toHaveBeenCalledTimes(1);
    expect(h!.addVaultStory).toHaveBeenCalledWith({ media_url: "https://cdn.example/61-full.jpg" });
    expect(btn.disabled).toBe(true);
    await flush();
    expect(btn.disabled).toBe(false);
    expect(d.getElementById("oi-note")?.textContent).toBe("Added to story");
    expect(loadDraft(s, "1").media_files).toEqual([61, { processId: "p1" }]);
    expect(h!.createPost).not.toHaveBeenCalled();
    unbind();
    expect(storyBtn(d)).toBeUndefined();
  });

  it("a picked video goes by its vault id; a failure shows the red note", async () => {
    const h = handlers();
    h.addVaultStory.mockImplementationOnce(() => Promise.reject(new Error("synthetic failure")));
    const { d, unbind } = bindStoryVault({ media_files: [62], thumbs: ["a"] }, h);
    storyBtn(d).click();
    expect(h.addVaultStory).toHaveBeenCalledWith({ media_files: [62] });
    await flush();
    expect(d.getElementById("oi-note")?.textContent).toBe("Could not add: synthetic failure");
    expect(storyBtn(d).disabled).toBe(false);
    unbind();
  });

  it.each([[[]], [[61, 62]]])("picks %j: the red pick-one note and nothing is sent", (media_files) => {
    const { d, h, unbind } = bindStoryVault({ media_files, thumbs: media_files.map(() => "") });
    storyBtn(d).click();
    expect(d.getElementById("oi-note")?.textContent).toBe("Pick one vault item for the story");
    expect(h!.addVaultStory).not.toHaveBeenCalled();
    unbind();
  });

  it("All-Creators scope: Add to story gives SELECT_MODEL and sends nothing", () => {
    const { d, s, unbind } = bindStoryVault({}, null);
    storyBtn(d).click();
    expect(d.getElementById("oi-note")?.textContent).toBe(SELECT_MODEL);
    expect(s.length).toBe(0);
    unbind();
  });
});

describe("picked vault media on the composer (index capture)", () => {
  const THUMBS = ["/img?u=https://cdn.example/62.jpg&account_id=1", "/img?u=https://cdn.example/61.jpg&account_id=1"];
  const rows = (d: Document) => [...d.querySelectorAll("#oi-post-thumbs")];
  const srcs = (d: Document) => [...d.querySelectorAll("#oi-post-thumbs img.b-photos__item__img")].map((i) => i.getAttribute("src"));

  it("a draft with 2 picks gives one row of 2 pictures in click order, directly before the actions bar; a second load replaces it", () => {
    const d = loadPage("index");
    const s = memoryStorage();
    saveDraft(s, "1", { ...empty(), text: "Synthetic post", media_files: [62, 61], thumbs: THUMBS });
    const ctx = { handlers: handlers(), storage: s, accountId: "1" };
    bindPost(d, "new-post/index", ctx)();
    expect(rows(d)).toHaveLength(1);
    expect(rows(d)[0].nextElementSibling?.classList.contains("b-make-post__actions")).toBe(true);
    expect(srcs(d)).toEqual(THUMBS);
    expect(editor(d).textContent).toBe("Synthetic post");
    const unbind = bindPost(d, "new-post/index", ctx);
    expect(rows(d)).toHaveLength(1);
    expect(srcs(d)).toEqual(THUMBS);
    unbind();
  });

  it("an empty draft adds no row, and a load after the draft is cleared removes it", () => {
    const d = loadPage("index");
    const s = memoryStorage();
    bindPost(d, "new-post/index", { handlers: handlers(), storage: s, accountId: "1" })();
    expect(rows(d)).toHaveLength(0);
    saveDraft(s, "1", { ...empty(), text: "Synthetic post", media_files: [62, 61], thumbs: THUMBS });
    bindPost(d, "new-post/index", { handlers: handlers(), storage: s, accountId: "1" })();
    clearDraft(s, "1");
    const unbind = bindPost(d, "new-post/index", { handlers: handlers(), storage: s, accountId: "1" });
    expect(rows(d)).toHaveLength(0);
    unbind();
  });

  it("Post sends the picked ids with the text, then clears the draft", async () => {
    const d = loadPage("index");
    const s = memoryStorage();
    saveDraft(s, "1", { ...empty(), text: "Synthetic post", media_files: [62, 61], thumbs: THUMBS });
    const h = handlers();
    const unbind = bindPost(d, "new-post/index", { handlers: h, storage: s, accountId: "1" });
    post(d).click();
    expect(h.createPost).toHaveBeenCalledTimes(1);
    expect(h.createPost).toHaveBeenCalledWith({ text: "Synthetic post", media_files: [62, 61], price: 0 });
    await flush();
    expect(loadDraft(s, "1")).toEqual(empty());
    unbind();
  });

  it.each(["new-post/index", "home/index"])("%s: each thumb's X drops that file from the draft and the row; the last one's removes the row and disables Post (U5)", (page) => {
    document.documentElement.innerHTML = readFileSync(resolve(__dirname, `../public/of-mirror/pages/${page}.html`), "utf8");
    const d = document;
    const s = memoryStorage();
    const id = page.startsWith("home/") ? "home:1" : "1";
    saveDraft(s, id, { ...empty(), media_files: [62, { processId: "p1" }], thumbs: THUMBS });
    const unbind = bindPost(d, page, { handlers: handlers(), storage: s, accountId: "1", draftId: page.startsWith("home/") ? id : undefined });
    const xs = () => [...d.querySelectorAll<HTMLButtonElement>("#oi-post-thumbs button[aria-label='Delete']")];
    expect(xs()).toHaveLength(2);
    expect(xs()[0].querySelector("use")!.getAttribute("href")).toBe("#icon-close");
    xs()[1].click();
    expect(loadDraft(s, id)).toEqual({ ...empty(), media_files: [62], thumbs: [THUMBS[0]] });
    expect(srcs(d)).toEqual([THUMBS[0]]);
    expect(post(d).disabled).toBe(false);
    xs()[0].click();
    expect(loadDraft(s, id)).toEqual(empty());
    expect(rows(d)).toHaveLength(0);
    expect(post(d).disabled).toBe(true);
    expect(d.getElementById("oi-note")).toBeNull();
    unbind();
  });
});

describe("Co-tags on the composer", () => {
  const NOW = new Date(2026, 9, 12, 10, 0);
  const AT = localIso(new Date(2026, 9, 13, 18, 30));
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(NOW);
  });
  afterEach(() => vi.useRealTimers());

  it("the summary names the schedule and the Co-tags; Clear empties both", () => {
    const d = loadPage("index");
    const s = memoryStorage();
    saveDraft(s, "1", { ...empty(), text: "Synthetic post", posted_at: AT, tagged_users: [2001] });
    const unbind = bindPost(d, "new-post/index", { handlers: handlers(), storage: s, accountId: "1", tagItems: TAGS });
    const summary = d.getElementById("oi-post-summary")!;
    expect(summary.textContent).toContain("Scheduled for");
    expect(summary.textContent).toContain("Synth Creator 1");
    expect(summary.textContent).toBe("Scheduled for Tue, Oct 13, 6:30 PM · Tagged: Synth Creator 1 · Clear");
    summary.querySelector<HTMLElement>("[data-oi-clear]")!.click();
    expect(d.getElementById("oi-post-summary")).toBeNull();
    expect(loadDraft(s, "1").posted_at).toBeUndefined();
    expect(loadDraft(s, "1").tagged_users).toEqual([]);
    unbind();
  });

  it("Co-tags alone show the summary; checking a row in the dialog updates it", () => {
    const s = memoryStorage();
    const d = loadPage("state-tag-people");
    const unbind = bindPost(d, "new-post/state-tag-people", { handlers: handlers(), storage: s, accountId: "1", tagItems: TAGS });
    expect(d.getElementById("oi-post-summary")).toBeNull();
    d.querySelector<HTMLInputElement>("[data-oi-user='2001'] input")!.click();
    d.querySelector<HTMLInputElement>("[data-oi-user='2002'] input")!.click();
    expect(d.getElementById("oi-post-summary")!.textContent).toBe("Tagged: Synth Creator 1, Synth Creator 2 · Clear");
    unbind();
  });

  it("Post sends tagged_users with the text and the schedule in one request", async () => {
    const d = loadPage("index");
    const s = memoryStorage();
    saveDraft(s, "1", { ...empty(), text: "Synthetic post", posted_at: AT, tagged_users: [2001] });
    const h = handlers();
    const unbind = bindPost(d, "new-post/index", { handlers: h, storage: s, accountId: "1", tagItems: TAGS });
    post(d).click();
    expect(h.createPost).toHaveBeenCalledTimes(1);
    expect(h.createPost).toHaveBeenCalledWith({ text: "Synthetic post", media_files: [], price: 0, posted_at: AT, tagged_users: [2001] });
    await flush();
    expect(h.navigate).not.toHaveBeenCalled();
    unbind();
  });
});

/** Bind `page` (under new-post) with bindPost and bindWrites, as OfMirrorFrame binds them. */
const bindBoth = (page: string, s = memoryStorage(), h: ReturnType<typeof handlers> | null = handlers(), extra: Partial<Parameters<typeof bindPost>[2]> = {}) => {
  const d = loadPage(page);
  const unbindPost = bindPost(d, `new-post/${page}`, { handlers: h, storage: s, accountId: h ? "1" : null, ...extra });
  const unbindWrites = bindWrites(d, `new-post/${page}`, null);
  return {
    d,
    s,
    h,
    unbind: () => {
      unbindPost();
      unbindWrites();
    },
  };
};
/** Type `value` into `input` as the browser would (input, then change on leaving it). */
const typeInto = (input: HTMLInputElement, value: string) => {
  input.value = value;
  input.dispatchEvent(new Event("input", { bubbles: true }));
  input.dispatchEvent(new Event("change", { bubbles: true }));
};

describe("poll and quiz panels (state-poll, state-quiz captures)", () => {
  const options = (d: Document) => [...d.querySelectorAll<HTMLInputElement>(".b-make-post__voting .vote-input input[at-attr='input']")];
  const radios = (d: Document) => [...d.querySelectorAll<HTMLInputElement>(".b-make-post__voting .vote-input input[type='radio']")];
  const addOption = (d: Document) => d.querySelector<HTMLButtonElement>(".b-make-post__voting .new_vote_add_option")!;

  it("typed options are the draft's poll, with no note; clearing every option drops it", () => {
    const { d, s, h, unbind } = bindBoth("state-poll");
    typeInto(options(d)[0], "Yes");
    typeInto(options(d)[1], "No");
    expect(loadDraft(s, "1").voting).toEqual({ type: 1, options: ["Yes", "No"] });
    expect(d.getElementById("oi-note")).toBeNull();
    expect(options(d).every((o) => o.hasAttribute("data-oi-wired"))).toBe(true);
    typeInto(options(d)[0], "");
    typeInto(options(d)[1], "");
    expect(loadDraft(s, "1").voting).toBeUndefined();
    expect(h!.createPost).not.toHaveBeenCalled();
    unbind();
  });

  it("+ Add another option adds an empty wired row, whose text joins the poll", () => {
    const { d, s, unbind } = bindBoth("state-poll");
    addOption(d).click();
    expect(d.getElementById("oi-note")).toBeNull();
    expect(options(d)).toHaveLength(3);
    expect(options(d)[2].value).toBe("");
    expect(d.activeElement).toBe(options(d)[2]); // the new row takes the cursor, as OF's does
    typeInto(options(d)[0], "A");
    typeInto(options(d)[2], "C");
    expect(loadDraft(s, "1").voting).toEqual({ type: 1, options: ["A", "", "C"] });
    unbind();
  });

  it("reopening shows the draft's options, extra rows included", () => {
    const s = memoryStorage();
    saveDraft(s, "1", { ...empty(), voting: { type: 1, options: ["A", "B", "C"] } });
    const { d, unbind } = bindBoth("state-poll", s);
    expect(options(d).map((o) => o.value)).toEqual(["A", "B", "C"]);
    unbind();
  });

  it("a quiz's correct-answer switch marks its row alone and saves it, with no note", () => {
    const { d, s, unbind } = bindBoth("state-quiz");
    typeInto(options(d)[0], "A");
    typeInto(options(d)[1], "B");
    const switches = () => [...d.querySelectorAll<HTMLElement>(".b-make-post__voting .vote-input .m-quiz-swithcer")];
    // The switch itself (OF's round button), as a click lands on it: its mark and its radio's attribute show the pick.
    switches()[1].click();
    expect(radios(d).map((r) => r.checked)).toEqual([false, true]);
    expect(radios(d).map((r) => r.hasAttribute("checked"))).toEqual([false, true]);
    expect(switches().map((b) => b.classList.contains("m-gray"))).toEqual([true, false]);
    expect(loadDraft(s, "1").voting).toEqual({ type: 2, options: ["A", "B"], correct: 1 });
    radios(d)[0].click();
    expect(radios(d).map((r) => r.checked)).toEqual([true, false]);
    expect(switches().map((b) => b.classList.contains("m-gray"))).toEqual([false, true]);
    expect(loadDraft(s, "1").voting?.correct).toBe(0);
    expect(d.getElementById("oi-note")).toBeNull();
    unbind();
  });

  it("the panel's × drops the poll from the draft", () => {
    const s = memoryStorage();
    saveDraft(s, "1", { ...empty(), text: "Synthetic post", voting: { type: 1, options: ["A", "B"] }, voting_due: 3 });
    const { d, unbind } = bindBoth("state-poll", s);
    const drop = d.querySelector<HTMLAnchorElement>(".b-make-post__voting .b-post-piece .b-dropzone__preview__delete")!;
    drop.addEventListener("click", (e) => e.preventDefault()); // no navigation in jsdom
    drop.click();
    expect(loadDraft(s, "1")).toEqual({ ...empty(), text: "Synthetic post" });
    unbind();
  });

  const piece = (d: Document) => d.querySelector<HTMLElement>(".b-make-post__voting .b-post-piece")!;
  const pieceValue = (d: Document) => piece(d).querySelector(".b-post-piece__value")!.textContent;
  const deletes = (d: Document) => [...d.querySelectorAll<HTMLButtonElement>(".b-make-post__voting .vote-input .delete-vote-option")];

  it("the duration piece shows the draft's length (OF's 7 days by default, No limit for 0)", () => {
    const s = memoryStorage();
    const shows = (page: string) => {
      const { d, unbind } = bindBoth(page, s);
      const text = pieceValue(d);
      unbind();
      return text;
    };
    expect(shows("state-poll")).toBe("7 days");
    saveDraft(s, "1", { ...empty(), voting_due: 1 });
    expect(shows("state-quiz")).toBe("1 day");
    saveDraft(s, "1", { ...empty(), voting_due: 0 });
    expect(shows("state-poll")).toBe("No limit");
  });

  it.each([
    ["state-poll", 1],
    ["state-quiz", 2],
  ] as const)("%s: a click on the duration piece marks the draft and opens the period dialog", (page, type) => {
    const { d, s, h, unbind } = bindBoth(page);
    expect(piece(d).hasAttribute("data-oi-wired")).toBe(true);
    piece(d).click();
    expect(loadDraft(s, "1").period_for).toBe(type);
    expect(h!.navigate).toHaveBeenCalledWith("/of-manager/new-post/state-expiration");
    expect(d.getElementById("oi-note")).toBeNull();
    unbind();
  });

  it("All-Creators scope: the duration piece gives the select-a-model note and opens nothing", () => {
    const { d, s, unbind } = bindBoth("state-poll", memoryStorage(), null);
    piece(d).click();
    expect(d.getElementById("oi-note")?.textContent).toBe(SELECT_MODEL);
    expect(s.length).toBe(0);
    unbind();
  });

  it("deletes are disabled at two rows; with three a delete removes its row and the poll follows", () => {
    const { d, s, unbind } = bindBoth("state-poll");
    expect(deletes(d).map((b) => b.disabled)).toEqual([true, true]);
    addOption(d).click();
    expect(deletes(d).map((b) => b.disabled)).toEqual([false, false, false]);
    expect(deletes(d).every((b) => b.hasAttribute("data-oi-wired"))).toBe(true);
    typeInto(options(d)[0], "A");
    typeInto(options(d)[1], "B");
    typeInto(options(d)[2], "C");
    deletes(d)[1].click();
    expect(options(d).map((o) => o.value)).toEqual(["A", "C"]);
    expect(loadDraft(s, "1").voting).toEqual({ type: 1, options: ["A", "C"] });
    expect(deletes(d).map((b) => b.disabled)).toEqual([true, true]);
    deletes(d)[0].click();
    expect(options(d)).toHaveLength(2);
    expect(d.getElementById("oi-note")).toBeNull();
    unbind();
  });

  it("deleting a quiz's correct answer moves it to the first row, as OF does", () => {
    const { d, s, unbind } = bindBoth("state-quiz");
    addOption(d).click();
    options(d).forEach((o, i) => typeInto(o, "ABC"[i]));
    radios(d)[2].click();
    deletes(d)[2].click();
    expect(radios(d).map((r) => r.checked)).toEqual([true, false]);
    expect(loadDraft(s, "1").voting).toEqual({ type: 2, options: ["A", "B"], correct: 0 });
    unbind();
  });

  it("+ Add another option stops at OF's 20 options", () => {
    const { d, unbind } = bindBoth("state-poll");
    for (let i = 0; i < 25; i++) addOption(d).click();
    expect(options(d)).toHaveLength(20);
    unbind();
  });

  it("All-Creators scope: a typed option is reset with the select-a-model note, and nothing is stored", () => {
    const { d, s, unbind } = bindBoth("state-poll", memoryStorage(), null);
    typeInto(options(d)[0], "Yes");
    expect(options(d)[0].value).toBe("");
    expect(d.getElementById("oi-note")?.textContent).toBe(SELECT_MODEL);
    expect(s.length).toBe(0);
    unbind();
  });
});

describe("expiration and fundraising target dialogs (state-expiration, state-target captures)", () => {
  const save = (d: Document) => d.querySelector<HTMLButtonElement>(".modal.show .modal-footer button")!;
  const period = (d: Document) => d.querySelector<HTMLInputElement>(".modal.show input[name='periodValue']")!;
  const tab = (d: Document, text: string) => [...d.querySelectorAll<HTMLButtonElement>(".modal.show .b-tabs__nav__link")].find((b) => b.textContent?.trim() === text)!;
  const target = (d: Document) => d.querySelector<HTMLInputElement>(".modal.show input[at-attr='input']")!;

  it.each(["new-post/state-expiration", "home/state-expiration"])("%s: the period chips wrap inside the 344px dialog, so 30 days is whole and takes its own click (U10)", (page) => {
    document.documentElement.innerHTML = readFileSync(resolve(__dirname, `../public/of-mirror/pages/${page}.html`), "utf8");
    const row = document.querySelector(".modal.show .b-tabs__nav__list")!;
    expect([...row.querySelectorAll(".b-tabs__nav__link")].map((b) => b.textContent?.trim())).toContain("30 days");
    expect(getComputedStyle(row).flexWrap).toBe("wrap");
    // Tag people's tabs (another small dialog) stay OF's one scrolled row.
    document.documentElement.innerHTML = readFileSync(resolve(__dirname, `../public/of-mirror/pages/${page.replace("expiration", "tag-people")}.html`), "utf8");
    expect(getComputedStyle(document.querySelector(".modal.show .b-tabs__nav__list")!).flexWrap).not.toBe("wrap");
  });

  it("a period tab fills the field and is current; Save stores expire_days and returns to the composer", () => {
    const { d, s, h, unbind } = bindBoth("state-expiration");
    tab(d, "7 days").click();
    expect(period(d).value).toBe("7");
    expect(tab(d, "7 days").classList.contains("m-current")).toBe(true);
    expect(tab(d, "No limit").classList.contains("m-current")).toBe(false);
    expect(save(d).disabled).toBe(false);
    save(d).click();
    expect(loadDraft(s, "1").expire_days).toBe(7);
    expect(h!.navigate).toHaveBeenCalledWith("/of-manager/new-post");
    expect(d.getElementById("oi-note")).toBeNull();
    unbind();
  });

  it("a typed period is saved; No limit clears it; a reopened dialog shows the draft's", () => {
    const s = memoryStorage();
    saveDraft(s, "1", { ...empty(), expire_days: 12 });
    const { d, unbind } = bindBoth("state-expiration", s);
    expect(period(d).value).toBe("12");
    typeInto(period(d), "21");
    save(d).click();
    expect(loadDraft(s, "1").expire_days).toBe(21);
    tab(d, "No limit").click();
    save(d).click();
    expect(loadDraft(s, "1").expire_days).toBeUndefined();
    unbind();
  });

  it("more than OF's 30 days keeps Save disabled", () => {
    const { d, s, unbind } = bindBoth("state-expiration");
    typeInto(period(d), "45");
    expect(save(d).disabled).toBe(true);
    save(d).click();
    expect(loadDraft(s, "1").expire_days).toBeUndefined();
    typeInto(period(d), "30");
    expect(save(d).disabled).toBe(false);
    unbind();
  });

  it("opened from a poll's duration: titled for it, opens on 7 days, Save stores voting_due and returns to the poll", () => {
    const s = memoryStorage();
    saveDraft(s, "1", { ...empty(), expire_days: 3, period_for: 1 });
    const { d, h, unbind } = bindBoth("state-expiration", s);
    const title = d.querySelector(".modal.show .modal-title")!;
    const links = () => [...d.querySelectorAll(".modal.show .modal-footer a, .modal.show .of-state-backdrop")].map((a) => a.getAttribute("href"));
    expect(title.textContent?.trim()).toBe("POLL DURATION");
    expect(links()).toEqual(["/of-manager/new-post/state-poll", "/of-manager/new-post/state-poll"]);
    expect(period(d).value).toBe("7");
    expect(tab(d, "7 days").classList.contains("m-current")).toBe(true);
    tab(d, "No limit").click();
    save(d).click();
    expect(loadDraft(s, "1")).toMatchObject({ voting_due: 0, expire_days: 3 });
    expect(h!.navigate).toHaveBeenCalledWith("/of-manager/new-post/state-poll");
    unbind();
    expect(title.textContent?.trim()).toBe("EXPIRATION PERIOD");
    expect(links()).toEqual(["/of-manager/new-post", "/of-manager/new-post"]);
  });

  it("opened from a quiz's duration: a typed length is saved and Save returns to the quiz", () => {
    const s = memoryStorage();
    saveDraft(s, "1", { ...empty(), voting_due: 3, period_for: 2 });
    const { d, h, unbind } = bindBoth("state-expiration", s);
    expect(d.querySelector(".modal.show .modal-title")!.textContent?.trim()).toBe("QUIZ DURATION");
    expect(period(d).value).toBe("3");
    typeInto(period(d), "30");
    save(d).click();
    expect(loadDraft(s, "1").voting_due).toBe(30);
    expect(loadDraft(s, "1").expire_days).toBeUndefined();
    expect(h!.navigate).toHaveBeenCalledWith("/of-manager/new-post/state-quiz");
    unbind();
  });

  it("any other new-post page drops a pending poll-duration mark, so the toolbar's EXPIRATION PERIOD is the post's again", () => {
    const s = memoryStorage();
    saveDraft(s, "1", { ...empty(), period_for: 1 });
    bindBoth("index", s).unbind();
    expect(loadDraft(s, "1").period_for).toBeUndefined();
  });

  it("a target of $10 or more enables Save, which stores fund_raising_target; less keeps it disabled", () => {
    const { d, s, h, unbind } = bindBoth("state-target");
    typeInto(target(d), "5");
    expect(save(d).disabled).toBe(true);
    typeInto(target(d), "50");
    expect(save(d).disabled).toBe(false);
    expect(d.getElementById("oi-note")).toBeNull();
    save(d).click();
    expect(loadDraft(s, "1").fund_raising_target).toBe(50);
    expect(h!.navigate).toHaveBeenCalledWith("/of-manager/new-post");
    unbind();
  });

  it("All-Creators scope: Save gives the select-a-model note and stores nothing", () => {
    const { d, s, unbind } = bindBoth("state-target", memoryStorage(), null);
    typeInto(target(d), "50");
    save(d).click();
    expect(d.getElementById("oi-note")?.textContent).toBe(SELECT_MODEL);
    expect(s.length).toBe(0);
    unbind();
  });
});

describe("labels dialog (state-labels capture)", () => {
  /** The Creator's own post labels from OF's GET /labels response (profile-labels.json, scrubbed): Archive and Private Archive are not offered. */
  const LABELS = postLabelsOf(fixture("profile-labels") as PostLabelsResp);
  const row = (d: Document, id: number) => d.querySelector<HTMLElement>(`label.b-rows-lists__item[data-oi-label='${id}']`)!;
  const newLabel = (d: Document) => d.querySelector<HTMLButtonElement>(".b-rows-lists__modal__add-list-btn")!;
  afterEach(() => vi.restoreAllMocks());

  it("applyLabelRows hides the examples and renders one wired row per label, its name and post count, checked when picked", () => {
    const d = loadPage("state-labels");
    applyLabelRows(d, LABELS, [8717761]);
    const shown = [...d.querySelectorAll<HTMLElement>("label.b-rows-lists__item")].filter((r) => r.style.display !== "none");
    expect(shown.map((r) => r.querySelector(".b-rows-lists__item__name")!.textContent!.trim())).toEqual(["Label 2", "Label 3"]);
    expect(row(d, 8717758).querySelector(".b-content-inside-thumbs__item")!.textContent!.trim()).toBe("3 posts");
    expect(row(d, 8717758).querySelector(".b-media-set")).toBeNull();
    expect(row(d, 8717758).hasAttribute("data-oi-wired")).toBe(true);
    expect(row(d, 8717761).querySelector<HTMLInputElement>("input")!.checked).toBe(true);
  });

  it("labelsOf reads OF's {list} or a bare array", () => {
    expect(labelsOf({ list: LABELS, hasMore: false })).toBe(LABELS);
    expect(labelsOf(LABELS)).toBe(LABELS);
    expect(labelsOf({})).toEqual([]);
  });

  it("checking a row picks its label in the draft, unchecking drops it, with no note", () => {
    const { d, s, unbind } = bindBoth("state-labels", memoryStorage(), handlers(), { labelItems: LABELS });
    row(d, 8717761).querySelector("input")!.click();
    row(d, 8717758).querySelector("input")!.click();
    expect(loadDraft(s, "1").label_ids).toEqual([8717761, 8717758]);
    row(d, 8717761).querySelector("input")!.click();
    expect(loadDraft(s, "1").label_ids).toEqual([8717758]);
    expect(d.getElementById("oi-note")).toBeNull();
    unbind();
  });

  const field = (d: Document) => d.querySelector<HTMLInputElement>("#oi-new-label input")!;
  const formButton = (d: Document, mark: string) => d.querySelector<HTMLButtonElement>(`#oi-new-label [${mark}]`)!;
  const typeName = (d: Document, name: string) => {
    field(d).value = name;
    field(d).dispatchEvent(new Event("input", { bubbles: true }));
  };

  it("NEW LABEL opens OF's name field in its place; Save creates the label, picks it and puts the button back", async () => {
    const { d, s, h, unbind } = bindBoth("state-labels", memoryStorage(), handlers(), { labelItems: LABELS });
    const prompt = vi.spyOn(d.defaultView!, "prompt");
    expect(d.getElementById("oi-new-label")!.style.display).toBe("none");
    newLabel(d).click();
    expect(prompt).not.toHaveBeenCalled();
    expect(newLabel(d).style.display).toBe("none");
    expect(d.getElementById("oi-new-label")!.style.display).toBe("flex");
    expect(d.activeElement).toBe(field(d));
    expect(formButton(d, "data-oi-save").disabled).toBe(true);
    typeName(d, "  Gamma label ");
    expect(formButton(d, "data-oi-save").disabled).toBe(false);
    formButton(d, "data-oi-save").click();
    expect(h!.createLabel).toHaveBeenCalledWith("Gamma label");
    await flush();
    expect(loadDraft(s, "1").label_ids).toEqual([77]);
    expect(newLabel(d).style.display).toBe("");
    expect(d.getElementById("oi-new-label")!.style.display).toBe("none");
    expect(d.getElementById("oi-note")).toBeNull();
    unbind();
    expect(d.getElementById("oi-new-label")).toBeNull();
  });

  it("NEW LABEL: Enter saves too; Cancel sends nothing; a failure shows the red note and keeps the field", async () => {
    const h = handlers();
    h.createLabel.mockImplementation(() => Promise.reject(new Error("502 bad gateway")));
    const { d, s, unbind } = bindBoth("state-labels", memoryStorage(), h, { labelItems: LABELS });
    newLabel(d).click();
    typeName(d, "Gamma label");
    formButton(d, "data-oi-cancel").click();
    expect(h.createLabel).not.toHaveBeenCalled();
    expect(newLabel(d).style.display).toBe("");
    newLabel(d).click();
    expect(field(d).value).toBe("");
    typeName(d, "Gamma label");
    field(d).dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
    expect(h.createLabel).toHaveBeenCalledWith("Gamma label");
    await flush();
    expect(d.getElementById("oi-note")?.textContent).toBe("Could not create: 502 bad gateway");
    expect(field(d).value).toBe("Gamma label");
    expect(formButton(d, "data-oi-save").disabled).toBe(false);
    expect(loadDraft(s, "1").label_ids).toBeUndefined();
    unbind();
  });

  it.each([
    ["no labelItems (loading or failed)", true],
    ["All-Creators scope", false],
  ])("%s: no rows at all, never the captured examples", (_, single) => {
    const { d, unbind } = bindBoth("state-labels", memoryStorage(), single ? handlers() : null);
    expect([...d.querySelectorAll<HTMLElement>("label.b-rows-lists__item")].filter((r) => r.style.display !== "none")).toHaveLength(0);
    unbind();
  });

  it("All-Creators scope: NEW LABEL gives the select-a-model note and opens nothing", () => {
    const { d, unbind } = bindBoth("state-labels", memoryStorage(), null);
    newLabel(d).click();
    expect(newLabel(d).style.display).toBe("");
    expect(d.getElementById("oi-note")?.textContent).toBe(SELECT_MODEL);
    unbind();
  });
});

describe("post extras on the composer (index capture)", () => {
  it("the summary names each extra; Clear drops them all", () => {
    const s = memoryStorage();
    saveDraft(s, "1", { ...empty(), text: "Synthetic post", save_for_later: true, voting: { type: 2, options: ["A", "B"], correct: 0 }, expire_days: 1, fund_raising_target: 50, label_ids: [11, 12] });
    const { d, unbind } = bindBoth("index", s);
    const summary = d.getElementById("oi-post-summary")!;
    expect(summary.textContent).toBe("Saved for later · Quiz: 2 options · Expires after 1 day · Target: $50 · Labels: 2 · Clear");
    summary.querySelector<HTMLElement>("[data-oi-clear]")!.click();
    expect(d.getElementById("oi-post-summary")).toBeNull();
    expect(loadDraft(s, "1")).toEqual({ ...empty(), text: "Synthetic post" });
    unbind();
  });

  it("the summary names the picked labels from the Relay's list; it counts them while one is unknown (U22)", () => {
    const labelItems = [{ id: 11, name: "Summer" }, { id: 12, name: "Beach" }];
    const s = memoryStorage();
    saveDraft(s, "1", { ...empty(), text: "Synthetic post", label_ids: [11, 12] });
    const named = bindBoth("index", s, handlers(), { labelItems });
    expect(named.d.getElementById("oi-post-summary")!.textContent).toBe("Labels: Summer, Beach · Clear");
    named.unbind();
    saveDraft(s, "1", { ...empty(), text: "Synthetic post", label_ids: [11, 13] });
    const unknown = bindBoth("index", s, handlers(), { labelItems });
    expect(unknown.d.getElementById("oi-post-summary")!.textContent).toBe("Labels: 2 · Clear");
    unknown.unbind();
  });

  it("the summary names a chosen poll length", () => {
    const s = memoryStorage();
    saveDraft(s, "1", { ...empty(), text: "Synthetic post", voting: { type: 1, options: ["A", "B"] }, voting_due: 0 });
    const { d, unbind } = bindBoth("index", s);
    expect(d.getElementById("oi-post-summary")!.textContent).toBe("Poll: 2 options, No limit · Clear");
    unbind();
  });

  it("Post sends every extra in one request; a saved-for-later post stays with its toast", async () => {
    const s = memoryStorage();
    saveDraft(s, "1", { ...empty(), text: "Synthetic post", save_for_later: true, voting: { type: 1, options: ["Yes", "No"] }, expire_days: 3, fund_raising_target: 25, label_ids: [11] });
    const { d, h, unbind } = bindBoth("index", s);
    post(d).click();
    expect(h!.createPost).toHaveBeenCalledWith({
      text: "Synthetic post",
      media_files: [],
      price: 0,
      save_for_later: true,
      voting_type: 1,
      voting_options: ["Yes", "No"],
      voting_due: 7,
      expire_days: 3,
      fund_raising_target: 25,
      label_ids: [11],
    });
    await flush();
    expect(h!.navigate).not.toHaveBeenCalled();
    expect(toastText(d)).toBe(SAVED_TOAST);
    unbind();
  });

  it("an incomplete poll makes Post show the note and send nothing", () => {
    const s = memoryStorage();
    saveDraft(s, "1", { ...empty(), text: "Synthetic post", voting: { type: 1, options: ["Yes", ""] } });
    const { d, h, unbind } = bindBoth("index", s);
    post(d).click();
    expect(d.getElementById("oi-note")?.textContent).toBe("Add at least two options");
    expect(h!.createPost).not.toHaveBeenCalled();
    unbind();
  });
});

describe("read-only controls (no Known body)", () => {
  /** Bind `page` in Single-Creator scope; nothing may reach a handler. */
  const bindPage = (page: string) => {
    const d = loadPage(page);
    const s = memoryStorage();
    const h = handlers();
    const unbindPost = bindPost(d, `new-post/${page}`, { handlers: h, storage: s, accountId: "1" });
    const unbindWrites = bindWrites(d, `new-post/${page}`, null); // the click fallback and change path, as OfMirrorFrame binds it
    const unbind = () => {
      unbindPost();
      unbindWrites();
    };
    return { d, s, h, unbind };
  };
  const noteText = (d: Document) => d.getElementById("oi-note")?.textContent;
  const expectNothingSent = (h: ReturnType<typeof handlers>) => {
    expect(h.createPost).not.toHaveBeenCalled();
    expect(h.navigate).not.toHaveBeenCalled();
  };

  it("state-format-text: the panel's tools are enabled and wired; with nothing selected a tool sends nothing and says so", () => {
    const { d, h, unbind } = bindPage("state-format-text");
    for (const label of ["Bold", "Italic", "Text Color", "Clear Formatting"]) {
      const b = d.querySelector<HTMLButtonElement>(`.js-text-editor-toolbar button[aria-label='${label}']`)!;
      expect(b.disabled, label).toBe(false);
      expect(b.hasAttribute("data-oi-wired"), label).toBe(true);
    }
    expect(d.querySelector(".js-text-editor-toolbar [aria-label='Text Size']")!.classList.contains("v-input--is-disabled")).toBe(false);
    d.querySelector<HTMLButtonElement>(".js-text-editor-toolbar button[aria-label='Bold']")!.click();
    expect(noteText(d)).toBe("Select some text to format");
    expectNothingSent(h);
    unbind();
  });

  it("state-format-text: Text Size and Text Color open OF's lists", () => {
    const { d, unbind } = bindPage("state-format-text");
    d.querySelector<HTMLElement>(".js-text-editor-toolbar [aria-label='Text Size']")!.click();
    expect([...d.querySelectorAll("#oi-menu [data-oi-value]")].map((r) => r.textContent?.trim())).toEqual(["Largest", "Large", "Default", "Small", "Smallest"]);
    d.body.click();
    d.querySelector<HTMLElement>(".js-text-editor-toolbar button[aria-label='Text Color']")!.click();
    expect([...d.querySelectorAll("#oi-menu [data-oi-value]")].map((r) => r.getAttribute("data-oi-value"))).toEqual(["m-editor-fc__gray", "m-editor-fc__blue-1", "m-editor-fc__blue-2", "m-editor-fc__default"]);
    unbind();
  });

  it.each(["Record voice", "Record video"])("index: %s opens the not-supported popup, whose OK closes it; nothing is sent", (label) => {
    const { d, h, unbind } = bindPage("index");
    const button = d.querySelector<HTMLButtonElement>(`button[aria-label='${label}']`)!;
    expect(button.disabled).toBe(false);
    expect(button.hasAttribute("data-oi-wired")).toBe(true);
    button.click();
    const popup = d.getElementById("oi-record-popup")!;
    expect(popup.textContent).toContain(RECORD_TEXT);
    expect(RECORD_TEXT).toBe("Recording isn't supported here. Use OnlyFans in your real browser. (I am a lazy dev.)");
    expect(d.getElementById("oi-note")).toBeNull();
    popup.querySelector<HTMLButtonElement>("button[data-oi-ok]")!.click();
    expect(d.getElementById("oi-record-popup")).toBeNull();
    expectNothingSent(h);
    unbind();
  });

  it.each(["state-labels", "state-poll", "state-quiz", "state-expiration", "state-target", "state-format-text"])(
    "%s: the editor's own input still saves the draft and enables Post, with no note",
    (page) => {
      const { d, s, unbind } = bindPage(page);
      type(d, "Synthetic post");
      expect(loadDraft(s, "1").text).toBe("Synthetic post");
      expect(post(d).disabled).toBe(false);
      expect(d.getElementById("oi-note")).toBeNull();
      unbind();
    },
  );
});

/**
 * New post from OF's own responses (app/lib/__fixtures__/of/new-post-*.json and profile-labels.json, read through the Relay
 * and scrubbed). new-post-create-body.json pairs each draft with the Relay body New post sends and the body the Relay's
 * of_client sends OF for it (OF's own keys, MakeFeedPost getDataObject).
 */
describe("New post with the captured shapes", () => {
  const ME = fixture("new-post-me") as OfMe;
  const LIMITS = { min: 3, max: 100 };
  const CREATE = fixture("new-post-create-body") as {
    now: string;
    ofKeys: string[];
    cases: { name: string; text: string; draft: Partial<PostDraft>; body: Record<string, unknown>; of: Record<string, unknown> }[];
  };

  it.each(CREATE.cases.map((c) => [c.name, c] as const))("the request body: %s", (_name, c) => {
    expect(collectPost(c.text, { ...empty(), ...c.draft }, new Date(CREATE.now))).toEqual(c.body);
    // The Relay's OF body uses OF's own keys; its one extra is `userTags` beside OF's `rfTag` for a tagged creator.
    expect(Object.keys(c.of).filter((k) => !CREATE.ofKeys.includes(k))).toEqual(c.draft.tagged_users ? ["userTags"] : []);
  });

  it("postPriceLimits: OF's price button on a free page, with users/me's post limits; none on a paid page or without the right", () => {
    expect(postPriceLimits(ME)).toEqual(LIMITS);
    expect(postPriceLimits({ ...ME, subscribePrice: 9.99 })).toBeNull();
    expect(postPriceLimits({ ...ME, canChangeContentPrice: false })).toBeNull();
    expect(postPriceLimits(undefined)).toBeUndefined();
  });

  it("readPrice: empty is free, a price within the limits is itself, anything else (or no limits) is null", () => {
    const read = readPrice(LIMITS);
    expect(["", "3", "$9.99", "100", "2.99", "100.01", "abc"].map(read)).toEqual([0, 3, 9.99, 100, null, null, null]);
    expect(readPrice(null)("5")).toBeNull();
  });

  it("standInModel: New post and its State pages show the first model in All models", () => {
    const accounts = [{ id: "7" }, { id: "8" }];
    expect(standInModel("/of-mirror/pages/new-post/index.html", null, accounts)).toBe("7");
    expect(standInModel("/of-mirror/pages/new-post/state-price.html", null, accounts)).toBe("7");
    expect(standInModel("/of-mirror/pages/new-post/index.html", "8", accounts)).toBeNull();
  });

  it("Post: disabled with OF's reason while there is neither text nor media; media alone posts, named by the model", async () => {
    const s = memoryStorage();
    const h = handlers();
    let { d, unbind } = bindBoth("index", s, h, { postAs: ME.name! });
    expect(post(d).disabled).toBe(true);
    expect(post(d).title).toBe("Write something or add media to post");
    expect(d.getElementById("oi-post-as")!.textContent).toBe("as Synth Model");
    expect(d.getElementById("oi-post-as")!.nextElementSibling).toBe(post(d));
    unbind();
    saveDraft(s, "1", { ...empty(), media_files: [5001], thumbs: ["/img?u=a"] });
    ({ d, unbind } = bindBoth("index", s, h, { postAs: ME.name! }));
    expect(post(d).disabled).toBe(false);
    expect(post(d).hasAttribute("title")).toBe(false);
    post(d).click();
    await flush();
    expect(h.createPost).toHaveBeenCalledWith({ text: "", media_files: [5001], price: 0 });
    unbind();
    expect(d.getElementById("oi-post-as")).toBeNull();
  });

  it("the price button shows only with limits and opens POST PRICE; Save keeps the price, which Post sends and which disables expiration and target", async () => {
    const s = memoryStorage();
    const h = handlers();
    const priceBtn = (d: Document) => d.querySelector<HTMLAnchorElement>("[at-attr='price_btn']")!;
    let { d, unbind } = bindBoth("index", s, h, { priceLimits: null });
    expect(priceBtn(d).style.display).toBe("none");
    unbind();
    ({ d, unbind } = bindBoth("state-price", s, h, { priceLimits: postPriceLimits(ME) }));
    expect(d.querySelector(".modal.show .modal-title")!.textContent!.trim()).toBe("POST PRICE");
    expect(d.querySelector(".modal.show .g-input__help")!.textContent).toBe("Minimum $3 USD or free");
    const field = d.querySelector<HTMLInputElement>(".modal.show input[at-attr='input']")!;
    const save = d.querySelector<HTMLButtonElement>(".modal.show .modal-footer button")!;
    const typeIn = (v: string) => {
      field.value = v;
      field.dispatchEvent(new Event("input", { bubbles: true }));
    };
    expect(save.disabled).toBe(true); // empty, no saved price: OF's isPriceInvalid
    typeIn("2");
    expect(save.disabled).toBe(true);
    typeIn("9.99");
    expect(save.disabled).toBe(false);
    save.click();
    expect(loadDraft(s, "1").price).toBe(9.99);
    expect(h.navigate).toHaveBeenCalledWith("/of-manager/new-post");
    unbind();
    saveDraft(s, "1", { ...loadDraft(s, "1"), text: "Synthetic paid post", media_files: [5001, 5002], thumbs: ["/img?u=a", "/img?u=b"] });
    ({ d, unbind } = bindBoth("index", s, h, { priceLimits: postPriceLimits(ME) }));
    expect(priceBtn(d).style.display).toBe("");
    expect(priceBtn(d).getAttribute("href")).toBe("/of-manager/new-post/state-price");
    expect(d.getElementById("oi-post-summary")!.textContent).toBe("Price: $9.99 · Clear");
    for (const tool of ["Expiration period", "Your target"]) expect(d.querySelector(`[aria-label='${tool}']`)!.getAttribute("aria-disabled"), tool).toBe("true");
    post(d).click();
    await flush();
    expect(h.createPost).toHaveBeenCalledWith(CREATE.cases.find((c) => c.name === "media and price")!.body);
    unbind();
  });

  it("POST PRICE opens on the saved price (Save disabled until it changes); emptying it saves a free post", () => {
    const s = memoryStorage();
    saveDraft(s, "1", { ...empty(), price: 9.99 });
    const h = handlers();
    const { d, unbind } = bindBoth("state-price", s, h, { priceLimits: postPriceLimits(ME) });
    const field = d.querySelector<HTMLInputElement>(".modal.show input[at-attr='input']")!;
    const save = d.querySelector<HTMLButtonElement>(".modal.show .modal-footer button")!;
    expect(field.value).toBe("9.99");
    expect(save.disabled).toBe(true);
    field.value = "";
    field.dispatchEvent(new Event("input", { bubbles: true }));
    expect(save.disabled).toBe(false);
    save.click();
    expect(loadDraft(s, "1").price).toBeUndefined();
    unbind();
  });

  it("ADD LABELS lists the Creator's own labels from OF's response, not Archive or Private Archive", () => {
    const { d, unbind } = bindBoth("state-labels", memoryStorage(), handlers(), { labelItems: labelsOf(fixture("profile-labels") as PostLabelsResp) });
    const shown = [...d.querySelectorAll<HTMLElement>("label.b-rows-lists__item")].filter((r) => r.style.display !== "none");
    expect(shown.map((r) => r.querySelector(".b-rows-lists__item__name")!.textContent!.trim())).toEqual(["Label 2", "Label 3"]);
    unbind();
  });

  it("TAG OTHER CREATORS lists OF's taggable creators by name and @username", () => {
    const items = (fixture("new-post-tags") as { items: TaggedFriendUser[] }).items;
    const { d, unbind } = bindBoth("state-tag-people", memoryStorage(), handlers(), { tagItems: items });
    const shown = [...d.querySelectorAll<HTMLElement>("label.b-rows-lists__item[data-oi-user]")].filter((r) => r.style.display !== "none");
    expect(shown.map((r) => r.querySelector(".b-rows-lists__item__name")!.textContent!.trim())).toEqual(["Synth Creator 1", "Synth Creator 2", "Synth Creator 3"]);
    expect(shown[0].querySelector(".b-rows-lists__item__subline")!.textContent!.trim()).toBe("@synthcreator1");
    unbind();
  });

  it("the vault dialog shows OF's folders and media, and a picked tile goes into the draft", () => {
    const lists = fixture("new-post-vault-lists") as { list: VaultList[]; all: never };
    const media = (fixture("new-post-vault-media") as { list: VaultMedia[] }).list;
    const d = loadPage("state-vault");
    applyData(d, "new-post/state-vault", { vaultLists: lists.list, vaultAll: lists.all, vaultMedia: media, picked: [] });
    const folders = [...d.querySelectorAll<HTMLElement>(".b-rows-lists__item")].filter((r) => r.style.display !== "none");
    expect(folders.map((r) => r.querySelector(".b-rows-lists__item__name")!.textContent!.trim())).toEqual(["All media", ...lists.list.map((l) => l.name)]);
    expect([...d.querySelectorAll("[data-oi-media]")].map((t) => t.getAttribute("data-oi-media"))).toEqual(media.map((m) => String(m.id)));
    const s = memoryStorage();
    const unbind = bindPost(d, "new-post/state-vault", { handlers: handlers(), storage: s, accountId: "1", vaultItems: media });
    d.querySelector<HTMLElement>("[data-oi-media='5001']")!.click();
    expect(loadDraft(s, "1").media_files).toEqual([5001]);
    unbind();
  });
});

describe("Edit post (the Queue's row menu): New post saves the queued post in place", () => {
  type Req = { method: string; path: string; body: Record<string, unknown> };
  const requests = fixture("queue-edit-requests") as Record<string, { of: Req; relay?: Req }>;
  const edited = () => {
    const h = { ...handlers(), editPost: vi.fn((_id: string, _body: unknown) => Promise.resolve({ id: 2433845504 })), confirm: vi.fn((_t: string) => true) };
    return h;
  };

  it("an edit that changes only the date: Post sends PUT /posts/{id} (the captured shape), not a new post, and goes back to the Queue", async () => {
    const s = memoryStorage();
    // The captured post's draft (postEditDraft), rescheduled a day later in the schedule dialog.
    const want = requests.reschedulePost.relay!;
    // OF's own Save sends the same moment as isScheduled + scheduledDate (captured live): the Relay maps posted_at to them.
    expect(Object.keys(requests.reschedulePost.of.body)).toEqual(expect.arrayContaining(["isScheduled", "scheduledDate", "text"]));
    saveDraft(s, "1", { ...empty(), text: "Synthetic scheduled post 1", posted_at: want.body.posted_at as string, edit_id: "2433845504" });
    const h = edited();
    const { d, unbind } = bindBoth("index", s, h, { zone: "Europe/Ljubljana" });
    expect(d.getElementById("oi-post-summary")!.textContent).toMatch(/^Editing a scheduled post · Scheduled for Fri, Nov 27, 3:14 AM · Clear · Discard$/);
    // OF's "Scheduled for" piece above the editor (PostScheduleForItem): its × greyed, a click opens the schedule.
    const pill = d.querySelector<HTMLElement>("#oi-schedule-pill > .b-post-piece.m-schedule")!;
    expect(pill.textContent!.replace(/\s+/g, " ").trim()).toBe("Scheduled for Fri, Nov 27, 3:14 AM");
    expect(pill.parentElement!.nextElementSibling!.contains(d.querySelector("[contenteditable]"))).toBe(true);
    expect([pill.querySelector("button")!.disabled, pill.querySelector("button")!.title]).toEqual([true, NOT_YET]);
    const schedule = d.querySelector<HTMLElement>("[at-attr='scheduled_msg']")!;
    const opened = vi.fn((ev: Event) => ev.preventDefault());
    schedule.addEventListener("click", opened);
    pill.click();
    expect(opened).toHaveBeenCalledTimes(1);
    post(d).click();
    expect(h.createPost).not.toHaveBeenCalled();
    expect(want.path).toBe("/api/of/v2/queue/posts/2433845504");
    expect(h.editPost.mock.calls).toEqual([["2433845504", want.body]]);
    await flush();
    expect(h.navigate).toHaveBeenCalledWith("/of-manager/queue?date=2026-11-27");
    expect(s.getItem(draftKey("1"))).toBeNull();
    unbind();
  });

  it("the schedule dialog shows and reads the Agency zone's wall clock", () => {
    const s = memoryStorage();
    saveDraft(s, "1", { ...empty(), text: "x", posted_at: "2026-11-26T02:14:00+00:00", edit_id: "2433845504" });
    const { d, unbind } = bindBoth("state-schedule", s, edited(), { zone: "America/Los_Angeles" });
    // 02:14 UTC on Nov 26 is 6:14 PM on Nov 25 in Los Angeles.
    expect(d.querySelector(".vdatetime-popup__tab.time")!.textContent).toBe("6:14 PM");
    expect(d.querySelector(".vdatetime-calendar__month__day--selected")!.textContent!.trim()).toBe("25");
    expect(collectSchedule(d, new Date("2026-11-01T00:00:00Z"), "America/Los_Angeles")).toBe(localIso(new Date("2026-11-26T02:14:00Z")));
    unbind();
  });

  it("an edited saved-for-later post stays saved for later and goes back to its page; Discard drops the draft and writes nothing", async () => {
    const s = memoryStorage();
    saveDraft(s, "1", { ...empty(), text: "Synthetic saved post", save_for_later: true, media_files: [8001], thumbs: [""], edit_id: "7001" });
    const h = edited();
    const { d, unbind } = bindBoth("index", s, h);
    expect(d.getElementById("oi-post-summary")!.textContent).toMatch(/^Editing a post saved for later · Saved for later · Clear · Discard$/);
    post(d).click();
    expect(h.editPost.mock.calls).toEqual([["7001", { text: "Synthetic saved post", media_files: [8001], price: 0, save_for_later: true }]]);
    await flush();
    expect(h.navigate).toHaveBeenCalledWith("/of-manager/queue/saved-for-later-posts");
    unbind();
    saveDraft(s, "1", { ...empty(), text: "Synthetic saved post", save_for_later: true, edit_id: "7001" });
    const again = bindBoth("index", s, h);
    again.d.querySelector<HTMLElement>("[data-oi-discard]")!.click();
    expect(s.getItem(draftKey("1"))).toBeNull();
    expect(h.editPost).toHaveBeenCalledTimes(1);
    again.unbind();
  });

  it("a Relay without the edit route (404, as one on main answers): the composer says the save failed, makes no new post and stays", async () => {
    const s = memoryStorage();
    saveDraft(s, "1", { ...empty(), text: "Synthetic scheduled post 1", posted_at: "2026-10-27T12:00:00+01:00", edit_id: "2827742023" });
    const h = { ...edited(), editPost: vi.fn((_id: string, _body: unknown) => Promise.reject(new RelayError(404, { detail: "Not Found" }, "Not Found"))) };
    const { d, unbind } = bindBoth("index", s, h, { zone: "Europe/Ljubljana" });
    post(d).click();
    await flush();
    expect(h.editPost).toHaveBeenCalledTimes(1);
    expect(h.createPost).not.toHaveBeenCalled();
    expect(h.navigate).not.toHaveBeenCalled();
    expect(d.getElementById("oi-note")?.textContent).toBe(`Could not save: ${OLD_RELAY}`);
    expect(post(d).disabled).toBe(false);
    expect(loadDraft(s, "1").edit_id).toBe("2827742023");
    unbind();
  });

  it("an edit with its date cleared asks before publishing at once; declined, nothing is sent", () => {
    const s = memoryStorage();
    saveDraft(s, "1", { ...empty(), text: "Synthetic scheduled post 1", edit_id: "2433845504" });
    const h = { ...edited(), confirm: vi.fn((_t: string) => false) };
    const { d, unbind } = bindBoth("index", s, h);
    post(d).click();
    expect(h.confirm).toHaveBeenCalledWith("This post has no date: publish it now?");
    expect(h.editPost).not.toHaveBeenCalled();
    unbind();
  });
});
