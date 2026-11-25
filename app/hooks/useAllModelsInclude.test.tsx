import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, renderHook } from "@testing-library/react";

const STORAGE_KEY = "chatterly:allModelsExclude";
const LEGACY_KEY = "chatterly:allModelsInclude";

async function freshHook() {
  const mod = await import("@/hooks/useAllModelsInclude");
  return mod.useAllModelsInclude;
}

beforeEach(() => {
  vi.resetModules();
  window.localStorage.clear();
});
afterEach(() => { cleanup(); });

describe("useAllModelsInclude exclude-list semantics", () => {
  it("includes everything by default (nothing stored)", async () => {
    const useAllModelsInclude = await freshHook();
    const { result } = renderHook(() => useAllModelsInclude());
    expect(result.current.excluded.size).toBe(0);
    expect(result.current.isIncluded("anyone")).toBe(true);
  });

  it("toggle excludes; toggling back re-includes and clears storage", async () => {
    const useAllModelsInclude = await freshHook();
    const { result } = renderHook(() => useAllModelsInclude());

    act(() => result.current.toggle("a"));
    expect(result.current.isIncluded("a")).toBe(false);
    expect(result.current.isIncluded("b")).toBe(true);
    expect(JSON.parse(window.localStorage.getItem(STORAGE_KEY)!)).toEqual(["a"]);

    act(() => result.current.toggle("a"));
    expect(result.current.isIncluded("a")).toBe(true);
    expect(window.localStorage.getItem(STORAGE_KEY)).toBeNull();
  });

  it("a model that appears AFTER an exclusion exists is still included", async () => {
    const useAllModelsInclude = await freshHook();
    const { result } = renderHook(() => useAllModelsInclude());
    act(() => result.current.toggle("old-model"));
    expect(result.current.isIncluded("captured-later")).toBe(true);
  });

  it("deletes the legacy include-list key and ignores its contents", async () => {
    window.localStorage.setItem(LEGACY_KEY, JSON.stringify(["the graded vault"]));
    const useAllModelsInclude = await freshHook();
    const { result } = renderHook(() => useAllModelsInclude());
    expect(result.current.isIncluded("one account")).toBe(true);
    expect(window.localStorage.getItem(LEGACY_KEY)).toBeNull();
  });

  it("keeps two hook instances in sync through the change event", async () => {
    const useAllModelsInclude = await freshHook();
    const first = renderHook(() => useAllModelsInclude());
    const second = renderHook(() => useAllModelsInclude());
    act(() => first.result.current.toggle("x"));
    expect(second.result.current.isIncluded("x")).toBe(false);
  });

  it("includeAll clears every exclusion, even for unlisted accounts", async () => {
    const useAllModelsInclude = await freshHook();
    const { result } = renderHook(() => useAllModelsInclude());
    act(() => result.current.excludeAll(["a", "b", "session-dropped"]));
    expect(result.current.isIncluded("a")).toBe(false);

    act(() => result.current.includeAll());
    expect(result.current.excluded.size).toBe(0);
    expect(result.current.isIncluded("session-dropped")).toBe(true);
    expect(window.localStorage.getItem(STORAGE_KEY)).toBeNull();
  });

  it("excludeAll adds on top of existing exclusions", async () => {
    const useAllModelsInclude = await freshHook();
    const { result } = renderHook(() => useAllModelsInclude());
    act(() => result.current.toggle("already-out"));
    act(() => result.current.excludeAll(["a", "b"]));
    const stored = new Set(JSON.parse(window.localStorage.getItem(STORAGE_KEY)!));
    expect(stored).toEqual(new Set(["already-out", "a", "b"]));
  });

  it("two rapid toggles both land (no stale-state clobber)", async () => {
    const useAllModelsInclude = await freshHook();
    const { result } = renderHook(() => useAllModelsInclude());
    const staleToggle = result.current.toggle;
    act(() => {
      staleToggle("a");
      staleToggle("b");
    });
    const stored = new Set(JSON.parse(window.localStorage.getItem(STORAGE_KEY)!));
    expect(stored).toEqual(new Set(["a", "b"]));
  });
});
