/** ticket 84: the stream schedule form's right column search (streaming/dashboard/create), against the real page. */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import { bindFeedSearch } from "./ofMirrorPost";
import { PAGE } from "./ofMirrorScheduleSearch";
import { bindWrites, localIso, NOT_YET, SELECT_MODEL } from "./ofMirrorWrites";
import { relay } from "./relay";

const loadPage = () => {
  document.documentElement.innerHTML = readFileSync(resolve(__dirname, `../public/of-mirror/pages/${PAGE}.html`), "utf8");
  return document;
};
const flush = () => new Promise((r) => setTimeout(r, 0));
const box = (d: Document) => d.querySelector<HTMLInputElement>("input[name='feed-search-input']")!;
const button = (d: Document) => d.querySelector<HTMLButtonElement>("button.m-search-btn")!;
const writes = () => ({ uploadProfileImage: vi.fn(), saveProfile: vi.fn(), setReplyOnSubscribe: vi.fn(), submit: vi.fn(() => Promise.resolve({ id: 1 })), navigate: vi.fn() });
const search = () => ({
  searchUsers: vi.fn(() => Promise.resolve([{ id: 5001, name: "Synthetic Fan", username: "fan1" }] as never)),
  searchPosts: vi.fn(() => Promise.resolve({ list: [{ id: 6001, text: "<p>Hello</p>", author: { id: 77, username: "yourmodel" } }] } as never)),
});
/** A valid schedule form (two days ahead, 18:30): a stray send from the search would go through. */
const fillDate = (d: Document) => {
  const day = localIso(new Date(Date.now() + 2 * 86_400_000)).slice(0, 10);
  d.querySelector<HTMLInputElement>("input[name='date']")!.value = day;
  d.querySelector<HTMLInputElement>("input[name='time']")!.value = "18:30";
};
const type = async (d: Document, text: string) => {
  box(d).value = text;
  box(d).dispatchEvent(new Event("input", { bubbles: true }));
  await vi.advanceTimersByTimeAsync(400);
};
const unbinds: (() => void)[] = [];
afterEach(() => {
  unbinds.splice(0).forEach((u) => u());
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("schedule form's search (ticket 84)", () => {
  it("the box is on and the Search button off until typed in, both Wired with the Not-yet title kept (D1)", () => {
    const d = loadPage();
    unbinds.push(bindFeedSearch(d, { handlers: search() }));
    const state = (e: HTMLInputElement | HTMLButtonElement) => [e.disabled, e.title, e.hasAttribute("data-oi-wired")];
    expect([state(box(d)), state(button(d))]).toEqual([[false, NOT_YET, true], [true, NOT_YET, true]]);
  });

  it("typing lists users and posts with Home's links; Enter and the Search button, a valid date filled, send no POST /streams", async () => {
    vi.useFakeTimers();
    const d = loadPage();
    const w = writes();
    const h = search();
    unbinds.push(bindWrites(d, PAGE, w, false), bindFeedSearch(d, { handlers: h, meId: 77 }));
    fillDate(d);
    await type(d, "syn");
    vi.useRealTimers();
    await flush();
    expect([h.searchUsers.mock.calls, h.searchPosts.mock.calls]).toEqual([[["syn"]], [["syn"]]]);
    const links = () => [...d.querySelectorAll<HTMLAnchorElement>("#oi-search-results a")].map((a) => [a.textContent, a.getAttribute("href"), a.getAttribute("target")]);
    expect(links()).toEqual([
      ["Synthetic Fan @fan1", "https://onlyfans.com/fan1", "_blank"],
      ["Hello · @yourmodel", "/of-manager/profile", "_top"],
    ]);
    expect(button(d).disabled).toBe(false);
    box(d).form!.requestSubmit(); // Enter in the box
    button(d).click(); // the Search button
    await flush();
    expect(h.searchUsers).toHaveBeenCalledTimes(3); // each ran the search at once
    expect(links()).toHaveLength(2);
    expect(w.submit).not.toHaveBeenCalled();
    expect(w.navigate).not.toHaveBeenCalled();
    expect(d.getElementById("oi-note")).toBeNull();
  });

  it("clearing the box drops the list at once; a search still out never redraws under the empty box", async () => {
    vi.useFakeTimers();
    const d = loadPage();
    let answer = (_v: unknown) => {};
    const h = { ...search(), searchUsers: vi.fn(() => new Promise((r) => { answer = r; }) as never) };
    unbinds.push(bindFeedSearch(d, { handlers: h }));
    await type(d, "syn");                                  // the search is out
    box(d).value = "";
    box(d).dispatchEvent(new Event("input", { bubbles: true }));   // cleared: no debounce wait
    answer([{ id: 5001, name: "Synthetic Fan", username: "fan1" }]);
    vi.useRealTimers();
    await flush();
    expect(d.getElementById("oi-search-results")).toBeNull();
  });

  it("a search still out when the page unbinds never draws afterwards", async () => {
    vi.useFakeTimers();
    const d = loadPage();
    let answer = (_v: unknown) => {};
    const h = { ...search(), searchUsers: vi.fn(() => new Promise((r) => { answer = r; }) as never) };
    const unbind = bindFeedSearch(d, { handlers: h });
    await type(d, "syn");
    unbind();
    answer([{ id: 5001, name: "Synthetic Fan", username: "fan1" }]);
    vi.useRealTimers();
    await flush();
    expect(d.getElementById("oi-search-results")).toBeNull();
  });

  it("All-Creators: typing, Enter and Search give the Select-model note and no search GET", async () => {
    vi.useFakeTimers();
    const get = vi.spyOn(relay, "get");
    const d = loadPage();
    unbinds.push(bindWrites(d, PAGE, null, false), bindFeedSearch(d, { handlers: null }));
    fillDate(d);
    await type(d, "syn");
    expect(d.getElementById("oi-note")?.textContent).toBe(SELECT_MODEL);
    box(d).form!.requestSubmit();
    button(d).click();
    expect(d.getElementById("oi-note")?.textContent).toBe(SELECT_MODEL);
    expect(get).not.toHaveBeenCalled();
    expect(d.getElementById("oi-search-results")).toBeNull();
  });
});
