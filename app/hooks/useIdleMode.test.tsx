import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { focusManager, QueryClientProvider } from "@tanstack/react-query";

const bus = vi.hoisted(() => ({ pause: vi.fn(), resume: vi.fn() }));
vi.mock("@/lib/events", () => ({ eventBus: bus }));

import { makeTestQueryClient } from "@/test-utils";
import { IDLE_AFTER_MS, IDLE_CHECK_MS, useIdleMode } from "./useIdleMode";

function mount() {
  const qc = makeTestQueryClient();
  const refetch = vi.spyOn(qc, "refetchQueries").mockResolvedValue();
  const view = renderHook(() => useIdleMode(), {
    wrapper: ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={qc}>{children}</QueryClientProvider>
    ),
  });
  return { ...view, refetch };
}

describe("useIdleMode", () => {
  beforeEach(() => { vi.useFakeTimers(); bus.pause.mockClear(); bus.resume.mockClear(); });
  afterEach(() => { focusManager.setFocused(undefined); vi.useRealTimers(); });

  it("goes idle after IDLE_AFTER_MS with no input: stream closed, polls paused", () => {
    const { result } = mount();
    act(() => { vi.advanceTimersByTime(IDLE_AFTER_MS - IDLE_CHECK_MS); });
    expect(result.current).toBe(false);
    act(() => { vi.advanceTimersByTime(IDLE_CHECK_MS); });
    expect(result.current).toBe(true);
    expect(bus.pause).toHaveBeenCalledTimes(1);
    expect(focusManager.isFocused()).toBe(false);
  });

  it("input keeps it awake", () => {
    const { result } = mount();
    act(() => { vi.advanceTimersByTime(IDLE_AFTER_MS - IDLE_CHECK_MS); });
    fireEvent.keyDown(window);
    act(() => { vi.advanceTimersByTime(IDLE_AFTER_MS - IDLE_CHECK_MS); });
    expect(result.current).toBe(false);
    expect(bus.pause).not.toHaveBeenCalled();
  });

  it("the next input resumes: stream reopened, polls back, stale queries refetched", () => {
    const { result, refetch } = mount();
    act(() => { vi.advanceTimersByTime(IDLE_AFTER_MS); });
    expect(result.current).toBe(true);
    act(() => { fireEvent.pointerDown(window); });
    expect(result.current).toBe(false);
    expect(bus.resume).toHaveBeenCalledTimes(1);
    expect(focusManager.isFocused()).toBe(true);
    expect(refetch).toHaveBeenCalledWith({ type: "active", stale: true });
  });

  it("unmounting while idle resumes", () => {
    const { unmount } = mount();
    act(() => { vi.advanceTimersByTime(IDLE_AFTER_MS); });
    unmount();
    expect(bus.resume).toHaveBeenCalledTimes(1);
  });
});
