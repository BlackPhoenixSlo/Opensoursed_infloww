/**
 * storageSync — the shared localStorage read and the persisted on/off flag.
 *
 * The flag replaced four hand-rolled useState + two-listener hooks; these
 * rows pin what each of them did: the default when nothing is stored, the
 * stored encoding (only the non-default value is written), and that every
 * reader follows a flip from this tab (custom event) and from another tab
 * (`storage`).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, renderHook } from "@testing-library/react";
import { createElement } from "react";
import { renderToString } from "react-dom/server";

import { createStoredFlag, readStorage } from "@/lib/storageSync";
import { readChatSortMode, useChatSortMode } from "@/hooks/useChatSortMode";

const KEY = "test:flag";
const EVENT = "test-flag-change";

beforeEach(() => localStorage.clear());
afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("readStorage", () => {
  it.each([
    ["missing key", "k", null, null],
    ["stored value", "k", "v", "v"],
    ["null key (no employee yet)", null, "v", null],
  ] as const)("%s", (_name, key, stored, want) => {
    if (stored !== null) localStorage.setItem("k", stored);
    expect(readStorage(key)).toBe(want);
  });

  it("SSR / no window → null, without touching localStorage", () => {
    localStorage.setItem("k", "v");
    vi.stubGlobal("window", undefined);
    expect(readStorage("k")).toBeNull();
  });
});

describe("createStoredFlag", () => {
  it.each([
    // def, nothing stored, raw that flips it, written when set to !def
    [true, "0"],
    [false, "1"],
  ] as const)("default %s: missing key reads as default; only %j flips it", (def, raw) => {
    const flag = createStoredFlag(KEY, EVENT, def);
    expect(flag.read()).toBe(def);
    localStorage.setItem(KEY, raw);
    expect(flag.read()).toBe(!def);
    // Any other stored value is not the non-default marker.
    localStorage.setItem(KEY, "garbage");
    expect(flag.read()).toBe(def);
  });

  it.each([
    [true, "0"],
    [false, "1"],
  ] as const)("default %s: setting !def writes %j, setting def removes the key", (def, raw) => {
    const flag = createStoredFlag(KEY, EVENT, def);
    const h = renderHook(() => flag.use());
    act(() => h.result.current[1](!def));
    expect(localStorage.getItem(KEY)).toBe(raw);
    act(() => h.result.current[1](def));
    expect(localStorage.getItem(KEY)).toBeNull();
  });

  it("SSR / no window → default from read and from the server render", () => {
    const flag = createStoredFlag(KEY, EVENT, true);
    localStorage.setItem(KEY, "0");
    expect(renderToString(createElement(() => String(flag.use()[0])))).toBe("true");
    vi.stubGlobal("window", undefined);
    expect(flag.read()).toBe(true);
  });

  it("same tab: a set from one reader re-renders every other reader", () => {
    const flag = createStoredFlag(KEY, EVENT, false);
    const a = renderHook(() => flag.use());
    const b = renderHook(() => flag.use());
    expect(b.result.current[0]).toBe(false);
    act(() => a.result.current[1](true));
    expect(a.result.current[0]).toBe(true);
    expect(b.result.current[0]).toBe(true);
  });

  it("same tab: the custom event alone makes readers re-read", () => {
    const flag = createStoredFlag(KEY, EVENT, true);
    const h = renderHook(() => flag.use());
    localStorage.setItem(KEY, "0");
    act(() => { window.dispatchEvent(new Event(EVENT)); });
    expect(h.result.current[0]).toBe(false);
  });

  it("cross-tab: a `storage` event re-reads what the other tab wrote", () => {
    const flag = createStoredFlag(KEY, EVENT, false);
    const h = renderHook(() => flag.use());
    localStorage.setItem(KEY, "1");
    act(() => { window.dispatchEvent(new StorageEvent("storage", { key: KEY })); });
    expect(h.result.current[0]).toBe(true);
    localStorage.removeItem(KEY);
    act(() => { window.dispatchEvent(new StorageEvent("storage", { key: KEY })); });
    expect(h.result.current[0]).toBe(false);
  });

  it("a write that throws still flips every same-tab reader, until another tab writes", () => {
    const flag = createStoredFlag(KEY, EVENT, false);
    const a = renderHook(() => flag.use());
    const b = renderHook(() => flag.use());
    const setItem = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("QuotaExceededError");
    });
    act(() => a.result.current[1](true));
    expect(localStorage.getItem(KEY)).toBeNull();
    expect(a.result.current[0]).toBe(true);
    expect(b.result.current[0]).toBe(true);
    expect(flag.read()).toBe(true);

    // Another tab writes: the stored value changed under the unsaved choice.
    setItem.mockRestore();
    localStorage.setItem(KEY, "x");
    act(() => { window.dispatchEvent(new StorageEvent("storage", { key: KEY })); });
    expect(b.result.current[0]).toBe(false);
  });
});

describe("useChatSortMode (createStoredValue)", () => {
  const SORT_KEY = "chatterly:chat-sort-mode";

  it.each([
    ["missing key", null, "recent"],
    ["stored mode", "hybrid", "hybrid"],
    ["unknown value", "garbage", "recent"],
  ] as const)("%s → %s", (_name, stored, want) => {
    if (stored !== null) localStorage.setItem(SORT_KEY, stored);
    expect(readChatSortMode()).toBe(want);
  });

  it("every choice is stored, the default's too", () => {
    const h = renderHook(() => useChatSortMode());
    act(() => h.result.current[1]("spend"));
    expect(localStorage.getItem(SORT_KEY)).toBe("spend");
    act(() => h.result.current[1]("recent"));
    expect(localStorage.getItem(SORT_KEY)).toBe("recent");
    expect(h.result.current[0]).toBe("recent");
  });

  it("a write that throws still flips the clicked control", () => {
    const h = renderHook(() => useChatSortMode());
    const setItem = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("QuotaExceededError");
    });
    act(() => h.result.current[1]("spend-unread"));
    expect(localStorage.getItem(SORT_KEY)).toBeNull();
    expect(h.result.current[0]).toBe("spend-unread");
    // Drop the module-level in-memory hold so it cannot leak into other rows.
    setItem.mockRestore();
    act(() => h.result.current[1]("recent"));
  });
});
