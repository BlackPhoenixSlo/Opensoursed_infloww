import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { renderHook } from "@testing-library/react";

import {
  DRAFT_DEBOUNCE_MS, clearDraft, readDraft, stashDraft, usePendingDraft, type DraftEntry,
} from "./pendingDraft";

const K = "chatterly:test-draft:1";
const V = { draft: { a: 1, b: [2] }, base: { a: 0, b: [2] } };
const stored = () => readDraft<{ a: number }>(K);

beforeEach(() => { localStorage.clear(); vi.useFakeTimers(); });
afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe("stash / read / clear", () => {
  it("round-trips an entry", () => {
    const e: DraftEntry<{ a: number }> = { draft: { a: 1 }, base: { a: 0 }, at: 5 };
    expect(stashDraft(K, e)).toBe(true);
    expect(stored()).toEqual(e);
  });

  it("a malformed value reads as no draft", () => {
    localStorage.setItem(K, JSON.stringify({ nope: 1 }));
    expect(stored()).toBeNull();
  });

  it.each<[string, unknown, boolean]>([
    ["no ifEquals", undefined, true],
    ["equal draft", { b: [2], a: 1 }, true], // key order ignored
    ["another draft (edited during the PUT)", { a: 2, b: [2] }, false],
  ])("clear — %s", (_n, ifEquals, gone) => {
    stashDraft(K, { ...V, at: 1 });
    expect(clearDraft(K, ifEquals)).toBe(gone);
    expect(stored() === null).toBe(gone);
  });

  it("quota: the write reports false", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new DOMException("full", "QuotaExceededError"); });
    expect(stashDraft(K, { ...V, at: 1 })).toBe(false);
    expect(stored()).toBeNull();
  });

  it("SSR: no window, every call is a no-op false / null", () => {
    vi.stubGlobal("window", undefined);
    expect(stashDraft(K, { ...V, at: 1 })).toBe(false);
    expect(readDraft(K)).toBeNull();
    expect(clearDraft(K)).toBe(false);
  });
});

describe("usePendingDraft", () => {
  type P = { k: string | null; v: typeof V | null };
  const mount = (k: string | null = K, v: typeof V | null = V) =>
    renderHook(({ k, v }: P) => usePendingDraft(k, v), { initialProps: { k, v } });

  it("debounces: nothing before the delay, the last value after it", () => {
    const h = mount();
    vi.advanceTimersByTime(DRAFT_DEBOUNCE_MS - 1);
    expect(stored()).toBeNull();
    const v2 = { ...V, draft: { a: 7, b: [2] } };
    h.rerender({ k: K, v: v2 });
    vi.advanceTimersByTime(DRAFT_DEBOUNCE_MS - 1);
    expect(stored()).toBeNull();
    vi.advanceTimersByTime(1);
    expect(stored()?.draft).toEqual(v2.draft);
    expect(stored()?.base).toEqual(V.base);
  });

  it.each<[string, () => void]>([
    ["visibilitychange → hidden", () => {
      vi.spyOn(document, "visibilityState", "get").mockReturnValue("hidden");
      document.dispatchEvent(new Event("visibilitychange"));
    }],
    ["pagehide", () => window.dispatchEvent(new Event("pagehide"))],
    ["beforeunload", () => window.dispatchEvent(new Event("beforeunload"))],
  ])("flushes at once on %s", (_n, fire) => {
    mount();
    fire();
    expect(stored()?.draft).toEqual(V.draft);
  });

  it("visibilitychange → visible does not flush", () => {
    mount();
    vi.spyOn(document, "visibilityState", "get").mockReturnValue("visible");
    document.dispatchEvent(new Event("visibilitychange"));
    expect(stored()).toBeNull();
  });

  it("flushes on unmount and on a key change", () => {
    const h = mount();
    h.rerender({ k: null, v: V });
    expect(stored()?.draft).toEqual(V.draft);
    localStorage.clear();
    h.rerender({ k: K, v: V });
    h.unmount();
    expect(stored()?.draft).toEqual(V.draft);
  });

  it("null value = clean: the stash goes, a pending write is dropped", () => {
    stashDraft(K, { ...V, at: 1 });
    const h = mount(K, { ...V, draft: { a: 9, b: [2] } });
    h.rerender({ k: K, v: null });
    expect(stored()).toBeNull();
    vi.advanceTimersByTime(DRAFT_DEBOUNCE_MS * 2);
    expect(stored()).toBeNull();
  });

  it("null key = not loaded: an existing stash is left for the reopen to read", () => {
    stashDraft(K, { ...V, at: 1 });
    const h = mount(null, null);
    vi.advanceTimersByTime(DRAFT_DEBOUNCE_MS * 2);
    h.unmount();
    expect(stored()?.at).toBe(1);
  });
});
