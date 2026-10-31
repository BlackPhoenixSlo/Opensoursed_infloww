import { afterEach, describe, expect, it, vi } from "vitest";

import { QUICK_EMOJIS } from "./emojiData";
import { LS_RECENTS_KEY, buildQuickRow, loadRecents, pushRecent, subscribeRecents } from "./emojiRecents";

afterEach(() => window.localStorage.clear());

describe("loadRecents", () => {
  it.each<[string, string | null, string[]]>([
    ["nothing stored", null, []],
    ["corrupt JSON", "{not json", []],
    ["a non-array", JSON.stringify({ a: "😀" }), []],
    ["non-strings filtered", JSON.stringify(["😀", 3, null, "🔥", {}]), ["😀", "🔥"]],
  ])("%s", (_, raw, want) => {
    if (raw !== null) window.localStorage.setItem(LS_RECENTS_KEY, raw);
    expect(loadRecents()).toEqual(want);
  });

  it("caps at 24", () => {
    window.localStorage.setItem(LS_RECENTS_KEY, JSON.stringify(Array.from({ length: 30 }, (_, i) => `e${i}`)));
    expect(loadRecents()).toHaveLength(24);
  });
});

describe("pushRecent", () => {
  it("puts the pick first and dedupes it", () => {
    pushRecent("😀");
    pushRecent("🔥");
    pushRecent("😀");
    expect(loadRecents()).toEqual(["😀", "🔥"]);
  });

  it("drops the oldest past 24", () => {
    for (let i = 0; i < 30; i++) pushRecent(`e${i}`);
    const got = loadRecents();
    expect(got).toHaveLength(24);
    expect(got[0]).toBe("e29");
    expect(got[23]).toBe("e6");
  });
});

describe("subscribeRecents", () => {
  it("fires on a pick, the pulse event and a cross-tab storage event; unsubscribe stops it", () => {
    const seen = vi.fn();
    const unsubscribe = subscribeRecents(seen);
    pushRecent("😀");
    window.dispatchEvent(new CustomEvent("chatterly:emoji_recents:changed"));
    window.dispatchEvent(new StorageEvent("storage", { key: LS_RECENTS_KEY }));
    expect(seen).toHaveBeenCalledTimes(3);
    unsubscribe();
    pushRecent("🔥");
    window.dispatchEvent(new StorageEvent("storage", { key: LS_RECENTS_KEY }));
    expect(seen).toHaveBeenCalledTimes(3);
  });
});

describe("buildQuickRow", () => {
  it.each<[string, string[], number, string[]]>([
    ["no recents -> defaults", [], 8, [...QUICK_EMOJIS]],
    ["recents first, defaults fill without dupes", ["🔥", "🐶"], 5, ["🔥", "🐶", "❤️", "😍", "👍"]],
    ["duplicate recents collapse", ["🐶", "🐶", "🐱"], 3, ["🐶", "🐱", "❤️"]],
    ["recents beyond the slots are cut", ["a", "b", "c", "d"], 2, ["a", "b"]],
    ["0 slots", ["🐶"], 0, []],
  ])("%s", (_, recents, slots, want) => {
    expect(buildQuickRow(recents, slots)).toEqual(want);
  });
});
