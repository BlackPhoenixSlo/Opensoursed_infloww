/**
 * New post's tools against OF's own shapes (app/lib/__fixtures__/of/new-post-*.json): formatted text, several files and
 * audio in one pick, a video story, the tag dialog's search, sort, tabs, row menu and invite, the vault dialog's folder
 * search and sort and its media sort, ADD LABELS' sort, a poll's drag to reorder, and the right column's search; the
 * Release form tab's empty placeholder, dialog notes above the footer, OF's sort menu look, and Settings' #promotion.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import { hasFormatting, normalize, ofHtml, setOfHtml } from "./ofMirrorFormat";
import { bindActionsOverflow, bindPost, bindStory, collectPost, loadDraft, searchHref, sortLabelRows, tagHref, tagsRoute, tagViewOf, type PostDraft, type PostLabel } from "./ofMirrorPost";
import { applyData } from "./ofMirrorData";
import { closeMenu, ORDER_GROUP, showMenu } from "./ofMirrorMenu";
import { AFTER_NEW_POST_PROMOTION, scrollToHash } from "./ofMirrorOffers";
import { note } from "./ofMirrorWrites";
import { relay, type TaggedFriendUser, type VaultUploadResp } from "./relay";
import { sortOfFolders } from "@/hooks/useVaultCache";

const fixture = <T,>(name: string): T => JSON.parse(readFileSync(resolve(__dirname, `__fixtures__/of/${name}.json`), "utf8")) as T;
const loadPage = (page: string) => {
  document.documentElement.innerHTML = readFileSync(resolve(__dirname, `../public/of-mirror/pages/${page}.html`), "utf8");
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
const click = (el: Element | null | undefined) => el!.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
const menuRows = (d: Document) => [...d.querySelectorAll<HTMLElement>("#oi-menu [data-oi-value]")];
const pickRow = (d: Document, label: string) => click(menuRows(d).find((r) => r.textContent?.trim() === label));
const unbinds: (() => void)[] = [];
const bound = (u: () => void) => void unbinds.push(u);
afterEach(() => {
  unbinds.splice(0).forEach((u) => u());
  vi.useRealTimers();
});
const handlers = () => ({
  createPost: vi.fn(() => Promise.resolve({})),
  createLabel: vi.fn(() => Promise.resolve({ id: 1 })),
  upload: vi.fn<(f: File) => Promise<VaultUploadResp>>(),
  navigate: vi.fn(),
  sortLabels: vi.fn(() => Promise.resolve({})),
  sortFolders: vi.fn(() => Promise.resolve({})),
  toggleTag: vi.fn(() => Promise.resolve({})),
  inviteGuest: vi.fn(() => Promise.resolve({ id: 9 })),
  searchUsers: vi.fn(() => Promise.resolve([])),
  searchPosts: vi.fn(() => Promise.resolve([])),
});

describe("Format text: OF's composer markup", () => {
  const cases = fixture<{ cases: { name: string; editor: string; html: string | null; relay: object }[] }>("new-post-format-body").cases;
  it.each(cases.map((c) => [c.name, c] as const))("%s", (_, c) => {
    const root = document.createElement("div");
    root.innerHTML = c.editor;
    normalize(root);
    expect(hasFormatting(root)).toBe(c.html !== null);
    if (c.html) expect(ofHtml(root)).toBe(c.html);
    const draft: PostDraft = { text: root.textContent ?? "", tagged_users: [], media_files: [], thumbs: [], html: hasFormatting(root) ? ofHtml(root) : undefined };
    expect(collectPost(root.textContent ?? "", draft)).toEqual(c.relay);
  });

  it("normalize leaves OF's tags in the editor (b, i, font gone; OF's classes on spans)", () => {
    const root = document.createElement("div");
    root.innerHTML = '<p><b>x</b><i>y</i><font color="#1b98e0">z</font><font size="1">s</font><span style="color: rgb(138, 150, 163)">g</span></p>';
    normalize(root);
    expect(root.innerHTML).toBe('<p><strong>x</strong><em>y</em><span class="m-editor-fc__blue-2">z</span><span class="m-editor-fs__sm">s</span><span class="m-editor-fc__gray">g</span></p>');
  });

  it("a saved draft's markup comes back with only OF's tags (no script, no attributes)", () => {
    const root = document.createElement("div");
    setOfHtml(root, '<p onclick="x()"><strong>b</strong><script>alert(1)</script><span class="m-editor-fs__l evil">L</span><a href="https://example.com">t</a></p><p></p>');
    expect(root.innerHTML).toBe('<p><strong>b</strong>alert(1)<span class="m-editor-fs__l">L</span>t</p><p><br></p>');
    expect(ofHtml(root)).toBe('<p><strong>b</strong>alert(1)<span class="m-editor-fs__l">L</span>t</p><p></p>');
  });

  it("only OF's exact class names survive: a lookalike or quote-carrying class never reaches the markup", () => {
    const root = document.createElement("div");
    const evil = document.createElement("span");
    evil.className = 'm-editor-fc__x"onmouseover="alert(1) m-editor-fs__lg2 m-editor-fc__blue-1';
    evil.textContent = "t";
    const p = document.createElement("p");
    p.append(evil);
    root.append(p);
    expect(ofHtml(root)).toBe('<p><span class="m-editor-fc__blue-1">t</span></p>');
    normalize(root);
    expect(root.innerHTML).toBe('<p><span class="m-editor-fc__blue-1">t</span></p>');
    setOfHtml(root, '<p><span class="m-editor-fc__evil&quot;onclick=&quot;x()">a</span><span class="m-editor-fs__sm">b</span></p>');
    expect(ofHtml(root)).toBe('<p>a<span class="m-editor-fs__sm">b</span></p>');
  });

  it("Post sends the formatted text as OF's markup (the draft keeps it across pages)", async () => {
    const d = loadPage("new-post/index");
    const h = handlers();
    const s = memoryStorage();
    bound(bindPost(d, "new-post/index", { handlers: h, storage: s, accountId: "1" }));
    const editor = d.querySelector<HTMLElement>("[contenteditable][aria-label='Textbox field']")!;
    editor.innerHTML = "<p>Hello <b>bold</b></p>";
    editor.dispatchEvent(new Event("input", { bubbles: true }));
    expect(loadDraft(s, "1").html).toBe("<p>Hello <strong>bold</strong></p>");
    // a State page round trip: the editor is drawn from the draft's markup
    const d2 = loadPage("new-post/state-schedule");
    bound(bindPost(d2, "new-post/state-schedule", { handlers: h, storage: s, accountId: "1" }));
    expect(d2.querySelector("[contenteditable][aria-label='Textbox field']")!.innerHTML).toBe("<p>Hello <strong>bold</strong></p>");
    const d3 = loadPage("new-post/index");
    bound(bindPost(d3, "new-post/index", { handlers: h, storage: s, accountId: "1" }));
    click(d3.querySelector("button[at-attr='submit_post']"));
    await flush();
    expect(h.createPost).toHaveBeenCalledWith({ text: "<p>Hello <strong>bold</strong></p>", media_files: [], price: 0 });
  });
});

describe("Add media: several files in one pick, audio too", () => {
  it("uploads each in the picked order and Post sends their claims as media_files (the fixture's body)", async () => {
    const fx = fixture<{ text: string; uploads: { name: string; type: string; send_with: Record<string, unknown>[] }[]; relay: object }>("new-post-media-body");
    const d = loadPage("new-post/index");
    const h = handlers();
    const s = memoryStorage();
    const order: string[] = [];
    h.upload.mockImplementation((f: File) => {
      order.push(f.name);
      const u = fx.uploads.find((x) => x.name === f.name)!;
      return Promise.resolve({ ready: true, send_with: u.send_with } as unknown as VaultUploadResp);
    });
    vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: () => "blob:synthetic" }));
    bound(bindPost(d, "new-post/index", { handlers: h, storage: s, accountId: "1" }));
    const picker = d.querySelector<HTMLInputElement>("input[type=file]")!;
    expect(picker.multiple).toBe(true);
    expect(picker.accept).toBe("image/*,video/*,audio/*");
    const files = fx.uploads.map((u) => new File(["x"], u.name, { type: u.type }));
    Object.defineProperty(picker, "files", { configurable: true, get: () => files });
    picker.dispatchEvent(new Event("change"));
    expect(d.querySelector<HTMLButtonElement>("button[at-attr='submit_post']")!.disabled).toBe(true); // all three in flight
    for (let i = 0; i < 10; i++) await flush();
    expect(order).toEqual(fx.uploads.map((u) => u.name));
    const editor = d.querySelector<HTMLElement>("[contenteditable][aria-label='Textbox field']")!;
    editor.innerHTML = `<p>${fx.text}</p>`;
    editor.dispatchEvent(new Event("input", { bubbles: true }));
    click(d.querySelector("button[at-attr='submit_post']"));
    await flush();
    expect(h.createPost).toHaveBeenCalledWith(fx.relay);
    vi.unstubAllGlobals();
  });
});

describe("Add to story: a video too", () => {
  it("a picked video goes to the story upload, as the fixture's request", async () => {
    const fx = fixture<{ file: { name: string; type: string } }>("new-post-story-video-body");
    const d = loadPage("new-post/index");
    const addStory = vi.fn(() => Promise.resolve({}));
    bound(bindStory(d, { addStory }));
    const picker = d.querySelector<HTMLInputElement>("input[type=file][accept='image/*,video/*']")!;
    const file = new File(["x"], fx.file.name, { type: fx.file.type });
    Object.defineProperty(picker, "files", { configurable: true, get: () => [file] });
    picker.dispatchEvent(new Event("change"));
    await flush();
    expect(addStory).toHaveBeenCalledWith(file);
    expect(d.getElementById("oi-note")?.textContent).toBe("Added to story");
  });
});

describe("Tag other creators: search, sort, tabs, row menu, invite", () => {
  const items = fixture<{ items: TaggedFriendUser[] }>("new-post-tags-search").items;
  const PAGE = "new-post/state-tag-people";
  const bindTag = (view = "") => {
    const d = loadPage(PAGE);
    const h = handlers();
    bound(bindPost(d, PAGE, { handlers: h, storage: memoryStorage(), accountId: "1", tagItems: items, tagView: tagViewOf(new URLSearchParams(view)) }));
    return { d, h };
  };

  it("reads OF's lists with its own params", () => {
    expect(tagsRoute(tagViewOf(new URLSearchParams("")))).toBe("/api/of/v2/posts/tagged-friend-users?limit=50&offset=0");
    expect(tagsRoute(tagViewOf(new URLSearchParams("q=alp&sort=name&order=asc")))).toBe("/api/of/v2/posts/tagged-friend-users?limit=50&offset=0&sort=name%3Aasc&filter=all&search=alp");
    expect(tagsRoute(tagViewOf(new URLSearchParams("tab=forms&filter=pending")))).toBe("/api/of/v2/release-forms?limit=50&offset=0&sort=date%3Adesc&filter=pending");
  });

  it("the search icon opens a field; typing opens the dialog with ?q=", async () => {
    vi.useFakeTimers();
    const { d, h } = bindTag();
    click(d.querySelector(".modal.show .modal-header button.g-btn.m-icon.m-icon-only:not([aria-label])"));
    const field = d.getElementById("oi-tag-search") as HTMLInputElement;
    expect(field).toBeTruthy();
    field.value = "creator";
    field.dispatchEvent(new Event("input"));
    await vi.advanceTimersByTimeAsync(400);
    expect(h.navigate).toHaveBeenCalledWith("/of-manager/new-post/state-tag-people?q=creator");
  });

  it("Sort: OF's menu; a pick opens the dialog sorted so", () => {
    const { d, h } = bindTag("q=creator");
    expect((d.getElementById("oi-tag-search") as HTMLInputElement).value).toBe("creator");
    click(d.querySelector(".modal.show button[aria-label='Sort']"));
    expect(menuRows(d).map((r) => r.textContent?.trim())).toEqual(["All", "Pending", "Recent", "Name", "Ascending", "Descending"]);
    pickRow(d, "Name");
    expect(h.navigate).toHaveBeenLastCalledWith(tagHref({ tab: "users", q: "creator", sort: "name", order: "desc", filter: "all" }, PAGE));
  });

  it("the Release form tab opens the dialog on OF's release forms", () => {
    const { d, h } = bindTag();
    const tab = [...d.querySelectorAll(".modal.show .b-tabs__nav__link")].find((t) => t.textContent?.trim() === "Release form")!;
    expect((tab as HTMLButtonElement).disabled).toBe(false);
    click(tab);
    expect(h.navigate).toHaveBeenCalledWith("/of-manager/new-post/state-tag-people?tab=forms");
  });

  it("the Release form tab with no forms shows OF's empty placeholder; while searching the search icon and Nothing found", () => {
    const empty = (view: string, list: TaggedFriendUser[] | undefined) => {
      const d = loadPage(PAGE);
      const unbind = bindPost(d, PAGE, { handlers: handlers(), storage: memoryStorage(), accountId: "1", tagItems: list, tagView: tagViewOf(new URLSearchParams(view)) });
      const docs = d.querySelector<HTMLElement>(".modal.show .b-release-form__docs")!;
      const el = docs.querySelector<HTMLElement>(":scope > .empty-message");
      const out = el && { icon: el.querySelector("svg")!.getAttribute("data-icon-name"), svg: el.querySelector("svg")!.getAttribute("class"), text: el.querySelector("span")!.textContent, column: docs.className };
      unbind();
      return { out, after: docs.querySelector(".empty-message"), scroll: docs.classList.contains("m-scrollbar-y") };
    };
    const none = empty("tab=forms", []);
    expect(none.out).toMatchObject({ icon: "icon-release-form", svg: "m-md-size mb-1 g-icon", text: "No release forms yet" });
    expect(none.out!.column).toContain("d-flex flex-column flex-fill");
    expect(none.out!.column).not.toContain("m-scrollbar-y");
    expect(none.after).toBeNull();
    expect(none.scroll).toBe(true);
    expect(empty("tab=forms&q=zz", []).out).toMatchObject({ icon: "icon-search", text: "Nothing found" });
    // loading (no list yet), forms there, or the Tag user tab: no placeholder
    expect(empty("tab=forms", undefined).out).toBeNull();
    expect(empty("tab=forms", items).out).toBeNull();
    expect(empty("", []).out).toBeNull();
  });

  it("a row's More > Hide from list sends OF's toggle-show body (the fixture's)", async () => {
    const fx = fixture<{ relay: object }>("new-post-tag-hide-body");
    const { d, h } = bindTag();
    const row = d.querySelector<HTMLElement>(`label.b-rows-lists__item[data-oi-user='${(fx.relay as { entity_id: number }).entity_id}']`) ?? d.querySelector<HTMLElement>("label.b-rows-lists__item[data-oi-user]")!;
    row.setAttribute("data-oi-entity", String((fx.relay as { entity_id: number }).entity_id));
    click(row.querySelector(".m-btn-vertical-dots"));
    pickRow(d, "Hide from list");
    expect(h.toggleTag).toHaveBeenCalledWith(fx.relay);
    await flush();
    expect(row.hasAttribute("data-oi-hidden")).toBe(true);
  });

  it("Invite new user: a name and Save send OF's guest body (the fixture's)", () => {
    const fx = fixture<{ relay: { name: string } }>("new-post-invite-body");
    const { d, h } = bindTag();
    const invite = [...d.querySelectorAll<HTMLButtonElement>(".modal.show button")].find((b) => b.textContent?.trim() === "Invite new user")!;
    expect(invite.disabled).toBe(false);
    click(invite);
    const input = d.querySelector<HTMLInputElement>("#oi-new-label input")!;
    input.value = fx.relay.name;
    input.dispatchEvent(new Event("input", { bubbles: true }));
    click(d.querySelector("#oi-new-label [data-oi-save]"));
    expect(h.inviteGuest).toHaveBeenCalledWith(fx.relay.name);
  });
});

describe("Vault dialog: folder search and sort, media sort", () => {
  const PAGE = "new-post/state-vault";
  const bindVaultPage = () => {
    const d = loadPage(PAGE);
    // the folder rows ofMirrorData draws (data-oi-data), named
    const rows = [...d.querySelectorAll<HTMLElement>(".modal.show .l-sidebar-column .b-rows-lists__item")].slice(1, 4);
    ["Beta", "alpha", "Gamma"].forEach((n, i) => {
      rows[i].setAttribute("data-oi-data", "");
      rows[i].querySelector(".b-rows-lists__item__name")!.textContent = n;
    });
    const h = handlers();
    bound(bindPost(d, PAGE, { handlers: h, storage: memoryStorage(), accountId: "1", vaultView: { field: null, sort: null, slist: null }, folderSort: { sort: "default", order: "desc" } }));
    const names = () => [...d.querySelectorAll<HTMLElement>(".modal.show .l-sidebar-column .b-rows-lists__item[data-oi-data]")].filter((r) => r.style.display !== "none").map((r) => r.querySelector(".b-rows-lists__item__name")!.textContent);
    return { d, h, names };
  };

  it("Search opens the dialog with ?slist= (GET /vault/lists' `query`, as the Vault page's) as you type", async () => {
    vi.useFakeTimers();
    const { d, h } = bindVaultPage();
    click(d.querySelector(".modal.show .l-sidebar-column .g-page__header button[aria-label='Search']"));
    const field = d.querySelector<HTMLInputElement>("input[aria-label='Search folders']")!;
    field.value = "alp";
    field.dispatchEvent(new Event("input"));
    await vi.advanceTimersByTimeAsync(400);
    expect(h.navigate).toHaveBeenCalledWith("/of-manager/new-post/state-vault?slist=alp");
  });

  it("folder Sort > Name re-orders the rows and sends OF's sort", () => {
    const { d, h, names } = bindVaultPage();
    click(d.querySelector(".modal.show .l-sidebar-column button[aria-label='Sort']"));
    expect(menuRows(d).map((r) => r.textContent?.trim())).toEqual(["Default", "Name", "Recent", "Media", "Custom", "Ascending", "Descending"]);
    pickRow(d, "Name");
    expect(h.sortFolders).toHaveBeenCalledWith("name", "desc");
    expect(names()).toEqual(["Gamma", "Beta", "alpha"]);
    click(d.querySelector(".modal.show .l-sidebar-column button[aria-label='Sort']"));
    pickRow(d, "Ascending");
    expect(h.sortFolders).toHaveBeenLastCalledWith("name", "asc");
    expect(names()).toEqual(["alpha", "Beta", "Gamma"]);
  });

  it("folder Sort sends the fixture's body: the app's to the Relay, the Relay's on to OF", async () => {
    const fx = fixture<{ relay: { account_id: string; sort: string; order: string }; of: { sort: string; order: string } }>("new-post-vault-sort-body");
    const { d, h } = bindVaultPage();
    click(d.querySelector(".modal.show .l-sidebar-column button[aria-label='Sort']"));
    pickRow(d, "Name");
    expect(h.sortFolders).toHaveBeenCalledWith(fx.relay.sort, fx.relay.order);
    // the handler's request (useVaultCache.sortOfFolders), as the interceptor caught it
    const post = vi.spyOn(relay, "post").mockResolvedValue({ sorted: true });
    await sortOfFolders(fx.relay.account_id, { sort: fx.relay.sort, order: fx.relay.order });
    expect(post).toHaveBeenCalledWith("/admin/vault-ai/of-folders/sort", expect.anything(), { accountId: fx.relay.account_id });
    expect(JSON.parse(JSON.stringify(post.mock.calls[0][1]))).toEqual(fx.relay);
    expect(fx.of).toEqual({ sort: fx.relay.sort, order: fx.relay.order });
    post.mockRestore();
  });

  it("during a folder search All media shows only while its name starts with the query (OF's showAllMedia)", () => {
    const allRow = (d: Document) => [...d.querySelectorAll<HTMLElement>(".b-rows-lists__item")].find((r) => r.querySelector(".b-rows-lists__item__name")?.textContent?.trim() === "All media")!;
    const data = { vaultLists: [{ id: 7, name: "Beach set", photosCount: 2 } as never], vaultAll: { photosCount: 5 } as never, vaultMedia: [] };
    for (const [q, shown] of [[null, true], ["all", true], ["  ALL M", true], ["beach", false], ["media", false]] as const) {
      const d = loadPage(PAGE);
      applyData(d, PAGE, { ...data, vaultSearch: q });
      expect([q, allRow(d).style.display !== "none"]).toEqual([q, shown]);
    }
  });

  it("media Sort opens the dialog with OF's field and order", () => {
    const { d, h } = bindVaultPage();
    const sorts = [...d.querySelectorAll(".modal.show button[aria-label='Sort']")];
    click(sorts.at(-1));
    expect(menuRows(d).map((r) => r.textContent?.trim())).toEqual(["Recent", "Most liked", "Highest tips", "Buyers", "Ascending", "Descending"]);
    pickRow(d, "Most liked");
    expect(h.navigate).toHaveBeenCalledWith("/of-manager/new-post/state-vault?field=most-liked");
  });
});

describe("ADD LABELS: Sort", () => {
  it("puts the rows in the picked order and sends OF's body (the fixture's)", () => {
    const fx = fixture<{ relay: { sort: string; order: string } }>("new-post-labels-sort-body");
    const labels = fixture<{ list: PostLabel[]; sort: string; order: string }>("new-post-labels");
    const d = loadPage("new-post/state-labels");
    const h = handlers();
    bound(bindPost(d, "new-post/state-labels", { handlers: h, storage: memoryStorage(), accountId: "1", labelItems: labels.list, labelSort: { sort: labels.sort, order: labels.order } }));
    const names = () => [...d.querySelectorAll("label.b-rows-lists__item[data-oi-label] .b-rows-lists__item__name")].map((n) => n.textContent?.trim());
    expect(names()).toEqual(["Label 3", "Label 4"]);
    click(d.querySelector(".modal.show button[aria-label='Sort']"));
    pickRow(d, "Name");
    click(d.querySelector(".modal.show button[aria-label='Sort']"));
    pickRow(d, "Ascending");
    expect(h.sortLabels).toHaveBeenLastCalledWith(fx.relay.sort, fx.relay.order);
    expect(names()).toEqual(["Label 3", "Label 4"]);
    sortLabelRows(d, labels.list, "posts", "desc");
    expect(names()).toEqual(["Label 4", "Label 3"]);
  });
});

describe("Poll and quiz: drag to reorder", () => {
  it("a row's handle carries it below the next one; the draft keeps the new order", () => {
    const d = loadPage("new-post/state-poll");
    const s = memoryStorage();
    bound(bindPost(d, "new-post/state-poll", { handlers: handlers(), storage: s, accountId: "1" }));
    click(d.querySelector(".b-make-post__voting .new_vote_add_option"));
    const rows = () => [...d.querySelectorAll<HTMLElement>(".b-make-post__voting .vote-input")];
    rows().forEach((r, i) => {
      const input = r.querySelector<HTMLInputElement>("input[at-attr='input']")!;
      input.value = "ABC"[i];
      input.dispatchEvent(new Event("input", { bubbles: true }));
      // each row 40px tall, stacked
      r.getBoundingClientRect = () => ({ top: i * 40, height: 40, bottom: i * 40 + 40, left: 0, right: 100, width: 100, x: 0, y: i * 40, toJSON: () => ({}) }) as DOMRect;
    });
    const handle = rows()[0].querySelector(".m-drag-btn")!;
    expect(handle.hasAttribute("data-oi-wired")).toBe(true);
    handle.dispatchEvent(new MouseEvent("pointerdown", { bubbles: true, cancelable: true, clientY: 10 }));
    d.dispatchEvent(new MouseEvent("pointermove", { bubbles: true, cancelable: true, clientY: 75 }));
    d.dispatchEvent(new MouseEvent("pointerup", { bubbles: true }));
    expect(rows().map((r) => r.querySelector<HTMLInputElement>("input[at-attr='input']")!.value)).toEqual(["B", "A", "C"]);
    expect(loadDraft(s, "1").voting).toEqual({ type: 1, options: ["B", "A", "C"] });
  });

  it("quiz: the correct-answer marker moves with its row, and the draft's correct index follows it", () => {
    const d = loadPage("new-post/state-quiz");
    const s = memoryStorage();
    bound(bindPost(d, "new-post/state-quiz", { handlers: handlers(), storage: s, accountId: "1" }));
    click(d.querySelector(".b-make-post__voting .new_vote_add_option"));
    const rows = () => [...d.querySelectorAll<HTMLElement>(".b-make-post__voting .vote-input")];
    const text = () => rows().map((r) => r.querySelector<HTMLInputElement>("input[at-attr='input']")!.value);
    const marked = () => rows().map((r) => r.querySelector<HTMLInputElement>("input[type='radio']")!.checked);
    rows().forEach((r, i) => {
      const input = r.querySelector<HTMLInputElement>("input[at-attr='input']")!;
      input.value = "ABC"[i];
      input.dispatchEvent(new Event("input", { bubbles: true }));
      r.getBoundingClientRect = () => ({ top: i * 40, height: 40, bottom: i * 40 + 40, left: 0, right: 100, width: 100, x: 0, y: i * 40, toJSON: () => ({}) }) as DOMRect;
    });
    // "A" is the correct answer
    click(rows()[0].querySelector(".m-quiz-swithcer"));
    expect(marked()).toEqual([true, false, false]);
    expect(loadDraft(s, "1").voting).toEqual({ type: 2, options: ["A", "B", "C"], correct: 0 });
    // A dragged below B
    rows()[0].querySelector(".m-drag-btn")!.dispatchEvent(new MouseEvent("pointerdown", { bubbles: true, cancelable: true, clientY: 10 }));
    d.dispatchEvent(new MouseEvent("pointermove", { bubbles: true, cancelable: true, clientY: 75 }));
    d.dispatchEvent(new MouseEvent("pointerup", { bubbles: true }));
    expect(text()).toEqual(["B", "A", "C"]);
    expect(marked()).toEqual([false, true, false]);
    expect(rows()[1].querySelector(".m-quiz-swithcer")!.classList.contains("m-gray")).toBe(false);
    expect(rows()[0].querySelector(".m-quiz-swithcer")!.classList.contains("m-gray")).toBe(true);
    expect(loadDraft(s, "1").voting).toEqual({ type: 2, options: ["B", "A", "C"], correct: 1 });
    // and a POST body counts it there
    expect(collectPost("Quiz", loadDraft(s, "1"))).toMatchObject({ voting_type: 2, voting_correct_index: 1 });
  });
});

describe("Right column search", () => {
  it("runs OF's users and posts search and links each result to its OF Manager page", async () => {
    vi.useFakeTimers();
    const d = loadPage("new-post/index");
    const h = handlers();
    h.searchUsers.mockResolvedValue([{ id: 5001, name: "Synthetic Fan", username: "fan1" }, { id: 5002, name: "Fan &amp; Co", username: "fan2" }] as never);
    h.searchPosts.mockResolvedValue({ list: [{ id: 6001, text: "<p>Hello</p>", author: { id: 77, username: "yourmodel" } }, { id: 6002, text: "Other &lt;3 &amp; more", author: { id: 88, username: "creator2" } }] } as never);
    bound(bindPost(d, "new-post/index", { handlers: h, storage: memoryStorage(), accountId: "1", meId: 77 }));
    const input = d.querySelector<HTMLInputElement>("input[name='feed-search-input']")!;
    input.value = "syn";
    input.dispatchEvent(new Event("input", { bubbles: true }));
    await vi.advanceTimersByTimeAsync(400);
    vi.useRealTimers();
    await flush();
    expect(h.searchUsers).toHaveBeenCalledWith("syn");
    expect(h.searchPosts).toHaveBeenCalledWith("syn");
    const links = [...d.querySelectorAll<HTMLAnchorElement>("#oi-search-results a")].map((a) => [a.textContent, a.getAttribute("href")]);
    expect(links).toEqual([
      ["Synthetic Fan @fan1", "/of-manager/messages/chat?chat=5001"],
      ["Fan & Co @fan2", "/of-manager/messages/chat?chat=5002"],
      ["Hello · @yourmodel", "/of-manager/profile"],
      ["Other <3 & more · @creator2", "/of-manager/messages/chat?chat=88"],
    ]);
    expect(d.getElementById("oi-note")).toBeNull();
  });

  it("searchHref: a user's chat; the model's own post its profile", () => {
    expect(searchHref("user", { id: 1 })).toBe("/of-manager/messages/chat?chat=1");
    expect(searchHref("post", { id: 2, author: { id: 3 } }, 3)).toBe("/of-manager/profile");
    expect(searchHref("post", { id: 2 })).toBeNull();
  });

  it("All-Creators: says select a model, sends nothing", async () => {
    vi.useFakeTimers();
    const d = loadPage("new-post/index");
    bound(bindPost(d, "new-post/index", { handlers: null, storage: memoryStorage(), accountId: null }));
    const input = d.querySelector<HTMLInputElement>("input[name='feed-search-input']")!;
    input.value = "syn";
    input.dispatchEvent(new Event("input", { bubbles: true }));
    await vi.advanceTimersByTimeAsync(400);
    expect(d.getElementById("oi-note")?.textContent).toBe("Select a model to save changes");
  });
});

describe("Composer toolbar on a narrow screen (OF's resize: overflow into More)", () => {
  // jsdom has no layout: each shown toolbar item is 40px wide, the composer `width`.
  const layout = (d: Document, width: number) => {
    const actions = d.querySelector<HTMLElement>(".b-make-post__actions")!;
    const btns = actions.querySelector<HTMLElement>(".b-make-post__actions__btns")!;
    Object.defineProperty(actions, "offsetWidth", { configurable: true, get: () => 40 * [...btns.children].filter((c) => (c as HTMLElement).style.display !== "none").length });
    Object.defineProperty(actions.parentElement!, "clientWidth", { configurable: true, get: () => width });
    return btns;
  };
  const shown = (btns: HTMLElement) => [...btns.children].filter((c) => (c as HTMLElement).style.display !== "none").map((c) => c.getAttribute("aria-label"));

  it("a wide composer keeps every button and no More", () => {
    const d = loadPage("new-post/index");
    const btns = layout(d, 2000);
    bound(bindActionsOverflow(d));
    expect(d.getElementById("oi-actions-more")).toBeNull();
    expect(btns.querySelectorAll("[data-oi-overflow]")).toHaveLength(0);
  });

  it("a narrow one moves the last buttons into More until the row fits; a More row clicks its button; unbind puts them back", () => {
    const d = loadPage("new-post/index");
    const btns = layout(d, 360); // 9 slots: 8 buttons and More
    const before = shown(btns);
    const unbind = bindActionsOverflow(d);
    const after = shown(btns);
    expect(after).toHaveLength(9);
    expect(after.at(-1)).toBe("More");
    expect(after.slice(0, 8)).toEqual(before.slice(0, 8));
    const moved = [...btns.querySelectorAll<HTMLElement>("[data-oi-overflow]")];
    expect(moved.map((b) => b.getAttribute("aria-label"))).toEqual(before.slice(8));
    click(d.getElementById("oi-actions-more"));
    expect(menuRows(d).map((r) => r.textContent?.trim())).toEqual(before.slice(8));
    // OF's rows carry the button's icon
    expect(menuRows(d)[0].querySelector("use")?.getAttribute("href")).toBe(moved[0].querySelector("use")?.getAttribute("href"));
    const hit = vi.fn((ev: Event) => ev.preventDefault());
    moved[1].addEventListener("click", hit);
    pickRow(d, moved[1].getAttribute("aria-label")!);
    expect(hit).toHaveBeenCalledOnce();
    expect(d.getElementById("oi-menu")).toBeNull();
    unbind();
    expect(shown(btns)).toEqual(before);
    expect(d.getElementById("oi-actions-more")).toBeNull();
  });

  it("the send-tip button OF keeps hidden stays hidden throughout", () => {
    const d = loadPage("new-post/index");
    const tip = d.querySelector<HTMLElement>("button[at-attr='send_tip']")!;
    expect(tip.style.display).toBe("none");
    layout(d, 200);
    const unbind = bindActionsOverflow(d);
    expect(tip.hasAttribute("data-oi-overflow")).toBe(false);
    unbind();
    expect(tip.style.display).toBe("none");
  });
});

describe("Dialog notes sit above the footer's buttons", () => {
  it("Invite new user's failure shows over its name row, which keeps its field, Cancel and Save together", async () => {
    const d = loadPage("new-post/state-tag-people");
    const h = { ...handlers(), inviteGuest: vi.fn(() => Promise.reject(new Error("intercepted: not sent to OnlyFans"))) };
    bound(bindPost(d, "new-post/state-tag-people", { handlers: h, storage: memoryStorage(), accountId: "1", tagItems: [], tagView: tagViewOf(new URLSearchParams("")) }));
    click([...d.querySelectorAll<HTMLButtonElement>(".modal.show button")].find((b) => b.textContent?.trim() === "Invite new user"));
    const row = d.getElementById("oi-new-label")!;
    expect(row.style.display).toBe("flex");
    const input = row.querySelector<HTMLInputElement>("input[aria-label='Name']")!;
    input.value = "Synthetic Guest";
    input.dispatchEvent(new Event("input", { bubbles: true }));
    click(row.querySelector("[data-oi-save]"));
    await flush();
    const n = d.getElementById("oi-note")!;
    expect(n.textContent).toBe("Could not invite: intercepted: not sent to OnlyFans");
    expect(n.nextElementSibling).toBe(row);
    expect([...row.children].map((c) => c.matches("[data-oi-cancel]") ? "cancel" : c.matches("[data-oi-save]") ? "save" : c.querySelector("input") ? "field" : "?")).toEqual(["field", "cancel", "save"]);
  });

  it("a dialog footer's button: the note goes right above the footer (a page's own button keeps it beside the button)", () => {
    document.body.innerHTML = '<div class="modal-content"><div class="modal-body"></div><div class="modal-footer"><button>Cancel</button><button id="s">Share</button></div></div><div class="page"><button id="p">Save</button></div>';
    note(document, document.getElementById("s")!, "Could not share: boom", true);
    expect(document.getElementById("oi-note")!.nextElementSibling!.className).toBe("modal-footer");
    note(document, document.getElementById("p")!, "Saved");
    expect(document.getElementById("oi-note")!.nextElementSibling!.id).toBe("p");
  });
});

describe("Sort menus in OF's dropdown look", () => {
  const rect = (el: Element, r: Partial<DOMRect>) => (el.getBoundingClientRect = () => ({ left: 0, right: 0, top: 0, bottom: 0, width: 0, height: 0, x: 0, y: 0, toJSON: () => ({}), ...r }) as DOMRect);
  afterEach(() => closeMenu(document));

  it("radio rows carry OF's radio and list scoped-style marks; plain-row menus keep their own", () => {
    document.body.innerHTML = '<button id="a">Sort</button>';
    const a = document.getElementById("a")!;
    showMenu(document, a, [{ name: "field", value: "x", options: [{ value: "x", label: "X" }] }, ORDER_GROUP("desc")], () => {});
    const menu = document.getElementById("oi-menu")!;
    expect(menu.querySelectorAll(".b-input-radio__container[data-v-af619994] input[data-v-af619994] + label[data-v-af619994] + .b-input-radio__label[data-v-af619994]")).toHaveLength(3);
    expect(menu.firstElementChild!.hasAttribute("data-v-d2f665f6")).toBe(true);
    expect(menu.style.borderStyle).toBe("none");
    closeMenu(document);
    showMenu(document, a, [{ name: "row", radio: false, options: [{ value: "t", label: "Hide from list" }] }], () => {});
    expect(document.getElementById("oi-menu")!.firstElementChild!.hasAttribute("data-v-d2f665f6")).toBe(false);
  });

  it("a menu that would run past its dialog is right-aligned to the anchor, as OF's; one that fits stays at the anchor's left", () => {
    document.body.innerHTML = '<div class="modal-content"><button id="a">Sort</button><button id="b">Sort</button></div>';
    rect(document.querySelector(".modal-content")!, { left: 100, right: 400 });
    rect(document.getElementById("a")!, { left: 350, right: 380, bottom: 50 });
    rect(document.getElementById("b")!, { left: 110, right: 140, bottom: 50 });
    showMenu(document, document.getElementById("a")!, [ORDER_GROUP("asc")], () => {});
    expect(document.getElementById("oi-menu")!.style.left).toBe("160px");
    closeMenu(document);
    showMenu(document, document.getElementById("b")!, [ORDER_GROUP("asc")], () => {});
    expect(document.getElementById("oi-menu")!.style.left).toBe("110px");
  });
});

describe("Settings > Subscription #promotion (where the promotion tile and Start campaign go, as OF)", () => {
  it("the hash is OF's; the frame's page scrolls to OF's #promotion section, other hashes leave it", () => {
    expect(AFTER_NEW_POST_PROMOTION).toBe("/of-manager/settings/subscription#promotion");
    const d = loadPage("settings/subscription");
    const section = d.getElementById("promotion")!;
    const scroll = vi.fn();
    section.scrollIntoView = scroll;
    expect(scrollToHash(d, "#promotion")).toBe(true);
    expect(scroll).toHaveBeenCalledWith({ behavior: "smooth", block: "start" });
    expect(scrollToHash(d, "")).toBe(false);
    expect(scrollToHash(d, "#a=b")).toBe(false);
    expect(scrollToHash(d, "#missing")).toBe(false);
  });
});
