/**
 * fanTyping — the relay's `chat_typing` push marks one Creator's chat with a
 * Fan as typing for a few seconds; the Fan's message ends it.
 *
 * Fixture identifiers are invented (this repo mirrors to a public one).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, renderHook } from "@testing-library/react";

import { applyTypingEvent, TYPING_MS, useFanTyping } from "./fanTyping";

const A = "100000001";
const FAN = 200000001;

beforeEach(() => vi.useFakeTimers());
afterEach(() => {
  vi.runOnlyPendingTimers();
  vi.useRealTimers();
});

describe("fanTyping", () => {
  it("shows typing for that Creator's chat only, until it lapses", () => {
    const h = renderHook(() => useFanTyping(A, FAN));
    const other = renderHook(() => useFanTyping("100000002", FAN));
    expect(h.result.current).toBe(false);

    act(() => applyTypingEvent({ chat_typing: { fan_id: FAN }, __account_id: A }, "chat_typing"));
    expect(h.result.current).toBe(true);
    expect(other.result.current).toBe(false);

    act(() => { vi.advanceTimersByTime(TYPING_MS + 100); });
    expect(h.result.current).toBe(false);
  });

  it("a newer push extends it, and the Fan's message ends it at once", () => {
    const h = renderHook(() => useFanTyping(A, String(FAN)));
    act(() => applyTypingEvent({ chat_typing: { fan_id: FAN }, __account_id: A }, "chat_typing"));
    act(() => { vi.advanceTimersByTime(3_000); });
    act(() => applyTypingEvent({ chat_typing: { fan_id: FAN }, __account_id: A }, "chat_typing"));
    act(() => { vi.advanceTimersByTime(3_000); });
    expect(h.result.current).toBe(true);

    act(() => applyTypingEvent({ api2_chat_message: { id: 1, fromUser: { id: FAN } }, __account_id: A }, "api2_chat_message"));
    expect(h.result.current).toBe(false);
  });

  it("ignores a push without an account or a fan id", () => {
    const h = renderHook(() => useFanTyping(A, FAN));
    act(() => applyTypingEvent({ chat_typing: { fan_id: FAN } }, "chat_typing"));
    act(() => applyTypingEvent({ chat_typing: {}, __account_id: A }, "chat_typing"));
    expect(h.result.current).toBe(false);
  });
});
