import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useTrailingDebounce } from "@/hooks/useTrailingDebounce";

describe("useTrailingDebounce", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());
  const hook = () => renderHook(({ v }) => useTrailingDebounce(v, 250, (s) => !s), { initialProps: { v: "" } });

  it("holds the last settled value until the input rests, then takes it once", () => {
    const h = hook();
    for (const v of ["a", "ab", "abc"]) { h.rerender({ v }); act(() => { vi.advanceTimersByTime(100); }); }
    expect(h.result.current).toBe("");
    act(() => { vi.advanceTimersByTime(250); });
    expect(h.result.current).toBe("abc");
  });

  it("an accepted value (a cleared box) applies at once, and the next typing debounces from it", () => {
    const h = hook();
    h.rerender({ v: "abc" });
    act(() => { vi.advanceTimersByTime(250); });
    h.rerender({ v: "" });
    expect(h.result.current).toBe("");
    h.rerender({ v: "x" });
    expect(h.result.current).toBe("");
    act(() => { vi.advanceTimersByTime(250); });
    expect(h.result.current).toBe("x");
  });
});
