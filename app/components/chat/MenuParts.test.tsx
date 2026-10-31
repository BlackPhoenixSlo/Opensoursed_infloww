import { afterEach, describe, expect, it, vi } from "vitest";
import { act, renderHook } from "@testing-library/react";

import { useMenuStatus } from "./MenuParts";

afterEach(() => vi.useRealTimers());

describe("useMenuStatus", () => {
  it("a second flash gets its full 2.5 s (the first one's timer no longer wipes it)", () => {
    vi.useFakeTimers();
    const { result } = renderHook(() => useMenuStatus());
    act(() => result.current.flash(true, "one"));
    act(() => vi.advanceTimersByTime(2000));
    act(() => result.current.flash(false, "two"));
    act(() => vi.advanceTimersByTime(1000)); // the first timer's 2.5 s are up
    expect(result.current.status).toEqual({ ok: false, msg: "two" });
    act(() => vi.advanceTimersByTime(1500));
    expect(result.current.status).toBeNull();
  });
});
