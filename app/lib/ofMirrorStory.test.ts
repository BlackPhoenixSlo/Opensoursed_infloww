import { readdirSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { bindStory } from "./ofMirrorPost";
import { bindWrites, READ_ONLY, SELECT_MODEL } from "./ofMirrorWrites";

const flush = () => new Promise((r) => setTimeout(r, 0));

describe("Add to story (story strip)", () => {
  const PAGES = resolve(__dirname, "../public/of-mirror/pages");
  const html = (page: string) => readFileSync(resolve(PAGES, `${page}.html`), "utf8");
  const OWN = ".b-story-item.m-story-item-own";
  const PICKER = "input[type=file][accept='image/*,video/*']";
  /** Every committed Mirror page (path under pages/, no .html) whose story strip carries the own tile. */
  const ownPages = (readdirSync(PAGES, { recursive: true }) as string[])
    .filter((f) => f.endsWith(".html"))
    .map((f) => f.slice(0, -".html".length))
    .filter((page) => new DOMParser().parseFromString(html(page), "text/html").querySelector(OWN))
    .sort();
  const load = (page: string) => {
    document.documentElement.innerHTML = html(page);
    return document;
  };
  const png = () => new File([new Uint8Array([137, 80, 78, 71])], "synthetic.png", { type: "image/png" });
  /**
   * Hand the hidden picker `files` and its browser-set `value` ("C:\\fakepath\\<name>"; jsdom refuses to set a file
   * input's value, so it is a plain writable property here), then fire its change, as the browser does after a pick.
   */
  const pick = (input: HTMLInputElement, files: File[]) => {
    Object.defineProperty(input, "files", { value: files, configurable: true });
    Object.defineProperty(input, "value", { value: files.length ? `C:\\fakepath\\${files[0].name}` : "", writable: true, configurable: true });
    input.dispatchEvent(new Event("change"));
  };
  /** A spy on every input's click(), so jsdom opens no picker. */
  const spyOpen = () => vi.spyOn(HTMLInputElement.prototype, "click").mockImplementation(() => {});
  let opened: ReturnType<typeof spyOpen>;
  beforeEach(() => {
    opened = spyOpen();
  });
  afterEach(() => {
    opened.mockRestore();
    vi.useRealTimers();
  });

  it("the glob finds the own tile on home index and its 11 States, and new-post index and its 12 States", () => {
    expect(ownPages).toEqual([
      "home/index",
      "home/state-avatar-menu",
      "home/state-expiration",
      "home/state-feed-tabs-edit",
      "home/state-format-text",
      "home/state-poll",
      "home/state-promotion",
      "home/state-quiz",
      "home/state-schedule",
      "home/state-tag-people",
      "home/state-target",
      "home/state-vault",
      "new-post/index",
      "new-post/state-expiration",
      "new-post/state-format-text",
      "new-post/state-labels",
      "new-post/state-poll",
      "new-post/state-price",
      "new-post/state-promotion",
      "new-post/state-quiz",
      "new-post/state-schedule",
      "new-post/state-tag-people",
      "new-post/state-target",
      "new-post/state-trial-link",
      "new-post/state-vault",
    ]);
  });

  it.each(ownPages)("%s: the own tile opens the image picker; a picked image goes to addStory once, then 'Added to story' under the strip", async (page) => {
    const d = load(page);
    const addStory = vi.fn((_file: File) => Promise.resolve({}));
    const unbind = bindStory(d, { addStory });
    const pickers = d.querySelectorAll<HTMLInputElement>(PICKER);
    expect(pickers).toHaveLength(1);
    const own = d.querySelector<HTMLButtonElement>(OWN)!;
    own.click();
    expect(opened).toHaveBeenCalledTimes(1);
    expect(opened.mock.contexts[0]).toBe(pickers[0]);
    const file = png();
    pick(pickers[0], [file]);
    expect(addStory).toHaveBeenCalledTimes(1);
    expect(addStory).toHaveBeenCalledWith(file);
    await flush();
    const shown = d.getElementById("oi-note");
    expect(shown?.textContent).toBe("Added to story");
    expect(shown?.previousElementSibling).toBe(own.closest(".stories-list"));
    unbind();
  });

  /** A promise and the hooks to settle it, so a test can look at the page while addStory is in flight. */
  const pending = () => {
    let resolve!: (v: unknown) => void;
    let reject!: (e: unknown) => void;
    const promise = new Promise<unknown>((res, rej) => {
      resolve = res;
      reject = rej;
    });
    return { promise, resolve, reject };
  };

  it("the tile is disabled until addStory settles; a click on it meanwhile opens no picker; a stale note is cleared", async () => {
    const d = load("home/index");
    const call = pending();
    const addStory = vi.fn((_file: File) => call.promise);
    const unbind = bindStory(d, { addStory });
    const own = d.querySelector<HTMLButtonElement>(OWN)!;
    const input = d.querySelector<HTMLInputElement>(PICKER)!;
    own.click();
    expect(opened).toHaveBeenCalledTimes(1);
    const stale = d.createElement("div");
    stale.id = "oi-note";
    stale.textContent = "Could not add: earlier failure";
    own.closest(".stories-list")!.after(stale);
    pick(input, [png()]);
    expect(own.disabled).toBe(true);
    expect(d.getElementById("oi-note")).toBeNull();
    own.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
    expect(opened).toHaveBeenCalledTimes(1);
    call.resolve({});
    await flush();
    expect(own.disabled).toBe(false);
    expect(d.getElementById("oi-note")?.textContent).toBe("Added to story");
    own.click();
    expect(opened).toHaveBeenCalledTimes(2);
    unbind();
  });

  it("a rejected addStory shows a red 'Could not add: <message>' that stays, and re-enables the tile", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    const d = load("new-post/index");
    const call = pending();
    const unbind = bindStory(d, { addStory: vi.fn((_file: File) => call.promise) });
    const own = d.querySelector<HTMLButtonElement>(OWN)!;
    pick(d.querySelector<HTMLInputElement>(PICKER)!, [png()]);
    expect(own.disabled).toBe(true);
    call.reject(new Error("synthetic failure"));
    await vi.advanceTimersByTimeAsync(0);
    const shown = d.getElementById("oi-note")!;
    expect(shown.textContent).toBe("Could not add: synthetic failure");
    expect(shown.style.color).toBe("rgb(255, 69, 69)");
    expect(own.disabled).toBe(false);
    await vi.advanceTimersByTimeAsync(10_000);
    expect(d.getElementById("oi-note")?.textContent).toBe("Could not add: synthetic failure");
    unbind();
  });

  it.each([
    ["resolved", () => Promise.resolve({})],
    ["rejected", () => Promise.reject(new Error("synthetic failure"))],
  ])("after a %s addStory the picker is reset, and the same file picked again uploads again", async (_how, settle) => {
    const d = load("home/index");
    const addStory = vi.fn((_file: File) => settle());
    const unbind = bindStory(d, { addStory });
    const input = d.querySelector<HTMLInputElement>(PICKER)!;
    const file = png();
    pick(input, [file]);
    await flush();
    expect(input.value).toBe("");
    pick(input, [file]);
    await flush();
    expect(addStory).toHaveBeenCalledTimes(2);
    expect(addStory.mock.calls).toEqual([[file], [file]]);
    expect(input.value).toBe("");
    unbind();
  });

  it.each([
    ["a text/plain file", "notes.txt", "text/plain"],
    ["a file with an empty type", "unknown", ""],
  ])("%s calls nothing and shows the red 'Could not add: choose an image or a video' note", (_what, name, type) => {
    const d = load("home/index");
    const addStory = vi.fn((_file: File) => Promise.resolve({}));
    const unbind = bindStory(d, { addStory });
    const own = d.querySelector<HTMLButtonElement>(OWN)!;
    pick(d.querySelector<HTMLInputElement>(PICKER)!, [new File(["synthetic"], name, { type })]);
    expect(addStory).not.toHaveBeenCalled();
    expect(own.disabled).toBe(false);
    const shown = d.getElementById("oi-note")!;
    expect(shown.textContent).toBe("Could not add: choose an image or a video");
    expect(shown.style.color).toBe("rgb(255, 69, 69)");
    expect(shown.previousElementSibling).toBe(own.closest(".stories-list"));
    unbind();
  });

  it("a change with an empty file list (a cancelled picker) calls nothing and adds no note", async () => {
    const d = load("new-post/index");
    const addStory = vi.fn((_file: File) => Promise.resolve({}));
    const unbind = bindStory(d, { addStory });
    d.querySelector<HTMLButtonElement>(OWN)!.click();
    pick(d.querySelector<HTMLInputElement>(PICKER)!, []);
    await flush();
    expect(addStory).not.toHaveBeenCalled();
    expect(d.getElementById("oi-note")).toBeNull();
    expect(d.querySelector<HTMLButtonElement>(OWN)!.disabled).toBe(false);
    unbind();
  });

  it.each(["home/index", "new-post/index"])("%s, All-Creators scope (null handlers): the own tile shows the grey SELECT_MODEL note under the strip and never clicks the picker", (page) => {
    const d = load(page);
    const unbind = bindStory(d, null);
    const own = d.querySelector<HTMLButtonElement>(OWN)!;
    const click = new MouseEvent("click", { bubbles: true, cancelable: true });
    own.dispatchEvent(click);
    expect(click.defaultPrevented).toBe(true);
    expect(opened).not.toHaveBeenCalled();
    const shown = d.getElementById("oi-note")!;
    expect(shown.textContent).toBe(SELECT_MODEL);
    expect(shown.style.color).toBe("rgb(138, 150, 163)");
    expect(shown.previousElementSibling).toBe(own.closest(".stories-list"));
    expect(own.disabled).toBe(false);
    unbind();
  });

  it("switching scope rebinds: after unbinding the All-Creators binding and binding with handlers, the tile opens the picker and uploads", async () => {
    const d = load("home/index");
    const unbindAll = bindStory(d, null);
    d.querySelector<HTMLButtonElement>(OWN)!.click();
    expect(d.getElementById("oi-note")?.textContent).toBe(SELECT_MODEL);
    unbindAll();
    const addStory = vi.fn((_file: File) => Promise.resolve({}));
    const unbind = bindStory(d, { addStory });
    const pickers = d.querySelectorAll<HTMLInputElement>(PICKER);
    expect(pickers).toHaveLength(1);
    d.querySelector<HTMLButtonElement>(OWN)!.click();
    expect(opened).toHaveBeenCalledTimes(1);
    expect(opened.mock.contexts[0]).toBe(pickers[0]);
    const file = png();
    pick(pickers[0], [file]);
    expect(addStory.mock.calls).toEqual([[file]]);
    await flush();
    expect(d.getElementById("oi-note")?.textContent).toBe("Added to story");
    unbind();
  });

  it("All-Creators scope (handlers null): the own tile and the hidden picker carry data-oi-wired too", () => {
    const d = load("home/index");
    const unbind = bindStory(d, null);
    expect([...d.querySelectorAll("[data-oi-wired]")]).toEqual([d.querySelector(OWN), d.querySelector(PICKER)]);
    unbind();
  });

  it("the own tile and the hidden picker, and only those, carry data-oi-wired", () => {
    const d = load("home/index");
    const unbind = bindStory(d, { addStory: vi.fn() });
    expect([...d.querySelectorAll("[data-oi-wired]")]).toEqual([d.querySelector(OWN), d.querySelector(PICKER)]);
    unbind();
  });

  /** The strip's tiles other than "Add to story", as the reader sees them (label, or "fan story" for a fan's tile). */
  const others = (d: Document) => [...d.querySelectorAll<HTMLButtonElement>(".b-story-item:not(.m-story-item-own)")];
  const label = (tile: Element) => (tile.matches("[at-attr=story_item]") ? "fan story" : tile.querySelector(".b-story-item__text")!.textContent!.trim());

  it.each([
    ["home/index", ["Start profile promotion"]],
    ["new-post/index", ["Go live", "Send message", "Start profile promotion", "Create new trial link"]],
    ["profile/index", ["Story archive", "Create highlight", "Go live"]],
  ])("%s carries these non-own tiles", (page, want) => {
    expect(others(load(page)).map(label)).toEqual(want);
  });

  it("home/index: Start profile promotion links to the promotion campaign dialog over Home, and the strip lets it go", () => {
    const d = load("home/index");
    const unbind = bindStory(d, { addStory: vi.fn() });
    const [tile] = others(d);
    expect(tile.closest("a")?.getAttribute("href")).toBe("/of-manager/home/state-promotion");
    expect(tile.matches(":disabled")).toBe(false);
    const click = new MouseEvent("click", { bubbles: true, cancelable: true });
    tile.dispatchEvent(click);
    expect(click.defaultPrevented).toBe(false);
    expect(d.getElementById("oi-note")).toBeNull();
    unbind();
  });

  it("new-post/index: Go live, Send message, Start profile promotion and Create new trial link are links to their OF Manager pages (the strip lets them go)", () => {
    const d = load("new-post/index");
    const unbind = bindStory(d, { addStory: vi.fn() });
    const tiles = others(d);
    expect(tiles.map((t) => t.closest("a")?.getAttribute("href"))).toEqual([
      "/of-manager/streaming",
      "/of-manager/messages/send",
      "/of-manager/new-post/state-promotion",
      "/of-manager/new-post/state-trial-link",
    ]);
    for (const tile of tiles) {
      const click = new MouseEvent("click", { bubbles: true, cancelable: true });
      tile.dispatchEvent(click);
      expect(click.defaultPrevented, label(tile)).toBe(false);
    }
    expect(d.getElementById("oi-note")).toBeNull();
    unbind();
  });

  describe.each([
    ["Single-Creator", true],
    ["All-Creators", false],
  ])("%s scope", (_scope, single) => {
    it("profile/index: Story archive is left to its binder (data-oi-wired: ofMirrorProfile), Create highlight is disabled quietly with the tooltip, Go live links to Go live; no tile gets the READ_ONLY note", () => {
      const d = load("profile/index");
      const addStory = vi.fn((_file: File) => Promise.resolve({}));
      const unbind = bindStory(d, single ? { addStory } : null);
      const unbindWrites = bindWrites(d, "profile/index", null);
      const [archive, create, live] = others(d);
      expect(archive.hasAttribute("data-oi-wired")).toBe(true);
      expect(create.disabled).toBe(true);
      expect(create.title).toBe("Not available in Inflowwww yet");
      expect(live.closest("a")?.getAttribute("href")).toBe("/of-manager/streaming");
      for (const tile of [archive, create, live]) {
        const click = new MouseEvent("click", { bubbles: true, cancelable: true });
        tile.dispatchEvent(click);
        expect(click.defaultPrevented, label(tile)).toBe(false);
        expect(d.getElementById("oi-note"), label(tile)).toBeNull();
      }
      expect(addStory).not.toHaveBeenCalled();
      expect(opened).not.toHaveBeenCalled();
      unbind();
      unbindWrites();
    });
  });

  it("profile/index has no Add to story: binding adds no picker and marks nothing, and no tile clicks a file input", () => {
    const d = load("profile/index");
    const addStory = vi.fn((_file: File) => Promise.resolve({}));
    const wired = [...d.querySelectorAll("[data-oi-wired]")]; // the generator's (My profile's own controls)
    const unbind = bindStory(d, { addStory });
    expect(d.querySelectorAll("input[type=file]")).toHaveLength(0);
    expect([...d.querySelectorAll("[data-oi-wired]")]).toEqual(wired);
    for (const tile of d.querySelectorAll<HTMLButtonElement>(".b-story-item")) tile.click();
    expect(opened).not.toHaveBeenCalled();
    expect(addStory).not.toHaveBeenCalled();
    unbind();
  });

  it("unbind removes the read-only listener: a non-own tile then shows no note", () => {
    const d = load("profile/index");
    bindStory(d, { addStory: vi.fn() })();
    others(d)[1].click();
    expect(d.getElementById("oi-note")).toBeNull();
  });

  it("unbind removes the hidden picker and the listeners", () => {
    const d = load("new-post/index");
    const addStory = vi.fn((_file: File) => Promise.resolve({}));
    const unbind = bindStory(d, { addStory });
    const input = d.querySelector<HTMLInputElement>(PICKER)!;
    unbind();
    expect(d.querySelectorAll("input[type=file]")).toHaveLength(0);
    d.querySelector<HTMLButtonElement>(OWN)!.click();
    pick(input, [png()]);
    expect(opened).not.toHaveBeenCalled();
    expect(addStory).not.toHaveBeenCalled();
    expect(d.getElementById("oi-note")).toBeNull();
  });
});
