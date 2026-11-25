import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ABOUT_FORMAT, profileAbout } from "./ofMirrorProfileFormat";
import { applyIdentity } from "./ofMirrorIdentity";
import { bindWrites, SAVED_TOAST, SELECT_MODEL } from "./ofMirrorWrites";

const PAGE = "settings/profile";
const BIO = "[data-placeholder='Bio']";
const PANEL = "[data-oi-about-format]";
const load = () => {
  document.documentElement.innerHTML = readFileSync(resolve(__dirname, `../public/of-mirror/pages/${PAGE}.html`), "utf8");
  document.execCommand = vi.fn((name: string) => {
    if (name !== "bold") return true;
    document.getSelection()!.getRangeAt(0).surroundContents(document.createElement("b"));
    return true;
  }) as never;
  return document;
};
const handlers = () => ({
  uploadProfileImage: vi.fn(),
  saveProfile: vi.fn((_body: unknown) => Promise.resolve()),
  setReplyOnSubscribe: vi.fn(() => Promise.resolve()),
  submit: vi.fn(() => Promise.resolve({})),
  navigate: vi.fn(),
});
const flush = () => new Promise((r) => setTimeout(r, 0));
const bio = (d: Document) => d.querySelector<HTMLElement>(BIO)!;
const save = (d: Document) => d.querySelector<HTMLButtonElement>(".g-btn__wrapper button[type='submit']")!;
const tool = (d: Document, label: string) => d.querySelector<HTMLElement>(`${PANEL} [aria-label='${label}']`)!;
const select = (d: Document, from: number, to: number) => {
  const text = bio(d).querySelector("p")!.firstChild!;
  const r = d.createRange();
  r.setStart(text, from);
  r.setEnd(text, to);
  d.getSelection()!.removeAllRanges();
  d.getSelection()!.addRange(r);
  d.dispatchEvent(new Event("selectionchange"));
};
const noteOf = (d: Document) => d.getElementById("oi-note")?.textContent ?? null;

afterEach(() => vi.restoreAllMocks());

describe("profileAbout", () => {
  const el = (html: string) => {
    const div = document.createElement("div");
    div.innerHTML = html;
    return div;
  };
  it.each([
    ["plain lines stay plain text", "<p>Line one</p><p>Line two</p>", "Line one\nLine two"],
    ["no paragraphs: its text", "Just text", "Just text"],
    ["bold: OF's markup", "<p><strong>Hi</strong> there</p>", "<p><strong>Hi</strong> there</p>"],
    ["italic", "<p>a <em>b</em></p>", "<p>a <em>b</em></p>"],
    ["a size and colour span", '<p><span class="m-editor-fs__l m-editor-fc__blue-2">Big</span></p>', '<p><span class="m-editor-fs__l m-editor-fc__blue-2">Big</span></p>'],
    ["empty", "<p></p>", ""],
    ["a plain bio's newlines, once formatted: OF's <br>", "<p><strong>One</strong>\n\nTwo\n</p>", "<p><strong>One</strong><br><br>Two<br></p>"],
    ["newlines inside a mark (the mark closes around the <br>, as ofHtml writes it)", "<p><strong>One\nTwo</strong></p>", "<p><strong>One</strong><br><strong>Two</strong></p>"],
  ])("%s", (_name, html, want) => expect(profileAbout(el(html))).toBe(want));
});

describe("Edit profile's About format button (ticket 68)", () => {
  it("is usable and Wired, its Not-yet title dropped (Live pass, D1); a click opens the toolbar over the Bio and its close closes it", () => {
    const d = load();
    const unbind = bindWrites(d, PAGE, handlers(), true);
    const btn = d.querySelector<HTMLButtonElement>(ABOUT_FORMAT)!;
    expect([btn.disabled, btn.hasAttribute("title"), btn.hasAttribute("data-oi-wired")]).toEqual([false, false, true]);
    const panel = d.querySelector<HTMLElement>(PANEL)!;
    expect(panel.style.display).toBe("none");
    expect(panel.nextElementSibling?.contains(bio(d))).toBe(true);
    for (const id of ["icon-bold", "icon-italic", "icon-text-colour", "icon-clear-format"]) expect(d.getElementById(id), id).not.toBeNull();
    expect(btn.getAttribute("aria-expanded")).toBe("false");
    btn.click();
    expect([panel.style.display, btn.getAttribute("aria-expanded")]).toEqual(["", "true"]);
    expect(noteOf(d)).toBeNull();
    tool(d, "Close Formatting Panel").click();
    expect(panel.style.display).toBe("none");
    btn.click();
    btn.click();
    expect(panel.style.display).toBe("none");
    unbind();
    expect(d.querySelector(PANEL)).toBeNull();
    expect(d.getElementById("icon-bold")).toBeNull();
  });

  it("Bold on a selection leaves OF's markup; Save sends it as `about` with no other request", async () => {
    const d = load();
    const h = handlers();
    const unbind = bindWrites(d, PAGE, h, true);
    d.querySelector<HTMLButtonElement>(ABOUT_FORMAT)!.click();
    expect(save(d).disabled).toBe(true);
    select(d, 0, 7);
    tool(d, "Bold").click();
    expect(bio(d).innerHTML).toBe("<p><strong>Welcome</strong> to my page.</p>");
    expect(save(d).disabled).toBe(false);
    expect(h.saveProfile).not.toHaveBeenCalled();
    save(d).click();
    await flush();
    expect(h.saveProfile).toHaveBeenCalledExactlyOnceWith({ about: "<p><strong>Welcome</strong> to my page.</p>" });
    expect(d.querySelector(".g-notification, [role='alert']")?.textContent ?? SAVED_TOAST).toContain(SAVED_TOAST);
    unbind();
  });

  it("an empty selection changes nothing and says so", () => {
    const d = load();
    const h = handlers();
    const unbind = bindWrites(d, PAGE, h, true);
    const before = bio(d).innerHTML;
    d.querySelector<HTMLButtonElement>(ABOUT_FORMAT)!.click();
    tool(d, "Bold").click();
    expect([bio(d).innerHTML, noteOf(d), save(d).disabled]).toEqual([before, "Select some text to format", true]);
    unbind();
  });

  it("a failed Save keeps the formatted Bio and shows the red note", async () => {
    const d = load();
    const h = { ...handlers(), saveProfile: vi.fn(() => Promise.reject(new Error("relay 502"))) };
    const unbind = bindWrites(d, PAGE, h, true);
    select(d, 0, 7);
    tool(d, "Bold").click();
    save(d).click();
    await flush();
    const n = d.getElementById("oi-note")!;
    expect([n.textContent, n.style.color, save(d).disabled]).toEqual(["Could not save: relay 502", "rgb(255, 69, 69)", false]);
    expect(bio(d).innerHTML).toBe("<p><strong>Welcome</strong> to my page.</p>");
    unbind();
  });

  it("no single model: a tool sends nothing and says to select a model", () => {
    const d = load();
    const unbind = bindWrites(d, PAGE, null, true);
    const before = bio(d).innerHTML;
    d.querySelector<HTMLButtonElement>(ABOUT_FORMAT)!.click();
    select(d, 0, 7);
    tool(d, "Bold").click();
    expect([bio(d).innerHTML, noteOf(d)]).toEqual([before, SELECT_MODEL]);
    unbind();
  });

  it("a formatted bio read back shows formatted in the Bio (identity), through the allow-list", () => {
    const d = load();
    applyIdentity(d, { id: 1, username: "alphaone", name: "Alpha", about: '<p><strong>Hi</strong> <img src=x onerror=alert(1)>there</p>' } as never);
    expect(bio(d).innerHTML).toBe("<p><strong>Hi</strong> there</p>");
    applyIdentity(d, { id: 1, username: "alphaone", name: "Alpha", about: "<p>Plain bio</p>" } as never);
    expect(bio(d).textContent).toContain("Hi");
  });
});
