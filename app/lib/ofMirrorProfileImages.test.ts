import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  AVATAR_CAMERA_NAME,
  COVER_PLACEHOLDER, IMAGE_SIZE_NOTE, IMAGE_TYPE_NOTE, PROFILE_CAMERA, PROFILE_IMAGE_MAX, PROFILE_REMOVE,
  profileImagePatch, profileImageProblem,
} from "./ofMirrorProfileImages";
import { bindWrites, NOT_YET, SAVED_TOAST, SELECT_MODEL } from "./ofMirrorWrites";

const PAGE = "settings/profile";
const ITEM = { processId: "p1", host: "convert", name: "cover.png", thumbId: 7 };
const load = () => {
  document.documentElement.innerHTML = readFileSync(resolve(__dirname, `../public/of-mirror/pages/${PAGE}.html`), "utf8");
  return document;
};
const handlers = () => ({
  saveProfile: vi.fn((_body: unknown) => Promise.resolve()),
  uploadProfileImage: vi.fn((_kind: string, _file: File) => Promise.resolve(ITEM)),
  setReplyOnSubscribe: vi.fn(() => Promise.resolve()),
  submit: vi.fn(() => Promise.resolve({})),
  navigate: vi.fn(),
});
const flush = () => new Promise((r) => setTimeout(r, 0));
const png = (size = 8, type = "image/png", name = "cover.png") => new File([new Uint8Array(size)], name, { type });
const pick = (d: Document, kind: "header" | "avatar", file: File) => {
  const input = d.querySelector<HTMLInputElement>(`input[data-oi-profile-file='${kind}']`)!;
  Object.defineProperty(input, "files", { value: [file], configurable: true });
  input.dispatchEvent(new Event("change", { bubbles: true }));
};
const cover = (d: Document) => d.querySelector<HTMLImageElement>("img.b-profile__header__cover-img")!;
const save = (d: Document) => d.querySelector<HTMLButtonElement>(".g-btn__wrapper button[type='submit']")!;

beforeEach(() => {
  URL.createObjectURL = vi.fn(() => "blob:picked");
  URL.revokeObjectURL = vi.fn();
});
afterEach(() => vi.restoreAllMocks());

describe("profileImageProblem", () => {
  it.each([
    ["png", { type: "image/png", size: 10 }, null],
    ["jpeg", { type: "image/jpeg", size: 10 }, null],
    ["gif", { type: "image/gif", size: 10 }, null],
    ["webp at the cap", { type: "image/webp", size: PROFILE_IMAGE_MAX }, null],
    ["over the cap", { type: "image/png", size: PROFILE_IMAGE_MAX + 1 }, IMAGE_SIZE_NOTE],
    ["svg", { type: "image/svg+xml", size: 10 }, IMAGE_TYPE_NOTE],
    ["text", { type: "text/plain", size: 10 }, IMAGE_TYPE_NOTE],
    ["no type", { type: "", size: 10 }, IMAGE_TYPE_NOTE],
  ])("%s", (_name, file, want) => expect(profileImageProblem(file)).toBe(want));
});

describe("profileImagePatch", () => {
  it.each([
    ["nothing staged", {}, {}, []],
    ["cover removed", { header: "remove" as const }, { header: "" }, []],
    ["cover picked, avatar removed", { header: png(), avatar: "remove" as const }, { header: ITEM, avatar: "" }, ["header"]],
    ["both picked", { avatar: png(), header: png() }, { header: ITEM, avatar: ITEM }, ["header", "avatar"]],
  ])("%s", async (_name, staged, want, uploads) => {
    const up = vi.fn((_k: string, _f: File) => Promise.resolve(ITEM));
    expect(await profileImagePatch(staged, up)).toEqual(want);
    expect(up.mock.calls.map((c) => c[0])).toEqual(uploads);
  });
});

describe("Edit profile's cover and avatar (ticket 67)", () => {
  it("makes the cameras and the cover's remove usable and Wired; only the cover's camera (Live pass) drops its title (D1)", () => {
    const d = load();
    const unbind = bindWrites(d, PAGE, handlers(), true);
    const state = (sel: string) => {
      const b = d.querySelector<HTMLButtonElement>(sel)!;
      return [b.disabled, b.hasAttribute("data-oi-wired"), b.getAttribute("title"), b.getAttribute("aria-label")];
    };
    expect(state(PROFILE_CAMERA.header)).toEqual([false, true, null, null]);
    expect(state(PROFILE_CAMERA.avatar)).toEqual([false, true, NOT_YET, AVATAR_CAMERA_NAME]);
    expect(state(PROFILE_REMOVE.header)).toEqual([false, true, NOT_YET, null]);
    unbind();
    expect(d.querySelector("input[data-oi-profile-file]")).toBeNull();
    expect(d.querySelector(PROFILE_CAMERA.header)!.getAttribute("title")).toBe(NOT_YET);
    expect(d.querySelector(PROFILE_CAMERA.avatar)!.hasAttribute("aria-label")).toBe(false);
  });

  it("a camera opens its file picker; the picked cover shows and Save uploads it, then sends the item", async () => {
    const d = load();
    const h = handlers();
    const unbind = bindWrites(d, PAGE, h, true);
    const input = d.querySelector<HTMLInputElement>("input[data-oi-profile-file='header']")!;
    const opened = vi.spyOn(input, "click");
    d.querySelector<HTMLButtonElement>(PROFILE_CAMERA.header)!.click();
    expect(opened).toHaveBeenCalledOnce();
    expect(d.getElementById("oi-note")).toBeNull();
    const file = png();
    pick(d, "header", file);
    expect(cover(d).src).toBe("blob:picked");
    expect(save(d).disabled).toBe(false);
    save(d).click();
    await flush();
    expect(h.uploadProfileImage).toHaveBeenCalledWith("header", file);
    expect(h.saveProfile).toHaveBeenCalledWith({ header: ITEM });
    expect(d.querySelector("#oi-toast .toast__text")?.textContent).toBe(SAVED_TOAST);
    expect(cover(d).src).toBe("blob:picked");
    unbind();
  });

  it("the picked avatar shows in the avatar and goes as `avatar`", async () => {
    const d = load();
    const h = handlers();
    const unbind = bindWrites(d, PAGE, h, true);
    pick(d, "avatar", png());
    expect(d.querySelector<HTMLImageElement>(".b-profile__user .g-avatar img[data-oi-avatar]")?.src).toBe("blob:picked");
    save(d).click();
    await flush();
    expect(h.saveProfile).toHaveBeenCalledWith({ avatar: ITEM });
    unbind();
  });

  it("the cover's remove shows OF's empty cover and Save sends header \"\" (no upload)", async () => {
    const d = load();
    cover(d).src = "https://example.invalid/cover.png";
    const h = handlers();
    const unbind = bindWrites(d, PAGE, h, true);
    const remove = d.querySelector<HTMLButtonElement>(PROFILE_REMOVE.header)!;
    remove.click();
    expect([cover(d).src, remove.hidden]).toEqual([COVER_PLACEHOLDER, true]);
    save(d).click();
    await flush();
    expect(h.uploadProfileImage).not.toHaveBeenCalled();
    expect(h.saveProfile).toHaveBeenCalledWith({ header: "" });
    unbind();
  });

  it("the avatar's remove, drawn by identity after the bind, is usable and sends avatar \"\"", async () => {
    const d = load();
    const h = handlers();
    const unbind = bindWrites(d, PAGE, h, true);
    const x = d.querySelector(PROFILE_REMOVE.header)!.cloneNode(true) as HTMLButtonElement;
    x.disabled = true;
    x.setAttribute("data-oi-avatar-remove", "");
    d.querySelector(".b-profile__user .g-avatar .b-profile__header__cover__btns")!.append(x);
    await flush();
    expect([x.disabled, x.title]).toEqual([false, NOT_YET]);
    x.click();
    save(d).click();
    await flush();
    expect(h.saveProfile).toHaveBeenCalledWith({ avatar: "" });
    unbind();
  });

  it("a pick after a removal shows the remove again; a failed Save puts it back as it was", async () => {
    const d = load();
    const h = { ...handlers(), saveProfile: vi.fn(() => Promise.reject(new Error("relay 502"))) };
    const unbind = bindWrites(d, PAGE, h, true);
    const remove = d.querySelector<HTMLButtonElement>(PROFILE_REMOVE.header)!;
    remove.click();
    pick(d, "header", png());
    expect(remove.hidden).toBe(false);
    remove.click();
    save(d).click();
    await flush();
    expect(h.saveProfile).toHaveBeenCalledWith({ header: "" });
    expect(remove.hidden).toBe(false);
    unbind();
  });

  it("text edits and a picked cover go in one Save", async () => {
    const d = load();
    const h = handlers();
    const unbind = bindWrites(d, PAGE, h, true);
    const name = d.querySelector<HTMLInputElement>("#input-name")!;
    name.value = "New name";
    name.dispatchEvent(new Event("input", { bubbles: true }));
    pick(d, "header", png());
    save(d).click();
    await flush();
    expect(h.saveProfile).toHaveBeenCalledWith({ name: "New name", header: ITEM });
    unbind();
  });

  it.each([
    ["a failed upload", { uploadProfileImage: vi.fn(() => Promise.reject(new Error("relay 502"))) }, false],
    ["a failed profile write", { saveProfile: vi.fn(() => Promise.reject(new Error("relay 502"))) }, true],
  ])("%s: the red note, the cover back as saved", async (_name, over, uploaded) => {
    const d = load();
    const before = cover(d).src;
    const h = { ...handlers(), ...over };
    const unbind = bindWrites(d, PAGE, h, true);
    pick(d, "header", png());
    save(d).click();
    await flush();
    expect(cover(d).src).toBe(before);
    const n = d.getElementById("oi-note")!;
    expect([n.textContent, n.style.color]).toEqual(["Could not save: relay 502", "rgb(255, 69, 69)"]);
    expect(save(d).disabled).toBe(false);
    if (!uploaded) expect(h.saveProfile).not.toHaveBeenCalled();
    unbind();
  });

  it.each([
    ["a text file", png(8, "text/plain", "notes.txt"), IMAGE_TYPE_NOTE],
    ["an svg", png(8, "image/svg+xml", "x.svg"), IMAGE_TYPE_NOTE],
    ["an oversize png", png(PROFILE_IMAGE_MAX + 1), IMAGE_SIZE_NOTE],
  ])("%s is refused before any request (nothing staged)", (_name, file, text) => {
    const d = load();
    const before = cover(d).src;
    const h = handlers();
    const unbind = bindWrites(d, PAGE, h, true);
    pick(d, "header", file);
    const n = d.getElementById("oi-note")!;
    expect([n.textContent, n.style.color]).toEqual([text, "rgb(255, 69, 69)"]);
    expect(cover(d).src).toBe(before);
    expect(save(d).disabled).toBe(true);
    save(d).click();
    expect(h.uploadProfileImage).not.toHaveBeenCalled();
    expect(h.saveProfile).not.toHaveBeenCalled();
    unbind();
  });

  it("no single model: a camera or remove sends nothing and says to select a model", () => {
    const d = load();
    const unbind = bindWrites(d, PAGE, null, true);
    const input = d.querySelector<HTMLInputElement>("input[data-oi-profile-file='header']")!;
    const opened = vi.spyOn(input, "click");
    for (const sel of [PROFILE_CAMERA.header, PROFILE_REMOVE.header]) {
      d.querySelector<HTMLButtonElement>(sel)!.click();
      expect(d.getElementById("oi-note")?.textContent, sel).toBe(SELECT_MODEL);
    }
    expect(opened).not.toHaveBeenCalled();
    expect(cover(d).src).not.toBe("blob:picked");
    unbind();
  });
});
